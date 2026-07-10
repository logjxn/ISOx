# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot. Arch, Debian, Kali, and various others across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. That can be an integrity risk (corrupted downloads, tampered mirrors, interrupted transfers), so I built a tool that automates the whole pipeline and makes verification the default, not an extra step.

## Features

- **Config-driven distro support** - supported distros (mirrors, checksum filename, hash algorithm, and how to locate the ISO filename) are defined in `distros.json`, not hardcoded in the script, meaning adding a new distro are added via the DISTROS.json rather than coding.
- **Mirror speed checks** - Uses download sampling (2MB) to run a quick check on the fastest mirror throughput, then downloads from that.
- **Streamed downloads** - files are downloaded in 8KB chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't blow up RAM usage.
- **Checksum verification** - after downloading, the tool recomputes the file's hash (chunked, via `hashlib`) and compares it against the official hash published by the distro, using whichever algorithm that distro publishes (SHA256, SHA512, etc.).
- **Algorithm-agnostic hashing** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports.

## Usage

```bash
pip install requests
python isox.py arch
python isox.py debian
python isox.py kali
```

Downloaded ISOs are saved to the created folder `ISOx_Downloads/`. Output looks like:

```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.33 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 1.98 MB/s
https://ftpmirror.infania.net/mirror/archlinux/iso/latest/archlinux-x86_64.iso sampled at 0.08 MB/s
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
        "hash_algo": "sha256",
        "iso_filename": "archlinux-x86_64.iso"
    },
    "debian": {
        "mirrors": ["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"],
        "checksum_filename": "SHA256SUMS",
        "hash_algo": "sha256",
        "iso_filename_contains": ["netinst", "amd64"]
    },
    "kali": {
        "mirrors": [
            "https://archive-4.kali.org/kali-images/current/",
            "https://kali.download/base-images/current/",
            "https://mirrors.dotsrc.org/kali-images/current/"
        ],
        "checksum_filename": "SHA256SUMS",
        "hash_algo": "sha256",
        "iso_filename_contains": ["installer-amd64"]
    }
}
```

Each mirror URL points at a "latest"-style path that the distro maintainers keep pointing at the current release, rather than a dated/versioned path that will eventually 404:

- **Arch** exposes an `iso/latest/` alias alongside its dated release folders (e.g. `iso/2026.07.01/`), which always mirrors the current release.
- **Debian** exposes a permanent `debian-cd/current/` path that always serves the current stable release, regardless of version number.
- **Kali** exposes a `current/` path per mirror that always resolves to the current release.

This means the config doesn't need to be updated every time a distro ships a new release.

**Two ways a distro's ISO filename can be located, both driven entirely by config:**

- `"iso_filename"` — for distros with one fixed, unchanging filename (Arch never changes `archlinux-x86_64.iso`).
- `"iso_filename_contains"` — a list of substrings used to discover the correct versioned filename by scanning the checksum file (Debian and Kali both bake a version number into their filenames, so the exact name has to be discovered rather than hardcoded).

`main()` picks whichever strategy a distro's config specifies, and there's no per-distro code anywhere in the script. Adding Kali required zero changes to `isox.py` and was purely a `distros.json` addition. `argparse`'s valid distro choices are also derived directly from `distros.json`'s keys, so a new distro automatically becomes a valid CLI argument too, with no separate list to keep in sync.

**Honest scope of "no code change needed":** this holds for any distro that publishes a flat `<hash>  <filename>` checksum file with either a stable filename or a discoverable one. A distro that instead requires scraping an HTML directory listing, or structures its checksum data differently, could need new code. 

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

response = requests.get("https://fastly.mirror.pkgbuild.com/iso/latest/sha256sums.txt")
hash_lookup = {}
for line in response.text.splitlines():
    parts = line.split()
    if len(parts) == 2:
        hash_lookup[parts[1]] = parts[0]

result = verify_checksum("ISOx_Downloads/archlinux-x86_64.iso", "archlinux-x86_64.iso", hash_lookup, "sha256")
print("Verified:", result)  # should print False now, after corruption
```

## NOTE
This tool does not perform signature checking. Some distros, such as Debian and Kali, use GPG signatures to verify that files genuinely originated from them. ISOx does NOT check for those. If you add additional distros to the configuration, please make sure you're using trusted, official mirrors. All mirrors currently built in come from Arch Linux's official worldwide mirrorlist, Debian's are sourced directly from debian.org, and Kali's are sourced from the official Kali mirror network (cdimage.kali.org and its listed mirrors).

## Requirements

- Python 3.x
- `requests` (`pip install requests`)

Everything else (`hashlib`, `json`, `argparse`, `os`, `time`) is part of the Python standard library.
