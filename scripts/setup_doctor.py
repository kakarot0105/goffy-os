from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.android_preflight import Check as AndroidCheck  # noqa: E402
from scripts.android_preflight import collect_checks as collect_android_checks  # noqa: E402

MIN_PYTHON = (3, 12)
DEV_MODULES = {
    "build": "build",
    "fastapi": "fastapi",
    "httpx2": "httpx",
    "jsonschema": "jsonschema",
    "mcp": "mcp",
    "mypy": "mypy",
    "pydantic": "pydantic",
    "pytest": "pytest",
    "pytest-asyncio": "pytest_asyncio",
    "pyyaml": "yaml",
    "ruff": "ruff",
    "segno": "segno",
    "uvicorn": "uvicorn",
    "websockets": "websockets",
}
JSON_SCHEMA_VERSION = "goffy.setup-doctor.v1"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ABSOLUTE_POSIX_PATH = re.compile(r"(?<![>\w])/(?:[^;\n\r,)]+)")
OTHER_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class DoctorCheck:
    category: str
    name: str
    ok: bool
    detail: str
    remediation: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


ModuleFinder = Callable[[str], bool]
AndroidCollector = Callable[[Path], Sequence[AndroidCheck]]


def default_module_finder(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def collect_python_checks(
    *,
    version_info: tuple[int, int, int] | None = None,
    executable: str = sys.executable,
    module_finder: ModuleFinder = default_module_finder,
) -> list[DoctorCheck]:
    version = version_info if version_info is not None else sys.version_info[:3]
    version_label = ".".join(str(part) for part in version)
    python_ok = version[:2] >= MIN_PYTHON
    checks = [
        DoctorCheck(
            category="python",
            name="Python runtime",
            ok=python_ok,
            detail=f"Python {version_label} at {executable}",
            remediation=(
                "" if python_ok else "Install Python 3.12+ and recreate the GOFFY virtualenv."
            ),
        )
    ]

    missing: list[str] = []
    for package, module in DEV_MODULES.items():
        if not module_finder(module):
            missing.append(package)

    checks.append(
        DoctorCheck(
            category="python",
            name="Python dev dependencies",
            ok=not missing,
            detail=(
                "all required dev modules importable"
                if not missing
                else f"missing modules for packages: {', '.join(sorted(missing))}"
            ),
            remediation=(
                ""
                if not missing
                else "Run `.venv/bin/python -m pip install -e '.[dev]'` from the repo root."
            ),
        )
    )
    return checks


def collect_doctor_report(
    *,
    root: Path = ROOT,
    module_finder: ModuleFinder = default_module_finder,
    android_collector: AndroidCollector = lambda root: collect_android_checks(root=root),
) -> DoctorReport:
    checks = collect_python_checks(module_finder=module_finder)
    checks.extend(
        DoctorCheck(
            category="android",
            name=check.name,
            ok=check.ok,
            detail=check.detail,
            remediation="" if check.ok else check.remediation,
        )
        for check in android_collector(root)
    )
    return DoctorReport(tuple(checks), repo_root=root.resolve())


def redact_paths(value: str, *, report: DoctorReport) -> str:
    redacted = value
    replacements = [
        (str(report.repo_root), "<repo>"),
        (str(report.home), "<home>"),
    ]
    for source, replacement in replacements:
        if source:
            redacted = redacted.replace(source, replacement)
    return ABSOLUTE_POSIX_PATH.sub("<path>", redacted)


def safe_text(value: str, *, report: DoctorReport) -> str:
    sanitized = redact_paths(value, report=report)
    sanitized = ANSI_ESCAPE.sub("", sanitized)
    sanitized = sanitized.replace("\\", "\\\\")
    sanitized = sanitized.replace("\r", "\\r").replace("\n", "\\n")
    return OTHER_CONTROL.sub(lambda match: f"\\x{ord(match.group(0)):02x}", sanitized)


def render_text(report: DoctorReport) -> str:
    lines = ["GOFFY setup doctor"]
    current_category = ""
    for check in report.checks:
        if check.category != current_category:
            current_category = check.category
            lines.append("")
            lines.append(f"{current_category.upper()}")
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {safe_text(check.detail, report=report)}")
        if not check.ok:
            lines.append(f"       fix: {safe_text(check.remediation, report=report)}")
    lines.append("")
    if report.ok:
        lines.append(
            "Ready for full local verification with `.venv/bin/python scripts/verify_all.py`."
        )
    else:
        lines.append(
            "Resolve failed checks before expecting full Android verification or "
            "physical-device tests."
        )
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    payload: Mapping[str, object] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "checks": [
            asdict(
                DoctorCheck(
                    category=check.category,
                    name=check.name,
                    ok=check.ok,
                    detail=redact_paths(check.detail, report=report),
                    remediation=redact_paths(check.remediation, report=report),
                )
            )
            for check in report.checks
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    report = collect_doctor_report(root=Path(args.repo_root).resolve())
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
