from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import scripts.setup_doctor as setup_doctor
from scripts.android_preflight import Check
from scripts.setup_doctor import (
    DEV_MODULES,
    DoctorCheck,
    DoctorReport,
    collect_doctor_report,
    collect_python_checks,
    main,
    render_json,
    render_text,
)

ROOT = Path(__file__).resolve().parents[1]


def test_python_checks_accept_supported_runtime_and_modules() -> None:
    checks = collect_python_checks(
        version_info=(3, 12, 4),
        executable="/opt/goffy-test/python",
        module_finder=lambda module: True,
    )

    assert all(check.ok for check in checks)
    assert checks[0].detail == "Python 3.12.4 at /opt/goffy-test/python"


def test_python_checks_report_missing_runtime_and_dev_modules() -> None:
    checks = collect_python_checks(
        version_info=(3, 11, 9),
        executable="/opt/goffy-test/python",
        module_finder=lambda module: module not in {"jsonschema", "ruff"},
    )

    assert not checks[0].ok
    assert not checks[1].ok
    assert "Python 3.12+" in checks[0].remediation
    assert "jsonschema" in checks[1].detail
    assert "ruff" in checks[1].detail


def test_python_dependency_contract_covers_verifier_and_test_imports() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_specs = [
        *pyproject["project"]["dependencies"],
        *pyproject["project"]["optional-dependencies"]["dev"],
    ]
    expected_packages = {package_name(spec) for spec in dependency_specs}

    assert set(DEV_MODULES) == expected_packages


def package_name(dependency_spec: str) -> str:
    return re.split(r"[\[<>=!~;,\s]", dependency_spec, maxsplit=1)[0].lower()


def test_doctor_report_includes_android_preflight_checks(tmp_path: Path) -> None:
    def android_collector(root: Path) -> list[Check]:
        return [
            Check(
                name="JDK",
                ok=True,
                detail="ready",
                remediation="install JDK",
            ),
            Check(
                name="Gradle wrapper",
                ok=False,
                detail=f"missing under {root}",
                remediation="restore wrapper",
            ),
        ]

    report = collect_doctor_report(
        root=tmp_path,
        module_finder=lambda module: True,
        android_collector=android_collector,
    )

    assert not report.ok
    assert report.checks[-2] == DoctorCheck(
        category="android",
        name="JDK",
        ok=True,
        detail="ready",
        remediation="",
    )
    assert report.checks[-1] == DoctorCheck(
        category="android",
        name="Gradle wrapper",
        ok=False,
        detail=f"missing under {tmp_path}",
        remediation="restore wrapper",
    )


def test_render_text_groups_checks_and_includes_next_step() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck("python", "Python runtime", True, "ready", ""),
            DoctorCheck("android", "adb", False, "missing", "install platform tools"),
        )
    )

    rendered = render_text(report)

    assert "GOFFY setup doctor" in rendered
    assert "PYTHON" in rendered
    assert "ANDROID" in rendered
    assert "[FAIL] adb: missing" in rendered
    assert "Resolve failed checks" in rendered


def test_render_text_escapes_control_characters_and_redacts_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "android",
                "JDK",
                False,
                f"{repo}/jdk and /opt/homebrew/jdk\n[OK] forged\x1b[31m",
                f"set JAVA_HOME under {home}\rnow",
            ),
        ),
        repo_root=repo,
        home=home,
    )

    rendered = render_text(report)

    assert "[FAIL] JDK: <repo>/jdk and <path>\\n[OK] forged" in rendered
    assert "fix: set JAVA_HOME under <home>\\rnow" in rendered
    assert str(repo) not in rendered
    assert str(home) not in rendered


def test_render_json_is_machine_readable() -> None:
    repo = Path("/opt/goffy-test/repo")
    report = DoctorReport(
        checks=(DoctorCheck("python", "Python runtime", True, f"ready at {repo}", ""),),
        repo_root=repo,
    )

    payload = json.loads(render_json(report))

    assert payload["ok"] is True
    assert payload["schemaVersion"] == "goffy.setup-doctor.v1"
    assert payload["checks"][0]["category"] == "python"
    assert payload["checks"][0]["detail"] == "ready at <repo>"


def test_render_json_redacts_non_repo_absolute_paths() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "android",
                "JDK",
                False,
                "known location: /Applications/Android Studio.app/Contents/jbr/Contents/Home",
                "install under /opt/homebrew",
            ),
        )
    )

    payload = json.loads(render_json(report))

    assert payload["checks"][0]["detail"] == "known location: <path>"
    assert payload["checks"][0]["remediation"] == "install under <path>"


def test_main_returns_zero_for_ready_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_doctor,
        "collect_doctor_report",
        lambda root: DoctorReport(
            checks=(DoctorCheck("python", "Python runtime", True, "ready", ""),),
            repo_root=root,
        ),
    )

    exit_code = main(["--repo-root", "/opt/goffy-test/repo"])

    assert exit_code == 0
    assert "GOFFY setup doctor" in capsys.readouterr().out


def test_main_returns_nonzero_for_blocked_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_doctor,
        "collect_doctor_report",
        lambda root: DoctorReport(
            checks=(DoctorCheck("android", "adb", False, "missing", "install adb"),),
            repo_root=root,
        ),
    )

    exit_code = main(["--repo-root", "/opt/goffy-test/repo", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
