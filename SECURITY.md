# Security

Rowstead is a local portfolio demo. Its bundled sources are synthetic, and the
default Compose setup publishes only the API on localhost. Public deployment,
untrusted source adapters and production monitoring require additional work;
see [architecture and operational limits](docs/architecture.md).

Security fixes are considered for the current development version. There is no
guaranteed response time or maintained older-release support schedule.

For a suspected vulnerability, use **Security → Report a vulnerability** on the
GitHub repository when private reporting is enabled. Include the affected
version, impact and a minimal reproduction using synthetic data. Never include
live passwords, cookies, uploads or customer records. GitHub documents the
[private reporting process](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

If the private-report button is unavailable, open a public issue containing only
a request for a private contact route; wait for that route before sending exploit
details. A `SECURITY.md` file does not enable GitHub private reporting automatically.
The repository owner must enable it when setting up the public repository.

Keep local credentials in ignored environment files. Rotate any exposed secret
immediately; deleting it from a later commit does not remove earlier copies.
The local release checker is a useful heuristic, not a complete security audit.
