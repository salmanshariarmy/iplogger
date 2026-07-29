# IP Logger Discord Bot

Auto IP grabber + campaign tracking + optional GPS page.  
Posts hits to a Discord channel via webhook or bot.

## Quick Deploy (Render)

1. Fork/clone this repo to your GitHub  
2. Go to https://render.com → New Web Service → connect repo  
3. Build: `pip install -r requirements.txt`  
4. Start: use Procfile  
5. Add environment variables (see below)  
6. Deploy  

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | No* | Bot token for slash commands + channel posting |
| `DISCORD_CHANNEL_ID` | No* | Channel ID for bot to post in |
| `DISCORD_WEBHOOK_URL` | No* | Webhook URL (fallback if bot not used) |
| `REDIRECT_URL` | No | Where visitors land (default: Google) |
| `IPINFO_TOKEN` | No | ipinfo.io token for better GeoIP |
| `BASE_URL` | No | Your app's public URL (for /genlink) |

*\*Either BOT_TOKEN+CHANNEL_ID or WEBHOOK_URL must be set.*

## URLs

- `/` → auto IP grab + redirect  
- `/r/<campaign>` → campaign-tracked redirect  
- `/g` → GPS decoy page (browser asks Allow/Block)  
- `/ping` → health check  

## Bot Commands

- `/status` — bot stats, hit count, ping  
- `/setredirect <url>` — change default redirect  
- `/genlink campaign:<name>` — generate tracked `/r/<name>` link
