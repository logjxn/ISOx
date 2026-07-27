import hashlib
import json
import os
import site
import sys
import sysconfig

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

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


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
    config_path = tmp_path / "distros.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(isox, "DISTROS_PATH", str(config_path))
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
    monkeypatch.setattr(isox, "DISTROS_PATH", str(tmp_path / "distros.json"))
    monkeypatch.setattr(sys, "argv", ["isox.py", "testdistro"])

    with pytest.raises(SystemExit) as excinfo:
        isox.main()

    assert excinfo.value.code == 1
    assert "distros.json not found" in capsys.readouterr().out


def test_malformed_distros_json_exits_1(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "distros.json"
    config_path.write_text("{not json")
    monkeypatch.setattr(isox, "DISTROS_PATH", str(config_path))
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


def test_version_flag_prints_version_and_exits_0(tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch, argv=("isox.py", "--version"))

    with pytest.raises(SystemExit) as excinfo:
        isox.run()

    assert excinfo.value.code == 0
    assert isox.__version__ in capsys.readouterr().out


def test_env_override_short_circuits_the_search(tmp_path, monkeypatch):
    monkeypatch.setenv("ISOX_DISTROS", str(tmp_path / "mine.json"))
    assert isox.distros_path_candidates() == [str(tmp_path / "mine.json")]


def test_user_config_outranks_the_bundled_copy(tmp_path, monkeypatch):
    # The reason this ordering exists: pip replaces what it installed, so a
    # customised mirror list kept only in the bundled copy silently reverts on
    # `pip install -U isox`. A user's own file has to win.
    monkeypatch.delenv("ISOX_DISTROS", raising=False)
    candidates = isox.distros_path_candidates()

    assert candidates[0] == os.path.join(isox.user_config_dir(), "distros.json")
    assert candidates[1] == os.path.join(
        os.path.dirname(os.path.abspath(isox.__file__)), "distros.json"
    )


def test_every_install_scheme_data_dir_is_searched(monkeypatch):
    """A wheel's data files land wherever the install scheme puts them.

    Checking only sys.prefix means `pip install --user` and Debian's /usr/local
    default can't find distros.json at all, and the tool doesn't start.
    """
    monkeypatch.delenv("ISOX_DISTROS", raising=False)
    candidates = isox.distros_path_candidates()

    for base in (sysconfig.get_path("data"), site.getuserbase(), sys.prefix):
        expected = os.path.join(base, "share", "isox", "distros.json")
        assert expected in candidates, f"{base} not searched"


def test_candidates_are_deduplicated(monkeypatch):
    # sys.prefix and the data scheme are the same path on a normal install, and
    # a "Looked in:" list that repeats itself reads like a bug.
    monkeypatch.delenv("ISOX_DISTROS", raising=False)
    candidates = isox.distros_path_candidates()
    assert len(candidates) == len(set(candidates))


def test_resolve_picks_the_first_file_that_exists(tmp_path, monkeypatch):
    missing = tmp_path / "nope" / "distros.json"
    present = tmp_path / "yes" / "distros.json"
    present.parent.mkdir(parents=True)
    present.write_text("{}")

    monkeypatch.setattr(
        isox, "distros_path_candidates", lambda: [str(missing), str(present)]
    )
    assert isox.resolve_distros_path() == str(present)


def test_resolve_falls_back_to_the_last_candidate_when_nothing_exists(
    tmp_path, monkeypatch
):
    a = str(tmp_path / "a.json")
    b = str(tmp_path / "b.json")
    monkeypatch.setattr(isox, "distros_path_candidates", lambda: [a, b])
    # Reported so the "not found" error names a real location rather than nothing.
    assert isox.resolve_distros_path() == b


@pytest.mark.parametrize(
    "platform, env, expected_parent",
    [
        (
            "nt",
            {"APPDATA": os.path.join("C:", "Users", "x", "AppData", "Roaming")},
            os.path.join("C:", "Users", "x", "AppData", "Roaming"),
        ),
        (
            "posix",
            {"XDG_CONFIG_HOME": os.path.join("/home", "x", ".config")},
            os.path.join("/home", "x", ".config"),
        ),
    ],
)
def test_user_config_dir_follows_platform_convention(
    monkeypatch, platform, env, expected_parent
):
    monkeypatch.setattr(os, "name", platform)
    for key in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert isox.user_config_dir() == os.path.join(expected_parent, "isox")


def test_missing_distros_json_error_lists_where_it_looked(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(isox, "DISTROS_PATH", str(tmp_path / "distros.json"))
    monkeypatch.setattr(
        isox,
        "distros_path_candidates",
        lambda: ["/one/distros.json", "/two/distros.json"],
    )
    monkeypatch.setattr(sys, "argv", ["isox.py", "testdistro"])

    with pytest.raises(SystemExit):
        isox.main()

    out = capsys.readouterr().out
    assert "/one/distros.json" in out
    assert "/two/distros.json" in out
    assert "ISOX_DISTROS" in out


def test_output_dir_flag_redirects_the_download(tmp_path, monkeypatch):
    setup_repo(
        tmp_path,
        monkeypatch,
        argv=("isox.py", "testdistro", "--output-dir", "elsewhere"),
    )
    monkeypatch.setattr(isox.requests, "get", router(f"{ISO_SHA256}  test.iso\n"))

    isox.run()

    assert (tmp_path / "elsewhere" / "test.iso").read_bytes() == ISO_BODY
    assert not (tmp_path / "ISOx_Downloads").exists()


CHECKSUM_BASE_CONFIG = {
    "testdistro": {
        "mirrors": [
            "https://fast-mirror.test/iso/",
            "https://canonical.test/iso/",
        ],
        "checksum_base": "https://canonical.test/iso/",
        "checksum_filename": "sha256sums.txt",
        "hash_algo": "sha256",
        "iso_filename": "test.iso",
    }
}


def test_checksum_comes_from_the_canonical_host_not_the_fastest_mirror(
    tmp_path, monkeypatch, capsys
):
    # A rogue mirror can serve a modified ISO and a hash that matches it. Here the
    # fast mirror serves both a bad ISO and a hash for it; the canonical host's
    # checksum is the one that has to win.
    tampered = b"tampered payload\n" * 64
    checksum_requests = []

    def fake_get(url, stream=False, timeout=None, headers=None, **kwargs):
        if url.endswith("sha256sums.txt"):
            checksum_requests.append(url)
            if url.startswith("https://fast-mirror.test/"):
                bad = hashlib.sha256(tampered).hexdigest()
                return FakeResponse(text=f"{bad}  test.iso\n")
            return FakeResponse(text=f"{ISO_SHA256}  test.iso\n")
        body = tampered if url.startswith("https://fast-mirror.test/") else ISO_BODY
        return FakeResponse(
            200, {"Content-Length": str(len(body)), "ETag": '"v1"'}, body
        )

    setup_repo(tmp_path, monkeypatch, config=CHECKSUM_BASE_CONFIG)
    monkeypatch.setattr(isox.requests, "get", fake_get)
    monkeypatch.setattr(
        isox,
        "check_mirror_throughput",
        lambda url: 9_000_000 if url.startswith("https://fast-mirror.test/") else 1.0,
    )

    with pytest.raises(SystemExit) as excinfo:
        isox.run()

    assert excinfo.value.code == 1
    assert checksum_requests == ["https://canonical.test/iso/sha256sums.txt"]
    assert (tmp_path / "ISOx_Downloads" / "test.iso.FAILED").exists()
    assert "checksum mismatch" in capsys.readouterr().out
