from __future__ import annotations

import hashlib
import json
import stat
import struct
import zipfile
from pathlib import Path

import pytest
from scripts.create_rom_release_signing_plan import (
    JSON_SCHEMA_VERSION,
    create_release_signing_plan,
    main,
    render_json,
)
from scripts.create_rom_stock_restore_evidence import write_output


def test_release_signing_plan_is_ready_with_external_keystore_and_apksigner(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    unsigned = write_unsigned_apk(root)
    apksigner = write_apksigner(tmp_path)
    keystore = tmp_path / "secrets" / "goffy-release.jks"
    keystore.parent.mkdir()
    keystore.write_bytes(b"not a real keystore")
    signed = Path(".goffy-validation/rom-signing/GoffyOS-signed.apk")

    plan = create_release_signing_plan(
        unsigned_apk=unsigned,
        signed_apk=signed,
        keystore=keystore,
        apksigner=apksigner,
        root=root,
        env={},
        sdk_roots=(),
    )

    assert plan.schema_version == JSON_SCHEMA_VERSION
    assert plan.ok
    assert plan.status == "READY_TO_SIGN"
    assert plan.blockers == ()
    assert plan.unsigned_apk.sha256 == hashlib.sha256(unsigned.read_bytes()).hexdigest()
    assert plan.signed_apk == str(root / signed)
    assert plan.keystore == str(keystore)
    assert plan.commands[0].name == "sign"
    assert "env:GOFFY_APK_KEYSTORE_PASS" in plan.commands[0].argv
    assert "not a real keystore" not in render_json(plan)


def test_release_signing_plan_blocks_missing_external_prerequisites(tmp_path: Path) -> None:
    root = tmp_path / "repo"

    plan = create_release_signing_plan(root=root, env={}, sdk_roots=())

    assert not plan.ok
    assert (
        "unsigned GOFFY release artifact is missing; run Android assembleRelease" in plan.blockers
    )
    assert "release keystore path is required and must live outside the repo" in plan.blockers
    assert "Android SDK apksigner was not found" in plan.blockers


def test_release_signing_plan_rejects_repo_keystore_and_bad_outputs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    unsigned = write_unsigned_apk(root)
    apksigner = write_apksigner(tmp_path)
    keystore = root / "release-key.jks"
    keystore.parent.mkdir(parents=True, exist_ok=True)
    keystore.write_bytes(b"secret key")

    plan = create_release_signing_plan(
        unsigned_apk=unsigned,
        signed_apk=root / "GoffyOS-signed.apk",
        keystore=keystore,
        apksigner=apksigner,
        root=root,
        env={},
        sdk_roots=(),
    )

    assert not plan.ok
    assert "release keystore must not live inside the GOFFY repo" in plan.blockers
    assert "signed GOFFY output must be under non-symlinked .goffy-validation" in plan.blockers
    assert "secret key" not in render_json(plan)


def test_release_signing_plan_rejects_debug_or_signed_source_apk(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    apk = root / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"debug")

    plan = create_release_signing_plan(
        unsigned_apk=apk,
        signed_apk=Path(".goffy-validation/rom-signing/GoffyOS-signed.apk"),
        keystore=tmp_path / "missing.jks",
        apksigner=write_apksigner(tmp_path),
        root=root,
        env={},
        sdk_roots=(),
    )

    assert "unsigned GOFFY release artifact must not be a debug APK" in plan.blockers
    assert "unsigned GOFFY release artifact must end with -unsigned.apk" in plan.blockers


def test_release_signing_plan_rejects_malformed_or_presigned_unsigned_apk(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    malformed = (
        root
        / "android"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "release"
        / "app-release-unsigned.apk"
    )
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"plain blob")
    signed = tmp_path / "app-release-unsigned.apk"
    signed.write_bytes(fake_apk_with_v2_signature_block())

    malformed_plan = create_release_signing_plan(
        unsigned_apk=malformed,
        signed_apk=Path(".goffy-validation/rom-signing/GoffyOS-signed.apk"),
        keystore=tmp_path / "missing.jks",
        apksigner=write_apksigner(tmp_path),
        root=root,
        env={},
        sdk_roots=(),
    )
    presigned_plan = create_release_signing_plan(
        unsigned_apk=signed,
        signed_apk=Path(".goffy-validation/rom-signing/GoffyOS-signed.apk"),
        keystore=tmp_path / "missing.jks",
        apksigner=write_apksigner(tmp_path),
        root=root,
        env={},
        sdk_roots=(),
    )

    assert "unsigned GOFFY release artifact must be a valid APK/ZIP container" in (
        malformed_plan.blockers
    )
    assert "unsigned GOFFY release artifact must not already be APK-signed" in (
        presigned_plan.blockers
    )


def test_release_signing_plan_rejects_non_sdk_apksigner_executable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    unsigned = write_unsigned_apk(root)
    keystore = tmp_path / "secrets" / "goffy-release.jks"
    keystore.parent.mkdir()
    keystore.write_bytes(b"key")

    plan = create_release_signing_plan(
        unsigned_apk=unsigned,
        signed_apk=Path(".goffy-validation/rom-signing/GoffyOS-signed.apk"),
        keystore=keystore,
        apksigner=write_executable(tmp_path / "bin" / "totally-not-apksigner"),
        root=root,
        env={},
        sdk_roots=(),
    )

    assert "Android SDK apksigner path must be named apksigner" in plan.blockers
    assert "Android SDK apksigner must live under build-tools/<version>" in plan.blockers


def test_release_signing_plan_writes_json_under_validation_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    unsigned = write_unsigned_apk(root)
    apksigner = write_apksigner(tmp_path)
    keystore = tmp_path / "secrets" / "goffy-release.jks"
    keystore.parent.mkdir()
    keystore.write_bytes(b"key")
    output = root / ".goffy-validation" / "rom-signing" / "plan.json"
    plan = create_release_signing_plan(
        unsigned_apk=unsigned,
        signed_apk=Path(".goffy-validation/rom-signing/GoffyOS-signed.apk"),
        keystore=keystore,
        apksigner=apksigner,
        root=root,
        env={},
        sdk_roots=(),
    )

    write_output(output, render_json(plan), root=root)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["commands"][0]["requires_secret_env"] == [
        "GOFFY_APK_KEYSTORE_PASS",
        "GOFFY_APK_KEY_PASS",
    ]


def test_release_signing_plan_cli_prints_blocked_plan_without_writing_repo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    unsigned = write_unsigned_apk(root)
    apksigner = write_apksigner(tmp_path)

    exit_code = main(
        [
            "--unsigned-apk",
            str(unsigned),
            "--signed-apk",
            str(root / ".goffy-validation" / "rom-signing" / "GoffyOS-signed.apk"),
            "--apksigner",
            str(apksigner),
            "--stdout",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["status"] == "BLOCKED_SIGNING_PREREQUISITES"
    assert "release keystore path is required" in "\n".join(payload["blockers"])


def test_release_signing_plan_cli_requires_stdout_for_markdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--markdown"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--markdown requires --stdout" in captured.err


def write_unsigned_apk(root: Path) -> Path:
    apk = (
        root
        / "android"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "release"
        / "app-release-unsigned.apk"
    )
    apk.parent.mkdir(parents=True)
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", "goffy")
    return apk


def write_apksigner(tmp_path: Path, *, name: str = "apksigner") -> Path:
    tool = tmp_path / "sdk" / "build-tools" / "36.0.0" / name
    return write_executable(tool)


def write_executable(path: Path) -> Path:
    tool = path
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def fake_apk_with_v2_signature_block() -> bytes:
    payload = b"fake apk payload"
    pair = struct.pack("<Q", 4) + struct.pack("<I", 0x7109871A)
    block_size = len(pair) + 24
    signing_block = (
        struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + b"APK Sig Block 42"
    )
    central_directory_offset = len(payload) + len(signing_block)
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 0, 0, 0, central_directory_offset, 0)
    return payload + signing_block + eocd
