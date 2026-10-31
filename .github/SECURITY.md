# Security Policy

## Verification

ISOx verifies downloaded Linux ISOs against checksums published by their respective distributions.

This detects:
- Corruption during transfer or storage.
- Incomplete or truncated downloads.
- ISOs that do not match the published checksum.

ISOx does **not** verify GPG signatures. A successful checksum verification confirms that the ISO matches the retrieved checksum, not that the checksum itself is authentic.

If your threat model requires release authenticity verification, follow the distribution's official signature verification instructions.

All configured mirrors use HTTPS. ISOx does not accept downloads over plain HTTP.

## Reporting a Vulnerability

Please report security vulnerabilities privately rather than opening a public issue.

Include a description of the issue, steps to reproduce it, and the affected distribution or environment, if applicable.

I'll acknowledge reports within seven days. ISOx is maintained independently, so remediation timelines may vary.