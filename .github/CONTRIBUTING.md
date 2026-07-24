# Contributing to ISOx

Thanks for taking a look. ISOx has a deliberately small surface, and the most
useful contributions are the most straightforward.

Let's get the important thing up front: **adding a distro is 99% of the time a config
change.** Of the eleven distros ISOx supports, only a couple needed code changes, which were 
Ubuntu and Fedora. Every other one, such as Mint and Garuda was an entry in `distros.json` and 
nothing else, thanks to the foundation Fedora built.

## Adding a distro

Every entry needs three fields:

- `mirrors` - a list of directory URLs (not direct links to the ISO). **HTTPS
  only.** Two or three is a good number; ISOx samples each one and downloads
  from whichever is fastest, so a slow mirror in the list costs nothing. Some distros
  have only one based on vendor suggestion. (openSUSE)
- `checksum_filename` - the name of the file the distro publishes its hashes
  in. Supports a `{iso_filename}` placeholder for distros that publish one
  checksum file per ISO.
- `hash_algo` - usually `sha256`. Anything `hashlib` supports will work.

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

### Version folders

If the distro has no permanent "latest" URL and instead puts ISOs in
version-numbered directories, set `"version_directory": true` and give a
`version_discovery_url` pointing at the parent directory. Put `{version}` in
your mirror URLs where the folder name goes, and ISOx will scrape the parent,
sort the version-like folder names numerically, and place the newest one in.

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
`"checksum_discovery_method": "html_scan"` too.

### A complete example

```json
"garuda": {
    "mirrors": ["https://iso.builds.garudalinux.org/iso/garuda/mokka/{version}/"],
    "version_directory": true,
    "version_discovery_url": "https://iso.builds.garudalinux.org/iso/garuda/mokka/",
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
Several distros have been evaluated and excluded, at least for now,
interactive download pages with no scrapable listing, checksums that don't match 
what's actually published, directory listings behind a 403, no stable index to scrape.

If you dig into one and hit a wall, open an issue describing what you found.
Knowing a distro *can't* currently be supported, and why, saves the next
person the same afternoon. I'm still exploring ways to figure this out
though.

## Acceptance criteria for a new distro

The test suite is hermetic, it stubs the network, so it can't tell you
whether a real mirror still has the layout you configured. That check is
manual, and it's the bar for merging:

1. `python isox.py <distro>` completes a full download and prints
   `Checksum matches, file is good.`
2. The resulting ISO actually boots.

Please verify these two to satisfy PR requirements. A config that doesn't boot
or run isn't exactly the criteria. Again, if you are unable to test, just
specify in the PR and I'll do the testing on my end and with VMs. I don't mind.

## Development setup

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Run `black .` before committing. CI runs `black --check` and will fail on
formatting alone, which is a frustrating way to get a red X.

## One warning about the test suite

The tests assert on user-facing strings - exception message substrings and
printed output lines, matched directly. Rewording an error message or a status
line is a test change, not a cosmetic one. If `pytest` goes red after you
touched a string, that's why, and updating the test alongside it is the
correct fix. This one almost got me too, so I get it.

## Bugs and feature requests

Open an issue. For a bug, the distro you ran, the full output, and your
Python version are usually enough to reproduce it.
