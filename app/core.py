from __future__ import annotations
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ACTIVITIES = {
    "running": ["run", "running", "jog", "jogging"],
    "cycling": ["cycle", "cycling", "bike", "biking", "commute"],
    "golf": ["golf"],
    "cricket": ["cricket"],
    "football": ["football", "soccer", "five-a-side", "futsal"],
    "tennis": ["tennis"],
    "hiking": ["hike", "hiking", "trek", "nature walk", "walk"],
    "picnic": ["picnic", "park outing"],
    "outdoor_event": ["outdoor event", "gathering", "wedding", "fair", "birthday party"],
    "photography": ["photography", "photos", "photograph", "photo session"],
}
LABELS = {
    "running": "running or jogging", "cycling": "cycling", "golf": "golf",
    "cricket": "cricket", "football": "outdoor football", "tennis": "outdoor tennis",
    "hiking": "hiking or a nature walk", "picnic": "a picnic or park outing",
    "outdoor_event": "an outdoor event or gathering", "photography": "outdoor photography",
}
TAGS = {
    "running": [("leisure", "park"), ("leisure", "track"), ("leisure", "sports_centre")],
    "cycling": [("leisure", "park"), ("route", "bicycle"), ("tourism", "viewpoint")],
    "golf": [("leisure", "golf_course")],
    "cricket": [("sport", "cricket"), ("leisure", "pitch"), ("leisure", "sports_centre")],
    "football": [("sport", "soccer"), ("leisure", "pitch"), ("leisure", "sports_centre")],
    "tennis": [("sport", "tennis"), ("leisure", "pitch"), ("leisure", "sports_centre")],
    "hiking": [("leisure", "nature_reserve"), ("tourism", "viewpoint"), ("highway", "path")],
    "picnic": [("leisure", "park"), ("leisure", "garden"), ("tourism", "picnic_site")],
    "outdoor_event": [("leisure", "park"), ("leisure", "garden"), ("amenity", "events_venue")],
    "photography": [("tourism", "viewpoint"), ("leisure", "park"), ("natural", "water")],
}
DATE_CUTOFF = re.compile(
    r"\b(?:tomorrow|today|tonight|this\s+(?:morning|afternoon|evening|weekend)|"
    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+or\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
    r"(?:\s+(?:morning|afternoon|evening))?|"
    r"in\s+(?:the\s+)?next\s+\w+\s+days?|for\s+the\s+next\s+\w+\s+days?|"
    r"after\s+work|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)|"
    r"within\s+\d+(?:\.\d+)?\s*km)\b",
    re.I,
)

def _clean_place(text: str) -> str | None:
    text = DATE_CUTOFF.split(text, maxsplit=1)[0]
    text = text.strip(" \t\r\n'\".,;:")
    return text or None

def parse_question(text: str) -> dict:
    lower = text.lower()
    activity = next((key for key, terms in ACTIVITIES.items()
                     if any(term in lower for term in terms)), None)
    place = None

    radius_place = re.search(
        r"\bwithin\s+(\d+(?:\.\d+)?)\s*km\s+of\s+(.+?)(?=[?.!;]|$)",
        text, re.I,
    )
    if radius_place:
        place = _clean_place(radius_place.group(2))

    if not place:
        # Prefer the last location preposition, while ignoring phrases like
        # "in the next two days" and "at 8 AM" that describe time.
        matches = list(re.finditer(r"\b(?:near|around|in|at)\s+", text, re.I))
        for match in reversed(matches):
            tail = text[match.end():]
            if re.match(r"(?:the\s+)?next\b", tail, re.I):
                continue
            if re.match(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", tail, re.I):
                continue
            candidate = _clean_place(tail)
            if candidate:
                place = candidate
                break

    radius_match = re.search(r"\b(?:within|radius(?:\s+of)?)\s*(\d+(?:\.\d+)?)\s*km\b", lower)
    personal = {
        "asthma": "asthma" in lower,
        "senior": any(word in lower for word in ("senior", "parents", "elderly", "older adult")),
        "child": any(word in lower for word in ("child", "kids", "children", "toddler")),
        "pregnancy": any(word in lower for word in ("pregnan", "expecting")),
    }
    return {
        "activity": activity,
        "place": place,
        "radius_km": min(50.0, max(2.0, float(radius_match.group(1)))) if radius_match else 12.0,
        "personal": personal,
        "time_hint": lower,
    }

def choose_hours(times: list[str], hint: str, timezone_name: str | None = None) -> list[int]:
    now = datetime.now(ZoneInfo(timezone_name)) if timezone_name else datetime.now()
    target_dates: set[str] = set()
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    mentioned = [day for day in weekdays if re.search(rf"\b{day}\b", hint)]
    if "tomorrow" in hint:
        target_dates.add((now + timedelta(days=1)).date().isoformat())
    elif "today" in hint or "tonight" in hint:
        target_dates.add(now.date().isoformat())
    elif "weekend" in hint or ({"saturday", "sunday"} <= set(mentioned)):
        for offset in range(7):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() >= 5 and day >= now.date():
                target_dates.add(day.isoformat())
    elif mentioned:
        wanted = weekdays[mentioned[0]]
        for offset in range(7):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() == wanted:
                target_dates.add(day.isoformat())
                break
    elif re.search(r"\b(?:in|for) (?:the )?next \w+ days?\b", hint):
        horizon = 48 if "two" in hint or "2 days" in hint else 72
        return [i for i, stamp in enumerate(times[:horizon])
                if stamp >= now.strftime("%Y-%m-%dT%H:%M")]
    else:
        target_dates = {stamp[:10] for stamp in times[:72]}

    selected = []
    for index, stamp in enumerate(times):
        if stamp[:10] == now.date().isoformat() and stamp < now.strftime("%Y-%m-%dT%H:%M"):
            continue
        hour = int(stamp[11:13])
        if stamp[:10] not in target_dates:
            continue
        if "morning" in hint and not 5 <= hour <= 11:
            continue
        if "evening" in hint and not 16 <= hour <= 21:
            continue
        if "afternoon" in hint and not 12 <= hour <= 17:
            continue
        if "sunset" in hint and not 16 <= hour <= 20:
            continue
        if "after work" in hint and not 16 <= hour <= 22:
            continue
        exact_time = re.search(r"\b(\d{1,2})(?::\d{2})?\s*(am|pm)\b", hint)
        if exact_time:
            wanted = int(exact_time.group(1)) % 12 + (12 if exact_time.group(2) == "pm" else 0)
            if hour != wanted:
                continue
        selected.append(index)
    return selected

def score(activity: str, weather: dict, air: dict, personal: dict) -> tuple[float, list[str], list[str]]:
    result, reasons, cautions = 100.0, [], []
    temp = weather.get("temperature_2m")
    rain = weather.get("precipitation_probability")
    wind = weather.get("wind_speed_10m")
    gust = weather.get("wind_gusts_10m")
    pm25 = air.get("pm2_5")
    uv = weather.get("uv_index")
    if temp is None:
        result -= 25
        cautions.append("Temperature data is unavailable for this hour.")
    elif temp > 38:
        result -= 38
        cautions.append("Very hot; avoid strenuous activity during this window.")
    elif temp > 34:
        result -= 25
        cautions.append("High heat; shorten the outing, carry water, and seek shade.")
    elif temp > 30:
        result -= 12
        cautions.append("Warm conditions; carry water and reduce intensity.")
    elif temp < 5:
        result -= 12
        cautions.append("Cold conditions; add a warm layer.")
    else:
        reasons.append(f"Temperature is {temp:.0f}°C")
    if rain is None:
        result -= 15
        cautions.append("Precipitation probability is unavailable for this hour.")
    elif rain >= 80:
        result -= 38
        cautions.append(f"Rain probability is {rain:.0f}%; choose shelter or another time.")
    elif rain >= 55:
        result -= 24
        cautions.append(f"Rain is likely (probability {rain:.0f}%).")
    elif rain >= 35:
        result -= 12
        cautions.append(f"Rain is possible (probability {rain:.0f}%).")
    else:
        reasons.append(f"Rain probability is {rain:.0f}%")
    if wind is None:
        result -= 10
        cautions.append("Wind-speed data is unavailable for this hour.")
    elif gust is not None and gust >= (28 if activity == "cycling" else 35):
        result -= 22
        cautions.append(f"Wind gusts may reach {gust:.0f} km/h.")
    elif wind >= 24:
        result -= 12
        cautions.append(f"Wind is around {wind:.0f} km/h.")
    else:
        reasons.append(f"Wind is {wind:.0f} km/h")
    if pm25 is None:
        result -= 20
        cautions.append("PM2.5 data is unavailable for this hour; the air-quality assessment is incomplete.")
    elif pm25 >= 55.5:
        result -= 42
        cautions.append(f"PM2.5 is {pm25:.1f} µg/m³; consider avoiding strenuous activity.")
    elif pm25 >= 35.5:
        result -= 25
        cautions.append(f"PM2.5 is {pm25:.1f} µg/m³; shorten exertion, especially with respiratory sensitivity.")
    elif pm25 >= 12.1:
        result -= 10
        cautions.append(f"PM2.5 is {pm25:.1f} µg/m³.")
    else:
        reasons.append(f"PM2.5 is {pm25:.1f} µg/m³")
    if personal.get("asthma") and pm25 is not None and pm25 > 12.1:
        result -= 18
        cautions.append("Asthma profile: consider a shorter outing or a lower-particle time.")
    if any(personal.get(flag) for flag in ("senior", "child", "pregnancy")):
        if temp is not None and temp > 30:
            result -= 10
        cautions.append("For a child, older adult, or pregnancy, keep the outing gentle and stop if unwell.")
    if uv is not None and uv >= 6:
        cautions.append(f"UV index is {uv:.0f}; use shade, sunscreen, and a hat.")
    if temp is None or rain is None or wind is None or pm25 is None:
        result = min(result, 64)
    return max(0.0, result), reasons, cautions

def status_for(score_value: float) -> str:
    if score_value < 45:
        return "Avoid this window"
    if score_value < 70:
        return "Use caution"
    return "Favorable conditions"

def advice(activity: str, personal: dict) -> list[str]:
    items = ["Carry water and check conditions again before leaving."]
    if activity in ("running", "cycling", "hiking"):
        items.append("Wear visible clothing and suitable footwear; keep to marked public routes.")
    if activity in ("cricket", "football", "tennis", "golf"):
        items.append("Confirm the facility is open and the playing surface is safe.")
    if activity in ("picnic", "outdoor_event"):
        items.append("Bring sun protection and a rain layer; identify nearby shelter.")
    if activity == "photography":
        items.append("Protect equipment from rain and keep clear of roads and restricted areas.")
    if personal.get("asthma"):
        items.append("Bring prescribed rescue medication and follow your clinician's air-quality advice.")
    return items

