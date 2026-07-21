from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.android_preflight import (  # noqa: E402
    REQUIRED_BUILD_TOOLS,
    default_sdk_roots,
    first_existing_path,
)
from scripts.create_aosp_product_import import detect_apk_signature_schemes  # noqa: E402
from scripts.create_rom_stock_restore_evidence import (  # noqa: E402
    output_path_allowed,
    write_output,
)

JSON_SCHEMA_VERSION = "goffy.rom-release-signing-plan.v1"
DEFAULT_UNSIGNED_APK = Path("android/app/build/outputs/apk/release/app-release-unsigned.apk")
DEFAULT_SIGNED_APK = Path(".goffy-validation/rom-signing/GoffyOS-signed.apk")
DEFAULT_PLAN_OUTPUT = Path(".goffy-validation/rom-signing/release-signing-plan.json")
DEFAULT_KEY_ALIAS = "goffy-release"
KEY_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._@+-]{1,80}$")
PASSWORD_ENV_VARS = ("GOFFY_APK_KEYSTORE_PASS", "GOFFY_APK_KEY_PASS")


@dataclass(frozen=True)
class SigningArtifact:
    path: str
    exists: bool
    sha256: str | None
    byte_count: int | None


@dataclass(frozen=True)
class SigningCommand:
    name: str
    argv: tuple[str, ...]
    mutates_filesystem: bool
    requires_secret_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class RomReleaseSigningPlan:
    schema_version: str
    ok: bool
    status: str
    unsigned_apk: SigningArtifact
    signed_apk: str
    apksigner: str
    keystore: str
    key_alias: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    commands: tuple[SigningCommand, ...]


def create_release_signing_plan(
    *,
    unsigned_apk: Path | None = None,
    signed_apk: Path | None = None,
    keystore: Path | None = None,
    key_alias: str = DEFAULT_KEY_ALIAS,
    apksigner: Path | None = None,
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    sdk_roots: Sequence[Path] | None = None,
) -> RomReleaseSigningPlan:
    unsigned_path = resolve_path(
        DEFAULT_UNSIGNED_APK if unsigned_apk is None else unsigned_apk, root=root
    )
    signed_path = resolve_path(DEFAULT_SIGNED_APK if signed_apk is None else signed_apk, root=root)
    apksigner_path = resolve_apksigner(
        explicit_apksigner=apksigner,
        env=os.environ if env is None else env,
        sdk_roots=sdk_roots,
    )
    keystore_path = keystore.expanduser() if keystore is not None else None

    blockers: list[str] = []
    warnings: list[str] = []
    validate_unsigned_apk(unsigned_path, blockers)
    validate_signed_output(signed_path, blockers, root=root)
    validate_keystore(keystore_path, blockers, root=root)
    validate_key_alias(key_alias, blockers)
    validate_apksigner(apksigner_path, blockers)

    if signed_path.exists():
        warnings.append("signed APK output already exists and would be overwritten by apksigner")

    commands = signing_commands(
        apksigner_path=apksigner_path,
        keystore_path=keystore_path,
        key_alias=key_alias,
        unsigned_apk=unsigned_path,
        signed_apk=signed_path,
    )
    ok = not blockers
    return RomReleaseSigningPlan(
        schema_version=JSON_SCHEMA_VERSION,
        ok=ok,
        status="READY_TO_SIGN" if ok else "BLOCKED_SIGNING_PREREQUISITES",
        unsigned_apk=artifact(unsigned_path),
        signed_apk=str(signed_path),
        apksigner=str(apksigner_path) if apksigner_path is not None else "",
        keystore=str(keystore_path) if keystore_path is not None else "",
        key_alias=key_alias,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        commands=commands,
    )


def resolve_apksigner(
    *,
    explicit_apksigner: Path | None,
    env: Mapping[str, str],
    sdk_roots: Sequence[Path] | None,
) -> Path | None:
    tool_name = "apksigner.bat" if platform.system() == "Windows" else "apksigner"
    if explicit_apksigner is not None:
        return explicit_apksigner.expanduser()

    effective_sdk_roots = default_sdk_roots(env) if sdk_roots is None else sdk_roots
    sdk_root = first_existing_path(effective_sdk_roots)
    candidates: list[Path] = []
    if sdk_root is not None:
        candidates.append(sdk_root / "build-tools" / REQUIRED_BUILD_TOOLS / tool_name)
    path_tool = shutil.which(tool_name)
    if path_tool:
        candidates.append(Path(path_tool))
    for candidate in candidates:
        expanded = candidate.expanduser()
        if expanded.is_file() and os.access(expanded, os.X_OK):
            return expanded
    return candidates[0] if candidates else None


def validate_unsigned_apk(path: Path, blockers: list[str]) -> None:
    if path.suffix != ".apk":
        blockers.append("unsigned GOFFY release artifact must be an APK")
    if "debug" in path.name.lower():
        blockers.append("unsigned GOFFY release artifact must not be a debug APK")
    if not path.name.endswith("-unsigned.apk"):
        blockers.append("unsigned GOFFY release artifact must end with -unsigned.apk")
    if not path.is_file():
        blockers.append("unsigned GOFFY release artifact is missing; run Android assembleRelease")
    elif path.stat().st_size <= 0:
        blockers.append("unsigned GOFFY release artifact must not be empty")
    elif detect_apk_signature_schemes(path):
        blockers.append("unsigned GOFFY release artifact must not already be APK-signed")
    elif not zipfile.is_zipfile(path):
        blockers.append("unsigned GOFFY release artifact must be a valid APK/ZIP container")


def validate_signed_output(path: Path, blockers: list[str], *, root: Path) -> None:
    if path.suffix != ".apk":
        blockers.append("signed GOFFY output must be an APK")
    if "debug" in path.name.lower():
        blockers.append("signed GOFFY output must not look like a debug APK")
    if path.name.endswith("-unsigned.apk"):
        blockers.append("signed GOFFY output must not end with -unsigned.apk")
    if not output_path_allowed(path, root=root):
        blockers.append("signed GOFFY output must be under non-symlinked .goffy-validation")


def validate_keystore(path: Path | None, blockers: list[str], *, root: Path) -> None:
    if path is None:
        blockers.append("release keystore path is required and must live outside the repo")
        return
    if not path.is_absolute():
        blockers.append("release keystore path must be absolute")
    resolved = path.resolve() if path.exists() else path.absolute()
    if is_relative_to(resolved, root.resolve()):
        blockers.append("release keystore must not live inside the GOFFY repo")
    if path.suffix not in {".jks", ".keystore"}:
        blockers.append("release keystore should be a .jks or .keystore file")
    if not path.is_file():
        blockers.append("release keystore file is missing")


def validate_key_alias(value: str, blockers: list[str]) -> None:
    if not KEY_ALIAS_PATTERN.fullmatch(value):
        blockers.append("release key alias contains unsupported characters")


def validate_apksigner(path: Path | None, blockers: list[str]) -> None:
    if path is None:
        blockers.append("Android SDK apksigner was not found")
        return
    if path.name not in {"apksigner", "apksigner.bat"}:
        blockers.append("Android SDK apksigner path must be named apksigner")
    if not path.is_file() or not os.access(path, os.X_OK):
        blockers.append("Android SDK apksigner must be an executable file")
    if not is_android_sdk_build_tools_path(path):
        blockers.append("Android SDK apksigner must live under build-tools/<version>")


def is_android_sdk_build_tools_path(path: Path) -> bool:
    expanded = path.expanduser()
    return expanded.parent.parent.name == "build-tools" and bool(expanded.parent.name)


def signing_commands(
    *,
    apksigner_path: Path | None,
    keystore_path: Path | None,
    key_alias: str,
    unsigned_apk: Path,
    signed_apk: Path,
) -> tuple[SigningCommand, ...]:
    apksigner_label = str(apksigner_path) if apksigner_path is not None else "<apksigner>"
    keystore_label = str(keystore_path) if keystore_path is not None else "<outside-repo-keystore>"
    sign_command = SigningCommand(
        name="sign",
        argv=(
            apksigner_label,
            "sign",
            "--ks",
            keystore_label,
            "--ks-key-alias",
            key_alias,
            "--ks-pass",
            f"env:{PASSWORD_ENV_VARS[0]}",
            "--key-pass",
            f"env:{PASSWORD_ENV_VARS[1]}",
            "--out",
            str(signed_apk),
            str(unsigned_apk),
        ),
        mutates_filesystem=True,
        requires_secret_env=PASSWORD_ENV_VARS,
    )
    verify_command = SigningCommand(
        name="verify",
        argv=(
            apksigner_label,
            "verify",
            "--verbose",
            "--print-certs",
            str(signed_apk),
        ),
        mutates_filesystem=False,
    )
    import_command = SigningCommand(
        name="aosp-import-plan",
        argv=(
            ".venv/bin/python",
            "scripts/create_aosp_product_import.py",
            "--aosp-root",
            "<aosp-root>",
            "--apk",
            str(signed_apk),
        ),
        mutates_filesystem=False,
    )
    return (sign_command, verify_command, import_command)


def artifact(path: Path) -> SigningArtifact:
    if not path.is_file():
        return SigningArtifact(path=str(path), exists=False, sha256=None, byte_count=None)
    return SigningArtifact(
        path=str(path),
        exists=True,
        sha256=sha256_file(path),
        byte_count=path.stat().st_size,
    )


def resolve_path(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_json(plan: RomReleaseSigningPlan) -> str:
    return json.dumps(asdict(plan), indent=2) + "\n"


def render_markdown(plan: RomReleaseSigningPlan) -> str:
    lines = [
        "# GOFFY ROM Release Signing Plan",
        "",
        f"- Status: `{plan.status}`",
        f"- OK: `{str(plan.ok).lower()}`",
        "- Secret handling: environment variable names only; passwords are not stored",
        "- Destructive device actions: withheld",
        "",
        "## Artifacts",
        f"- unsigned_apk: `{plan.unsigned_apk.path}`",
        f"- unsigned_apk_sha256: `{plan.unsigned_apk.sha256 or 'missing'}`",
        f"- signed_apk: `{plan.signed_apk}`",
        f"- keystore: `{plan.keystore or 'missing'}`",
        f"- apksigner: `{plan.apksigner or 'missing'}`",
    ]
    if plan.blockers:
        lines.extend(("", "## Blockers"))
        lines.extend(f"- {blocker}" for blocker in plan.blockers)
    if plan.warnings:
        lines.extend(("", "## Warnings"))
        lines.extend(f"- {warning}" for warning in plan.warnings)
    lines.extend(("", "## Commands"))
    for command in plan.commands:
        mutation = "writes files" if command.mutates_filesystem else "read-only"
        secret_env = (
            f"; requires env {', '.join(command.requires_secret_env)}"
            if command.requires_secret_env
            else ""
        )
        lines.append(f"- {command.name} ({mutation}{secret_env}):")
        lines.append(f"  `{format_command(command.argv)}`")
    lines.append("")
    return "\n".join(lines)


def format_command(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(item) for item in argv)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a safe GOFFY ROM release APK signing plan without signing.",
    )
    parser.add_argument("--unsigned-apk", type=Path, default=DEFAULT_UNSIGNED_APK)
    parser.add_argument("--signed-apk", type=Path, default=DEFAULT_SIGNED_APK)
    parser.add_argument("--keystore", type=Path)
    parser.add_argument("--key-alias", default=DEFAULT_KEY_ALIAS)
    parser.add_argument("--apksigner", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PLAN_OUTPUT,
        help="Optional JSON output path under .goffy-validation.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print instead of writing JSON.")
    parser.add_argument("--markdown", action="store_true", help="Render Markdown instead of JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.markdown and not args.stdout:
            raise ValueError("--markdown requires --stdout")
        plan = create_release_signing_plan(
            unsigned_apk=args.unsigned_apk,
            signed_apk=args.signed_apk,
            keystore=args.keystore,
            key_alias=args.key_alias,
            apksigner=args.apksigner,
        )
        text = render_markdown(plan) if args.markdown else render_json(plan)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, render_json(plan))
            print(f"wrote ROM release signing plan to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if plan.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
