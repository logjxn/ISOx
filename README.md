# ISOx

![Python](https://img.shields.io/badge/python-3.10+-blue)
[![PyPI](https://img.shields.io/pypi/v/isox)](https://pypi.org/project/isox/)
![License](https://img.shields.io/github/license/logjxn/ISOx)
![Release](https://img.shields.io/github/v/release/logjxn/ISOx)
![OS](https://img.shields.io/badge/platform-Linux-orange)
![CI](https://github.com/logjxn/ISOx/actions/workflows/ci.yml/badge.svg)

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest source, and cryptographically verifies integrity against the checksum by the official host, so you never have to manually hunt down hashes or skip verification again.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
                                          (fastest mirror)  (distro's own host)
```

The ISO comes from whichever mirror is fastest right now. The checksum comes from the
distribution's own server, so the mirror that hands you the bytes is not also giving the checksum.
See [What verification does and doesn't cover](#what-verification-does-and-doesnt-cover).

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification simple.

Furthermore, I simply love Linux. It's been my daily driver for a while now, and I want to see it continue to grow. I hope this tool makes getting started with Linux a little faster, easier, and safer for anyone who wants to use it.

## Install

From PyPI:

    pip install isox
    isox arch

Or straight from a clone:

    pip install .
    isox arch

## Usage

Once installed from PyPI, `isox` works as a bare command. From a clone, use `python isox.py`. The two are interchangeable; examples below use the clone form.

List every supported distro:
```bash
python isox.py --list
```

Save somewhere other than `./ISOx_Downloads`:
```bash
python isox.py arch --output-dir /example/directory
```

Download and verify a distro:
```bash
python isox.py arch
python isox.py debian
python isox.py kali
python isox.py alpine
python isox.py mint
python isox.py fedora
python isox.py opensuse
python isox.py gentoo
python isox.py void
python isox.py garuda
python isox.py ubuntu
python isox.py rocky
python isox.py alma
python isox.py cachyos
python isox.py mageia
python isox.py openmandriva
python isox.py proxmox
python isox.py ubuntu-server
python isox.py zorin
python isox.py centos-stream
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

- **Config-driven distro support** - supported distros are defined in `distros.json`, meaning adding a new distro is a JSON entry, not a code change.
- **Three ISO-discovery strategies** - covers distros that publish their ISOs in very different ways.
- **Checksums from the distro, ISO from the fastest mirror** - a mirror serving a modified ISO could serve a matching hash just as easily, so the hash is fetched from the distribution's own host.
- **Version-folder auto-discovery** - for distros with no stable "latest" alias, the current version-numbered directory is discovered by scanning a parent directory and numerically sorting version-like folder names, so outdated ISOs aren't retrieved.
- **Mirror speed checks** - samples ~2MB from each candidate mirror via a ranged request to measure real throughput, then downloads from the fastest.
- **Resumable downloads** - interrupted transfers are written to a `.part` file and continued via an HTTP `Range` request on the next run, so you don't have to restart if something goes wrong. (.part files that are stale are also checked before resuming, and are scrapped if they're out of date)
- **Live progress bar** - shows percentage and real-time throughput, and degrades to a plain byte counter if the server won't report a total size.
- **Streamed downloads** - files are downloaded in large chunks (`requests` with `stream=True`), so multi-GB ISOs don't hog RAM.
- **Failure quarantine** - an ISO that fails verification is renamed, so it can't be mistaken for a verified file.
- **Path-traversal protection** - filenames discovered from remote HTML listings are validated before ever being used in a URL or local file path.

## How it works

This section covers what you need to configure and run ISOx.

### Config format (`distros.json`)

Every distro entry needs `mirrors`, `checksum_filename`, and `hash_algo` at minimum. Everything else is optional and only needed if that distro deviates from the simplest cases such as Arch.

Fedora is shown as a more complex example on purpose. It demonstrates the options available when a distro needs version discovery, mirror scanning, or custom checksum handling. Most distributions only require the basic fields plus one or two optional ones.

If the included mirrors are not ideal for your location, you can easily update them. Just find a suitable mirror from the distro's official mirror list and replace the URL in distros.json. The tool will then handle the rest. Mirror, checksum and version-discovery URLs must be HTTPS.

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

| Key | Purpose |
|---|---|
| `mirrors` | **Required.** Where the ISO may be downloaded from. Raced on every run. |
| `checksum_filename` | **Required.** Literal name, or a `{iso_filename}.sha256` template. |
| `hash_algo` | **Required.** Anything `hashlib` supports. Validated before any download starts. |
| `checksum_base` | Host to fetch the checksum from, ideally the distro's own server. Also decides the ISO filename, so name and hash always agree. |
| `iso_filename` | For distros whose filename never changes. |
| `iso_filename_contains` | Substrings every candidate filename must contain. |
| `iso_filename_excludes` | Substrings that disqualify a filename. Use this when a distro publishes images your substrings can't tell apart, like Debian's `-edu-` and `-mac-` images. |
| `discovery_method` | `checksum_scan` (default) or `html_scan`. |
| `checksum_discovery_method` | `html_scan` when the checksum filename itself has to be scraped. |
| `checksum_format` | `multi` (default), `bsd`, or `single`. |
| `version_directory` | `true` when the current version has to be discovered first. |
| `version_discovery_url` | One URL or a list of them, tried in order. |
| `version_scheme` | `ubuntu_lts` to select only LTS releases. |

#### Where `distros.json` is loaded from

Searched in this order, first hit wins:

1. `$ISOX_DISTROS`
2. `~/.config/isox/distros.json` (`%APPDATA%\isox\distros.json` on Windows)
3. Beside `isox.py` (usually when it's git cloned)
4. `share/isox/distros.json` under the install scheme's data directory, the user base, or `sys.prefix`

**If you customize mirrors on a pip install, put your copy at (2)**, so it survives updates.

```bash
mkdir -p ~/.config/isox
isox --list                      # prints the config path currently in use
cp "$(isox --list | sed -n 's/^config: //p')" ~/.config/isox/distros.json
```

### ISO filename discovery

- **`"iso_filename"`** - for distros with one fixed, unchanging filename.
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file for a filename matching all the given substrings.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - scrapes the directory listing HTML for distros with no single shared checksum file.

### Version-folder discovery

For distros with no stable "latest" URL alias, `"version_directory": true` scrapes the
parent directory first, sorts version-like folder names numerically, and splices the newest
into every `{version}` placeholder before any discovery happens.

`version_discovery_url` takes a list as well as a single URL, tried in order.
`version_scheme: "ubuntu_lts"` narrows this to even-year `.04` folders, so
`python isox.py ubuntu` resolves to the latest LTS rather than the latest interim.

### Checksum parsing

Three published formats are normalized into the same `{filename: hash}` lookup:

- **`multi`** (default) - `<hash>  <filename>`, one per line
- **`bsd`** - `SHA256 (filename) = <hash>`
- **`single`** - the file contains only the hash

### Mirror selection

Each mirror is sampled with a ranged GET pulling the first ~2MB of the actual ISO,
and real throughput is measured over that sample. Fastest wins. Mirrors that time out or
error are skipped. The checksum is fetched separately, from `checksum_base`.

### Resumable downloads

Downloads are written to `<filename>.part` and only renamed to the final name once the
transfer completes, so a partial can't be mistaken for a finished file. On the next run
the `.part` size becomes the offset in a `Range: bytes=N-` request.

Four things can go wrong with a resume. A partial larger than the file on the server, a
partial from an older release, a different mirror winning the race, and a server that
ignores `Range` entirely. Each is handled.

### Checksum verification

The checksum file is fetched new on every run, from `checksum_base` rather than from the
mirror that served the ISO, and compared with `hmac.compare_digest`. A hash mismatch
renames the ISO to `<filename>.FAILED`; a missing entry renames it to
`<filename>.UNVERIFIED`.

## What verification does and doesn't cover

**Covered.** Corruption in transit, truncated transfers, a bad disk, a botched resume, and
a mirror serving a modified ISO. That last one is why the checksum is fetched from
`checksum_base` (own host) rather than from the mirror that served
the bytes. A mirror that can hand you a tampered ISO can hand you a hash matching it just
as easily. Splitting the two means one rogue mirror can't supply both halves.

GPG is not included as it would require maintaining trusted public keys (or fingerprints)
for every supported distribution, along with key management and signature validation
logic. That complexity conflicts with ISOx's goal of being a lightweight, easy to use, and
config-driven Linux tool.

## Requirements

- Python 3.10+
- `requests`
- `beautifulsoup4` - used for HTML directory-listing discovery

Everything else (`hashlib`, `hmac`, `json`, `argparse`, `os`, `sys`, `time`, `re`, `site`, `sysconfig`) is part of the Python standard library.

## Development

    pip install -e '.[dev]'
    pytest
    black --check .
    ruff check .
    bandit isox.py

The suite is simulated (no network), except `tests/test_live_mirrors.py`, as it resolves
every distro in `distros.json` against the real mirrors
and checks if the filename it lands on has a checksum, without downloading
any ISO. It's deselected by default and takes about a minute:

    pytest -m live       # all distros
    pytest -m live -s    # printing each resolved filename and hash
    pytest -m live -k rocky

## Contributing

Distro requests and additions are welcome. Most new distros are a
`distros.json` entry with no Python at all. See
[CONTRIBUTING.md](https://github.com/logjxn/ISOx/blob/main/.github/CONTRIBUTING.md).

## License

MIT License: see [LICENSE](https://github.com/logjxn/ISOx/blob/main/LICENSE) for details. Feel free to use, modify, or build on this.
