"""Weather tool — wttr.in, no API key required.

Contract (PLAN.md §3.1):
  success -> {city, temp_c, condition, humidity, wind_kph, observed_at}
  failure -> {error: "city_not_found" | "timeout" | "upstream_error"}
"""

import httpx
from langchain_core.tools import tool

TIMEOUT_SECONDS = 8.0
WTTR_URL = "https://wttr.in/{city}?format=j1"


@tool
async def get_weather(city: str) -> dict:
    """Get the current weather for a city.

    Args:
        city: City name, e.g. "Shanghai" or "New York".
    """
    city = (city or "").strip()
    if not city:
        return {"error": "city_not_found"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                WTTR_URL.format(city=city),
                headers={"User-Agent": "agent-tool-assistant/0.1"},
            )
    except httpx.TimeoutException:
        return {"error": "timeout"}
    except httpx.HTTPError:
        return {"error": "upstream_error"}

    if resp.status_code == 404:
        return {"error": "city_not_found"}

    # wttr.in answers unknown locations with 500 + "location not found".
    if resp.status_code != 200:
        if "location not found" in resp.text.lower():
            return {"error": "city_not_found"}
        return {"error": "upstream_error"}

    try:
        payload = resp.json()
    except ValueError:
        return {"error": "upstream_error"}

    if payload.get("error"):
        return {"error": "city_not_found"}

    try:
        current = payload["current_condition"][0]
        area = payload.get("nearest_area", [{}])[0]
        temp_c = float(current["temp_C"])
        humidity = int(current["humidity"])
        wind_kph = float(current["windspeedKmph"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "upstream_error"}

    # areaName is a neighbourhood ("Pootung"); region is the city ("Shanghai").
    resolved_city = city
    for key in ("region", "areaName"):
        values = area.get(key)
        if values and values[0].get("value"):
            resolved_city = values[0]["value"]
            break

    observed_at = current.get("localObsDateTime") or current.get("observation_time", "").strip()

    return {
        "city": resolved_city,
        "temp_c": temp_c,
        "condition": current.get("weatherDesc", [{"value": "unknown"}])[0].get("value", "unknown").strip(),
        "humidity": humidity,
        "wind_kph": wind_kph,
        "observed_at": observed_at or None,
    }
