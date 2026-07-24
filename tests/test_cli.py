import hashlib
import json
import sys

import pytest
import requests

import isox

ISO_BODY = b"ISOx test payload\n" * 64
ISO_SHA256 = hashlib.sha256(ISO_BODY).hexdigest()

DISTRO_CONFIG = {
    "testdistro": {
        "mirrors": ["https://mirror.test/iso/"],
        "checksum_filename": "sha256sums.txt",
        "hash_algo": "sha256",
        "iso_filename": "test.iso",
    }
}


class FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b"", text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        pass


def router(checksum_text):
    """One fake serving both the checksum file and the ISO, keyed on URL."""

    def fake_get(url, stream=False, timeout=None, headers=None, **kwargs):
        if url.endswith("sha256sums.txt"):
            return FakeResponse(text=checksum_text)
        return FakeResponse(
            200,
            {"Content-Length": str(len(ISO_BODY)), "ETag": '"v1"'},
            ISO_BODY,
        )

    return fake_get


def setup_repo(
    tmp_path, monkeypatch, config=DISTRO_CONFIG, argv=("isox.py", "testdistro")
):
    (tmp_path / "distros.json").write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", list(argv))


def test_happy_path_downloads_and_verifies(tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(isox.requests, "get", router(f"{ISO_SHA256}  test.iso\n"))

    isox.run()

    assert "Checksum matches, file is good." in capsys.readouterr().out
    assert (tmp_path / "ISOx_Downloads" / "test.iso").read_bytes() == ISO_BODY


def test_checksum_mismatch_quarantines_as_failed(tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(isox.requests, "get", router(f"{'0' * 64}  test.iso\n"))

    with pytest.raises(SystemExit) as excinfo:
        isox.run()

    assert excinfo.value.code == 1
    assert (tmp_path / "ISOx_Downloads" / "test.iso.FAILED").exists()
    assert not (tmp_path / "ISOx_Downloads" / "test.iso").exists()
    assert "checksum mismatch" in capsys.readouterr().out


def test_missing_checksum_entry_quarantines_as_unverified(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(isox.requests, "get", router(f"{ISO_SHA256}  other.iso\n"))

    with pytest.raises(SystemExit) as excinfo:
        isox.run()

    assert excinfo.value.code == 1
    assert (tmp_path / "ISOx_Downloads" / "test.iso.UNVERIFIED").exists()


def test_list_flag_prints_distros(tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch, argv=("isox.py", "--list"))

    isox.run()

    out = capsys.readouterr().out
    assert "1 distros available:" in out
    assert "testdistro" in out
    assert not (tmp_path / "ISOx_Downloads").exists()


def test_unsafe_filename_is_rejected(tmp_path, monkeypatch, capsys):
    config = {"evil": dict(DISTRO_CONFIG["testdistro"], iso_filename="../escape.iso")}
    setup_repo(tmp_path, monkeypatch, config=config, argv=("isox.py", "evil"))

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 1
    assert "looks unsafe" in capsys.readouterr().out


def test_missing_distros_json_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["isox.py", "testdistro"])

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 1
    assert "distros.json not found" in capsys.readouterr().out


def test_malformed_distros_json_exits_1(tmp_path, monkeypatch, capsys):
    (tmp_path / "distros.json").write_text("{not json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["isox.py"])

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 1
    assert "malformed" in capsys.readouterr().out


def test_all_mirrors_down_exits_1(tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(isox.requests, "get", boom)

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 1
    assert "none of the mirrors" in capsys.readouterr().out


def test_keyboard_interrupt_exits_130(monkeypatch, capsys):
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(isox, "run", interrupted)

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 130
    assert "Interrupted" in capsys.readouterr().out


UBUNTU_CONFIG = {
    "ubuntu": {
        "mirrors": ["https://mirror.test/{version}/"],
        "version_directory": True,
        "version_discovery_url": "https://mirror.test/",
        "version_scheme": "ubuntu_lts",
        "checksum_filename": "SHA256SUMS",
        "hash_algo": "sha256",
        "iso_filename": "test.iso",
    }
}


def test_ubuntu_config_resolves_to_lts_not_interim(tmp_path, monkeypatch, capsys):
    listing = '<a href="26.10/">a</a><a href="26.04/">b</a>'

    def fake_get(url, stream=False, timeout=None, headers=None, **kwargs):
        if url.rstrip("/") == "https://mirror.test":
            return FakeResponse(text=listing)
        if url.endswith("SHA256SUMS"):
            return FakeResponse(text=f"{ISO_SHA256}  test.iso\n")
        return FakeResponse(
            200, {"Content-Length": str(len(ISO_BODY)), "ETag": '"v1"'}, ISO_BODY
        )

    setup_repo(tmp_path, monkeypatch, config=UBUNTU_CONFIG, argv=("isox.py", "ubuntu"))
    monkeypatch.setattr(isox.requests, "get", fake_get)

    isox.run()

    assert "Discovered latest version: 26.04" in capsys.readouterr().out
