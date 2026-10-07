# Music Maniacs — Weekly Playlist Builder

Collects Spotify track links posted in your music channels and builds a
Spotify playlist from them — on demand (`!buildplaylist`) or automatically
every 7 days. Only Spotify **track** links are collected (albums/playlists
from other platforms are skipped).

## 1. Create a second Discord bot

This is a different bot from the songlink one, so make another application:

1. https://discord.com/developers/applications → **New Application**.
2. **Bot** tab → **Reset Token** → copy it (`DISCORD_TOKEN`).
3. Enable **Message Content Intent**, save.
4. **OAuth2 → URL Generator**: scopes `bot` (+ `applications.commands`
   if you want slash commands later); permissions: **Send Messages**,
   **Embed Links**, **Read Message History**.
5. Open the URL, add it to your server. Give it **Send Messages** in the
   channels it should announce in.

## 2. Create a Spotify app

1. https://developer.spotify.com/dashboard → **Create app**.
2. Copy the **Client ID** and **Client Secret**.
3. In the app's settings, add a **Redirect URI** — this must exactly match
   `SPOTIFY_REDIRECT_URI`, e.g. `https://your-app.up.railway.app/callback`
   (for local testing: `http://localhost:8000/callback`).

## 3. Authorize once

1. Deploy/run the bot with the env vars below.
2. In Discord, an admin runs `!spotifyauth`. The bot replies with a link.
3. Click it, approve Spotify access. The bot stores the tokens — done.
   (Tokens refresh automatically from then on.)

## 4. Run it (needs 24/7 hosting: Railway, Replit, VPS)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python playlist_bot.py
```

| Var | Required | What |
|-----|----------|------|
| `DISCORD_TOKEN` | yes | This bot's token |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | yes | From step 2 |
| `SPOTIFY_REDIRECT_URI` | yes | Must match dashboard entry |
| `TARGET_CHANNEL_IDS` | no | Channels to watch (empty = all) |
| `ANNOUNCE_CHANNEL_ID` | no | Where weekly playlists are posted (e.g. #general) |
| `WEEKLY_BUILD` | no | `true` (default) = auto-build every 7 days |
| `PLAYLIST_PUBLIC` | no | `true` (default) = public playlist |
| `PORT` | no | Web port for OAuth callback (hosts set this; default 8000) |
| `DB_PATH` | no | SQLite file (default `playlist_bot.db`) |

Get a channel ID: Discord Settings → Advanced → Developer Mode → right-click
channel → Copy Channel ID.

## Commands

| Command | Who | What |
|---------|-----|------|
| `!spotifyauth` | admin | One-time Spotify authorization |
| `!buildplaylist` | admin | Build the playlist from queued tracks now |
| `!pending` | anyone | How many tracks are queued |

Playlists are named like `🎵 Music Maniacs — Week of Oct 09` and created on
the Spotify account that authorized the bot. Tracks are de-duplicated, and
each week's build only includes tracks posted since the last build.
