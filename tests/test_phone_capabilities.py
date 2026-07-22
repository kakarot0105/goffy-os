import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from goffy_protocol import ExecutionTarget, PermissionLevel, ToolCapability

FIXTURE_PATH = Path(__file__).parents[1] / "shared" / "fixtures" / "phone-tool-capabilities.json"
EXPECTED_PERMISSIONS = {
    "phone.battery.status": PermissionLevel.SAFE,
    "phone.device.info": PermissionLevel.SAFE,
    "phone.flashlight.set": PermissionLevel.CONFIRM,
    "phone.memory.forget_all": PermissionLevel.CONFIRM,
    "phone.memory.list": PermissionLevel.SAFE,
    "phone.memory.remember": PermissionLevel.CONFIRM,
    "phone.note.create": PermissionLevel.CONFIRM,
    "phone.ocr.read": PermissionLevel.SAFE,
    "phone.qr.read": PermissionLevel.SAFE,
    "phone.timer.create": PermissionLevel.CONFIRM,
}


def test_phone_capability_fixture_is_typed_sorted_and_permission_preserving() -> None:
    raw_capabilities = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    capabilities = [ToolCapability.model_validate(item) for item in raw_capabilities]

    assert [capability.name for capability in capabilities] == sorted(EXPECTED_PERMISSIONS)
    assert len(capabilities) == len(EXPECTED_PERMISSIONS)
    for capability in capabilities:
        assert capability.meta.execution_target is ExecutionTarget.PHONE
        assert capability.meta.permission is EXPECTED_PERMISSIONS[capability.name]
        assert capability.annotations.destructive_hint is (
            capability.name == "phone.memory.forget_all"
        )
        assert capability.annotations.open_world_hint is False
        if capability.meta.permission is PermissionLevel.SAFE:
            assert capability.annotations.read_only_hint is True
            assert capability.annotations.idempotent_hint is True
        else:
            assert capability.annotations.read_only_hint is False

        Draft202012Validator.check_schema(capability.input_schema)
        Draft202012Validator.check_schema(capability.output_schema)


def test_phone_capability_schemas_accept_canonical_examples() -> None:
    capabilities = {
        item["name"]: ToolCapability.model_validate(item)
        for item in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    }
    examples = {
        "phone.battery.status": ({}, {"levelPercent": 75, "charging": True}),
        "phone.device.info": (
            {},
            {
                "manufacturer": "motorola",
                "model": "moto g",
                "androidRelease": "15",
                "sdkInt": 35,
                "goffySystemApp": False,
                "goffyHomeCandidate": True,
                "goffyDefaultHome": False,
            },
        ),
        "phone.flashlight.set": (
            {"enabled": True},
            {"enabled": True, "stateChanged": True},
        ),
        "phone.note.create": (
            {"text": "Buy milk"},
            {"noteId": 1, "text": "Buy milk", "createdAtEpochMillis": 1},
        ),
        "phone.memory.forget_all": (
            {},
            {"deletedCount": 1, "remainingCount": 0},
        ),
        "phone.memory.list": (
            {},
            {
                "status": "available",
                "count": 1,
                "truncated": False,
                "entries": [
                    {
                        "memoryId": 1,
                        "text": "favorite project is GOFFY",
                        "createdAtEpochMillis": 1,
                        "provenance": "user_approved_phone_command",
                    }
                ],
            },
        ),
        "phone.memory.remember": (
            {"text": "favorite project is GOFFY"},
            {
                "memoryId": 1,
                "text": "favorite project is GOFFY",
                "createdAtEpochMillis": 1,
                "provenance": "user_approved_phone_command",
            },
        ),
        "phone.ocr.read": (
            {},
            {
                "status": "available",
                "script": "latin",
                "characterCount": 28,
                "characterCountTruncated": False,
                "lineCount": 2,
                "lineCountTruncated": False,
                "preview": "GOFFY OS Observe Plan Act",
                "previewTruncated": False,
                "redacted": False,
            },
        ),
        "phone.qr.read": (
            {},
            {
                "status": "available",
                "contentType": "url",
                "characterCount": 42,
                "characterCountTruncated": False,
                "preview": "https://example.com/...",
                "previewTruncated": False,
                "redacted": False,
            },
        ),
        "phone.timer.create": (
            {"durationSeconds": 30, "skipClockUi": True},
            {
                "durationSeconds": 30,
                "clockPackage": "com.google.android.deskclock",
                "clockActivity": "com.google.android.deskclock.TimerActivity",
                "systemApplication": True,
                "skipClockUiRequested": True,
                "systemAction": "android.intent.action.SET_TIMER",
            },
        ),
    }

    for name, (arguments, result) in examples.items():
        Draft202012Validator(capabilities[name].input_schema).validate(arguments)
        Draft202012Validator(capabilities[name].output_schema).validate(result)


def test_phone_capability_schemas_reject_extra_and_policy_mismatched_arguments() -> None:
    capabilities = {
        item["name"]: ToolCapability.model_validate(item)
        for item in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    }
    battery_arguments = {"unexpected": True}
    timer_arguments = {"durationSeconds": 30, "skipClockUi": False}
    flashlight_arguments = {"enabled": "yes"}

    with pytest.raises(ValidationError):
        Draft202012Validator(capabilities["phone.battery.status"].input_schema).validate(
            battery_arguments
        )
    with pytest.raises(ValidationError):
        Draft202012Validator(capabilities["phone.timer.create"].input_schema).validate(
            timer_arguments
        )
    with pytest.raises(ValidationError):
        Draft202012Validator(capabilities["phone.flashlight.set"].input_schema).validate(
            flashlight_arguments
        )
