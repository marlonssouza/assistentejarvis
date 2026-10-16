import json
import unittest
from unittest.mock import patch

from jarvis import weather


class WeatherTests(unittest.TestCase):
    def test_wmo_mapping(self):
        self.assertEqual(weather._wmo_to_pt(0), "céu limpo")
        self.assertEqual(weather._wmo_to_pt(61), "chuva leve")
        self.assertEqual(weather._wmo_to_pt(None), "condição desconhecida")

    def test_all_sources_failing_returns_error_json(self):
        with (
            patch.object(weather, "OPENWEATHER_API_KEY", "fake"),
            patch.object(weather, "_weather_openweather", return_value=None),
            patch.object(weather, "_weather_openmeteo", return_value=None),
            patch.object(weather, "_weather_wttr", return_value=None),
            patch.object(weather, "_get_city_coords", return_value=None),
        ):
            data = json.loads(weather.get_weather("Cidade Inexistente"))
        self.assertIn("error", data)

    def test_openweather_is_preferred(self):
        payload = {"source": "openweather", "temp": 20}
        with (
            patch.object(weather, "OPENWEATHER_API_KEY", "fake"),
            patch.object(weather, "_weather_openweather", return_value=payload),
            patch.object(weather, "_weather_openmeteo") as om,
            patch.object(weather, "_weather_wttr") as wt,
        ):
            data = json.loads(weather.get_weather("São Paulo"))
        self.assertEqual(data["source"], "openweather")
        om.assert_not_called()
        wt.assert_not_called()

    def test_falls_back_to_openmeteo_when_no_key(self):
        payload = {"source": "openmeteo", "temp": 18}
        with (
            patch.object(weather, "OPENWEATHER_API_KEY", ""),
            patch.object(weather, "_weather_openmeteo", return_value=payload) as om,
            patch.object(weather, "_weather_wttr") as wt,
            patch.object(
                weather,
                "_get_city_coords",
                return_value={"lat": -23.5, "lon": -46.6, "name": "São Paulo"},
            ),
        ):
            data = json.loads(weather.get_weather("São Paulo"))
        self.assertEqual(data["source"], "openmeteo")
        om.assert_called_once()
        wt.assert_not_called()

    def test_falls_back_to_wttr_last(self):
        payload = {"source": "wttr", "temp": 17}
        with (
            patch.object(weather, "OPENWEATHER_API_KEY", ""),
            patch.object(weather, "_weather_openmeteo", return_value=None),
            patch.object(weather, "_weather_wttr", return_value=payload),
            patch.object(weather, "_get_city_coords", return_value=None),
        ):
            data = json.loads(weather.get_weather("Qualquer"))
        self.assertEqual(data["source"], "wttr")


if __name__ == "__main__":
    unittest.main()
