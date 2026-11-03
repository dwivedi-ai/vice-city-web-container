# Contributing

This project develops container packaging and browser asset delivery around a
pinned upstream engine. Read [the README](README.md) and
[third-party requirements](THIRD_PARTY.md) before proposing a change. Source
cleanup does not resolve permission to distribute the customized engine.

## Local checks

Use Python 3.11+ and Node 22+. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node --test tests/test_*.mjs
bash -n standalone/package.sh
sh -n docker/prepare/prepare.sh
docker compose config --quiet
git diff --check
```

Tests use synthetic data. Never attach game files, extracted assets, saves,
engine binaries, or image archives to a pull request, issue, or CI artifact.
Generated local data stays ignored; `.xo/` belongs to XO Space and must not be edited.

## Changes worth testing

Add focused regressions for behavioral fixes, particularly integrity failures,
archive extraction, retries, cancellation, cache errors, or texture preservation.
A green unit suite does not replace browser verification for engine integration.

For runtime changes, use your own game installation and check cold/warm startup,
New Game, vehicle entry/radio, driving into an uncached area, and local-save
persistence. Record time to playable world as well as Start readiness. Include
cache state, throttling, build identity, and errors in benchmark reports. Do not
compare timings taken while a build/export is competing for host resources.

The root Dockerfile is the only image definition. Changes should preserve one
runtime container, a non-root server, source game files, and an original-quality
option. Engine changes require reviewing the pinned checksums and guarded wrapper
anchors. Do not publish a rebuilt game image from CI.
