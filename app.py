from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

# -------------------------
# API Keys
# -------------------------

FOURSQUARE_API_KEY = os.environ.get("FOURSQUARE_API_KEY")
ORS_API_KEY = os.environ.get("ORS_API_KEY")


# -------------------------
# Isochrone generator (ORS)
# -------------------------
def get_isochrone(lat, lon, api_key=ORS_API_KEY, range_meters=1000):
    """Generate isochrone polygon from OpenRouteService"""
    if not api_key or api_key.startswith("YOUR_"):
        return None  # Skip if no key provided
    url = "https://api.openrouteservice.org/v2/isochrones/driving-car"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {
        "locations": [[lon, lat]],   # ORS expects [lon, lat]
        "range": [range_meters]
    }

    resp = requests.post(url, headers=headers, json=body)
    if resp.status_code == 200:
        return resp.json()
    else:
        print("ORS error:", resp.status_code, resp.text)
        return None

# -------------------------
# Foursquare API helper
# -------------------------
class FoursquarePlaces:
    def __init__(self, api_key, api_version="2025-06-17", base_url="https://places-api.foursquare.com/places"):
        self.api_key = api_key
        self.api_version = api_version
        self.base_url = base_url
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-Places-Api-Version": self.api_version
        }

    def search_places(self, query, latitude, longitude, radius=1000, limit=5):
        """Search Foursquare places near a point (lat/lon)"""
        url = f"{self.base_url}/search"
        params = {
            "query": query,
            "ll": f"{latitude},{longitude}",  # Foursquare expects lat,lon
            "radius": radius,
            "limit": limit
        }
        resp = requests.get(url, headers=self.headers, params=params)
        if resp.status_code != 200:
            print("Foursquare error:", resp.status_code, resp.text)
            return []
        results = resp.json().get("results", [])
        venues = []
        for place in results:
            venues.append({
                "name": place.get("name", "Unknown"),
                "address": (
                    place.get("location", {}).get("formatted_address")
                    or place.get("location", {}).get("address", "No address")
                ),
                "category": place.get("categories", [{}])[0].get("name", "Uncategorized")
            })
        return venues

# -------------------------
# Flask App
# -------------------------
app = Flask(__name__)
CORS(app)

fs = FoursquarePlaces(FOURSQUARE_API_KEY)

@app.route("/")
def home():
    return {"message": "GeoMeet Backend is running 🚀"}

@app.route("/api/venues", methods=["POST"])
def get_venues():
    data = request.get_json()
    query = data.get("query", "hospital")
    radius = int(data.get("radius", 1000))
    locations = data.get("locations", [])

    all_results = []

    for loc in locations:
        if len(loc) != 2:
            continue
        lat, lon = loc

        # 1️⃣ Generate Isochrone (optional use)
        isochrone = get_isochrone(lat, lon, range_meters=radius)
        if isochrone:
            print(f"Isochrone generated for [{lon}, {lat}]")

        # 2️⃣ Search Foursquare venues inside radius
        results = fs.search_places(query, lat, lon, radius=radius, limit=5)
        all_results.extend(results)

    # ✅ Deduplicate venues by name+address
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r["name"], r["address"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    return jsonify(unique_results)

if __name__ == "__main__":
    # IMPORTANT: For deployment use Gunicorn, not app.run()
    app.run(host="0.0.0.0", port=5000, debug=True)

