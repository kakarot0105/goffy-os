from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CRITICAL_STEP_NAMES = {
    "Verify",
    "Android preflight",
    "Lint, test, and assemble",
    "Verify GOFFY LITE APK budget",
    "Compile optional LiteRT-LM provider",
    "Verify merged Android manifests",
}
ANDROID_DIAGNOSTIC_CONDITION = (
    "${{ failure() && (steps.android_preflight.conclusion == 'failure' || "
    "steps.android_gradle.conclusion == 'failure' || "
    "steps.android_apk_budget.conclusion == 'failure' || "
    "steps.android_local_model_provider.conclusion == 'failure' || "
    "steps.merged_manifest_security.conclusion == 'failure') }}"
)


def workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def job_steps(job_name: str) -> list[dict[str, Any]]:
    jobs = cast("dict[str, Any]", workflow()["jobs"])
    job = cast("dict[str, Any]", jobs[job_name])
    return cast("list[dict[str, Any]]", job["steps"])


def step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def assert_blocking_step(step: dict[str, Any]) -> None:
    assert "continue-on-error" not in step
    assert "if" not in step


def test_python_ci_uses_unified_verifier() -> None:
    verify = step_by_name(job_steps("python"), "Verify")

    assert verify["run"] == "python scripts/verify_all.py --allow-missing-android"
    assert_blocking_step(verify)


def test_android_ci_preflights_before_gradle_and_manifest_security() -> None:
    steps = job_steps("android")
    names = [step.get("name") for step in steps]

    preflight = step_by_name(steps, "Android preflight")
    gradle = step_by_name(steps, "Lint, test, and assemble")
    apk_budget = step_by_name(steps, "Verify GOFFY LITE APK budget")
    provider_compile = step_by_name(steps, "Compile optional LiteRT-LM provider")
    manifest_scan = step_by_name(steps, "Verify merged Android manifests")
    diagnostics = step_by_name(steps, "Setup diagnostics on failure")

    assert preflight["run"] == "python3 scripts/android_preflight.py"
    assert preflight["id"] == "android_preflight"
    assert str(gradle["run"]).startswith("./android/gradlew -p android")
    assert gradle["id"] == "android_gradle"
    assert apk_budget["run"] == "python3 scripts/verify_android_apk_budget.py"
    assert apk_budget["id"] == "android_apk_budget"
    assert (
        provider_compile["run"] == "./android/gradlew -p android :app:processModelDebugManifest "
        ":app:compileModelDebugKotlin --no-daemon"
    )
    assert provider_compile["id"] == "android_local_model_provider"
    assert manifest_scan["run"] == "python3 scripts/security_scan.py --require-merged-manifests"
    assert manifest_scan["id"] == "merged_manifest_security"
    assert (
        diagnostics["run"]
        == "python3 scripts/setup_doctor.py --android-only --include-device --json"
    )
    assert diagnostics["if"] == ANDROID_DIAGNOSTIC_CONDITION
    assert diagnostics["continue-on-error"] is True
    assert names.index("Android preflight") < names.index("Lint, test, and assemble")
    assert names.index("Lint, test, and assemble") < names.index("Verify GOFFY LITE APK budget")
    assert names.index("Verify GOFFY LITE APK budget") < names.index(
        "Compile optional LiteRT-LM provider"
    )
    assert names.index("Compile optional LiteRT-LM provider") < names.index(
        "Verify merged Android manifests"
    )
    assert names.index("Verify merged Android manifests") < names.index(
        "Setup diagnostics on failure"
    )

    for step in (preflight, gradle, apk_budget, provider_compile, manifest_scan):
        assert_blocking_step(step)


def test_ci_permissions_and_actions_are_locked_down() -> None:
    loaded = workflow()

    assert loaded["permissions"] == {"contents": "read"}

    jobs = cast("dict[str, Any]", loaded["jobs"])
    for job in jobs.values():
        steps = cast("list[dict[str, Any]]", cast("dict[str, Any]", job)["steps"])
        for step in steps:
            if step.get("name") in CRITICAL_STEP_NAMES:
                assert_blocking_step(step)
            uses = step.get("uses")
            if uses is not None:
                assert isinstance(uses, str)
                assert re.search(r"@[0-9a-f]{40}$", uses) is not None
