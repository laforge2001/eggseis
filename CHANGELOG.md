# Changelog

All notable changes to eggseis are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [PEP 440](https://peps.python.org/pep-0440/).

## [0.1.0a1] — 2026-04-26

**M1 — "The data opens" complete.**

### Added
- `eggseis.data.SeismicVolume` — stable public abstraction over a 3D seismic volume.
- `eggseis.data.SurveyGeometry` — frozen dataclass describing inline/xline/sample geometry.
- `eggseis.data.SeismicBackend` — `Protocol` defining the storage backend contract.
- `eggseis.backends.mdio.MDIOBackend` — first backend, reads MDIO v1 surveys.
- `eggseis.cli` — Typer-based CLI with `eggseis info` and `eggseis dump-inline` commands.
- Synthetic MDIO fixture in `tests/conftest.py` for deterministic backend tests.
- GitHub Actions CI matrix on Linux/macOS/Windows × Python 3.11 / 3.12 running `pytest` and `ruff`.

### Notes
- Pre-alpha. API is stable for the surface listed above; everything else is subject to change.
- Not published to PyPI.
