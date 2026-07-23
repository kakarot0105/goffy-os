from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.create_rom_unlock_eligibility_evidence import (
    JSON_SCHEMA_VERSION,
    MOTOROLA_BOOTLOADER_SUPPORT_URL,
    create_unlock_eligibility_evidence,
    load_unlock_eligibility_evidence,
    main,
    public_target_sha256,
    render_json,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION

BUILD_FINGERPRINT = (
    "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
)
TARGET_DEVICE = {
    "model": "moto g - 2025",
    "codename": "kansas",
    "product": "kansas_g_sys",
    "hardware_sku": "XT2513V",
    "build_fingerprint": BUILD_FINGERPRINT,
    "carrier": "tracfone",
}
PROBE_GENERATED_AT = "2026-07-22T00:00:00+00:00"


def test_unlock_eligibility_evidence_records_redacted_manual_result(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    evidence = create_unlock_eligibility_evidence(
        oem_unlocking_visible=True,
        oem_unlocking_enabled=True,
        motorola_unlock_eligibility="eligible",
        probe_json=probe,
        operator_note_code="checked_no_identifiers_stored",
        root=tmp_path,
    )
    payload = json.loads(render_json(evidence))

    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    assert payload["target_device"] == TARGET_DEVICE
    assert payload["probe_binding"] == probe_binding()
    assert payload["unlock_eligibility"] == {
        "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
        "oem_unlocking_visible": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "operator_note_code": "checked_no_identifiers_stored",
    }
    assert "generated_at" in payload


def test_unlock_eligibility_rejects_impossible_oem_toggle_state(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=False,
            oem_unlocking_enabled=True,
            motorola_unlock_eligibility="unknown",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "cannot be enabled when the toggle is not visible" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_unofficial_source_and_invalid_status() -> None:
    probe = Path(".goffy-validation/rom-feasibility-current.json")
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="maybe",
            probe_json=probe,
            source_url="https://example.invalid/unlock",
        )
    except ValueError as exc:
        assert "motorola eligibility must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="not_eligible",
            probe_json=probe,
            source_url="https://example.invalid/unlock",
        )
    except ValueError as exc:
        assert "source URL must be the Motorola bootloader support URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_freeform_note_values(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="unknown",
            probe_json=probe,
            operator_note_code="ZY32LBQLMQ",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "operator note code must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_sensitive_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "target_device": TARGET_DEVICE,
                "probe_binding": probe_binding(),
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                    "device_serial": "ZY32LBQLMQ",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "sensitive key" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "target_device": TARGET_DEVICE,
                "probe_binding": probe_binding(),
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                    "screenshot_path": "redacted-oem.png",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "unsupported keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_top_level_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "target_device": TARGET_DEVICE,
                "probe_binding": probe_binding(),
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                },
                "screenshot_path": "redacted-oem.png",
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "unsupported top-level keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_requires_string_fields(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "target_device": TARGET_DEVICE,
                "probe_binding": probe_binding(),
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": 123,
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "operator_note_code must be a string" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_requires_target_device(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "target_device object" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_extra_target_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "target_device": {**TARGET_DEVICE, "sales_channel": "retus"},
                "probe_binding": probe_binding(),
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "target_device contains unsupported keys: ['sales_channel']" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_noncanonical_probe(tmp_path: Path) -> None:
    probe = tmp_path / "docs" / "stale-probe.json"
    probe.parent.mkdir()
    probe.write_text(render_probe_json(), encoding="utf-8")

    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=True,
            motorola_unlock_eligibility="eligible",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "probe JSON must be .goffy-validation/rom-feasibility-current.json" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_symlinked_probe(tmp_path: Path) -> None:
    target = tmp_path / ".goffy-validation" / "probe-target.json"
    target.parent.mkdir(parents=True)
    target.write_text(render_probe_json(), encoding="utf-8")
    probe = tmp_path / ".goffy-validation" / "rom-feasibility-current.json"
    probe.symlink_to(target)

    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=True,
            motorola_unlock_eligibility="eligible",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "probe JSON path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_wrong_target_probe(tmp_path: Path) -> None:
    probe = write_probe(tmp_path, codename="wrong")

    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=True,
            motorola_unlock_eligibility="eligible",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "target_device.codename must match kansas" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_emits_redacted_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    probe = write_probe(tmp_path)
    exit_code = main(
        [
            "--oem-unlocking-visible",
            "yes",
            "--oem-unlocking-enabled",
            "no",
            "--probe-json",
            str(probe),
            "--motorola-eligibility",
            "not_eligible",
            "--stdout",
        ],
        root=tmp_path,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target_device"] == TARGET_DEVICE
    assert payload["probe_binding"] == probe_binding()
    assert payload["unlock_eligibility"]["motorola_unlock_eligibility"] == "not_eligible"


def test_cli_prints_relative_output_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe = write_probe(tmp_path)
    output = tmp_path / ".goffy-validation" / "rom-unlock-eligibility-evidence.json"

    exit_code = main(
        [
            "--oem-unlocking-visible",
            "yes",
            "--oem-unlocking-enabled",
            "yes",
            "--probe-json",
            str(probe),
            "--motorola-eligibility",
            "eligible",
            "--output",
            str(output),
        ],
        root=tmp_path,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert (
        "wrote unlock eligibility evidence to "
        ".goffy-validation/rom-unlock-eligibility-evidence.json"
    ) in captured.out
    assert str(tmp_path) not in captured.out


def write_probe(tmp_path: Path, *, codename: str = "kansas") -> Path:
    probe = tmp_path / ".goffy-validation" / "rom-feasibility-current.json"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(render_probe_json(codename=codename), encoding="utf-8")
    return probe


def render_probe_json(*, codename: str = "kansas") -> str:
    device = {**TARGET_DEVICE, "codename": codename}
    return json.dumps(
        {
            "schema_version": PROBE_SCHEMA_VERSION,
            "generated_at": PROBE_GENERATED_AT,
            "device": {
                "model": device["model"],
                "codename": device["codename"],
                "product": device["product"],
                "hardware_sku": device["hardware_sku"],
                "carrier": device["carrier"],
            },
            "properties": {"ro.build.fingerprint": device["build_fingerprint"]},
        }
    )


def probe_binding() -> dict[str, str]:
    return {
        "source_path": ".goffy-validation/rom-feasibility-current.json",
        "probe_generated_at": PROBE_GENERATED_AT,
        "public_target_sha256": public_target_sha256(TARGET_DEVICE),
    }
