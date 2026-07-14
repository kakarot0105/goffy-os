from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import scripts.run_moto_g_usb_setup as usb_setup
from scripts.run_moto_g_usb_setup import (
    CommandResult,
    StepStatus,
    UsbSetupStep,
    build_report,
    main,
    render_json,
    render_text,
    setup_commands,
)
from scripts.verify_moto_g_readiness import ReadinessCheck, ReadinessReport


def ready_report(root: Path, *, reverse_ok: bool = True) -> ReadinessReport:
    return ReadinessReport(
        checks=(
            ReadinessCheck("android", "JDK", True, "ready", ""),
            ReadinessCheck("android", "adb", True, "ready", ""),
            ReadinessCheck("device", "Authorized Android device", True, "authorized:1", ""),
            ReadinessCheck(
                "device",
                "Hub USB reverse",
                reverse_ok,
                "tcp:8787 reverse is active" if reverse_ok else "tcp:8787 reverse missing",
                "Run `adb reverse tcp:8787 tcp:8787`.",
            ),
            ReadinessCheck("hub", "Hub health endpoint", True, "status:ok", ""),
            ReadinessCheck("hub", "Hub protocol version", True, "protocolVersion:0.2.0", ""),
            ReadinessCheck("hub", "Hub tool health", True, "healthy:1; unavailable:0", ""),
            ReadinessCheck("hub", "Hub tool access", True, "toolAccess:enabled", ""),
            ReadinessCheck("android", "Debug APK", True, str(root / "app-debug.apk"), ""),
        ),
        repo_root=root,
    )


def patch_setup_readiness(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[Path], ReadinessReport],
) -> None:
    monkeypatch.setattr(
        usb_setup,
        "collect_setup_readiness",
        lambda *, root, adb, runner, timeout_seconds: factory(root),
    )


def test_plan_mode_never_executes_device_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_setup_readiness(monkeypatch, ready_report)
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(
        root=tmp_path,
        runner=runner,
    )

    assert report.ok
    assert not report.setup_complete
    assert not report.executed
    assert seen == []
    assert [step.status for step in report.steps] == [StepStatus.PLANNED, StepStatus.PLANNED]


def test_execute_requires_explicit_device_mutation_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(root=tmp_path, execute=True)

    assert not report.ok
    assert report.readiness_blockers == ("missing explicit --confirm-device-mutation",)
    assert all(step.status is StepStatus.PLANNED for step in report.steps)


def test_execute_blocks_on_readiness_failures_except_reverse_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def blocked(root: Path) -> ReadinessReport:
        report = ready_report(root, reverse_ok=False)
        return ReadinessReport(
            checks=(
                *report.checks,
                ReadinessCheck("hub", "Hub tool access", False, "toolAccess:disabled", "pair"),
            ),
            repo_root=root,
        )

    patch_setup_readiness(monkeypatch, blocked)
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert "hub/Hub tool access" in report.readiness_blockers
    assert "device/Hub USB reverse" not in report.readiness_blockers


def test_execute_blocks_non_checkout_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    other_root = tmp_path / "other"
    trusted_root.mkdir()
    other_root.mkdir()
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=other_root,
        execute=True,
        confirm_device_mutation=True,
        trusted_root=trusted_root,
    )

    assert not report.ok
    assert report.readiness_blockers == (
        "repo-root/mutating mode only supports the checked-out GOFFY repository root",
    )
    assert all(step.status is StepStatus.PLANNED for step in report.steps)


def test_execute_requires_trusted_sdk_adb_not_path_adb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path_adb = tmp_path / "path-adb"
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: path_adb)
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: None)

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.readiness_blockers == ("device/trusted SDK adb executable",)
    assert report.steps[0].command[0] == str(path_adb)


def test_missing_trusted_adb_never_runs_device_commands(tmp_path: Path) -> None:
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    checks = usb_setup.collect_trusted_device_checks(
        root=tmp_path,
        adb=None,
        runner=runner,
    )

    assert seen == []
    assert checks[0].name == "trusted SDK adb executable"
    assert not checks[0].ok


def test_trusted_adb_path_uses_sdk_platform_tools_not_path(tmp_path: Path) -> None:
    sdk_root = tmp_path / "sdk"
    sdk_adb = sdk_root / "platform-tools" / "adb"
    path_adb = tmp_path / "bin" / "adb"
    sdk_adb.parent.mkdir(parents=True)
    path_adb.parent.mkdir()
    sdk_adb.write_text("#!/bin/sh\n", encoding="utf-8")
    path_adb.write_text("#!/bin/sh\n", encoding="utf-8")
    sdk_adb.chmod(0o755)
    path_adb.chmod(0o755)

    adb = usb_setup.trusted_adb_path({"ANDROID_HOME": str(sdk_root), "PATH": str(path_adb.parent)})

    assert adb == sdk_adb.resolve()


def test_execute_runs_fixed_reverse_then_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "adb"
    seen: list[tuple[str, ...]] = []
    patch_setup_readiness(monkeypatch, lambda root: ready_report(root, reverse_ok=False))
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: adb)
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "ok", "")

    # Replace the verification helper directly to keep this test focused on fixed commands.
    monkeypatch.setattr(
        usb_setup,
        "verify_reverse_step",
        lambda root, adb, runner, timeout_seconds: UsbSetupStep(
            name="Verify Hub USB reverse",
            status=StepStatus.OK,
            detail="tcp:8787 reverse is active",
        ),
    )

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    reverse, install = setup_commands(tmp_path, adb)
    assert report.ok
    assert report.setup_complete
    assert report.executed
    assert report.readiness_ok
    assert seen == [reverse, install]
    assert [step.status for step in report.steps] == [
        StepStatus.OK,
        StepStatus.OK,
        StepStatus.OK,
    ]


def test_reverse_verification_failure_skips_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, ...]] = []
    patch_setup_readiness(monkeypatch, lambda root: ready_report(root, reverse_ok=False))
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(
        usb_setup,
        "verify_reverse_step",
        lambda root, adb, runner, timeout_seconds: UsbSetupStep(
            name="Verify Hub USB reverse",
            status=StepStatus.FAIL,
            detail="tcp:8787 reverse missing",
        ),
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert not report.setup_complete
    assert seen == [("/opt/android/adb", "reverse", "tcp:8787", "tcp:8787")]
    assert report.steps[1].status is StepStatus.FAIL
    assert report.steps[2].status is StepStatus.SKIP


def test_reverse_verification_uses_configured_timeout(
    tmp_path: Path,
) -> None:
    seen_timeouts: list[int] = []
    seen_commands: list[tuple[str, ...]] = []
    adb = tmp_path / "sdk" / "platform-tools" / "adb"

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen_commands.append(tuple(command))
        seen_timeouts.append(timeout)
        if tuple(command[1:]) == ("devices", "-l"):
            return CommandResult(0, "abc123 device product:moto\n", "")
        if tuple(command[1:]) == ("reverse", "--list"):
            return CommandResult(0, "abc123 tcp:8787 tcp:8787\n", "")
        return CommandResult(1, "", "unexpected command")

    step = usb_setup.verify_reverse_step(
        tmp_path,
        adb=adb,
        runner=runner,
        timeout_seconds=42,
    )

    assert step.status is StepStatus.OK
    assert seen_timeouts == [42, 42]
    assert seen_commands == [
        (str(adb), "devices", "-l"),
        (str(adb), "reverse", "--list"),
    ]


def test_failed_reverse_skips_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_setup_readiness(monkeypatch, lambda root: ready_report(root, reverse_ok=False))
    monkeypatch.setattr(usb_setup, "discover_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(usb_setup, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        return CommandResult(1, "", "failed")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.steps[0].status is StepStatus.FAIL
    assert report.steps[-1].status is StepStatus.SKIP


def test_renderers_redact_paths_and_mark_mutating_steps(tmp_path: Path) -> None:
    report = usb_setup.UsbSetupReport(
        executed=False,
        readiness_ok=False,
        readiness_blockers=(str(tmp_path / "secret"),),
        steps=(
            UsbSetupStep(
                name="Install debug APK",
                status=StepStatus.PLANNED,
                command=("/opt/android/adb", "install", str(tmp_path / "apk")),
                mutates_device=True,
                detail=str(tmp_path / "detail"),
            ),
        ),
        repo_root=tmp_path,
    )

    rendered = render_text(report)
    payload = json.loads(render_json(report))

    assert str(tmp_path) not in rendered
    assert payload["steps"][0]["mutates_device"] is True
    assert payload["setupComplete"] is False
    assert payload["steps"][0]["command"][-1] == "<repo>/apk"


def test_readiness_json_preserves_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def blocked(root: Path) -> ReadinessReport:
        return ReadinessReport(
            checks=(ReadinessCheck("hub", "Hub health endpoint", False, "down", "start Hub"),),
            repo_root=root,
        )

    monkeypatch.setattr(usb_setup, "collect_readiness_report", blocked)

    assert main(["--repo-root", str(tmp_path), "--readiness-json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
