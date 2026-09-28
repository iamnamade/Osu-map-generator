# osu! Map AI Generator

An AI-assisted osu! beatmap generator: analyze a song, place Ranked-section-compliant
hit objects across Easy/Normal/Hard, validate against the osu! Ranking Criteria,
and export `.osu`/`.osz` mapsets — with a local web wizard (generator + editor)
driven by a localhost FastAPI bridge.

## Quick start

```bash
npm install
npm run generator:dev        # full local wizard (API + frontend)
# or
npm run dev                  # frontend only
```

Python engine deps: `pip install -r tools/local_api/requirements.txt`
(includes `tools/map_generator/requirements.txt`).

## Validation

One command runs the entire verification pass (exit-code aware):

```bash
npm run validate:all         # == python tools/validate_all.py
```

Stages: Python engine suite → Python local-API suite → `tsc --noEmit` → Vitest.
See `docs/ARCHITECTURE.md §3` for flags and per-stage commands.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture and the
  quality achievements locked in across the six audit phases:
  - **Ranking Criteria compliance** — density bands (Easy 0.8–2.0, Normal 1.3–2.0,
    Hard 2.5–3.8 obj/s), ≥35% slider ratio for Normal/Hard, spinner clearance and
    recovery, collision/stacking prevention, 512×384 containment.
  - **Unicode / i18n metadata pipeline** — NFC normalization, transliteration
    fallbacks, `TitleUnicode`/`ArtistUnicode` export, shared filename sanitization.
  - **Modular PlacementStrategy architecture** — Standard (production),
    Catch and Mania seams behind a registered-strategy interface.
  - **Security hardening** — magic-byte upload validation, per-stage execution
    watchdogs, atomic workspace manifest writes, path-safety defense in depth.
- `docs/` — per-feature guides (validation, difficulty, evolution, tournaments,
  post-processing, section-aware mapping, osu! format interop).
- `audit_reports/` — the six audit reports (`phase_1_density.md` …
  `phase_6_master_roadmap.md`) that drove the hardening roadmap.

## Script map (excerpt)

| Script | Purpose |
|--------|---------|
| `npm run validate:all` | Unified validation pass (Python + tsc + Vitest) |
| `npm run test` / `npm run typecheck` | Vitest / TypeScript only |
| `npm run generate:map:*` | Generate a beatmap for a difficulty |
| `npm run validate:maps` | Validate generated maps |
| `npm run improve:maps` | Post-process maps against validator reports |
| `npm run export:osu:all` / `npm run package:osz` | Export `.osu` / package `.osz` |
