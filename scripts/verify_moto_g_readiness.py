from __future__ import annotations

import argparse
import http.client
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

from goffy_protocol import PROTOCOL_VERSION  # noqa: E402
from scripts.setup_doctor import (  # noqa: E402
    DoctorCheck,
    DoctorReport,
    collect_doctor_report,
    redact_paths,
    safe_text,
)

JSON_SCHEMA_VERSION = "goffy.moto-g-readiness.v1"
HUB_HEALTH_URL = "http://127.0.0.1:8787/health"
DEBUG_APK_RELATIVE_PATH = Path("android/app/build/outputs/apk/debug/app-debug.apk")
MAX_HUB_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class HubProbeResult:
    status_code: int
    body: str


@dataclass(frozen=True)
class ReadinessCheck:
    category: str
    name: str
    ok: bool
    detail: str
    remediation: str


@dataclass(frozen=True)
class ReadinessReport:
    checks: tuple[ReadinessCheck, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


DoctorCollector = Callable[[Path], DoctorReport]
HubProbe = Callable[[float], HubProbeResult]


def default_doctor_collector(root: Path) -> DoctorReport:
    return collect_doctor_report(root=root, include_python=False, include_device=True)


def default_hub_probe(timeout_seconds: float) -> HubProbeResult:
    connection = http.client.HTTPConnection("127.0.0.1", 8787, timeout=timeout_seconds)
    try:
        connection.request("GET", "/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(4096).decode("utf-8", errors="replace")
        return HubProbeResult(status_code=response.status, body=body)
    finally:
        connection.close()


def doctor_to_readiness(check: DoctorCheck) -> ReadinessCheck:
    return ReadinessCheck(
        category=check.category,
        name=check.name,
        ok=check.ok,
        detail=check.detail,
        remediation=check.remediation,
    )


def collect_hub_checks(
    *,
    probe: HubProbe = default_hub_probe,
    timeout_seconds: float = 2.0,
) -> list[ReadinessCheck]:
    try:
        result = probe(timeout_seconds)
    except (OSError, TimeoutError, ValueError, http.client.HTTPException) as exc:
        return [
            ReadinessCheck(
                category="hub",
                name="Hub health endpoint",
                ok=False,
                detail=f"unreachable on 127.0.0.1:8787 ({exc.__class__.__name__})",
                remediation="Start GOFFY Hub locally, then rerun this readiness check.",
            )
        ]

    if result.status_code != 200:
        return [
            ReadinessCheck(
                category="hub",
                name="Hub health endpoint",
                ok=False,
                detail=f"HTTP {result.status_code}",
                remediation="Start GOFFY Hub locally and confirm `/health` returns HTTP 200.",
            )
        ]

    try:
        decoded: Any = json.loads(result.body)
    except json.JSONDecodeError:
        return [
            ReadinessCheck(
                category="hub",
                name="Hub health endpoint",
                ok=False,
                detail="HTTP 200 but response was not valid JSON",
                remediation="Restart GOFFY Hub and inspect its local logs.",
            )
        ]
    if not isinstance(decoded, dict):
        return [
            ReadinessCheck(
                category="hub",
                name="Hub health endpoint",
                ok=False,
                detail="HTTP 200 but response JSON was not an object",
                remediation="Restart GOFFY Hub and inspect its local logs.",
            )
        ]
    payload: dict[str, Any] = decoded

    status = payload.get("status")
    healthy_count = payload.get("healthyToolCount")
    unavailable_count = payload.get("unavailableToolCount")
    tool_access = payload.get("toolAccess")
    protocol_version = payload.get("protocolVersion")
    healthy_int = healthy_count if type(healthy_count) is int else None
    unavailable_int = unavailable_count if type(unavailable_count) is int else None

    endpoint_ok = status in {"ok", "degraded"}
    protocol_ok = protocol_version == PROTOCOL_VERSION
    if healthy_int is None or unavailable_int is None:
        tools_ok = False
        tool_health_detail = "tool health counters invalid"
    else:
        tools_ok = status == "ok" and healthy_int > 0 and unavailable_int == 0
        tool_health_detail = f"healthy:{healthy_int}; unavailable:{unavailable_int}"
    access_ok = tool_access == "enabled"
    status_detail = f"status:{status}" if endpoint_ok else "status invalid"
    protocol_detail = (
        f"protocolVersion:{PROTOCOL_VERSION}" if protocol_ok else "protocolVersion mismatch"
    )
    access_detail = (
        f"toolAccess:{tool_access}"
        if tool_access in {"enabled", "disabled"}
        else "toolAccess invalid"
    )
    return [
        ReadinessCheck(
            category="hub",
            name="Hub health endpoint",
            ok=endpoint_ok,
            detail=status_detail,
            remediation="Restart GOFFY Hub and confirm `/health` returns the typed health schema.",
        ),
        ReadinessCheck(
            category="hub",
            name="Hub protocol version",
            ok=protocol_ok,
            detail=protocol_detail,
            remediation=(
                f"Start a Hub that reports GOFFY protocol {PROTOCOL_VERSION} before "
                "running Mac status from the phone."
            ),
        ),
        ReadinessCheck(
            category="hub",
            name="Hub tool health",
            ok=tools_ok,
            detail=tool_health_detail,
            remediation="Wait for Hub tool health to recover or inspect local Hub logs.",
        ),
        ReadinessCheck(
            category="hub",
            name="Hub tool access",
            ok=access_ok,
            detail=access_detail,
            remediation=(
                "Start the Hub with a development token or complete loopback pairing before "
                "running Mac status from the phone."
            ),
        ),
    ]


def collect_debug_apk_check(root: Path) -> ReadinessCheck:
    apk = root / DEBUG_APK_RELATIVE_PATH
    ok = apk.is_file() and apk.stat().st_size > 0
    return ReadinessCheck(
        category="android",
        name="Debug APK",
        ok=ok,
        detail=str(apk) if ok else "debug APK is unavailable",
        remediation=(
            "" if ok else "Run Android Gradle assembly on a machine with JDK 17 and Android SDK 36."
        ),
    )


def collect_readiness_report(
    *,
    root: Path = ROOT,
    doctor_collector: DoctorCollector = default_doctor_collector,
    hub_probe: HubProbe = default_hub_probe,
    hub_timeout_seconds: float = 2.0,
) -> ReadinessReport:
    doctor_report = doctor_collector(root)
    checks = [doctor_to_readiness(check) for check in doctor_report.checks]
    checks.extend(collect_hub_checks(probe=hub_probe, timeout_seconds=hub_timeout_seconds))
    checks.append(collect_debug_apk_check(root))
    return ReadinessReport(
        checks=tuple(checks),
        repo_root=root.resolve(),
        home=Path.home(),
    )


def doctor_report_for_redaction(report: ReadinessReport) -> DoctorReport:
    return DoctorReport(checks=(), repo_root=report.repo_root, home=report.home)


def render_text(report: ReadinessReport) -> str:
    redaction_report = doctor_report_for_redaction(report)
    lines = ["GOFFY Moto G readiness"]
    current_category = ""
    for check in report.checks:
        if check.category != current_category:
            current_category = check.category
            lines.append("")
            lines.append(current_category.upper())
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {safe_text(check.detail, report=redaction_report)}")
        if not check.ok:
            lines.append(f"       fix: {safe_text(check.remediation, report=redaction_report)}")
    lines.append("")
    if report.ok:
        lines.append("Ready to run the documented Moto G physical validation checklist.")
    else:
        lines.append(
            "Resolve failed readiness checks before treating Moto G validation as complete."
        )
    return "\n".join(lines)


def render_json(report: ReadinessReport) -> str:
    redaction_report = doctor_report_for_redaction(report)
    payload: dict[str, object] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "checks": [
            asdict(
                ReadinessCheck(
                    category=check.category,
                    name=check.name,
                    ok=check.ok,
                    detail=redact_paths(check.detail, report=redaction_report),
                    remediation=redact_paths(check.remediation, report=redaction_report),
                )
            )
            for check in report.checks
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def bounded_hub_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_HUB_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"timeout must be finite, greater than 0, and at most "
            f"{MAX_HUB_TIMEOUT_SECONDS:g} seconds"
        )
    return timeout


def existing_directory(value: str) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise argparse.ArgumentTypeError("repo root must be an existing directory")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--hub-timeout-seconds",
        type=bounded_hub_timeout,
        default=2.0,
        help="Bounded timeout for the localhost Hub health probe.",
    )
    args = parser.parse_args(argv)

    report = collect_readiness_report(
        root=args.repo_root,
        hub_timeout_seconds=args.hub_timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
