from __future__ import annotations
import asyncio
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core import ACTIVITIES, LABELS, TAGS, advice, choose_hours, parse_question, score, status_for

app = FastAPI(
    title="GeoAI Outdoor Assistant",
    version="0.2.0",
    description="Live-data recommendations for outdoor activities.",
)
STATIC = Path(__file__).parent / "static" / "index.html"
CACHE: dict[str, tuple[float, Any]] = {}
HEADERS = {"User-Agent": "Fieldnote-GeoAI/0.2 (outdoor activity hackathon prototype)"}
TTL_SECONDS = 600

class RecommendRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1000)
    radius_km: float | None = Field(default=None, ge=2, le=50)
    activity: str | None = None
    location: str | None = None
    personal: dict[str, bool] | None = None

async def get_json(client: httpx.AsyncClient, url: str, params=None, method="get", data=None):
    key = f"{method}:{url}:{params}:{data}"
    cached = CACHE.get(key)
    if cached and time.time() - cached[0] < TTL_SECONDS:
        return cached[1]
    try:
        if method == "post":
            response = await client.post(url, content=data, headers={"Content-Type": "text/plain"})
        else:
            response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        CACHE[key] = (time.time(), payload)
        return payload
    except Exception as exc:
        host = url.split("/")[2]
        raise HTTPException(
            status_code=502,
            detail=f"Live data source {host} is unavailable ({type(exc).__name__}).",
        ) from exc

async def geocode(client: httpx.AsyncClient, place: str) -> dict:
    data = await get_json(
        client,
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": place, "count": 1, "language": "en", "format": "json"},
    )
    results = data.get("results") or []
    if not results:
        raise HTTPException(status_code=422, detail=f"Could not locate '{place}'. Add a nearby city or area.")
    item = results[0]
    return {
        "name": ", ".join(value for value in (item.get("name"), item.get("admin1"), item.get("country")) if value),
        "lat": item["latitude"],
        "lon": item["longitude"],
        "timezone": item.get("timezone"),
    }

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad = math.pi / 180
    delta_lat, delta_lon = (lat2 - lat1) * rad, (lon2 - lon1) * rad
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(delta_lon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(value))

def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad = math.pi / 180
    y = math.sin((lon2 - lon1) * rad) * math.cos(lat2 * rad)
    x = math.cos(lat1 * rad) * math.sin(lat2 * rad) - math.sin(lat1 * rad) * math.cos(lat2 * rad) * math.cos((lon2 - lon1) * rad)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def matches_activity(tags: dict, activity: str) -> bool:
    return any(tags.get(key) == value for key, value in TAGS[activity])

async def get_places(client: httpx.AsyncClient, center: dict, radius_km: float, activity: str):
    lat, lon = center["lat"], center["lon"]
    radius_m = int(radius_km * 1000)
    venue_terms = [f'nwr(around:{radius_m},{lat},{lon})[{key}="{value}"];' for key, value in TAGS[activity]]
    nearby_m = int((radius_km + 2) * 1000)
    context_terms = [
        f'nwr(around:{nearby_m},{lat},{lon})[highway~"^(motorway|trunk|primary|secondary|tertiary)$"];',
        f'nwr(around:{nearby_m},{lat},{lon})[landuse=industrial];',
        f'nwr(around:{nearby_m},{lat},{lon})[natural=water];',
        f'nwr(around:{nearby_m},{lat},{lon})[leisure=park];',
        f'nwr(around:{nearby_m},{lat},{lon})[leisure=garden];',
    ]
    query = (
        "[out:json][timeout:20];("
        + "".join(venue_terms)
        + ");out center 80;("
        + "".join(context_terms)
        + ");out center 180;"
    )
    data = await get_json(client, "https://overpass-api.de/api/interpreter", method="post", data=query)
    venues, context = [], []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        center_point = element.get("center") or {}
        item_lat = element.get("lat", center_point.get("lat"))
        item_lon = element.get("lon", center_point.get("lon"))
        if item_lat is None or item_lon is None:
            continue
        km = distance_km(lat, lon, item_lat, item_lon)
        name = (
            tags.get("name") or tags.get("sport") or tags.get("leisure")
            or tags.get("tourism") or tags.get("natural") or tags.get("highway")
            or "Mapped outdoor place"
        )
        feature = {
            "id": element.get("id"),
            "name": name,
            "lat": item_lat,
            "lon": item_lon,
            "tags": tags,
        }
        if matches_activity(tags, activity) and km <= radius_km:
            venues.append({**feature, "distance_km": round(km, 1)})
        kind = (
            "road" if tags.get("highway") else
            "industry" if tags.get("landuse") == "industrial" else
            "water" if tags.get("natural") == "water" else
            "green" if tags.get("leisure") in ("park", "garden") else None
        )
        if kind:
            context.append({**feature, "kind": kind})
    unique, seen = [], set()
    for venue in sorted(venues, key=lambda item: item["distance_km"]):
        key = (venue["name"], round(venue["lat"], 4), round(venue["lon"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(venue)
    return unique[:6], context

async def fetch_forecasts(client: httpx.AsyncClient, lat: float, lon: float):
    weather_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index",
        "forecast_days": 7, "timezone": "auto",
    }
    air_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "pm2_5,pm10,us_aqi", "forecast_days": 7, "timezone": "auto",
    }
    weather, air = await asyncio.gather(
        get_json(client, "https://api.open-meteo.com/v1/forecast", weather_params),
        get_json(client, "https://air-quality-api.open-meteo.com/v1/air-quality", air_params),
    )
    return weather, air

def local_context(venue: dict, context: list[dict]) -> list[dict]:
    found = []
    seen = set()
    for feature in context:
        separation = distance_km(venue["lat"], venue["lon"], feature["lat"], feature["lon"])
        feature_id = feature.get("id")
        if separation <= 2 and (feature_id is None or feature_id not in seen):
            if feature_id is not None: seen.add(feature_id)
            found.append({
                "name": feature["name"],
                "kind": feature["kind"],
                "distance_km": round(separation, 2),
                "lat": feature["lat"],
                "lon": feature["lon"],
            })
    return sorted(found, key=lambda item: item["distance_km"])[:30]

def apply_context(option: dict, venue: dict, features: list[dict]) -> dict:
    green = sum(item["kind"] == "green" for item in features)
    roads = [item for item in features if item["kind"] == "road"]
    water = [item for item in features if item["kind"] == "water"]
    industries = [item for item in features if item["kind"] == "industry"]
    wind_from = option["weather"].get("wind_direction_10m")
    upwind = []
    if wind_from is not None:
        for item in industries:
            bearing = bearing_degrees(venue["lat"], venue["lon"], item["lat"], item["lon"])
            angular_gap = abs((bearing - wind_from + 180) % 360 - 180)
            if angular_gap <= 60:
                upwind.append(item)
    closest_road = roads[0]["distance_km"] if roads else None
    green_bonus = min(6, green * 2)
    industry_penalty = min(15, len(upwind) * 5)
    road_penalty = 3 if closest_road is not None and closest_road <= 0.2 else 0
    adjustment = green_bonus - industry_penalty - road_penalty
    base_score = option["score"]
    option["score_components"] = {
        "weather_air_score": base_score,
        "nearby_green_bonus": green_bonus,
        "upwind_industry_penalty": industry_penalty,
        "nearby_road_penalty": road_penalty,
    }
    option["score"] = round(max(0, min(100, base_score + adjustment)))
    option["status"] = status_for(option["score"])
    if green:
        option["reasons"].append(f"{green} mapped green spaces within 2 km.")
    if upwind:
        names = list(dict.fromkeys(item["name"] for item in upwind))
        option["cautions"].append(
            "Mapped industrial land is upwind within 2 km based on forecast wind direction "
            f"({', '.join(names)}); this is contextual only, not a pollution measurement."
        )
    if closest_road is not None and closest_road <= 0.2:
        option["cautions"].append(
            f"A mapped major road is about {closest_road:.1f} km away; traffic volume and exposure are not measured."
        )
    option["geospatial_context"] = {
        "nearby_osm_features": [
            {key: item[key] for key in ("name", "kind", "distance_km", "lat", "lon")}
            for item in features[:12]
        ],
        "green_spaces_mapped": green,
        "roads_mapped": len(roads),
        "industrial_features_mapped": len(industries),
        "water_features_mapped": len(water),
        "wind_direction_degrees_from": wind_from,
        "note": "OSM counts describe mapped features within 2 km. They do not measure traffic or pollution.",
    }
    return option

@app.get("/")
async def home():
    return FileResponse(STATIC)

@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")}

@app.get("/api/activities")
async def activities():
    return {"activities": [{"id": key, "label": value} for key, value in LABELS.items()]}

@app.post("/api/recommend")
async def recommend(request: RecommendRequest):
    parsed = parse_question(request.question)
    activity = request.activity or parsed["activity"]
    place = request.location or parsed["place"]
    radius_km = request.radius_km or parsed["radius_km"]
    personal = request.personal if request.personal is not None else parsed["personal"]
    if activity not in ACTIVITIES:
        raise HTTPException(
            status_code=422,
            detail="Name one activity: running, cycling, golf, cricket, football, tennis, hiking, picnic, outdoor event, or photography.",
        )
    if not place:
        raise HTTPException(status_code=422, detail="Add an area or city, for example 'near Powai, Mumbai'.")
    async with httpx.AsyncClient(timeout=35, headers=HEADERS) as client:
        center = await geocode(client, place)
        try:
            venues, context = await get_places(client, center, radius_km, activity)
            context_available = True
        except HTTPException:
            venues, context, context_available = [], [], False
        area_only = False
        if not venues:
            venues = [{
                "name": center["name"] + " (area forecast)",
                "lat": center["lat"], "lon": center["lon"],
                "distance_km": 0.0, "tags": {},
            }]
            area_only = True

        async def evaluate(venue: dict):
            weather, air = await fetch_forecasts(client, venue["lat"], venue["lon"])
            hourly, air_hourly = weather.get("hourly", {}), air.get("hourly", {})
            times = hourly.get("time", [])
            air_indices = {stamp: index for index, stamp in enumerate(air_hourly.get("time", []))}
            features = local_context(venue, context)
            options = []
            for index in choose_hours(times, parsed["time_hint"], center.get("timezone")):
                wx = {
                    key: (hourly.get(key) or [None] * len(times))[index]
                    for key in (
                        "temperature_2m", "apparent_temperature", "precipitation_probability",
                        "precipitation", "wind_speed_10m", "wind_direction_10m",
                        "wind_gusts_10m", "uv_index",
                    )
                }
                aq_index = air_indices.get(times[index])
                aq = {
                    key: air_hourly[key][aq_index]
                    for key in ("pm2_5", "pm10", "us_aqi")
                    if aq_index is not None and key in air_hourly and aq_index < len(air_hourly[key])
                }
                points, reasons, cautions = score(activity, wx, aq, personal)
                option = {
                    "time": times[index],
                    "score": round(points),
                    "weather": wx,
                    "air_quality": aq,
                    "reasons": reasons,
                    "cautions": cautions,
                }
                options.append(apply_context(option, venue, features))
            if not options:
                return None
            best = max(options, key=lambda item: item["score"])
            weekend_comparison = {}
            if "weekend" in parsed["time_hint"] or ("saturday" in parsed["time_hint"] and "sunday" in parsed["time_hint"]):
                for day in ("Saturday", "Sunday"):
                    day_options = [item for item in options if datetime.fromisoformat(item["time"]).strftime("%A") == day]
                    if day_options:
                        day_best = max(day_options, key=lambda item: item["score"])
                        weekend_comparison[day] = {
                            "time": day_best["time"],
                            "score": day_best["score"],
                            "status": day_best["status"],
                        }
            return {
                "venue": {key: value for key, value in venue.items() if key not in ("tags", "lat", "lon")},
                "coordinates": {"lat": venue["lat"], "lon": venue["lon"]},
                "best_window": best,
                "options_checked": len(options),
                "day_comparison": weekend_comparison,
                "area_forecast_only": area_only,
            }

        evaluated = await asyncio.gather(*(evaluate(venue) for venue in venues[:4]))
        recommendations = sorted(
            (item for item in evaluated if item),
            key=lambda item: item["best_window"]["score"],
            reverse=True,
        )
    if not recommendations:
        raise HTTPException(status_code=502, detail="Forecast sources returned no usable hours for this request.")
    for item in recommendations:
        item["practical_advice"] = advice(activity, personal)
    response = {
        "activity": activity,
        "activity_label": LABELS[activity],
        "location": center,
        "radius_km": radius_km,
        "personal_profile": personal,
        "recommendations": recommendations[:4],
        "data_sources": {
            "weather": "Open-Meteo Forecast API",
            "air_quality": "Open-Meteo Air Quality API (PM2.5, PM10, US AQI)",
            "places_and_context": "OpenStreetMap via Overpass API",
            "geocoding": "Open-Meteo Geocoding API",
        },
        "context_status": "available" if context_available else "Overpass unavailable; recommendations use weather and air-quality data only.",
        "attribution": "© OpenStreetMap contributors",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": os.getenv("MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct"),
    }
    try:
        from app.model import explain
        response["summary"] = await asyncio.to_thread(
            explain,
            request.question,
            {
                "activity": activity,
                "recommendations": recommendations[:3],
                "data_sources": response["data_sources"],
            },
        )
    except Exception as exc:
        response["summary"] = (
            "The recommendation is ranked from the fetched forecast and mapped context. "
            "The local SLM summary was unavailable; use the measurements, status, and cautions below."
        )
        response["model_note"] = f"Local SLM unavailable ({type(exc).__name__}); deterministic ranking still provided."
    return response

