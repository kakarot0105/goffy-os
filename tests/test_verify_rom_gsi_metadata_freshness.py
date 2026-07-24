from __future__ import annotations

import json
import urllib.error
from pathlib import Path

from scripts.create_rom_gsi_candidate_evidence import (
    DEFAULT_ANDROID16_GSI_ARTIFACT_NAME,
    DEFAULT_ANDROID16_GSI_DOWNLOAD_URL,
    DEFAULT_ANDROID16_GSI_SHA256,
    OFFICIAL_GSI_RELEASES_URL,
)
from scripts.verify_rom_gsi_metadata_freshness import (
    DEFAULT_ANDROID16_GSI_SECTION_TITLE,
    GsiMetadataFreshnessStatus,
    latest_android_arm64_gsi_candidate,
    main,
    render_json,
    render_text,
    verify_rom_gsi_metadata_freshness,
)

ANDROID17_ARTIFACT = "aosp_arm64-exp-CP2A.260605.012-15430684-8e545e1e.zip"
ANDROID17_SHA256 = "8e545e1e1e977c3b43b4e54a3af463f3e7d1c3177b120e772138334e15f48f75"
ANDROID16_GMS_ARTIFACT = "gsi_gms_arm64-exp-CP11.251209.009.A1-14840729-89298580.zip"
ANDROID16_GMS_SHA256 = "89298580dda1280efe32b27d04b9caf5bbe19061c3716635c0d2d11640acf292"
ANDROID16_OLDER_ARTIFACT = "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip"
ANDROID16_OLDER_SHA256 = "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea"


def releases_page_html(
    *,
    android16_artifact: str = DEFAULT_ANDROID16_GSI_ARTIFACT_NAME,
    android16_sha256: str = DEFAULT_ANDROID16_GSI_SHA256,
) -> str:
    return f"""\
<html>
  <body>
    <h2 id="android-gsi-17">Android 17 GSIs</h2>
    <table>
      <tr id="arm64">
        <td>ARM64</td>
        <td><button>{ANDROID17_ARTIFACT}</button><br /><code>{ANDROID17_SHA256}</code></td>
      </tr>
    </table>
    <h2 id="android-gsi-16" data-text="Android 16 GSIs">Android 16 GSIs</h2>
    <h3 id="16-qpr3">{DEFAULT_ANDROID16_GSI_SECTION_TITLE}</h3>
    <table>
      <tr id="gms">
        <td>ARM64+GMS</td>
        <td><button>{ANDROID16_GMS_ARTIFACT}</button><br /><code>{ANDROID16_GMS_SHA256}</code></td>
      </tr>
      <tr id="arm64">
        <td>ARM64</td>
        <td><button>{android16_artifact}</button><br /><code>{android16_sha256}</code></td>
      </tr>
    </table>
    <h3 id="16-stable">Android 16</h3>
    <table>
      <tr id="arm64">
        <td>ARM64</td>
        <td>
          <button>{ANDROID16_OLDER_ARTIFACT}</button>
          <br /><code>{ANDROID16_OLDER_SHA256}</code>
        </td>
      </tr>
    </table>
    <h2 id="android-gsi-15">Android 15 GSIs</h2>
  </body>
</html>
"""


def test_latest_android16_candidate_ignores_android17_and_gms_entries() -> None:
    candidate = latest_android_arm64_gsi_candidate(releases_page_html(), android_release="16")

    assert candidate.artifact_name == DEFAULT_ANDROID16_GSI_ARTIFACT_NAME
    assert candidate.sha256 == DEFAULT_ANDROID16_GSI_SHA256
    assert candidate.download_url == DEFAULT_ANDROID16_GSI_DOWNLOAD_URL
    assert candidate.android_release == "16"
    assert candidate.architecture == "arm64"
    assert candidate.section_title == DEFAULT_ANDROID16_GSI_SECTION_TITLE


def test_freshness_check_passes_when_official_page_matches_committed_candidate() -> None:
    seen: list[tuple[str, int]] = []

    def fetcher(url: str, timeout_seconds: int) -> str:
        seen.append((url, timeout_seconds))
        return releases_page_html()

    report = verify_rom_gsi_metadata_freshness(fetcher=fetcher, timeout_seconds=120)

    assert report.ok is True
    assert report.status is GsiMetadataFreshnessStatus.FRESH
    assert report.observed is not None
    assert report.observed.artifact_name == DEFAULT_ANDROID16_GSI_ARTIFACT_NAME
    assert seen == [(OFFICIAL_GSI_RELEASES_URL, 30)]
    assert report.safety.artifact_downloaded is False
    assert report.safety.device_mutation == "NONE"


def test_freshness_check_reports_stale_committed_candidate() -> None:
    official_artifact = "aosp_arm64-exp-CP11.251209.009.A1-14840729-aaaaaaaa.zip"
    report = verify_rom_gsi_metadata_freshness(
        page_text=releases_page_html(
            android16_artifact=official_artifact,
            android16_sha256="a" * 64,
        )
    )

    assert report.ok is False
    assert report.status is GsiMetadataFreshnessStatus.STALE
    assert report.observed is not None
    assert report.observed.artifact_name == official_artifact
    assert any("artifact is stale" in blocker for blocker in report.blockers)
    assert any("SHA-256 is stale" in blocker for blocker in report.blockers)


def test_freshness_check_reports_stale_subsection_if_official_page_adds_newer_track() -> None:
    newer_artifact = "aosp_arm64-exp-CP11.251209.009.A1-14840729-bbbbbbbb.zip"
    report = verify_rom_gsi_metadata_freshness(
        page_text=releases_page_html(
            android16_artifact=newer_artifact,
            android16_sha256="b" * 64,
        ).replace(DEFAULT_ANDROID16_GSI_SECTION_TITLE, "Android 16 QPR4 (Beta)")
    )

    assert report.ok is False
    assert report.status is GsiMetadataFreshnessStatus.STALE
    assert any("subsection is stale" in blocker for blocker in report.blockers)


def test_freshness_check_rejects_invalid_android16_section_metadata() -> None:
    report = verify_rom_gsi_metadata_freshness(
        page_text=releases_page_html(
            android16_artifact=ANDROID17_ARTIFACT,
            android16_sha256=ANDROID17_SHA256,
        )
    )

    assert report.ok is False
    assert report.status is GsiMetadataFreshnessStatus.INVALID_OFFICIAL_METADATA
    assert any("does not match Android 16" in blocker for blocker in report.blockers)


def test_freshness_check_handles_unavailable_source_without_leaking_url_details() -> None:
    def fetcher(url: str, timeout_seconds: int) -> str:
        raise urllib.error.URLError("temporary outage")

    report = verify_rom_gsi_metadata_freshness(fetcher=fetcher)

    assert report.ok is False
    assert report.status is GsiMetadataFreshnessStatus.SOURCE_UNAVAILABLE
    assert report.blockers == ("official GSI releases page could not be read",)


def test_renderers_report_non_authorizing_metadata_only() -> None:
    report = verify_rom_gsi_metadata_freshness(page_text=releases_page_html())
    text = render_text(report)
    payload = json.loads(render_json(report))

    assert "artifact downloaded: false" in text
    assert "device mutation: NONE" in text
    assert payload["safety"]["authorization"] == "NON_AUTHORIZING_EVIDENCE"
    assert payload["safety"]["destructive_actions"] == "WITHHELD"


def test_cli_parses_local_fixture_without_fetching_or_downloading(
    tmp_path: Path,
    capsys,
) -> None:
    html = tmp_path / "gsi-releases.html"
    html.write_text(releases_page_html(), encoding="utf-8")

    exit_code = main(["--source-html", str(html), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["observed"]["artifact_name"] == DEFAULT_ANDROID16_GSI_ARTIFACT_NAME
    assert payload["safety"]["artifact_downloaded"] is False


def test_cli_can_allow_missing_local_fixture_as_source_unavailable(
    tmp_path: Path,
    capsys,
) -> None:
    missing = tmp_path / "missing.html"

    exit_code = main(["--source-html", str(missing), "--allow-source-unavailable", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is False
    assert payload["status"] == "SOURCE_UNAVAILABLE"
    assert payload["blockers"] == ["official GSI releases page read failed: errno 2"]
