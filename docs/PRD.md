# Coolio Music - Product Requirements Document

## Vision

Build a fully automated YouTube channel that publishes multi-hour study/productivity music sets. The system generates original music, creates visuals, composes videos, and uploads them on a scheduled basis with minimal human intervention.

## Target Aesthetic

- **Genres**: House, electronic, lofi, Berlin techno, minimal
- **Visual Style**: Spinning vinyl record with custom artwork/graphics
- **Video Format**: 2+ hour continuous mixes with crossfaded tracks
- **Audience**: Students, remote workers, focus/productivity seekers

---

## Development Phases

### Phase 1: Music Generation Engine (Current)

Build the core music generation pipeline using ElevenLabs API.

**Goals:**
- Generate individual 3-5 minute tracks programmatically
- Support multiple styles (house, lofi, minimal, berlin techno)
- Store tracks with metadata for later composition
- CLI interface for manual generation and iteration

**Deliverables:**
- `coolio generate` command to create single tracks
- `coolio batch` command to create multiple tracks
- Prompt templates for each genre
- Local storage with metadata tracking

---

### Phase 2: Visual Generation

Create the visual elements for videos.

**Goals:**
- Generate vinyl record artwork per video/genre
- Create looping animation (spinning vinyl)
- Consistent aesthetic across videos

**Tech Options:**
- DALL-E 3 API for artwork generation
- Leonardo.ai for more control
- FFmpeg for animation (Ken Burns, rotation)
- Stable Diffusion for local generation

**Deliverables:**
- Visual generator module
- Spinning vinyl loop renderer
- Genre-specific visual templates

---

### Phase 3: Audio Composition

Stitch multiple tracks into cohesive long-form mixes.

**Goals:**
- Crossfade between tracks (2-4 second transitions)
- Normalize audio levels
- Generate tracklist with timestamps
- Target 2+ hour final duration

**Tech:**
- pydub for audio manipulation
- FFmpeg for final encoding

**Deliverables:**
- Audio composer module
- Crossfade and normalization pipeline
- Tracklist generator

---

### Phase 4: Video Composition

Combine audio and visuals into final video.

**Goals:**
- Layer audio over looping visual
- Add subtle effects (vinyl dust, ambient lighting)
- Render to YouTube-optimized format (1080p/4K)

**Tech:**
- MoviePy for composition
- FFmpeg for encoding

**Deliverables:**
- Video composer module
- Render pipeline with quality presets

---

### Phase 5: Thumbnail Generation

Create eye-catching thumbnails for each video.

**Goals:**
- Consistent brand aesthetic
- Genre-specific styling
- Text overlay (title, duration, vibe)

**Tech:**
- DALL-E 3 for base image
- Pillow for text overlay and composition

**Deliverables:**
- Thumbnail generator module
- Template system for consistent branding

---

### Phase 6: YouTube Automation

Automate the upload and publishing process.

**Goals:**
- Upload video with metadata
- Set thumbnail
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

## Tech Stack

| Component | Technology | Status |
|-----------|------------|--------|
| Music Generation | ElevenLabs API | Phase 1 |
| Visual Generation | DALL-E 3 / Leonardo.ai | Phase 2 |
| Audio Processing | pydub, FFmpeg | Phase 3 |
| Video Composition | MoviePy, FFmpeg | Phase 4 |
| Thumbnail | DALL-E 3, Pillow | Phase 5 |
| YouTube Upload | YouTube Data API v3 | Phase 6 |
| Asset Storage | Local → Cloudflare R2 | Incremental |
| Database | SQLite → PostgreSQL | Incremental |
| Orchestration | Python/cron → n8n | Phase 7 |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      COOLIO MUSIC PIPELINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│   │  Music   │   │  Visual  │   │  Video   │   │ YouTube  │    │
│   │Generator │──►│Generator │──►│ Composer │──►│ Uploader │    │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘    │
│        │              │              │              │            │
│        ▼              ▼              ▼              ▼            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                    Storage Layer                         │   │
│   │         (Local filesystem → Cloudflare R2)              │   │
│   └─────────────────────────────────────────────────────────┘   │
│        │                                                         │
│        ▼                                                         │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   Metadata Store                         │   │
│   │              (SQLite → PostgreSQL)                       │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
cooliomusic/
├── src/coolio/           # Main package
│   ├── core/             # Shared utilities, models, config
│   ├── music/            # Music generation (Phase 1)
│   ├── visuals/          # Visual generation (Phase 2)
│   ├── video/            # Video composition (Phase 3-4)
│   ├── youtube/          # YouTube integration (Phase 6)
│   ├── storage/          # Storage backends (incremental)
│   └── pipeline/         # Orchestration (Phase 7)
├── prompts/              # Prompt templates
├── templates/            # Visual templates
├── output/               # Generated content (gitignored)
├── data/                 # Database (gitignored)
└── docs/                 # Documentation
```

---

## Success Metrics

- **Phase 1**: Generate 10 tracks with consistent quality
- **Phase 2-4**: Produce first complete 2-hour video
- **Phase 5-6**: Upload first video to YouTube
- **Phase 7**: Run automated daily generation for 1 week
- **Monetization**: Reach YouTube Partner Program requirements (1K subs, 4K watch hours)

---

## Open Questions

1. **Copyright**: Confirm ElevenLabs music is cleared for YouTube monetization
2. **Quality Gate**: Manual review vs. automated quality scoring
3. **Branding**: Channel name, visual identity, thumbnail style
4. **Content Strategy**: How many videos per week? What mix of genres?

