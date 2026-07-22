from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import scripts.create_rom_gsi_candidate_evidence as gsi_evidence
from scripts.create_rom_gsi_candidate_evidence import (
    JSON_SCHEMA_VERSION,
    OFFICIAL_GSI_RELEASES_URL,
    create_gsi_candidate_evidence,
    main,
    normalize_architecture,
    render_json,
)

TEST_CONTENT = b"goffy official gsi"
TEST_SHA = hashlib.sha256(TEST_CONTENT).hexdigest()
ARTIFACT_NAME = f"aosp_arm64-exp-BP4A.251205.006-14401865-{TEST_SHA[:8]}.zip"
DOWNLOAD_URL = f"https://dl.google.com/developers/android/baklava/images/gsi/{ARTIFACT_NAME}"


def external_artifact(
    tmp_path: Path, *, name: str = ARTIFACT_NAME, content: bytes = TEST_CONTENT
) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    artifact = tmp_path / "downloads" / name
    artifact.parent.mkdir()
    artifact.write_bytes(content)
    return root, artifact


def test_gsi_candidate_evidence_hashes_artifact_without_leaking_path(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    evidence = create_gsi_candidate_evidence(
        artifact_path=artifact,
        source_url=OFFICIAL_GSI_RELEASES_URL,
        download_url=DOWNLOAD_URL,
        expected_sha256=TEST_SHA,
        candidate_name="Official Google Android 16 ARM64 GSI",
        android_release="16",
        architecture="arm64",
        root=root,
    )
    payload = json.loads(render_json(evidence))

    assert evidence.schema_version == JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["status"] == "ARTIFACT_CHECKSUM_VERIFIED"
    assert payload["candidate"] == {
        "name": "Official Google Android 16 ARM64 GSI",
        "android_release": "16",
        "architecture": "arm64",
        "image_kind": "archive",
        "license_note_code": "official_google_gsi_terms",
    }
    assert payload["artifact"] == {
        "artifact_name": ARTIFACT_NAME,
        "byte_count": len(TEST_CONTENT),
        "sha256": TEST_SHA,
        "expected_sha256": TEST_SHA,
    }
    assert payload["source"] == {
        "source_url": OFFICIAL_GSI_RELEASES_URL,
        "download_url": DOWNLOAD_URL,
    }
    assert payload["safety"] == {
        "execution_authority": "OFFLINE_HASH_ONLY",
        "device_mutation": "NONE",
        "authorization": "NON_AUTHORIZING_EVIDENCE",
        "destructive_actions": "WITHHELD",
        "local_path_redacted": True,
    }
    assert str(artifact.parent) not in render_json(evidence)


def test_gsi_candidate_evidence_rejects_sha_mismatch(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)
    wrong_sha_with_matching_filename_prefix = TEST_SHA[:8] + ("0" * 56)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=wrong_sha_with_matching_filename_prefix,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact SHA-256 does not match expected official checksum" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_unsafe_urls(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=f"{OFFICIAL_GSI_RELEASES_URL}?token=abc",
            download_url="https://user:pass@example.invalid/gsi.zip",
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        message = str(exc)
        assert "source URL must not include query or fragment" in message
        assert "download URL must not include credentials" in message
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_unofficial_sources(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url="https://example.invalid/gsi",
            download_url=f"https://example.invalid/developers/android/images/gsi/{ARTIFACT_NAME}",
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        message = str(exc)
        assert "source URL must be the official Android GSI releases page" in message
        assert "download URL must use the official Google download host" in message
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_non_gsi_google_download_path(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=f"https://dl.google.com/developers/android/other/{ARTIFACT_NAME}",
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "download URL must be under the official Android GSI downloads path" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_bogus_release_gsi_directory(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=f"https://dl.google.com/developers/android/not-a-release/images/gsi/{ARTIFACT_NAME}",
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "download URL must be under the official Android GSI downloads path" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_extra_gsi_path_segments(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=f"https://dl.google.com/developers/android/baklava/images/gsi/extra/{ARTIFACT_NAME}",
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "download URL must be under the official Android GSI downloads path" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_filename_architecture_mismatch(tmp_path: Path) -> None:
    x86_name = "aosp_x86_64-exp-BP4A.251205.006-14401865-aa5d832e.zip"
    root, artifact = external_artifact(tmp_path, name=x86_name)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=f"https://dl.google.com/developers/android/baklava/images/gsi/{x86_name}",
            expected_sha256="aa5d832e" + ("0" * 56),
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact filename architecture must match candidate architecture" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_filename_android_release_mismatch(
    tmp_path: Path,
) -> None:
    android17_name = "aosp_arm64-exp-CP31.260623.005-15817740-0ff59a08.zip"
    root, artifact = external_artifact(tmp_path, name=android17_name)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=f"https://dl.google.com/developers/android/cinnamonbun/images/gsi/{android17_name}",
            expected_sha256="0ff59a08" + ("0" * 56),
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact filename build must match candidate Android release" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_filename_checksum_prefix_mismatch(
    tmp_path: Path,
) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256="f8760221" + ("0" * 56),
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact filename checksum prefix must match expected SHA-256" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_action_word_in_candidate_name(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=TEST_SHA,
            candidate_name="Approved Flash This Phone",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "candidate name must not contain approval or device-action wording" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@pytest.mark.parametrize(
    "candidate_name",
    (
        "Unlocking Candidate",
        "Authorization Pending GSI",
        "Flashing Candidate",
    ),
)
def test_gsi_candidate_evidence_rejects_action_word_variants(
    tmp_path: Path,
    candidate_name: str,
) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=TEST_SHA,
            candidate_name=candidate_name,
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "candidate name must not contain approval or device-action wording" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_in_repo_artifact(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    artifact = root / "downloads" / ARTIFACT_NAME
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(TEST_CONTENT)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact path must be outside the repo" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_repo_local_symlink_to_external_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external" / ARTIFACT_NAME
    external.parent.mkdir()
    external.write_bytes(TEST_CONTENT)
    link = root / "downloads" / ARTIFACT_NAME
    link.parent.mkdir()
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    try:
        create_gsi_candidate_evidence(
            artifact_path=link,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 16 ARM64 GSI",
            android_release="16",
            architecture="arm64",
            root=root,
        )
    except ValueError as exc:
        assert "artifact path must be outside the repo" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_rejects_unsupported_target_metadata(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    try:
        create_gsi_candidate_evidence(
            artifact_path=artifact,
            source_url=OFFICIAL_GSI_RELEASES_URL,
            download_url=DOWNLOAD_URL,
            expected_sha256=TEST_SHA,
            candidate_name="Official Google Android 15 x86 GSI",
            android_release="15",
            architecture="x86_64",
            root=root,
        )
    except ValueError as exc:
        message = str(exc)
        assert "candidate Android release must be 16 or newer" in message
        assert "candidate architecture must be arm64 or arm64+gms" in message
    else:
        raise AssertionError("expected ValueError")


def test_gsi_candidate_evidence_accepts_official_arm64_gms_alias() -> None:
    assert normalize_architecture("gsi_gms_arm64") == "arm64+gms"


def test_gsi_candidate_evidence_json_contains_no_device_command_verbs(tmp_path: Path) -> None:
    root, artifact = external_artifact(tmp_path)

    evidence = create_gsi_candidate_evidence(
        artifact_path=artifact,
        source_url=OFFICIAL_GSI_RELEASES_URL,
        download_url=DOWNLOAD_URL,
        expected_sha256=TEST_SHA,
        candidate_name="Official Google Android 16 ARM64 GSI",
        android_release="16",
        architecture="arm64",
        root=root,
    )
    text = render_json(evidence).lower()

    assert "fastboot" not in text
    assert "adb" not in text
    assert "erase" not in text
    assert "reboot bootloader" not in text
    assert "flash" not in text


def test_gsi_candidate_evidence_cli_writes_under_validation_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, artifact = external_artifact(tmp_path)
    output = root / ".goffy-validation" / "rom-gsi-candidate-evidence.json"

    exit_code = main(
        [
            "--artifact",
            str(artifact),
            "--source-url",
            OFFICIAL_GSI_RELEASES_URL,
            "--download-url",
            DOWNLOAD_URL,
            "--expected-sha256",
            TEST_SHA,
            "--candidate-name",
            "Official Google Android 16 ARM64 GSI",
            "--android-release",
            "16",
            "--architecture",
            "arm64",
            "--output",
            str(output),
        ],
        root=root,
    )

    assert exit_code == 0
    assert "wrote GSI candidate evidence" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == JSON_SCHEMA_VERSION


def test_gsi_candidate_evidence_cli_redacts_filesystem_error_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, artifact = external_artifact(tmp_path)

    def fail_sha256(path: Path) -> str:
        raise OSError(f"failed to read {path}")

    monkeypatch.setattr(gsi_evidence, "sha256_file", fail_sha256)

    exit_code = main(
        [
            "--artifact",
            str(artifact),
            "--source-url",
            OFFICIAL_GSI_RELEASES_URL,
            "--download-url",
            DOWNLOAD_URL,
            "--expected-sha256",
            TEST_SHA,
            "--candidate-name",
            "Official Google Android 16 ARM64 GSI",
            "--android-release",
            "16",
            "--architecture",
            "arm64",
        ],
        root=root,
    )

    error = capsys.readouterr().err
    assert exit_code == 2
    assert "local filesystem operation failed" in error
    assert str(artifact) not in error


def test_gsi_candidate_evidence_cli_redacts_errno_strerror_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, artifact = external_artifact(tmp_path)

    def fail_sha256(path: Path) -> str:
        raise OSError(5, f"failed to read {path}")

    monkeypatch.setattr(gsi_evidence, "sha256_file", fail_sha256)

    exit_code = main(
        [
            "--artifact",
            str(artifact),
            "--source-url",
            OFFICIAL_GSI_RELEASES_URL,
            "--download-url",
            DOWNLOAD_URL,
            "--expected-sha256",
            TEST_SHA,
            "--candidate-name",
            "Official Google Android 16 ARM64 GSI",
            "--android-release",
            "16",
            "--architecture",
            "arm64",
        ],
        root=root,
    )

    error = capsys.readouterr().err
    assert exit_code == 2
    assert "local filesystem operation failed: errno 5" in error
    assert str(artifact) not in error


def test_gsi_candidate_evidence_cli_rejects_output_outside_validation_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, artifact = external_artifact(tmp_path)
    output = root / "rom-gsi-candidate-evidence.json"

    exit_code = main(
        [
            "--artifact",
            str(artifact),
            "--source-url",
            OFFICIAL_GSI_RELEASES_URL,
            "--download-url",
            DOWNLOAD_URL,
            "--expected-sha256",
            TEST_SHA,
            "--candidate-name",
            "Official Google Android 16 ARM64 GSI",
            "--android-release",
            "16",
            "--architecture",
            "arm64",
            "--output",
            str(output),
        ],
        root=root,
    )

    assert exit_code == 2
    assert "output path must be under .goffy-validation" in capsys.readouterr().err
