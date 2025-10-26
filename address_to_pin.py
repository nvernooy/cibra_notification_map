from geopy.geocoders import Nominatim
from time import sleep

geo = Nominatim(user_agent="cibra-app")


def get_coordinates(address):
    """Get gpc cooredinate from a cape town address"""
    address = f"{address}, Cape Town"
    location = geo.geocode(address)
    sleep(1)  # honour rate limits
    if location:
        return {
            "latitude": location.latitude,
            "longitude": location.longitude,
        }

    print(f"ERROR: no coordinates found for {address}")
    return {}
