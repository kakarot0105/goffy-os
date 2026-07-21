from __future__ import annotations

import json
from pathlib import Path

from scripts.create_rom_manual_gates_template import (
    MOTOROLA_SOFTWARE_FIX_URL,
    create_manual_gates_template,
    output_path_allowed,
    render_json,
    write_output,
)
from scripts.create_rom_stock_restore_evidence import (
    JSON_SCHEMA_VERSION as STOCK_RESTORE_SCHEMA_VERSION,
)
from scripts.validate_rom_manual_gates import (
    JSON_SCHEMA_VERSION as MANUAL_GATES_SCHEMA_VERSION,
)
from scripts.validate_rom_manual_gates import validate_manual_gates


def test_manual_gates_template_defaults_to_blocked_safe_values() -> None:
    template = create_manual_gates_template()
    report = validate_manual_gates(template)

    assert template["schema_version"] == MANUAL_GATES_SCHEMA_VERSION
    assert template["backup_confirmed"] is False
    assert template["oem_unlocking_enabled"] is False
    assert template["motorola_unlock_eligibility"] == "unknown"
    assert template["destructive_approval"] == "not_requested"
    assert template["stock_restore"]["source_url"] == MOTOROLA_SOFTWARE_FIX_URL
    assert not report.ok
    assert "backup_confirmed must be true" in report.blockers
    assert "oem_unlocking_enabled must be true" in report.blockers
    assert "Motorola bootloader unlock eligibility is not recorded as eligible" in report.blockers
    assert "stock_restore.archive_name must be a filename, not a path" in report.blockers
    assert "stock_restore.sha256 must be 64 hex characters" in report.blockers


def test_manual_gates_template_merges_stock_restore_evidence(tmp_path: Path) -> None:
    stock_restore = {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": "a" * 64,
        "rollback_doc": "docs/setup/kansas-stock-rollback.md",
    }
    evidence_path = tmp_path / "rom-stock-restore-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": STOCK_RESTORE_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "stock_restore": stock_restore,
            }
        ),
        encoding="utf-8",
    )

    template = create_manual_gates_template(stock_restore_evidence=evidence_path)

    assert template["stock_restore"] == stock_restore
    assert template["backup_confirmed"] is False
    assert template["destructive_approval"] == "not_requested"
    assert "generated_at" not in render_json(template)


def test_manual_gates_template_rejects_sensitive_stock_restore_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "rom-stock-restore-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": STOCK_RESTORE_SCHEMA_VERSION,
                "stock_restore": {
                    "source_url": "https://en-us.support.motorola.com/app/softwarefix",
                    "archive_name": "kansas-stock.zip",
                    "sha256": "a" * 64,
                    "rollback_doc": "docs/setup/kansas-stock-rollback.md",
                    "device_serial": "ZY32LBQLMQ",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        create_manual_gates_template(stock_restore_evidence=evidence_path)
    except ValueError as exc:
        assert "sensitive key" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_manual_gates_template_rejects_extra_stock_restore_evidence_keys(tmp_path: Path) -> None:
    evidence_path = tmp_path / "rom-stock-restore-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": STOCK_RESTORE_SCHEMA_VERSION,
                "stock_restore": {
                    "source_url": "https://en-us.support.motorola.com/app/softwarefix",
                    "archive_name": "kansas-stock.zip",
                    "sha256": "a" * 64,
                    "rollback_doc": "docs/setup/kansas-stock-rollback.md",
                    "source_channel": "retus",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        create_manual_gates_template(stock_restore_evidence=evidence_path)
    except ValueError as exc:
        assert "unsupported keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_manual_gates_template_rejects_invalid_stock_restore_values(tmp_path: Path) -> None:
    evidence_path = tmp_path / "rom-stock-restore-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": STOCK_RESTORE_SCHEMA_VERSION,
                "stock_restore": {
                    "source_url": "https://example.invalid/fw.zip?auth=abc",
                    "archive_name": "../../kansas-stock.zip",
                    "sha256": "not-a-sha",
                    "rollback_doc": "../secret.md",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        create_manual_gates_template(stock_restore_evidence=evidence_path)
    except ValueError as exc:
        assert "Motorola Software Fix URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_manual_gates_template_output_is_limited_to_validation_dir(tmp_path: Path) -> None:
    payload = render_json(create_manual_gates_template())
    allowed = tmp_path / ".goffy-validation" / "rom-0-manual-gates.template.json"
    relative_allowed = Path(".goffy-validation/rom-0-manual-gates.relative.json")
    blocked = tmp_path / "docs" / "rom-0-manual-gates.template.json"

    assert output_path_allowed(allowed, root=tmp_path)
    assert output_path_allowed(relative_allowed, root=tmp_path)
    assert not output_path_allowed(blocked, root=tmp_path)

    write_output(allowed, payload, root=tmp_path)
    assert json.loads(allowed.read_text(encoding="utf-8"))["schema_version"] == (
        MANUAL_GATES_SCHEMA_VERSION
    )

    try:
        write_output(blocked, payload, root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_manual_gates_template_rejects_symlinked_validation_output_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    validation_root = tmp_path / ".goffy-validation"
    validation_root.symlink_to(target, target_is_directory=True)
    output = validation_root / "rom-0-manual-gates.template.json"

    assert not output_path_allowed(output, root=tmp_path)

    try:
        write_output(output, render_json(create_manual_gates_template()), root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_manual_gates_template_rejects_symlinked_output_file(tmp_path: Path) -> None:
    validation_root = tmp_path / ".goffy-validation"
    validation_root.mkdir()
    outside = tmp_path / "outside.json"
    output = validation_root / "rom-0-manual-gates.template.json"
    output.symlink_to(outside)

    assert not output_path_allowed(output, root=tmp_path)

    try:
        write_output(output, render_json(create_manual_gates_template()), root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")
