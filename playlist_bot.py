"""
Music Maniacs - Weekly Playlist Builder bot.

Watches your music channels for Spotify track links, collects them, and
builds a Spotify playlist on demand (!buildplaylist) or automatically every
week. Posts the playlist link back to the server.

Setup: see README.md
Env vars:
    DISCORD_TOKEN        (required) token of THIS bot (make a second app)
    SPOTIFY_CLIENT_ID    (required) from developer.spotify.com
    SPOTIFY_CLIENT_SECRET(required) from developer.spotify.com
    SPOTIFY_REDIRECT_URI (required) e.g. https://your-app.up.railway.app/callback
                                     (must match the Spotify dashboard entry)
    TARGET_CHANNEL_IDS   (optional) comma-separated channel IDs to watch;
                         if empty, watches every channel the bot can read
    ANNOUNCE_CHANNEL_ID  (optional) channel ID where weekly playlists are
                         announced (e.g. #general)
    WEEKLY_BUILD         (optional) "true"/"false", default true: auto-build
                         every 7 days
    PLAYLIST_PUBLIC      (optional) "true"/"false", default true
    PORT                 (optional) web port for the Spotify OAuth callback,
                         default 8000 (hosts like Railway set this)
"""

import asyncio
import logging
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands, tasks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("playlist-bot")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "")
TARGET_CHANNEL_IDS = {
    int(x) for x in os.environ.get("TARGET_CHANNEL_IDS", "").split(",") if x.strip()
}
ANNOUNCE_CHANNEL_ID = int(os.environ.get("ANNOUNCE_CHANNEL_ID", "0") or 0)
WEEKLY_BUILD = os.environ.get("WEEKLY_BUILD", "true").lower() == "true"
PLAYLIST_PUBLIC = os.environ.get("PLAYLIST_PUBLIC", "true").lower() == "true"
PORT = int(os.environ.get("PORT", "8000"))
DB_PATH = os.environ.get("DB_PATH", "playlist_bot.db")

for var in ("DISCORD_TOKEN", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
            "SPOTIFY_REDIRECT_URI"):
    if not os.environ.get(var):
        raise SystemExit(f"{var} env var is required. See README.md.")

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private"

TRACK_RE = re.compile(
    r"https?://open\.spotify\.com/track/([A-Za-z0-9]+)", re.IGNORECASE
)

# In-memory OAuth states: state -> created_at
pending_states: dict[str, float] = {}


# ---------------- database ----------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tracks ("
        " spotify_id TEXT PRIMARY KEY,"
        " channel_id INTEGER, user_id INTEGER,"
        " posted_at INTEGER, added INTEGER DEFAULT 0)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return conn


def kv_get(key: str) -> str | None:
    conn = db()
    try:
        row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def kv_set(key: str, value: str) -> None:
    conn = db()
    try:
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()


def store_tracks(track_ids: set[str], channel_id: int, user_id: int) -> int:
    """Insert new track IDs. Returns how many were actually new."""
    if not track_ids:
        return 0
    conn = db()
    try:
        now = int(time.time())
        added = 0
        for tid in track_ids:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tracks "
                "(spotify_id, channel_id, user_id, posted_at) VALUES (?,?,?,?)",
                (tid, channel_id, user_id, now),
            )
            added += cur.rowcount
        conn.commit()
        return added
    finally:
        conn.close()


def pending_tracks() -> list[str]:
    conn = db()
    try:
        rows = conn.execute(
            "SELECT spotify_id FROM tracks WHERE added=0 ORDER BY posted_at"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def mark_added(track_ids: list[str]) -> None:
    conn = db()
    try:
        conn.executemany(
            "UPDATE tracks SET added=1 WHERE spotify_id=?",
            [(t,) for t in track_ids],
        )
        conn.commit()
    finally:
        conn.close()


# ---------------- Spotify API ----------------

async def spotify_token(session: aiohttp.ClientSession) -> str:
    """Return a valid access token, refreshing with the stored refresh token."""
    access = kv_get("sp_access")
    expires_at = float(kv_get("sp_expires_at") or 0)
    if access and time.time() < expires_at - 60:
        return access
    refresh = kv_get("sp_refresh")
    if not refresh:
        raise RuntimeError(
            "Spotify not authorized yet. An admin must run !spotifyauth first."
        )
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    async with session.post(SPOTIFY_TOKEN_URL, data=data) as resp:
        body = await resp.json()
        if resp.status != 200:
            raise RuntimeError(f"Spotify token refresh failed: {body}")
    kv_set("sp_access", body["access_token"])
    kv_set("sp_expires_at", str(time.time() + body.get("expires_in", 3600)))
    if body.get("refresh_token"):
        kv_set("sp_refresh", body["refresh_token"])
    return body["access_token"]


async def spotify_me(session: aiohttp.ClientSession) -> dict:
    token = await spotify_token(session)
    async with session.get(
        f"{SPOTIFY_API}/me", headers={"Authorization": f"Bearer {token}"}
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def spotify_create_playlist(
    session: aiohttp.ClientSession, user_id: str, name: str
) -> dict:
    token = await spotify_token(session)
    payload = {
        "name": name,
        "public": PLAYLIST_PUBLIC,
        "description": "Auto-built from links shared in the Music Maniacs "
                       "Discord server.",
    }
    async with session.post(
        f"{SPOTIFY_API}/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json=payload,
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def spotify_add_tracks(
    session: aiohttp.ClientSession, playlist_id: str, track_ids: list[str]
) -> None:
    token = await spotify_token(session)
    uris = [f"spotify:track:{t}" for t in track_ids]
    for i in range(0, len(uris), 100):  # Spotify caps at 100 per request
        chunk = uris[i:i + 100]
        async with session.post(
            f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"uris": chunk},
        ) as resp:
            resp.raise_for_status()


def authorize_url() -> str:
    state = secrets.token_urlsafe(16)
    pending_states[state] = time.time()
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    return f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def handle_oauth_callback(request: web.Request) -> web.Response:
    code = request.query.get("code", "")
    state = request.query.get("state", "")
    if not code or state not in pending_states:
        return web.Response(text="Invalid or expired authorization. Try again.",
                            status=400)
    del pending_states[state]
    session: aiohttp.ClientSession = request.app["http_session"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    async with session.post(SPOTIFY_TOKEN_URL, data=data) as resp:
        body = await resp.json()
        if resp.status != 200:
            log.error("OAuth exchange failed: %s", body)
            return web.Response(
                text=f"Authorization failed: {body.get('error_description', body)}",
                status=500,
            )
    kv_set("sp_access", body["access_token"])
    kv_set("sp_expires_at", str(time.time() + body.get("expires_in", 3600)))
    kv_set("sp_refresh", body["refresh_token"])
    log.info("Spotify authorization complete.")
    return web.Response(
        text="Authorized! The bot can now build playlists. "
             "You can close this tab."
    )


# ---------------- bot ----------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
http_session: aiohttp.ClientSession | None = None


async def build_playlist(session: aiohttp.ClientSession) -> tuple[str, int]:
    """Create the weekly playlist from collected tracks. Returns (url, count)."""
    track_ids = pending_tracks()
    if not track_ids:
        raise RuntimeError("No new tracks collected since the last build.")
    me = await spotify_me(session)
    week = datetime.now(timezone.utc).strftime("%b %d")
    name = f"\U0001f3b5 Music Maniacs \u2014 Week of {week}"
    playlist = await spotify_create_playlist(session, me["id"], name)
    await spotify_add_tracks(session, playlist["id"], track_ids)
    mark_added(track_ids)
    url = playlist["external_urls"]["spotify"]
    log.info("Built playlist %s with %d tracks: %s", name, len(track_ids), url)
    return url, len(track_ids)


@bot.event
async def on_ready():
    global http_session
    http_session = aiohttp.ClientSession()
    log.info("Logged in as %s", bot.user)

    # OAuth callback web server (same event loop as the bot).
    app = web.Application()
    app["http_session"] = http_session
    app.router.add_get("/callback", handle_oauth_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("OAuth callback listening on port %d", PORT)

    if WEEKLY_BUILD and not weekly_build.is_running():
        weekly_build.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or http_session is None:
        return
    if TARGET_CHANNEL_IDS and message.channel.id not in TARGET_CHANNEL_IDS:
        return
    ids = {m.group(1) for m in TRACK_RE.finditer(message.content or "")}
    new = store_tracks(ids, message.channel.id, message.author.id)
    if new:
        log.info("Collected %d new track(s) from #%s", new, message.channel)
    await bot.process_commands(message)


@bot.command(name="spotifyauth")
@commands.has_permissions(administrator=True)
async def cmd_spotifyauth(ctx: commands.Context):
    """Admin-only: start the Spotify authorization flow."""
    url = authorize_url()
    await ctx.reply(
        "Click to authorize Spotify playlist access (one-time):\n"
        f"<{url}>\nAfter approving, you're done \u2014 the bot handles the rest.",
        mention_author=False,
    )


@bot.command(name="buildplaylist")
@commands.has_permissions(administrator=True)
async def cmd_buildplaylist(ctx: commands.Context):
    """Admin-only: build the playlist from collected tracks right now."""
    if http_session is None:
        await ctx.reply("Bot is still starting, try again in a moment.")
        return
    try:
        url, count = await build_playlist(http_session)
    except RuntimeError as exc:
        await ctx.reply(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        log.exception("Playlist build failed")
        await ctx.reply(f"Build failed: {exc}")
        return
    await ctx.reply(
        f"\U0001f3b5 Weekly playlist is live with {count} tracks:\n{url}"
    )


@bot.command(name="pending")
async def cmd_pending(ctx: commands.Context):
    """How many tracks are queued for the next playlist."""
    await ctx.reply(f"\U0001f4e5 {len(pending_tracks())} tracks queued.")


@tasks.loop(hours=24 * 7)
async def weekly_build():
    if http_session is None:
        return
    try:
        url, count = await build_playlist(http_session)
    except RuntimeError as exc:
        log.info("Weekly build skipped: %s", exc)
        return
    except Exception:  # noqa: BLE001
        log.exception("Weekly build failed")
        return
    if ANNOUNCE_CHANNEL_ID:
        channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if channel:
            await channel.send(
                f"\U0001f3b5 This week's community playlist is live "
                f"with {count} tracks:\n{url}"
            )


@weekly_build.before_loop
async def _wait_ready():
    await bot.wait_until_ready()


@bot.event
async def on_disconnect():
    if http_session and not http_session.closed:
        await http_session.close()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
