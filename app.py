from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import uuid
import time
import os
import logging

# -------------------------
# Configuration
# -------------------------
FOURSQUARE_API_KEY = os.getenv("FOURSQUARE_API_KEY", "")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")

if not FOURSQUARE_API_KEY:
    print("⚠️ Warning: FOURSQUARE_API_KEY not set.")
if not ORS_API_KEY:
    print("⚠️ Warning: ORS_API_KEY not set.")

# -------------------------
# Flask Setup
# -------------------------
app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)

# -------------------------
# Isochrone Generator (ORS)
# -------------------------
def get_isochrone(lat, lon, api_key=ORS_API_KEY, range_meters=1000):
    """Generate isochrone polygon from OpenRouteService"""
    if not api_key:
        return None
    try:
        url = "https://api.openrouteservice.org/v2/isochrones/driving-car"
        headers = {"Authorization": api_key, "Content-Type": "application/json"}
        body = {"locations": [[lon, lat]], "range": [range_meters]}

        resp = requests.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logging.error(f"ORS error: {e}")
        return None

# -------------------------
# Foursquare API Wrapper
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
        if not self.api_key:
            return []

        try:
            url = f"{self.base_url}/search"
            params = {
                "query": query,
                "ll": f"{latitude},{longitude}",  # Foursquare expects lat,lon
                "radius": radius,
                "limit": limit
            }
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()
            results = resp.json().get("results", [])

            return [
                {
                    "name": place.get("name", "Unknown"),
                    "address": (
                        place.get("location", {}).get("formatted_address")
                        or place.get("location", {}).get("address", "No address")
                    ),
                    "category": place.get("categories", [{}])[0].get("name", "Uncategorized")
                }
                for place in results
            ]
        except requests.RequestException as e:
            logging.error(f"Foursquare error: {e}")
            return []

# -------------------------
# Room Management (in-memory)
# -------------------------
rooms = {}
fs = FoursquarePlaces(FOURSQUARE_API_KEY)

@app.route("/api/rooms", methods=["POST"])
def create_room():
    try:
        data = request.json or {}
        password = data.get("password", "")
        room_id = str(uuid.uuid4())[:6]

        rooms[room_id] = {"password": password, "members": {}}
        logging.info(f"Room created: {room_id}")

        return jsonify({"roomId": room_id})
    except Exception as e:
        logging.exception("Error creating room")
        return jsonify({"error": "Backend error creating room"}), 500

@app.route("/api/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id):
    try:
        data = request.json or {}
        client_id = data.get("clientId")
        name = data.get("name")
        password = data.get("password", "")

        if not client_id or not name:
            return jsonify({"error": "Missing clientId or name"}), 400
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
        logging.info(f"{name} joined room {room_id}")

        return jsonify({"status": "joined"})
    except Exception as e:
        logging.exception("Error joining room")
        return jsonify({"error": "Backend error joining room"}), 500

@app.route("/api/rooms/<room_id>/locations", methods=["POST"])
def push_location(room_id):
    try:
        data = request.json or {}
        client_id = data.get("clientId")

        if room_id not in rooms or client_id not in rooms[room_id]["members"]:
            return jsonify({"error": "Room/member not found"}), 404

        rooms[room_id]["members"][client_id].update({
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "timestamp": time.time()
        })
        return jsonify({"status": "location updated"})
    except Exception as e:
        logging.exception("Error updating location")
        return jsonify({"error": "Backend error updating location"}), 500

@app.route("/api/rooms/<room_id>/locations", methods=["GET"])
def get_locations(room_id):
    try:
        if room_id not in rooms:
            return jsonify({"error": "Room not found"}), 404

        members = [
            {"clientId": cid, **info}
            for cid, info in rooms[room_id]["members"].items()
        ]
        return jsonify({"members": members})
    except Exception as e:
        logging.exception("Error fetching locations")
        return jsonify({"error": "Backend error fetching locations"}), 500

@app.route("/api/venues", methods=["POST"])
def get_venues():
    try:
        data = request.get_json() or {}
        query = data.get("query", "hospital")
        radius = int(data.get("radius", 1000))
        locations = data.get("locations", [])

        all_results = []
        for loc in locations:
            if len(loc) != 2:
                continue
            lat, lon = loc

            isochrone = get_isochrone(lat, lon, range_meters=radius)
            if isochrone:
                logging.info(f"Isochrone generated for {lat}, {lon}")

            results = fs.search_places(query, lat, lon, radius=radius, limit=5)
            all_results.extend(results)

        # Deduplicate venues
        seen, unique_results = set(), []
        for r in all_results:
            key = (r["name"], r["address"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        return jsonify(unique_results)
    except Exception as e:
        logging.exception("Error fetching venues")
        return jsonify({"error": "Backend error fetching venues"}), 500

# -------------------------
# Run Server
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
