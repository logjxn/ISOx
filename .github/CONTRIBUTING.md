# Contributing to ISOx

Thanks for taking a look. ISOx has a deliberately small surface, and the most
useful contributions are the most straightforward.

Let's get the important thing up front: **adding a distro is 99% of the time a config
change.** Of the distros ISOx supports, only a couple needed code changes, which were
Ubuntu and Fedora. Every other one, such as Mint and Garuda, was an entry in `distros.json` and
nothing else, thanks to the foundation Fedora built.

## Adding a distro

Every entry needs three fields:

- `mirrors` - a list of directory URLs (not direct links to the ISO). **HTTPS
  only, enforced by validation.** Two or three is a good number; ISOx samples each one and downloads
  from whichever is fastest, so a slow mirror in the list costs nothing. Some distros
  have only one based on vendor suggestion. (openSUSE)
- `checksum_filename` - the name of the file the distro publishes its hashes
  in. Supports a `{iso_filename}` placeholder for distros that publish one
  checksum file per ISO.
- `hash_algo` - usually `sha256`. Anything `hashlib` supports will work, and it's
  checked at startup rather than after the download.

One more you should always set:

- `checksum_base` - the directory URL on the **distro's own server** to fetch the
  checksum from, instead of taking it from whichever mirror won the speed race. A
  mirror that can serve a modified ISO can serve a matching hash just as easily, so
  this is what stops one rogue mirror supplying both halves. Usually this is the
  vendor-run entry already in your `mirrors` list. It takes `{version}` too.

Then pick how ISOx should find the ISO filename. There are three strategies,
chosen by which fields you set:

| The distro | Use |
|---|---|
| always publishes the same filename | `iso_filename` |
| versions the filename, but lists all of them in one shared checksum file | `iso_filename_contains` |
| versions the filename and has no shared checksum file | `iso_filename_contains` + `"discovery_method": "html_scan"` |

`iso_filename_contains` is a list of substrings that must *all* appear in the
filename. Pick the ones that stay stable across releases, architecture,
edition, that type of thing, and avoid anything containing a version number.

### When your substrings match more than one ISO

This is the part worth getting right, because the failure mode is quiet. Debian's
`SHA256SUMS` lists `debian-`, `debian-edu-` and `debian-mac-` netinst images, and all
three match `["netinst", "amd64"]`. Kali pairs every `.iso` with a `.iso.torrent` that
matches the same substrings. A wrong pick still verifies cleanly, because the thing you
downloaded has a valid published hash of its own - you just get an image you didn't ask
for and a "file is good" message.

So ISOx doesn't guess. Non-`.iso` files are dropped, and if more than one candidate
survives in a checksum file the run stops and names them. Add `iso_filename_excludes` -
a list of disqualifying substrings - to narrow it down:

```json
"iso_filename_contains": ["netinst", "amd64"],
"iso_filename_excludes": ["-edu-", "-mac-"]
```

Release candidates (`_rc1`, `-beta`, `-alpha`) are filtered out for you everywhere.
Don't skip this as a curiosity: Alpine publishes RCs into the same directory as final
releases, and `_` sorts *above* `-`, so "newest wins" would otherwise pick
`alpine-extended-3.24.2_rc1-x86_64.iso` over the actual release.

### Version folders

If the distro has no permanent "latest" URL and instead puts ISOs in
version-numbered directories, set `"version_directory": true` and give a
`version_discovery_url` pointing at the parent directory. Put `{version}` in
your mirror URLs where the folder name goes, and ISOx will scrape the parent,
sort the version-like folder names numerically, and place the newest one in.

`version_discovery_url` also takes a list, tried in order. Give it a second host
where you can - this step decides the directory everything else is fetched from,
so one unreachable server here fails the run even when the mirrors are all fine.

Ubuntu is the one distro that needed more than this, because "newest folder"
and "newest LTS" aren't the same thing. That's what `version_scheme` exists
for. If a distro you're adding needs similar special handling, mention in
the PR, it's a valid reason to add code.

### Checksum format

Set `checksum_format` to whichever shape the distro publishes:

- `multi` (the default) - `<hash>  <filename>`, one per line
- `bsd` - `SHA256 (filename) = <hash>`
- `single` - the file contains only the hash and nothing else

If the checksum file isn't at a predictable name and has to be scraped, set
`"checksum_discovery_method": "html_scan"` too. Currently this matches files ending in
CHECKSUM; if your distro's scraped checksum file is named differently, mention it in the PR.

### A complete example

```json
"garuda": {
    "mirrors": ["https://iso.builds.garudalinux.org/iso/garuda/mokka/{version}/"],
    "version_directory": true,
    "version_discovery_url": "https://iso.builds.garudalinux.org/iso/garuda/mokka/",
    "checksum_base": "https://iso.builds.garudalinux.org/iso/garuda/mokka/{version}/",
    "checksum_filename": "{iso_filename}.sha256",
    "discovery_method": "html_scan",
    "hash_algo": "sha256",
    "iso_filename_contains": ["garuda", "mokka"]
}
```

Despite the long list of fields, Garuda did not cost me any new Python. Shoutout
Fedora.

## Just want to request a distro?

You don't have to configure it yourself. Open a
[distro request](https://github.com/logjxn/ISOx/issues/new/choose) with the mirrors and checksum file
you know about, and that's plenty to work from. I love working on this, so I'll
get it added. :)

## Distros that *don't* work

These are just as useful to report, and I'd rather have the writeup than not.
Several distros have been evaluated and excluded, at least for now:
interactive download pages with no scrapable listing, checksums that don't match
what's actually published, directory listings behind a 403, no stable index to scrape.

If you dig into one and hit a wall, open an issue describing what you found.
Knowing a distro *can't* currently be supported, and why, saves the next
person the same afternoon. I'm still exploring ways to figure this out
though.

## Acceptance criteria for a new distro

The default test suite is hermetic, it stubs the network, so it can't tell you
whether a real mirror still has the layout you configured. Two of the three
checks below cover that, and they're the bar for merging:

1. `pytest -m live -k <distro>` passes. This resolves the version folder, the
   ISO filename and the checksum against the real mirrors, and confirms the
   filename it settled on actually has an entry in the published checksum file.
   It downloads no ISO, so it takes seconds rather than an evening, and it
   catches the common config mistakes: substrings that match two images,
   substrings that match none, a checksum file that lists a different name.
2. `python isox.py <distro>` completes a full download and prints
   `Checksum matches, file is good.`
3. The resulting ISO actually boots.

Run step 1 first. If it fails, steps 2 and 3 will waste a lot of bandwidth
telling you the same thing more slowly.

Please verify these two to satisfy PR requirements. A config that doesn't boot
or run isn't exactly the criteria. Again, if you are unable to test, just
specify in the PR and I'll do the testing on my end and with VMs. I don't mind.

## Development setup

```bash
pip install -e '.[dev]'
pytest              # hermetic, no network
pytest -m live      # checks every distro against the real mirrors, ~30s
pytest -m live -s   # same, printing the filename and hash it resolved
```

Run `black .` and `ruff check .` before committing. CI runs both and will fail on
formatting alone, which is a frustrating way to get a red X. CI does *not* run the
live tests, since a mirror having a bad afternoon isn't a reason to fail a PR.

## One warning about the test suite

The tests assert on user-facing strings - exception message substrings and
printed output lines, matched directly. Rewording an error message or a status
line is a test change, not a cosmetic one. If `pytest` goes red after you
touched a string, that's why, and updating the test alongside it is the
correct fix. This one almost got me too, so I get it.

## Bugs and feature requests

Open an issue. For a bug, the distro you ran, the full output, and your
Python version are usually enough to reproduce it.
