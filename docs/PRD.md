# Coolio Music - Product Requirements Document

## Vision

Build a fully automated YouTube channel that publishes multi-hour study/productivity music sets. The system generates original music, creates visuals, composes videos, and uploads them on a scheduled basis with minimal human intervention.

## Target Aesthetic

- **Genres**: House, electronic, lofi, Berlin techno, minimal, jungle, ambient
- **Visual Style**: Spinning vinyl record with custom artwork/graphics
- **Video Format**: 2+ hour continuous mixes with DJ-style crossfaded tracks
- **Audience**: Students, remote workers, focus/productivity seekers

---

## Core Constraints

| Constraint | Value | Rationale |
|------------|-------|-----------|
| **Track Duration** | 2–8 minutes (hard range) | Balances variety with API cost efficiency |
| **Video Duration** | 1–2+ hours | Long-form content performs well for study/focus |
| **Genre Isolation** | Strict per-video | No mixing jungle tracks into a house set |

---

## Two-Agent Architecture: Curator + Generator

The system uses two specialized AI agents with distinct responsibilities. This separation of concerns mirrors real-world music production: **curating/DJing** is a different skill than **creating/producing**.

### Agent Flow

```
User Concept ("Berlin techno, minimal, hypnotic focus")
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                      CURATOR AGENT                           │
│                                                              │
│  "I need 5 tracks for a minimal techno set"                 │
│   → Queries R2 library by genre, BPM, energy                │
│   → Finds 2 existing tracks that fit                        │
│   → Identifies 3 gaps that need new generation              │
│   → Outputs: Curation Plan (reused tracks + generation reqs)│
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     GENERATOR AGENT                          │
│                                                              │
│  "Generate 3 new tracks with these specs"                   │
│   → Receives specs from Curator (not raw user concept)      │
│   → Crafts detailed prompts for each new track              │
│   → Focuses purely on music creation, not curation          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
            Final Track List (2 reused + 3 new)
```

---

### Curator Agent

The Curator Agent acts as a **DJ digging through crates**. It interprets the user's concept and decides what tracks are needed, checking the library first before requesting new generation.

**Responsibilities:**

1. **Interpret Video Concept**
   - Parse user's high-level prompt (e.g., "Berlin techno, minimal, hypnotic focus")
   - Determine genre, mood, energy arc, and target duration
   - Define the BPM range for the set

2. **Query Library**
   - Search R2 library for existing tracks matching the concept
   - **Hard Filter**: Filter by genre and recency (e.g., exclude tracks used in last 7 days)
   - Retrieve candidate list of track metadata for the LLM

3. **Plan Track Sequence**
   - The LLM reviews the candidate list against the user concept
   - **LLM Decision**: Selects tracks to reuse based on vibe, energy, and flow (no hard-coded scoring)
   - Fills gaps by requesting new generation where no suitable track exists
   - Output ordered list of track slots with:
     - Track role (intro, build, peak, sustain, cooldown, outro)
     - Duration range (2–8 min)
     - BPM target (for flow between tracks)
     - Energy level (1–10 scale)
   - For each slot: either assign an existing track OR request generation

4. **Output Curation Plan**
   - List of reused tracks (with R2 references)
   - List of generation requests (specs for Generator Agent)

**Curator Output Schema:**

```json
{
  "video_concept": "Berlin techno, minimal, hypnotic focus",
  "genre": "berlin_techno",
  "target_duration_minutes": 60,
  "bpm_range": [124, 130],
  "track_slots": [
    {
      "order": 1,
      "role": "intro",
      "duration_ms": 240000,
      "bpm_target": 124,
      "energy": 3,
      "source": "library",
      "track_id": "abc123"
    },
    {
      "order": 2,
      "role": "build",
      "duration_ms": 300000,
      "bpm_target": 126,
      "energy": 5,
      "source": "generate",
      "generation_request": {
        "genre": "berlin_techno",
        "subgenre": "minimal_hypnotic",
        "mood": "driving, hypnotic",
        "instruments": ["filtered pads", "sparse kicks", "rolling hi-hats"],
        "exclude": ["vocals", "melodic hooks"]
      }
    }
  ]
}
```

---

### Generator Agent

The Generator Agent acts as a **music producer**. It receives specific track requests from the Curator and crafts detailed prompts optimized for the music generation providers.

**Responsibilities:**

1. **Receive Generation Requests**
   - Accept specs from Curator Agent (genre, mood, instruments, exclusions)
   - Does NOT interpret raw user concepts directly

2. **Craft Detailed Prompts**
   - Layer multiple descriptors (genre + BPM + instruments + mood + exclusions)
   - Tailor prompts to the selected provider (ElevenLabs vs Stable Audio)
   - Avoid trademarked terms for ElevenLabs

3. **Select Provider**
   - Choose between ElevenLabs and Stable Audio based on track role and budget
   - Hero tracks (intro, peak, outro) → ElevenLabs
   - Sustain/atmospheric tracks → Stable Audio

**Generator Output Schema:**

```json
{
  "tracks_to_generate": [
    {
      "order": 2,
      "role": "build",
      "provider": "stable_audio",
      "duration_ms": 300000,
      "bpm_target": 126,
      "energy": 5,
      "prompt": "Minimal Berlin techno at 126 BPM with filtered analog pads, sparse kick drum pattern, rolling hi-hats, and deep sub-bass. Hypnotic and driving atmosphere with no vocals, no melodic hooks, steady groove."
    }
  ]
}
```

---

## Dual-Provider API System

The system rotates between two providers to balance cost and quality while keeping music unique.

### Supported Providers

| Provider | Strengths | Cost | Max Duration | Status |
|----------|-----------|------|--------------|--------|
| **ElevenLabs** | Highest quality, composition plans, great structure | ~$0.30/min | 5 min | Active |
| **Stable Audio** | Strong electronic genres, cheaper, different sonic character | $0.20/track | 190 sec | Active |

### Why Two Providers?

1. **Cost Rotation**: Alternate between providers to reduce per-video spend
2. **Sonic Variety**: Each provider has distinct characteristics, preventing repetitive sound
3. **Quota Management**: When one provider hits limits, fall back to the other
4. **Genre Strengths**: ElevenLabs excels at structured compositions; Stable Audio shines on electronic textures

### Provider Selection Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    TRACK ROLE ROUTING                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Hero Tracks (intro, peak, outro)                          │
│   └── ElevenLabs (structured, high quality)                 │
│                                                              │
│   Sustain/Build/Atmospheric Tracks                          │
│   └── Stable Audio (textural, cost-efficient)               │
│                                                              │
│   Fallback on Quota/Error                                   │
│   └── Switch to other provider automatically                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Provider Interface

Both providers implement a common interface:

```python
class MusicProvider(Protocol):
    name: str
    max_duration_ms: int
    
    def generate(self, prompt: str, duration_ms: int) -> GeneratedTrack: ...
    def get_quota(self) -> QuotaInfo: ...
    def estimate_cost(self, duration_ms: int) -> float: ...
```

---

## Asset & Session Storage (Cloudflare R2)

The system uses Cloudflare R2 as the single source of truth, storing both reusable components (tracks) and finished products (sessions).

### Storage Organization

```
r2://coolio-storage/
├── library/                    # Reusable individual assets
│   ├── tracks/
│   │   ├── berlin_techno/
│   │   │   ├── track_abc123.mp3
│   │   │   └── track_abc123.json
│   │   └── ...
│   └── index.json             # Searchable track index
│
└── sessions/                   # Complete video releases
    ├── session_20231125_A1B2/  # Unique session ID
    │   ├── session.json        # Full metadata (prompt, plan, youtube info)
    │   ├── audio/
    │   │   ├── final_mix.mp3   # Mastered audio
    │   │   ├── tracklist.txt
    │   │   └── stems/          # Individual track files used
    │   ├── visuals/
    │   │   ├── base_artwork.png
    │   │   ├── thumbnail.jpg
    │   │   ├── video_loop.mp4
    │   │   └── prompt.txt
    │   └── distribution/
    │       ├── video_full.mp4  # Final render (optional, if not composed on fly)
    │       └── youtube_metadata.json
```

### Library Query Flow

Each track's JSON sidecar includes:

```json
{
  "id": "abc123",
  "genre": "berlin_techno",
  "subgenre": "minimal_hypnotic",
  "prompt": "Original generation prompt...",
  "duration_ms": 240000,
  "bpm": 126,
  "key": "Am",
  "energy": 5,
  "provider": "elevenlabs",
  "quality_rating": 4,
  "times_used": 3,
  "created_at": "2024-01-15T10:30:00Z",
  "composition_plan": { ... }
}
```

### Library Query Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Agent needs    │     │  Query library  │     │  Found match?   │
│  track for      │────►│  by genre, BPM, │────►│                 │
│  "minimal intro"│     │  energy, duration│     │  Yes ──► Reuse  │
└─────────────────┘     └─────────────────┘     │  No  ──► Generate│
                                                 └─────────────────┘
```

---

## Development Phases

### Phase 1: Music Generation Engine ✅ (Complete)

Build the core music generation pipeline with multi-provider support.

**Goals:**
- Generate individual 2–8 minute tracks programmatically
- Support multiple styles (house, minimal, berlin techno, deep house, detroit techno, etc)
- Store tracks with metadata for later composition
- CLI interface for manual generation and iteration
- AI agent for DJ-style track planning

**Deliverables:**
- `coolio generate` command with AI-planned track sequences
- `coolio plan` command to preview without generating
- Setup both providers (ElevenLabs + Stable Audio)

---

### Phase 2: Audio Asset Library & R2 Integration ✅ (Complete)

Build the track library system for organizing, storing, and reusing generated audio tracks.

**Scope:** Audio assets only (tracks + metadata). Visual/video assets are out of scope for this phase.

**What was built:**
- **R2 Storage** (`src/coolio/library/storage.py`): Thin boto3 wrapper for Cloudflare R2
- **Track Metadata** (`src/coolio/library/metadata.py`): Rich metadata schema including:
  - Identity: `track_id`, `title` (human-readable song names like "Recursive Patterns")
  - Musical: `genre`, `subgenre`, `bpm`, `duration_ms`, `energy`, `role`
  - Provenance: `provider`, `prompt_hash`, `session_id`
  - Timestamps: `created_at`, `last_used_at`, `usage_count` (for curator agent filtering)
- **Auto-upload**: Generator automatically uploads tracks to R2 after generation
- **AI Track Naming**: Agent generates evocative track titles (not generic names)
- **Library Query** (`src/coolio/library/query.py`): Query tracks by genre with recency filtering

**Storage Structure:**
```
r2://cooliomusicstorage/
└── library/tracks/{genre}/{track_id}.mp3
└── library/tracks/{genre}/{track_id}.json
```

**Environment Variables:**
```
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=cooliomusicstorage
R2_ENDPOINT_URL=https://ccbe407ceb8cc78fc1ec28cbb02894b0.r2.cloudflarestorage.com
```

---

### Phase 2.5: Curator-Generator Unification ✅ (Complete)

Unified the architecture to implement the two-agent sequential flow.

**What was built:**
- **Unified Data Model** (`src/coolio/models.py`):
  - `TrackSlot`: Single dataclass for all track planning (replaces separate TrackPlan/CurationSlot)
  - `SessionPlan`: Complete session plan with built-in cost estimation
- **Curator Agent** (`src/coolio/agents/curator.py`): Always runs first, queries library, plans session
- **Unified CLI Flow**:
  - `coolio generate` is now the unified entry point
  - Always runs through Curator (library query + planning)
  - `--no-library` flag to skip library lookup
  - `--genre` is now required
  - `curate` command kept as hidden alias for backwards compatibility
- **Simplified Generator** (`src/coolio/music/generator.py`):
  - Single `execute_plan()` method replaces separate methods
  - Fixed GeneratedTrack bug for reused tracks
  - Proper metadata_path handling

**CLI Commands:**
- `coolio generate "concept"` - Full flow with library reuse (genre inferred by LLM)
- `coolio generate "concept" --no-library` - Generate all from scratch
- `coolio plan "concept"` - Preview plan without generating
- `coolio mix <session_dir>` - Mix session tracks into final MP3
- `coolio library verify` - Test R2 connection
- `coolio library list` - List tracks in library

---

### Phase 3: Audio Composition & Mixing ✅ (Complete)

Implemented the post-processing pipeline that combines session tracks into seamless mixes.

**What was built:**
- **MixComposer** (`src/coolio/mixer.py`): Combines tracks with crossfade transitions
  - Configurable crossfade duration (default 5 seconds)
  - Automatic silence trimming (leading/trailing)
  - Peak normalization across full mix
  - 320kbps MP3 export
- **Tracklist Generator**: Creates `tracklist.txt` with timestamps
- **CLI Integration**: `coolio mix <session_dir>` command

**Tech:**
- `pydub` for audio manipulation
- `FFmpeg` for MP3 encoding

---

### Phase 4: Visual & Thumbnail Generation (In Progress - Experimentation)

Generate a 1920x1080 base image via AI, then animate it into a looping video for the duration of the mix.

**Current Status:** Experimentation phase — evaluating AI image generation and animation APIs before full implementation. Aesthetic will be defined through system prompt iteration once we find tools we like.

**Goals:**
- Generate 1920x1080 base artwork via AI image generation
- Animate the base image into a seamless loop via AI animation API
- Define visual aesthetic through prompt engineering (system prompt TBD)
- Experiment with different providers to find the best quality/cost balance

**Two-Step Pipeline:**

```
┌─────────────────────────────────────────────────────────────┐
│                   VISUAL GENERATION FLOW                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Step 1: Image Generation (1920x1080)                      │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  Concept + System Prompt                             │   │
│   │         │                                            │   │
│   │         ▼                                            │   │
│   │  ┌─────────────┐                                     │   │
│   │  │ AI Image    │  Candidates:                        │   │
│   │  │ Generator   │  • Flux (fal.ai)                   │   │
│   │  │             │  • DALL-E 3                         │   │
│   │  │             │  • Midjourney API                   │   │
│   │  │             │  • Ideogram                         │   │
│   │  └──────┬──────┘                                     │   │
│   │         │                                            │   │
│   │         ▼                                            │   │
│   │    base_artwork.png (1920x1080)                      │   │
│   └─────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│   Step 2: Animation                                          │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  base_artwork.png + animation prompt                 │   │
│   │         │                                            │   │
│   │         ▼                                            │   │
│   │  ┌─────────────┐                                     │   │
│   │  │ AI Animation│  Candidates:                        │   │
│   │  │ API         │  • Runway Gen-3                     │   │
│   │  │             │  • Kling                            │   │
│   │  │             │  • Luma Dream Machine               │   │
│   │  │             │  • Pika                             │   │
│   │  │             │  • Stable Video Diffusion           │   │
│   │  └──────┬──────┘                                     │   │
│   │         │                                            │   │
│   │         ▼                                            │   │
│   │    animated_loop.mp4                                 │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Experimentation Checklist:**
- [ ] Test image generation APIs (Flux, DALL-E 3, etc.) for 1920x1080 output
- [ ] Test animation APIs (Runway, Kling, Luma, etc.) with static image input
- [ ] Evaluate looping quality (seamless vs jarring)
- [ ] Evaluate cost per generation
- [ ] Define system prompt / aesthetic direction
- [ ] Select final providers for implementation

**Aesthetic Direction (TBD after experimentation):**
- Spinning vinyl / record player aesthetic (original concept)
- OR: Abstract visualizer responding to genre
- OR: Ambient scene (rain on window, cityscape, etc.)
- Final aesthetic will be locked in after prompt iteration

**Deliverables (after experimentation):**
- Selected image generation provider + system prompt
- Selected animation provider + animation prompt template
- Visual generation module (`src/coolio/visuals/`)
- Thumbnail generator (crop/resize from base image)

---

### Phase 5: Video Composition

Combine animated visual with mixed audio into final video.

**Goals:**
- Layer mixed audio over looping animated visual
- Add subtle effects (vinyl dust, ambient lighting) if desired
- Render to YouTube-optimized format (1080p/4K)

**Tech:**
- MoviePy for composition
- FFmpeg for encoding

**Deliverables:**
- Video composer module
- Render pipeline with quality presets

---

### Phase 6: YouTube Automation

Automate the upload and publishing process.

**Goals:**
- Upload video with metadata
- Set thumbnail (generated in Phase 4)
- Schedule publish time
- Generate SEO-optimized titles, descriptions, tags

**Tech:**
- YouTube Data API v3
- Google OAuth for authentication

**Deliverables:**
- YouTube uploader module
- Metadata generator (titles, descriptions, tags)
- Scheduling system

---

### Phase 7: Full Pipeline & Scheduling

Orchestrate the entire process end-to-end.

**Goals:**
- Daily/weekly automated video generation
- Quality validation checkpoints
- Notification on completion
- Error handling and retry logic

**Tech Options:**
- n8n for visual workflow orchestration
- Python + cron for simpler approach
- Prefect for Python-native orchestration

**Deliverables:**
- Pipeline orchestrator
- Scheduler (cron or n8n integration)
- Monitoring and notifications

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           COOLIO MUSIC PIPELINE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   User Prompt ("Berlin techno, minimal, hypnotic focus")                    │
│                                    │                                         │
│                                    ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                         CURATOR AGENT                                 │  │
│   │                                                                        │  │
│   │   • Interprets concept (genre, mood, energy arc)                      │  │
│   │   • Queries R2 library for existing tracks                            │  │
│   │   • Selects reusable tracks OR requests new generation                │  │
│   │   • Outputs: Curation Plan                                            │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│          ┌─────────────────────────┴─────────────────────────┐              │
│          │                                                    │              │
│          ▼                                                    ▼              │
│   ┌─────────────────┐                              ┌─────────────────────┐  │
│   │  Track Library  │                              │  GENERATOR AGENT    │  │
│   │  (Cloudflare R2)│                              │                     │  │
│   │                 │                              │ • Receives specs    │  │
│   │ genres/         │                              │ • Crafts prompts    │  │
│   │   berlin_techno/│◄── Reuse ──┐                │ • Selects provider  │  │
│   │   house/        │            │                └──────────┬──────────┘  │
│   │   lofi/         │            │                           │              │
│   └────────┬────────┘            │                           ▼              │
│            │                     │                ┌─────────────────────┐   │
│            │                     │                │  Music Providers    │   │
│            │                     │                │                     │   │
│            │                     │                │ • ElevenLabs        │   │
│            │                     │                │   (hero tracks)     │   │
│            │                     │                │ • Stable Audio      │   │
│            │                     │                │   (sustain/atmo)    │   │
│            │                     │                └──────────┬──────────┘   │
│            │                     │                           │              │
│            │                     └───────────────────────────┤              │
│            │                                                 │              │
│            └─────────────────────┬───────────────────────────┘              │
│                                  │                                           │
│                                  ▼                                           │
│                        ┌─────────────────────────┐                          │
│                        │     Mix Composer        │                          │
│                        │                         │                          │
│                        │ • Execute transitions   │                          │
│                        │ • Crossfades & filters  │                          │
│                        │ • Level normalization   │                          │
│                        │ • Generate tracklist    │                          │
│                        └────────────┬────────────┘                          │
│                                     │                                        │
│          ┌──────────────────────────┴──────────────────────────┐            │
│          ▼                                                      │            │
│   ┌─────────────────────────────────────────────────────────┐  │            │
│   │              Base Image Generator (DALL-E, etc.)         │  │            │
│   │                         │                                 │  │            │
│   │           ┌─────────────┴─────────────┐                  │  │            │
│   │           ▼                           ▼                  │  │            │
│   │    ┌─────────────┐            ┌─────────────┐           │  │            │
│   │    │  Thumbnail  │            │  Animator   │           │  │            │
│   │    │  (+ text)   │            │ (→ loop.mp4)│           │  │            │
│   │    └──────┬──────┘            └──────┬──────┘           │  │            │
│   └───────────┼──────────────────────────┼──────────────────┘  │            │
│               │                          │                      │            │
│               │                          ▼                      │            │
│               │                   ┌─────────────┐              │            │
│               │                   │   Video     │              │            │
│               └──────────────────►│  Composer   │◄─────────────┘            │
│                                   └──────┬──────┘                           │
│                                    │                                        │
│                                    ▼                                        │
│                        ┌─────────────────────────┐                          │
│                        │    YouTube Uploader     │                          │
│                        │                         │                          │
│                        │ • Upload video          │                          │
│                        │ • Set thumbnail         │                          │
│                        │ • Schedule publish      │                          │
│                        │ • SEO metadata          │                          │
│                        └─────────────────────────┘                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology | Status |
|-----------|------------|--------|
| Session Planner | OpenRouter (Claude, GPT, etc.) | ✅ Active |
| Music Generation | ElevenLabs + Stable Audio | ✅ Active |
| Asset Storage (Audio) | Cloudflare R2, boto3 | ✅ Active |
| Library Query | Python with R2 filtering | ✅ Active |
| Audio Mixing | pydub, FFmpeg | ✅ Active |
| Base Image Generation | TBD (Flux, DALL-E 3, Ideogram, etc.) | 🔬 Experimenting |
| Visual Animation | TBD (Runway, Kling, Luma, etc.) | 🔬 Experimenting |
| Thumbnail Composer | Pillow (crop from base image) | Phase 4 |
| Video Composition | MoviePy, FFmpeg | Phase 5 |
| YouTube Upload | YouTube Data API v3 | Phase 6 |
| Orchestration | Python/cron → n8n | Phase 7 |

---

## Project Structure

```
cooliomusic/
├── src/coolio/
│   ├── cli.py              # CLI entry point (coolio command)
│   ├── models.py           # Shared data models (TrackSlot, SessionPlan)
│   ├── config.py           # Settings (API keys, R2 config)
│   ├── djcoolio.py         # Session planner (concept → track plan)
│   ├── generator.py        # Orchestrates execution (reuse + generation)
│   ├── mixer.py            # Audio mixing (crossfade, normalize)
│   ├── providers/
│   │   ├── base.py         # Provider protocol
│   │   ├── elevenlabs.py
│   │   └── stable_audio.py
│   ├── library/
│   │   ├── storage.py      # R2 client (boto3 wrapper)
│   │   ├── metadata.py     # TrackMetadata schema
│   │   └── query.py        # Library querying with filters
│   ├── visuals/            # (Phase 4 - in progress)
│   ├── video/              # (Phase 5 - planned)
│   ├── youtube/            # (Phase 6 - planned)
│   └── pipeline/           # (Phase 7 - planned)
├── experiments/visuals/    # Visual generation experiments
├── output/audio/           # Local session output (gitignored)
├── docs/                   # Documentation
└── tests/
```

---

## Success Metrics

| Phase | Metric |
|-------|--------|
| Phase 1 | Generate 10+ tracks with consistent quality |
| Phase 2 | All generated tracks stored in R2 with queryable metadata |
| Phase 3 | Produce seamless 1-hour mix with proper transitions |
| Phase 4 | Base image → thumbnail + animated visual working |
| Phase 5 | Complete video with spinning vinyl visual |
| Phase 6 | First video uploaded to YouTube |
| Phase 7 | Automated daily generation for 1 week |
| Monetization | YouTube Partner Program (1K subs, 4K watch hours) |
