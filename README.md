# Coolio Music

Automated YouTube music channel generator. Creates long-form study/productivity music mixes with AI-generated audio, thumbnails, and videos.

## Overview

Coolio generates complete YouTube-ready content:

1. **Plan** — AI curator decides track order, reuses library tracks, plans new generation
2. **Generate** — Creates tracks via Stable Audio (~80%) / ElevenLabs (~20%) + thumbnail via Flux
3. **Mix** — Combines tracks with crossfades into a seamless 60-minute mix
4. **Compose** — Creates final video with waveform visualization and fade-in

All assets are stored in Cloudflare R2 for reuse across sessions.

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/cooliomusic.git
cd cooliomusic

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Install FFmpeg (required for mixing/video)
brew install ffmpeg  # macOS
```

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required API keys:

| Service | Purpose | Cost | Get Key |
|---------|---------|------|---------|
| **OpenRouter** | LLM for planning/Image Gen | ~$0.01/plan | https://openrouter.ai/keys |
| **Stable Audio** | Music generation | $0.20/track | https://stableaudio.com |
| **ElevenLabs** | Music generation | ~$1.20/track | https://elevenlabs.io |
| **Cloudflare R2** | Storage | Free tier | https://dash.cloudflare.com |

## Quick Start

```bash
# 1. Preview a session plan (no cost)
coolio plan "Berlin techno, minimal, hypnotic focus music"

# 2. Generate tracks + thumbnail (~$5 for 60 min)
coolio generate "Berlin techno, minimal, hypnotic focus music"

# 3. Mix into single audio file
coolio mix output/audio/session_XXXXXXXX

# 4. Compose final video with waveform + fade-in
coolio compose output/audio/session_XXXXXXXX

# Video is uploaded to R2, ready for manual YouTube upload
```

## Commands

### Core Workflow

| Command | Description |
|---------|-------------|
| `coolio plan <concept>` | Preview session plan without spending credits |
| `coolio generate <concept>` | Generate tracks, thumbnail, upload to R2 |
| `coolio download <session_id>` | Download session from R2 for local mixing |
| `coolio mix <session_dir>` | Mix tracks with crossfades, upload to R2 |
| `coolio compose <session_dir>` | Create video with waveform, upload to R2 |

### Library Management

| Command | Description |
|---------|-------------|
| `coolio library list` | List tracks in the R2 library |
| `coolio library sessions` | List sessions in R2 |
| `coolio library verify` | Verify R2 connection and list objects |

### Utilities

| Command | Description |
|---------|-------------|
| `coolio config` | Show current configuration |
| `coolio models` | List available LLM models |
| `coolio providers` | Show music generation providers |

## Options

### Generate Options

```bash
coolio generate "concept" \
  --duration 60 \            # Target duration in minutes (default: 60)
  --model "anthropic/..." \  # OpenRouter model ID
  --exclude-days 7 \         # Don't reuse tracks used in last N days
  --no-library \             # Skip library query, generate all new
  --skip-audio \             # Generate plan only, no audio
  --skip-upload \            # Don't upload new tracks to R2
  --skip-visual \            # Skip thumbnail generation
  --visual-hint "..."        # Style hint for thumbnail
```

### Mix Options

```bash
coolio mix <session_dir> \
  --crossfade 5000 \         # Crossfade duration in ms (default: 5000)
  --no-normalize \           # Skip audio normalization
  --output my_mix.mp3 \      # Custom output filename
  --skip-upload              # Don't upload to R2
```

### Compose Options

```bash
coolio compose <session_dir> \
  --waveform-color "white@0.9" \  # Waveform core color (FFmpeg format)
  --skip-metadata \               # Skip YouTube metadata generation
  --skip-upload                   # Don't upload to R2
```

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                      USER CONCEPT                            │
│  "Berlin techno, minimal, hypnotic focus music"             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  PLAN: LLM (DJ Coolio) queries library, decides:            │
│  • Which existing tracks to reuse (free)                    │
│  • Which new tracks to generate ($)                         │
│  • Track order, BPM flow, energy arc                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  GENERATE: For each slot:                                    │
│  • Library track → Download from R2 (free)                  │
│  • New track → Stable Audio (~80%) or ElevenLabs (~20%)    │
│  Also: Generate thumbnail via Flux                          │
│  Upload: tracks + metadata to R2                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  MIX: Combine all tracks                                     │
│  • Crossfade transitions (default 5s)                       │
│  • Trim silence, normalize levels                           │
│  • Generate tracklist with timestamps                       │
│  Upload: final_mix.mp3 to R2                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  COMPOSE: Create YouTube video                               │
│  • Static thumbnail as background                           │
│  • Animated glowing waveform overlay (centered)             │
│  • 5-second fade-in from black                              │
│  • Generate YouTube metadata (title, description, tags)     │
│  • Auto-compress thumbnail for upload (<2MB)                │
│  Upload: final_video.mp4 to R2                              │
└─────────────────────────────────────────────────────────────┘
```

## Library System

The key cost-saving feature is **track reuse**. Every generated track is stored in R2 with metadata (genre, BPM, energy, mood). Future sessions query this library first:

```
Session 1: Generate 14 tracks (~$5) → 60 min mix
Session 2: Reuse 5 tracks, generate 9 → ~$4
Session 3: Reuse 10 tracks, generate 4 → ~$2
```

Tracks used within the last 7 days are excluded to prevent repetition across videos.

Tracks are organized by genre:
```
r2://cooliomusic/
  library/
    tracks/
      techno/
        abc123.mp3
        abc123.json  # metadata
      house/
        ...
  sessions/
    session_20231125_123456/
      session.json
      thumbnail.png
      audio/
        final_mix.mp3
        tracklist.txt
      video/
        final_video.mp4
```