import os
import time

import pytest
import requests

import isox

BODY = b"0123456789" * 100  # 1000 bytes


class FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        pass


class FakeServer:
    """Serves BODY, honors Range, reports an ETag, records what it was asked for."""

    def __init__(self, body=BODY, etag='"v1"', ignore_range=False):
        self.body = body
        self.etag = etag
        self.ignore_range = ignore_range
        self.ranges_seen = []

    def get(self, url, stream=False, timeout=None, headers=None, **kwargs):
        rng = (headers or {}).get("Range")
        self.ranges_seen.append(rng)
        total = len(self.body)

        if rng is None or self.ignore_range:
            return FakeResponse(
                200, {"Content-Length": str(total), "ETag": self.etag}, self.body
            )

        start = int(rng.split("=")[1].split("-")[0])
        if start >= total:
            return FakeResponse(416, {"ETag": self.etag}, b"")
        return FakeResponse(
            206,
            {"Content-Range": f"bytes {start}-{total - 1}/{total}", "ETag": self.etag},
            self.body[start:],
        )


def test_download_writes_file_and_cleans_up(tmp_path, monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"

    isox.download_file("https://example.test/arch.iso", str(dest))

    assert dest.read_bytes() == BODY
    assert not (tmp_path / "arch.iso.part").exists()
    assert not (tmp_path / "arch.iso.part.meta").exists()
    assert server.ranges_seen == [None]


def test_download_resumes_from_existing_part(tmp_path, monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(BODY[:400])
    (tmp_path / "arch.iso.part.meta").write_text('"v1"')

    isox.download_file("https://example.test/arch.iso", str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=400-"]


def test_download_discards_partial_with_stale_fingerprint(
    tmp_path, monkeypatch, capsys
):
    server = FakeServer(etag='"v2"')
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(b"OLD" * 100)
    (tmp_path / "arch.iso.part.meta").write_text('"v1"')

    isox.download_file("https://example.test/arch.iso", str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=300-", None]
    assert "doesn't match file on server" in capsys.readouterr().out


def test_download_restarts_when_partial_is_larger_than_source(tmp_path, monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(b"x" * 2000)
    (tmp_path / "arch.iso.part.meta").write_text('"v1"')

    isox.download_file("https://example.test/arch.iso", str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=2000-", None]


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    server = FakeServer(ignore_range=True)
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(BODY[:400])
    (tmp_path / "arch.iso.part.meta").write_text('"v1"')

    isox.download_file("https://example.test/arch.iso", str(dest))

    assert dest.read_bytes() == BODY
    assert len(dest.read_bytes()) == 1000  # not 1400


def test_read_meta_returns_none_when_absent(tmp_path):
    assert isox.read_meta(str(tmp_path / "nope.meta")) is None


def test_read_meta_strips_whitespace(tmp_path):
    meta = tmp_path / "x.meta"
    meta.write_text('  "v1"\n')
    assert isox.read_meta(str(meta)) == '"v1"'


def test_write_meta_skips_none_fingerprint(tmp_path):
    meta = tmp_path / "x.meta"
    isox.write_meta(str(meta), None)
    assert not meta.exists()


def test_discard_part_tolerates_missing_files(tmp_path):
    # No assert needed: the test fails if this raises.
    isox.discard_part(str(tmp_path / "a.part"), str(tmp_path / "a.part.meta"))


def test_part_is_stale_compares_fingerprints(tmp_path):
    part = tmp_path / "a.part"
    part.write_bytes(b"x")
    meta = tmp_path / "a.part.meta"
    meta.write_text('"v1"')

    assert isox.part_is_stale(str(part), str(meta), '"v1"') is False
    assert isox.part_is_stale(str(part), str(meta), '"v2"') is True


def test_part_is_stale_falls_back_to_age(tmp_path):
    part = tmp_path / "a.part"
    part.write_bytes(b"x")
    meta = tmp_path / "a.part.meta"  # deliberately never written

    assert isox.part_is_stale(str(part), str(meta), None) is False

    old = time.time() - (isox.PART_MAX_AGE_SECONDS + 60)
    os.utime(part, (old, old))
    assert isox.part_is_stale(str(part), str(meta), None) is True


def test_unreachable_mirror_returns_none(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(isox.requests, "get", boom)
    assert isox.check_mirror_throughput("https://example.test/a.iso") is None


def test_fastest_mirror_wins(monkeypatch):
    speeds = {
        "https://slow.test/x.iso": 1_000_000,
        "https://fast.test/x.iso": 5_000_000,
    }
    monkeypatch.setattr(isox, "check_mirror_throughput", lambda url: speeds[url])
    assert (
        isox.find_fastest_mirror_by_throughput(list(speeds))
        == "https://fast.test/x.iso"
    )


def test_unreachable_mirrors_are_skipped(monkeypatch):
    speeds = {"https://down.test/x.iso": None, "https://up.test/x.iso": 2_000_000}
    monkeypatch.setattr(isox, "check_mirror_throughput", lambda url: speeds[url])
    assert (
        isox.find_fastest_mirror_by_throughput(list(speeds)) == "https://up.test/x.iso"
    )


def test_all_mirrors_down_raises(monkeypatch):
    monkeypatch.setattr(isox, "check_mirror_throughput", lambda url: None)
    with pytest.raises(isox.ISOxError, match="none of the mirrors"):
        isox.find_fastest_mirror_by_throughput(["https://a.test/x.iso"])
