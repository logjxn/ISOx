# ISOx design notes

How ISOx works internally, and why each piece is built the way it is. The
[README](https://github.com/logjxn/ISOx/blob/main/README.md) covers what you need to
install, configure and run it; this covers the reasoning underneath.

If you're here to *add* a distro rather than to understand one, the practical guide is
[CONTRIBUTING.md](https://github.com/logjxn/ISOx/blob/main/.github/CONTRIBUTING.md).
This document explains what the code does with a config; that one explains how to
write one.

## Contents

- [ISO filename discovery](#iso-filename-discovery)
- [Version-folder discovery](#version-folder-discovery)
- [Checksum parsing](#checksum-parsing)
- [Mirror selection](#mirror-selection)
- [Resumable downloads](#resumable-downloads)
- [Checksum verification](#checksum-verification)
- [Config resolution](#config-resolution)
- [A note on the test suite](#a-note-on-the-test-suite)

## ISO filename discovery

Not every distro publishes ISOs the same way, so the tool picks a strategy per distro
based on which config fields are present.

- **`"iso_filename"`** - for distros with one fixed, unchanging filename, like Arch's
  `archlinux-x86_64.iso`. Nothing is discovered; the name is taken straight from the config.
- **`"iso_filename_contains"` + default discovery** - scans a shared checksum file for a
  filename matching all the given substrings, since versioned filenames would be
  inefficient to hardcode.
- **`"iso_filename_contains"` + `"discovery_method": "html_scan"`** - for distros with no
  single shared checksum file to scan. Scrapes the actual directory listing HTML with
  BeautifulSoup and filters `<a href>` links ending in `.iso` that match all the necessary
  substrings.

### Pre-release filtering

Both scanning strategies filter out pre-release artifacts by default. This matters more
than it sounds: Alpine publishes `alpine-extended-3.24.2_rc1-x86_64.iso` into the same
directory as the final release, and because `_` sorts above `-`, a plain "newest wins"
comparison hands you the release candidate. An RC has a perfectly valid published
checksum, so it would download and verify without complaint.

The default exclusion list covers `_rc`, `-rc`, `_beta`, `-beta`, `_alpha` and `-alpha`.
A distro can add its own disqualifying substrings with `iso_filename_excludes`, which
stack on top of the defaults rather than replacing them.

### Only `.iso` files are considered

Checksum files cover every artifact of a release, and Kali's `SHA256SUMS` pairs each ISO
with a `.iso.torrent` that matches exactly the same substrings. Without the extension
filter, a 100KB torrent could be downloaded, verified against its own hash, and reported
as a good ISO.

### The two strategies break ties differently, on purpose

A directory listing legitimately holds several versions of the same image, so the newest
wins. Filenames are ordered by a natural sort that reads embedded digit runs as integers,
so `foo-10.iso` outranks `foo-9.iso` rather than losing to it lexicographically. Date-stamped
names like `void-live-x86_64-20260101-base.iso` sort correctly under the same rule.

A checksum file, by contrast, describes a single release. Several matches there means the
config is ambiguous rather than that there's a choice to make, so the run stops and names
the candidates:

```
Error: 'debian' matched 3 ISOs in the checksum file at
https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA256SUMS:
debian-13.6.0-amd64-netinst.iso, debian-edu-13.6.0-amd64-netinst.iso,
debian-mac-13.6.0-amd64-netinst.iso. Narrow iso_filename_contains or add
iso_filename_excludes in distros.json.
```

Guessing here is how you ship `debian-mac` to someone who asked for `debian`, and it would
verify cleanly against its own published hash. The user gets a "file is good" message and
an image they didn't ask for, which is worse than a failure.

### One dead source doesn't kill discovery

Discovery is tried against each source in turn - `checksum_base` first when it's configured,
then the mirrors - and an unreachable source is treated the same as one that has no match.
Only when every source has been tried does the run fail.

When `checksum_base` is set it also decides the filename, not just the hash. Taking the name
from one host and the hash from another would quarantine a perfectly good ISO every time a
mirror lags a release behind.

## Version-folder discovery

Some distros have no stable "latest" URL alias at all and put each release in its own
version-numbered directory. `"version_directory": true` turns on a separate, earlier step:
before any ISO discovery happens, the parent directory is scraped, version-numbered folder
names are parsed and sorted *numerically*, and the newest one is spliced into every
`{version}` placeholder across the mirror URLs and `checksum_base`.

Sorting is on the parsed tuple of integer parts, so `22.1` beats `21.3` and `10` beats `9`.
Entries that aren't purely numeric-and-dots (`../`, `latest/`, `README`) are ignored.

`version_discovery_url` takes a list as well as a single URL, and they're tried in order.
This step decides which directory everything else is fetched from, so a single unreachable
host here would otherwise fail the whole run even when every configured mirror is healthy.
A failed URL prints a line and moves on:

```
Couldn't discover a version via https://dl.fedoraproject.org/pub/fedora/linux/releases/
Discovered latest version: 44
```

### The Ubuntu case

`version_scheme` is optional and only applies alongside `version_directory`. Left out, the
newest version-numbered folder is selected. Set to `"ubuntu_lts"`, only even-year `.04`
folders match, so `python isox.py ubuntu` resolves to the latest LTS.

Two things make this necessary. Interim releases sort newer than the LTS that precedes them,
so a generic "newest folder" finder serves `26.10` when `26.04` is what most people want as
a daily driver. And Canonical publishes dated point-release folders like `24.04.2` alongside
the `24.04` alias it keeps updated with the latest ISO, so restricting to two-part `YY.04`
names picks the alias rather than a snapshot.

Ubuntu is the only distro so far that has needed a version scheme of its own. If one you're
adding needs similar handling, that's a valid reason to add code - mention it in the PR.

## Checksum parsing

Three published formats are normalized into the same `{filename: hash}` lookup:

- **`multi`** (default) - the standard `<hash>  <filename>` format used by `sha256sum`'s own
  output. Lines that don't split into exactly two fields are dropped, which discards comment
  lines and blank lines without special-casing them. A leading `*` binary marker on the
  filename is stripped.
- **`single`** - the whole file content is treated as the hash, with the filename supplied
  from context rather than parsed. Available for distros that publish a genuinely bare hash.
- **`bsd`** - parses lines shaped like `SHA256 (filename) = hash`. Only lines starting with
  the configured `hash_algo` are read, so a file listing both SHA256 and SHA512 for the same
  filename can't have the wrong one picked.

A `single`-format file has no filename in it to match against, so pairing it with
`iso_filename_contains` and checksum-scan discovery is rejected at validation time rather
than failing confusingly later.

### Scraped checksum filenames

Some distros don't publish the checksum at a predictable name. `"checksum_discovery_method":
"html_scan"` scrapes the directory listing for it, currently matching files ending in
`CHECKSUM`. Fedora uses this.

## Mirror selection

Each candidate mirror is sampled with a ranged GET request, pulling the first ~2MB of the
actual ISO via an HTTP `Range` header, and the real transfer speed (bytes/second) is measured
over that sample. The mirror with the highest sampled throughput is selected for the ISO
download. The checksum is fetched separately, from `checksum_base`.

The sample reads from the real ISO rather than a synthetic test file because that's the only
thing that measures what the actual download will do. The connection is closed explicitly once
the sample size is reached - otherwise it would sit unreleased until garbage collection, and a
mirror that ignored `Range` would go on pushing the whole ISO into the socket meanwhile.

Mirrors that time out or return an error status are caught
(`requests.exceptions.RequestException`) and skipped rather than crashing the whole run. If
every mirror is unreachable, the run stops before anything is downloaded:

```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso is unreachable
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso is unreachable
Error: none of the mirrors for this distro are reachable right now. Try again soon, or swap the mirrors in distros.json.
```

### Every request identifies itself

`requests` defaults to a `python-requests/x.y.z` User-Agent, which is indistinguishable from
any other scraper and is exactly what rate-limit rules key on. Every outbound request carries
`ISOx/<version> (+https://github.com/logjxn/ISOx)` instead, so an operator seeing unfamiliar
traffic can look the project up or allowlist it rather than blanket-blocking an anonymous
client. ISOx samples every mirror on every run, so it owes them that much.

A test walks the module source and fails if any `requests.get` call site is missing its
headers, because being nameable is only worth anything if it's true of every request.

## Resumable downloads

Downloads are written to `<filename>.part` and only renamed to the final name once the
transfer completes, so a partial file can never be mistaken for a finished one. On the next
run, if a `.part` exists, its size becomes the offset in a `Range: bytes=N-` request and the
transfer continues from there.

Four things can go wrong with a resume, and each is handled:

- **The `.part` is larger than the file on the server.** The server answers `416 Range Not
  Satisfiable`, which means the partial is stale: it's deleted and the download restarts.
- **The `.part` belongs to an older release.** Rolling distros like Arch reuse the same
  filename (`archlinux-x86_64.iso`) for a new image every month, so a partial from June would
  happily append onto July's file and produce a corrupt ISO. ISOx stores the mirror's
  `ETag`/`Last-Modified` alongside the `.part` and discards the partial if it no longer
  matches. If the server publishes neither header, the partial is discarded after 24 hours
  instead.
- **A different mirror wins the race this time.** `ETag`s are per-server - nginx derives them
  from mtime and size, which differ between mirrors holding identical bytes - so a fingerprint
  from one mirror says nothing about another. The URL is recorded alongside the fingerprint
  and they're only compared when they came from the same place, otherwise the 24-hour age
  check applies. Without this, changing mirrors between runs looks exactly like the file
  changing, and a 90%-complete download gets thrown away.
- **The server ignores the `Range` header** and sends the whole file with a `200`. The offset
  is reset and the file is rewritten from scratch rather than appended to.

A transfer that ends short of the advertised `Content-Length` keeps its `.part` and exits
non-zero rather than being promoted. A short read is the exact case resuming exists for, so
turning it into a `.FAILED` ISO would throw away work that was still good - the bytes on disk
are fine, there are just fewer of them than promised.

```
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Partial download doesn't match file on server. Starting fresh.
[##############################] 100.0%    3.39 MB/s
Checksum matches, file is good.
```

Resuming an existing partial looks like this instead:

```
https://fastly.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 3.28 MB/s
https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso sampled at 2.04 MB/s
https://mirror.rackspace.com/archlinux/iso/latest/archlinux-x86_64.iso is unreachable
Downloading archlinux-x86_64.iso from https://fastly.mirror.pkgbuild.com/iso/latest ...
Resuming from 743.6 MB ...
[##############################] 100.0%    3.26 MB/s
Checksum matches, file is good.
```

Checksum verification remains the final stop: a bad merge that somehow slipped through would
fail verification and be quarantined.

### The `.meta` sidecar

The URL and fingerprint for a `.part` live in a `<filename>.part.meta` file as JSON. Before
3.0 this held a bare fingerprint instead, and since an `ETag` is a quoted string, `json.loads()`
parses one without complaint - so the old format is recognised by *shape* (not a dict) rather
than by whether it's valid JSON. Failing to write the sidecar is non-fatal; the worst case is
a `.part` being discarded that didn't need to be.

## Checksum verification

The distro's checksum file is fetched new on every run, from `checksum_base` rather than from
the mirror that served the ISO, and parsed into a `{filename: hash}` lookup dictionary. The
downloaded file is then hashed via `hashlib` and compared against the expected hash with
`hmac.compare_digest`, case-insensitively - `hexdigest()` is always lowercase and not every
distro publishes it that way, and a case difference would otherwise be reported as tampering.

If the hashes don't match, the ISO is renamed to `<filename>.FAILED`. If no checksum entry
could be found for the file at all, it's renamed to `<filename>.UNVERIFIED`. In both cases the
process exits non-zero.

```
[##############################] 100.0%    3.12 MB/s
WARNING: checksum mismatch, file may be corrupted or tampered with!
Renamed to ISOx_Downloads/archlinux-x86_64.iso.FAILED so it can't be mistaken for a verified ISO.
```

The hash algorithm is validated at startup rather than after the download. Rejecting a bad
`hash_algo` up front costs one function call; letting it reach verification costs a full
multi-gigabyte download first, and then quarantines the perfectly good ISO it just fetched.

### This was tested

I created a separate script to append garbage bytes to a previously-verified ISO, then ran
the same `verify_checksum()` function used in the main program against it. It correctly
returns `False`, confirming the verification logic detects tampering/corruption rather than
always reporting success.

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

### Filenames from remote sources are validated

Both the ISO filename and the resolved checksum filename are checked for path separators and
`..` before being used in a URL or a local path, so a crafted directory listing can't write
outside the download directory.

## Config resolution

`distros.json` is searched for in the order the
[README lists](https://github.com/logjxn/ISOx/blob/main/README.md#where-distrosjson-is-loaded-from),
first hit wins. `ISOX_DISTROS` short-circuits the search entirely, so a typo'd path is
reported rather than silently falling back to the bundled config.

The install-scheme entry is three locations rather than one because a wheel's data files land
wherever the *install scheme* puts them, and that varies by how pip was invoked:

- venv and pipx have `sys.prefix` and the data path coincide
- `pip install --user` puts it under the user base
- Debian's patched system Python defaults to `/usr/local` while `sys.prefix` stays `/usr`

Checking only `sys.prefix` means the tool can't find its own config on either of the last two,
and refuses to start. Duplicates collapse, so a normal install shows one path in the "Looked in:"
list rather than three - a list that repeats itself reads like a bug.

`distros.json` ships as a data file rather than package data, because a single-module
distribution has no package directory to carry it. CI installs the built wheel both normally
and with `--user`, then runs `isox --list` from outside the repo, since an install that
silently dropped the config would still import cleanly and only fail at runtime.

## A note on the test suite

The tests assert on user-facing strings - exception message substrings and printed output
lines, matched directly. Rewording an error message or a status line is a test change, not a
cosmetic one.

The suite is hermetic and stubs the network, which means it structurally cannot tell you
whether a real mirror still has the layout a config claims. `tests/test_live_mirrors.py`
covers that gap: it walks the whole pipeline up to the point the ISO bytes would be fetched,
for every distro, and asserts the filename it resolved has an entry in the published checksum
file. It's deselected by default and runs weekly in CI, filing an issue when a distro moves
its files.