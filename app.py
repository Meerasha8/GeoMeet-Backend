from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import uuid, time, os

# -------------------------
# API Keys (from environment variables)
# -------------------------
FOURSQUARE_API_KEY = os.getenv("FOURSQUARE_API_KEY", "")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")

# -------------------------
# Isochrone generator (ORS)
# -------------------------
def get_isochrone(lat, lon, api_key=ORS_API_KEY, range_meters=1000):
    """Generate isochrone polygon from OpenRouteService"""
    if not api_key:
        return None
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
        if not self.api_key:
            return []

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
# Flask App Setup
# -------------------------
app = Flask(__name__)
CORS(app)

fs = FoursquarePlaces(FOURSQUARE_API_KEY)

# -------------------------
# Room Management (in-memory)
# -------------------------
rooms = {}

@app.route("/api/rooms", methods=["POST"])
def create_room():
    try:
        room_id = str(uuid.uuid4())[:6]  # short ID
        password = request.json.get("password", "")
        rooms[room_id] = {
            "password": password,
            "members": {},
        }
        return jsonify({"roomId": room_id})
    except Exception as e:
        print("Error creating room:", str(e))
        return jsonify({"error": "Backend error creating room"}), 500

@app.route("/api/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id):
    data = request.json
    client_id = data.get("clientId")
    name = data.get("name")
    password = data.get("password", "")

    if room_id not in rooms:
        return jsonify({"error": "Room not found"}), 404

    if rooms[room_id]["password"] and rooms[room_id]["password"] != password:
        return jsonify({"error": "Invalid password"}), 403

    rooms[room_id]["members"][client_id] = {
        "name": name,
        "lat": None,
        "lon": None,
        "timestamp": None
    }
    return jsonify({"status": "joined"})

@app.route("/api/rooms/<room_id>/locations", methods=["POST"])
def push_location(room_id):
    data = request.json
    client_id = data.get("clientId")
    if room_id not in rooms or client_id not in rooms[room_id]["members"]:
        return jsonify({"error": "Room/member not found"}), 404

    rooms[room_id]["members"][client_id].update({
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "timestamp": time.time()
    })
    return jsonify({"status": "location updated"})

@app.route("/api/rooms/<room_id>/locations", methods=["GET"])
def get_locations(room_id):
    if room_id not in rooms:
        return jsonify({"error": "Room not found"}), 404

    members = [
        {"clientId": cid, **info}
        for cid, info in rooms[room_id]["members"].items()
    ]
    return jsonify({"members": members})

# -------------------------
# Venue Search (Foursquare + ORS)
# -------------------------
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

        # Isochrone (optional)
        isochrone = get_isochrone(lat, lon, range_meters=radius)
        if isochrone:
            print(f"Isochrone generated for [{lon}, {lat}]")

        # Search Foursquare venues
        results = fs.search_places(query, lat, lon, radius=radius, limit=5)
        all_results.extend(results)

    # Deduplicate venues by name+address
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r["name"], r["address"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    return jsonify(unique_results)

# -------------------------
# Run Server
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
