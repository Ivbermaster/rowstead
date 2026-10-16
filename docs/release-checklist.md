# Local release preparation

- [x] Working import → HTTP/browser → CSV/XLSX flow and responsive English panel.
- [x] SQLite/local and PostgreSQL/Compose startup with explicit migrations.
- [x] Owner/CSRF boundaries, input validation and formula-safe exports tested.
- [x] PostgreSQL claims/control/fencing regressions executed in a private network.
- [x] Real 3,000-row HTTP batch with output verification and measured resource usage.
- [x] Actual worker SIGKILL/restart and preservation of committed results.
- [x] Custom dump restoration plus original-file hash verification.
- [x] UI browser checks, four reusable desktop/mobile screenshots and local WebM walkthrough.
- [x] Local secrets, runtime data, videos and dump artifacts excluded from Git.
- [x] MIT selected by the owner; license and package metadata included.
- [x] Dependency license inventory and local publication preflight provided.
- [x] Public examples, contributor/security guidance and GitHub issue/PR templates.
- [x] Local Git repository initialized on `main`; public files reviewed before staging.
- [x] Three-step import, sample onboarding, server search and issue filtering tested in Chromium.
- [x] Owner authorized public GitHub publication as Rowstead, without video.
- [ ] Publish the prepared source repository and version 0.1.0.
- [ ] Run the hosted CI workflow after pushing; it has not run locally on GitHub.
- [ ] Review notices for the actual browser/container artifacts if distributing binaries.
- [x] Video excluded from this release; local runtime artifacts remain private.

This checklist describes local demo readiness. Public hosting, external sources,
retention automation and a managed production service are separate work.

The runtime/recovery/backup results above were measured on 2026-10-15.
See [verification](verification.md) for the separate 2026-10-16 source/UI checks
and the status of the Docker rerun. Dependency metadata is an inventory, not a
complete vulnerability audit or legal review.
