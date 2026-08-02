"""Checks every distros.json entry against the real mirrors.

Deselected by default, because the rest of the suite is hermetic and this one
needs the network and takes about a minute:

    pytest -m live            # just these
    pytest -m live -s         # with the resolved filename and hash printed
    pytest -m live -k rocky   # one distro

This is the check the hermetic tests structurally cannot do: whether a mirror
still has the layout the config claims. It runs everything a real download does
except the transfer itself, so a pass means `python isox.py <distro>` would
fetch the ISO and print "Checksum matches, file is good."
"""

import json

import os

import pytest

import isox

# The repo's own config, not isox.DISTROS_PATH: that resolves ~/.config/isox
# first, so anyone who followed the README's advice about surviving
# `pip install -U` would silently be testing their copy instead of what ships.
DISTROS_PATH = os.path.join(os.path.dirname(isox.__file__), "distros.json")

with open(DISTROS_PATH) as f:
    SHIPPED_DISTROS = json.load(f)

pytestmark = pytest.mark.live


def resolve_everything_but_the_download(name, info):
    """Walk run()'s pipeline up to the point the ISO bytes would be fetched."""
    isox.validate_distro_config(name, info)

    mirrors = info["mirrors"]
    checksum_base = info.get("checksum_base")
    version = None

    if info.get("version_directory"):
        finder = (
            isox.find_latest_lts_folder
            if info.get("version_scheme") == "ubuntu_lts"
            else isox.find_latest_version_folder
        )
        version = isox.find_latest_version(
            name, isox.version_discovery_urls(info), finder
        )
        mirrors = [m.format(version=version) for m in mirrors]
        if checksum_base:
            checksum_base = checksum_base.format(version=version)

    sources = ([checksum_base] if checksum_base else []) + mirrors
    iso_filename = isox.resolve_iso_filename(
        name, info, sources, info["checksum_filename"]
    )

    checksum_source = (
        checksum_base.rstrip("/") if checksum_base else mirrors[0].rstrip("/")
    )
    checksum_filename = isox.resolve_checksum_filename(
        name, info, checksum_source, info["checksum_filename"], iso_filename
    )
    response = isox.requests.get(f"{checksum_source}/{checksum_filename}", timeout=30)
    response.raise_for_status()
    hash_lookup = isox.parse_checksum_file(
        response.text,
        info.get("checksum_format", "multi"),
        info["hash_algo"],
        iso_filename,
    )
    return version, iso_filename, checksum_source, checksum_filename, hash_lookup


@pytest.mark.parametrize("name", sorted(SHIPPED_DISTROS))
def test_distro_resolves_and_has_a_published_checksum(name):
    info = SHIPPED_DISTROS[name]
    version, iso_filename, source, checksum_filename, hash_lookup = (
        resolve_everything_but_the_download(name, info)
    )

    assert not isox.is_unsafe_filename(iso_filename), iso_filename
    assert iso_filename in hash_lookup, (
        f"'{iso_filename}' was discovered for {name}, but {checksum_filename} at "
        f"{source} has no entry for it. A real run would download the ISO and then "
        f"quarantine it as .UNVERIFIED. Entries present: {sorted(hash_lookup)}"
    )

    label = f"[{version}] " if version else ""
    print(f"\n  {name}: {label}{iso_filename}")
    print(f"    {info['hash_algo']}={hash_lookup[iso_filename]}")
    print(f"    checksum from {source}")
