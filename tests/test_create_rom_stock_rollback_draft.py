from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts.create_rom_stock_rollback_draft import (
    JSON_SCHEMA_VERSION,
    create_stock_rollback_draft,
    main,
    render_markdown,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION

BUILD_FINGERPRINT = (
    "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
)


def write_probe(root: Path, *, codename: str = "kansas") -> Path:
    probe = root / ".goffy-validation" / "rom-feasibility-current.json"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        (
            "{\n"
            f'  "schema_version": "{PROBE_SCHEMA_VERSION}",\n'
            '  "device": {\n'
            '    "model": "moto g - 2025",\n'
            f'    "codename": "{codename}",\n'
            '    "product": "kansas_g_sys",\n'
            '    "hardware_sku": "XT2513V",\n'
            '    "carrier": "tracfone"\n'
            "  },\n"
            '  "properties": {\n'
            f'    "ro.build.fingerprint": "{BUILD_FINGERPRINT}"\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    return probe


def test_stock_rollback_draft_binds_probe_archive_and_hash_without_paths(
    tmp_path: Path,
) -> None:
    probe = write_probe(tmp_path)
    archive = tmp_path / "Downloads" / "XT2513V_KANSAS_stock.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"goffy stock rollback archive")

    draft = create_stock_rollback_draft(
        archive_path=archive,
        source_url="https://en-us.support.motorola.com/app/softwarefix",
        probe_json=probe,
        root=tmp_path,
    )
    markdown = render_markdown(draft)

    assert draft.schema_version == JSON_SCHEMA_VERSION
    assert draft.archive_name == "XT2513V_KANSAS_stock.zip"
    assert draft.sha256 == hashlib.sha256(b"goffy stock rollback archive").hexdigest()
    assert draft.probe_json == ".goffy-validation/rom-feasibility-current.json"
    assert "## Device Baseline" in markdown
    assert "## Stock Restore Source" in markdown
    assert "## SHA-256 Evidence" in markdown
    assert "## Rollback Procedure" in markdown
    assert "moto g - 2025" in markdown
    assert "XT2513V" in markdown
    assert BUILD_FINGERPRINT in markdown
    assert "XT2513V_KANSAS_stock.zip" in markdown
    assert draft.sha256 in markdown
    assert str(archive.parent) not in markdown
    assert str(probe.parent) not in markdown


def test_stock_rollback_draft_rejects_unofficial_or_sensitive_source(
    tmp_path: Path,
) -> None:
    probe = write_probe(tmp_path)
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_rollback_draft(
            archive_path=archive,
            source_url="https://user:pass@example.invalid/firmware.zip?token=1",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "source URL must not include credentials" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_rollback_draft_rejects_probe_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-probe.json"
    outside.write_text(
        (
            "{\n"
            f'  "schema_version": "{PROBE_SCHEMA_VERSION}",\n'
            '  "device": {},\n'
            '  "properties": {}\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_rollback_draft(
            archive_path=archive,
            source_url="https://en-us.support.motorola.com/app/softwarefix",
            probe_json=outside,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "probe JSON must be inside the repo" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_rollback_draft_rejects_noncanonical_repo_probe(tmp_path: Path) -> None:
    probe = tmp_path / "docs" / "stale-probe.json"
    probe.parent.mkdir()
    probe.write_text(
        (
            "{\n"
            f'  "schema_version": "{PROBE_SCHEMA_VERSION}",\n'
            '  "device": {},\n'
            '  "properties": {}\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_rollback_draft(
            archive_path=archive,
            source_url="https://en-us.support.motorola.com/app/softwarefix",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "probe JSON must be .goffy-validation/rom-feasibility-current.json" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_rollback_draft_rejects_symlinked_canonical_probe(tmp_path: Path) -> None:
    target = tmp_path / ".goffy-validation" / "probe-target.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        (
            "{\n"
            f'  "schema_version": "{PROBE_SCHEMA_VERSION}",\n'
            '  "device": {},\n'
            '  "properties": {}\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    probe = tmp_path / ".goffy-validation" / "rom-feasibility-current.json"
    probe.symlink_to(target)
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_rollback_draft(
            archive_path=archive,
            source_url="https://en-us.support.motorola.com/app/softwarefix",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "probe JSON path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_rollback_draft_requires_exact_kansas_probe_target(tmp_path: Path) -> None:
    probe = write_probe(tmp_path, codename="wrong")
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_rollback_draft(
            archive_path=archive,
            source_url="https://en-us.support.motorola.com/app/softwarefix",
            probe_json=probe,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "target_device.codename must match kansas" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_rollback_draft_cli_prints_relative_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    probe = write_probe(tmp_path)
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")
    output = tmp_path / ".goffy-validation" / "kansas-stock-rollback.draft.md"

    exit_code = main(
        [
            "--archive",
            str(archive),
            "--source-url",
            "https://en-us.support.motorola.com/app/softwarefix",
            "--probe-json",
            str(probe),
            "--output",
            str(output),
        ],
        root=tmp_path,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert "wrote stock rollback draft to .goffy-validation/kansas-stock-rollback.draft.md" in (
        captured.out
    )
    assert str(tmp_path) not in captured.out
