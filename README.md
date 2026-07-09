# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source-published checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot. Arch, Debian, and various others across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. That can be an integrity risk (corrupted downloads, tampered mirrors, interrupted transfers), so I built a tool that automates the whole pipeline and makes verification the default, not an extra step.

## Features

- **Config-driven distro support** - supported distros (mirrors, checksum filename, hash algorithm) are defined in `distros.json`, not hardcoded in the script, meaning adding a new distro is a data change, not a code change.
- **Mirror speed checks** - Uses download sampling (2MB) to run a quick check on the fastest mirror throughput, then downloads from that.
- **Streamed downloads** - files are downloaded in 8KB chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't blow up RAM usage.
- **Checksum verification** - after downloading, the tool recomputes the file's hash (chunked, via `hashlib`) and compares it against the official hash published by the distro, using whichever algorithm that distro publishes (SHA256, SHA512, etc.).
- **Algorithm-agnostic hashing** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports, driven entirely by the JSON config.

## Usage

```bash
pip install requests
python isox.py arch
python isox.py debian
```

Downloaded ISOs are saved to the created folder `ISOx_Downloads/`. Output looks like:

```
https://fastly.mirror.pkgbuild.com/iso/latest/sha256sums.txt responded in 1.082s
https://geo.mirror.pkgbuild.com/iso/latest/sha256sums.txt responded in 1.428s
https://ftpmirror.infania.net/mirror/archlinux/iso/latest/sha256sums.txt responded in 2.000s
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Checksum matches, file is good.
```

## How it works

### Config format (`distros.json`)

```json
{
    "arch": {
        "mirrors": [
            "https://fastly.mirror.pkgbuild.com/iso/latest/",
            "https://geo.mirror.pkgbuild.com/iso/latest/",
            "https://ftpmirror.infania.net/mirror/archlinux/iso/latest/"
        ],
        "checksum_filename": "sha256sums.txt",
        "hash_algo": "sha256"
    },
    "debian": {
        "mirrors": ["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"],
        "checksum_filename": "SHA256SUMS",
        "hash_algo": "sha256"
    }
}
```

Each mirror URL points at a "latest"-style path that the distro maintainers keep pointing at the current release, rather than a dated/versioned path that will eventually 404:

- **Arch** exposes an `iso/latest/` alias alongside its dated release folders (e.g. `iso/2026.07.01/`), which always mirrors the current release.
- **Debian** exposes a permanent `debian-cd/current/` path that always serves the current stable release, regardless of version number.

This means the config doesn't need to be updated every time a distro ships a new release.

### Mirror selection

Each candidate mirror is sampled with a ranged GET request, that pulls the first ~2MB of the actual ISO via an HTTP Range: bytes=0-1999999 header, and the real transfer speed (bytes/second) is measured over that sample. The mirror with the highest sampled throughput is selected for both the checksum file and the full ISO download.

Mirrors that time out or return an error status are caught (requests.exceptions.RequestException) and skipped rather than crashing the whole run.

v1 → v1.1 change: the original version selected mirrors using HEAD request response time (pure latency) rather than throughput. After some testing, it proved that a mirror that answered the HEAD request fastest wasn't always the fastest download option. The mirror selection logic was rebuilt to sample real throughput directly rather than inferring it from response latency.

### Checksum verification

The distro's checksum file (a flat text file with `<hash>  <filename>` per line, the standard output format of tools like `sha256sum`) is fetched fresh on every run and parsed into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed in 8KB chunks via `hashlib`, and the result is compared against the expected hash with a simple string equality check.

**This was tested, not just assumed to work:** I created a separate script to deliberately append garbage bytes to a previously-verified ISO, then ran the same `verify_checksum()` function used in the main program against it. It correctly returns `False`, confirming the verification logic detects tampering/corruption rather than always reporting success.
*See below for the script I used to test corruption. Feel free to try yourself.*
```python
from isox import compute_hash, verify_checksum
import requests

response = requests.get("https://fastly.mirror.pkgbuild.com/iso/2026.07.01/sha256sums.txt")
hash_lookup = {}
for line in response.text.splitlines():
    parts = line.split()
    if len(parts) == 2:
        hash_lookup[parts[1]] = parts[0]

result = verify_checksum("ISOx_Downloads/archlinux-x86_64.iso", "archlinux-x86_64.iso", hash_lookup, "sha256")
print("Verified:", result)  # should print False now, after corruption
```

## NOTE
This tool does not perform signature checking. Some distros, such as Debian, use GPG signatures to verify that files genuinely originated from them. This tool does NOT check for those. If you add additional distros to the configuration, please make sure you're using trusted, official mirrors. All mirrors currently built in come from Arch Linux's official worldwide mirrorlist, and Debian's are sourced directly from debian.org.

## Requirements

- Python 3.x
- `requests` (`pip install requests`)

Everything else (`hashlib`, `json`, `argparse`, `os`, `time`) is part of the Python standard library.
