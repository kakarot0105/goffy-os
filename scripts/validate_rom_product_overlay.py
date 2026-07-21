from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "rom" / "product" / "goffy-product-overlay.json"
SCHEMA_VERSION = "goffy.rom-product-overlay.v1"
SYSTEM_APP_SCHEMA_VERSION = "goffy.rom-system-app.v1"
PRODUCT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,64}$")
REQUIRED_MODULE = "GoffyOS"
BLOCKED_TEMPLATE_PATTERNS = (
    "add_lunch_combo",
    "avbctl",
    "disable-verity",
    "fastboot",
    "flashing unlock",
    "magisk",
    "oem unlock",
    "privapp-permissions",
    "PRODUCT_ADB_KEYS",
    "PRODUCT_COPY_FILES",
    "PRODUCT_DEFAULT_DEV_CERTIFICATE",
    "PRODUCT_OTA_PUBLIC_KEYS",
    "ro.adb.secure=0",
    "ro.debuggable=1",
    "ro.secure=0",
    "su ",
    "userdebug_plat_sepolicy.cil",
)


def validate_rom_product_overlay(
    *,
    descriptor_path: Path = DESCRIPTOR,
    root: Path = ROOT,
) -> list[str]:
    findings: list[str] = []
    descriptor = load_descriptor(descriptor_path)

    product_name = string_value(descriptor.get("product_name"))
    required_module = string_value(descriptor.get("required_module"))
    target_device = string_value(descriptor.get("target_device"))
    supported_lunch_choices = string_list(descriptor.get("supported_lunch_choices"))

    if descriptor.get("schema_version") != SCHEMA_VERSION:
        findings.append("descriptor schema_version mismatch")
    if PRODUCT_NAME_PATTERN.fullmatch(product_name) is None:
        findings.append("product_name must be lowercase snake_case")
    if target_device != "generic":
        findings.append("target_device must remain generic until device tree evidence exists")
    if descriptor.get("target_arch") != "arm64":
        findings.append("target_arch must remain arm64 for the Moto G GSI path")
    if required_module != REQUIRED_MODULE:
        findings.append("required_module must be GoffyOS")
    if descriptor.get("flashable") is not False:
        findings.append("product overlay descriptor must not claim to be flashable")
    if descriptor.get("destructive_actions_included") is not False:
        findings.append("product overlay must not include destructive actions")
    if supported_lunch_choices != [f"{product_name}-userdebug"]:
        findings.append("supported_lunch_choices must contain only the userdebug GOFFY product")

    android_products = relative_repo_path(descriptor.get("android_products_template"), root=root)
    product_makefile = relative_repo_path(descriptor.get("product_makefile_template"), root=root)
    packages_makefile = relative_repo_path(descriptor.get("packages_makefile_template"), root=root)
    system_app_descriptor = relative_repo_path(descriptor.get("system_app_descriptor"), root=root)

    template_paths = {
        "android_products_template": android_products,
        "product_makefile_template": product_makefile,
        "packages_makefile_template": packages_makefile,
    }
    for label, path in template_paths.items():
        if path is None or not path.is_file():
            findings.append(f"{label} must point to an existing repo file")

    if system_app_descriptor is None or not system_app_descriptor.is_file():
        findings.append("system_app_descriptor must point to an existing repo file")
    else:
        findings.extend(validate_system_app_descriptor(system_app_descriptor))

    if android_products is not None and android_products.is_file():
        findings.extend(
            validate_android_products_template(
                android_products,
                product_name=product_name,
                product_makefile=aosp_template_filename(product_makefile),
            )
        )
    if product_makefile is not None and product_makefile.is_file():
        findings.extend(
            validate_product_makefile_template(
                product_makefile,
                product_name=product_name,
                required_package_makefile=aosp_template_filename(packages_makefile),
            )
        )
    if packages_makefile is not None and packages_makefile.is_file():
        findings.extend(
            validate_packages_makefile_template(
                packages_makefile,
                required_module=required_module,
            )
        )

    for label, path in template_paths.items():
        if path is not None and path.is_file():
            findings.extend(blocked_pattern_findings(label, path.read_text(encoding="utf-8")))

    return findings


def validate_android_products_template(
    path: Path,
    *,
    product_name: str,
    product_makefile: str,
) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    if "PRODUCT_MAKEFILES :=" not in text:
        findings.append("AndroidProducts template must declare PRODUCT_MAKEFILES")
    if f"$(LOCAL_DIR)/{product_makefile}" not in text:
        findings.append("AndroidProducts template must reference the GOFFY product makefile")
    if "COMMON_LUNCH_CHOICES :=" not in text:
        findings.append("AndroidProducts template must declare COMMON_LUNCH_CHOICES")
    if f"{product_name}-userdebug" not in text:
        findings.append(
            "AndroidProducts template must expose only the GOFFY userdebug lunch choice"
        )
    if "-eng" in text:
        findings.append("AndroidProducts template must not expose eng lunch choices")
    return findings


def validate_product_makefile_template(
    path: Path,
    *,
    product_name: str,
    required_package_makefile: str,
) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    if "$(SRC_TARGET_DIR)/product/handheld_system.mk" not in text:
        findings.append("product makefile must inherit handheld_system.mk")
    if "$(SRC_TARGET_DIR)/product/telephony_system.mk" not in text:
        findings.append("product makefile must inherit telephony_system.mk")
    if f"$(LOCAL_DIR)/{required_package_makefile}" not in text:
        findings.append("product makefile must inherit the GOFFY package list")
    if f"PRODUCT_NAME := {product_name}" not in text:
        findings.append("product makefile PRODUCT_NAME mismatch")
    if "PRODUCT_DEVICE := generic" not in text:
        findings.append("product makefile must keep PRODUCT_DEVICE generic")
    if "PRODUCT_BRAND := GOFFY" not in text:
        findings.append("product makefile must set PRODUCT_BRAND to GOFFY")
    if "PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := strict" not in text:
        findings.append("product makefile must enforce artifact path requirements")
    return findings


def validate_packages_makefile_template(
    path: Path,
    *,
    required_module: str,
) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    if "PRODUCT_PACKAGES +=" not in text:
        findings.append("packages makefile must declare PRODUCT_PACKAGES")
    if required_module not in package_lines(text):
        findings.append("packages makefile must include GoffyOS")
    return findings


def validate_system_app_descriptor(path: Path) -> list[str]:
    descriptor = load_descriptor(path)
    findings: list[str] = []
    if descriptor.get("schema_version") != SYSTEM_APP_SCHEMA_VERSION:
        findings.append("system app descriptor schema_version mismatch")
    if descriptor.get("module_name") != REQUIRED_MODULE:
        findings.append("system app descriptor module_name must be GoffyOS")
    if descriptor.get("privileged") is not False:
        findings.append("system app descriptor must remain non-privileged")
    if descriptor.get("platform_signed") is not False:
        findings.append("system app descriptor must not request platform signing")
    if descriptor.get("privileged_permission_allowlist") != []:
        findings.append("system app descriptor privileged allowlist must remain empty")
    return findings


def blocked_pattern_findings(label: str, text: str) -> list[str]:
    lower_text = text.lower()
    findings: list[str] = []
    for pattern in BLOCKED_TEMPLATE_PATTERNS:
        haystack = lower_text if pattern.islower() else text
        needle = pattern if not pattern.islower() else pattern.lower()
        if needle in haystack:
            findings.append(f"{label} must not contain {pattern}")
    return findings


def package_lines(text: str) -> set[str]:
    packages: set[str] = set()
    collecting = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("PRODUCT_PACKAGES +="):
            collecting = True
            line = line.removeprefix("PRODUCT_PACKAGES +=").strip()
        if collecting:
            for token in line.replace("\\", " ").split():
                packages.add(token)
            if not raw_line.rstrip().endswith("\\"):
                collecting = False
    return packages


def load_descriptor(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ROM product overlay descriptor must be a JSON object")
    return payload


def string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def relative_repo_path(value: object, *, root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return root / path


def aosp_template_filename(path: Path | None) -> str:
    if path is None:
        return ""
    return path.name.removesuffix(".template")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GOFFY ROM product overlay templates.",
    )
    parser.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        findings = validate_rom_product_overlay(descriptor_path=args.descriptor)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("GOFFY ROM product overlay validation failed")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("GOFFY ROM product overlay validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
