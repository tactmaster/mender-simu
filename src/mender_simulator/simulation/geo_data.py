"""Land-based geo location data for simulated device inventory.

Provides a curated list of real city coordinates (guaranteed to be on land)
used to populate geo-lat/geo-lon/geo-city/geo-country/geo-timezone inventory
attributes on simulated devices, matching the attribute names real Mender
devices report.
"""

import random

# (city, country_code, lat, lon, IANA timezone) -- spans every inhabited
# continent so simulated devices spread out across the world map rather than
# clustering in one place.
LAND_CITIES = [
    ("Stockholm", "SE", 59.3293, 18.0686, "Europe/Stockholm"),
    ("Gothenburg", "SE", 57.7089, 11.9746, "Europe/Stockholm"),
    ("Oslo", "NO", 59.9139, 10.7522, "Europe/Oslo"),
    ("Copenhagen", "DK", 55.6761, 12.5683, "Europe/Copenhagen"),
    ("Helsinki", "FI", 60.1699, 24.9384, "Europe/Helsinki"),
    ("London", "GB", 51.5074, -0.1278, "Europe/London"),
    ("Manchester", "GB", 53.4808, -2.2426, "Europe/London"),
    ("Dublin", "IE", 53.3498, -6.2603, "Europe/Dublin"),
    ("Paris", "FR", 48.8566, 2.3522, "Europe/Paris"),
    ("Lyon", "FR", 45.7640, 4.8357, "Europe/Paris"),
    ("Berlin", "DE", 52.5200, 13.4050, "Europe/Berlin"),
    ("Munich", "DE", 48.1351, 11.5820, "Europe/Berlin"),
    ("Hamburg", "DE", 53.5511, 9.9937, "Europe/Berlin"),
    ("Amsterdam", "NL", 52.3676, 4.9041, "Europe/Amsterdam"),
    ("Brussels", "BE", 50.8503, 4.3517, "Europe/Brussels"),
    ("Zurich", "CH", 47.3769, 8.5417, "Europe/Zurich"),
    ("Vienna", "AT", 48.2082, 16.3738, "Europe/Vienna"),
    ("Madrid", "ES", 40.4168, -3.7038, "Europe/Madrid"),
    ("Barcelona", "ES", 41.3851, 2.1734, "Europe/Madrid"),
    ("Lisbon", "PT", 38.7223, -9.1393, "Europe/Lisbon"),
    ("Rome", "IT", 41.9028, 12.4964, "Europe/Rome"),
    ("Milan", "IT", 45.4642, 9.1900, "Europe/Rome"),
    ("Warsaw", "PL", 52.2297, 21.0122, "Europe/Warsaw"),
    ("Prague", "CZ", 50.0755, 14.4378, "Europe/Prague"),
    ("Budapest", "HU", 47.4979, 19.0402, "Europe/Budapest"),
    ("Athens", "GR", 37.9838, 23.7275, "Europe/Athens"),
    ("Bucharest", "RO", 44.4268, 26.1025, "Europe/Bucharest"),
    ("Reykjavik", "IS", 64.1466, -21.9426, "Atlantic/Reykjavik"),
    ("Moscow", "RU", 55.7558, 37.6173, "Europe/Moscow"),
    ("Istanbul", "TR", 41.0082, 28.9784, "Europe/Istanbul"),
    ("New York", "US", 40.7128, -74.0060, "America/New_York"),
    ("Chicago", "US", 41.8781, -87.6298, "America/Chicago"),
    ("Los Angeles", "US", 34.0522, -118.2437, "America/Los_Angeles"),
    ("San Francisco", "US", 37.7749, -122.4194, "America/Los_Angeles"),
    ("Seattle", "US", 47.6062, -122.3321, "America/Los_Angeles"),
    ("Austin", "US", 30.2672, -97.7431, "America/Chicago"),
    ("Denver", "US", 39.7392, -104.9903, "America/Denver"),
    ("Miami", "US", 25.7617, -80.1918, "America/New_York"),
    ("Toronto", "CA", 43.6532, -79.3832, "America/Toronto"),
    ("Vancouver", "CA", 49.2827, -123.1207, "America/Vancouver"),
    ("Montreal", "CA", 45.5019, -73.5674, "America/Toronto"),
    ("Mexico City", "MX", 19.4326, -99.1332, "America/Mexico_City"),
    ("Sao Paulo", "BR", -23.5505, -46.6333, "America/Sao_Paulo"),
    ("Rio de Janeiro", "BR", -22.9068, -43.1729, "America/Sao_Paulo"),
    ("Buenos Aires", "AR", -34.6037, -58.3816, "America/Argentina/Buenos_Aires"),
    ("Santiago", "CL", -33.4489, -70.6693, "America/Santiago"),
    ("Bogota", "CO", 4.7110, -74.0721, "America/Bogota"),
    ("Lima", "PE", -12.0464, -77.0428, "America/Lima"),
    ("Cairo", "EG", 30.0444, 31.2357, "Africa/Cairo"),
    ("Lagos", "NG", 6.5244, 3.3792, "Africa/Lagos"),
    ("Nairobi", "KE", -1.2921, 36.8219, "Africa/Nairobi"),
    ("Johannesburg", "ZA", -26.2041, 28.0473, "Africa/Johannesburg"),
    ("Cape Town", "ZA", -33.9249, 18.4241, "Africa/Johannesburg"),
    ("Casablanca", "MA", 33.5731, -7.5898, "Africa/Casablanca"),
    ("Accra", "GH", 5.6037, -0.1870, "Africa/Accra"),
    ("Addis Ababa", "ET", 9.0300, 38.7400, "Africa/Addis_Ababa"),
    ("Dubai", "AE", 25.2048, 55.2708, "Asia/Dubai"),
    ("Riyadh", "SA", 24.7136, 46.6753, "Asia/Riyadh"),
    ("Tel Aviv", "IL", 32.0853, 34.7818, "Asia/Jerusalem"),
    ("Mumbai", "IN", 19.0760, 72.8777, "Asia/Kolkata"),
    ("Delhi", "IN", 28.7041, 77.1025, "Asia/Kolkata"),
    ("Bengaluru", "IN", 12.9716, 77.5946, "Asia/Kolkata"),
    ("Karachi", "PK", 24.8607, 67.0011, "Asia/Karachi"),
    ("Dhaka", "BD", 23.8103, 90.4125, "Asia/Dhaka"),
    ("Bangkok", "TH", 13.7563, 100.5018, "Asia/Bangkok"),
    ("Singapore", "SG", 1.3521, 103.8198, "Asia/Singapore"),
    ("Kuala Lumpur", "MY", 3.1390, 101.6869, "Asia/Kuala_Lumpur"),
    ("Jakarta", "ID", -6.2088, 106.8456, "Asia/Jakarta"),
    ("Manila", "PH", 14.5995, 120.9842, "Asia/Manila"),
    ("Hanoi", "VN", 21.0285, 105.8542, "Asia/Ho_Chi_Minh"),
    ("Ho Chi Minh City", "VN", 10.8231, 106.6297, "Asia/Ho_Chi_Minh"),
    ("Hong Kong", "HK", 22.3193, 114.1694, "Asia/Hong_Kong"),
    ("Shanghai", "CN", 31.2304, 121.4737, "Asia/Shanghai"),
    ("Beijing", "CN", 39.9042, 116.4074, "Asia/Shanghai"),
    ("Shenzhen", "CN", 22.5431, 114.0579, "Asia/Shanghai"),
    ("Seoul", "KR", 37.5665, 126.9780, "Asia/Seoul"),
    ("Tokyo", "JP", 35.6762, 139.6503, "Asia/Tokyo"),
    ("Osaka", "JP", 34.6937, 135.5023, "Asia/Tokyo"),
    ("Sydney", "AU", -33.8688, 151.2093, "Australia/Sydney"),
    ("Melbourne", "AU", -37.8136, 144.9631, "Australia/Melbourne"),
    ("Brisbane", "AU", -27.4698, 153.0251, "Australia/Brisbane"),
    ("Perth", "AU", -31.9505, 115.8605, "Australia/Perth"),
    ("Auckland", "NZ", -36.8485, 174.7633, "Pacific/Auckland"),
]


def random_land_location(jitter_degrees: float = 0.05) -> dict:
    """Return a dict of geo-* inventory attributes for a randomly chosen real city.

    A small random jitter is applied so devices assigned the same city don't
    stack exactly on top of each other on the map. The jitter is kept small
    enough that it stays within the same city/urban area (roughly +/-5km for
    the default 0.05 degrees), so it does not risk landing in water.
    """
    city, country, lat, lon, tz = random.choice(LAND_CITIES)
    lat += random.uniform(-jitter_degrees, jitter_degrees)
    lon += random.uniform(-jitter_degrees, jitter_degrees)
    return {
        "geo-city": city,
        "geo-country": country,
        "geo-lat": f"{lat:.4f}",
        "geo-lon": f"{lon:.4f}",
        "geo-timezone": tz,
    }
