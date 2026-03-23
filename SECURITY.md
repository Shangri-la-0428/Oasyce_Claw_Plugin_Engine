# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.11.x  | Yes                |
| < 1.11  | No                 |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, send an email to **wutc@oasyce.com** with the subject line
`[SECURITY] <brief description>`.

### What to Include

- Description of the vulnerability and its potential impact.
- Steps to reproduce or a proof-of-concept.
- Affected version(s) and component(s) (e.g., consensus, escrow, capability delivery).
- Any suggested fix, if available.

### Response Timeline

- **48 hours** -- acknowledgment of your report.
- **7 days** -- initial assessment and severity classification.
- **30 days** -- target for a fix or mitigation for confirmed vulnerabilities.

Timelines may vary for complex issues. We will keep you informed of progress.

## Coordinated Disclosure

We follow a coordinated disclosure model:

1. Reporter submits the vulnerability privately.
2. We confirm, triage, and develop a fix.
3. A patched release is published.
4. The vulnerability is disclosed publicly after the fix is available.

We ask that you allow us a reasonable window to address the issue before any
public disclosure. We will credit reporters in release notes unless anonymity
is requested.

## Out of Scope

The following are generally not considered security vulnerabilities:

- Denial of service on local development/testnet instances.
- Issues requiring physical access to the machine.
- Social engineering attacks.
- Vulnerabilities in dependencies that are already publicly disclosed (please
  still report if Oasyce uses an affected version).
- Bugs in third-party services or infrastructure not maintained by Oasyce.

## Questions

For general security questions that are not vulnerability reports, open a
discussion on the [GitHub repository](https://github.com/Shangri-la-0428/oasyce-net).
