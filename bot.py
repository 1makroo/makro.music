from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import discord
import spotipy
import yt_dlp
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("makro_music_bot")

BOT_SIGNATURE = "Makro"
MAX_QUERY_LENGTH = 300
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
SPOTIFY_OPEN_URL_RE = re.compile(
    r"open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
SPOTIFY_URI_RE = re.compile(
    r"spotify:(track|album|playlist):([A-Za-z0-9]+)",
    re.IGNORECASE,
)

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"

YTDL_METADATA_OPTIONS: dict[str, Any] = {
    "default_search": "ytsearch",
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
    "noplaylist": False,
    "quiet": True,
    "skip_download": True,
}

YTDL_STREAM_OPTIONS: dict[str, Any] = {
    "default_search": "ytsearch",
    "format": "bestaudio/best",
    "ignoreerrors": True,
    "noplaylist": True,
    "quiet": True,
    "skip_download": True,
}


def getenv_int(name: str, default: int, minimum: int = 1, maximum: int = 100) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


MAX_PLAYLIST_ITEMS = getenv_int("MAX_PLAYLIST_ITEMS", 50)
YTDL_METADATA_OPTIONS["playlistend"] = MAX_PLAYLIST_ITEMS


@dataclass
class Track:
    title: str
    query: str
    requester: str
    source_url: str | None = None


class UserFacingError(Exception):
    """An exception whose message is safe to show in Discord."""


def clean_text(value: str, limit: int = 180) -> str:
    value = discord.utils.escape_mentions(discord.utils.escape_markdown(value))
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def is_url(query: str) -> bool:
    return bool(URL_RE.match(query.strip()))


def is_public_ip_address(address: str) -> bool:
    try:
        ip_address = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip_address.is_global


def validate_public_media_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UserFacingError("Only public `http` and `https` media links are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise UserFacingError("That URL is missing a valid hostname.")

    normalized_hostname = hostname.rstrip(".").lower()
    if (
        normalized_hostname in {"localhost", "localhost.localdomain"}
        or normalized_hostname.endswith(".localhost")
        or normalized_hostname.endswith(".local")
    ):
        raise UserFacingError("Local/private network URLs are not allowed.")

    try:
        _ = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        if "." not in normalized_hostname:
            raise UserFacingError("Local/private network URLs are not allowed.")

    try:
        addresses = socket.getaddrinfo(
            normalized_hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UserFacingError("I couldn't resolve that URL's hostname.") from exc

    resolved_ips = {str(address[4][0]) for address in addresses}
    if not resolved_ips or any(not is_public_ip_address(ip) for ip in resolved_ips):
        raise UserFacingError("Local/private network URLs are not allowed.")


def validate_query(query: str) -> str:
    normalized = query.strip()
    if not normalized:
        raise UserFacingError("Give me a URL or search query to play.")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise UserFacingError(
            f"Queries must be {MAX_QUERY_LENGTH} characters or fewer."
        )
    return normalized


def user_in_same_voice_channel(
    interaction: discord.Interaction,
    state: GuildMusicState,
) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False

    user_voice = interaction.user.voice
    if not user_voice or not user_voice.channel or not state.voice:
        return False

    return user_voice.channel == state.voice.channel


def parse_spotify_reference(query: str) -> tuple[str, str] | None:
    open_url_match = SPOTIFY_OPEN_URL_RE.search(query)
    if open_url_match:
        return open_url_match.group(1).lower(), open_url_match.group(2)

    uri_match = SPOTIFY_URI_RE.search(query)
    if uri_match:
        return uri_match.group(1).lower(), uri_match.group(2)

    return None


def spotify_client() -> spotipy.Spotify | None:
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    credentials = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    return spotipy.Spotify(auth_manager=credentials)


def spotify_track_to_track(raw_track: dict[str, Any], requester: str) -> Track | None:
    if not raw_track or raw_track.get("is_local"):
        return None

    name = raw_track.get("name") or "Unknown track"
    artists = ", ".join(
        artist.get("name", "Unknown artist") for artist in raw_track.get("artists", [])
    )
    artists = artists or "Unknown artist"
    title = f"{name} - {artists}"
    source_url = raw_track.get("external_urls", {}).get("spotify")

    return Track(
        title=title,
        query=f"ytsearch1:{name} {artists} official audio",
        requester=requester,
        source_url=source_url,
    )


def resolve_spotify_tracks_sync(
    kind: str, spotify_id: str, requester: str
) -> list[Track]:
    client = spotify_client()
    if client is None:
        message = (
            "Spotify links need `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`. "
            + "You can still play YouTube/search queries without them."
        )
        raise UserFacingError(message)

    tracks: list[Track] = []

    if kind == "track":
        track = spotify_track_to_track(client.track(spotify_id), requester)
        return [track] if track else []

    if kind == "album":
        results = client.album_tracks(spotify_id, limit=min(50, MAX_PLAYLIST_ITEMS))
        while results and len(tracks) < MAX_PLAYLIST_ITEMS:
            for raw_track in results.get("items", []):
                track = spotify_track_to_track(raw_track, requester)
                if track:
                    tracks.append(track)
                if len(tracks) >= MAX_PLAYLIST_ITEMS:
                    break

            if len(tracks) >= MAX_PLAYLIST_ITEMS or not results.get("next"):
                break
            results = client.next(results)

        return tracks

    if kind == "playlist":
        results = client.playlist_items(
            spotify_id,
            fields="items(track(name,artists(name),external_urls,is_local)),next",
            limit=min(100, MAX_PLAYLIST_ITEMS),
            additional_types=("track",),
        )
        while results and len(tracks) < MAX_PLAYLIST_ITEMS:
            for item in results.get("items", []):
                raw_track = item.get("track") if item else None
                track = (
                    spotify_track_to_track(raw_track, requester) if raw_track else None
                )
                if track:
                    tracks.append(track)
                if len(tracks) >= MAX_PLAYLIST_ITEMS:
                    break

            if len(tracks) >= MAX_PLAYLIST_ITEMS or not results.get("next"):
                break
            results = client.next(results)

        return tracks

    raise UserFacingError(f"Unsupported Spotify link type: `{kind}`")


def ytdl_extract_sync(query: str, options: dict[str, Any]) -> dict[str, Any] | None:
    with yt_dlp.YoutubeDL(cast(Any, options)) as ytdl:
        info = cast(object, ytdl.extract_info(query, download=False))
        return cast(dict[str, Any] | None, info)


def entry_url(entry: dict[str, Any]) -> str | None:
    url = entry.get("webpage_url") or entry.get("url")
    if not url:
        return None

    if isinstance(url, str) and url.startswith("http"):
        return url

    extractor = str(entry.get("ie_key") or entry.get("extractor_key") or "")
    if "Youtube" in extractor or re.fullmatch(r"[A-Za-z0-9_-]{11}", str(url)):
        return f"https://www.youtube.com/watch?v={url}"

    return str(url)


async def resolve_ytdl_tracks(query: str, requester: str) -> list[Track]:
    if is_url(query):
        await asyncio.to_thread(validate_public_media_url, query)
        lookup = query
    else:
        lookup = f"ytsearch1:{query}"

    info = await asyncio.to_thread(ytdl_extract_sync, lookup, YTDL_METADATA_OPTIONS)
    if not info:
        return []

    tracks: list[Track] = []
    entries = info.get("entries") if isinstance(info, dict) else None

    if entries:
        for entry in entries:
            if not entry:
                continue

            url = entry_url(entry)
            if not url:
                continue

            title = entry.get("title") or url
            tracks.append(
                Track(
                    title=title,
                    query=url,
                    requester=requester,
                    source_url=url if url.startswith("http") else None,
                )
            )

            if len(tracks) >= MAX_PLAYLIST_ITEMS:
                break
    else:
        title = info.get("title") or query
        url = info.get("webpage_url") or query
        tracks.append(
            Track(
                title=title,
                query=url,
                requester=requester,
                source_url=url
                if isinstance(url, str) and url.startswith("http")
                else None,
            )
        )

    return tracks


async def resolve_tracks(query: str, requester: str) -> list[Track]:
    query = validate_query(query)
    spotify_reference = parse_spotify_reference(query)
    if spotify_reference:
        kind, spotify_id = spotify_reference
        tracks = await asyncio.to_thread(
            resolve_spotify_tracks_sync,
            kind,
            spotify_id,
            requester,
        )
    else:
        tracks = await resolve_ytdl_tracks(query, requester)

    if not tracks:
        raise UserFacingError("I couldn't find any playable tracks for that query.")

    return tracks


async def resolve_stream(track: Track) -> dict[str, str | None]:
    if is_url(track.query):
        await asyncio.to_thread(validate_public_media_url, track.query)

    info = await asyncio.to_thread(ytdl_extract_sync, track.query, YTDL_STREAM_OPTIONS)
    if not info:
        raise UserFacingError("I couldn't resolve this track into an audio stream.")

    entries = info.get("entries") if isinstance(info, dict) else None
    if entries:
        info = next((entry for entry in entries if entry), None)

    if not info or not info.get("url"):
        raise UserFacingError("I couldn't resolve this track into an audio stream.")

    return {
        "stream_url": info.get("url"),
        "title": info.get("title"),
        "webpage_url": info.get("webpage_url"),
    }


class GuildMusicState:
    def __init__(self, bot: MusicBot, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.next_track = asyncio.Event()
        self.play_error: Exception | None = None
        self.player_task = asyncio.create_task(self.player_loop())

    async def connect(
        self,
        voice_channel: discord.VoiceChannel | discord.StageChannel,
        text_channel: discord.abc.Messageable | None,
    ) -> None:
        self.text_channel = text_channel

        if self.voice and self.voice.is_connected():
            if self.voice.channel != voice_channel:
                await self.voice.move_to(voice_channel)
            return

        self.voice = await voice_channel.connect()

    async def player_loop(self) -> None:
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next_track.clear()
            self.play_error = None

            try:
                track = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await self.disconnect()
                self.bot.music_states.pop(self.guild_id, None)
                return

            self.current = track

            try:
                if not self.voice or not self.voice.is_connected():
                    await self.send(
                        "Playback stopped because I'm no longer connected to voice."
                    )
                    continue

                stream = await resolve_stream(track)
                track.title = stream.get("title") or track.title
                track.source_url = stream.get("webpage_url") or track.source_url

                audio = discord.FFmpegPCMAudio(
                    stream["stream_url"],
                    before_options=FFMPEG_BEFORE_OPTIONS,
                    options=FFMPEG_OPTIONS,
                )
                source = discord.PCMVolumeTransformer(audio, volume=0.7)

                self.voice.play(source, after=self.after_play)
                now_playing_message = (
                    f"Now playing: **{clean_text(track.title)}** "
                    + f"(requested by {clean_text(track.requester, 80)})"
                )
                await self.send(now_playing_message)

                await self.next_track.wait()

                if self.play_error:
                    LOGGER.warning("Playback error: %s", self.play_error)
                    await self.send(
                        "Playback failed. Check the bot console for details."
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Could not play track: %s", track.title)
                await self.send(
                    f"Couldn't play **{clean_text(track.title)}**. Check the bot console for details."
                )
            finally:
                self.current = None
                self.queue.task_done()

    def after_play(self, error: Exception | None) -> None:
        self.play_error = error
        self.bot.loop.call_soon_threadsafe(self.next_track.set)

    async def send(self, message: str) -> None:
        if self.text_channel:
            try:
                await self.text_channel.send(message)
            except discord.DiscordException:
                pass

    def queued_tracks(self) -> list[Track]:
        return list(cast(Any, self.queue)._queue)

    def clear_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self.queue.task_done()

    async def stop(self) -> None:
        self.clear_queue()
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()

    async def disconnect(self) -> None:
        self.clear_queue()
        if self.voice and self.voice.is_connected():
            await self.voice.disconnect(force=True)
        self.voice = None

    async def destroy(self) -> None:
        await self.disconnect()
        if not self.player_task.done():
            self.player_task.cancel()


class MusicBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.music_states: dict[int, GuildMusicState] = {}

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            try:
                guild = discord.Object(id=int(guild_id))
            except ValueError as exc:
                raise SystemExit(
                    "DISCORD_GUILD_ID must be a numeric Discord server ID."
                ) from exc

            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash command(s) to guild {guild_id}.")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} global slash command(s).")

    def get_music_state(self, guild_id: int) -> GuildMusicState:
        state = self.music_states.get(guild_id)
        if state is None or state.player_task.done():
            state = GuildMusicState(self, guild_id)
            self.music_states[guild_id] = state
        return state

    def remove_music_state(self, guild_id: int) -> None:
        self.music_states.pop(guild_id, None)


bot = MusicBot()


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}.")


@bot.tree.command(
    name="play", description="Play a URL or search query in your voice channel."
)
@app_commands.describe(query="YouTube/Spotify/other URL, or search terms")
async def play(interaction: discord.Interaction, query: str) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    voice_state = interaction.user.voice
    if not voice_state or not voice_state.channel:
        await interaction.response.send_message(
            "Join a voice channel first.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    state = bot.get_music_state(interaction.guild.id)
    if (
        state.voice
        and state.voice.is_connected()
        and state.voice.channel != voice_state.channel
        and (
            state.voice.is_playing()
            or state.voice.is_paused()
            or state.current
            or state.queued_tracks()
        )
    ):
        await interaction.followup.send(
            "I'm already active in another voice channel. Join that channel first.",
            ephemeral=True,
        )
        return

    try:
        await state.connect(voice_state.channel, interaction.channel)
        tracks = await resolve_tracks(query, interaction.user.display_name)
    except UserFacingError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception:
        LOGGER.exception("Could not queue query")
        await interaction.followup.send(
            "Could not queue that. Check the bot console for details.", ephemeral=True
        )
        return

    for track in tracks:
        await state.queue.put(track)

    if len(tracks) == 1:
        await interaction.followup.send(f"Queued **{clean_text(tracks[0].title)}**.")
    else:
        await interaction.followup.send(f"Queued **{len(tracks)}** tracks.")


@bot.tree.command(name="queue", description="Show the current music queue.")
async def queue_command(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state:
        await interaction.response.send_message("Nothing is queued right now.")
        return

    lines: list[str] = []
    if state.current:
        lines.append(f"Now playing: **{clean_text(state.current.title)}**")

    queued = state.queued_tracks()
    if queued:
        lines.append("\nUp next:")
        for index, track in enumerate(queued[:10], start=1):
            lines.append(f"{index}. {clean_text(track.title)}")
        if len(queued) > 10:
            lines.append(f"…and {len(queued) - 10} more")

    await interaction.response.send_message(
        "\n".join(lines) if lines else "Nothing is queued right now."
    )


@bot.tree.command(name="nowplaying", description="Show the currently playing track.")
async def nowplaying(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state or not state.current:
        await interaction.response.send_message("Nothing is playing right now.")
        return

    await interaction.response.send_message(
        f"Now playing: **{clean_text(state.current.title)}**"
    )


@bot.tree.command(name="pause", description="Pause playback.")
async def pause(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state or not state.voice or not state.voice.is_playing():
        await interaction.response.send_message(
            "Nothing is playing right now.", ephemeral=True
        )
        return
    if not user_in_same_voice_channel(interaction, state):
        await interaction.response.send_message(
            "Join my voice channel first.", ephemeral=True
        )
        return

    state.voice.pause()
    await interaction.response.send_message("Paused playback.")


@bot.tree.command(name="resume", description="Resume playback.")
async def resume(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state or not state.voice or not state.voice.is_paused():
        await interaction.response.send_message(
            "Playback is not paused.", ephemeral=True
        )
        return
    if not user_in_same_voice_channel(interaction, state):
        await interaction.response.send_message(
            "Join my voice channel first.", ephemeral=True
        )
        return

    state.voice.resume()
    await interaction.response.send_message("Resumed playback.")


@bot.tree.command(name="skip", description="Skip the current track.")
async def skip(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if (
        not state
        or not state.voice
        or not (state.voice.is_playing() or state.voice.is_paused())
    ):
        await interaction.response.send_message(
            "Nothing is playing right now.", ephemeral=True
        )
        return
    if not user_in_same_voice_channel(interaction, state):
        await interaction.response.send_message(
            "Join my voice channel first.", ephemeral=True
        )
        return

    state.voice.stop()
    await interaction.response.send_message("Skipped the current track.")


@bot.tree.command(name="stop", description="Clear the queue and stop playback.")
async def stop(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state:
        await interaction.response.send_message(
            "Nothing is playing right now.", ephemeral=True
        )
        return
    if (
        state.voice
        and state.voice.is_connected()
        and not user_in_same_voice_channel(interaction, state)
    ):
        await interaction.response.send_message(
            "Join my voice channel first.", ephemeral=True
        )
        return

    await state.stop()
    await interaction.response.send_message("Stopped playback and cleared the queue.")


@bot.tree.command(name="about", description="Show bot info and credits.")
async def about(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"Local Discord Music Bot — self-hostable music bot signed by **{BOT_SIGNATURE}**."
    )


@bot.tree.command(name="leave", description="Disconnect the bot from voice.")
async def leave(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "Use this command inside a server.", ephemeral=True
        )
        return

    state = bot.music_states.get(interaction.guild.id)
    if not state:
        await interaction.response.send_message(
            "I'm not connected to voice right now.", ephemeral=True
        )
        return
    if (
        state.voice
        and state.voice.is_connected()
        and not user_in_same_voice_channel(interaction, state)
    ):
        await interaction.response.send_message(
            "Join my voice channel first.", ephemeral=True
        )
        return

    await state.destroy()
    bot.remove_music_state(interaction.guild.id)
    await interaction.response.send_message("Disconnected from voice.")


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "replace-with-your-discord-bot-token":
        raise SystemExit("Set DISCORD_TOKEN in your .env file before starting the bot.")

    bot.run(token)


if __name__ == "__main__":
    main()
