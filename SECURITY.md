# Security

Security fixes target the current `main` branch. There is no guaranteed response
time or supported historical release series.

For a vulnerability, use the repository's **Security → Report a vulnerability**
option when available. If private reporting is unavailable, open a minimal issue
requesting a private contact without including exploit details, credentials, game
files, or saves. Include the affected revision and a synthetic reproduction when
sharing details privately.

The server serves all packaged assets to clients that can reach it; it does not
provide authentication. Apply access control at your reverse proxy if needed.
Browser saves belong to each browser origin, not the container. Treat backups and
archives as untrusted input; extraction rejects paths outside the destination,
links, and special files, but it is not a resource sandbox for arbitrarily large
or maliciously compressed inputs.

Unit tests and checksum-pinned downloads are safeguards, not a complete security
audit. Review upstream components and base images when updating deployments.
