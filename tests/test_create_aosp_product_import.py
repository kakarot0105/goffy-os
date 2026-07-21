from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from scripts.create_aosp_product_import import (
    APK_VERIFICATION_SCHEMA_VERSION,
    APP_IMPORT_DIR,
    PRODUCT_IMPORT_DIR,
    AospProductImportError,
    create_aosp_product_import_report,
    execute_aosp_product_import,
)


def test_aosp_product_import_plan_is_dry_run_with_signed_apk(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    aosp_root = tmp_path / "aosp"

    report = create_aosp_product_import_report(aosp_root=aosp_root, apk_path=apk)

    assert report.safe_to_execute is True
    assert report.blockers == ()
    assert {item.destination for item in report.files} == {
        (PRODUCT_IMPORT_DIR / "AndroidProducts.mk").as_posix(),
        (PRODUCT_IMPORT_DIR / "goffy_gsi_phone.mk").as_posix(),
        (PRODUCT_IMPORT_DIR / "goffy_product_packages.mk").as_posix(),
        (APP_IMPORT_DIR / "Android.bp").as_posix(),
        (APP_IMPORT_DIR / "GoffyOS.apk").as_posix(),
    }
    assert apk_entry(report).apk_signature_schemes == ("v2",)
    assert not (aosp_root / PRODUCT_IMPORT_DIR).exists()
    assert not (aosp_root / APP_IMPORT_DIR).exists()


def test_aosp_product_import_accepts_matching_apk_verification_evidence(
    tmp_path: Path,
) -> None:
    apk = write_signed_apk(tmp_path)
    verification = write_apk_verification(tmp_path, apk)

    report = create_aosp_product_import_report(
        aosp_root=tmp_path / "aosp",
        apk_path=apk,
        apk_verification_json=verification,
    )

    assert report.safe_to_execute is True
    assert report.blockers == ()


def test_aosp_product_import_rejects_apk_verification_mismatch(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    other_apk = tmp_path / "OtherGoffyOS-signed.apk"
    other_apk.write_bytes(apk.read_bytes())
    verification = write_apk_verification(tmp_path, other_apk)

    report = create_aosp_product_import_report(
        aosp_root=tmp_path / "aosp",
        apk_path=apk,
        apk_verification_json=verification,
    )

    assert report.safe_to_execute is False
    assert "GOFFY APK verification path does not match import APK" in report.blockers


def test_aosp_product_import_rejects_apk_verification_hash_mismatch(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    verification = write_apk_verification(tmp_path, apk, sha256="d" * 64)

    report = create_aosp_product_import_report(
        aosp_root=tmp_path / "aosp",
        apk_path=apk,
        apk_verification_json=verification,
    )

    assert report.safe_to_execute is False
    assert "GOFFY APK verification sha256 does not match import APK" in report.blockers


def test_aosp_product_import_rejects_blocked_apk_verification(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    verification = write_apk_verification(
        tmp_path,
        apk,
        ok=False,
        status="BLOCKED_APK_VERIFICATION",
        blockers=["GOFFY release verification APK is missing"],
        signature_schemes=(),
    )

    report = create_aosp_product_import_report(
        aosp_root=tmp_path / "aosp",
        apk_path=apk,
        apk_verification_json=verification,
    )

    assert report.safe_to_execute is False
    assert "GOFFY release verification APK is missing" in report.blockers


def test_aosp_product_import_blocks_unsigned_default_apk(tmp_path: Path) -> None:
    report = create_aosp_product_import_report(aosp_root=tmp_path / "aosp")

    assert report.safe_to_execute is False
    assert "GOFFY import APK must be externally signed before ROM import" in report.blockers


def test_aosp_product_import_blocks_debug_artifacts(tmp_path: Path) -> None:
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(fake_apk_with_v2_signature_block())

    report = create_aosp_product_import_report(aosp_root=tmp_path / "aosp", apk_path=apk)

    assert report.safe_to_execute is False
    assert "GOFFY import APK must not be a debug build artifact" in report.blockers
    assert apk_entry(report).apk_signature_schemes == ("v2",)


def test_aosp_product_import_rejects_signed_name_without_signature_block(
    tmp_path: Path,
) -> None:
    apk = tmp_path / "GoffyOS-signed.apk"
    apk.write_bytes(b"not an apk signature block")

    report = create_aosp_product_import_report(aosp_root=tmp_path / "aosp", apk_path=apk)

    assert report.safe_to_execute is False
    assert "GOFFY import APK must contain an APK Signature Scheme v2/v3 block" in report.blockers
    assert apk_entry(report).apk_signature_schemes == ()


def test_aosp_product_import_executes_only_into_existing_aosp_root(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    aosp_root = tmp_path / "aosp"
    report = create_aosp_product_import_report(aosp_root=aosp_root, apk_path=apk)

    with pytest.raises(AospProductImportError, match="existing directory"):
        execute_aosp_product_import(report, aosp_root=aosp_root)

    aosp_root.mkdir()
    executed = execute_aosp_product_import(report, aosp_root=aosp_root)

    assert (aosp_root / PRODUCT_IMPORT_DIR / "AndroidProducts.mk").is_file()
    assert (aosp_root / PRODUCT_IMPORT_DIR / "goffy_gsi_phone.mk").is_file()
    assert (aosp_root / PRODUCT_IMPORT_DIR / "goffy_product_packages.mk").is_file()
    assert (aosp_root / APP_IMPORT_DIR / "Android.bp").is_file()
    assert (aosp_root / APP_IMPORT_DIR / "GoffyOS.apk").read_bytes() == apk.read_bytes()
    assert {item.status for item in executed.files} == {"copied"}


def test_aosp_product_import_is_idempotent_for_identical_files(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    aosp_root = tmp_path / "aosp"
    aosp_root.mkdir()
    report = create_aosp_product_import_report(aosp_root=aosp_root, apk_path=apk)

    execute_aosp_product_import(report, aosp_root=aosp_root)
    executed_again = execute_aosp_product_import(report, aosp_root=aosp_root)

    assert {item.status for item in executed_again.files} == {"unchanged"}


def test_aosp_product_import_refuses_to_overwrite_different_files(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    aosp_root = tmp_path / "aosp"
    existing = aosp_root / PRODUCT_IMPORT_DIR / "AndroidProducts.mk"
    existing.parent.mkdir(parents=True)
    existing.write_text("user owned file\n", encoding="utf-8")
    report = create_aosp_product_import_report(aosp_root=aosp_root, apk_path=apk)

    with pytest.raises(AospProductImportError, match="refusing to overwrite"):
        execute_aosp_product_import(report, aosp_root=aosp_root)

    assert existing.read_text(encoding="utf-8") == "user owned file\n"


def write_signed_apk(tmp_path: Path) -> Path:
    apk = tmp_path / "GoffyOS-signed.apk"
    apk.write_bytes(fake_apk_with_v2_signature_block())
    return apk


def write_apk_verification(
    tmp_path: Path,
    apk: Path,
    *,
    ok: bool = True,
    status: str = "VERIFIED",
    sha256: str | None = None,
    blockers: list[str] | None = None,
    signature_schemes: tuple[str, ...] = ("v2",),
) -> Path:
    path = tmp_path / "release-apk-verification.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": APK_VERIFICATION_SCHEMA_VERSION,
                "ok": ok,
                "status": status,
                "destructive_actions": "withheld",
                "apk": {
                    "path": str(apk),
                    "exists": apk.is_file(),
                    "sha256": sha256 or hashlib.sha256(apk.read_bytes()).hexdigest(),
                    "byte_count": apk.stat().st_size if apk.is_file() else None,
                    "signature_schemes": list(signature_schemes),
                },
                "blockers": blockers or [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def apk_entry(report):
    return next(item for item in report.files if item.destination.endswith("GoffyOS.apk"))


def fake_apk_with_v2_signature_block() -> bytes:
    payload = b"fake apk payload"
    pair = struct.pack("<Q", 4) + struct.pack("<I", 0x7109871A)
    block_size = len(pair) + 24
    signing_block = (
        struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + b"APK Sig Block 42"
    )
    central_directory_offset = len(payload) + len(signing_block)
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 0, 0, 0, central_directory_offset, 0)
    return payload + signing_block + eocd
