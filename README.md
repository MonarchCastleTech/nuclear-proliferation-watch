# Nuclear Proliferation Watch

[![Pages](https://github.com/MonarchCastleTech/nuclear-proliferation-watch/actions/workflows/pipeline.yml/badge.svg)](https://github.com/MonarchCastleTech/nuclear-proliferation-watch/actions/workflows/pipeline.yml)

Open-source monitoring signals for nuclear facilities and proliferation risk.

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
