import json
import os
import time

import pytest
import requests

import isox

BODY = b"0123456789" * 100  # 1000 bytes
URL = "https://example.test/arch.iso"


def meta_for(url, fingerprint):
    """A .meta in the current on-disk format."""
    return json.dumps({"url": url, "fingerprint": fingerprint})


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

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


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

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert not (tmp_path / "arch.iso.part").exists()
    assert not (tmp_path / "arch.iso.part.meta").exists()
    assert server.ranges_seen == [None]


def test_download_resumes_from_existing_part(tmp_path, monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(BODY[:400])
    (tmp_path / "arch.iso.part.meta").write_text(meta_for(URL, '"v1"'))

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=400-"]


def test_download_discards_partial_with_stale_fingerprint(
    tmp_path, monkeypatch, capsys
):
    server = FakeServer(etag='"v2"')
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(b"OLD" * 100)
    (tmp_path / "arch.iso.part.meta").write_text(meta_for(URL, '"v1"'))

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=300-", None]
    assert "doesn't match file on server" in capsys.readouterr().out


def test_download_keeps_partial_when_the_mirror_changes(tmp_path, monkeypatch):
    # ETags are per-server, so the winner of the speed race changing between runs
    # must not look like the file changing. Restarting here would throw away a
    # partial that is byte-for-byte fine.
    server = FakeServer(etag='"other-mirror-etag"')
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(BODY[:400])
    (tmp_path / "arch.iso.part.meta").write_text(
        meta_for("https://slow-mirror.test/arch.iso", '"v1"')
    )

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=400-"]  # resumed, not restarted


def test_download_restarts_when_partial_is_larger_than_source(tmp_path, monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(b"x" * 2000)
    (tmp_path / "arch.iso.part.meta").write_text(meta_for(URL, '"v1"'))

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert server.ranges_seen == ["bytes=2000-", None]


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    server = FakeServer(ignore_range=True)
    monkeypatch.setattr(isox.requests, "get", server.get)
    dest = tmp_path / "arch.iso"
    (tmp_path / "arch.iso.part").write_bytes(BODY[:400])
    (tmp_path / "arch.iso.part.meta").write_text(meta_for(URL, '"v1"'))

    isox.download_file(URL, str(dest))

    assert dest.read_bytes() == BODY
    assert len(dest.read_bytes()) == 1000  # not 1400


def test_download_keeps_part_when_the_transfer_ends_early(tmp_path, monkeypatch):
    # A short read is exactly what resuming is for, so the .part has to survive
    # rather than being promoted and then quarantined as a corrupt ISO.
    truncated = FakeResponse(200, {"Content-Length": "1000"}, BODY[:600])
    monkeypatch.setattr(isox.requests, "get", lambda *a, **k: truncated)
    dest = tmp_path / "arch.iso"

    with pytest.raises(isox.ISOxError, match="ended early"):
        isox.download_file(URL, str(dest))

    assert (tmp_path / "arch.iso.part").read_bytes() == BODY[:600]
    assert not dest.exists()


def test_request_headers_identifies_isox():
    headers = isox.request_headers()
    assert (
        headers["User-Agent"]
        == f"ISOx/{isox.__version__} (+https://github.com/logjxn/ISOx)"
    )
    assert "python-requests" not in headers["User-Agent"]


def test_request_headers_keeps_the_range_alongside_the_agent():
    headers = isox.request_headers({"Range": "bytes=400-"})
    assert headers["Range"] == "bytes=400-"
    assert "ISOx" in headers["User-Agent"]


def test_every_outbound_request_identifies_itself(monkeypatch):
    """Guards the whole surface: a new requests.get without headers fails here.

    Being nameable is only worth anything if it's true of every request, and the
    easy mistake is adding a call site and forgetting.
    """
    import inspect

    source = inspect.getsource(isox)
    calls = [
        line.strip()
        for line in source.splitlines()
        if "requests.get(" in line and not line.strip().startswith("#")
    ]
    assert calls, "no requests.get call sites found - did the module change shape?"
    unidentified = [c for c in calls if "headers=" not in c]
    assert not unidentified, f"requests.get without headers: {unidentified}"


def test_download_sends_the_user_agent(tmp_path, monkeypatch):
    seen = {}

    def capture(url, stream=False, timeout=None, headers=None, **kwargs):
        seen.update(headers or {})
        return FakeResponse(200, {"Content-Length": str(len(BODY))}, BODY)

    monkeypatch.setattr(isox.requests, "get", capture)
    isox.download_file(URL, str(tmp_path / "arch.iso"))

    assert "ISOx" in seen["User-Agent"]


def test_throughput_sample_sends_the_user_agent(monkeypatch):
    seen = {}

    def capture(url, headers=None, stream=False, timeout=None, **kwargs):
        seen.update(headers or {})
        return FakeResponse(206, {}, b"x" * 4096)

    monkeypatch.setattr(isox.requests, "get", capture)
    isox.check_mirror_throughput("https://example.test/a.iso", sample_bytes=4096)

    assert "ISOx" in seen["User-Agent"]
    assert seen["Range"] == "bytes=0-4095"


def test_read_meta_returns_none_when_absent(tmp_path):
    assert isox.read_meta(str(tmp_path / "nope.meta")) is None


def test_read_meta_round_trips_url_and_fingerprint(tmp_path):
    meta = tmp_path / "x.meta"
    isox.write_meta(str(meta), URL, '"v1"')
    assert isox.read_meta(str(meta)) == {"url": URL, "fingerprint": '"v1"'}


def test_read_meta_reads_pre_3_0_bare_fingerprint(tmp_path):
    # An ETag is a quoted string, so json.loads() parses one without complaint.
    # The old format has to be recognised by shape, not by whether it's valid JSON.
    meta = tmp_path / "x.meta"
    meta.write_text('  "v1"\n')
    assert isox.read_meta(str(meta)) == {"url": None, "fingerprint": '"v1"'}


def test_write_meta_skips_none_fingerprint(tmp_path):
    meta = tmp_path / "x.meta"
    isox.write_meta(str(meta), URL, None)
    assert not meta.exists()


def test_discard_part_tolerates_missing_files(tmp_path):
    # No assert needed: the test fails if this raises.
    isox.discard_part(str(tmp_path / "a.part"), str(tmp_path / "a.part.meta"))


def test_part_is_stale_compares_fingerprints_from_the_same_mirror(tmp_path):
    part = tmp_path / "a.part"
    part.write_bytes(b"x")
    meta = tmp_path / "a.part.meta"
    meta.write_text(meta_for(URL, '"v1"'))

    assert isox.part_is_stale(str(part), str(meta), URL, '"v1"') is False
    assert isox.part_is_stale(str(part), str(meta), URL, '"v2"') is True


def test_part_is_stale_ignores_fingerprints_from_a_different_mirror(tmp_path):
    part = tmp_path / "a.part"
    part.write_bytes(b"x")
    meta = tmp_path / "a.part.meta"
    meta.write_text(meta_for("https://other.test/a.iso", '"v1"'))

    # Different mirror, different ETag scheme: this says nothing about the bytes,
    # so it falls through to the age check, which a fresh .part passes.
    assert isox.part_is_stale(str(part), str(meta), URL, '"v2"') is False

    old = time.time() - (isox.PART_MAX_AGE_SECONDS + 60)
    os.utime(part, (old, old))
    assert isox.part_is_stale(str(part), str(meta), URL, '"v2"') is True


def test_part_is_stale_falls_back_to_age(tmp_path):
    part = tmp_path / "a.part"
    part.write_bytes(b"x")
    meta = tmp_path / "a.part.meta"  # deliberately never written

    assert isox.part_is_stale(str(part), str(meta), URL, None) is False

    old = time.time() - (isox.PART_MAX_AGE_SECONDS + 60)
    os.utime(part, (old, old))
    assert isox.part_is_stale(str(part), str(meta), URL, None) is True


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
