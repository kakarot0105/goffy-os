from __future__ import annotations

import json
from pathlib import Path

from scripts.create_rom_stock_candidate_report import (
    CandidateMatchStatus,
    CandidateReportStatus,
    build_report,
    load_probe_json,
    main,
    normalize_candidates,
    normalize_source_url,
    parse_build_id_from_fingerprint,
    render_json,
    render_markdown,
)
from scripts.create_rom_stock_restore_evidence import write_output

PROBE = {
    "schema_version": "goffy.rom-feasibility-probe.v1",
    "device": {
        "model": "moto g - 2025",
        "codename": "kansas",
        "product": "kansas_g_sys",
        "carrier": "tracfone",
    },
    "platform": {
        "android_release": "16",
        "build_incremental": "ebe4e3-2b6752",
        "build_security_patch": "2026-06-01",
    },
    "properties": {
        "ro.build.fingerprint": (
            "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
        )
    },
}


def test_parse_build_id_from_probe_fingerprint() -> None:
    assert (
        parse_build_id_from_fingerprint(
            "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
        )
        == "W1VKS36H.9-12-9-8-2"
    )
    assert parse_build_id_from_fingerprint("not-a-fingerprint") == ""


def test_nearby_kansas_archives_do_not_become_rollback_evidence() -> None:
    report = build_report(
        PROBE,
        source_url="https://mirrors.lolinet.com/firmware/lenomola/2025/kansas/official/RETUS/",
        candidate_names=(
            "XT2513-1_KANSAS_RETUS_16_W1VK36H.9-12_subsidy-DEFAULT_regulatory-DEFAULT.zip",
            "XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-1_subsidy-DEFAULT_regulatory-DEFAULT.zip",
        ),
    )
    markdown = render_markdown(report)

    assert report.status is CandidateReportStatus.BLOCKED_NO_EXACT_STOCK_ARCHIVE
    assert not report.ok
    assert all(not candidate.rollback_evidence for candidate in report.candidates)
    assert {candidate.match_status for candidate in report.candidates} == {
        CandidateMatchStatus.RELATED_KANSAS_NEARBY_BUILD
    }
    assert "nearby firmware is not rollback evidence" in markdown
    assert "W1VKS36H.9-12-9-8-2" in markdown


def test_build_id_archive_name_still_requires_variant_hash_and_rollback_doc() -> None:
    report = build_report(
        PROBE,
        source_url="https://en-us.support.motorola.com/app/softwarefix",
        candidate_names=("XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-9-8-2_subsidy-DEFAULT.zip",),
    )
    payload = json.loads(render_json(report))

    assert report.status is CandidateReportStatus.BUILD_ID_NAME_FOUND_NEEDS_VARIANT_HASH
    assert payload["candidates"][0]["match_status"] == "CODENAME_AND_BUILD_ID_PRESENT"
    assert payload["candidates"][0]["rollback_evidence"] is False
    assert any("variant confirmation" in blocker for blocker in report.blockers)
    assert any("SHA-256" in blocker for blocker in report.blockers)


def test_build_id_prefix_collision_is_not_a_build_id_match() -> None:
    report = build_report(
        PROBE,
        candidate_names=("XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-9-8-20_subsidy-DEFAULT.zip",),
    )

    assert report.status is CandidateReportStatus.BLOCKED_NO_EXACT_STOCK_ARCHIVE
    assert report.candidates[0].match_status is CandidateMatchStatus.RELATED_KANSAS_NEARBY_BUILD
    assert report.candidates[0].rollback_evidence is False


def test_same_build_wrong_variant_is_only_a_filename_candidate() -> None:
    report = build_report(
        PROBE,
        candidate_names=("XT9999-1_KANSAS_OTHER_16_W1VKS36H.9-12-9-8-2_subsidy-DEFAULT.zip",),
    )

    assert report.status is CandidateReportStatus.BUILD_ID_NAME_FOUND_NEEDS_VARIANT_HASH
    assert report.candidates[0].match_status is CandidateMatchStatus.CODENAME_AND_BUILD_ID_PRESENT
    assert report.candidates[0].rollback_evidence is False
    assert "variant" in report.blockers[0]


def test_unrelated_candidate_is_insufficient() -> None:
    report = build_report(PROBE, candidate_names=("XT0000-1_OTHER_16_W1VKS36H.zip",))

    assert report.candidates[0].match_status is CandidateMatchStatus.UNRELATED_OR_INSUFFICIENT
    assert report.candidates[0].rollback_evidence is False


def test_rejects_unsafe_candidate_name_and_source_url() -> None:
    try:
        normalize_candidates(["../firmware.zip"])
    except ValueError as exc:
        assert "candidate archive name is invalid" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    try:
        normalize_source_url("https://user:pass@example.invalid/firmware.zip?token=x")
    except ValueError as exc:
        assert "source URL must not include credentials" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_probe_json_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"schema_version": "other"}), encoding="utf-8")

    try:
        load_probe_json(path)
    except ValueError as exc:
        assert "unsupported probe schema" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_report_output_can_be_written_under_validation_dir(tmp_path: Path) -> None:
    output = tmp_path / ".goffy-validation" / "rom-stock-candidates.json"
    payload = render_json(build_report(PROBE, candidate_names=("XT0000-1_OTHER_16.zip",)))

    write_output(output, payload, root=tmp_path)

    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        "goffy.rom-stock-candidate-report.v1"
    )


def test_cli_accepts_repeated_candidate_arguments(tmp_path: Path, capsys) -> None:
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(PROBE), encoding="utf-8")

    exit_code = main(
        [
            str(probe),
            "--candidate",
            "XT2513-1_KANSAS_RETUS_16_W1VK36H.9-12.zip",
            "--candidate",
            "XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-1.zip",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED_NO_EXACT_STOCK_ARCHIVE"
    assert len(payload["candidates"]) == 2


def test_cli_requires_json_mode_for_json_output_path(tmp_path: Path, capsys) -> None:
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(PROBE), encoding="utf-8")

    exit_code = main(
        [
            str(probe),
            "--candidate",
            "XT2513-1_KANSAS_RETUS_16_W1VK36H.9-12.zip",
            "--output",
            ".goffy-validation/rom-stock-candidates.json",
        ]
    )

    assert exit_code == 2
    assert "--json is required" in capsys.readouterr().err
