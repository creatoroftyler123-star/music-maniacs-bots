"""
Music Maniacs - Songlink auto-converter bot.

Listens for music links (Spotify, Apple Music, YouTube, YouTube Music,
SoundCloud, Deezer, Tidal, Amazon Music) in chat and replies with the
universal song.link URL so everyone can open the track in their own app.

Setup: see README.md
Env vars:
    DISCORD_TOKEN      (required) bot token from discord.com/developers
    ODESLI_API_KEY     (optional) key from Odesli; public keyless access
                       is deprecated, so a key is strongly recommended
    TARGET_CHANNEL_IDS (optional) comma-separated channel IDs to watch;
                       if empty, watches every channel the bot can read
"""

import logging
import os
import re
import urllib.parse

import aiohttp
import discord

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("songlink-bot")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
ODESLI_API_KEY = os.environ.get("ODESLI_API_KEY", "")
ODESLI_ENDPOINT = "https://api.song.link/v1-alpha.1/links"
TARGET_CHANNEL_IDS = {
    int(x) for x in os.environ.get("TARGET_CHANNEL_IDS", "").split(",") if x.strip()
}

if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN env var is required. See README.md.")

# Matches a music URL from the major platforms.
MUSIC_URL_RE = re.compile(
    r"https?://"
    r"(?:"
    r"open\.spotify\.com/(?:track|album|playlist|episode)/[A-Za-z0-9]+"
    r"|music\.apple\.com/[^\s<>]+"
    r"|(?:www\.)?youtube\.com/watch\?[^\s<>]*"
    r"|music\.youtube\.com/watch\?[^\s<>]*"
    r"|youtu\.be/[^\s<>]+"
    r"|soundcloud\.com/[^\s<>]+"
    r"|(?:www\.)?deezer\.com/[^\s<>]+"
    r"|tidal\.com/browse/[^\s<>]+"
    r"|music\.amazon\.[a-z.]+/[^\s<>]+"
    r")",
    re.IGNORECASE,
)

# Already-universal links need no conversion.
ALREADY_UNIVERSAL_RE = re.compile(
    r"https?://(?:song\.link|album\.link|odesli\.co)/", re.IGNORECASE
)

# Tracking params stripped before conversion (keeps URLs clean).
TRACKING_PARAMS = {"si", "utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "igshid", "fbclid"}


def clean_url(url: str) -> str:
    """Strip tracking query params; keep the rest of the URL intact."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    new_query = urllib.parse.urlencode(kept)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )


async def resolve_universal(session: aiohttp.ClientSession, music_url: str) -> str:
    """Ask Odesli for the universal page URL. Raises on any failure."""
    params = {"url": music_url, "userCountry": "US"}
    if ODESLI_API_KEY:
        params["key"] = ODESLI_API_KEY
    timeout = aiohttp.ClientTimeout(total=20)
    async with session.get(ODESLI_ENDPOINT, params=params, timeout=timeout) as resp:
        body = await resp.text()
        if resp.status == 401:
            raise RuntimeError(
                "Odesli API rejected the request (401). Public keyless access "
                "is deprecated - set the ODESLI_API_KEY env var with a key "
                f"from Odesli. Response: {body[:160]}"
            )
        if resp.status != 200:
            raise RuntimeError(f"Odesli API HTTP {resp.status}: {body[:160]}")
        data = await resp.json()
    page_url = data.get("pageUrl")
    if not page_url:
        raise RuntimeError("Odesli returned no pageUrl for this link.")
    return page_url


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
http_session: aiohttp.ClientSession | None = None


@client.event
async def on_ready():
    global http_session
    http_session = aiohttp.ClientSession()
    log.info("Logged in as %s", client.user)
    # Self-test the Odesli API so a bad key shows up immediately in logs.
    try:
        test = await resolve_universal(
            http_session, "https://open.spotify.com/track/5JJDu0Z5DKe7mR31MGksSg"
        )
        log.info("Odesli self-test OK: %s", test)
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        log.warning("Odesli self-test failed: %s", exc)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or http_session is None:
        return
    if TARGET_CHANNEL_IDS and message.channel.id not in TARGET_CHANNEL_IDS:
        return

    text = message.content or ""
    if ALREADY_UNIVERSAL_RE.search(text):
        return
    match = MUSIC_URL_RE.search(text)
    if not match:
        return

    music_url = clean_url(match.group(0).rstrip(").,"))
    log.info("Converting %s in #%s", music_url, message.channel)

    try:
        page_url = await resolve_universal(http_session, music_url)
    except Exception as exc:  # noqa: BLE001 - keep the bot alive
        log.warning("Conversion failed for %s: %s", music_url, exc)
        return

    try:
        await message.reply(f"\U0001f517 Universal link: {page_url}",
                            mention_author=False)
    except discord.HTTPException as exc:
        log.warning("Could not reply in #%s: %s", message.channel, exc)


@client.event
async def on_disconnect():
    if http_session and not http_session.closed:
        await http_session.close()


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
