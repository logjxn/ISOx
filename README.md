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

**A Normal Run**
```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.33 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 1.98 MB/s
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso sampled at 0.08 MB/s
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
[##############################] 100.0%    3.41 MB/s
Checksum matches, file is good.
```
**Resumed Output**
```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.28 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 2.04 MB/s
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso is unreachable
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Resuming from 743.6 MB ...
[##############################] 100.0%    3.26 MB/s
Checksum matches, file is good.
```

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

Four locations for the install case rather than one because a wheel's data files land
wherever the *install scheme* puts them, and that varies by how pip was invoked. venv and
pipx have `sys.prefix` and the data path coincide; `pip install --user` puts it under the
user base; Debian's patched system Python defaults to `/usr/local` while `sys.prefix` stays
`/usr`. Duplicates collapse, so a normal install shows one path, not three.

**If you customise mirrors on a pip install, put your copy at (2).** `pip install -U isox`
replaces what it installed, so edits made directly to (4) revert on upgrade without
warning. A copy in your config directory survives.

```bash
mkdir -p ~/.config/isox
isox --list                      # prints the config path currently in use
cp "$(isox --list | sed -n 's/^config: //p')" ~/.config/isox/distros.json
```

`isox --list` prints which file won, which is the quickest way to answer "why is it
using the wrong mirrors".

### ISO filename discovery, three strategies

Not every distro publishes ISOs the same way, so the tool picks a strategy per distro based on which config fields are present. No per-distro code exists anywhere in the script.

- **`"iso_filename"`** - for distros with one fixed, unchanging filename.
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file for a filename matching all the given substrings, since versioned filenames would be inefficient to hardcode.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - for distros with no single shared checksum file to scan. Scrapes the actual directory listing HTML with BeautifulSoup and filters `<a href>` links ending in `.iso` that match all the necessary substrings.

Both scanning strategies filter out pre-release artifacts by default. This matters more
than it sounds: Alpine publishes `alpine-extended-3.24.2_rc1-x86_64.iso` into the same
directory as the final release, and because `_` sorts above `-`, a plain "newest wins"
comparison hands you the release candidate. An RC has a perfectly valid published
checksum, so it would download and verify without complaint.

The two strategies also differ in how they break ties, deliberately. A directory listing
legitimately holds several versions, so the newest wins. A checksum file describes one
release, so several matches means the config is ambiguous rather than that there is a
choice to make - the run stops and names the candidates:

```
Error: 'debian' matched 3 ISOs in the checksum file at
https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA256SUMS:
debian-13.6.0-amd64-netinst.iso, debian-edu-13.6.0-amd64-netinst.iso,
debian-mac-13.6.0-amd64-netinst.iso. Narrow iso_filename_contains or add
iso_filename_excludes in distros.json.
```

Only `.iso` files are considered. Checksum files cover every artifact of a release, and
Kali's `SHA256SUMS` pairs each ISO with a `.iso.torrent` that matches exactly the same
substrings - without the extension filter, a 100KB torrent could be downloaded, verified
against its own hash, and reported as a good ISO.

**Version-folder auto-discovery** (`"version_directory": true`) is a separate, earlier step for distros with no stable "latest" URL alias at all. Before any ISO discovery happens, the parent directory is scraped, version-numbered folder names are parsed and sorted *numerically*, and the newest one is spliced into every `{version}` placeholder across the mirror URLs.

`version_discovery_url` takes a list as well as a single URL, and they are tried in order.
This step decides which directory everything else is fetched from, so a single unreachable
host here would otherwise fail the whole run even when every configured mirror is healthy.

For Ubuntu, `version_scheme` is optional and only applies alongside version_directory. Left out, the newest version-numbered folder is selected. Set to "ubuntu_lts", only even-year .04 folders match, so `python isox.py ubuntu` resolves to the latest LTS. Interim releases are skipped intentionally, since LTS is the better default for a daily driver.

### Checksum parsing

- **`"multi"` (default)** - the standard `<hash>  <filename>` format used by `sha256sum`'s own output.
- **`"single"`** - the whole file content is treated as the hash, with the filename supplied from context rather than parsed. Available for distros that publish a genuinely bare hash.
- **`"bsd"`** - parses lines shaped like `SHA256 (filename) = hash`, used by some distros. Only lines starting with the configured `hash_algo` are read, so a file listing multiple algorithms for the same filename can't have the wrong one picked.

### Mirror selection

Each candidate mirror is sampled with a ranged GET request, pulling the first ~2MB of the actual ISO via an HTTP `Range` header, and the real transfer speed (bytes/second) is measured over that sample. The mirror with the highest sampled throughput is selected for the ISO download. The checksum is fetched separately, from `checksum_base`.

Mirrors that time out or return an error status are caught (`requests.exceptions.RequestException`) and skipped rather than crashing the whole run.

**All Mirrors Down**
```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso is unreachable
Error: none of the mirrors for this distro are reachable right now. Try again soon, or swap the mirrors in distros.json.
```


### Resumable downloads

Downloads are written to `<filename>.part` and only renamed to the final name once the transfer completes, so a partial file can never be mistaken for a finished one. On the next run, if a `.part` exists, its size becomes the offset in a `Range: bytes=N-` request and the transfer continues from there.

Four things can go wrong with a resume, and each is handled:

- **The `.part` is larger than the file on the server.** The server answers `416 Range Not Satisfiable`, which means the partial is stale: it's deleted and the download restarts.
- **The `.part` belongs to an older release.** Rolling distros like Arch reuse the same filename (`archlinux-x86_64.iso`) for a new image every month, so a partial from June would happily append onto July's file and produce a corrupt iso. ISOx stores the mirror's `ETag`/`Last-Modified` alongside the `.part` and discards the partial if it no longer matches. If the server publishes neither header, the partial is discarded after 24 hours instead.
- **A different mirror wins the race this time.** `ETag`s are per-server - nginx derives them from mtime and size, which differ between mirrors holding identical bytes - so a fingerprint from one mirror says nothing about another. The URL is recorded alongside the fingerprint and they're only compared when they came from the same place, otherwise the 24-hour age check applies. Without this, changing mirrors between runs looks exactly like the file changing, and a 90%-complete download gets thrown away.
- **The server ignores the `Range` header** and sends the whole file with a `200`. The offset is reset and the file is rewritten from scratch rather than appended to.

A transfer that ends short of the advertised `Content-Length` keeps its `.part` and exits
non-zero rather than being promoted. A short read is the exact case resuming exists for,
so turning it into a `.FAILED` ISO would throw away work that was still good.

**Stale Partial Downloads**
```
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Partial download doesn't match file on server. Starting fresh.
[##############################] 100.0%    3.39 MB/s
Checksum matches, file is good.
```

Checksum verification remains the final stop: a bad merge that somehow slipped through would fail verification and be quarantined.

### Checksum verification

The distro's checksum file is fetched new on every run, from `checksum_base` rather than from the mirror that served the ISO, and parsed into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed via `hashlib` and compared against the expected hash with `hmac.compare_digest`, case-insensitively - `hexdigest()` is always lowercase and not every distro publishes it that way, and a case difference would otherwise be reported as tampering.

If the hashes don't match, the ISO is renamed to `<filename>.FAILED`. If no checksum entry could be found for the file at all, it's renamed to `<filename>.UNVERIFIED`. In both cases the process exits non-zero.

**Verification Failure**
```
[##############################] 100.0%    3.12 MB/s
WARNING: checksum mismatch, file may be corrupted or tampered with!
Renamed to ISOx_Downloads/archlinux-x86_64.iso.FAILED so it can't be mistaken for a verified ISO.
```

**This was tested:** I created a separate script to append garbage bytes to a previously-verified ISO, then ran the same `verify_checksum()` function used in the main program against it. It correctly returns `False`, confirming the verification logic detects tampering/corruption rather than always reporting success.
*The script I used to test corruption is below. Feel free to try for yourself.*
```python
from isox import verify_checksum
import requests

response = requests.get("https://fastly.mirror.pkgbuild.com/iso/latest/sha256sums.txt")
hash_lookup = {}
for line in response.text.splitlines():
    parts = line.split()
    if len(parts) == 2:
        hash_lookup[parts[1]] = parts[0]

result = verify_checksum("ISOx_Downloads/archlinux-x86_64.iso", "archlinux-x86_64.iso", hash_lookup, "sha256")
print("Verified:", result)  # should print False now, after corruption
```

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

Run it straight from a clone:

    pip install .
    isox arch

Or install from PyPI:

    pip install isox
    isox arch

## Development

    pip install -e '.[dev]'
    pytest
    black --check .
    ruff check .
    bandit isox.py

The suite is hermetic and stubs the network. `tests/test_live_mirrors.py` is the
one exception: it resolves every distro in `distros.json` against the real mirrors
and checks the filename it lands on has a published checksum, without downloading
any ISO. It's deselected by default and takes about 30 seconds:

    pytest -m live       # all distros
    pytest -m live -s    # printing each resolved filename and hash
    pytest -m live -k rocky

## Contributing

Distro requests and additions are welcome - most new distros are a
`distros.json` entry with no Python at all. See
[CONTRIBUTING.md](https://github.com/logjxn/ISOx/blob/main/.github/CONTRIBUTING.md).

## License

MIT License: see [LICENSE](https://github.com/logjxn/ISOx/blob/main/LICENSE) for details. Feel free to use, modify, or build on this.
