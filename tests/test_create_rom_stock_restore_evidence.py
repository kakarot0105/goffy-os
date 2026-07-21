from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.create_rom_stock_restore_evidence import (
    JSON_SCHEMA_VERSION,
    create_stock_restore_evidence,
    output_path_allowed,
    render_json,
    write_output,
)


def write_rollback_doc(root: Path) -> str:
    rollback_doc = root / "docs" / "setup" / "kansas-stock-rollback.md"
    rollback_doc.parent.mkdir(parents=True)
    rollback_doc.write_text("# Rollback\n", encoding="utf-8")
    return "docs/setup/kansas-stock-rollback.md"


def test_stock_restore_evidence_hashes_archive_without_leaking_path(tmp_path: Path) -> None:
    rollback_doc = write_rollback_doc(tmp_path)
    archive = tmp_path / "downloads" / "kansas-stock.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"goffy stock archive")

    evidence = create_stock_restore_evidence(
        archive_path=archive,
        source_url="https://en-us.support.motorola.com/app/softwarefix",
        rollback_doc=rollback_doc,
        root=tmp_path,
    )

    assert evidence.schema_version == JSON_SCHEMA_VERSION
    assert evidence.stock_restore == {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": hashlib.sha256(b"goffy stock archive").hexdigest(),
        "rollback_doc": rollback_doc,
    }
    assert str(archive.parent) not in render_json(evidence)


def test_stock_restore_evidence_rejects_unsafe_inputs(tmp_path: Path) -> None:
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_restore_evidence(
            archive_path=archive,
            source_url="http://example.invalid/firmware.zip",
            rollback_doc="../rollback.txt",
            root=tmp_path,
        )
    except ValueError as exc:
        message = str(exc)
        assert "source URL must be https" in message
        assert "rollback doc must be a relative repo path" in message
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_rejects_source_url_query_or_fragment(tmp_path: Path) -> None:
    rollback_doc = write_rollback_doc(tmp_path)
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_restore_evidence(
            archive_path=archive,
            source_url="https://example.invalid/firmware.zip?token=abc#download",
            rollback_doc=rollback_doc,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "source URL must not include query or fragment" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_rejects_source_url_credentials(tmp_path: Path) -> None:
    rollback_doc = write_rollback_doc(tmp_path)
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_restore_evidence(
            archive_path=archive,
            source_url="https://user:pass@example.invalid/firmware.zip",
            rollback_doc=rollback_doc,
            root=tmp_path,
        )
    except ValueError as exc:
        assert "source URL must not include credentials" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_requires_existing_markdown_rollback_doc(tmp_path: Path) -> None:
    archive = tmp_path / "firmware.zip"
    archive.write_bytes(b"firmware")

    try:
        create_stock_restore_evidence(
            archive_path=archive,
            source_url="https://example.invalid/firmware.zip",
            rollback_doc="docs/setup/rollback.txt",
            root=tmp_path,
        )
    except ValueError as exc:
        message = str(exc)
        assert "rollback doc must be Markdown" in message
        assert "rollback doc must exist" in message
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_output_is_limited_to_validation_dir(tmp_path: Path) -> None:
    payload = json.dumps({"ok": True})
    allowed = tmp_path / ".goffy-validation" / "rom-stock-restore-evidence.json"
    relative_allowed = Path(".goffy-validation/rom-stock-restore-evidence.relative.json")
    blocked = tmp_path / "docs" / "rom-stock-restore-evidence.json"

    assert output_path_allowed(allowed, root=tmp_path)
    assert output_path_allowed(relative_allowed, root=tmp_path)
    assert not output_path_allowed(blocked, root=tmp_path)

    write_output(allowed, payload, root=tmp_path)
    assert allowed.read_text(encoding="utf-8") == payload
    write_output(relative_allowed, payload, root=tmp_path)
    assert (tmp_path / relative_allowed).read_text(encoding="utf-8") == payload

    try:
        write_output(blocked, payload, root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_rejects_symlinked_validation_output_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    validation_root = tmp_path / ".goffy-validation"
    validation_root.symlink_to(target, target_is_directory=True)
    output = validation_root / "rom-stock-restore-evidence.json"

    assert not output_path_allowed(output, root=tmp_path)

    try:
        write_output(output, json.dumps({"ok": True}), root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stock_restore_evidence_rejects_symlinked_output_file(tmp_path: Path) -> None:
    validation_root = tmp_path / ".goffy-validation"
    validation_root.mkdir()
    outside = tmp_path / "outside.json"
    output = validation_root / "rom-stock-restore-evidence.json"
    output.symlink_to(outside)

    assert not output_path_allowed(output, root=tmp_path)

    try:
        write_output(output, json.dumps({"ok": True}), root=tmp_path)
    except ValueError as exc:
        assert "output path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")
