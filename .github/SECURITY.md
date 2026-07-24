# Security Policy

## What ISOx protects against

ISOx downloads a Linux ISO and verifies it against the checksum the
distribution publishes. That catches:

- Corruption in transit or on disk
- A truncated or partially-written download
- A mirror serving a modified ISO

## What it does not protect against

ISOx does **not** verify GPG signatures. It confirms the ISO matches the
checksum it fetched, but it does not confirm that checksum is authentic. If a
distribution's published checksum is itself wrong or tampered with at the
source, ISOx will faithfully verify against it and report success.

This is a deliberate design decision, explained in the
[README](https://github.com/logjxn/ISOx/blob/main/README.md#note). If your
threat model requires verifying the origin of a release, follow the
distribution's own GPG instructions.

Related, and worth stating plainly: mirrors are selected by measured download
speed, not by trust. All configured mirrors are HTTPS.

## Reporting a vulnerability

Please report privately rather than opening a public issue:

**[Report a vulnerability](https://github.com/logjxn/ISOx/security/advisories/new)**

Useful things to include: what you did, what happened, and the distro you ran
if it's specific to one. A reproduction is ideal but not required.

I'll acknowledge within a week. ISOx is maintained by me in my spare
time, so I'd rather promise a week and mean it than promise a day and miss it.

## Supported versions

Only the latest release is supported. ISOx is a single file with no release
branches, so fixes ship in the next release rather than being backported.

## What counts

Reports that would land as a security issue rather than a bug:

- A path outside `ISOx_Downloads/` being written to, via a crafted filename in
  a directory listing or checksum file
- A failed or skipped verification being reported as a success
- Anything in a mirror's response leading to code execution
- A `.part` from a different file being silently merged into a download

Reports that are bugs, and belong in a normal issue:

- A distro's layout changed upstream and discovery broke
- A mirror is down or slow
- The absence of GPG verification, which is documented above
