import hashlib
import json
import os
import types

import pytest

import isox


def test_multi_format_parses_hash_and_filename():
    text = "abc123 archlinux-x86_64.iso\n"
    result = isox.parse_checksum_file(text, "multi", "sha256", None)
    assert result == {"archlinux-x86_64.iso": "abc123"}


def test_multi_format_strips_binary_marker():
    text = "def456 *debian-netinst.iso\n"
    result = isox.parse_checksum_file(text, "multi", "sha256", None)
    assert result == {"debian-netinst.iso": "def456"}


def test_multi_format_drops_lines_that_arent_two_fields():
    text = (
        "# comment with several words\n"
        "abc123 good.iso\n"
        "789xyz file with spaces.iso\n"
        "\n"
    )
    result = isox.parse_checksum_file(text, "multi", "sha256", None)
    assert result == {"good.iso": "abc123"}


BSD_TEXT = (
    "# Fedora-Workstation\n"
    "SHA256 (Fedora-Workstation.iso) = aaa111\n"
    "SHA512 (Fedora-Workstation.iso) = bbb222\n"
)


@pytest.mark.parametrize(
    "algo, expected_hash",
    [
        ("sha256", "aaa111"),
        ("sha512", "bbb222"),
    ],
)
def test_bsd_format_selects_configured_algorithm(algo, expected_hash):
    result = isox.parse_checksum_file(BSD_TEXT, "bsd", algo, None)
    assert result == {"Fedora-Workstation.iso": expected_hash}


def test_single_format_is_the_whole_file_stripped():
    result = isox.parse_checksum_file("  deadbeef\n", "single", "sha256", "arch.iso")
    assert result == {"arch.iso": "deadbeef"}


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("archlinux-x86_64.iso", False),
        ("../evil.iso", True),
        ("sub/dir.iso", True),
        ("win\\path.iso", True),
        ("..hidden.iso", True),
        ("foo..bar.iso", True),
        ("", False),
    ],
)
def test_is_unsafe_filename(filename, expected):
    assert isox.is_unsafe_filename(filename) is expected


@pytest.mark.parametrize(
    "status_code, headers, expected",
    [
        (200, {"Content-Length": "1000"}, 1000),
        (206, {"Content-Range": "bytes 500-999/1000"}, 1000),
        (206, {"Content-Range": "bytes 500-999/*"}, None),
        (206, {}, None),
        (200, {}, None),
        (200, {"Content-Length": "abc"}, None),
    ],
)
def test_total_size_from(status_code, headers, expected):
    response = types.SimpleNamespace(status_code=status_code, headers=headers)
    assert isox.total_size_from(response) == expected


VALID_CONFIG = {
    "mirrors": ["https://example.test/iso/"],
    "checksum_filename": "sha256sums.txt",
    "hash_algo": "sha256",
    "iso_filename": "example.iso",
}


@pytest.mark.parametrize(
    "config, message",
    [
        ({}, "is missing"),
        (
            {
                "mirrors": [],
                "checksum_filename": "sha256sums.txt",
                "hash_algo": "sha256",
                "iso_filename": "example.iso",
            },
            "empty mirrors list",
        ),
        (
            {
                "mirrors": ["https://example.test/iso/"],
                "checksum_filename": "sha256sums.txt",
                "hash_algo": "sha256",
                "iso_filename": "example.iso",
                "version_directory": True,
            },
            "no version_discovery_url",
        ),
        (
            {
                "mirrors": ["https://example.test/iso/"],
                "checksum_filename": "sha256sums.txt",
                "hash_algo": "sha256",
            },
            "iso_filename or iso_filename_contains",
        ),
    ],
)
def test_rejects_invalid_config(config, message):
    with pytest.raises(isox.ISOxError, match=message):
        isox.validate_distro_config("testdistro", config)


def test_accepts_minimal_valid_config():
    isox.validate_distro_config("testdistro", VALID_CONFIG)


DISTROS_PATH = os.path.join(os.path.dirname(isox.__file__), "distros.json")

with open(DISTROS_PATH, "r") as f:
    SHIPPED_DISTROS = json.load(f)


@pytest.mark.parametrize("name", sorted(SHIPPED_DISTROS))
def test_shipped_distro_entry_validates(name):
    isox.validate_distro_config(name, SHIPPED_DISTROS[name])


def test_compute_hash_known_digest(tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello")
    assert (
        isox.compute_hash(target, "sha256")
        == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_compute_hash_empty_file(tmp_path):
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    assert (
        isox.compute_hash(target, "sha256")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_compute_hash_spans_multiple_chunks(tmp_path):
    data = b"x" * 20000
    target = tmp_path / "big.bin"
    target.write_bytes(data)
    assert isox.compute_hash(target, "sha256") == hashlib.sha256(data).hexdigest()


def test_compute_hash_rejects_unknown_algorithm(tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello")
    with pytest.raises(ValueError, match="Unsupported hash algorithm"):
        isox.compute_hash(target, "notanalgo")


HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_verify_checksum_match(tmp_path):
    target = tmp_path / "arch.iso"
    target.write_bytes(b"hello")
    lookup = {"arch.iso": HELLO_SHA256}
    assert isox.verify_checksum(target, "arch.iso", lookup, "sha256") is True


def test_verify_checksum_mismatch(tmp_path):
    target = tmp_path / "arch.iso"
    target.write_bytes(b"hello")
    lookup = {"arch.iso": "0" * 64}
    assert isox.verify_checksum(target, "arch.iso", lookup, "sha256") is False


def test_verify_checksum_missing_entry_raises(tmp_path):
    target = tmp_path / "arch.iso"
    target.write_bytes(b"hello")
    with pytest.raises(ValueError, match="No checksum entry found"):
        isox.verify_checksum(target, "arch.iso", {}, "sha256")
