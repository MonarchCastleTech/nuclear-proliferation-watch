from datetime import datetime, timedelta, timezone

from pipeline.nuclear_warning_model import WEIGHTS, _npwmd_component, build_nuclear_warning


NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)


def title(days, text="IAEA unable to verify undeclared enrichment activities"):
    return {"title": text, "seendate": (NOW - timedelta(days=days)).strftime("%Y%m%dT%H%M%SZ"), "link": "https://www.iaea.org/example"}


def sources():
    iaea = {"signals": [title(day) for day in (0, 2, 4, 20, 40, 60, 80, 100)]}
    npwmd = {"entries": [{"id": "2", "name": "Entity B"}], "count": 1}
    prior = {"entries": [{"id": "1", "name": "Entity A"}]}
    incidents = {"events": [
        {"title": "Projectile struck facility", "reported_date": f"{day:02d} Aug 2026", "description": "attack and damage", "url": "https://www-news.iaea.org/"}
        for day in (27, 25, 23)
    ]}
    seismic = {"sites": [{"name": "Punggye-ri"}], "events": []}
    return iaea, npwmd, prior, incidents, seismic


def test_contract_and_weights():
    iaea, npwmd, prior, incidents, seismic = sources()
    warning = build_nuclear_warning(iaea, npwmd, incidents, seismic, previous_npwmd=prior, now=NOW)
    assert warning["classification"] == "nuclear-escalation-pressure-not-test-or-weapon-probability"
    assert warning["horizon"] == "0-30 days"
    assert WEIGHTS == {"iaea_safeguards_strain": .35, "npwmd_designation_delta": .25, "facility_security_incidents": .20, "test_site_seismicity": .20}
    assert warning["data_health"]["available_components"] == 4


def test_exact_npwmd_delta():
    result = _npwmd_component({"entries": [{"id": "2"}, {"id": "3"}]}, {"entries": [{"id": "1"}, {"id": "2"}]})
    assert result["added_count"] == 1
    assert result["removed_count"] == 1
    assert result["added"][0]["id"] == "3"


def test_first_snapshot_excluded_not_zero():
    iaea, npwmd, _, incidents, seismic = sources()
    warning = build_nuclear_warning(iaea, npwmd, incidents, seismic, now=NOW)
    delta = next(row for row in warning["components"] if row["id"] == "npwmd_designation_delta")
    assert delta["available"] is False
    assert warning["data_health"]["available_components"] == 3


def test_concurrence_needs_official_and_physical():
    iaea, npwmd, prior, incidents, seismic = sources()
    warning = build_nuclear_warning(iaea, npwmd, incidents, seismic, previous_npwmd=prior, now=NOW)
    assert warning["concurrence"]["active"] is True
    assert warning["concurrence"]["score_bonus"] == 5


def test_history_replaces_same_hour_and_is_bounded():
    iaea, npwmd, prior, incidents, seismic = sources()
    history = [{"timestamp": (NOW - timedelta(hours=200-index)).isoformat(), "score": index} for index in range(200)]
    history.append({"timestamp": (NOW - timedelta(minutes=10)).isoformat(), "score": 99})
    warning = build_nuclear_warning(iaea, npwmd, incidents, seismic, previous_npwmd=prior, previous_warning={"history": history}, now=NOW)
    assert len(warning["history"]) <= 180
    assert warning["history"][-1]["timestamp"] == NOW.isoformat()
