# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification the default, and not an extra step.

Furthermore, I simply love Linux. It's been my daily driver ever since I discovered it, and I want to see it continue to grow. I hope this tool makes getting started with Linux a little faster, easier, and safer for anyone who wants to use it.

## Usage

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
...
```

Downloaded ISOs are saved to the created folder `ISOx_Downloads/`. Output looks like:

```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.33 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 1.98 MB/s
https://ftpmirror.infania.net/mirror/archlinux/iso/latest/archlinux-x86_64.iso sampled at 0.08 MB/s
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Checksum matches, file is good.
```
## Features

- **Config-driven distro support** - supported distros are defined in `distros.json`, not hardcoded, meaning adding a new distro is a JSON entry, not a code change.
- **Three ISO-discovery strategies** - covers distros that publish their ISOs in very different ways.
- **Version-folder auto-discovery** - for distros with no stable "latest" alias, the current version-numbered directory is discovered automatically by scanning a parent directory and numerically sorting version-like folder names, so outdated isos aren't retrieved.
- **Mirror speed checks** - samples ~2MB from each candidate mirror via a ranged request to measure real throughput, then downloads from the fastest.
- **Streamed downloads** - files are downloaded in large chunks (`requests` with `stream=True`) rather than loaded into memory all at once, so multi-GB ISOs don't hog RAM.
- **Checksum verification across three real-world formats** - the standard `<hash>  <filename>` format, a single-hash-per-file format, and a BSD-style format are all normalized into the same lookup and compared with `hashlib`.
- **Multi-algorithm support** - uses `hashlib.new(algo)` rather than hardcoding a specific hash function, so the same code path supports SHA256, SHA512, or anything else `hashlib` supports.
- **Path-traversal protection** - filenames discovered from remote HTML listings are validated before ever being used in a URL or local file path.

## How it works

### Config format (`distros.json`)

Every distro entry needs `mirrors`, `checksum_filename`, and `hash_algo` at minimum. Everything else is optional and only needed if that distro deviates from the simplest cases such as Arch.

Fedora is shown as a more complex example on purpose. It demonstrates the additional options available when a distro needs version discovery, mirror scanning, or custom checksum handling. Most distributions only require the basic fields plus one or two optional ones.

If the included mirrors are not ideal for your location, you can easily update them. Just find a suitable mirror from the distro’s official mirror list and replace the URL in distros.json. The tool will then handle the rest.

```json
{
    "arch": {
        "mirrors": ["https://fastly.mirror.pkgbuild.com/iso/latest/"],
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
        "version_discovery_url" : "https://dl.fedoraproject.org/pub/fedora/linux/releases/",
        "checksum_filename" : "CHECKSUM",
        "checksum_discovery_method" : "html_scan",
        "checksum_format" : "bsd",
        "discovery_method": "html_scan",
        "hash_algo": "sha256",
        "iso_filename_contains": ["Workstation", "x86_64"]
    }
}
```

### ISO filename discovery, three strategies

Not every distro publishes ISOs the same way, so `main()` picks a strategy per distro based on which config fields are present. No per-distro code exists anywhere in the script.

- **`"iso_filename"`** - for distros with one fixed, unchanging filename.
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file for a filename matching all the given substrings, since versioned filenames would be inefficient to hardcode.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - for distros with no single shared checksum file to scan. Scrapes the actual directory listing HTML with BeautifulSoup and filters `<a href>` links ending in `.iso` that match all the necessary substrings.

**Version-folder auto-discovery** (`"version_directory": true`) is a separate, earlier step for distros with no stable "latest" URL alias at all. Before any ISO discovery happens, the parent directory is scraped, version-numbered folder names are parsed and sorted *numerically*, and the newest one is spliced into every `{version}` placeholder across the mirror URLs. 

### Checksum parsing

- **`"multi"` (default)** - the standard `<hash>  <filename>` format used by `sha256sum`'s own output.
- **`"single"`** - the whole file content is treated as the hash, with the filename supplied from context rather than parsed. Available for distros that publish a genuinely bare hash.
- **`"bsd"`** - parses lines shaped like `SHA256 (filename) = hash`, used by some distros. Only lines starting with the configured `hash_algo` are read, so a file listing multiple algorithms for the same filename can't have the wrong one picked.

### Mirror selection

Each candidate mirror is sampled with a ranged GET request, pulling the first ~2MB of the actual ISO via an HTTP `Range` header, and the real transfer speed (bytes/second) is measured over that sample. The mirror with the highest sampled throughput is selected for both the checksum file and the full ISO download.

Mirrors that time out or return an error status are caught (`requests.exceptions.RequestException`) and skipped rather than crashing the whole run.

### Checksum verification

The distro's checksum file is fetched new on every run and parsed into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed via `hashlib` and compared against the expected hash with a string equality check.

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

ISOx does **not** perform GPG signature verification. Many Linux distributions publish GPG signatures alongside their release files or checksum files. These provide an additional layer of authenticity by allowing you to verify that the checksum has been signed by the distribution's key.

ISOx verifies that the downloaded ISO matches the checksum it retrieves, but it does not verify the authenticity of that checksum with GPG. For most users, this still protects against download or file corruption. 

GPG is not included as it would require maintaining trusted public keys (or fingerprints) for every supported distribution, along with key management and signature validation logic. That complexity conflicts with ISOx's goal of being a lightweight, configuration-driven tool that simplifies Linux media downloads while automatically verifying file integrity against published checksums.

If your threat model requires verifying the origin of release files, consult the distribution's official documentation for its public signing keys and GPG verification instructions.

## Requirements

- Python 3.x
- `requests` (`pip install requests`)
- `beautifulsoup4` (`pip install beautifulsoup4`) - used for HTML directory-listing discovery

Everything else (`hashlib`, `json`, `argparse`, `os`, `time`) is part of the Python standard library.

## License

MIT License: see [LICENSE](LICENSE) for details. Feel free to use, modify, or build on this.
