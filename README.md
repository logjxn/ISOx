# ISOx

![Python](https://img.shields.io/badge/python-3.10+-blue)
[![PyPI](https://img.shields.io/pypi/v/isox)](https://pypi.org/project/isox/)
![License](https://img.shields.io/github/license/logjxn/ISOx)
![Release](https://img.shields.io/github/v/release/logjxn/ISOx)
![OS](https://img.shields.io/badge/platform-Linux-orange)
![CI](https://github.com/logjxn/ISOx/actions/workflows/ci.yml/badge.svg)

A command-line tool for downloading and verifying Linux distribution ISOs. 

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
                                          (fastest mirror)  (distro's own host)
```

Already have an ISO? `isox <distro> --verify FILE` checks it against the distro’s own checksum without downloading anything.

## Why

Manually verifying checksums gets tedious quickly, making it easy to skip. Skipping verification can pose an integrity risk (modified ISOs, corruption, etc.), so ISOx automates the process.

I hope this tool makes getting started with Linux a little faster, easier, and safer for anyone who wants to use it.

## Install

From PyPI:

    pip install isox
    isox arch

Or straight from a clone:

    pip install .
    isox arch

## Usage

Once installed from PyPI, `isox` works as a bare command. From a clone, use `python isox.py`. Examples below use the clone form.

List every supported distro:
```bash
python isox.py --list
```

Save somewhere other than `./ISOx_Downloads`:
```bash
python isox.py arch --output-dir /example/directory
```

Pick an older release instead of the newest:
```bash
python isox.py ubuntu-server --release 24.04
python isox.py proxmox --release 8
python isox.py mint --release 22        # newest 22.x
```

Verify an ISO you already have (from a browser, a torrent, a USB stick):
```bash
python isox.py fedora --release 44 --verify ~/Downloads/Fedora-Workstation-Live-44-1.7.x86_64.iso
python isox.py ubuntu --release 24.04 --verify ubuntu-24.04.5.1-desktop-amd64.iso
```

Downloaded ISOs are saved to the created folder `ISOx_Downloads/`. Output looks like:

```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.33 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 1.98 MB/s
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso sampled at 0.08 MB/s
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
[##############################] 100.0%    3.41 MB/s
Checksum matches, file is good.
```

## Features

- **Config-driven distro support** - add supported distributions through `distros.json` without changing code.
- **Version-folder auto-discovery** - for distros with no stable "latest" alias, the current version-numbered directory is discovered by scanning a parent directory and sorting versions (folder names).
- **Release selection** - `--release` picks an older release, such as Ubuntu 24.04 or Proxmox 8. A partial version like `22` gets the newest release in that series.
- **Mirror selection** - tests available mirrors and selects the fastest.
- **Resumable downloads** - continues interrupted downloads, while discarding out of date copies.
- **Live progress bar** - shows percentage and real-time throughput, and degrades to a plain byte counter if the server won't report a total size.
- **Verify existing ISOs** - `--verify` checks a file you already have against the distro's checksum, without downloading or renaming anything.

## Config format (`distros.json`)

Every distro entry needs `mirrors`, `checksum_filename`, and `hash_algo` at minimum. Everything else is optional and only needed if that distro deviates from the simplest cases.

If the included mirrors are not ideal for your location, you can easily update them. Just find a suitable mirror from the distro's official mirror list and replace the URL in distros.json. The tool will then handle the rest. HTTPS only.

```json
{
    "arch": {
        "mirrors": ["https://fastly.mirror.pkgbuild.com/iso/latest/"],
        "checksum_base": "https://geo.mirror.pkgbuild.com/iso/latest/",
        "checksum_filename": "sha256sums.txt",
        "hash_algo": "sha256",
        "iso_filename": "archlinux-x86_64.iso"
    },
    "fedora": {
        "mirrors": [
            "https://dl.fedoraproject.org/pub/fedora/linux/releases/{version}/Workstation/x86_64/iso/",
            "https://mirror.cs.princeton.edu/pub/mirrors/fedora/linux/releases/{version}/Workstation/x86_64/iso/",
            "https://mirror.arizona.edu/fedora/linux/releases/{version}/Workstation/x86_64/iso/"
        ],
        "version_directory" : true,
        "version_discovery_url" : [
            "https://dl.fedoraproject.org/pub/fedora/linux/releases/",
            "https://mirror.arizona.edu/fedora/linux/releases/"
        ],
        "checksum_base": "https://dl.fedoraproject.org/pub/fedora/linux/releases/{version}/Workstation/x86_64/iso/",
        "checksum_filename" : "CHECKSUM",
        "checksum_discovery_method" : "html_scan",
        "checksum_format" : "bsd",
        "discovery_method": "html_scan",
        "hash_algo": "sha256",
        "iso_filename_contains": ["Workstation", "x86_64"]
    }
}
```

### Checksum verification

The checksum is fetched on every run. Files that fail verification are renamed to `.FAILED`. Files that cannot be verified remain `.UNVERIFIED`.

## Security

ISOx detects corruption, incomplete downloads, and ISOs that don't match their published checksums.

It does not authenticate the checksum itself. If a distribution's infrastructure is compromised, an attacker could replace both the ISO and its checksum.

ISOx does not verify GPG signatures. See [SECURITY.md](https://github.com/logjxn/ISOx/blob/main/.github/SECURITY.md) for details.

## Requirements

- Python 3.10+
- `requests`
- `beautifulsoup4` 

## Development

    pip install -e '.[dev]'
    pytest
    black --check .
    ruff check .
    bandit isox.py

    pytest -m live       # all distros
    pytest -m live -s    # printing each resolved filename and hash
    pytest -m live -k rocky

## License

MIT License: see [LICENSE](https://github.com/logjxn/ISOx/blob/main/LICENSE) for details. Feel free to use, modify, or build on this.
