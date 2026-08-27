# Nuclear Proliferation Watch

[![Pages](https://github.com/MonarchCastleTech/nuclear-proliferation-watch/actions/workflows/pipeline.yml/badge.svg)](https://github.com/MonarchCastleTech/nuclear-proliferation-watch/actions/workflows/pipeline.yml)

Open-source monitoring signals for nuclear facilities and proliferation risk.

The autonomous warning model estimates public nuclear-escalation pressure over a 0–30 day horizon. It is not proof or prediction of weaponization, a nuclear test, or facility status.

## Reproducible model

Four predeclared components: IAEA safeguards/access strain (35%), official NPWMD designation deltas (25%), IAEA-hosted facility-security incidents (20%), and tightly filtered USGS seismic anomalies near historical test areas (20%). Available weights are renormalized. A five-point concurrence bonus requires both official and physical elevation.

Seismic events score only if shallow M3.5+ and within 75 km, or catalogued explicitly as a nuclear explosion. Even then, the model makes no nuclear-test claim: CTBTO radionuclide evidence and expert analysis are required.

GitHub Actions runs every six hours, tests before refresh, caches sources for at most 72 hours, preserves last-good output on total IAEA failure, commits accepted snapshots, and deploys GitHub Pages. Formulae and evidence are published in `data/output.json`.

**Live dashboard:** https://monarchcastletech.github.io/nuclear-proliferation-watch/

## Run locally

```bash
python -m pip install -r requirements.txt
python pipeline/nuclear_proliferation_watch_pipeline.py
python -m http.server 8000
```

Open `http://localhost:8000`. Direct `file://` access cannot fetch `data/output.json` in modern browsers.

## Automation

GitHub Actions refreshes public data every six hours and deploys the static dashboard to GitHub Pages. AI briefs are optional: configure `OPENROUTER_API_KEY` as a repository Actions secret. Without it, core collection and dashboard deployment remain available.

## Data notice

Source availability varies. The dashboard identifies its generation time and operating mode in `data/output.json`. Treat indicators as decision-support signals, not verified ground truth.

## Brand

Part of Monarch Castle Technologies. See [BRAND.md](BRAND.md) for approved asset use.
