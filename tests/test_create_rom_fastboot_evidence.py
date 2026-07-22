from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from scripts.create_rom_fastboot_evidence import (
    CommandResult,
    FastbootStatus,
    command_evidence,
    create_fastboot_evidence,
    main,
    parse_fastboot_devices,
    render_json,
    trusted_fastboot_path,
)

SERIAL = "ZY32LBQLMQ"


def test_host_ready_check_does_not_require_bootloader_mode(tmp_path: Path) -> None:
    sdk = write_sdk_fastboot(tmp_path)

    evidence = create_fastboot_evidence(
        root=tmp_path,
        env={"ANDROID_HOME": str(sdk)},
        runner=runner_for(
            version=f"fastboot version 36.0.0-12345678\nInstalled as {sdk}/fastboot\n"
        ),
    )
    payload = render_json(evidence)

    assert evidence.ok
    assert evidence.status is FastbootStatus.HOST_READY
    assert evidence.destructive_actions == "withheld"
    assert evidence.host["fastboot"] == "available"
    assert evidence.host["fastboot_path"] == "<android-sdk>/platform-tools/fastboot"
    command_stdout = evidence.commands[0]["stdout"]
    assert isinstance(command_stdout, str)
    assert command_stdout.endswith("Installed as <path>")
    assert evidence.manual_bootloader_check["requested"] is False
    assert any("manual bootloader visibility was not checked" in item for item in evidence.warnings)
    assert str(sdk) not in payload
    assert SERIAL not in payload


def test_manual_bootloader_check_redacts_visible_fastboot_serial(tmp_path: Path) -> None:
    sdk = write_sdk_fastboot(tmp_path)

    evidence = create_fastboot_evidence(
        root=tmp_path,
        env={"ANDROID_HOME": str(sdk)},
        runner=runner_for(devices=f"{SERIAL}\tfastboot\n"),
        manual_bootloader_check=True,
    )
    payload = render_json(evidence)

    assert evidence.ok
    assert evidence.status is FastbootStatus.MANUAL_BOOTLOADER_VISIBLE
    assert evidence.manual_bootloader_check["bootloader_device_visible"] is True
    assert evidence.manual_bootloader_check["bootloader_device_count"] == 1
    assert SERIAL not in payload
    assert "<device-serial>\\tfastboot" in payload


def test_manual_bootloader_check_blocks_when_no_device_is_visible(tmp_path: Path) -> None:
    sdk = write_sdk_fastboot(tmp_path)

    evidence = create_fastboot_evidence(
        root=tmp_path,
        env={"ANDROID_HOME": str(sdk)},
        runner=runner_for(devices=""),
        manual_bootloader_check=True,
    )

    assert not evidence.ok
    assert evidence.status is FastbootStatus.BLOCKED
    assert "no manually booted fastboot device is visible" in evidence.blockers


def test_missing_trusted_fastboot_blocks(tmp_path: Path) -> None:
    sdk = tmp_path / "sdk"
    (sdk / "platform-tools").mkdir(parents=True)

    evidence = create_fastboot_evidence(root=tmp_path, env={"ANDROID_HOME": str(sdk)})

    assert not evidence.ok
    assert evidence.status is FastbootStatus.BLOCKED
    assert "trusted Android SDK fastboot executable is unavailable" in evidence.blockers


def test_trusted_fastboot_path_rejects_symlinked_binary(tmp_path: Path) -> None:
    sdk = tmp_path / "sdk"
    platform_tools = sdk / "platform-tools"
    platform_tools.mkdir(parents=True)
    outside = tmp_path / "outside-fastboot"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o755)
    (platform_tools / "fastboot").symlink_to(outside)

    assert trusted_fastboot_path({"ANDROID_HOME": str(sdk)}) is None


def test_command_evidence_redacts_windows_paths() -> None:
    result = command_evidence(
        "fastboot --version",
        CommandResult(
            0,
            "fastboot version 36.0.0\n"
            "Installed as "
            "C:\\Users\\alice\\AppData\\Local\\Android\\Sdk\\platform-tools\\fastboot.exe\n",
            "using \\\\host\\share\\android\\fastboot.exe\n",
        ),
    )

    assert "C:\\Users\\alice" not in str(result)
    assert "\\\\host\\share" not in str(result)
    assert result["stdout"] == "fastboot version 36.0.0\nInstalled as <path>"
    assert result["stderr"] == "using <path>"


def test_fastboot_devices_parser_accepts_only_fastboot_lines() -> None:
    assert parse_fastboot_devices(f"{SERIAL}\tfastboot\nignored\tdevice\n") == (SERIAL,)


def test_command_evidence_rejects_destructive_fastboot_labels() -> None:
    with pytest.raises(ValueError, match="read-only"):
        command_evidence("fastboot flash boot boot.img", CommandResult(0, "", ""))


def test_command_evidence_rejects_unlisted_fastboot_labels() -> None:
    with pytest.raises(ValueError, match="read-only"):
        command_evidence("fastboot getvar all", CommandResult(0, "", ""))


def test_cli_writes_only_under_validation_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdk = write_sdk_fastboot(tmp_path)
    allowed = tmp_path / ".goffy-validation" / "rom-fastboot-evidence.json"
    blocked = tmp_path / "rom-fastboot-evidence.json"

    monkeypatch.setattr(
        "scripts.create_rom_fastboot_evidence.default_command_runner",
        runner_for(),
    )
    monkeypatch.setattr("scripts.create_rom_fastboot_evidence.ROOT", tmp_path)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))

    assert main(["--output", str(allowed)]) == 0
    assert json.loads(allowed.read_text(encoding="utf-8"))["destructive_actions"] == "withheld"
    assert main(["--output", str(blocked)]) == 1
    assert not blocked.exists()


def write_sdk_fastboot(tmp_path: Path) -> Path:
    sdk = tmp_path / "sdk"
    platform_tools = sdk / "platform-tools"
    platform_tools.mkdir(parents=True)
    fastboot = platform_tools / "fastboot"
    fastboot.write_text("#!/bin/sh\n", encoding="utf-8")
    fastboot.chmod(0o755)
    return sdk


def runner_for(
    *,
    version: str = "fastboot version 36.0.0-12345678\n",
    devices: str = "",
) -> Callable[[Sequence[str], Path, int], CommandResult]:
    def runner(command: Sequence[str], cwd: Path, timeout_seconds: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized[-1] == "--version":
            return CommandResult(0, version, "")
        if normalized[-1] == "devices":
            return CommandResult(0, devices, "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    return runner
