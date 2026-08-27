# -*- coding: utf-8 -*-
"""Shared data fetchers for MCT Intelligence projects."""
import os
import json
import csv
import hashlib
import io
import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

CACHE_MAX_AGE = timedelta(hours=72)


def _cache_path(name):
    root = Path(os.path.expanduser("~")) / ".cache" / "nuclear-proliferation-watch"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}.json"


def _read_recent_cache(name):
    try:
        payload = json.loads(_cache_path(name).read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(str(payload.get("fetched_at", "")).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if timedelta(0) <= datetime.now(timezone.utc) - fetched <= CACHE_MAX_AGE:
            return payload.get("data")
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def _write_cache(name, data):
    _cache_path(name).write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data}), encoding="utf-8")


def fetch_iaea_signal_titles(max_results=100):
    """Fetch official IAEA page titles through a public indexed feed."""
    query = "site:iaea.org (safeguards OR enrichment OR inspectors OR undeclared OR verification OR proliferation) when:120d"
    rows = fetch_google_news_rss(query, max_results)
    official = [row for row in rows if row.get("domain") == "internationalatomicenergyagency" or "iaea" in str(row.get("link", ""))]
    return {"signals": official, "query": query, "cached": False}


def fetch_iaea_news_events():
    """Parse the IAEA-hosted Nuclear Events Web-based System."""
    try:
        response = requests.get("https://www-news.iaea.org/EventList.aspx?ps=100", timeout=40, headers={"User-Agent": "nuclear-proliferation-watch/2.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        for heading in soup.select("h4 a[href]"):
            cell = heading.find_parent("td")
            if not cell:
                continue
            header = cell.select_one("span.float-right-margin")
            detail = cell.find("p")
            metadata = " ".join((header.get_text(" ", strip=True) if header else "").split())
            country_match = re.match(r"(.+?),\s*(\d{2}\s+\w+\s+\d{4})(?:,\s*INES:\s*([^,]+))?", metadata)
            reported = re.search(r"Reported by\s+(.+?)\s+of\s+(.+?)\s+on\s+(\d{2}\s+\w+\s+\d{4})", detail.get_text(" ", strip=True) if detail else "", re.I)
            href = str(heading.get("href") or "")
            events.append({
                "title": " ".join(heading.get_text(" ", strip=True).split()),
                "url": "https://www-news.iaea.org/" + href.lstrip("/"),
                "country": country_match.group(1).strip() if country_match else "Unknown",
                "event_date": country_match.group(2) if country_match else None,
                "ines": country_match.group(3).strip() if country_match and country_match.group(3) else None,
                "reported_by": reported.group(1).strip() if reported else None,
                "reported_date": reported.group(3) if reported else None,
                "description": " ".join((detail.get_text(" ", strip=True) if detail else "").split())[:800],
                "source": "IAEA NEWS",
            })
        if not events:
            raise ValueError("IAEA NEWS returned no events")
        data = {"events": events, "cached": False}
        _write_cache("iaea-news", data)
        return data
    except Exception as exc:
        print(f"[IAEA-NEWS] Error: {exc}")
        cached = _read_recent_cache("iaea-news")
        if cached:
            cached["cached"] = True
            return cached
        return {}


def fetch_ofac_wmd_snapshot():
    """Download official SDN CSV and retain NPWMD program entries only."""
    url = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
    try:
        response = requests.get(url, timeout=55, headers={"User-Agent": "nuclear-proliferation-watch/2.0"})
        response.raise_for_status()
        entries = []
        for row in csv.reader(io.StringIO(response.content.decode("utf-8-sig", errors="replace"))):
            if len(row) >= 4 and str(row[0]).strip().isdigit() and "NPWMD" in str(row[3]).upper():
                entries.append({"id": str(row[0]).strip(), "name": str(row[1]).strip(), "type": str(row[2]).strip(), "program": str(row[3]).strip()})
        if not entries:
            raise ValueError("official SDN CSV contained no NPWMD entries")
        publish = re.search(r"/(\d{4}-\d{2}-\d{2})/", response.url)
        data = {"entries": entries, "count": len(entries), "publish_date": publish.group(1) if publish else None, "sha256": hashlib.sha256(response.content).hexdigest(), "cached": False}
        _write_cache("ofac-npwmd", data)
        return data
    except Exception as exc:
        print(f"[OFAC-NPWMD] Error: {exc}")
        cached = _read_recent_cache("ofac-npwmd")
        if cached:
            cached["cached"] = True
            return cached
        return {}


TEST_SITES = {
    "Punggye-ri": (41.29, 129.09), "Lop Nur": (41.69, 88.42), "Novaya Zemlya": (73.40, 54.90),
    "Semipalatinsk": (50.44, 78.75), "Nevada National Security Site": (37.12, -116.05),
    "Chagai": (28.90, 64.95), "Pokhran": (27.10, 71.80), "Reggane": (26.72, 0.17),
}


def _fetch_site_seismicity(item):
    site, (lat, lon) = item
    start = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
    response = requests.get("https://earthquake.usgs.gov/fdsnws/event/1/query", params={
        "format": "geojson", "starttime": start, "latitude": lat, "longitude": lon,
        "maxradiuskm": 250, "minmagnitude": 1.5, "orderby": "time", "limit": 2000,
    }, timeout=45, headers={"User-Agent": "nuclear-proliferation-watch/2.0"})
    response.raise_for_status()
    rows = []
    for feature in response.json().get("features", []):
        props, coordinates = feature.get("properties", {}), feature.get("geometry", {}).get("coordinates", [0, 0, 0])
        rows.append({"id": feature.get("id"), "site": site, "site_lat": lat, "site_lon": lon, "time": props.get("time"), "magnitude": props.get("mag"), "magnitude_type": props.get("magType"), "event_type": props.get("type"), "place": props.get("place"), "url": props.get("url"), "lon": coordinates[0], "lat": coordinates[1], "depth_km": coordinates[2], "source": "USGS"})
    return rows


def fetch_test_site_seismicity():
    """Fetch one-year USGS public seismicity around declared historical test areas."""
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            batches = list(executor.map(_fetch_site_seismicity, TEST_SITES.items()))
        events = [row for batch in batches for row in batch]
        data = {"events": events, "sites": [{"name": name, "lat": coords[0], "lon": coords[1]} for name, coords in TEST_SITES.items()], "cached": False}
        _write_cache("test-site-seismicity", data)
        return data
    except Exception as exc:
        print(f"[USGS-TEST-SITES] Error: {exc}")
        cached = _read_recent_cache("test-site-seismicity")
        if cached:
            cached["cached"] = True
            return cached
        return {}

def fetch_nasa_firms(api_key=None, region="world", days=1):
    """Fetch NASA FIRMS fire/thermal anomaly data."""
    key = api_key or os.environ.get("NASA_FIRMS_API_KEY", "")
    if not key:
        return []
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NPP/{region}/{days}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            lines = r.text.strip().split("\n")
            if len(lines) < 2:
                return []
            headers = lines[0].split(",")
            return [
                dict(zip(headers, line.split(",")))
                for line in lines[1:]
                if line.strip()
            ][:500]
        return []
    except Exception as e:
        print(f"[NASA-FIRMS] Error: {e}")
        return []

def fetch_cisa_kev():
    """Fetch CISA Known Exploited Vulnerabilities catalog."""
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "MCT-Intel/1.0"})
        if r.status_code == 200:
            data = r.json()
            vulns = data.get("vulnerabilities", [])
            return [
                {
                    "cveID": v.get("cveID", ""),
                    "vendorProject": v.get("vendorProject", ""),
                    "product": v.get("product", ""),
                    "vulnerabilityName": v.get("vulnerabilityName", ""),
                    "dateAdded": v.get("dateAdded", ""),
                    "shortDescription": v.get("shortDescription", ""),
                    "dueDate": v.get("requiredAction", ""),
                    "source": "CISA-KEV"
                }
                for v in vulns
            ]
        return []
    except Exception as e:
        print(f"[CISA-KEV] Error: {e}")
        return []

def fetch_acled(*_args, **_kwargs):
    """Disabled until a licensed ACLED key is explicitly configured."""
    return []

def fetch_opensanctions(*_args, **_kwargs):
    """Disabled: current OpenSanctions API requires authenticated access."""
    return {}

def fetch_census_country():
    """Fetch World Bank country indicators (GDP, population)."""
    url = "https://api.worldbank.org/v2/country?format=json&per_page=300"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if len(data) > 1:
                return [
                    {
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "region": c.get("region", {}).get("value", ""),
                        "capitalCity": c.get("capitalCity", ""),
                        "longitude": c.get("longitude", ""),
                        "latitude": c.get("latitude", ""),
                    }
                    for c in data[1]
                ]
        return []
    except Exception as e:
        print(f"[WorldBank] Error: {e}")
        return []

def fetch_coingecko(coin="bitcoin"):
    """Fetch crypto market data from CoinGecko (free, no key)."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin}"
    try:
        r = requests.get(url, params={"localization": "false", "tickers": "false"}, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        print(f"[CoinGecko] Error: {e}")
        return {}

def fetch_exchange_rates(base="USD"):
    """Fetch free exchange rates (no key needed)."""
    url = f"https://api.exchangerate-api.com/v4/latest/{base}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()
            rates = data.get("rates", {})
            # Return top 20 rates as list of dicts
            return [{"currency": k, "rate": v} for k, v in list(rates.items())[:20]]
        return []
    except Exception as e:
        print(f"[ExchangeRate] Error: {e}")
        return []

def fetch_weather(lat, lon):
    """Fetch free weather from Open-Meteo (no key)."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lat, "longitude": lon, "current": "temperature_2m,wind_speed_10m"}
    try:
        r = requests.get(url, params=params, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        print(f"[OpenMeteo] Error: {e}")
        return {}

def fetch_covid_global():
    """Fetch COVID-19 summary data."""
    url = "https://disease.sh/v3/covid-19/countries"
    try:
        r = requests.get(url, timeout=30)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[COVID] Error: {e}")
        return []

def fetch_earthquakes(hours=24):
    """Fetch recent earthquake data from USGS."""
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()
            features = data.get("features", [])
            return [
                {
                    "place": f.get("properties", {}).get("place", ""),
                    "mag": f.get("properties", {}).get("mag", 0),
                    "time": f.get("properties", {}).get("time", ""),
                    "lon": f.get("geometry", {}).get("coordinates", [0, 0, 0])[0],
                    "lat": f.get("geometry", {}).get("coordinates", [0, 0, 0])[1],
                    "depth": f.get("geometry", {}).get("coordinates", [0, 0, 0])[2],
                    "source": "USGS"
                }
                for f in features[:200]
            ]
        return []
    except Exception as e:
        print(f"[USGS-Quake] Error: {e}")
        return []

def safe_fetch(fetcher, *args, **kwargs):
    """Wrapper that catches all exceptions and returns empty data."""
    try:
        return fetcher(*args, **kwargs)
    except Exception as e:
        print(f"[SafeFetch] {fetcher.__name__} failed: {e}")
        return {} if not isinstance(args, list) else []

def fetch_google_news_rss(query, max_results=50):
    """Fetch news headlines from Google News RSS."""
    import re
    import urllib.parse
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone

    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "MCT-Intel/1.0"})
        if r.status_code != 200:
            print(f"[GoogleNews] HTTP {r.status_code}")
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:max_results]
        articles = []
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = item.findtext("link") or ""
            pub = item.findtext("pubDate") or ""
            source_el = item.find("source")
            source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
            if source_name and title.endswith(" - " + source_name):
                title = title[: -(len(source_name) + 3)].strip()
            seendate = ""
            for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
                try:
                    dt = datetime.strptime(pub.replace("GMT", "UTC"), fmt)
                    seendate = dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    break
                except ValueError:
                    continue
            if not seendate:
                seendate = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            domain = re.sub(r"[^a-z0-9.-]", "", (source_name or "news.google.com").lower()) or "news.google.com"
            articles.append({
                "title": title,
                "url": link,
                "domain": domain,
                "language": "",
                "tone": 0,
                "seendate": seendate,
                "source": "GoogleNews",
            })
        return articles
    except Exception as e:
        print(f"[GoogleNews] Error: {e}")
        return []
