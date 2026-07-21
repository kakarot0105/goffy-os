from __future__ import annotations

import json
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from scripts.verify_rom_release_apk import (
    JSON_SCHEMA_VERSION,
    main,
    render_json,
    verify_release_apk,
)


def test_release_apk_verification_accepts_signed_apk(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)

    verification = verify_release_apk(apk=apk, root=tmp_path)

    assert verification.schema_version == JSON_SCHEMA_VERSION
    assert verification.ok
    assert verification.status == "VERIFIED"
    assert verification.destructive_actions == "withheld"
    assert verification.apk.exists is True
    assert verification.apk.sha256
    assert verification.apk.signature_schemes == ("v2",)


def test_release_apk_verification_blocks_missing_unsigned_and_debug_apks(
    tmp_path: Path,
) -> None:
    missing = verify_release_apk(apk=tmp_path / "GoffyOS-signed.apk", root=tmp_path)
    unsigned = tmp_path / "app-release-unsigned.apk"
    unsigned.write_bytes(fake_apk_with_v2_signature_block())
    debug = tmp_path / "app-debug.apk"
    debug.write_bytes(fake_apk_with_v2_signature_block())

    unsigned_verification = verify_release_apk(apk=unsigned, root=tmp_path)
    debug_verification = verify_release_apk(apk=debug, root=tmp_path)

    assert not missing.ok
    assert "GOFFY release verification APK is missing" in missing.blockers
    assert not unsigned_verification.ok
    assert (
        "GOFFY release verification APK must not be an unsigned Gradle artifact"
        in unsigned_verification.blockers
    )
    assert not debug_verification.ok
    assert (
        "GOFFY release verification APK must not be a debug build artifact"
        in debug_verification.blockers
    )


def test_release_apk_verification_blocks_missing_signature_block(tmp_path: Path) -> None:
    apk = tmp_path / "GoffyOS-signed.apk"
    apk.write_bytes(fake_unsigned_apk())

    verification = verify_release_apk(apk=apk, root=tmp_path)

    assert not verification.ok
    assert (
        "GOFFY release verification APK must contain an APK Signature Scheme v2/v3 block"
        in verification.blockers
    )


def test_release_apk_verification_blocks_non_zip_signature_blob(tmp_path: Path) -> None:
    apk = tmp_path / "GoffyOS-signed.apk"
    apk.write_bytes(fake_signature_blob_without_zip_container())

    verification = verify_release_apk(apk=apk, root=tmp_path)

    assert not verification.ok
    assert (
        "GOFFY release verification APK must be a valid APK/ZIP container" in verification.blockers
    )


def test_release_apk_verification_cli_prints_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    apk = write_signed_apk(tmp_path)

    exit_code = main(
        [
            "--apk",
            str(apk),
            "--stdout",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    assert payload["ok"] is True


def test_release_apk_verification_cli_requires_stdout_for_markdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--markdown"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--markdown requires --stdout" in captured.err


def test_release_apk_verification_json_does_not_record_secrets(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)

    payload = render_json(verify_release_apk(apk=apk, root=tmp_path))

    assert "GOFFY_APK_KEYSTORE_PASS" not in payload
    assert "GOFFY_APK_KEY_PASS" not in payload


def write_signed_apk(tmp_path: Path) -> Path:
    apk = tmp_path / "GoffyOS-signed.apk"
    apk.write_bytes(fake_apk_with_v2_signature_block())
    return apk


def fake_apk_with_v2_signature_block() -> bytes:
    unsigned = bytearray(fake_unsigned_apk())
    eocd_offset = unsigned.rfind(b"PK\x05\x06")
    central_directory_offset = struct.unpack_from("<I", unsigned, eocd_offset + 16)[0]
    pair = struct.pack("<Q", 4) + struct.pack("<I", 0x7109871A)
    block_size = len(pair) + 24
    signing_block = (
        struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + b"APK Sig Block 42"
    )
    unsigned[central_directory_offset:central_directory_offset] = signing_block
    struct.pack_into(
        "<I",
        unsigned,
        eocd_offset + len(signing_block) + 16,
        central_directory_offset + len(signing_block),
    )
    return bytes(unsigned)


def fake_unsigned_apk() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", "goffy")
    return buffer.getvalue()


def fake_signature_blob_without_zip_container() -> bytes:
    payload = b"fake apk payload"
    pair = struct.pack("<Q", 4) + struct.pack("<I", 0x7109871A)
    block_size = len(pair) + 24
    signing_block = (
        struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + b"APK Sig Block 42"
    )
    central_directory_offset = len(payload) + len(signing_block)
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 0, 0, 0, central_directory_offset, 0)
    return payload + signing_block + eocd
