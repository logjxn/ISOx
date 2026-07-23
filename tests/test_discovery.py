import types

import pytest

import isox


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


def test_html_listing_sorts_lexicographically_not_numerically(monkeypatch):
    serve_html(
        monkeypatch, listing("void-live-x86_64-9.iso", "void-live-x86_64-10.iso")
    )
    result = isox.discover_via_html_listing("https://example.test/", ["void"])
    assert result == "void-live-x86_64-9.iso"


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
