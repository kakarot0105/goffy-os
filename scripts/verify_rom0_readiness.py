from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_aosp_product_import import (  # noqa: E402
    AospProductImportError,
    create_aosp_product_import_report,
)
from scripts.create_rom_dsu_preflight_evidence import (  # noqa: E402
    load_dsu_preflight_evidence,
)
from scripts.create_rom_fastboot_evidence import (  # noqa: E402
    ABSOLUTE_POSIX_PATH,
    ABSOLUTE_WINDOWS_PATH,
    FastbootStatus,
    command_label_allowed,
    parse_fastboot_devices,
)
from scripts.create_rom_fastboot_evidence import (  # noqa: E402
    JSON_SCHEMA_VERSION as FASTBOOT_SCHEMA_VERSION,
)
from scripts.create_rom_gsi_candidate_evidence import (  # noqa: E402
    ARTIFACT_FAMILY_ARCHITECTURES,
    CANDIDATE_NAME_PATTERN,
    GsiCandidateStatus,
    build_matches_android_release,
    candidate_name_contains_action_word,
    parse_gsi_artifact_name,
    validate_official_download_url,
    validate_official_source_url,
)
from scripts.create_rom_gsi_candidate_evidence import (  # noqa: E402
    JSON_SCHEMA_VERSION as GSI_CANDIDATE_SCHEMA_VERSION,
)
from scripts.create_rom_release_signing_plan import (  # noqa: E402
    JSON_SCHEMA_VERSION as SIGNING_PLAN_SCHEMA_VERSION,
)
from scripts.create_rom_release_signing_plan import (  # noqa: E402
    validate_apksigner,
    validate_key_alias,
    validate_keystore,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    ARCHIVE_NAME_PATTERN,
    SHA256_PATTERN,
    load_manual_gates,
    validate_manual_gates,
)
from scripts.validate_rom_product_overlay import validate_rom_product_overlay  # noqa: E402
from scripts.validate_rom_system_app import validate_rom_system_app  # noqa: E402
from scripts.verify_rom_release_apk import JSON_SCHEMA_VERSION as APK_SCHEMA_VERSION  # noqa: E402

READINESS_SCHEMA_VERSION = "goffy.rom0-readiness.v1"
DEFAULT_AOSP_ROOT = Path("<aosp-root>")
EXPECTED_CODENAME = "kansas"
EXPECTED_PRODUCT = "kansas_g_sys"
TARGET_DEVICE_EVIDENCE_KEYS = (
    "model",
    "codename",
    "product",
    "hardware_sku",
    "build_fingerprint",
    "carrier",
)
GSI_TOP_LEVEL_KEYS = frozenset(
    ("schema_version", "generated_at", "ok", "status", "candidate", "artifact", "source", "safety")
)
GSI_CANDIDATE_KEYS = frozenset(
    ("name", "android_release", "architecture", "image_kind", "license_note_code")
)
GSI_ARTIFACT_KEYS = frozenset(("artifact_name", "byte_count", "sha256", "expected_sha256"))
GSI_SOURCE_KEYS = frozenset(("source_url", "download_url"))
GSI_SAFETY_KEYS = frozenset(
    (
        "execution_authority",
        "device_mutation",
        "authorization",
        "destructive_actions",
        "local_path_redacted",
    )
)
FASTBOOT_TOP_LEVEL_KEYS = frozenset(
    (
        "schema_version",
        "generated_at",
        "ok",
        "status",
        "destructive_actions",
        "host",
        "manual_bootloader_check",
        "commands",
        "blockers",
        "warnings",
    )
)
FASTBOOT_HOST_KEYS = frozenset(("fastboot", "fastboot_path", "fastboot_version"))
FASTBOOT_MANUAL_CHECK_KEYS = frozenset(
    (
        "requested",
        "bootloader_device_visible",
        "bootloader_device_count",
        "serials_redacted",
    )
)
FASTBOOT_COMMAND_KEYS = frozenset(("label", "exit_code", "timed_out", "stdout", "stderr"))
SAFE_FASTBOOT_WARNINGS = frozenset(
    ("manual bootloader visibility was not checked; do not reboot automatically",)
)
SAFE_FASTBOOT_BLOCKERS = frozenset(
    (
        "trusted Android SDK fastboot executable is unavailable",
        "fastboot --version failed",
        "fastboot version could not be parsed",
        "fastboot devices failed",
        "no manually booted fastboot device is visible",
    )
)
REDACTED_FASTBOOT_DEVICE_LINE_PATTERN = re.compile(r"^<device-serial>\s+fastboot(?:\s|$)")


class Rom0ReadinessStatus(StrEnum):
    BLOCKED = "BLOCKED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


@dataclass(frozen=True)
class ReadinessSection:
    name: str
    ok: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    evidence: dict[str, str] | None = None


@dataclass(frozen=True)
class Rom0ReadinessReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: Rom0ReadinessStatus
    destructive_actions: str
    sections: tuple[ReadinessSection, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class FastbootCommandSummary:
    successful_labels: frozenset[str]
    redacted_fastboot_device_count: int


def build_readiness_report(
    *,
    probe_json: Path | None,
    manual_gates_json: Path | None,
    signed_apk: Path | None,
    fastboot_evidence_json: Path | None = None,
    gsi_candidate_evidence_json: Path | None = None,
    dsu_preflight_evidence_json: Path | None = None,
    signing_plan_json: Path | None = None,
    apk_verification_json: Path | None = None,
    aosp_root: Path = DEFAULT_AOSP_ROOT,
    root: Path = ROOT,
    evidence_root: Path = ROOT,
) -> Rom0ReadinessReport:
    rom_descriptors = validate_rom_descriptors(root=root)
    rom_probe = validate_probe_evidence(probe_json)
    manual_gates = validate_manual_gate_evidence(
        manual_gates_json,
        evidence_root=evidence_root,
        probe_evidence=rom_probe.evidence or {},
    )
    sections = (
        rom_descriptors,
        rom_probe,
        manual_gates,
        validate_fastboot_evidence(
            fastboot_evidence_json,
            require_manual_visibility=True,
        ),
        validate_gsi_candidate_evidence(gsi_candidate_evidence_json),
        validate_dsu_preflight_evidence(dsu_preflight_evidence_json),
        validate_release_signing_plan_evidence(
            signing_plan_json,
            signed_apk=signed_apk,
            root=root,
        ),
        validate_release_apk_verification_evidence(
            apk_verification_json,
            signed_apk=signed_apk,
        ),
        validate_aosp_import_evidence(signed_apk=signed_apk, aosp_root=aosp_root, root=root),
    )
    ok = all(section.ok for section in sections)
    return Rom0ReadinessReport(
        schema_version=READINESS_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=ok,
        status=Rom0ReadinessStatus.READY_FOR_HUMAN_REVIEW if ok else Rom0ReadinessStatus.BLOCKED,
        destructive_actions="withheld",
        sections=sections,
        next_steps=next_steps(sections),
    )


def validate_rom_descriptors(*, root: Path) -> ReadinessSection:
    blockers = [
        *(f"system-app: {finding}" for finding in validate_rom_system_app(root=root)),
        *(f"product-overlay: {finding}" for finding in validate_rom_product_overlay(root=root)),
    ]
    return ReadinessSection(
        name="rom_descriptors",
        ok=not blockers,
        blockers=tuple(blockers),
        evidence={"system_app": "validated", "product_overlay": "validated"}
        if not blockers
        else {},
    )


def validate_probe_evidence(path: Path | None) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="rom_probe",
            ok=False,
            blockers=("ROM feasibility probe JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="rom_probe", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    warnings: list[str] = list(string_items(payload.get("warnings")))
    if payload.get("schema_version") != PROBE_SCHEMA_VERSION:
        blockers.append("ROM feasibility probe schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.extend(
            string_items(payload.get("blockers")) or ["ROM feasibility probe is not OK"]
        )
    device = mapping_value(payload.get("device"))
    boot = mapping_value(payload.get("boot"))
    treble = mapping_value(payload.get("treble"))
    dsu = mapping_value(payload.get("dsu"))
    properties = mapping_value(payload.get("properties"))
    if device.get("codename") != EXPECTED_CODENAME:
        blockers.append("ROM probe codename does not match kansas")
    if device.get("product") != EXPECTED_PRODUCT:
        blockers.append("ROM probe product does not match kansas_g_sys")
    if boot.get("flash_locked") != "0" or boot.get("vbmeta_device_state") != "unlocked":
        blockers.append("ROM probe does not show an unlocked bootloader")
    if treble.get("enabled") != "true":
        blockers.append("ROM probe does not show Treble enabled")
    if treble.get("dynamic_partitions") != "true":
        blockers.append("ROM probe does not show dynamic partitions")
    if dsu_package_present(dsu) != "true":
        warnings.append("ROM probe did not confirm DSU package availability")
    evidence = {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "hardware_sku": device.get("hardware_sku", ""),
        "build_fingerprint": properties.get("ro.build.fingerprint", ""),
        "carrier": device.get("carrier", ""),
        "bootloader": boot.get("vbmeta_device_state", ""),
        "rom_path": str(payload.get("rom_path", "")),
    }
    for key in TARGET_DEVICE_EVIDENCE_KEYS:
        if not evidence[key]:
            blockers.append(f"ROM probe target_device.{key} is missing")

    return ReadinessSection(
        name="rom_probe",
        ok=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(dict.fromkeys(warnings)),
        evidence=evidence,
    )


def validate_manual_gate_evidence(
    path: Path | None,
    *,
    evidence_root: Path,
    probe_evidence: Mapping[str, str] | None = None,
) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="manual_gates",
            ok=False,
            blockers=("ROM-0 manual gate evidence JSON was not supplied",),
        )
    try:
        payload = load_manual_gates(path)
        report = validate_manual_gates(
            payload,
            root=evidence_root,
            expected_target_device=probe_evidence,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="manual_gates", ok=False, blockers=(str(exc),))
    blockers = list(report.blockers)
    return ReadinessSection(
        name="manual_gates",
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=report.warnings,
        evidence=report.accepted_evidence,
    )


def validate_fastboot_evidence(
    path: Path | None,
    *,
    require_manual_visibility: bool = False,
) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="fastboot_evidence",
            ok=False,
            blockers=("ROM fastboot evidence JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="fastboot_evidence", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    warnings = filtered_fastboot_messages(
        string_items(payload.get("warnings")),
        label="warnings",
        blockers=blockers,
    )
    append_unsupported_key_blockers(
        payload,
        allowed=FASTBOOT_TOP_LEVEL_KEYS,
        label="fastboot evidence",
        blockers=blockers,
    )
    if payload.get("schema_version") != FASTBOOT_SCHEMA_VERSION:
        blockers.append("ROM fastboot evidence schema_version mismatch")
    payload_blockers = filtered_fastboot_messages(
        string_items(payload.get("blockers")),
        label="blockers",
        blockers=blockers,
    )
    if payload.get("ok") is not True:
        blockers.extend(payload_blockers or ["ROM fastboot evidence is not OK"])
    elif payload_blockers:
        blockers.append("ROM fastboot evidence blockers must be empty when ok is true")
    if payload.get("destructive_actions") != "withheld":
        blockers.append("ROM fastboot evidence destructive_actions must be withheld")

    status = str(payload.get("status", ""))
    if status not in {FastbootStatus.HOST_READY, FastbootStatus.MANUAL_BOOTLOADER_VISIBLE}:
        blockers.append(
            "ROM fastboot evidence status must be HOST_READY or MANUAL_BOOTLOADER_VISIBLE"
        )

    host = mapping_value(payload.get("host"))
    append_unsupported_key_blockers(
        host,
        allowed=FASTBOOT_HOST_KEYS,
        label="fastboot host evidence",
        blockers=blockers,
    )
    if host.get("fastboot") != "available":
        blockers.append("ROM fastboot evidence must show trusted fastboot available")
    if host.get("fastboot_path") != "<android-sdk>/platform-tools/fastboot":
        blockers.append("ROM fastboot evidence fastboot_path must be redacted")
    if not host.get("fastboot_version"):
        blockers.append("ROM fastboot evidence fastboot_version is missing")

    manual = validate_fastboot_manual_check(payload.get("manual_bootloader_check"), blockers)
    command_summary = validate_fastboot_commands(payload.get("commands"), blockers)
    validate_fastboot_status_consistency(
        status=status,
        manual=manual,
        command_summary=command_summary,
        blockers=blockers,
    )
    if require_manual_visibility and status != FastbootStatus.MANUAL_BOOTLOADER_VISIBLE:
        blockers.append("manual bootloader-mode fastboot visibility has not been recorded")
    if not manual.get("requested"):
        warnings.append("manual bootloader-mode fastboot visibility is still pending")

    return ReadinessSection(
        name="fastboot_evidence",
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        evidence={
            "status": status,
            "fastboot_version": host.get("fastboot_version", ""),
            "manual_bootloader_check_requested": str(manual.get("requested", False)).lower(),
            "bootloader_device_visible": str(
                manual.get("bootloader_device_visible", False)
            ).lower(),
            "bootloader_device_count": str(manual.get("bootloader_device_count", 0)),
        },
    )


def validate_fastboot_manual_check(
    value: object,
    blockers: list[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        blockers.append("ROM fastboot evidence manual_bootloader_check must be an object")
        return {}
    append_unsupported_key_blockers(
        value,
        allowed=FASTBOOT_MANUAL_CHECK_KEYS,
        label="fastboot manual bootloader evidence",
        blockers=blockers,
    )
    if value.get("serials_redacted") is not True:
        blockers.append("ROM fastboot evidence serials_redacted must be true")
    requested = value.get("requested")
    visible = value.get("bootloader_device_visible")
    count = value.get("bootloader_device_count")
    if not isinstance(requested, bool):
        blockers.append("ROM fastboot evidence requested must be boolean")
    if not isinstance(visible, bool):
        blockers.append("ROM fastboot evidence bootloader_device_visible must be boolean")
    if not isinstance(count, int) or count < 0:
        blockers.append(
            "ROM fastboot evidence bootloader_device_count must be a non-negative integer"
        )
    if requested is True and visible is not True:
        blockers.append("ROM fastboot evidence requested manual bootloader check found no device")
    if visible is True and (not isinstance(count, int) or count < 1):
        blockers.append("ROM fastboot evidence visible bootloader device count must be positive")
    return value


def validate_fastboot_status_consistency(
    *,
    status: str,
    manual: Mapping[str, object],
    command_summary: FastbootCommandSummary,
    blockers: list[str],
) -> None:
    requested = manual.get("requested")
    visible = manual.get("bootloader_device_visible")
    count = manual.get("bootloader_device_count")
    devices_count = command_summary.redacted_fastboot_device_count
    successful_labels = command_summary.successful_labels

    if status == FastbootStatus.HOST_READY:
        if requested is not False or visible is not False or count != 0:
            blockers.append("HOST_READY fastboot evidence must not claim bootloader visibility")
        if "fastboot devices" in successful_labels or devices_count:
            blockers.append("HOST_READY fastboot evidence must not include fastboot devices proof")
    elif status == FastbootStatus.MANUAL_BOOTLOADER_VISIBLE:
        if requested is not True or visible is not True or not isinstance(count, int) or count < 1:
            blockers.append(
                "MANUAL_BOOTLOADER_VISIBLE fastboot evidence requires visible manual check fields"
            )
        if "fastboot devices" not in successful_labels:
            blockers.append(
                "MANUAL_BOOTLOADER_VISIBLE fastboot evidence requires fastboot devices proof"
            )
        if devices_count < 1:
            blockers.append(
                "MANUAL_BOOTLOADER_VISIBLE fastboot evidence requires redacted device output"
            )
        elif isinstance(count, int) and count != devices_count:
            blockers.append(
                "MANUAL_BOOTLOADER_VISIBLE fastboot device count must match redacted output"
            )


def validate_fastboot_commands(value: object, blockers: list[str]) -> FastbootCommandSummary:
    if not isinstance(value, list) or not value:
        blockers.append("ROM fastboot evidence commands must include read-only command results")
        return FastbootCommandSummary(frozenset(), 0)
    labels: list[str] = []
    successful_labels: set[str] = set()
    redacted_fastboot_device_count = 0
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            blockers.append(f"ROM fastboot evidence command {index} must be an object")
            continue
        append_unsupported_key_blockers(
            item,
            allowed=FASTBOOT_COMMAND_KEYS,
            label=f"fastboot command {index}",
            blockers=blockers,
        )
        label = str(item.get("label", ""))
        normalized_label = " ".join(label.lower().split())
        labels.append(normalized_label)
        label_allowed = command_label_allowed(label)
        exit_clean = item.get("exit_code") == 0
        did_not_timeout = item.get("timed_out") is False
        if not label_allowed:
            blockers.append(f"ROM fastboot evidence command {index} is not read-only")
        if not exit_clean:
            blockers.append(f"ROM fastboot evidence command {index} did not exit cleanly")
        if not did_not_timeout:
            blockers.append(f"ROM fastboot evidence command {index} timed out")
        if label_allowed and exit_clean and did_not_timeout:
            successful_labels.add(normalized_label)
        for stream_name in ("stdout", "stderr"):
            stream = str(item.get(stream_name, ""))
            if contains_unredacted_fastboot_output(stream):
                blockers.append(
                    f"ROM fastboot evidence command {index} {stream_name} is not fully redacted"
                )
            if normalized_label == "fastboot devices":
                redacted_fastboot_device_count += count_redacted_fastboot_devices(stream)
    if "fastboot --version" not in labels:
        blockers.append("ROM fastboot evidence must include fastboot --version")
    return FastbootCommandSummary(
        successful_labels=frozenset(successful_labels),
        redacted_fastboot_device_count=redacted_fastboot_device_count,
    )


def contains_unredacted_fastboot_output(text: str) -> bool:
    return (
        bool(parse_fastboot_devices(text))
        or ABSOLUTE_POSIX_PATH.search(text) is not None
        or ABSOLUTE_WINDOWS_PATH.search(text) is not None
    )


def filtered_fastboot_messages(
    messages: tuple[str, ...],
    *,
    label: str,
    blockers: list[str],
) -> list[str]:
    safe_messages: list[str] = []
    allowed_messages = (
        SAFE_FASTBOOT_WARNINGS
        if label == "warnings"
        else SAFE_FASTBOOT_BLOCKERS
        if label == "blockers"
        else frozenset()
    )
    for message in messages:
        if message not in allowed_messages or contains_unredacted_fastboot_output(message):
            blockers.append(f"ROM fastboot evidence {label} contain unsupported or unredacted text")
        else:
            safe_messages.append(message)
    return safe_messages


def count_redacted_fastboot_devices(text: str) -> int:
    return sum(
        1 for line in text.splitlines() if REDACTED_FASTBOOT_DEVICE_LINE_PATTERN.match(line.strip())
    )


def validate_gsi_candidate_evidence(path: Path | None) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="gsi_candidate",
            ok=False,
            blockers=("ROM GSI candidate evidence JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="gsi_candidate", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    append_unsupported_key_blockers(
        payload,
        allowed=GSI_TOP_LEVEL_KEYS,
        label="GSI candidate evidence",
        blockers=blockers,
    )
    if payload.get("schema_version") != GSI_CANDIDATE_SCHEMA_VERSION:
        blockers.append("ROM GSI candidate evidence schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.append("ROM GSI candidate evidence is not OK")
    if payload.get("status") != GsiCandidateStatus.ARTIFACT_CHECKSUM_VERIFIED:
        blockers.append("ROM GSI candidate evidence status is not ARTIFACT_CHECKSUM_VERIFIED")

    candidate = mapping_value(payload.get("candidate"))
    artifact = mapping_value(payload.get("artifact"))
    source = mapping_value(payload.get("source"))
    safety_payload = payload.get("safety")
    safety = mapping_value(safety_payload)
    validate_gsi_candidate(candidate, blockers)
    validate_gsi_artifact(artifact, blockers)
    validate_gsi_artifact_binding(candidate, artifact, blockers)
    validate_gsi_source(source, artifact_name=artifact.get("artifact_name", ""), blockers=blockers)
    validate_gsi_safety(safety_payload, safety, blockers)

    return ReadinessSection(
        name="gsi_candidate",
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        evidence={
            "status": str(payload.get("status", "")),
            "candidate_name": candidate.get("name", ""),
            "android_release": candidate.get("android_release", ""),
            "architecture": candidate.get("architecture", ""),
            "artifact_name": artifact.get("artifact_name", ""),
            "sha256": artifact.get("sha256", "").lower(),
            "source_url": source.get("source_url", ""),
            "authorization": safety.get("authorization", ""),
        },
    )


def validate_dsu_preflight_evidence(path: Path | None) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="dsu_preflight",
            ok=False,
            blockers=("ROM DSU preflight evidence JSON was not supplied",),
        )
    try:
        evidence = load_dsu_preflight_evidence(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="dsu_preflight", ok=False, blockers=(str(exc),))
    return ReadinessSection(
        name="dsu_preflight",
        ok=True,
        blockers=(),
        warnings=("DSU preflight is non-authorizing and does not prove the GSI will boot",),
        evidence=evidence,
    )


def validate_gsi_candidate(candidate: Mapping[str, str], blockers: list[str]) -> None:
    append_unsupported_key_blockers(
        candidate,
        allowed=GSI_CANDIDATE_KEYS,
        label="GSI candidate",
        blockers=blockers,
    )
    if candidate.get("android_release") != "16":
        blockers.append("GSI candidate Android release must be 16 for the Moto G ROM-0 target")
    if candidate.get("architecture") not in {"arm64", "arm64+gms"}:
        blockers.append("GSI candidate architecture must be arm64 or arm64+gms")
    if candidate.get("image_kind") != "archive":
        blockers.append("GSI candidate image_kind must be archive")
    if candidate.get("license_note_code") != "official_google_gsi_terms":
        blockers.append(
            "GSI candidate license_note_code must acknowledge official Google GSI terms"
        )
    candidate_name = candidate.get("name", "")
    if not candidate_name:
        blockers.append("GSI candidate name is required")
    elif not CANDIDATE_NAME_PATTERN.fullmatch(candidate_name):
        blockers.append("GSI candidate name contains unsupported characters")
    elif candidate_name_contains_action_word(candidate_name):
        blockers.append("GSI candidate name must not contain approval or device-action wording")


def validate_gsi_artifact(artifact: Mapping[str, str], blockers: list[str]) -> None:
    append_unsupported_key_blockers(
        artifact,
        allowed=GSI_ARTIFACT_KEYS,
        label="GSI artifact",
        blockers=blockers,
    )
    artifact_name = artifact.get("artifact_name", "")
    sha256 = artifact.get("sha256", "").lower()
    expected_sha256 = artifact.get("expected_sha256", "").lower()
    if not ARCHIVE_NAME_PATTERN.fullmatch(artifact_name):
        blockers.append("GSI artifact artifact_name must be a filename, not a path")
    if not SHA256_PATTERN.fullmatch(sha256):
        blockers.append("GSI artifact sha256 must be 64 hex characters")
    if not SHA256_PATTERN.fullmatch(expected_sha256):
        blockers.append("GSI artifact expected_sha256 must be 64 hex characters")
    if sha256 and expected_sha256 and sha256 != expected_sha256:
        blockers.append("GSI artifact sha256 must match expected_sha256")
    byte_count = artifact.get("byte_count", "")
    if not byte_count.isdigit() or int(byte_count) <= 0:
        blockers.append("GSI artifact byte_count must be a positive integer")


def validate_gsi_artifact_binding(
    candidate: Mapping[str, str],
    artifact: Mapping[str, str],
    blockers: list[str],
) -> None:
    metadata = parse_gsi_artifact_name(artifact.get("artifact_name", ""))
    if metadata is None:
        blockers.append(
            "GSI artifact artifact_name must match the official Google GSI naming pattern"
        )
        return
    artifact_architecture = ARTIFACT_FAMILY_ARCHITECTURES[metadata["family"].lower()]
    if artifact_architecture != candidate.get("architecture", ""):
        blockers.append("GSI artifact architecture must match GSI candidate architecture")
    if not build_matches_android_release(
        build_id=metadata["build"],
        android_release=candidate.get("android_release", ""),
    ):
        blockers.append("GSI artifact build must match GSI candidate Android release")
    sha256 = artifact.get("sha256", "").lower()
    if sha256 and not sha256.startswith(metadata["sha_prefix"].lower()):
        blockers.append("GSI artifact checksum prefix must match GSI artifact sha256")


def validate_gsi_source(
    source: Mapping[str, str],
    *,
    artifact_name: str,
    blockers: list[str],
) -> None:
    append_unsupported_key_blockers(
        source,
        allowed=GSI_SOURCE_KEYS,
        label="GSI source",
        blockers=blockers,
    )
    blockers.extend(validate_official_source_url(source.get("source_url", "")))
    blockers.extend(
        validate_official_download_url(source.get("download_url", ""), expected_name=artifact_name)
    )


def validate_gsi_safety(
    safety_payload: object,
    safety: Mapping[str, str],
    blockers: list[str],
) -> None:
    append_unsupported_key_blockers(
        safety,
        allowed=GSI_SAFETY_KEYS,
        label="GSI safety",
        blockers=blockers,
    )
    if safety.get("execution_authority") != "OFFLINE_HASH_ONLY":
        blockers.append("GSI safety execution_authority must be OFFLINE_HASH_ONLY")
    if safety.get("device_mutation") != "NONE":
        blockers.append("GSI safety device_mutation must be NONE")
    if safety.get("authorization") != "NON_AUTHORIZING_EVIDENCE":
        blockers.append("GSI safety authorization must be NON_AUTHORIZING_EVIDENCE")
    if safety.get("destructive_actions") != "WITHHELD":
        blockers.append("GSI safety destructive_actions must be WITHHELD")
    if (
        not isinstance(safety_payload, Mapping)
        or safety_payload.get("local_path_redacted") is not True
    ):
        blockers.append("GSI safety local_path_redacted must be true")


def validate_release_signing_plan_evidence(
    path: Path | None,
    *,
    signed_apk: Path | None,
    root: Path = ROOT,
) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="release_signing_plan",
            ok=False,
            blockers=("ROM release signing plan JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="release_signing_plan", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    if payload.get("schema_version") != SIGNING_PLAN_SCHEMA_VERSION:
        blockers.append("ROM release signing plan schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.extend(
            string_items(payload.get("blockers")) or ["ROM release signing plan is not ready"]
        )
    if payload.get("status") != "READY_TO_SIGN":
        blockers.append("ROM release signing plan status is not READY_TO_SIGN")

    planned_signed_apk = str(payload.get("signed_apk", ""))
    if not planned_signed_apk:
        blockers.append("ROM release signing plan is missing signed_apk")
    elif signed_apk is not None and not same_path(planned_signed_apk, signed_apk):
        blockers.append("ROM release signing plan signed_apk does not match supplied APK")

    apksigner_value = str(payload.get("apksigner", ""))
    apksigner_blockers: list[str] = []
    if apksigner_value:
        validate_apksigner(Path(apksigner_value).expanduser(), apksigner_blockers)
    else:
        apksigner_blockers.append("Android SDK apksigner was not found")
    blockers.extend(apksigner_blockers)

    keystore_value = str(payload.get("keystore", ""))
    keystore_blockers: list[str] = []
    if keystore_value:
        validate_keystore(Path(keystore_value).expanduser(), keystore_blockers, root=root)
    else:
        keystore_blockers.append("release keystore path is required and must live outside the repo")
    blockers.extend(keystore_blockers)

    key_alias = str(payload.get("key_alias", ""))
    validate_key_alias(key_alias, blockers)

    unsigned_apk = mapping_value(payload.get("unsigned_apk"))
    evidence = {
        "status": str(payload.get("status", "")),
        "unsigned_apk_sha256": unsigned_apk.get("sha256", ""),
        "signed_apk": planned_signed_apk,
        "apksigner": classified_presence(apksigner_value, apksigner_blockers),
        "keystore": "external"
        if keystore_value and not keystore_blockers
        else classified_presence(keystore_value, keystore_blockers),
        "key_alias": key_alias,
    }
    return ReadinessSection(
        name="release_signing_plan",
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=string_items(payload.get("warnings")),
        evidence=evidence,
    )


def validate_release_apk_verification_evidence(
    path: Path | None,
    *,
    signed_apk: Path | None,
) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="release_apk_verification",
            ok=False,
            blockers=("ROM release APK verification JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="release_apk_verification", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    if payload.get("schema_version") != APK_SCHEMA_VERSION:
        blockers.append("ROM release APK verification schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.extend(
            string_items(payload.get("blockers")) or ["ROM release APK verification is not OK"]
        )
    if payload.get("status") != "VERIFIED":
        blockers.append("ROM release APK verification status is not VERIFIED")

    apk_payload = payload.get("apk")
    apk = mapping_value(apk_payload)
    verified_apk = apk.get("path", "")
    if not verified_apk:
        blockers.append("ROM release APK verification is missing APK path")
    elif signed_apk is not None and not same_path(verified_apk, signed_apk):
        blockers.append("ROM release APK verification APK path does not match supplied APK")

    signature_schemes = string_items(
        apk_payload.get("signature_schemes") if isinstance(apk_payload, Mapping) else None
    )
    if not any(scheme in {"v2", "v3", "v3.1"} for scheme in signature_schemes):
        blockers.append("ROM release APK verification did not record a v2/v3 signature scheme")

    return ReadinessSection(
        name="release_apk_verification",
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=string_items(payload.get("warnings")),
        evidence={
            "apk_sha256": apk.get("sha256", ""),
            "apk_signature_schemes": ",".join(signature_schemes),
            "apk_path": verified_apk,
        },
    )


def validate_aosp_import_evidence(
    *,
    signed_apk: Path | None,
    aosp_root: Path,
    root: Path,
) -> ReadinessSection:
    if signed_apk is None:
        return ReadinessSection(
            name="aosp_import",
            ok=False,
            blockers=("Externally signed GOFFY APK was not supplied",),
        )
    try:
        report = create_aosp_product_import_report(
            aosp_root=aosp_root,
            apk_path=signed_apk,
            repo_root=root,
        )
    except (OSError, ValueError, json.JSONDecodeError, AospProductImportError) as exc:
        return ReadinessSection(name="aosp_import", ok=False, blockers=(str(exc),))
    apk_entry = next(
        (item for item in report.files if item.destination.endswith("GoffyOS.apk")),
        None,
    )
    apk_sha256 = (apk_entry.sha256 or "") if apk_entry else ""
    evidence = {
        "aosp_root": report.aosp_root or "",
        "apk_sha256": apk_sha256,
        "apk_signature_schemes": ",".join(apk_entry.apk_signature_schemes) if apk_entry else "",
    }
    return ReadinessSection(
        name="aosp_import",
        ok=report.safe_to_execute,
        blockers=report.blockers,
        evidence=evidence,
    )


def next_steps(sections: tuple[ReadinessSection, ...]) -> tuple[str, ...]:
    steps: list[str] = []
    for section in sections:
        if section.ok:
            continue
        if section.name == "rom_probe":
            steps.append(
                "Run the read-only ROM feasibility probe and record unlocked-state evidence."
            )
        elif section.name == "manual_gates":
            steps.append("Complete ROM-0 manual gate evidence without secrets or live approval.")
        elif section.name == "fastboot_evidence":
            steps.append(
                "Run the read-only fastboot evidence helper; a human must enter "
                "bootloader mode before the optional visibility check."
            )
        elif section.name == "gsi_candidate":
            steps.append(
                "Create ROM GSI candidate evidence from a downloaded official Google "
                "ARM64 GSI archive."
            )
        elif section.name == "dsu_preflight":
            steps.append(
                "Create read-only DSU preflight evidence after stock restore and GSI "
                "checksum evidence exist."
            )
        elif section.name == "release_signing_plan":
            steps.append("Create a ROM release signing plan with an external keystore.")
        elif section.name == "release_apk_verification":
            steps.append("Verify the signed GOFFY APK before AOSP import planning.")
        elif section.name == "aosp_import":
            steps.append(
                "Provide an externally signed non-debug GOFFY APK for AOSP import planning."
            )
        else:
            steps.append(f"Resolve blockers in {section.name}.")
    if not steps:
        steps.append(
            "Review the evidence manually; this report still does not authorize unlock, "
            "flash, or erase."
        )
    return tuple(dict.fromkeys(steps))


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def dsu_package_present(dsu: Mapping[str, str]) -> str:
    return dsu.get("package_present") or dsu.get("package_installed", "")


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def same_path(left: str, right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return Path(left).expanduser().absolute() == right.expanduser().absolute()


def classified_presence(value: str, blockers: list[str]) -> str:
    if not value:
        return "missing"
    if blockers:
        return "invalid"
    return "configured"


def append_unsupported_key_blockers(
    payload: Mapping[str, object] | Mapping[str, str],
    *,
    allowed: frozenset[str],
    label: str,
    blockers: list[str],
) -> None:
    unsupported = sorted(set(payload) - allowed)
    if unsupported:
        blockers.append(f"{label} contains unsupported keys: {unsupported}")


def render_json(report: Rom0ReadinessReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_markdown(report: Rom0ReadinessReport) -> str:
    lines = [
        "# GOFFY ROM-0 Readiness",
        "",
        f"- Status: `{report.status}`",
        f"- OK: `{str(report.ok).lower()}`",
        f"- Destructive actions: `{report.destructive_actions}`",
    ]
    for section in report.sections:
        lines.extend(("", f"## {section.name}", f"- OK: `{str(section.ok).lower()}`"))
        if section.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {blocker}" for blocker in section.blockers)
        if section.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in section.warnings)
        if section.evidence:
            lines.append("- Evidence:")
            for key, value in section.evidence.items():
                lines.append(f"  - {key}: `{value or 'missing'}`")
    lines.extend(("", "## Next Steps"))
    lines.extend(f"- {step}" for step in report.next_steps)
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize GOFFY ROM-0 readiness without device or AOSP mutations.",
    )
    parser.add_argument("--probe-json", type=Path)
    parser.add_argument("--manual-gates-json", type=Path)
    parser.add_argument("--fastboot-evidence-json", type=Path)
    parser.add_argument("--gsi-candidate-evidence-json", type=Path)
    parser.add_argument("--dsu-preflight-evidence-json", type=Path)
    parser.add_argument("--signing-plan-json", type=Path)
    parser.add_argument("--apk-verification-json", type=Path)
    parser.add_argument("--signed-apk", type=Path)
    parser.add_argument("--aosp-root", type=Path, default=DEFAULT_AOSP_ROOT)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=ROOT,
        help="Root used for rollback_doc paths inside manual gate evidence.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_readiness_report(
        probe_json=args.probe_json,
        manual_gates_json=args.manual_gates_json,
        fastboot_evidence_json=args.fastboot_evidence_json,
        gsi_candidate_evidence_json=args.gsi_candidate_evidence_json,
        dsu_preflight_evidence_json=args.dsu_preflight_evidence_json,
        signing_plan_json=args.signing_plan_json,
        apk_verification_json=args.apk_verification_json,
        signed_apk=args.signed_apk,
        aosp_root=args.aosp_root,
        evidence_root=args.evidence_root,
    )
    print(render_json(report) if args.json else render_markdown(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
