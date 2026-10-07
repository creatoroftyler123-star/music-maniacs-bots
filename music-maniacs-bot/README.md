# Music Maniacs — Songlink Bot

Auto-replies to music links (Spotify, Apple Music, YouTube, YouTube Music,
SoundCloud, Deezer, Tidal, Amazon Music) with the universal `song.link` URL,
so everyone can open the track in their own streaming app.

## 1. Create the bot in Discord

1. Go to https://discord.com/developers/applications → **New Application**,
   name it (e.g. `Music Maniacs Linker`).
2. **Bot** tab → **Reset Token** → copy the token (this is `DISCORD_TOKEN`).
3. In the **Bot** tab, enable the **Message Content Intent** toggle (required
   so the bot can read message text). Save.
4. **OAuth2 → URL Generator**: check scopes `bot`, then in **Bot Permissions**
   check: **Send Messages**, **Embed Links**, **Read Message History**.
5. Open the generated URL, pick your server, authorize.

Give the bot the **Send Messages** permission in whichever channels it should
watch (it needs it even in links-only channels — its replies contain links,
so they pass link-only AutoMod rules).

## 2. Odesli API key (recommended)

Odesli deprecated free keyless API access, so request a key or the bot will
fail its conversion step. Contact them via https://odesli.co (see the contact
link at the bottom of the page) and put the key in `ODESLI_API_KEY`.

Without a key the bot still starts, logs a clear warning from its self-test,
and simply won't reply to links.

## 3. Run it (needs 24/7 hosting)

This bot must stay online to work. Easy options: Railway, Replit, or any VPS.

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your values
python bot.py
```

Environment variables:

| Var | Required | What |
|-----|----------|------|
| `DISCORD_TOKEN` | yes | Bot token from step 1 |
| `ODESLI_API_KEY` | recommended | Odesli API key |
| `TARGET_CHANNEL_IDS` | no | Comma-separated channel IDs to watch; empty = all channels |

To get a channel ID: Discord Settings → Advanced → enable Developer Mode,
then right-click the channel → Copy Channel ID.

## How it behaves

- Ignores bots and its own messages.
- Skips messages that already contain a `song.link` / `album.link` URL.
- Converts only the **first** music link per message.
- Strips tracking params (`si`, `utm_*`, …) before converting.
- Replies with `🔗 Universal link: <song.link URL>` (no @mention).
- If Odesli fails, it stays silent and logs the error — no spam.
- On startup it self-tests the Odesli API and logs whether conversion works.
