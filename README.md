# ISOx

A command-line tool that downloads Linux distribution ISOs, races mirrors to find the fastest available source, and cryptographically verifies file integrity against source checksums, so you never have to manually hunt down hashes or skip verification because it's tedious.

```
Select distro -> Compare mirror speeds -> Download .iso -> Verify checksum
```

## Why

I distro-hop a lot across laptops, tablets, Pis, and spare hardware. Manually visiting each project's download page, picking a mirror, and copy-pasting checksums to verify against every time got tedious enough that I started skipping the verification step entirely. This poses an integrity risk (modified ISOs, corruption, etc.), so I built a tool that automates the whole pipeline and makes verification the default, and not an extra step.

Furthermore, I simply love Linux. It's been my daily driver ever since I discovered it, and I want to see it continue to grow. I hope this tool makes getting started with Linux a little faster, easier, and safer for anyone who wants to use it.

## Usage
List every supported distro:
```bash
python isox.py --list
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
- **Version-folder auto-discovery** - for distros with no stable "latest" alias, the current version-numbered directory is discovered automatically by scanning a parent directory and numerically sorting version-like folder names, so outdated ISOs aren't retrieved.
- **Mirror speed checks** - samples ~2MB from each candidate mirror via a ranged request to measure real throughput, then downloads from the fastest.
- **Resumable downloads** - interrupted transfers are written to a `.part` file and continued via an HTTP `Range` request on the next run, so a drop at 90% doesn't cost you the 90% you already downloaded.
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

Not every distro publishes ISOs the same way, so the tool picks a strategy per distro based on which config fields are present. No per-distro code exists anywhere in the script.

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

**All Mirrors Down**
``` 
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso is unreachable
Error: none of the mirrors for this distro are reachable right now. Try again soon, or swap the mirrors in distros.json.
```


### Resumable downloads

Downloads are written to `<filename>.part` and only renamed to the final name once the transfer completes, so a partial file can never be mistaken for a finished one. On the next run, if a `.part` exists, its size becomes the offset in a `Range: bytes=N-` request and the transfer continues from there.

Three things can go wrong with a resume, and each is handled:

- **The `.part` is larger than the file on the server.** The server answers `416 Range Not Satisfiable`, which means the partial is stale: it's deleted and the download restarts.
- **The `.part` belongs to an older release.** Rolling distros like Arch reuse the same filename (`archlinux-x86_64.iso`) for a new image every month, so a partial from June would happily append onto July's file and produce a corrupt iso. ISOx stores the mirror's `ETag`/`Last-Modified` alongside the `.part` and discards the partial if it no longer matches. If the server publishes neither header, the partial is discarded after 24 hours instead.
- **The server ignores the `Range` header** and sends the whole file with a `200`. The offset is reset and the file is rewritten from scratch rather than appended to.

**Stale Partial Downloads**
``` 
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Partial download doesn't match file on server. Starting fresh.
[##############################] 100.0%    3.39 MB/s
Checksum matches, file is good.
```

Checksum verification remains the final stop: a bad merge that somehow slipped through would fail verification and be quarantined.

### Checksum verification

The distro's checksum file is fetched new on every run and parsed into a `{filename: hash}` lookup dictionary. The downloaded file is then hashed via `hashlib` and compared against the expected hash with a string equality check.

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

## NOTE

ISOx does **not** perform GPG signature verification. Many Linux distributions publish GPG signatures alongside their release files or checksum files. These provide an additional layer of authenticity by allowing you to verify that the checksum has been signed by the distribution's key.

ISOx verifies that the downloaded ISO matches the checksum it retrieves, but it does not verify the authenticity of that checksum with GPG. For most users, this still protects against download or file corruption. 

GPG is not included as it would require maintaining trusted public keys (or fingerprints) for every supported distribution, along with key management and signature validation logic. That complexity conflicts with ISOx's goal of being a lightweight, easy to use, and config-driven Linux tool.

If your threat model requires verifying the origin of releases, consult the distribution's official documentation for its public signing keys and GPG verification instructions.

## Requirements

- Python 3.x
- `requests` (`pip install requests`)
- `beautifulsoup4` (`pip install beautifulsoup4`) - used for HTML directory-listing discovery

Everything else (`hashlib`, `json`, `argparse`, `os`, `sys`, `time`) is part of the Python standard library.

## License

MIT License: see [LICENSE](LICENSE) for details. Feel free to use, modify, or build on this.
