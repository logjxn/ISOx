# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification the default, and not an extra step.

## Features

- **Config-driven distro support** - supported distros (mirrors, checksum filename, hash algorithm, and how to locate the ISO filename) are defined in `DISTROS.json`, not hardcoded, meaning adding a new distro is via the DISTROS.json rather than changing the main code.
- **Mirror speed checks** - Uses download sampling (2MB) to run a quick check on mirror throughput, then chooses the fastest.
- **Streamed downloads** - files are downloaded in 8KB chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't hog up RAM.
- **Checksum verification** - after downloading, the tool recomputes the file's hash (via `hashlib`) and compares it against the official hash published by the distro, using whichever algorithm that distro publishes (SHA256, SHA512, etc.).
- **Multi-algorithm support** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports.

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

### Config format (`DISTROS.json`)

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

- For example, **Arch** exposes an `iso/latest/` alias alongside its dated release folders (like `iso/2026.07.01/`), which always mirrors the current release.
- **Debian** exposes a permanent `debian-cd/current/` path that always serves the current stable release, regardless of version number.

This means the config doesn't need to be updated every time a distro has a new release.

**How are various ISO names set in DISTROS.json?**

- `"iso_filename"` - for distros with one fixed, unchanging filename (Arch never changes `archlinux-x86_64.iso`).
- `"iso_filename_contains"` - a list of substrings used to discover the correct versioned filename by scanning the checksum file (Debian, Kali, and many other distros have a version number into their filenames, so the exact name has to be pieced together).

`main()` picks whichever strategy a distro's config specifies, and there's no per-distro code anywhere in the script. `argparse`'s valid distro choices are also derived directly from `DISTROS.json`'s keys, so a new distro automatically becomes a valid CLI argument too.

**"no code change needed":** this holds for any distro that publishes a flat `<hash>  <filename>` checksum file with either a stable filename or a discoverable one. A distro that instead requires scraping an HTML directory listing, or structures its checksum data differently, could potentially need new code in isox.py.

### Mirror selection

Each candidate mirror is sampled with a ranged GET request, that pulls the first ~2MB of the actual ISO via an HTTP Range header, and the real transfer speed (bytes/second) is measured over that sample. The mirror with the highest sampled throughput is selected for both the checksum file and the full ISO download.

Mirrors that time out or return an error status are caught (requests.exceptions.RequestException) and skipped rather than crashing the whole run.

v1 → v1.1 change: the original version selected mirrors using HEAD request response time (pure latency) rather than throughput. After some testing, it proved that a mirror that answered the HEAD request fastest wasn't always the fastest download option. The mirror selection logic was rebuilt to sample real throughput directly rather than inferring it from response latency.

### Checksum verification

The distro's checksum file is fetched on every run and parsed into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed in 8KB chunks via `hashlib`, and the result is compared against the expected hash with a string equality check.

**This was tested, not just assumed to work:** I created a separate script to deliberately append garbage bytes to a previously-verified ISO, then ran the same `verify_checksum()` function used in the main program against it. It correctly returns `False`, confirming the verification logic detects tampering/corruption rather than always confirming it's unmodified.
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

## License
MIT License — see [LICENSE](LICENSE) for details. Feel free to use, modify, or build on this.
