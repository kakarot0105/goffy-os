from __future__ import annotations

from pathlib import Path

import pytest
from scripts.create_aosp_product_import import (
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
    assert not (aosp_root / PRODUCT_IMPORT_DIR).exists()
    assert not (aosp_root / APP_IMPORT_DIR).exists()


def test_aosp_product_import_blocks_unsigned_default_apk(tmp_path: Path) -> None:
    report = create_aosp_product_import_report(aosp_root=tmp_path / "aosp")

    assert report.safe_to_execute is False
    assert "GOFFY import APK must be externally signed before ROM import" in report.blockers


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
    apk.write_bytes(b"fake signed apk for import planning")
    return apk
