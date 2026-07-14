from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_JDK_MAJOR = 17
REQUIRED_ANDROID_PLATFORM = "android-36"
REQUIRED_BUILD_TOOLS = "36.0.0"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ABSOLUTE_POSIX_PATH = re.compile(r"(?<![>\w])/(?!\s)(?:[^;\n\r,)]+)")
OTHER_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    remediation: str


def java_major_from_release(release_file: Path) -> int | None:
    if not release_file.is_file():
        return None
    match = re.search(
        r'^JAVA_VERSION="(?P<major>\d+)(?:[._][^"]*)?"$',
        release_file.read_text(encoding="utf-8", errors="replace"),
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    return int(match.group("major"))


def java_home_from_bin(java_bin: str | None) -> Path | None:
    if java_bin is None:
        return None
    path = Path(java_bin).expanduser()
    if path.name not in {"java", "java.exe"}:
        return None
    resolved = path.resolve()
    if len(resolved.parents) < 2:
        return None
    return resolved.parents[1]


def default_jdk_homes() -> list[Path]:
    homes: list[Path] = [
        Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
        Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
    ]
    homes.extend(Path("/Library/Java/JavaVirtualMachines").glob("*/Contents/Home"))
    return homes


def check_jdk(
    env: Mapping[str, str],
    known_jdk_homes: Sequence[Path],
    java_on_path: str | None,
) -> Check:
    java_home = env.get("JAVA_HOME")
    candidates: list[tuple[str, Path]] = []
    if java_home:
        candidates.append(("JAVA_HOME", Path(java_home).expanduser()))
    else:
        path_home = java_home_from_bin(java_on_path)
        if path_home is not None:
            candidates.append(("PATH", path_home))
        candidates.extend(("known location", path.expanduser()) for path in known_jdk_homes)

    inspected: list[str] = []
    for source, candidate in candidates:
        release_file = candidate / "release"
        major = java_major_from_release(release_file)
        inspected.append(f"{source}: {candidate}")
        if major is None:
            continue
        if major >= REQUIRED_JDK_MAJOR:
            return Check(
                name="JDK",
                ok=True,
                detail=f"found Java {major} at {candidate}",
                remediation="",
            )
        return Check(
            name="JDK",
            ok=False,
            detail=(
                f"{source} points to Java {major} at {candidate}; "
                f"Java {REQUIRED_JDK_MAJOR}+ is required"
            ),
            remediation="Install JDK 17+ and set JAVA_HOME to that JDK home.",
        )

    detail = "no inspectable JDK release file found"
    if inspected:
        detail += f" ({'; '.join(inspected)})"
    return Check(
        name="JDK",
        ok=False,
        detail=detail,
        remediation=(
            "Install JDK 17+ or Android Studio, then export JAVA_HOME before running Gradle."
        ),
    )


def default_sdk_roots(env: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = env.get(key)
        if value:
            roots.append(Path(value).expanduser())
    home = env.get("HOME")
    if home:
        roots.append(Path(home).expanduser() / "Library" / "Android" / "sdk")
    return roots


def first_existing_path(paths: Sequence[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def check_sdk_root(env: Mapping[str, str], sdk_roots: Sequence[Path]) -> Check:
    android_home = env.get("ANDROID_HOME")
    android_sdk_root = env.get("ANDROID_SDK_ROOT")
    if (
        android_home
        and android_sdk_root
        and Path(android_home).resolve() != Path(android_sdk_root).resolve()
    ):
        return Check(
            name="Android SDK root",
            ok=False,
            detail="ANDROID_HOME and ANDROID_SDK_ROOT point to different directories",
            remediation=(
                "Set both variables to the same Android SDK root, or set only ANDROID_HOME."
            ),
        )
    root = first_existing_path(sdk_roots)
    if root is None:
        return Check(
            name="Android SDK root",
            ok=False,
            detail="no Android SDK root found",
            remediation="Install Android SDK 36 and export ANDROID_HOME to the SDK directory.",
        )
    return Check(
        name="Android SDK root",
        ok=True,
        detail=str(root),
        remediation="",
    )


def check_sdk_component(
    sdk_root: Path | None,
    relative_path: str,
    label: str,
    remediation: str,
) -> Check:
    if sdk_root is None:
        return Check(
            name=label,
            ok=False,
            detail="Android SDK root is unavailable",
            remediation=remediation,
        )
    component = sdk_root / relative_path
    return Check(
        name=label,
        ok=component.exists(),
        detail=str(component),
        remediation="" if component.exists() else remediation,
    )


def check_adb(sdk_root: Path | None, adb_on_path: str | None) -> Check:
    adb = resolve_adb(sdk_root, adb_on_path)
    return Check(
        name="adb",
        ok=adb is not None,
        detail=str(adb) if adb else "adb not found",
        remediation="Install Android SDK Platform Tools and ensure adb is on PATH.",
    )


def resolve_adb(sdk_root: Path | None, adb_on_path: str | None) -> Path | None:
    adb_name = "adb.exe" if platform.system() == "Windows" else "adb"
    candidates: list[Path] = []
    if sdk_root is not None:
        candidates.append(sdk_root / "platform-tools" / adb_name)
    if adb_on_path:
        candidates.append(Path(adb_on_path))
    for candidate in candidates:
        expanded = candidate.expanduser()
        if not expanded.is_absolute():
            continue
        resolved = expanded.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def check_gradle_wrapper(root: Path) -> Check:
    wrapper = root / "android" / ("gradlew.bat" if platform.system() == "Windows" else "gradlew")
    ok = wrapper.is_file()
    if platform.system() != "Windows":
        ok = ok and os.access(wrapper, os.X_OK)
    return Check(
        name="Gradle wrapper",
        ok=ok,
        detail=str(wrapper),
        remediation="Restore android/gradlew and ensure it is executable.",
    )


def collect_checks(
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    known_jdk_homes: Sequence[Path] | None = None,
    sdk_roots: Sequence[Path] | None = None,
    java_on_path: str | None = None,
    adb_on_path: str | None = None,
    use_path_tools: bool = True,
) -> list[Check]:
    effective_env = os.environ if env is None else env
    effective_jdk_homes = default_jdk_homes() if known_jdk_homes is None else known_jdk_homes
    effective_sdk_roots = default_sdk_roots(effective_env) if sdk_roots is None else sdk_roots
    java_path = shutil.which("java") if java_on_path is None and use_path_tools else java_on_path
    adb_path = shutil.which("adb") if adb_on_path is None and use_path_tools else adb_on_path

    sdk_root = first_existing_path(effective_sdk_roots)
    return [
        check_jdk(effective_env, effective_jdk_homes, java_path),
        check_sdk_root(effective_env, effective_sdk_roots),
        check_sdk_component(
            sdk_root,
            f"platforms/{REQUIRED_ANDROID_PLATFORM}",
            f"Android SDK Platform {REQUIRED_ANDROID_PLATFORM}",
            "Install Android SDK Platform 36 in Android Studio SDK Manager.",
        ),
        check_sdk_component(
            sdk_root,
            f"build-tools/{REQUIRED_BUILD_TOOLS}",
            f"Android SDK Build Tools {REQUIRED_BUILD_TOOLS}",
            "Install Android SDK Build Tools 36.0.0 in Android Studio SDK Manager.",
        ),
        check_adb(sdk_root, adb_path),
        check_gradle_wrapper(root),
    ]


def render_report(checks: Sequence[Check]) -> str:
    lines = ["Android preflight"]
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {safe_text(check.detail)}")
        if not check.ok:
            lines.append(f"       fix: {safe_text(check.remediation)}")
    if all(check.ok for check in checks):
        lines.append("Ready for Android Gradle validation.")
    else:
        lines.append("Install the missing prerequisites before running Android Gradle validation.")
    return "\n".join(lines)


def safe_text(value: str) -> str:
    redacted = value.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
    redacted = ABSOLUTE_POSIX_PATH.sub("<path>", redacted)
    redacted = ANSI_ESCAPE.sub("", redacted)
    redacted = redacted.replace("\\", "\\\\")
    redacted = redacted.replace("\r", "\\r").replace("\n", "\\n")
    return OTHER_CONTROL.sub(lambda match: f"\\x{ord(match.group(0)):02x}", redacted)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        default=str(ROOT),
        help="Repository root containing android/gradlew.",
    )
    args = parser.parse_args(argv)
    checks = collect_checks(root=Path(args.repo_root).resolve())
    print(render_report(checks))
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
