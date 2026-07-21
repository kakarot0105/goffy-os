from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    DeviceTarget,
    StepStatus,
    adb_command,
    default_command_runner,
    display_adb_command,
    resolve_device_target,
    trusted_adb_path,
)

JSON_SCHEMA_VERSION = "goffy.rom-feasibility-probe.v1"
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
MAX_PROPERTY_VALUE_CHARS = 512
MAX_TEXT_ARTIFACT_CHARS = 32_000
DSU_PACKAGE = "com.android.dynsystem"
DSU_START_INSTALL_ACTION = "android.os.image.action.START_INSTALL"
DSU_PLACEHOLDER_URI = "file:///storage/emulated/0/Download/goffy-dsu-placeholder.gz"

ROM_PROPERTIES = (
    "ro.product.model",
    "ro.product.device",
    "ro.product.name",
    "ro.product.manufacturer",
    "ro.product.brand",
    "ro.product.board",
    "ro.hardware",
    "ro.board.platform",
    "ro.soc.manufacturer",
    "ro.soc.model",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.version.incremental",
    "ro.build.version.security_patch",
    "ro.build.fingerprint",
    "ro.boot.hardware",
    "ro.boot.slot_suffix",
    "ro.boot.flash.locked",
    "ro.boot.vbmeta.device_state",
    "ro.boot.verifiedbootstate",
    "ro.boot.dynamic_partitions",
    "ro.boot.product.hardware.sku",
    "ro.oem_unlock_supported",
    "sys.oem_unlock_allowed",
    "ro.treble.enabled",
    "ro.apex.updatable",
    "ro.carrier",
    "ro.vendor.build.security_patch",
)


class RomPath(StrEnum):
    BLOCKED_LOCKED_BOOTLOADER = "BLOCKED_LOCKED_BOOTLOADER"
    GSI_OR_DSU_FIRST = "GSI_OR_DSU_FIRST"
    FULL_DEVICE_TREE_REQUIRED = "FULL_DEVICE_TREE_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RomProbeStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    detail: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class RomFeasibilityReport:
    schema_version: str
    ok: bool
    generated_at: str
    device: dict[str, str]
    boot: dict[str, str]
    platform: dict[str, str]
    treble: dict[str, str]
    dsu: dict[str, str]
    rom_path: RomPath
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]
    properties: dict[str, str]
    steps: tuple[RomProbeStep, ...]


def build_report(
    *,
    root: Path = ROOT,
    device_serial: str | None = None,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 30,
) -> RomFeasibilityReport:
    generated_at = datetime.now(UTC).isoformat()
    adb = trusted_adb_path()
    if adb is None:
        return blocked_report(
            generated_at=generated_at,
            blocker="trusted Android SDK adb executable is unavailable",
            remediation="Install Android SDK platform-tools and rerun the read-only probe.",
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        requested_serial=device_serial,
    )
    if target is None:
        return blocked_report(
            generated_at=generated_at,
            blocker=target_step.detail,
            remediation=target_step.remediation,
            steps=(from_device_step(target_step),),
        )

    properties, property_steps = collect_properties(
        root=root,
        adb=adb,
        target=target,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    vndk_isolated, vndk_step = collect_vndk_isolation(
        root=root,
        adb=adb,
        target=target,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    dsu, dsu_steps = collect_dsu_readiness(
        root=root,
        adb=adb,
        target=target,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    steps = (from_device_step(target_step), *property_steps, vndk_step, *dsu_steps)

    device = {
        "model": properties.get("ro.product.model", ""),
        "codename": properties.get("ro.product.device", ""),
        "product": properties.get("ro.product.name", ""),
        "manufacturer": properties.get("ro.product.manufacturer", ""),
        "brand": properties.get("ro.product.brand", ""),
        "carrier": properties.get("ro.carrier", ""),
    }
    platform = {
        "board": properties.get("ro.product.board", ""),
        "hardware": properties.get("ro.hardware", ""),
        "boot_hardware": properties.get("ro.boot.hardware", ""),
        "board_platform": properties.get("ro.board.platform", ""),
        "soc_manufacturer": properties.get("ro.soc.manufacturer", ""),
        "soc_model": properties.get("ro.soc.model", ""),
        "android_release": properties.get("ro.build.version.release", ""),
        "sdk": properties.get("ro.build.version.sdk", ""),
        "build_incremental": properties.get("ro.build.version.incremental", ""),
        "build_security_patch": properties.get("ro.build.version.security_patch", ""),
        "vendor_security_patch": properties.get("ro.vendor.build.security_patch", ""),
    }
    boot = {
        "slot_suffix": properties.get("ro.boot.slot_suffix", ""),
        "flash_locked": properties.get("ro.boot.flash.locked", ""),
        "vbmeta_device_state": properties.get("ro.boot.vbmeta.device_state", ""),
        "verified_boot_state": properties.get("ro.boot.verifiedbootstate", ""),
        "oem_unlock_supported": properties.get("ro.oem_unlock_supported", ""),
        "oem_unlock_allowed": properties.get("sys.oem_unlock_allowed", ""),
    }
    treble = {
        "enabled": properties.get("ro.treble.enabled", ""),
        "dynamic_partitions": properties.get("ro.boot.dynamic_partitions", ""),
        "apex_updatable": properties.get("ro.apex.updatable", ""),
        "vndk_namespace_default_isolated": vndk_isolated,
    }
    rom_path, blockers, warnings, next_steps = classify_rom_path(
        properties=properties,
        vndk_isolated=vndk_isolated,
        dsu=dsu,
    )
    return RomFeasibilityReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not blockers,
        generated_at=generated_at,
        device=device,
        boot=boot,
        platform=platform,
        treble=treble,
        dsu=dsu,
        rom_path=rom_path,
        blockers=blockers,
        warnings=warnings,
        next_steps=next_steps,
        properties=properties,
        steps=steps,
    )


def blocked_report(
    *,
    generated_at: str,
    blocker: str,
    remediation: str,
    steps: tuple[RomProbeStep, ...] = (),
) -> RomFeasibilityReport:
    return RomFeasibilityReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=False,
        generated_at=generated_at,
        device={},
        boot={},
        platform={},
        treble={},
        dsu={},
        rom_path=RomPath.UNKNOWN,
        blockers=(blocker,),
        warnings=(),
        next_steps=(remediation,),
        properties={},
        steps=steps,
    )


def collect_properties(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[dict[str, str], tuple[RomProbeStep, ...]]:
    properties: dict[str, str] = {}
    steps: list[RomProbeStep] = []
    for prop in ROM_PROPERTIES:
        result = runner(adb_command(adb, target, "shell", "getprop", prop), root, timeout_seconds)
        display = display_adb_command(adb, "shell", "getprop", prop)
        if result.exit_code != 0:
            steps.append(
                RomProbeStep(
                    name=f"Read {prop}",
                    status=StepStatus.FAIL,
                    command=display,
                    detail="getprop failed",
                )
            )
            properties[prop] = ""
            continue
        properties[prop] = bounded_value(result.stdout)
        steps.append(
            RomProbeStep(
                name=f"Read {prop}",
                status=StepStatus.OK,
                command=display,
                detail="read allowlisted property",
            )
        )
    return properties, tuple(steps)


def collect_vndk_isolation(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[str, RomProbeStep]:
    display = display_adb_command(
        adb,
        "shell",
        "cat",
        "/system/etc/ld.config.version_identifier.txt",
    )
    result = runner(
        adb_command(adb, target, "shell", "cat", "/system/etc/ld.config.version_identifier.txt"),
        root,
        timeout_seconds,
    )
    if result.exit_code != 0:
        return "", RomProbeStep(
            name="Read VNDK isolation config",
            status=StepStatus.FAIL,
            command=display,
            detail="VNDK config file unavailable",
        )
    isolated = parse_vndk_isolated(result.stdout[-MAX_TEXT_ARTIFACT_CHARS:])
    return isolated, RomProbeStep(
        name="Read VNDK isolation config",
        status=StepStatus.OK if isolated else StepStatus.FAIL,
        command=display,
        detail=(
            f"namespace.default.isolated={isolated}"
            if isolated
            else "namespace.default.isolated not found"
        ),
    )


def collect_dsu_readiness(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[dict[str, str], tuple[RomProbeStep, ...]]:
    package_display = display_adb_command(adb, "shell", "pm", "path", DSU_PACKAGE)
    package_result = runner(
        adb_command(adb, target, "shell", "pm", "path", DSU_PACKAGE),
        root,
        timeout_seconds,
    )
    package_path = bounded_value(package_result.stdout.removeprefix("package:"))
    package_present = package_result.exit_code == 0 and bool(package_path)

    resolve_display = display_adb_command(
        adb,
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        DSU_START_INSTALL_ACTION,
        "-d",
        DSU_PLACEHOLDER_URI,
    )
    resolve_result = runner(
        adb_command(
            adb,
            target,
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            DSU_START_INSTALL_ACTION,
            "-d",
            DSU_PLACEHOLDER_URI,
        ),
        root,
        timeout_seconds,
    )
    start_install_activity = parse_resolved_activity(resolve_result.stdout)
    start_install_resolves = resolve_result.exit_code == 0 and bool(start_install_activity)

    dsu = {
        "package_present": bool_text(package_present),
        "package_path": package_path if package_present else "",
        "start_install_resolves": bool_text(start_install_resolves),
        "start_install_activity": start_install_activity,
    }
    steps = (
        RomProbeStep(
            name="Check DSU package",
            status=StepStatus.OK if package_present else StepStatus.FAIL,
            command=package_display,
            detail="Dynamic System package present" if package_present else "DSU package not found",
        ),
        RomProbeStep(
            name="Resolve DSU START_INSTALL activity",
            status=StepStatus.OK if start_install_resolves else StepStatus.FAIL,
            command=resolve_display,
            detail=(
                f"resolved {start_install_activity}"
                if start_install_resolves
                else "START_INSTALL activity not resolved"
            ),
        ),
    )
    return dsu, steps


def parse_resolved_activity(text: str) -> str:
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if "/" in line and not line.startswith("priority="):
            return bounded_value(line)
    return ""


def parse_vndk_isolated(text: str) -> str:
    in_vendor = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_vendor = line == "[vendor]"
            continue
        if in_vendor and line.startswith("namespace.default.isolated"):
            _, _, value = line.partition("=")
            return value.strip()
    return ""


def classify_rom_path(
    *,
    properties: dict[str, str],
    vndk_isolated: str,
    dsu: dict[str, str],
) -> tuple[RomPath, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = []
    warnings: list[str] = []
    next_steps: list[str] = []

    flash_locked = properties.get("ro.boot.flash.locked", "")
    vbmeta_state = properties.get("ro.boot.vbmeta.device_state", "")
    verified_state = properties.get("ro.boot.verifiedbootstate", "")
    treble_enabled = properties.get("ro.treble.enabled", "")
    dynamic_partitions = properties.get("ro.boot.dynamic_partitions", "")
    sdk = int_or_none(properties.get("ro.build.version.sdk", ""))
    locked_bootloader = flash_locked == "1" or vbmeta_state == "locked"

    if locked_bootloader:
        blockers.append(
            "bootloader is currently locked; do not flash, root, or boot custom images yet"
        )
        next_steps.append(
            "Manually verify OEM unlocking in Developer options and Motorola "
            "unlock-token eligibility."
        )
    elif flash_locked == "0" or vbmeta_state == "unlocked":
        warnings.append(
            "bootloader appears unlocked; flashing still needs stock restore images first"
        )
    else:
        warnings.append("bootloader lock state is unknown from allowlisted properties")

    if verified_state and verified_state != "green":
        warnings.append(f"verified boot state is {verified_state}; document before ROM work")
    if treble_enabled != "true":
        blockers.append("Treble support is not confirmed; GSI path is unsafe")
    if dynamic_partitions != "true":
        warnings.append("dynamic partitions are not confirmed; DSU/GSI path may be unavailable")
    if sdk is not None and sdk < 28:
        blockers.append("device SDK is below API 28; modern GSI assumptions do not hold")
    if vndk_isolated == "false":
        warnings.append("VNDK isolation is false; cross-version GSI compatibility may be limited")
    elif not vndk_isolated:
        warnings.append("VNDK isolation could not be confirmed from system config")
    if dsu.get("package_present") != "true":
        warnings.append("Android Dynamic System package is not visible")
    if dsu.get("start_install_resolves") != "true":
        warnings.append("Android DSU START_INSTALL activity is not resolvable")

    if blockers and locked_bootloader:
        path = RomPath.BLOCKED_LOCKED_BOOTLOADER
    elif blockers:
        path = RomPath.UNKNOWN
        if not next_steps:
            next_steps.append("Resolve blockers, then rerun this read-only probe.")
    elif treble_enabled == "true" and dynamic_partitions == "true":
        path = RomPath.GSI_OR_DSU_FIRST
        next_steps.extend(
            (
                "Back up user data and obtain exact stock firmware/recovery path "
                "for kansas before any unlock.",
                "Use DSU/GSI as the first ROM experiment before building a full device tree.",
                "Track modem, IMS, camera, fingerprint, sensors, and battery "
                "behavior as acceptance gates.",
            )
        )
    else:
        path = RomPath.FULL_DEVICE_TREE_REQUIRED
        next_steps.append(
            "Research kernel, vendor, device tree, and stock firmware availability "
            "before ROM build work."
        )

    if not next_steps:
        next_steps.append("Resolve blockers, then rerun this read-only probe.")
    return path, tuple(blockers), tuple(warnings), tuple(next_steps)


def int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def bounded_value(value: str) -> str:
    return value.strip()[:MAX_PROPERTY_VALUE_CHARS]


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def from_device_step(step: object) -> RomProbeStep:
    return RomProbeStep(
        name=getattr(step, "name", "Verify device target"),
        status=getattr(step, "status", StepStatus.FAIL),
        command=tuple(getattr(step, "command", ())),
        detail=getattr(step, "detail", ""),
        remediation=getattr(step, "remediation", ""),
    )


def render_text(report: RomFeasibilityReport) -> str:
    lines = [
        "GOFFY ROM feasibility probe",
        f"schema: {report.schema_version}",
        f"overall: {'PASS' if report.ok else 'BLOCKED'}",
        f"rom path: {report.rom_path}",
    ]
    if report.device:
        lines.append(
            "device: "
            f"{report.device.get('model', '<unknown>')} / "
            f"{report.device.get('codename', '<unknown>')} / "
            f"{report.platform.get('soc_model', '<unknown>')}"
        )
    if report.dsu:
        lines.append(
            "dsu: "
            f"package={report.dsu.get('package_present', 'unknown')} "
            f"start_install={report.dsu.get('start_install_resolves', 'unknown')}"
        )
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    lines.append("next steps:")
    lines.extend(f"- {step}" for step in report.next_steps)
    return "\n".join(lines)


def render_json(report: RomFeasibilityReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only GOFFY ROM feasibility probe for the connected Moto G.",
    )
    parser.add_argument("--device-serial", help="ADB serial when more than one device is attached.")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        device_serial=args.device_serial,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
