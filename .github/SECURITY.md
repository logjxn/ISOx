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
[README](https://github.com/logjxn/ISOx/blob/main/README.md#what-verification-does-and-doesnt-cover). If your
threat model requires verifying the origin of a release, follow the
distribution's own GPG instructions.

All configured mirrors are HTTPS, and ISOx never uses a response that is over plain HTTP.

## Reporting a vulnerability

Please report privately rather than opening a public issue:

**[Report a vulnerability](https://github.com/logjxn/ISOx/security/advisories/new)**

Useful things to include: what you did, what happened, and the distro you ran
if it's specific to one.

I'll acknowledge within a week. ISOx is maintained by me in my spare
time, so I'd rather promise a week to give some leeway.