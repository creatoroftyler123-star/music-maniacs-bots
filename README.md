# Music Maniacs — Song of the Day

Posts a daily track to your server, rotating through your 12 genre channels'
genres (rock → jazz → classical → … → instrumental → back to rock). Each
post is a rich embed with artwork, artist, and a Spotify link.

## 1. Create a third Discord bot

1. https://discord.com/developers/applications → **New Application**.
2. **Bot** tab → **Reset Token** → copy it (`DISCORD_TOKEN`).
3. No privileged intents needed this time (it only sends messages).
4. **OAuth2 → URL Generator**: scope `bot`; permissions: **Send Messages**,
   **Embed Links**.
5. Open the URL, add it to your server.

## 2. Spotify credentials (read-only — no login needed)

Unlike the playlist bot, this one never touches your Spotify account:

1. https://developer.spotify.com/dashboard → **Create app**.
2. Copy the **Client ID** and **Client Secret**. No redirect URI needed.

## 3. Run it (needs 24/7 hosting: Railway, Replit, VPS)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python sotd_bot.py
```

| Var | Required | What |
|-----|----------|------|
| `DISCORD_TOKEN` | yes | This bot's token |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | yes | From step 2 |
| `POST_CHANNEL_ID` | yes | Where the daily song goes (e.g. #general) |
| `POST_HOUR` | no | Hour to post, 0–23 (default 9) |
| `TIMEZONE` | no | e.g. `America/Los_Angeles` (default UTC) |
| `DB_PATH` | no | SQLite file (default `sotd_bot.db`) |

Get a channel ID: Discord Settings → Advanced → Developer Mode → right-click
channel → Copy Channel ID.

## Commands

| Command | What |
|---------|------|
| `!sotd` | Post today's pick right now |
| `!sotd jazz` | Post a pick for a specific genre (rock, jazz, classical, hip-hop-rap, techno-edm-house, heavy-metal, country, random-music, pop, reggae, latin, instrumental) |

Tracks are never repeated until every candidate has been posted. The bot
picks from Spotify's most popular results per genre each day.
