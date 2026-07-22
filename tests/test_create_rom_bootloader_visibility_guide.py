from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.create_rom_bootloader_visibility_guide import (
    FORBIDDEN_COMMAND_TERMS,
    GuideStatus,
    StepStatus,
    build_visibility_guide,
    main,
    render_json,
    render_markdown,
)


def test_visibility_guide_blocks_until_host_fastboot_evidence_exists(tmp_path: Path) -> None:
    guide = build_visibility_guide(root=tmp_path)
    rendered = render_markdown(guide).lower()
    actions = {step.step_id: step for step in guide.steps}

    assert not guide.ok
    assert guide.status is GuideStatus.HOST_EVIDENCE_MISSING
    assert guide.destructive_actions == "withheld"
    assert "create host fastboot evidence" in guide.blocked_by[0]
    assert actions["record_host_fastboot"].status is StepStatus.READY
    assert actions["manual_enter_bootloader"].status is StepStatus.BLOCKED
    assert actions["record_manual_fastboot_visibility"].status is StepStatus.BLOCKED
    assert "create_rom_fastboot_evidence.py" in rendered
    assert_forbidden_terms_absent(rendered)


def test_visibility_guide_accepts_host_ready_and_prompts_manual_check(
    tmp_path: Path,
) -> None:
    write_fastboot_evidence(tmp_path)

    guide = build_visibility_guide(root=tmp_path)
    rendered = render_markdown(guide)
    actions = {step.step_id: step for step in guide.steps}

    assert not guide.ok
    assert guide.status is GuideStatus.READY_FOR_MANUAL_BOOTLOADER_CHECK
    assert "manual bootloader-mode fastboot visibility has not been recorded" in guide.blocked_by
    assert actions["record_host_fastboot"].status is StepStatus.RECORDED
    assert actions["manual_enter_bootloader"].status is StepStatus.READY
    assert actions["record_manual_fastboot_visibility"].status is StepStatus.READY
    assert (
        ".venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check"
        in rendered
    )
    assert_forbidden_terms_absent(rendered.lower())


def test_visibility_guide_passes_after_manual_bootloader_visibility(
    tmp_path: Path,
) -> None:
    write_fastboot_evidence(tmp_path, manual_visible=True)

    guide = build_visibility_guide(root=tmp_path)
    actions = {step.step_id: step for step in guide.steps}

    assert guide.ok
    assert guide.status is GuideStatus.MANUAL_BOOTLOADER_VISIBLE
    assert guide.blocked_by == ()
    assert actions["record_host_fastboot"].status is StepStatus.RECORDED
    assert actions["manual_enter_bootloader"].status is StepStatus.RECORDED
    assert actions["record_manual_fastboot_visibility"].status is StepStatus.RECORDED
    assert actions["record_manual_fastboot_visibility"].safe_commands == ()


def test_visibility_guide_fails_closed_for_invalid_fastboot_evidence(
    tmp_path: Path,
) -> None:
    validation = tmp_path / ".goffy-validation"
    validation.mkdir()
    (validation / "rom-fastboot-evidence.json").write_text(
        json.dumps({"schema_version": "unexpected"}),
        encoding="utf-8",
    )

    guide = build_visibility_guide(root=tmp_path)
    payload = render_json(guide)

    assert not guide.ok
    assert guide.status is GuideStatus.FASTBOOT_EVIDENCE_INVALID
    assert "ROM fastboot evidence schema_version mismatch" in guide.blocked_by
    assert str(tmp_path) not in payload


def test_visibility_guide_rejects_input_outside_validation_dir(tmp_path: Path) -> None:
    outside = tmp_path / "rom-fastboot-evidence.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="under .goffy-validation"):
        build_visibility_guide(fastboot_evidence_json=outside, root=tmp_path)


def test_visibility_guide_redacts_absolute_input_evidence_path(tmp_path: Path) -> None:
    evidence = write_fastboot_evidence(tmp_path)

    guide = build_visibility_guide(fastboot_evidence_json=evidence.resolve(), root=tmp_path)
    payload = render_json(guide)

    assert guide.fastboot_evidence.path == ".goffy-validation/rom-fastboot-evidence.json"
    assert str(tmp_path) not in payload


def test_visibility_guide_cli_writes_outputs_only_under_validation_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_fastboot_evidence(tmp_path, manual_visible=True)
    allowed_json = tmp_path / ".goffy-validation" / "rom-bootloader-visibility-guide.json"
    allowed_md = tmp_path / ".goffy-validation" / "rom-bootloader-visibility-guide.md"
    blocked_json = tmp_path / "rom-bootloader-visibility-guide.json"

    monkeypatch.setattr("scripts.create_rom_bootloader_visibility_guide.ROOT", tmp_path)

    assert main(["--output", str(allowed_json), "--markdown-output", str(allowed_md)]) == 0
    assert json.loads(allowed_json.read_text(encoding="utf-8"))["ok"] is True
    assert allowed_md.read_text(encoding="utf-8").startswith(
        "# GOFFY ROM Bootloader Visibility Guide"
    )
    assert main(["--output", str(blocked_json), "--markdown-output", str(allowed_md)]) == 1
    assert not blocked_json.exists()


def write_fastboot_evidence(tmp_path: Path, *, manual_visible: bool = False) -> Path:
    validation = tmp_path / ".goffy-validation"
    validation.mkdir(exist_ok=True)
    path = validation / "rom-fastboot-evidence.json"
    commands = [
        {
            "label": "fastboot --version",
            "exit_code": 0,
            "timed_out": False,
            "stdout": "fastboot version 37.0.0-14910828\nInstalled as <path>",
            "stderr": "",
        }
    ]
    if manual_visible:
        commands.append(
            {
                "label": "fastboot devices",
                "exit_code": 0,
                "timed_out": False,
                "stdout": "<device-serial>\tfastboot",
                "stderr": "",
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-fastboot-evidence.v1",
                "generated_at": "2026-07-22T00:00:00+00:00",
                "ok": True,
                "status": "MANUAL_BOOTLOADER_VISIBLE" if manual_visible else "HOST_READY",
                "destructive_actions": "withheld",
                "host": {
                    "fastboot": "available",
                    "fastboot_path": "<android-sdk>/platform-tools/fastboot",
                    "fastboot_version": "37.0.0-14910828",
                },
                "manual_bootloader_check": {
                    "requested": manual_visible,
                    "bootloader_device_visible": manual_visible,
                    "bootloader_device_count": 1 if manual_visible else 0,
                    "serials_redacted": True,
                },
                "commands": commands,
                "blockers": [],
                "warnings": []
                if manual_visible
                else ["manual bootloader visibility was not checked; do not reboot automatically"],
            }
        ),
        encoding="utf-8",
    )
    return path


def assert_forbidden_terms_absent(text: str) -> None:
    for term in FORBIDDEN_COMMAND_TERMS:
        assert term not in text
