# Music Maniacs — Deploy All Three Bots (one runbook)

Everything in one place, in the order that actually works. Sources: the three
per-bot READMEs in this folder (root, playlist/, sotd/), plus a verified
shortcut for the songlink bot (see step 4).

## The short version

| Bot | Discord token | Message Content Intent | Spotify | Other |
|-----|---------------|------------------------|---------|-------|
| songlink (root `bot.py`) | own token | **required** | none | Odesli key **no longer needed** (see step 4) |
| playlist (`playlist/playlist_bot.py`) | own token | **required** | Client ID + Secret, redirect URI, one-time `!spotifyauth` | SQLite DB auto-created |
| song-of-the-day (`sotd/sotd_bot.py`) | own token | not needed | Client ID + Secret only (read-only) | `POST_CHANNEL_ID` required |

- **One Spotify app is enough for both Spotify bots.** Create a single app at
  https://developer.spotify.com/dashboard and reuse its Client ID/Secret in
  both bots. Only the playlist bot needs a Redirect URI (set to your host's
  public URL + `/callback`, e.g. `https://your-app.up.railway.app/callback`).
- Three separate Discord applications are needed (one token per bot process,
  as built). Creating them takes ~5 min each:
  https://discord.com/developers/applications → New Application → Bot tab →
  Reset Token → enable Message Content Intent where required (songlink,
  playlist) → OAuth2 URL Generator with the scopes/permissions from each
  README → open the URL, add to your server.

## Step 1 — Create the 3 Discord applications

For each bot (songlink, playlist, sotd): New Application → Bot tab → Reset
Token → save the token. Enable **Message Content Intent** for songlink and
playlist only (sotd doesn't read messages, so it doesn't need it). Then
OAuth2 → URL Generator:

- songlink: scopes `bot`; permissions Send Messages, Embed Links,
  Read Message History.
- playlist: scopes `bot` (+ `applications.commands` optional); same
  permissions.
- sotd: scope `bot`; permissions Send Messages, Embed Links.

Add each to the server. In the links-only channels, each bot needs Send
Messages permission (their replies contain links, so they pass link-only
AutoMod rules).

## Step 2 — Create ONE Spotify app

1. https://developer.spotify.com/dashboard → Create app.
2. Copy Client ID + Client Secret — paste into **both** `playlist/.env` and
   `sotd/.env`.
3. **Sequencing matters for the playlist bot:** deploy first (step 3), get
   your public host URL, *then* add the Redirect URI in the Spotify dashboard
   (must exactly match `SPOTIFY_REDIRECT_URI` in `playlist/.env`, e.g.
   `https://your-app.up.railway.app/callback`).

## Step 3 — Host (24/7: Railway, Replit, or a VPS)

Each bot is its own process:

```bash
# songlink
cd ~/workspace/music-maniacs-bot && pip install -r requirements.txt
cp .env.example .env   # fill DISCORD_TOKEN (+ TARGET_CHANNEL_IDS optional)
python bot.py

# playlist
cd playlist && pip install -r requirements.txt
cp .env.example .env   # fill DISCORD_TOKEN, SPOTIFY_CLIENT_ID/SECRET, SPOTIFY_REDIRECT_URI
python playlist_bot.py

# song of the day
cd ../sotd && pip install -r requirements.txt
cp .env.example .env   # fill DISCORD_TOKEN, SPOTIFY_CLIENT_ID/SECRET, POST_CHANNEL_ID, TIMEZONE=America/Los_Angeles
python sotd_bot.py
```

SOTD env specifics: `POST_CHANNEL_ID` (required — where the daily song goes,
e.g. #general), `POST_HOUR` (default 9), `TIMEZONE` (default UTC — set to
`America/Los_Angeles`).

## Step 4 — One-time authorizations (after hosting is up)

- **Playlist bot:** an admin runs `!spotifyauth` in Discord → click the link
  → approve Spotify access. Tokens store and refresh automatically. Then
  `!buildplaylist` builds on demand; `!pending` shows the queue; auto-build
  runs every 7 days (`WEEKLY_BUILD=true` default). Playlists are named like
  "🎵 Music Maniacs — Week of Oct 09" on the authorizing account.
- **Songlink bot:** **no Odesli API key needed anymore.** Verified 2026-10-02:
  `https://song.link/<url-encoded-track-url>` resolves to a working universal
  song page (tested with a Spotify track → "Come Out and Play" by The
  Offspring, artwork + Listen/Buy links). The bot can be patched to generate
  these URLs directly instead of calling Odesli — ask Juno to apply the patch
  to `bot.py` (it keeps the tracking-param stripping and silent-on-failure
  behavior). Verified for Spotify; other platforms expected to resolve the
  same way but not individually tested.

## Channel IDs

Discord Settings → Advanced → enable Developer Mode → right-click channel →
Copy Channel ID. Used for `TARGET_CHANNEL_IDS` (which channels each bot
watches; empty = all) and `POST_CHANNEL_ID` / `ANNOUNCE_CHANNEL_ID`.

## If something's off

- Songlink bot silent on links → check Message Content Intent is enabled and
  it has Send Messages in that channel.
- `!spotifyauth` link errors → Redirect URI in the Spotify dashboard doesn't
  exactly match `SPOTIFY_REDIRECT_URI` (trailing slashes count).
- SOTD posting at the wrong hour → `POST_HOUR` + `TIMEZONE` (defaults are
  9 and UTC).
