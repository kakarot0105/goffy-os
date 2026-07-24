from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_rom_feature_payload import validate_rom_feature_payload


def system_app_descriptor() -> dict[str, object]:
    return {
        "schema_version": "goffy.rom-system-app.v1",
        "module_name": "GoffyOS",
        "privileged": False,
        "platform_signed": False,
        "privileged_permission_allowlist": [],
        "home_surface": {"policy": "user_selectable_default_home"},
    }


def product_overlay_descriptor() -> dict[str, object]:
    return {
        "schema_version": "goffy.rom-product-overlay.v1",
        "required_module": "GoffyOS",
        "flashable": False,
        "destructive_actions_included": False,
    }


def feature_payload() -> dict[str, object]:
    return {
        "schema_version": "goffy.rom-feature-payload.v1",
        "payload_name": "GOFFY ROM-0 Jarvis Payload",
        "target_stage": "ROM-0",
        "default_performance_mode": "GOFFY LITE",
        "system_app_descriptor": "rom/system-app/goffy-system-app.json",
        "product_overlay_descriptor": "rom/product/goffy-product-overlay.json",
        "rom0_flashable": False,
        "privileged": False,
        "platform_signed": False,
        "rom_destructive_actions_included": False,
        "app_private_destructive_tools_included": True,
        "requires_user_selected_home": True,
        "local_model_policy": "disabled_by_default_observe_only",
        "source_basis": [
            "AOSP product makefiles include modules through PRODUCT_PACKAGES.",
            "AOSP AndroidProducts.mk declares product makefiles and userdebug lunch choices.",
            "Android privileged permission allowlists are required only for privileged apps.",
            "Android GSI work requires bootloader, rollback, and original ROM evidence.",
            "Android DSU is a reversible guest-OS staging path only when supported.",
        ],
        "features": [
            feature(
                "agent_loop_timeline",
                "android/app/src/main/java/dev/goffy/os/agent/GoffyTaskReducer.kt",
                targets=["PHONE", "MAC", "CLOUD"],
            ),
            feature(
                "charging_dock_awake",
                "android/app/src/main/java/dev/goffy/os/GoffyDockAwakePolicy.kt",
            ),
            feature(
                "foreground_voice_camera",
                "android/app/src/main/java/dev/goffy/os",
                permissions=["android.permission.CAMERA", "android.permission.RECORD_AUDIO"],
                tools=["phone.ocr.read", "phone.qr.read"],
                runtime_policy="foreground_user_approved_only_no_image_or_audio_persistence",
            ),
            feature(
                "home_surface",
                "android/app/src/main/java/dev/goffy/os/MainActivity.kt",
                tools=["phone.device.info"],
            ),
            feature(
                "local_intent_fallback",
                "android/app/src/main/java/dev/goffy/os/localmodel",
                runtime_policy="disabled_by_default_observe_only_non_authoritative",
            ),
            feature(
                "phone_tools",
                "android/app/src/main/java/dev/goffy/os/phone",
                permissions=["android.permission.CAMERA", "com.android.alarm.permission.SET_ALARM"],
                tools=[
                    "phone.battery.status",
                    "phone.device.info",
                    "phone.flashlight.set",
                    "phone.memory.forget",
                    "phone.memory.forget_all",
                    "phone.memory.list",
                    "phone.memory.remember",
                    "phone.memory.update",
                    "phone.note.create",
                    "phone.ocr.read",
                    "phone.qr.read",
                    "phone.timer.create",
                ],
                app_private_destructive_tools=[
                    "phone.memory.forget",
                    "phone.memory.forget_all",
                ],
                runtime_policy="foreground deterministic phone tools with exact approval",
            ),
            feature(
                "rom_status",
                "hub/src/goffy_hub/tools/rom_status.py",
                targets=["MAC"],
                tools=["goffy.rom.checklist", "goffy.rom.features", "goffy.rom.status"],
            ),
            feature(
                "secure_mac_hub",
                "android/app/src/main/java/dev/goffy/os/hub",
                targets=["MAC"],
                permissions=["android.permission.INTERNET"],
                tools=[
                    "mac.system_info",
                    "goffy.rom.checklist",
                    "goffy.rom.features",
                    "goffy.rom.status",
                ],
            ),
        ],
        "blocked_rom_actions": [
            "background_camera",
            "background_microphone",
            "disable_verity",
            "flash_image",
            "platform_signing",
            "privileged_permission_grants",
            "reboot_bootloader",
            "root_or_su",
            "unlock_bootloader",
            "unrestricted_shell",
            "wipe_data",
        ],
    }


def feature(
    feature_id: str,
    source_module: str,
    *,
    targets: list[str] | None = None,
    permissions: list[str] | None = None,
    tools: list[str] | None = None,
    runtime_policy: str = "foreground user visible and audited",
    app_private_destructive_tools: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": feature_id,
        "title": feature_id.replace("_", " ").title(),
        "included_in_rom0": True,
        "source_module": source_module,
        "execution_targets": targets or ["PHONE"],
        "mcp_tools": tools or [],
        "android_permissions": permissions or [],
        "runtime_policy": runtime_policy,
        "audit_policy": "terminal_task_visible",
        "privileged_required": False,
        "foreground_only": True,
        "background_access": False,
        "rom_destructive_action": False,
        "app_private_destructive_tools": app_private_destructive_tools or [],
    }


def write_fixture(tmp_path: Path, payload: dict[str, object]) -> Path:
    descriptor_path = tmp_path / "rom" / "features" / "goffy-rom-features.json"
    system_app_path = tmp_path / "rom" / "system-app" / "goffy-system-app.json"
    product_overlay_path = tmp_path / "rom" / "product" / "goffy-product-overlay.json"
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    system_app_path.parent.mkdir(parents=True, exist_ok=True)
    product_overlay_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(payload), encoding="utf-8")
    system_app_path.write_text(json.dumps(system_app_descriptor()), encoding="utf-8")
    product_overlay_path.write_text(json.dumps(product_overlay_descriptor()), encoding="utf-8")

    for item in payload.get("features", []):
        if not isinstance(item, dict):
            continue
        source_module = item.get("source_module")
        if not isinstance(source_module, str):
            continue
        source_path = tmp_path / source_module
        source_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.suffix:
            source_path.write_text("placeholder", encoding="utf-8")
        else:
            source_path.mkdir(parents=True, exist_ok=True)
    android_tool_names_path = (
        tmp_path
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "dev"
        / "goffy"
        / "os"
        / "protocol"
        / "GoffyToolNames.kt"
    )
    android_tool_names_path.parent.mkdir(parents=True, exist_ok=True)
    android_tool_names_path.write_text(
        "\n".join(
            f'const val PHONE_TEST_{index}_TOOL = "{tool}"'
            for index, tool in enumerate(
                sorted(
                    {
                        tool
                        for item in payload.get("features", [])
                        if isinstance(item, dict)
                        for tool in item.get("mcp_tools", [])
                        if isinstance(tool, str) and tool.startswith("phone.")
                    }
                )
            )
        ),
        encoding="utf-8",
    )
    return descriptor_path


def test_rom_feature_payload_accepts_current_safe_shape(tmp_path: Path) -> None:
    descriptor_path = write_fixture(tmp_path, feature_payload())

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert findings == []


def test_rom_feature_payload_rejects_privileged_or_flashable_claims(tmp_path: Path) -> None:
    payload = feature_payload()
    payload["rom0_flashable"] = True
    payload["privileged"] = True
    payload["platform_signed"] = True
    payload["rom_destructive_actions_included"] = True
    payload["app_private_destructive_tools_included"] = False
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert "ROM-0 feature payload must not claim to be flashable" in findings
    assert "ROM-0 feature payload must remain non-privileged" in findings
    assert "ROM-0 feature payload must not request platform signing" in findings
    assert "ROM-0 feature payload must not include ROM/system destructive actions" in findings
    assert any(
        "app_private_destructive_tools_included must truthfully acknowledge" in finding
        for finding in findings
    )


def test_rom_feature_payload_rejects_feature_authority_creep(tmp_path: Path) -> None:
    payload = feature_payload()
    features = payload["features"]
    assert isinstance(features, list)
    unsafe = dict(features[0])
    unsafe["privileged_required"] = True
    unsafe["background_access"] = True
    unsafe["rom_destructive_action"] = True
    unsafe["foreground_only"] = False
    features[0] = unsafe
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert "agent_loop_timeline: privileged_required must remain false" in findings
    assert "agent_loop_timeline: background_access must remain false" in findings
    assert "agent_loop_timeline: rom_destructive_action must remain false" in findings
    assert "agent_loop_timeline: foreground_only must remain true" in findings


def test_rom_feature_payload_rejects_unreviewed_tools_and_permissions(tmp_path: Path) -> None:
    payload = feature_payload()
    features = payload["features"]
    assert isinstance(features, list)
    unsafe = dict(features[0])
    unsafe["mcp_tools"] = ["mac.shell.exec"]
    unsafe["android_permissions"] = ["android.permission.READ_SMS"]
    unsafe["execution_targets"] = ["PHONE", "ROOT"]
    features[0] = unsafe
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert "agent_loop_timeline: execution_targets contain unsupported targets" in findings
    assert (
        "agent_loop_timeline: android_permissions not approved: ['android.permission.READ_SMS']"
        in findings
    )
    assert "agent_loop_timeline: mcp_tools not in ROM-0 allowlist: ['mac.shell.exec']" in findings


def test_rom_feature_payload_rejects_omitted_feature_tools_and_permissions(
    tmp_path: Path,
) -> None:
    payload = feature_payload()
    features = payload["features"]
    assert isinstance(features, list)
    phone_tools = next(
        item for item in features if isinstance(item, dict) and item["id"] == "phone_tools"
    )
    phone_tools["mcp_tools"] = ["phone.battery.status"]
    camera_tools = next(
        item
        for item in features
        if isinstance(item, dict) and item["id"] == "foreground_voice_camera"
    )
    camera_tools["android_permissions"] = []
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert any("phone_tools: mcp_tools must be exactly" in finding for finding in findings)
    assert any(
        "foreground_voice_camera: android_permissions must be exactly" in finding
        for finding in findings
    )


def test_rom_feature_payload_rejects_phone_source_tool_drift(tmp_path: Path) -> None:
    descriptor_path = write_fixture(tmp_path, feature_payload())
    tool_names_path = (
        tmp_path
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "dev"
        / "goffy"
        / "os"
        / "protocol"
        / "GoffyToolNames.kt"
    )
    tool_names_path.write_text(
        tool_names_path.read_text(encoding="utf-8")
        + '\nconst val PHONE_NEW_TOOL = "phone.future.tool"\n',
        encoding="utf-8",
    )

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert any(
        "descriptor PHONE tools must match Android GoffyToolNames.kt constants" in finding
        for finding in findings
    )


def test_rom_feature_payload_requires_foreground_policy_for_camera_or_microphone(
    tmp_path: Path,
) -> None:
    payload = feature_payload()
    features = payload["features"]
    assert isinstance(features, list)
    unsafe = dict(features[2])
    unsafe["runtime_policy"] = "silent capture"
    features[2] = unsafe
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert (
        "foreground_voice_camera: camera/microphone permissions require foreground policy"
        in findings
    )


def test_rom_feature_payload_requires_exact_feature_set(tmp_path: Path) -> None:
    payload = feature_payload()
    features = payload["features"]
    assert isinstance(features, list)
    features.pop()
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert any("features must exactly cover ROM-0 feature ids" in finding for finding in findings)


def test_rom_feature_payload_rejects_system_app_privilege_drift(tmp_path: Path) -> None:
    descriptor_path = write_fixture(tmp_path, feature_payload())
    system_app_path = tmp_path / "rom" / "system-app" / "goffy-system-app.json"
    unsafe = system_app_descriptor() | {
        "privileged": True,
        "platform_signed": True,
        "privileged_permission_allowlist": ["android.permission.WRITE_SECURE_SETTINGS"],
    }
    system_app_path.write_text(json.dumps(unsafe), encoding="utf-8")

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert "system_app_descriptor must remain non-privileged" in findings
    assert "system_app_descriptor must not request platform signing" in findings
    assert "system_app_descriptor privileged allowlist must remain empty" in findings


def test_rom_feature_payload_requires_required_blocked_actions(tmp_path: Path) -> None:
    payload = feature_payload()
    payload["blocked_rom_actions"] = ["unrestricted_shell"]
    descriptor_path = write_fixture(tmp_path, payload)

    findings = validate_rom_feature_payload(descriptor_path=descriptor_path, root=tmp_path)

    assert any("blocked_actions missing required entries" in finding for finding in findings)
