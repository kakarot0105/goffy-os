from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_rom_product_overlay import validate_rom_product_overlay

ANDROID_PRODUCTS = """\
PRODUCT_MAKEFILES := \\
    $(LOCAL_DIR)/goffy_gsi_phone.mk

COMMON_LUNCH_CHOICES := \\
    goffy_gsi_phone-userdebug
"""

PRODUCT_MAKEFILE = """\
$(call inherit-product, $(SRC_TARGET_DIR)/product/handheld_system.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/telephony_system.mk)
$(call inherit-product, $(LOCAL_DIR)/goffy_product_packages.mk)

PRODUCT_NAME := goffy_gsi_phone
PRODUCT_DEVICE := generic
PRODUCT_BRAND := GOFFY
PRODUCT_MODEL := GOFFY OS GSI Phone
PRODUCT_MANUFACTURER := GOFFY

PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := strict
"""

PACKAGES_MAKEFILE = """\
PRODUCT_PACKAGES += \\
    GoffyOS
"""

SYSTEM_APP_DESCRIPTOR = {
    "schema_version": "goffy.rom-system-app.v1",
    "module_name": "GoffyOS",
    "privileged": False,
    "platform_signed": False,
    "privileged_permission_allowlist": [],
}


def descriptor() -> dict[str, object]:
    return {
        "schema_version": "goffy.rom-product-overlay.v1",
        "product_name": "goffy_gsi_phone",
        "target_device": "generic",
        "target_arch": "arm64",
        "android_products_template": "rom/product/AndroidProducts.mk.template",
        "product_makefile_template": "rom/product/goffy_gsi_phone.mk.template",
        "packages_makefile_template": "rom/product/goffy_product_packages.mk.template",
        "required_module": "GoffyOS",
        "system_app_descriptor": "rom/system-app/goffy-system-app.json",
        "supported_lunch_choices": ["goffy_gsi_phone-userdebug"],
        "flashable": False,
        "destructive_actions_included": False,
    }


def write_fixture(
    tmp_path: Path,
    payload: dict[str, object],
) -> tuple[Path, Path, Path, Path, Path]:
    descriptor_path = tmp_path / "rom" / "product" / "goffy-product-overlay.json"
    android_products = tmp_path / "rom" / "product" / "AndroidProducts.mk.template"
    product_makefile = tmp_path / "rom" / "product" / "goffy_gsi_phone.mk.template"
    packages_makefile = tmp_path / "rom" / "product" / "goffy_product_packages.mk.template"
    system_app = tmp_path / "rom" / "system-app" / "goffy-system-app.json"
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    system_app.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(payload), encoding="utf-8")
    android_products.write_text(ANDROID_PRODUCTS, encoding="utf-8")
    product_makefile.write_text(PRODUCT_MAKEFILE, encoding="utf-8")
    packages_makefile.write_text(PACKAGES_MAKEFILE, encoding="utf-8")
    system_app.write_text(json.dumps(SYSTEM_APP_DESCRIPTOR), encoding="utf-8")
    return descriptor_path, android_products, product_makefile, packages_makefile, system_app


def test_rom_product_overlay_accepts_current_safe_shape(tmp_path: Path) -> None:
    descriptor_path, *_ = write_fixture(tmp_path, descriptor())

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert findings == []


def test_rom_product_overlay_rejects_flashable_or_destructive_claims(tmp_path: Path) -> None:
    payload = descriptor()
    payload["flashable"] = True
    payload["destructive_actions_included"] = True
    descriptor_path, *_ = write_fixture(tmp_path, payload)

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert "product overlay descriptor must not claim to be flashable" in findings
    assert "product overlay must not include destructive actions" in findings


def test_rom_product_overlay_rejects_eng_or_unlock_templates(tmp_path: Path) -> None:
    descriptor_path, android_products, product_makefile, *_ = write_fixture(tmp_path, descriptor())
    android_products.write_text(
        ANDROID_PRODUCTS + "\nCOMMON_LUNCH_CHOICES += goffy_gsi_phone-eng\n",
        encoding="utf-8",
    )
    product_makefile.write_text(
        PRODUCT_MAKEFILE + "\n# fastboot flashing unlock\n", encoding="utf-8"
    )

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert "AndroidProducts template must not expose eng lunch choices" in findings
    assert "product_makefile_template must not contain fastboot" in findings
    assert "product_makefile_template must not contain flashing unlock" in findings


def test_rom_product_overlay_rejects_debug_security_properties(tmp_path: Path) -> None:
    descriptor_path, _, product_makefile, *_ = write_fixture(tmp_path, descriptor())
    product_makefile.write_text(
        PRODUCT_MAKEFILE
        + "\nPRODUCT_SYSTEM_DEFAULT_PROPERTIES += ro.secure=0 ro.adb.secure=0 ro.debuggable=1\n",
        encoding="utf-8",
    )

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert "product_makefile_template must not contain ro.secure=0" in findings
    assert "product_makefile_template must not contain ro.adb.secure=0" in findings
    assert "product_makefile_template must not contain ro.debuggable=1" in findings


def test_rom_product_overlay_rejects_missing_goffy_package(tmp_path: Path) -> None:
    descriptor_path, _, _, packages_makefile, _ = write_fixture(tmp_path, descriptor())
    packages_makefile.write_text("PRODUCT_PACKAGES += Launcher3QuickStep\n", encoding="utf-8")

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert "packages makefile must include GoffyOS" in findings


def test_rom_product_overlay_rejects_privileged_system_app_descriptor(tmp_path: Path) -> None:
    descriptor_path, *_, system_app = write_fixture(tmp_path, descriptor())
    unsafe = SYSTEM_APP_DESCRIPTOR | {
        "privileged": True,
        "platform_signed": True,
        "privileged_permission_allowlist": ["android.permission.WRITE_SECURE_SETTINGS"],
    }
    system_app.write_text(json.dumps(unsafe), encoding="utf-8")

    findings = validate_rom_product_overlay(descriptor_path=descriptor_path, root=tmp_path)

    assert "system app descriptor must remain non-privileged" in findings
    assert "system app descriptor must not request platform signing" in findings
    assert "system app descriptor privileged allowlist must remain empty" in findings
