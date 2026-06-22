# Local Discord Music Bot

A self-hosted Discord music bot template. Anyone can clone it, add their own bot token, and run it locally for their own Discord server.

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

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH`
- A Discord bot token
- Optional Spotify developer app credentials for Spotify links

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
SPOTIFY_CLIENT_ID=optional
SPOTIFY_CLIENT_SECRET=optional
MAX_PLAYLIST_ITEMS=50
```

## Run

```bash
python bot.py
```

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
