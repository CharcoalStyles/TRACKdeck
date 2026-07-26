from typing import Optional

from langchain_core.tools import tool
import requests
import json
import logging

from agent.settings import settings

logger = logging.getLogger(__name__)

def call_open_meteo_search(location: str) -> dict:
    """Call the Open-Meteo API and return the response."""

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=en&format=json"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()

def call_open_meteo_forecast(latitude: float, longitude: float, params: dict) -> dict:
    """Call the Open-Meteo API and return the response."""
    # Open-Meteo: free, no API key needed



    response = requests.get(f"https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
    logger.debug("Open-Meteo request URL: %s", response.url)
    response.raise_for_status()
    return response.json()

def fetch_current_conditions(location: str) -> Optional[dict]:
    """Shared by get_current_weather (LLM tool, formats to a string) and
    jobs/device_sync.py's build_sync_payload (needs structured fields).
    Returns None if the location can't be resolved or Open-Meteo fails —
    callers must handle that gracefully rather than treating it as fatal."""
    try:
        location_data = call_open_meteo_search(location)
        if len(location_data["results"]) == 0:
            return None

        latitude = location_data["results"][0]['latitude']
        longitude = location_data["results"][0]['longitude']

        params = {
            'latitude': latitude,
            'longitude': longitude,
            'current': 'temperature_2m,cloudcover,precipitation',
            'format': 'json',
        }

        data = call_open_meteo_forecast(latitude, longitude, params)

        if "error" in data:
            return None

        return {
            "temperature_c": data["current"]["temperature_2m"],
            "cloud_cover_pct": data["current"]["cloudcover"],
            "precipitation_mm": data["current"]["precipitation"],
        }

    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to Open-Meteo: %s", e)
        return None


@tool
def get_current_weather(location: Optional[str] = None) -> str:
    """Get the current weather.

    Args:
        location: City or suburb. If not provided, uses the user's configured default location.

    Returns:
        A string containing the current weather in the specified location.
    """
    loc = location or settings.default_location
    logger.info("Fetching weather for: %s", loc)

    conditions = fetch_current_conditions(loc)
    if conditions is None:
        return f"Weather for {loc}: No results found."

    return (
        f"Weather for {loc}: {conditions['temperature_c']}°C, "
        f"{conditions['cloud_cover_pct']}% cloud cover, "
        f"{conditions['precipitation_mm']}mm precipitation."
    )

@tool
def get_weather_forecast(location: Optional[str] = None) -> str:
    """Get the forecast weather for the next 7 days.

    Args:
        location: City or suburb. If not provided, uses the user's configured default location.

    Returns:
        A list of dictionaries containing the forecast for the next 7 days.
    """

    loc = location or settings.default_location
    logger.info("Fetching weather for: %s", loc)

    try:
        location_data = call_open_meteo_search(loc)
        if len(location_data["results"]) == 0:
            return f"Weather for {loc}: No results found."

        logger.debug("Found location: %s", location_data['results'])

        latitude = location_data["results"][0]['latitude']
        longitude = location_data["results"][0]['longitude']

        # Open-Meteo: free, no API key needed
        # Define API parameters
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'forecast_days': 7,
            'daily': 'temperature_2m_min,temperature_2m_max,precipitation_probability_min,precipitation_probability_max',
            'format': 'json',  # Requests JSON response format
        }

        data = call_open_meteo_forecast(latitude, longitude, params)

        if "error" in data:
            return f"Weather for {loc}: {data['error']}"
        
        forecast = []
        num_days = len(data["daily"]["time"])
        for i in range(num_days):
            day = {
                "time": data["daily"]["time"][i],
                "temperature_2m_min": data["daily"]["temperature_2m_min"][i],
                "temperature_2m_max": data["daily"]["temperature_2m_max"][i],
                "precipitation_probability_min": data["daily"]["precipitation_probability_min"][i],
                "precipitation_probability_max": data["daily"]["precipitation_probability_max"][i],
            }
            forecast.append(day)

        return json.dumps(forecast)

    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to Open-Meteo: %s", e)
        return f"Weather for {loc}: No results found."

@tool
def get_range_forecast(start: str, end: str, location: Optional[str] = None) -> str:
    """Get the forecast weather for a range of days.

    Args:
        start: Start date in ISO format (e.g., "2023-01-01")
        end: End date in ISO format (e.g., "2023-01-05")
        location: City or suburb. If not provided, uses the user's configured default location.

    Returns:
        A list of dictionaries containing the forecast for the specified range of days.
    """

    loc = location or settings.default_location
    logger.info("Fetching weather for: %s", loc)

    try:
        location_data = call_open_meteo_search(loc)
        if len(location_data["results"]) == 0:
            return f"Weather for {loc}: No results found."

        logger.debug("Found location: %s", location_data['results'])

        latitude = location_data["results"][0]['latitude']
        longitude = location_data["results"][0]['longitude']

        # Open-Meteo: free, no API key needed
        # Define API parameters
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'start_date': start,
            'end_date': end,
            'daily': 'temperature_2m_min,temperature_2m_max,precipitation_probability_min,precipitation_probability_max',
            'format': 'json',  # Requests JSON response format
        }

        data = call_open_meteo_forecast(latitude, longitude, params)

        if "error" in data:
            return f"Weather for {loc}: {data['error']}"
        
        forecast = []
        num_days = len(data["daily"]["time"])
        for i in range(num_days):
            day = {
                "time": data["daily"]["time"][i],
                "temperature_2m_min": data["daily"]["temperature_2m_min"][i],
                "temperature_2m_max": data["daily"]["temperature_2m_max"][i],
                "precipitation_probability_min": data["daily"]["precipitation_probability_min"][i],
                "precipitation_probability_max": data["daily"]["precipitation_probability_max"][i],
            }
            forecast.append(day)

        return json.dumps(forecast)

    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to Open-Meteo: %s", e)
        return f"Weather for {loc}: No results found."
    

def get_tools():
    return [
        get_current_weather,
        get_weather_forecast,
        get_range_forecast,
    ]