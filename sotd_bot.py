"""
Music Maniacs - Song of the Day bot.

Posts a daily track to your server, rotating through your 12 genre
channels' genres. Picks a random popular track per genre via the Spotify
search API and posts a rich embed with artwork.

Only needs Spotify *client credentials* (no user login, no redirect URI).

Setup: see README.md
Env vars:
    DISCORD_TOKEN     (required) token of THIS bot (third app)
    SPOTIFY_CLIENT_ID (required) from developer.spotify.com
    SPOTIFY_CLIENT_SECRET (required) from developer.spotify.com
    POST_CHANNEL_ID   (required) channel ID to post in (e.g. #general)
    POST_HOUR         (optional) hour of day to post, default 9
    TIMEZONE          (optional) e.g. America/Los_Angeles, default UTC
    DB_PATH           (optional) SQLite file, default sotd_bot.db
"""

import asyncio
import datetime
import logging
import os
import random
import sqlite3
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("sotd-bot")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
POST_CHANNEL_ID = int(os.environ.get("POST_CHANNEL_ID", "0") or 0)
POST_HOUR = int(os.environ.get("POST_HOUR", "9") or 9)
TIMEZONE = os.environ.get("TIMEZONE", "UTC")
DB_PATH = os.environ.get("DB_PATH", "sotd_bot.db")

for var in ("DISCORD_TOKEN", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
    if not os.environ.get(var):
        raise SystemExit(f"{var} env var is required. See README.md.")
if not POST_CHANNEL_ID:
    raise SystemExit("POST_CHANNEL_ID env var is required. See README.md.")

# Your 12 genre channels, in rotation order, mapped to Spotify genre queries.
GENRES = [
    ("rock", "rock"),
    ("jazz", "jazz"),
    ("classical", "classical"),
    ("hip-hop-rap", "hip hop"),
    ("techno-edm-house", "edm"),
    ("heavy-metal", "metal"),
    ("country", "country"),
    ("random-music", None),  # wild card: any genre
    ("pop", "pop"),
    ("reggae", "reggae"),
    ("latin", "latin"),
    ("instrumental", "instrumental"),
]

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"


# ---------------- database ----------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS posted ("
        " spotify_id TEXT PRIMARY KEY, genre TEXT, posted_at TEXT)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return conn


def already_posted(spotify_id: str) -> bool:
    conn = db()
    try:
        return conn.execute(
            "SELECT 1 FROM posted WHERE spotify_id=?", (spotify_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def record_posted(spotify_id: str, genre: str) -> None:
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO posted (spotify_id, genre, posted_at)"
            " VALUES (?,?,?)",
            (spotify_id, genre,
             datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def genre_for_today(today: datetime.date) -> tuple[str, str | None]:
    """Rotate genres by day count so each day hits the next genre."""
    idx = today.toordinal() % len(GENRES)
    return GENRES[idx]


# ---------------- Spotify API (client credentials) ----------------

async def spotify_token(session: aiohttp.ClientSession) -> str:
    data = {
        "grant_type": "client_credentials",
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    async with session.post(SPOTIFY_TOKEN_URL, data=data) as resp:
        body = await resp.json()
        if resp.status != 200:
            raise RuntimeError(f"Spotify auth failed: {body}")
        return body["access_token"]


async def pick_track(
    session: aiohttp.ClientSession, genre_query: str | None
) -> dict:
    """Pick a random unposted track for the genre. Raises if none found."""
    token = await spotify_token(session)
    headers = {"Authorization": f"Bearer {token}"}
    query = f'genre:"{genre_query}"' if genre_query else "genre:pop"
    params = {"q": query, "type": "track", "limit": 50,
              "market": "US"}
    async with session.get(SPOTIFY_SEARCH_URL, headers=headers,
                           params=params) as resp:
        resp.raise_for_status()
        items = (await resp.json())["tracks"]["items"]
    fresh = [t for t in items if t and not already_posted(t["id"])]
    if not fresh:
        raise RuntimeError("No fresh tracks found (all 50 already posted).")
    return random.choice(fresh)


def build_embed(track: dict, genre_label: str) -> discord.Embed:
    artists = ", ".join(a["name"] for a in track["artists"])
    title = track["name"]
    url = track["external_urls"]["spotify"]
    images = track["album"].get("images") or []
    embed = discord.Embed(
        title="\U0001f3b5 Song of the Day",
        description=f"**[{title}]({url})**\n{artists}",
        color=0x1DB954,
    )
    if images:
        embed.set_thumbnail(url=images[0]["url"])
    embed.set_footer(text=f"Today's genre: #{genre_label} \u2022 "
                          "via Spotify")
    return embed


# ---------------- bot ----------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
http_session: aiohttp.ClientSession | None = None


async def post_song_of_the_day(channel: discord.abc.Messageable,
                               force_genre: str | None = None) -> None:
    assert http_session is not None
    today = datetime.datetime.now(ZoneInfo(TIMEZONE)).date()
    if force_genre:
        genre_label, genre_query = force_genre, force_genre
    else:
        genre_label, genre_query = genre_for_today(today)
    track = await pick_track(http_session, genre_query)
    await channel.send(embed=build_embed(track, genre_label))
    record_posted(track["id"], genre_label)
    log.info("Posted Song of the Day: %s (%s)", track["name"], genre_label)


@tasks.loop(time=datetime.time(hour=POST_HOUR,
                               tzinfo=ZoneInfo(TIMEZONE)))
async def daily_post():
    channel = bot.get_channel(POST_CHANNEL_ID)
    if channel is None:
        log.error("POST_CHANNEL_ID %s not found.", POST_CHANNEL_ID)
        return
    try:
        await post_song_of_the_day(channel)
    except Exception:  # noqa: BLE001 - keep the loop alive
        log.exception("Daily post failed")


@daily_post.before_loop
async def _wait_ready():
    await bot.wait_until_ready()


@bot.command(name="sotd")
async def cmd_sotd(ctx: commands.Context, genre: str | None = None):
    """Post the Song of the Day on demand. Optional: !sotd jazz"""
    valid = {g[0] for g in GENRES}
    if genre and genre not in valid:
        await ctx.reply(
            f"Unknown genre. Pick one of: {', '.join(sorted(valid))}"
        )
        return
    try:
        await post_song_of_the_day(ctx.channel, force_genre=genre)
    except Exception as exc:  # noqa: BLE001
        log.exception("Manual sotd failed")
        await ctx.reply(f"Couldn't pick a track right now: {exc}")


@bot.event
async def on_ready():
    global http_session
    http_session = aiohttp.ClientSession()
    log.info("Logged in as %s", bot.user)
    if not daily_post.is_running():
        daily_post.start()
        log.info("Daily post scheduled at %02d:00 %s", POST_HOUR, TIMEZONE)


@bot.event
async def on_disconnect():
    if http_session and not http_session.closed:
        await http_session.close()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
