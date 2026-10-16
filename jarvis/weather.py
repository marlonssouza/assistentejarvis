import json
import logging
from typing import Any, Dict, Optional

import httpx

from .config import OPENWEATHER_API_KEY

logger = logging.getLogger(__name__)

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WTTR_URL = "https://wttr.in"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _get_city_coords(city: str) -> Optional[Dict[str, float]]:
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(GEOCODING_URL, params={"name": city, "count": 1, "language": "pt"})
            r.raise_for_status()
            data = r.json()
            results = data.get("results") or []
            if results:
                res = results[0]
                return {
                    "lat": float(res["latitude"]),
                    "lon": float(res["longitude"]),
                    "name": res.get("name"),
                    "country": res.get("country"),
                }
    except Exception as e:
        logger.debug("geocoding failed: %s", e)
    return None


def _weather_openweather(city: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if not OPENWEATHER_API_KEY:
        return None
    try:
        params: Dict[str, Any] = {"appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "pt_br"}
        if lat is not None and lon is not None:
            params["lat"] = lat
            params["lon"] = lon
        elif city:
            params["q"] = city
        else:
            return None
        with httpx.Client(timeout=10.0) as client:
            r = client.get(OPENWEATHER_URL, params=params)
            r.raise_for_status()
            d = r.json()
            return {
                "source": "openweather",
                "city": d.get("name"),
                "country": (d.get("sys") or {}).get("country"),
                "temp": d.get("main", {}).get("temp"),
                "feels_like": d.get("main", {}).get("feels_like"),
                "humidity": d.get("main", {}).get("humidity"),
                "pressure": d.get("main", {}).get("pressure"),
                "wind_speed": d.get("wind", {}).get("speed"),
                "description": ((d.get("weather") or [{}])[0]).get("description"),
                "icon": ((d.get("weather") or [{}])[0]).get("icon"),
            }
    except Exception as e:
        logger.debug("openweather failed: %s", e)
    return None


def _weather_openmeteo(lat: float, lon: float, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ["temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,pressure_msl"],
            "daily": ["weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"],
            "timezone": "auto",
            "forecast_days": 3,
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.get(OPENMETEO_URL, params=params)
            r.raise_for_status()
            d = r.json()
            current = d.get("current") or {}
            daily = d.get("daily") or {}
            return {
                "source": "openmeteo",
                "city": name,
                "temp": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "pressure": current.get("pressure_msl"),
                "wind_speed": current.get("wind_speed_10m"),
                "description": _wmo_to_pt(current.get("weather_code")),
                "daily": {
                    "days": daily.get("time"),
                    "temp_max": daily.get("temperature_2m_max"),
                    "temp_min": daily.get("temperature_2m_min"),
                    "precip_sum": daily.get("precipitation_sum"),
                    "codes": daily.get("weather_code"),
                },
            }
    except Exception as e:
        logger.debug("openmeteo failed: %s", e)
    return None


def _wmo_to_pt(code: Any) -> str:
    mapping = {
        0: "céu limpo",
        1: "principalmente limpo",
        2: "parcialmente nublado",
        3: "nublado",
        45: "nevoeiro",
        48: "nevoeiro com geada",
        51: "chuvisco leve",
        53: "chuvisco moderado",
        55: "chuvisco denso",
        61: "chuva leve",
        63: "chuva moderada",
        65: "chuva forte",
        71: "neve leve",
        73: "neve moderada",
        75: "neve forte",
        80: "pancadas de chuva leves",
        81: "pancadas moderadas",
        82: "pancadas fortes",
        95: "trovoada",
        96: "trovoada com granizo leve",
        99: "trovoada com granizo forte",
    }
    try:
        c = int(code) if code is not None else -1
    except Exception:
        c = -1
    return mapping.get(c, "condição desconhecida")


def _weather_wttr(city: Optional[str] = "auto") -> Optional[Dict[str, Any]]:
    try:
        q = city or "auto"
        url = f"{WTTR_URL}/{q}?format=j1"
        with httpx.Client(timeout=10.0, headers={"User-Agent": "curl/8.0.1"}) as client:
            r = client.get(url)
            r.raise_for_status()
            d = r.json()
            current = (d.get("current_condition") or [{}])[0]
            return {
                "source": "wttr",
                "city": ((d.get("nearest_area") or [{}])[0]).get("areaName", [{}])[0].get("value"),
                "temp": current.get("temp_C"),
                "feels_like": current.get("FeelsLikeC"),
                "humidity": current.get("humidity"),
                "pressure": current.get("pressure"),
                "wind_speed": current.get("windspeedKmph"),
                "description": current.get("weatherDesc", [{}])[0].get("value"),
            }
    except Exception as e:
        logger.debug("wttr failed: %s", e)
    return None


def get_weather(city: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    """Obtém clima atual com fallbacks resilientes (OpenWeather → Open-Meteo → wttr.in)."""
    result = None

    if OPENWEATHER_API_KEY:
        result = _weather_openweather(city=city, lat=lat, lon=lon)

    if not result and lat is not None and lon is not None:
        name = None
        if city:
            name = city
        result = _weather_openmeteo(lat, lon, name=name)

    if not result and city:
        coords = _get_city_coords(city)
        if coords:
            result = _weather_openmeteo(coords["lat"], coords["lon"], name=coords.get("name") or city)

    if not result:
        result = _weather_wttr(city=city or "auto")

    if not result:
        return json.dumps({"error": "Não foi possível obter dados meteorológicos."}, ensure_ascii=False)

    payload = result
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return _truncate(str(payload), 4000)