"""天气工具 —— wttr.in，无需 API key。

对应 PLAN.md §3.1 的契约：
  成功 -> {city, temp_c, condition, humidity, wind_kph, observed_at}
  失败 -> {error: "city_not_found" | "timeout" | "upstream_error"}

本文件全程不抛异常，任何失败都转成 {"error": "..."} 返回给上层。
"""

import httpx
from langchain_core.tools import tool

#: 单次请求超时时间（秒）。wttr.in 偶尔会慢，8 秒是权衡值。
TIMEOUT_SECONDS = 8.0

#: wttr.in 的接口地址，{city} 会被替换成城市名。
WTTR_URL = "https://wttr.in/{city}?format=j1"


@tool
async def get_weather(city: str) -> dict:
    """查询某个城市的当前天气。

    Args:
        city: 城市名，例如 "Shanghai" 或 "New York"。
    """
    city = (city or "").strip()
    if not city:
        return {"error": "city_not_found"}

    # 用 httpx 的异步客户端，因为这个工具是 async def，LangGraph 会并发调用它
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

    # wttr.in 的坑：查不到的城市返回的是 500 而不是 404，
    # 而且响应体是一句纯文本 "location not found"，没法按 JSON 解析。
    # 所以只能靠响应体的内容来判断。
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

    # current_condition[0] 是当前观测；nearest_area[0] 是命中的地点信息
    try:
        current = payload["current_condition"][0]
        area = payload.get("nearest_area", [{}])[0]
        temp_c = float(current["temp_C"])
        humidity = int(current["humidity"])
        wind_kph = float(current["windspeedKmph"])
    except (KeyError, IndexError, TypeError, ValueError):
        # 上游改了字段结构
        return {"error": "upstream_error"}

    # 另一个坑：areaName 是街区名不是城市名。
    # 查 "Shanghai" 会返回 "Pootung"（浦东），所以优先取 region（"Shanghai"）。
    resolved_city = city
    for key in ("region", "areaName"):
        values = area.get(key)
        if values and values[0].get("value"):
            resolved_city = values[0]["value"]
            break

    # 观测时间优先用本地时间，没有再退回 UTC 观测时间
    observed_at = current.get("localObsDateTime") or current.get("observation_time", "").strip()

    return {
        "city": resolved_city,
        "temp_c": temp_c,
        # 上游的 weatherDesc 结尾常带空格，strip 掉
        "condition": current.get("weatherDesc", [{"value": "unknown"}])[0].get("value", "unknown").strip(),
        "humidity": humidity,
        "wind_kph": wind_kph,
        "observed_at": observed_at or None,
    }
