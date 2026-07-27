import json
import os
import types

import pytest

import requests

import isox

DISTROS_PATH = os.path.join(os.path.dirname(isox.__file__), "distros.json")

with open(DISTROS_PATH, "r") as f:
    SHIPPED_DISTROS = json.load(f)


def serve_html(monkeypatch, html):
    """Point isox's requests.get at a canned HTML instead of the network"""

    def fake_get(url, **kwargs):
        return types.SimpleNamespace(text=html, raise_for_status=lambda: None)

    monkeypatch.setattr(isox.requests, "get", fake_get)


def listing(*hrefs):
    """Build a minimal directory-listing page from href values"""
    links = "".join(f'<a href="{h}">{h}</a>' for h in hrefs)
    return f"<html><body>{links}</body></html>"


def test_html_listing_finds_matching_iso(monkeypatch):
    serve_html(
        monkeypatch, listing("archlinux-x86_64.iso", "notes.txt", "sha256sums.txt")
    )
    result = isox.discover_via_html_listing("https://example.test/", ["archlinux"])
    assert result == "archlinux-x86_64.iso"


def test_html_listing_strips_relative_prefix(monkeypatch):
    serve_html(monkeypatch, listing("./garuda-mokka-linux-zen.iso"))
    result = isox.discover_via_html_listing("https://example.test/", ["garuda"])
    assert result == "garuda-mokka-linux-zen.iso"


def test_html_listing_requires_every_substring(monkeypatch):
    serve_html(
        monkeypatch,
        listing("debian-13.0.0-amd64-netinst.iso", "debian-13.0.0-arm64-netinst.iso"),
    )
    result = isox.discover_via_html_listing(
        "https://example.test/", ["netinst", "amd64"]
    )
    assert result == "debian-13.0.0-amd64-netinst.iso"


def test_html_listing_sorts_numerically(monkeypatch):
    serve_html(
        monkeypatch, listing("void-live-x86_64-9.iso", "void-live-x86_64-10.iso")
    )
    result = isox.discover_via_html_listing("https://example.test/", ["void"])
    assert result == "void-live-x86_64-10.iso"


def test_html_listing_mixed_digit_and_text_names_dont_crash(monkeypatch):
    serve_html(monkeypatch, listing("foo-10.iso", "foo-beta.iso"))
    result = isox.discover_via_html_listing("https://example.test/", ["foo"])
    assert result == "foo-beta.iso"


def test_html_listing_sorts_date_stamped_names(monkeypatch):
    serve_html(
        monkeypatch,
        listing("void-live-x86_64-20251231.iso", "void-live-x86_64-20260101.iso"),
    )
    result = isox.discover_via_html_listing("https://example.test/", ["void"])
    assert result == "void-live-x86_64-20260101.iso"


def test_html_listing_raises_when_nothing_matches(monkeypatch):
    serve_html(monkeypatch, listing("readme.txt", "sha256sums.txt"))
    with pytest.raises(ValueError, match="No matching filename"):
        isox.discover_via_html_listing("https://example.test/", ["arch"])


def test_html_listing_can_target_checksum_files(monkeypatch):
    serve_html(
        monkeypatch,
        listing(
            "Fedora-Workstation-Live-42-1.1.iso",
            "Fedora-Workstation-42-1.1-x86_64-CHECKSUM",
        ),
    )
    result = isox.discover_via_html_listing(
        "https://example.test/", [], must_end_with="CHECKSUM"
    )
    assert result == "Fedora-Workstation-42-1.1-x86_64-CHECKSUM"


def test_version_folder_sorts_numerically(monkeypatch):
    serve_html(monkeypatch, listing("9/", "10/", "8/"))
    assert isox.find_latest_version_folder("https://example.test/") == "10"


def test_version_folder_handles_multipart_versions(monkeypatch):
    serve_html(monkeypatch, listing("21.3/", "22/", "22.1/"))
    assert isox.find_latest_version_folder("https://example.test/") == "22.1"


def test_version_folder_ignores_non_numeric_entries(monkeypatch):
    serve_html(monkeypatch, listing("../", "latest/", "README", "24/"))
    assert isox.find_latest_version_folder("https://example.test/") == "24"


def test_version_folder_raises_when_none_found(monkeypatch):
    serve_html(monkeypatch, listing("../", "latest/", "README"))
    with pytest.raises(ValueError, match="No version-numbered folders"):
        isox.find_latest_version_folder("https://example.test/")


UBUNTU_LISTING = ("26.10/", "26.04.1/", "26.04/", "25.10/", "25.04/", "24.04/")


def test_lts_finder_skips_interim_and_point_releases(monkeypatch):
    serve_html(monkeypatch, listing(*UBUNTU_LISTING))
    assert isox.find_latest_lts_folder("https://example.test/") == "26.04"


def test_generic_finder_would_pick_the_interim_release(monkeypatch):
    # Same listing, other finder. This divergence is the whole point of
    # version_scheme: without it, `isox ubuntu` starts serving interims.
    serve_html(monkeypatch, listing(*UBUNTU_LISTING))
    assert isox.find_latest_version_folder("https://example.test/") == "26.10"


def test_lts_finder_rejects_odd_year_releases(monkeypatch):
    serve_html(monkeypatch, listing("25.04/", "23.04/"))
    with pytest.raises(ValueError, match="No LTS-style"):
        isox.find_latest_lts_folder("https://example.test/")


def test_lts_finder_rejects_non_april_releases(monkeypatch):
    serve_html(monkeypatch, listing("24.10/", "26.10/"))
    with pytest.raises(ValueError, match="No LTS-style"):
        isox.find_latest_lts_folder("https://example.test/")


def test_lts_finder_rejects_point_releases(monkeypatch):
    serve_html(monkeypatch, listing("24.04.2/"))
    with pytest.raises(ValueError, match="No LTS-style"):
        isox.find_latest_lts_folder("https://example.test/")


HTML_DISCOVERY_CONFIG = {
    "iso_filename_contains": ["archlinux"],
    "discovery_method": "html_scan",
    "hash_algo": "sha256",
}

PEEK_DISCOVERY_CONFIG = {
    "iso_filename_contains": ["archlinux"],
    "hash_algo": "sha256",
}


def test_resolve_iso_filename_skips_dead_mirror(monkeypatch):
    def fake_get(url, **kwargs):
        if url.startswith("https://down.test/"):
            raise requests.exceptions.ConnectionError("down")
        return types.SimpleNamespace(
            text=listing("archlinux-x86_64.iso"), raise_for_status=lambda: None
        )

    monkeypatch.setattr(isox.requests, "get", fake_get)
    result = isox.resolve_iso_filename(
        "arch",
        HTML_DISCOVERY_CONFIG,
        ["https://down.test/", "https://up.test/"],
        "sha256sums.txt",
    )
    assert result == "archlinux-x86_64.iso"


def test_resolve_iso_filename_skips_mirror_without_a_match(monkeypatch):
    def fake_get(url, **kwargs):
        if url.startswith("https://stale.test/"):
            html = listing("readme.txt")
        else:
            html = listing("archlinux-x86_64.iso")
        return types.SimpleNamespace(text=html, raise_for_status=lambda: None)

    monkeypatch.setattr(isox.requests, "get", fake_get)
    result = isox.resolve_iso_filename(
        "arch",
        HTML_DISCOVERY_CONFIG,
        ["https://stale.test/", "https://fresh.test/"],
        "sha256sums.txt",
    )
    assert result == "archlinux-x86_64.iso"


def test_resolve_iso_filename_checksum_peek_skips_dead_mirror(monkeypatch):
    def fake_get(url, **kwargs):
        if url.startswith("https://down.test/"):
            raise requests.exceptions.ConnectionError("down")
        return types.SimpleNamespace(
            text="abc123 archlinux-x86_64.iso\n", raise_for_status=lambda: None
        )

    monkeypatch.setattr(isox.requests, "get", fake_get)
    result = isox.resolve_iso_filename(
        "arch",
        PEEK_DISCOVERY_CONFIG,
        ["https://down.test/", "https://up.test/"],
        "sha256sums.txt",
    )
    assert result == "archlinux-x86_64.iso"


def test_resolve_iso_filename_raises_when_every_mirror_fails(monkeypatch):
    def fake_get(url, **kwargs):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(isox.requests, "get", fake_get)
    with pytest.raises(isox.ISOxError, match="any of its"):
        isox.resolve_iso_filename(
            "arch",
            HTML_DISCOVERY_CONFIG,
            ["https://a.test/", "https://b.test/"],
            "sha256sums.txt",
        )


def serve_text(monkeypatch, text):
    """Point isox's requests.get at a canned checksum file instead of the network"""

    def fake_get(url, **kwargs):
        return types.SimpleNamespace(text=text, raise_for_status=lambda: None)

    monkeypatch.setattr(isox.requests, "get", fake_get)


# --- pre-release filtering -------------------------------------------------
# Alpine publishes _rc images into the same directory as the finals they precede,
# and "_" sorts above "-", so the RC wins a straight version comparison.


def test_html_listing_skips_release_candidates(monkeypatch):
    serve_html(
        monkeypatch,
        listing(
            "alpine-extended-3.24.1-x86_64.iso",
            "alpine-extended-3.24.2_rc1-x86_64.iso",
        ),
    )
    result = isox.discover_via_html_listing(
        "https://example.test/", ["extended"], isox.DEFAULT_FILENAME_EXCLUDES
    )
    assert result == "alpine-extended-3.24.1-x86_64.iso"


def test_html_listing_skips_a_release_candidate_of_the_same_version(monkeypatch):
    serve_html(
        monkeypatch,
        listing(
            "alpine-extended-3.24.0-x86_64.iso",
            "alpine-extended-3.24.0_rc1-x86_64.iso",
            "alpine-extended-3.24.0_rc2-x86_64.iso",
        ),
    )
    result = isox.discover_via_html_listing(
        "https://example.test/", ["extended"], isox.DEFAULT_FILENAME_EXCLUDES
    )
    assert result == "alpine-extended-3.24.0-x86_64.iso"


def test_unfiltered_listing_would_pick_the_release_candidate(monkeypatch):
    # Same listing, no excludes. This divergence is the whole point of the
    # default filter: without it, `isox alpine` starts serving RCs.
    serve_html(
        monkeypatch,
        listing(
            "alpine-extended-3.24.0-x86_64.iso",
            "alpine-extended-3.24.0_rc2-x86_64.iso",
        ),
    )
    result = isox.discover_via_html_listing("https://example.test/", ["extended"])
    assert result == "alpine-extended-3.24.0_rc2-x86_64.iso"


def test_shipped_alpine_config_excludes_release_candidates(monkeypatch):
    serve_html(
        monkeypatch,
        listing(
            "alpine-extended-3.24.1-x86_64.iso",
            "alpine-extended-3.24.2_rc1-x86_64.iso",
        ),
    )
    alpine = SHIPPED_DISTROS["alpine"]
    result = isox.resolve_iso_filename(
        "alpine", alpine, alpine["mirrors"], alpine["checksum_filename"]
    )
    assert result == "alpine-extended-3.24.1-x86_64.iso"


# --- checksum-file scanning ------------------------------------------------
# A checksum file covers every artifact of a release, not just the ISO.


def test_checksum_scan_ignores_non_iso_artifacts(monkeypatch):
    # Torrent listed first on purpose: dict order is what used to decide this.
    serve_text(
        monkeypatch,
        "aaa  kali-linux-2026.2-installer-amd64.iso.torrent\n"
        "bbb  kali-linux-2026.2-installer-amd64.iso\n",
    )
    config = {"iso_filename_contains": ["installer-amd64"], "hash_algo": "sha256"}
    result = isox.resolve_iso_filename(
        "kali", config, ["https://kali.test/"], "SHA256SUMS"
    )
    assert result == "kali-linux-2026.2-installer-amd64.iso"


DEBIAN_SHA256SUMS = (
    "aaa  debian-13.6.0-amd64-netinst.iso\n"
    "bbb  debian-edu-13.6.0-amd64-netinst.iso\n"
    "ccc  debian-mac-13.6.0-amd64-netinst.iso\n"
)


def test_checksum_scan_refuses_to_guess_between_matches(monkeypatch):
    serve_text(monkeypatch, DEBIAN_SHA256SUMS)
    config = {"iso_filename_contains": ["netinst", "amd64"], "hash_algo": "sha256"}
    with pytest.raises(isox.ISOxError, match="matched 3 ISOs"):
        isox.resolve_iso_filename(
            "debian", config, ["https://debian.test/"], "SHA256SUMS"
        )


def test_checksum_scan_excludes_narrow_an_ambiguous_match(monkeypatch):
    serve_text(monkeypatch, DEBIAN_SHA256SUMS)
    debian = SHIPPED_DISTROS["debian"]
    result = isox.resolve_iso_filename(
        "debian", debian, ["https://debian.test/"], debian["checksum_filename"]
    )
    assert result == "debian-13.6.0-amd64-netinst.iso"


def test_checksum_scan_honours_the_configured_checksum_format(monkeypatch):
    # A bsd-format checksum file parsed as "multi" yields nothing, and the
    # failure surfaces as a misleading "no mirror could discover a filename".
    serve_text(monkeypatch, "SHA256 (void-live-x86_64-20260101-base.iso) = aaa\n")
    config = {
        "iso_filename_contains": ["live-x86_64-2", "base"],
        "checksum_format": "bsd",
        "hash_algo": "sha256",
    }
    result = isox.resolve_iso_filename(
        "void", config, ["https://void.test/"], "sha256sum.txt"
    )
    assert result == "void-live-x86_64-20260101-base.iso"


# --- version discovery fallback --------------------------------------------


def test_version_discovery_falls_back_to_the_next_url(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        if url.startswith("https://down.test/"):
            raise requests.exceptions.ConnectionError("down")
        return types.SimpleNamespace(
            text=listing("41/", "42/"), raise_for_status=lambda: None
        )

    monkeypatch.setattr(isox.requests, "get", fake_get)
    result = isox.find_latest_version(
        "fedora",
        ["https://down.test/", "https://up.test/"],
        isox.find_latest_version_folder,
    )
    assert result == "42"
    assert (
        "Couldn't discover a version via https://down.test/" in capsys.readouterr().out
    )


def test_version_discovery_raises_when_every_url_fails(monkeypatch):
    def fake_get(url, **kwargs):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(isox.requests, "get", fake_get)
    with pytest.raises(isox.ISOxError, match="version_discovery_url entries"):
        isox.find_latest_version(
            "fedora",
            ["https://a.test/", "https://b.test/"],
            isox.find_latest_version_folder,
        )
