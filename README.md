# Makro Discord Music Bot

A self-hosted Discord music bot template. Anyone can clone it, add their own bot token, and run it for free on their own PC, home server, VPS, or Docker host.

## Features

- Slash commands: `/play`, `/skip`, `/pause`, `/resume`, `/stop`, `/leave`, `/queue`, `/nowplaying`, `/about`
- Plays YouTube URLs and search queries
- Plays many sites supported by `yt-dlp` such as SoundCloud, Bandcamp, Vimeo, Twitch clips, and more
- Optional Spotify track/album/playlist support by resolving Spotify metadata to YouTube audio
- Per-server queues
- No central hosting required
- Signed by Makro

> Note: Spotify does not provide raw audio streams for bots. Spotify links are converted into YouTube searches using Spotify metadata. Users need Spotify API credentials only if they want Spotify link support.

## Requirements

For local Python hosting:

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH`
- A Discord bot token
- Optional Spotify developer app credentials for Spotify links

For Docker hosting:

- Docker with the Docker Compose plugin
- A Discord bot token
- Optional Spotify developer app credentials for Spotify links

The Docker image installs FFmpeg and Opus support inside the container.

## Discord bot setup

1. Go to <https://discord.com/developers/applications>.
2. Create an application.
3. Open **Bot** and create/reset the token.
4. Enable the bot if needed, then copy the token into `.env`.
5. Open **OAuth2 > URL Generator**.
6. Select scopes:
   - `bot`
   - `applications.commands`
7. Select bot permissions:
   - `Connect`
   - `Speak`
   - `Use Voice Activity`
   - `Send Messages`
   - `Use Slash Commands`
8. Open the generated invite URL and add the bot to your server.

## Install

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Configure

Copy the example environment file:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
DISCORD_TOKEN=your-token-here
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
MAX_PLAYLIST_ITEMS=50
LOG_LEVEL=INFO
# Optional: sync slash commands instantly to one server instead of globally.
# DISCORD_GUILD_ID=your-server-id
```

## Run locally with Python

```bash
python bot.py
```

## Run with Docker Compose

This is the recommended setup for servers, home labs, NAS boxes, VPS hosts.
The bot does not expose any inbound ports; it only needs outbound internet access to Discord, YouTube/other media sites, and Spotify if enabled.

1. Install Docker and the Compose plugin.
2. Clone this repository.
3. Create your environment file:

   ```bash
   cp .env.example .env
   nano .env
   ```

4. Start the bot:

   ```bash
   docker compose up -d --build
   ```

5. Watch logs:

   ```bash
   docker compose logs -f makro-music
   ```

Useful Docker commands:

```bash
# Stop the bot
docker compose down

# Restart the bot
docker compose restart

# Rebuild after pulling code updates
docker compose up -d --build
```

The Compose file uses `restart: unless-stopped`, so Docker will restart the bot after reboots or container crashes unless you manually stop it.

If slash commands do not appear quickly, add `DISCORD_GUILD_ID` to `.env` with your Discord server ID and restart the container. Guild-scoped slash commands usually sync much faster than global commands.

## Notes for public/self-hosted use

- You do not need to open or forward any router ports.
- Leave `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` blank unless you create Spotify API credentials.
- YouTube and other media sites can change behavior over time.

## Commands

- `/play query:<url or search>` - join your voice channel and queue music
- `/queue` - show the next queued tracks
- `/nowplaying` - show the current track
- `/pause` - pause playback
- `/resume` - resume playback
- `/skip` - skip the current track
- `/stop` - clear the queue and stop playback
- `/leave` - disconnect from voice
- `/about` - show bot info

## Safety notes

- Never share `.env`; it contains your Discord token and optional Spotify credentials.
- Keep `Privileged Gateway Intents` disabled unless you add features that truly need them.
- The bot rejects local/private network URLs to reduce the risk of someone using `/play` to make your machine request internal services.
- Playback control commands require the user to be in the same voice channel as the bot.
- Unexpected technical errors are logged to the local console instead of being posted into Discord.

---

Made with care by **Makro**.
