"""Autonomous public-data pipeline for nuclear-escalation early warning."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import fetch_iaea_news_events, fetch_iaea_signal_titles, fetch_ofac_wmd_snapshot, fetch_test_site_seismicity
from nuclear_warning_model import build_nuclear_warning


def load_config():
    with open(os.path.join(os.path.dirname(__file__), "config.yaml"), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_previous():
    try:
        with open("data/output.json", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _retain(live, previous, key, notes):
    if live.get(key) or not previous.get(key):
        return
    live[key] = dict(previous[key])
    live[key]["retained"] = True
    notes.append(f"{key} unavailable; retained last accepted snapshot.")


def fetch_all(previous):
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {
            "iaea_titles": executor.submit(fetch_iaea_signal_titles),
            "iaea_events": executor.submit(fetch_iaea_news_events),
            "ofac_npwmd": executor.submit(fetch_ofac_wmd_snapshot),
            "test_site_seismicity": executor.submit(fetch_test_site_seismicity),
        }
    live = {key: job.result() for key, job in jobs.items()}
    notes = []
    previous_live = previous.get("live_data") or {}
    for key in jobs:
        _retain(live, previous_live, key, notes)
    return {key: value for key, value in live.items() if value}, notes


def build_stats(warning):
    health = warning.get("data_health") or {}
    npwmd = next((row for row in warning.get("components", []) if row.get("id") == "npwmd_designation_delta"), {})
    return [
        {"label": "Escalation Pressure", "value": f"{warning.get('score', 0):.1f}/100", "delta": warning.get("level", "UNAVAILABLE")},
        {"label": "IAEA Signals", "value": str(health.get("iaea_titles", 0)), "delta": "official indexed pages"},
        {"label": "NPWMD Entries", "value": str(health.get("npwmd_entries", 0)), "delta": f"{(npwmd.get('added_count') or 0):+d} since snapshot"},
        {"label": "Model Coverage", "value": f"{health.get('available_components', 0)}/4", "delta": warning.get("confidence", "LOW") + " confidence"},
    ]


def main():
    config, previous = load_config(), load_previous()
    live, notes = fetch_all(previous)
    if not live.get("iaea_titles") and not live.get("iaea_events"):
        print("No IAEA source available; preserving last-good output.")
        return False
    warning = build_nuclear_warning(
        live.get("iaea_titles") or {}, live.get("ofac_npwmd") or {},
        live.get("iaea_events") or {}, live.get("test_site_seismicity") or {},
        previous_npwmd=(previous.get("live_data") or {}).get("ofac_npwmd"), previous_warning=previous.get("early_warning"),
    )
    retained = warning.get("data_health", {}).get("retained_components", [])
    output = {
        "meta": {"project": config["project"]["id"], "generated": datetime.now(timezone.utc).isoformat(), "mode": "partial" if retained else "live", "sources": [row["name"] for row in warning["sources"]], "source_notes": notes, "version": "2.0.0"},
        "early_warning": warning, "stats": build_stats(warning), "live_data": live,
        "events": (warning["components"][0].get("evidence") or []) + (warning["components"][2].get("evidence") or []),
    }
    os.makedirs("data", exist_ok=True)
    with open("data/output.json", "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
    print(f"Done. mode={output['meta']['mode']} score={warning['score']} level={warning['level']} coverage={warning['data_health']['available_components']}/4")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if main() else 2)
