# ISOx

![Python](https://img.shields.io/badge/python-3.10+-blue)
[![PyPI](https://img.shields.io/pypi/v/isox)](https://pypi.org/project/isox/)
![License](https://img.shields.io/github/license/logjxn/ISOx)
![Release](https://img.shields.io/github/v/release/logjxn/ISOx)
![OS](https://img.shields.io/badge/platform-Linux-orange)
![CI](https://github.com/logjxn/ISOx/actions/workflows/ci.yml/badge.svg)

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against the checksum published by the distribution itself, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
                                          (fastest mirror)  (distro's own host)
```

The ISO comes from whichever mirror is fastest right now. The checksum comes from the
distribution's own server, so the mirror that hands you the bytes is not also the one
vouching for them. See [What verification does and doesn't cover](#what-verification-does-and-doesnt-cover).

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification the default, and not an extra step.

Furthermore, I simply love Linux. It's been my daily driver ever since I discovered it, and I want to see it continue to grow. I hope this tool makes getting started with Linux a little faster, easier, and safer for anyone who wants to use it.

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
python isox.py arch --output-dir /mnt/usb
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

Resumed runs, unreachable mirrors, and verification failures are shown in
[the design doc](https://github.com/logjxn/ISOx/blob/main/docs/design.md).

## Features

- **Config-driven distro support** - supported distros are defined in `distros.json`, not hardcoded, meaning adding a new distro is a JSON entry, not a code change.
- **Three ISO-discovery strategies** - covers distros that publish their ISOs in very different ways.
- **Checksums from the distro, ISO from the fastest mirror** - a mirror serving a modified ISO could serve a matching hash just as easily, so the hash is fetched from the distribution's own host rather than from whichever mirror won the speed race.
- **Version-folder auto-discovery** - for distros with no stable "latest" alias, the current version-numbered directory is discovered automatically by scanning a parent directory and numerically sorting version-like folder names, so outdated ISOs aren't retrieved.
- **Pre-release filtering** - distros publish release candidates into the same directory as final releases, and `_rc2` sorts *above* the release it precedes. Those are filtered out so `isox alpine` means the release, not the candidate.
- **No silent guessing** - if a distro's config matches more than one ISO in a checksum file, the run stops and names the candidates instead of picking one. A wrong image would still verify cleanly against its own published hash, so guessing is the one thing worse than failing.
- **Mirror speed checks** - samples ~2MB from each candidate mirror via a ranged request to measure real throughput, then downloads from the fastest.
- **Resumable downloads** - interrupted transfers are written to a `.part` file and continued via an HTTP `Range` request on the next run, so a drop at 90% doesn't cost you the 90% you already downloaded, even if a different mirror wins the race next time.
- **Stale-partial detection** - a `.part` left over from a *previous release* of a rolling distro is detected and discarded rather than merged into the new one.
- **Live progress bar** - shows percentage and real-time throughput, and degrades to a plain byte counter if the server won't report a total size.
- **Streamed downloads** - files are downloaded in large chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't hog RAM.
- **Checksum verification across three real-world formats** - the standard `<hash>  <filename>` format, a single-hash-per-file format, and a BSD-style format are all normalized into the same lookup and compared with `hashlib`.
- **Multi-algorithm support** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports.
- **Failure quarantine** - an ISO that fails verification is renamed rather than left in place, so it can't be mistaken for a verified file.
- **Single-point error handling** - every failure path exits with a one-line explanation and a non-zero status code, not a traceback.
- **Path-traversal protection** - filenames discovered from remote HTML listings are validated before ever being used in a URL or local file path.

## How it works

This section covers what you need to configure and run ISOx. For how each piece is
implemented and why it works the way it does, see
[docs/design.md](https://github.com/logjxn/ISOx/blob/main/docs/design.md).

### Config format (`distros.json`)

Every distro entry needs `mirrors`, `checksum_filename`, and `hash_algo` at minimum. Everything else is optional and only needed if that distro deviates from the simplest cases such as Arch.

Fedora is shown as a more complex example on purpose. It demonstrates the additional options available when a distro needs version discovery, mirror scanning, or custom checksum handling. Most distributions only require the basic fields plus one or two optional ones.

If the included mirrors are not ideal for your location, you can easily update them. Just find a suitable mirror from the distro's official mirror list and replace the URL in distros.json. The tool will then handle the rest. Mirror, checksum and version-discovery URLs must be HTTPS. ISOx refuses a config with a plain-HTTP URL, but most distros have moved to HTTPS-only mirrors already, so this shouldn't narrow your options much.

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
| `checksum_base` | Host to fetch the checksum from, instead of the winning mirror. Should be the distro's own server. Also decides the ISO filename, so name and hash always agree. |
| `iso_filename` | For distros whose filename never changes. |
| `iso_filename_contains` | Substrings every candidate filename must contain. |
| `iso_filename_excludes` | Substrings that disqualify a filename, on top of the built-in pre-release filter. Use this when a distro publishes variants your substrings can't tell apart, like Debian's `-edu-` and `-mac-` images. |
| `discovery_method` | `checksum_scan` (default) or `html_scan`. |
| `checksum_discovery_method` | `html_scan` when the checksum filename itself has to be scraped. |
| `checksum_format` | `multi` (default), `bsd`, or `single`. |
| `version_directory` | `true` when the current version has to be discovered first. |
| `version_discovery_url` | One URL or a list of them, tried in order. |
| `version_scheme` | `ubuntu_lts` to select only LTS releases. |

#### Where `distros.json` is loaded from

Searched in this order, first hit wins:

1. `$ISOX_DISTROS`, if set - this short-circuits the rest, so a typo is reported rather than silently falling back
2. `~/.config/isox/distros.json` (`%APPDATA%\isox\distros.json` on Windows)
3. Beside `isox.py` - the git clone case
4. `share/isox/distros.json` under the install scheme's data directory, the user base, or `sys.prefix`

**If you customise mirrors on a pip install, put your copy at (2).** `pip install -U isox`
replaces what it installed, so edits made directly to (4) revert on upgrade without
warning. A copy in your config directory survives.

```bash
mkdir -p ~/.config/isox
isox --list                      # prints the config path currently in use
cp "$(isox --list | sed -n 's/^config: //p')" ~/.config/isox/distros.json
```

`isox --list` prints which file won, which is the quickest way to answer "why is it
using the wrong mirrors". Why (4) is three locations rather than one is covered in
[Config resolution](https://github.com/logjxn/ISOx/blob/main/docs/design.md#config-resolution).

### ISO filename discovery

Not every distro publishes ISOs the same way, so the tool picks a strategy per distro based on which config fields are present. No per-distro code exists anywhere in the script.

- **`"iso_filename"`** - for distros with one fixed, unchanging filename.
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file for a filename matching all the given substrings.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - scrapes the directory listing HTML for distros with no single shared checksum file.

Both scanning strategies filter out pre-release artifacts, and only `.iso` files are
considered. The two break ties differently on purpose: a directory listing legitimately
holds several versions, so the newest wins, while several matches inside one checksum file
means the config is ambiguous and the run stops.
[Full explanation, with the Alpine and Debian cases that motivate both](https://github.com/logjxn/ISOx/blob/main/docs/design.md#iso-filename-discovery).

### Version-folder discovery

For distros with no stable "latest" URL alias, `"version_directory": true` scrapes the
parent directory first, sorts version-like folder names numerically, and splices the newest
into every `{version}` placeholder before any ISO discovery happens.
`version_discovery_url` takes a list as well as a single URL, tried in order.

`version_scheme: "ubuntu_lts"` narrows this to even-year `.04` folders, so
`python isox.py ubuntu` resolves to the latest LTS rather than the latest interim.
[More on the sorting and the LTS case](https://github.com/logjxn/ISOx/blob/main/docs/design.md#version-folder-discovery).

### Checksum parsing

Three published formats are normalized into the same `{filename: hash}` lookup:

- **`multi`** (default) - `<hash>  <filename>`, one per line
- **`bsd`** - `SHA256 (filename) = <hash>`
- **`single`** - the file contains only the hash

[Parsing details, including how `bsd` picks the right algorithm](https://github.com/logjxn/ISOx/blob/main/docs/design.md#checksum-parsing).

### Mirror selection

Each candidate mirror is sampled with a ranged GET pulling the first ~2MB of the actual ISO,
and real throughput is measured over that sample. Fastest wins. Mirrors that time out or
error are skipped rather than crashing the run. The checksum is fetched separately, from
`checksum_base`.
[Sampling mechanics and the all-mirrors-down output](https://github.com/logjxn/ISOx/blob/main/docs/design.md#mirror-selection).

### Resumable downloads

Downloads are written to `<filename>.part` and only renamed to the final name once the
transfer completes, so a partial can never be mistaken for a finished file. On the next run
the `.part` size becomes the offset in a `Range: bytes=N-` request.

Four things can go wrong with a resume - a partial larger than the file on the server, a
partial from an older release, a different mirror winning the race, and a server that
ignores `Range` entirely - and each is handled.
[How each one is detected](https://github.com/logjxn/ISOx/blob/main/docs/design.md#resumable-downloads).

### Checksum verification

The checksum file is fetched new on every run, from `checksum_base` rather than from the
mirror that served the ISO, and compared with `hmac.compare_digest`. A hash mismatch
renames the ISO to `<filename>.FAILED`; a missing entry renames it to
`<filename>.UNVERIFIED`. Both exit non-zero.
[Verification details, and the corruption test I ran against it](https://github.com/logjxn/ISOx/blob/main/docs/design.md#checksum-verification).

## What verification does and doesn't cover

**Covered.** Corruption in transit, truncated transfers, a bad disk, a botched resume, and
a mirror serving a modified ISO. That last one is why the checksum is fetched from
`checksum_base` - the distribution's own host - rather than from the mirror that served
the bytes. A mirror that can hand you a tampered ISO can hand you a hash matching it just
as easily, so verifying a mirror's file against that same mirror's hash is close to
verifying nothing. Splitting the two means one rogue mirror can't supply both halves.

**Not covered.** ISOx does not perform GPG signature verification, so it cannot prove the
checksum itself is authentic. If the distribution's own host is compromised, or someone
holds a certificate for it, a matching ISO and hash could be served together and ISOx
would report success.

GPG is not included as it would require maintaining trusted public keys (or fingerprints)
for every supported distribution, along with key management and signature validation
logic. That complexity conflicts with ISOx's goal of being a lightweight, easy to use, and
config-driven Linux tool.

Worth knowing: several distros already publish signed checksums that ISOx fetches and
parses while ignoring the signature - Gentoo's `.sha256` is PGP-clearsigned, and Rocky
ships a `CHECKSUM.asc` beside its `CHECKSUM`. If your threat model requires verifying the
origin of a release, those signatures are right there, and the distribution's
documentation covers its public signing keys and the verification steps.

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

The suite is hermetic and stubs the network. `tests/test_live_mirrors.py` is the
one exception: it resolves every distro in `distros.json` against the real mirrors
and checks the filename it lands on has a published checksum, without downloading
any ISO. It's deselected by default and takes about a minute:

    pytest -m live       # all distros
    pytest -m live -s    # printing each resolved filename and hash
    pytest -m live -k rocky

## Contributing

Distro requests and additions are welcome - most new distros are a
`distros.json` entry with no Python at all. See
[CONTRIBUTING.md](https://github.com/logjxn/ISOx/blob/main/.github/CONTRIBUTING.md).

## License

MIT License: see [LICENSE](https://github.com/logjxn/ISOx/blob/main/LICENSE) for details. Feel free to use, modify, or build on this.