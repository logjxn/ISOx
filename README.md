# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification the default, and not an extra step.

## Features

- **Config-driven distro support** - supported distros (mirrors, checksum details, and how to locate the ISO filename) are defined in `distros.json`, not hardcoded, meaning adding a new distro is a json entry, not a code change.
- **Three ISO-discovery strategies** - a static filename, a substring scanned out of a shared checksum file, or a substring match scraped from an HTML directory listing, covering distros that publish their ISOs in very different ways.
- **Version-folder auto-discovery** - for distros with no stable "latest" URL alias, the current version-numbered directory is discovered automatically by scanning a parent directory and numerically sorting version-like folder names, instead of hardcoding a version that goes stale on the next release.
- **Mirror speed checks** - samples ~2MB from each candidate mirror via a ranged request to measure real throughput, then downloads from the fastest.
- **Streamed downloads**-— files are downloaded in large chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't hog RAM.
- **Checksum verification across three real-world formats** - the standard `<hash>  <filename>` format, a single-hash-per-file format, and a GPG-signed BSD-style format (`SHA256 (filename) = hash`) are all normalized into the same lookup and compared with `hashlib`.
- **Multi-algorithm support** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports.
- **Path-traversal protection** - filenames discovered from remote HTML listings are validated before ever being used in a URL or local file path.

## Usage

```bash
python isox.py arch
python isox.py debian
python isox.py kali
python isox.py alpine
python isox.py mint
python isox.py fedora
python isox.py opensuse
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

Every distro entry needs `mirrors`, `checksum_filename`, and `hash_algo` at minimum. Everything else is optional and only needed if that distro deviates from the simplest case (Arch: one fixed filename, one fixed checksum filename, one checksum format).

```json
{
    "arch": {
        "mirrors": ["https://fastly.mirror.pkgbuild.com/iso/latest/"],
        "checksum_filename": "sha256sums.txt",
        "hash_algo": "sha256",
        "iso_filename": "archlinux-x86_64.iso"
    },
    "debian": {
        "mirrors": ["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"],
        "checksum_filename": "SHA256SUMS",
        "hash_algo": "sha256",
        "iso_filename_contains": ["netinst", "amd64"]
    }
}
```

### ISO filename discovery, three strategies

Not every distro publishes ISOs the same way, so `main()` picks a strategy per distro based on which config fields are present. No per-distro code exists anywhere in the script.

- **`"iso_filename"`** - for distros with one fixed, unchanging filename (Arch never changes `archlinux-x86_64.iso`).
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file (like Debian's `SHA256SUMS`) for a filename matching all the given substrings, since versioned filenames would be inefficient to hardcode.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - for distros with no single shared checksum file to scan (Alpine ships one checksum file *per* ISO; Mint and Fedora need the ISO filename discovered before a checksum filename can even be built). Scrapes the actual directory listing HTML with BeautifulSoup and filters `<a href>` links ending in `.iso` that match all the given substrings.

**Version-folder auto-discovery** (`"version_directory": true`) is a separate, earlier step for distros with no stable "latest" URL alias at all. Before any ISO discovery happens, the parent directory is scraped, version-numbered folder names are parsed and sorted *numerically*, and the newest one is spliced into every `{version}` placeholder across the mirror URLs. 

### Checksum parsing

- **`"multi"` (default)** - the standard `<hash>  <filename>` format used by `sha256sum`'s own output. Also handles a leading `*` before the filename, a binary-mode marker some tools include.
- **`"single"`** - the whole file content is treated as the hash, with the filename supplied from context rather than parsed. Available for distros that publish a genuinely bare hash.
- **`"bsd"`** - parses lines shaped like `SHA256 (filename) = hash`, used by Fedora's GPG-signed CHECKSUM files. Only lines starting with the configured `hash_algo` are read, so a file listing multiple algorithms for the same filename can't have the wrong one silently picked.

### Mirror selection

Each candidate mirror is sampled with a ranged GET request, pulling the first ~2MB of the actual ISO via an HTTP `Range` header, and the real transfer speed (bytes/second) is measured over that sample. The mirror with the highest sampled throughput is selected for both the checksum file and the full ISO download.

Mirrors that time out or return an error status are caught (`requests.exceptions.RequestException`) and skipped rather than crashing the whole run.

**v1 → v1.1 change:** the original version selected mirrors using HEAD request response time (pure latency) rather than throughput. Testing showed the fastest-responding mirror wasn't always the fastest actual download, so mirror selection was rebuilt to sample real throughput directly.

**Why did I change this?:** during testing, a mirror that won the HEAD-request race turned out to be noticeably slower on the actual ISO transfer. Separately, a new Debian  release temporarily left two of three mirrors returning 404s (they hadn't synced yet); the tool correctly marked them unreachable and completed successfully using the mirror that was current.

### Checksum verification

The distro's checksum file is fetched fresh on every run and parsed (using whichever format that distro requires) into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed via `hashlib` and compared against the expected hash with a string equality check.

**This was tested:** I created a separate script to append garbage bytes to a previously-verified ISO, then ran the same `verify_checksum()` function used in the main program against it. It correctly returns `False`, confirming the verification logic detects tampering/corruption rather than always reporting success.
*The script I used to test corruption is below. Feel free to try for yourself.*
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
This tool does NOT perform GPG signature verifications. Many distros use this as further proof an iso came from the correct distributor, i.e. Debian/Fedora. ISOx does not check GPG signatures, if you add any distros please ensure you are using **official** mirrors. Most distros often publish their own mirrorlists. 

## Requirements

- Python 3.x
- `requests` (`pip install requests`)
- `beautifulsoup4` (`pip install beautifulsoup4`) - used for HTML directory-listing discovery

Everything else (`hashlib`, `json`, `argparse`, `os`, `time`) is part of the Python standard library.

## License

MIT License: see [LICENSE](LICENSE) for details. Feel free to use, modify, or build on this.
