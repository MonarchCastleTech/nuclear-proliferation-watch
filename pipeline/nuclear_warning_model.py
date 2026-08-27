"""Explainable public-data nuclear-escalation precursor model."""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone


WEIGHTS = {
    "iaea_safeguards_strain": 0.35,
    "npwmd_designation_delta": 0.25,
    "facility_security_incidents": 0.20,
    "test_site_seismicity": 0.20,
}

STRAIN_TERMS = {
    "cannot verify": 4.0, "unable to verify": 4.0, "loss of continuity": 4.0,
    "access": 1.4, "inspectors": 1.6, "undeclared": 3.0, "non-compliance": 3.5,
    "outstanding issues": 2.5, "enrichment": 1.4, "weapon-grade": 4.0,
    "60 per cent": 2.5, "60%": 2.5, "90 per cent": 4.0, "90%": 4.0,
    "safeguards": 1.0, "verification": 1.0, "cooperation": 0.8, "proliferation": 1.6,
}
RELIEF_TERMS = {"agreement": 1.0, "restored access": 3.0, "cooperation framework": 2.0, "resumed inspections": 3.0}
INCIDENT_TERMS = {
    "attack": 3.0, "strike": 3.0, "projectile": 3.0, "sabotage": 4.0,
    "unauthorized": 2.5, "lost": 2.0, "stolen": 3.0, "damage": 1.5,
    "explosion": 2.0, "fire": 1.2, "security": 1.0,
}


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        return None


def _robust_z(current, baseline):
    values = [float(value) for value in baseline if value is not None]
    if len(values) < 3:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    if mad < 1e-9:
        scale = max(1.0, math.sqrt(abs(median) + 1))
        return (float(current) - median) / scale
    return (float(current) - median) / (1.4826 * mad)


def _term_weight(text, terms):
    lowered = str(text or "").lower()
    return sum(weight for term, weight in terms.items() if term in lowered)


def _iaea_component(payload, now):
    signals = list(payload.get("signals") or [])
    buckets = [{"weight": 0.0, "count": 0} for _ in range(9)]
    evidence = []
    for row in signals:
        observed = _parse_date(row.get("seendate") or row.get("date"))
        if not observed:
            continue
        age = (now - observed).days
        index = age // 14
        if not 0 <= index < len(buckets):
            continue
        text = row.get("title", "")
        strain = _term_weight(text, STRAIN_TERMS)
        relief = _term_weight(text, RELIEF_TERMS)
        buckets[index]["weight"] += max(0.0, strain - relief)
        buckets[index]["count"] += 1
        if index == 0 and strain:
            evidence.append({"title": text, "url": row.get("link"), "date": observed.date().isoformat(), "weight": round(strain, 1)})
    current = buckets[0]["weight"]
    baseline = [row["weight"] for row in buckets[1:]]
    anomaly = _robust_z(current, baseline)
    density = _clamp(current * 4.0, high=60)
    score = density if sum(value > 0 for value in baseline) < 3 else 0.65 * density + 0.35 * _clamp(max(0, anomaly) * 20, high=40)
    return {
        "id": "iaea_safeguards_strain", "label": "IAEA safeguards and access strain",
        "available": bool(signals), "score": round(_clamp(score), 1), "current_14d_weight": round(current, 1),
        "current_14d_titles": buckets[0]["count"], "baseline_periods": len(baseline),
        "baseline_median": round(statistics.median(baseline), 2) if baseline else 0.0,
        "anomaly_z": round(anomaly, 2), "evidence": sorted(evidence, key=lambda row: row["weight"], reverse=True)[:12],
        "retained": bool(payload.get("cached") or payload.get("retained")),
    }


def _npwmd_component(snapshot, previous):
    current = {str(row.get("id")): row for row in snapshot.get("entries", []) if row.get("id")}
    prior = {str(row.get("id")): row for row in (previous or {}).get("entries", []) if row.get("id")}
    available = bool(current) and bool(prior)
    added = sorted(set(current) - set(prior)) if available else []
    removed = sorted(set(prior) - set(current)) if available else []
    score = _clamp(len(added) * 12 + len(removed) * 4)
    return {
        "id": "npwmd_designation_delta", "label": "Official NPWMD designation delta", "available": available,
        "score": round(score, 1), "current_count": len(current), "previous_count": len(prior) if prior else None,
        "added_count": len(added) if available else None, "removed_count": len(removed) if available else None,
        "added": [current[key] for key in added[:20]], "removed": [prior[key] for key in removed[:20]],
        "publish_date": snapshot.get("publish_date"), "sha256": snapshot.get("sha256"),
        "retained": bool(snapshot.get("cached") or snapshot.get("retained")),
    }


def _incident_component(payload, now):
    events = list(payload.get("events") or [])
    buckets = [0.0 for _ in range(12)]
    evidence = []
    for row in events:
        observed = _parse_date(row.get("reported_date") or row.get("event_date"))
        if not observed:
            continue
        index = (now - observed).days // 30
        if not 0 <= index < len(buckets):
            continue
        text = f"{row.get('title', '')} {row.get('description', '')}"
        weight = _term_weight(text, INCIDENT_TERMS)
        ines = float(row.get("ines") or 0) if str(row.get("ines") or "").replace(".", "", 1).isdigit() else 0.0
        weight += min(3.0, ines) * 0.8
        buckets[index] += weight
        if index == 0 and weight:
            evidence.append({**row, "weight": round(weight, 1)})
    anomaly = _robust_z(buckets[0], buckets[1:])
    density = _clamp(buckets[0] * 4, high=65)
    score = 0.7 * density + 0.3 * _clamp(max(0, anomaly) * 18, high=35)
    return {
        "id": "facility_security_incidents", "label": "IAEA-reported facility security incidents",
        "available": bool(events), "score": round(_clamp(score), 1), "current_30d_weight": round(buckets[0], 1),
        "baseline_months": 11, "baseline_median": round(statistics.median(buckets[1:]), 2),
        "anomaly_z": round(anomaly, 2), "evidence": sorted(evidence, key=lambda row: row["weight"], reverse=True)[:12],
        "retained": bool(payload.get("cached") or payload.get("retained")),
    }


def _seismic_component(payload, now):
    events = list(payload.get("events") or [])
    buckets = [0.0 for _ in range(12)]
    evidence = []
    for row in events:
        observed = datetime.fromtimestamp(float(row.get("time") or 0) / 1000, tz=timezone.utc)
        index = (now - observed).days // 30
        if not 0 <= index < len(buckets):
            continue
        depth = float(row.get("depth_km") or 999)
        magnitude = float(row.get("magnitude") or 0)
        event_type = str(row.get("event_type") or "").lower()
        lat1, lon1 = math.radians(float(row.get("site_lat") or 0)), math.radians(float(row.get("site_lon") or 0))
        lat2, lon2 = math.radians(float(row.get("lat") or 0)), math.radians(float(row.get("lon") or 0))
        distance = 6371 * 2 * math.asin(math.sqrt(math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2))
        diagnostic = 20.0 if "nuclear explosion" in event_type else 0.0
        if distance <= 75 and depth <= 5 and magnitude >= 3.5:
            diagnostic += 5 + (magnitude - 3.5) * 8 + (5 - max(0, depth)) * 0.5
        buckets[index] += diagnostic
        if index == 0 and diagnostic >= 2:
            evidence.append({**row, "distance_km": round(distance, 1), "weight": round(diagnostic, 1), "date": observed.isoformat()})
    anomaly = _robust_z(buckets[0], buckets[1:])
    density = _clamp(buckets[0] * 5, high=65)
    score = 0.65 * density + 0.35 * _clamp(max(0, anomaly) * 18, high=35)
    return {
        "id": "test_site_seismicity", "label": "Historical test-site seismic anomaly",
        "available": bool(payload.get("sites")), "score": round(_clamp(score), 1),
        "current_30d_diagnostic_weight": round(buckets[0], 1), "events_considered": len(events),
        "sites_monitored": len(payload.get("sites") or []), "anomaly_z": round(anomaly, 2),
        "evidence": sorted(evidence, key=lambda row: row["weight"], reverse=True)[:12],
        "retained": bool(payload.get("cached") or payload.get("retained")),
        "caveat": "Only shallow M3.5+ events within 75 km or catalogued nuclear-explosion types score. USGS waveforms alone cannot identify a nuclear explosion; CTBTO radionuclide and expert analysis are required.",
    }


def _level(score):
    return "SEVERE" if score >= 75 else "ELEVATED" if score >= 55 else "WATCH" if score >= 35 else "BASELINE"


def build_nuclear_warning(iaea_titles, npwmd, incidents, seismicity, previous_npwmd=None, previous_warning=None, now=None):
    now = now or datetime.now(timezone.utc)
    components = [
        _iaea_component(iaea_titles, now), _npwmd_component(npwmd, previous_npwmd or {}),
        _incident_component(incidents, now), _seismic_component(seismicity, now),
    ]
    available = [row for row in components if row["available"]]
    denominator = sum(WEIGHTS[row["id"]] for row in available)
    base = sum(row["score"] * WEIGHTS[row["id"]] for row in available) / denominator if denominator else 0.0
    official = [row["id"] for row in components[:2] if row["available"] and row["score"] >= 35]
    physical = [row["id"] for row in components[2:] if row["available"] and row["score"] >= 35]
    bonus = 5.0 if official and physical else 0.0
    score = _clamp(base + bonus)
    health = sum(WEIGHTS[row["id"]] * (0.85 if row.get("retained") else 1.0) for row in available)
    confidence_score = 100 * health
    confidence = "HIGH" if confidence_score >= 80 else "MEDIUM" if confidence_score >= 55 else "LOW"
    alerts = [{"id": row["id"], "title": row["label"], "score": row["score"], "level": _level(row["score"])} for row in available if row["score"] >= 35]
    history = list((previous_warning or {}).get("history") or [])[-179:]
    if history:
        last = _parse_date(history[-1].get("timestamp"))
        if last and timedelta(0) <= now - last < timedelta(hours=1):
            history.pop()
    history.append({"timestamp": now.isoformat(), "score": round(score, 1), "level": _level(score), "components": {row["id"]: row["score"] for row in components}})
    return {
        "issued_at": now.isoformat(), "horizon": "0-30 days",
        "classification": "nuclear-escalation-pressure-not-test-or-weapon-probability",
        "score": round(score, 1), "level": _level(score), "confidence": confidence, "confidence_score": round(confidence_score, 1),
        "components": components, "concurrence": {"active": bool(bonus), "official_components": official, "physical_components": physical, "score_bonus": bonus},
        "alerts": sorted(alerts, key=lambda row: row["score"], reverse=True), "history": history,
        "data_health": {"available_components": len(available), "retained_components": [row["id"] for row in components if row.get("retained")], "iaea_titles": len(iaea_titles.get("signals") or []), "npwmd_entries": len(npwmd.get("entries") or []), "iaea_events": len(incidents.get("events") or []), "test_sites": len(seismicity.get("sites") or [])},
        "method": {"name": "Nuclear escalation precursor concurrence model v1", "weights": WEIGHTS, "aggregation": "availability-renormalized weighted mean; five-point bonus requires independent official and physical elevation", "warning": "Public escalation pressure only; not proof or prediction of a nuclear test, weaponization, or facility status."},
        "sources": [
            {"name": "IAEA official pages", "url": "https://www.iaea.org/newscenter"},
            {"name": "IAEA Nuclear Events Web-based System", "url": "https://www-news.iaea.org/"},
            {"name": "OFAC Sanctions List Service", "url": "https://ofac.treasury.gov/sanctions-list-service"},
            {"name": "USGS Earthquake Catalog", "url": "https://earthquake.usgs.gov/fdsnws/event/1/"},
            {"name": "CTBTO verification-method caveat", "url": "https://www.ctbto.org/our-work/international-data-centre"},
        ],
    }
