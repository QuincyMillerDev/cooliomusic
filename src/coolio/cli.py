"""CLI interface for Coolio music generation."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from coolio.config import get_settings
from coolio.djcoolio import generate_session_plan
from coolio.library.query import LibraryQuery
from coolio.library.storage import R2Storage
from coolio.models import SessionPlan
from coolio.generator import MusicGenerator
from coolio.visuals import (
    KlingAIVideoGenerator,
    VisualGenerator,
    generate_video_motion_prompt,
    generate_visual_prompt,
)

app = typer.Typer(
    name="coolio",
    help="Generate study/productivity music for YouTube using AI.",
    no_args_is_help=True,
)
library_app = typer.Typer(help="Manage the R2 track library.")
app.add_typer(library_app, name="library")

console = Console()


def _display_plan(plan: SessionPlan) -> None:
    """Display a session plan in a formatted table."""
    table = Table(title="Session Plan")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Source", style="bold", width=10)
    table.add_column("Title", style="white", width=25)
    table.add_column("Role", style="green", width=10)
    table.add_column("Duration", width=8)
    table.add_column("Provider/ID", style="magenta", width=15)
    table.add_column("BPM", width=5)
    table.add_column("Energy", width=6)

    for slot in plan.slots:
        duration_sec = slot.duration_ms // 1000
        duration_str = f"{duration_sec // 60}:{duration_sec % 60:02d}"

        source_style = "green" if slot.source == "library" else "yellow"
        source_display = f"[{source_style}]{slot.source.upper()}[/{source_style}]"

        provider_or_id = slot.track_id if slot.source == "library" else (slot.provider or "?")
        title_display = (slot.title or "TBD")[:23] + ".." if slot.title and len(slot.title) > 25 else (slot.title or "TBD")

        table.add_row(
            str(slot.order),
            source_display,
            title_display,
            slot.role,
            duration_str,
            provider_or_id,
            str(slot.bpm_target),
            str(slot.energy),
        )

    console.print(table)
    console.print()
    console.print(f"[bold]Library reuse:[/bold] {len(plan.library_tracks)} tracks (free)")
    console.print(f"[bold]New generation:[/bold] {len(plan.generation_tracks)} tracks")
    console.print(f"[bold]Estimated cost:[/bold] ${plan.estimated_cost:.2f}")
    console.print(f"[bold]Estimated duration:[/bold] {plan.estimated_duration_minutes:.1f} minutes")


@app.command()
def generate(
    concept: str = typer.Argument(
        ...,
        help="Video concept describing genre, vibe, mood, and purpose",
    ),
    duration: int = typer.Option(
        60,
        "--duration",
        "-d",
        help="Target total duration in minutes",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use (default: from settings)",
    ),
    provider: str = typer.Option(
        "elevenlabs",
        "--provider",
        "-p",
        help="Audio provider: elevenlabs (default) or stable_audio",
    ),
    exclude_days: int = typer.Option(
        7,
        "--exclude-days",
        help="Exclude library tracks used in the last N days",
    ),
    no_library: bool = typer.Option(
        False,
        "--no-library",
        help="Skip library lookup, generate all tracks from scratch",
    ),
    skip_audio: bool = typer.Option(
        False,
        "--skip-audio",
        help="Only generate plan, don't create audio",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Don't upload new tracks to R2 library",
    ),
    skip_visual: bool = typer.Option(
        False,
        "--skip-visual",
        help="Skip visual thumbnail generation",
    ),
    visual_hint: str = typer.Option(
        None,
        "--visual-hint",
        help="Atmosphere/style hints for thumbnail (e.g., 'Upside Down with floating particles')",
    ),
):
    """
    Generate a music session with smart library reuse.

    The planner checks the R2 library for existing tracks that fit your concept,
    then fills gaps with new generation.

    Example:
        coolio generate "Berlin techno, minimal, hypnotic focus"
        coolio generate "lofi hip hop for studying" --no-library
        coolio generate "ambient focus music" --provider stable_audio
    """
    # Validate provider
    valid_providers = ["elevenlabs", "stable_audio"]
    if provider not in valid_providers:
        console.print(f"[red]Invalid provider '{provider}'. Choose from: {', '.join(valid_providers)}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}\n"
        f"[bold]Provider:[/bold] {provider}",
        title="Coolio Music Generator"
    ))
    console.print()

    # Step 1: Query Library (unless --no-library)
    candidates = []
    if not no_library:
        console.print("[bold cyan]Step 1:[/bold cyan] Querying library for reusable tracks...")
        try:
            query = LibraryQuery()
            candidates = query.query_tracks(exclude_days=exclude_days)
            if candidates:
                console.print(f"  Found {len(candidates)} available tracks for potential reuse.")
            else:
                console.print("  [yellow]No tracks found in library.[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Library query failed: {e}[/yellow]")
            console.print("  Proceeding with full generation.")
    else:
        console.print("[bold cyan]Step 1:[/bold cyan] Skipping library lookup (--no-library)")
    console.print()

    # Step 2: Planning Session
    console.print("[bold cyan]Step 2:[/bold cyan] Planning session...")
    console.print(f"  Model: {model or get_settings().openrouter_model}")
    console.print(f"  Provider: {provider}")
    console.print(f"  Target: {duration} minutes")
    console.print()

    try:
        plan = generate_session_plan(
            concept=concept,
            candidates=candidates,
            target_duration_minutes=duration,
            model=model,
            provider=provider,
        )
    except Exception as e:
        console.print(f"[red]Error generating session plan: {e}[/red]")
        raise typer.Exit(1)

    _display_plan(plan)
    console.print()

    if skip_audio:
        console.print("[yellow]Skipping audio generation (--skip-audio)[/yellow]")
        return

    # Step 3: Execute Plan
    console.print("[bold cyan]Step 3:[/bold cyan] Executing plan (reuse + generate)...")
    if not skip_upload:
        console.print("  New tracks will be uploaded to R2 library.")
    console.print()

    generator = MusicGenerator(upload_to_r2=not skip_upload, provider_override=provider)

    try:
        session = generator.execute_plan(plan)
    except Exception as e:
        console.print(f"[red]Error executing plan: {e}[/red]")
        raise typer.Exit(1)

    # Step 3.5: Generate Visual Assets (unless --skip-visual)
    # Done AFTER audio so we have the real session_dir to save to
    visual_r2_key: str | None = None
    visual_prompt: str | None = None
    clip_path: str | None = None
    if not skip_visual:
        console.print()
        console.print("[bold cyan]Step 3.5:[/bold cyan] Generating visual assets...")
        if visual_hint:
            console.print(f"  Hint: {visual_hint}")
        try:
            # Step 3.5a: Generate visual prompt from concept
            visual_data = generate_visual_prompt(concept, visual_hint=visual_hint, model=model)
            visual_prompt = str(visual_data["prompt"])
            scene_type = str(visual_data["scene_type"])
            console.print(f"  a) Scene type: {scene_type}")
            console.print(f"     Prompt: {visual_prompt[:50]}...")

            # Step 3.5b: Generate thumbnail image
            visual_gen = VisualGenerator()
            thumbnail_path = visual_gen.generate(
                prompt=visual_prompt,
                session_id=session.session_id,
                output_dir=session.session_dir,
            )
            console.print(f"  b) Thumbnail: {thumbnail_path.name}")

            # Step 3.5c: Generate video motion prompt
            console.print("  c) Generating video motion prompt...")
            motion_data = generate_video_motion_prompt(
                concept=concept,
                image_prompt=visual_prompt,
                model=model,
            )
            motion_prompt = str(motion_data["prompt"])
            motion_type = str(motion_data["motion_type"])
            console.print(f"     Motion type: {motion_type}")
            console.print(f"     Prompt: {motion_prompt[:50]}...")

            # Step 3.5d: Generate 10s looping video clip with Kling AI
            console.print("  d) Creating 10s loop clip via Kling AI...")
            video_gen = KlingAIVideoGenerator()
            video_result = video_gen.generate(
                image_path=thumbnail_path,
                prompt=motion_prompt,
                session_id=session.session_id,
                output_dir=session.session_dir,
            )
            clip_path = str(video_result.output_path)
            console.print(f"     Clip saved: {video_result.output_path.name}")

            # Upload thumbnail to R2 (if not skipping uploads)
            if not skip_upload:
                r2 = R2Storage()
                visual_r2_key = r2.upload_image(thumbnail_path, session.session_id)
                console.print(f"  e) Uploaded thumbnail: {visual_r2_key}")

        except Exception as e:
            console.print(f"  [yellow]Visual generation failed: {e}[/yellow]")
            console.print("  [dim]Session audio is complete but visuals may be incomplete.[/dim]")
    else:
        console.print()
        console.print("[bold cyan]Step 3.5:[/bold cyan] Skipping visual generation (--skip-visual)")

    # Summary
    visual_info = ""
    if visual_r2_key:
        visual_info = f"\nThumbnail: {visual_r2_key}"
    elif visual_prompt:
        visual_info = "\nThumbnail: (generated locally)"
    if clip_path:
        visual_info += "\nVideo clip: ready for compose"

    console.print()
    console.print(Panel(
        f"[green]Session complete![/green]\n\n"
        f"Session ID: {session.session_id}\n"
        f"Output: {session.session_dir}\n"
        f"Reused: {session.reused_count} tracks\n"
        f"Generated: {session.generated_count} tracks\n"
        f"Total cost: ${session.estimated_cost:.2f}"
        f"{visual_info}",
        title="Complete",
    ))


@app.command()
def plan(
    concept: str = typer.Argument(
        ...,
        help="Video concept describing genre, vibe, mood, and purpose",
    ),
    duration: int = typer.Option(
        60,
        "--duration",
        "-d",
        help="Target total duration in minutes",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use",
    ),
    provider: str = typer.Option(
        "elevenlabs",
        "--provider",
        "-p",
        help="Audio provider: elevenlabs (default) or stable_audio",
    ),
    exclude_days: int = typer.Option(
        7,
        "--exclude-days",
        help="Exclude library tracks used in the last N days",
    ),
    no_library: bool = typer.Option(
        False,
        "--no-library",
        help="Skip library lookup",
    ),
):
    """
    Preview a session plan without generating audio.

    Shows how the planner would mix library tracks with new generation.
    Useful for previewing before spending credits.

    Example:
        coolio plan "lofi hip hop, rainy day vibes"
        coolio plan "ambient focus music" --provider stable_audio
    """
    # Validate provider
    valid_providers = ["elevenlabs", "stable_audio"]
    if provider not in valid_providers:
        console.print(f"[red]Invalid provider '{provider}'. Choose from: {', '.join(valid_providers)}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}\n"
        f"[bold]Provider:[/bold] {provider}",
        title="Session Plan Preview"
    ))
    console.print()

    # Query Library
    candidates = []
    if not no_library:
        console.print("Querying library for reusable tracks...")
        try:
            query = LibraryQuery()
            candidates = query.query_tracks(exclude_days=exclude_days)
            if candidates:
                console.print(f"Found {len(candidates)} available tracks.")
            else:
                console.print("[yellow]No tracks in library.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Library query failed: {e}[/yellow]")
    console.print()

    # Generate Plan
    console.print(f"Planning with model: {model or get_settings().openrouter_model}")
    console.print(f"Provider: {provider}")
    console.print()

    try:
        plan = generate_session_plan(
            concept=concept,
            candidates=candidates,
            target_duration_minutes=duration,
            model=model,
            provider=provider,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    _display_plan(plan)

    # Show detailed prompts for generation slots
    gen_slots = plan.generation_tracks
    if gen_slots:
        console.print()
        console.print(Panel("[bold]Generation Prompts[/bold]", title="Details"))
        for slot in gen_slots:
            console.print(f"\n[cyan]Track {slot.order}:[/cyan] {slot.title}")
            console.print(f"[dim]{slot.prompt}[/dim]")


@app.command()
def config():
    """Show current configuration."""
    console.print(Panel("[bold]Current Configuration[/bold]", title="Coolio"))

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    s = get_settings()

    def mask_key(key: str) -> str:
        if len(key) > 12:
            return f"{key[:8]}...{key[-4:]}"
        return "***"

    table.add_row("ElevenLabs API Key", mask_key(s.elevenlabs_api_key))
    table.add_row("Stability API Key", mask_key(s.stability_api_key))
    table.add_row("OpenRouter API Key", mask_key(s.openrouter_api_key))
    table.add_row("OpenRouter Model", s.openrouter_model)
    table.add_row("Stable Audio Model", s.stable_audio_model)
    table.add_row("Output Directory", str(s.output_dir))
    table.add_row("", "")
    table.add_row("R2 Access Key", mask_key(s.r2_access_key_id))
    table.add_row("R2 Bucket", s.r2_bucket_name)
    table.add_row("R2 Endpoint", s.r2_endpoint_url)

    console.print(table)


@app.command()
def models():
    """List popular OpenRouter models for music planning."""
    console.print(Panel("[bold]Recommended OpenRouter Models[/bold]", title="Models"))

    table = Table()
    table.add_column("Model ID", style="cyan")
    table.add_column("Provider")
    table.add_column("Notes")

    models_list = [
        ("anthropic/claude-opus-4.5", "Anthropic", "Expensive, reliable, great reasoning"),
        ("openai/gpt-5.1", "OpenAI", "Latest GPT, excellent structured output"),
        ("google/gemini-3-pro-preview", "Google", "Fast, good value"),
    ]

    for model_id, provider, notes in models_list:
        table.add_row(model_id, provider, notes)

    console.print(table)
    console.print()
    console.print("Use with: [cyan]coolio generate \"...\" --genre X --model <model-id>[/cyan]")


@app.command()
def providers():
    """Show available music generation providers."""
    console.print(Panel("[bold]Music Generation Providers[/bold]", title="Providers"))

    table = Table()
    table.add_column("Provider", style="cyan")
    table.add_column("Status")
    table.add_column("Max Duration")
    table.add_column("Cost")
    table.add_column("Best For")

    table.add_row(
        "elevenlabs",
        "[green]DEFAULT[/green]",
        "300 sec",
        "~$0.30/min",
        "Structured compositions, vocals",
    )
    table.add_row(
        "stable_audio",
        "[yellow]DEPRECATED[/yellow]",
        "190 sec",
        "$0.20/track",
        "Electronic, ambient, synthwave",
    )

    console.print(table)
    console.print()
    console.print(
        "Use [cyan]--provider stable_audio[/cyan] to override the default.\n"
        "Example: [cyan]coolio generate \"ambient music\" --provider stable_audio[/cyan]"
    )


@app.command()
def download(
    session_id: str = typer.Argument(
        ...,
        help="Session ID to download from R2 (e.g., session_20251204_210015)",
    ),
    output_dir: str = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory (default: output/audio/<session_id>)",
    ),
):
    """
    Download a session from R2 storage to local disk.

    Downloads all tracks and metadata for a session so you can mix it locally.

    Example:
        coolio download session_20251204_210015
        coolio download session_20251204_210015 -o ./my_session
    """
    from pathlib import Path

    console.print(Panel(
        f"[bold]Session:[/bold] {session_id}",
        title="Download from R2"
    ))
    console.print()

    try:
        r2 = R2Storage()

        # Get session metadata
        console.print("[bold cyan]Fetching session metadata...[/bold cyan]")
        session_meta = r2.get_session_metadata(session_id)
        if not session_meta:
            console.print(f"[red]Session not found in R2: {session_id}[/red]")
            raise typer.Exit(1)

        # Determine output directory
        if output_dir:
            dest_dir = Path(output_dir)
        else:
            dest_dir = Path("output/audio") / session_id

        dest_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[bold]Output:[/bold] {dest_dir}")

        # Get genre and track info from session metadata
        genre = session_meta.get("genre", "electronic")
        slots = session_meta.get("slots", [])
        track_refs = {ref["title"]: ref for ref in session_meta.get("track_references", [])}

        if not slots:
            console.print("[red]No slots found in session metadata[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Genre:[/bold] {genre}")
        console.print(f"[bold]Tracks:[/bold] {len(slots)}")
        console.print()
        console.print(f"[bold cyan]Downloading tracks from library...[/bold cyan]")

        downloaded = 0
        for slot in slots:
            order = slot.get("order", 0)
            title = slot.get("title", f"track_{order:02d}")
            role = slot.get("role", "track")
            source = slot.get("source", "library")

            # Get track_id and genre based on source
            if source == "library":
                track_id = slot.get("track_id")
                # Library tracks use their ORIGINAL genre folder (track_genre), not session genre
                track_genre = slot.get("track_genre") or genre
            else:
                # Find the generated track by title in track_references
                ref = track_refs.get(title, {})
                track_id = ref.get("track_id")
                # Generated tracks use the session genre (or ref genre)
                track_genre = ref.get("genre") or genre

            if not track_id:
                console.print(f"  [yellow]?[/yellow] track_{order:02d}_{role} - no track_id found for '{title}'")
                continue

            # Build R2 key - tracks are stored in library/tracks/{track_genre}/{track_id}.mp3
            audio_key = f"library/tracks/{track_genre}/{track_id}.mp3"
            metadata_key = f"library/tracks/{track_genre}/{track_id}.json"

            # Download audio file
            filename = f"track_{order:02d}_{role}.mp3"
            local_path = dest_dir / filename

            try:
                r2.download_file(audio_key, local_path)
                console.print(f"  [green]✓[/green] {filename} - {title}")
                downloaded += 1

                # Try to download metadata too
                import json
                meta_path = dest_dir / f"track_{order:02d}_{role}.json"
                try:
                    track_meta = r2.read_json(metadata_key)
                    track_meta["order"] = order  # Add order for mixer
                    with open(meta_path, "w") as f:
                        json.dump(track_meta, f, indent=2)
                except Exception:
                    # If no separate metadata, use slot info
                    with open(meta_path, "w") as f:
                        json.dump(slot, f, indent=2)

            except Exception as e:
                console.print(f"  [red]✗[/red] {filename} - {e}")

        # Download thumbnail if it exists in R2
        console.print()
        console.print("[bold cyan]Downloading thumbnail...[/bold cyan]")
        thumbnail_path = r2.download_thumbnail(session_id, dest_dir)
        if thumbnail_path:
            console.print(f"  [green]✓[/green] {thumbnail_path.name}")
        else:
            console.print("  [yellow]No thumbnail found in R2[/yellow]")

        # Save session metadata
        import json
        session_meta_path = dest_dir / "session.json"
        with open(session_meta_path, "w") as f:
            json.dump(session_meta, f, indent=2, default=str)

        thumbnail_info = f"\nThumbnail: {thumbnail_path.name}" if thumbnail_path else ""
        console.print()
        console.print(Panel(
            f"[green]Downloaded {downloaded}/{len(slots)} tracks[/green]{thumbnail_info}\n\n"
            f"Session: {dest_dir}\n\n"
            f"[bold]Next step:[/bold] coolio mix {dest_dir}",
            title="Complete"
        ))

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Download failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def mix(
    session_dir: str = typer.Argument(
        ...,
        help="Path to session directory containing tracks to mix",
    ),
    crossfade: int = typer.Option(
        5000,
        "--crossfade",
        "-c",
        help="Crossfade duration in milliseconds",
    ),
    no_normalize: bool = typer.Option(
        False,
        "--no-normalize",
        help="Skip audio level normalization",
    ),
    output: str = typer.Option(
        "final_mix.mp3",
        "--output",
        "-o",
        help="Output filename for the mixed audio",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Skip uploading mix to R2 storage",
    ),
):
    """
    Mix session tracks into a seamless final mix.

    Combines all tracks in a session directory with crossfade transitions
    and exports a single MP3 file ready for video composition.

    Example:
        coolio mix output/audio/session_20231125_123456
        coolio mix ./my_session --crossfade 8000 --output my_mix.mp3
    """
    from pathlib import Path
    from coolio.mixer import MixComposer

    session_path = Path(session_dir)

    if not session_path.exists():
        console.print(f"[red]Session directory not found: {session_dir}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Session:[/bold] {session_path.name}\n"
        f"[bold]Crossfade:[/bold] {crossfade}ms\n"
        f"[bold]Normalize:[/bold] {not no_normalize}\n"
        f"[bold]Upload to R2:[/bold] {not skip_upload}",
        title="Mix Composer"
    ))
    console.print()

    try:
        mixer = MixComposer(
            crossfade_ms=crossfade,
            normalize=not no_normalize,
        )
        result = mixer.mix_session(
            session_dir=session_path,
            output_filename=output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Mix failed: {e}[/red]")
        raise typer.Exit(1)

    # Upload to R2 if not skipped
    r2_info = ""
    if not skip_upload:
        console.print("[bold cyan]Uploading to R2...[/bold cyan]")
        try:
            # Extract session ID from directory name
            session_id = session_path.name
            r2 = R2Storage()
            r2_result = r2.upload_final_mix(
                mix_path=result.output_path,
                tracklist_path=result.tracklist_path,
                session_id=session_id,
            )
            r2_info = f"\nR2: {r2_result.get('mix_key', 'uploaded')}"
            console.print(f"  Uploaded: {r2_result.get('mix_key')}")
        except Exception as e:
            console.print(f"  [yellow]R2 upload failed: {e}[/yellow]")
            r2_info = "\nR2: upload failed"

    # Summary
    duration_min = result.total_duration_ms / 60000
    console.print()
    console.print(Panel(
        f"[green]Mix complete![/green]\n\n"
        f"Output: {result.output_path}\n"
        f"Tracklist: {result.tracklist_path}\n"
        f"Duration: {duration_min:.1f} minutes\n"
        f"Tracks: {result.track_count}"
        f"{r2_info}",
        title="Complete",
    ))


@app.command()
def compose(
    session_dir: str = typer.Argument(
        ...,
        help="Path to session directory containing mixed audio and video clip",
    ),
    output: str = typer.Option(
        "final_video.mp4",
        "--output",
        "-o",
        help="Output filename for the composed video",
    ),
    skip_metadata: bool = typer.Option(
        False,
        "--skip-metadata",
        help="Skip YouTube metadata generation",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Skip uploading video to R2 storage",
    ),
):
    """
    Compose final YouTube video from session assets.

    Loops a video clip for the duration of the mixed audio track
    to create a YouTube-ready MP4 video. Also generates metadata for upload.

    Requires:
        - Video clip ({session_id}_clip.mp4)
        - Mixed audio (final_mix.mp3 - run `coolio mix` first)

    Example:
        coolio compose output/audio/session_20231125_123456
        coolio compose ./my_session --output my_video.mp4
    """
    import json
    from pathlib import Path
    from coolio.video.composer import VideoComposer
    from coolio.video.metadata import generate_youtube_metadata, save_metadata

    session_path = Path(session_dir)

    if not session_path.exists():
        console.print(f"[red]Session directory not found: {session_dir}[/red]")
        raise typer.Exit(1)

    # Check for required files
    audio_path = session_path / "final_mix.mp3"
    if not audio_path.exists():
        console.print(f"[red]Mixed audio not found: {audio_path}[/red]")
        console.print("Run [cyan]coolio mix <session>[/cyan] first.")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Session:[/bold] {session_path.name}\n"
        f"[bold]Upload to R2:[/bold] {not skip_upload}",
        title="Video Composer"
    ))
    console.print()

    # Step 1: Compose video
    console.print("[bold cyan]Step 1:[/bold cyan] Composing video...")
    try:
        composer = VideoComposer()
        result = composer.compose_session(
            session_dir=session_path,
            output_filename=output,
        )
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Video composition failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"  Video: {result.output_path}")
    console.print(f"  Duration: {result.duration_seconds / 60:.1f} minutes")
    console.print(f"  Size: {result.file_size_mb:.1f} MB")
    console.print()

    # Step 2: Generate YouTube metadata
    metadata_info = ""
    if not skip_metadata:
        console.print("[bold cyan]Step 2:[/bold cyan] Generating YouTube metadata...")

        # Load session info for concept
        session_json = session_path / "session.json"
        concept = "Music mix"  # Default
        tracklist = None

        if session_json.exists():
            with open(session_json) as f:
                session_data = json.load(f)
                concept = session_data.get("concept", concept)
                # Extract tracklist if available
                slots = session_data.get("slots", [])
                if slots:
                    tracklist = [{"title": s.get("title", f"Track {i+1}")} for i, s in enumerate(slots)]

        try:
            metadata = generate_youtube_metadata(
                concept=concept,
                duration_minutes=result.duration_seconds / 60,
                tracklist=tracklist,
            )
            json_path, txt_path = save_metadata(metadata, session_path)
            console.print(f"  Title: {metadata.title}")
            console.print(f"  Metadata: {txt_path}")
            metadata_info = f"\nMetadata: {txt_path}"
        except Exception as e:
            console.print(f"  [yellow]Metadata generation failed: {e}[/yellow]")
    else:
        console.print("[bold cyan]Step 2:[/bold cyan] Skipping metadata (--skip-metadata)")

    # Step 3: Upload to R2
    r2_info = ""
    if not skip_upload:
        console.print("[bold cyan]Step 3:[/bold cyan] Uploading to R2...")
        try:
            session_id = session_path.name
            r2 = R2Storage()
            video_key = r2.upload_video(result.output_path, session_id)
            r2_info = f"\nR2: {video_key}"
            console.print(f"  Uploaded: {video_key}")
        except Exception as e:
            console.print(f"  [yellow]R2 upload failed: {e}[/yellow]")
            r2_info = "\nR2: upload failed"
    else:
        console.print("[bold cyan]Step 3:[/bold cyan] Skipping R2 upload (--skip-upload)")

    # Summary
    console.print()
    console.print(Panel(
        f"[green]Video composition complete![/green]\n\n"
        f"Video: {result.output_path}\n"
        f"Duration: {result.duration_seconds / 60:.1f} minutes\n"
        f"Size: {result.file_size_mb:.1f} MB"
        f"{metadata_info}"
        f"{r2_info}\n\n"
        f"[dim]Ready for manual upload to YouTube Studio[/dim]",
        title="Complete",
    ))


@app.command()
def video(
    session: str = typer.Argument(
        ...,
        help="Session directory path or session ID (e.g., session_20251206_233300)",
    ),
    visual_hint: str = typer.Option(
        None,
        "--visual-hint",
        help="Atmosphere/style hints for motion prompt generation",
    ),
    motion_prompt: str = typer.Option(
        None,
        "--motion-prompt",
        help="Custom motion prompt (skips LLM generation)",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Skip uploading video clip to R2 storage",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use for motion prompt generation",
    ),
):
    """
    Generate or retry video clip creation for an existing session.

    Uses the session's thumbnail to create a 10-second looping video clip
    via Kling AI. Useful for retrying after adding tokens or fixing errors.

    The command will:
    1. Find the session (local path or R2)
    2. Locate or download the thumbnail
    3. Generate a motion prompt (or use --motion-prompt)
    4. Create the video clip via Kling AI

    Example:
        coolio video output/audio/session_20251206_233300
        coolio video session_20251206_233300 --visual-hint "subtle green lighting"
        coolio video session_20251206_233300 --motion-prompt "Slow haze drift..."
    """
    import json
    from pathlib import Path

    console.print(Panel(
        f"[bold]Session:[/bold] {session}",
        title="Video Clip Generator"
    ))
    console.print()

    # Step 1: Resolve session path and load metadata
    console.print("[bold cyan]Step 1:[/bold cyan] Loading session...")
    session_path = Path(session)
    session_id: str
    concept: str = ""
    visual_prompt: str | None = None

    # Check if it's a local directory path
    if session_path.exists() and session_path.is_dir():
        session_id = session_path.name
        session_dir = session_path
        console.print(f"  Found local session: {session_dir}")

        # Try to load session.json for concept (locally first, then R2)
        session_json = session_dir / "session.json"
        if session_json.exists():
            with open(session_json) as f:
                session_data = json.load(f)
                concept = session_data.get("concept", "")
                console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")
        else:
            # session.json not local (cleaned up), fetch from R2
            console.print("  session.json not found locally, fetching from R2...")
            try:
                r2 = R2Storage()
                session_meta = r2.get_session_metadata(session_id)
                if session_meta:
                    concept = session_meta.get("concept", "")
                    # Save locally for future use
                    with open(session_json, "w") as f:
                        json.dump(session_meta, f, indent=2)
                    console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")
                else:
                    console.print("  [yellow]Session not found in R2[/yellow]")
            except Exception as e:
                console.print(f"  [yellow]Failed to fetch from R2: {e}[/yellow]")
    else:
        # Assume it's a session ID - try R2
        session_id = session if session.startswith("session_") else f"session_{session}"
        session_dir = Path(get_settings().output_dir) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"  Fetching from R2: {session_id}")
        try:
            r2 = R2Storage()
            session_meta = r2.get_session_metadata(session_id)
            if not session_meta:
                console.print(f"[red]Session not found in R2: {session_id}[/red]")
                raise typer.Exit(1)

            concept = session_meta.get("concept", "")
            console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")

            # Save session.json locally
            session_json = session_dir / "session.json"
            with open(session_json, "w") as f:
                json.dump(session_meta, f, indent=2)

        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Failed to fetch session from R2: {e}[/red]")
            raise typer.Exit(1)

    # Step 2: Find or download thumbnail
    console.print()
    console.print("[bold cyan]Step 2:[/bold cyan] Locating thumbnail...")

    thumbnail_path = session_dir / f"{session_id}_thumbnail.png"
    if not thumbnail_path.exists():
        # Try alternate name pattern
        for pattern in ["*_thumbnail.png", "*thumbnail*.png"]:
            matches = list(session_dir.glob(pattern))
            if matches:
                thumbnail_path = matches[0]
                break

    if not thumbnail_path.exists():
        # Try to download from R2
        console.print("  Thumbnail not found locally, checking R2...")
        try:
            r2 = R2Storage()
            downloaded_path = r2.download_thumbnail(session_id, session_dir)
            if downloaded_path:
                thumbnail_path = downloaded_path
                console.print(f"  Downloaded: {thumbnail_path.name}")
            else:
                console.print("[red]Thumbnail not found in R2[/red]")
                console.print("Run the full generate command first to create a thumbnail.")
                raise typer.Exit(1)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Failed to download thumbnail: {e}[/red]")
            raise typer.Exit(1)
    else:
        console.print(f"  Found: {thumbnail_path.name}")

    # Step 3: Generate or use motion prompt
    console.print()
    console.print("[bold cyan]Step 3:[/bold cyan] Preparing motion prompt...")

    if motion_prompt:
        # User provided custom motion prompt
        final_motion_prompt = motion_prompt
        console.print("  Using custom motion prompt")
        console.print(f"  Prompt: {final_motion_prompt[:50]}...")
    else:
        # Generate motion prompt via LLM
        if not concept:
            console.print("[yellow]No concept found - using generic motion prompt[/yellow]")
            concept = "Electronic music, atmospheric, hypnotic"

        console.print("  Generating motion prompt via LLM...")
        try:
            motion_data = generate_video_motion_prompt(
                concept=concept,
                image_prompt=visual_prompt,
                model=model,
            )
            final_motion_prompt = str(motion_data["prompt"])
            motion_type = str(motion_data["motion_type"])
            console.print(f"  Motion type: {motion_type}")
            console.print(f"  Prompt: {final_motion_prompt[:50]}...")
        except Exception as e:
            console.print(f"[red]Failed to generate motion prompt: {e}[/red]")
            raise typer.Exit(1)

    # Step 4: Generate video via Kling AI
    console.print()
    console.print("[bold cyan]Step 4:[/bold cyan] Creating video clip via Kling AI...")
    console.print("  This may take a few minutes...")

    try:
        video_gen = KlingAIVideoGenerator()
        video_result = video_gen.generate(
            image_path=thumbnail_path,
            prompt=final_motion_prompt,
            session_id=session_id,
            output_dir=session_dir,
        )
        console.print(f"  [green]Video created:[/green] {video_result.output_path.name}")
        console.print(f"  Duration: {video_result.duration_seconds}s")
    except Exception as e:
        console.print(f"[red]Kling AI video generation failed: {e}[/red]")
        raise typer.Exit(1)

    # Step 5: Upload to R2 (optional)
    r2_info = ""
    if not skip_upload:
        console.print()
        console.print("[bold cyan]Step 5:[/bold cyan] Uploading to R2...")
        try:
            r2 = R2Storage()
            video_key = f"sessions/{session_id}/video/{video_result.output_path.name}"
            r2.upload_file(video_result.output_path, video_key)
            r2_info = f"\nR2: {video_key}"
            console.print(f"  Uploaded: {video_key}")
        except Exception as e:
            console.print(f"  [yellow]R2 upload failed: {e}[/yellow]")
            r2_info = "\nR2: upload failed"
    else:
        console.print()
        console.print("[bold cyan]Step 5:[/bold cyan] Skipping R2 upload (--skip-upload)")

    # Summary
    console.print()
    console.print(Panel(
        f"[green]Video clip created![/green]\n\n"
        f"Session: {session_id}\n"
        f"Video: {video_result.output_path}\n"
        f"Duration: {video_result.duration_seconds}s"
        f"{r2_info}\n\n"
        f"[dim]Next: coolio mix {session_dir}[/dim]",
        title="Complete",
    ))


@app.command()
def visuals(
    session: str = typer.Argument(
        ...,
        help="Session directory path or session ID (e.g., session_20251206_233300)",
    ),
    visual_hint: str = typer.Option(
        None,
        "--visual-hint",
        help="Atmosphere/style hints for thumbnail generation",
    ),
    motion_prompt: str = typer.Option(
        None,
        "--motion-prompt",
        help="Custom motion prompt for video (skips LLM generation)",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Skip uploading assets to R2 storage",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use for prompt generation",
    ),
):
    """
    Regenerate all visual assets (thumbnail + video clip) for an existing session.

    Uses the session's concept to generate a new thumbnail and video clip.
    This will overwrite any existing visual assets in the session directory.

    The command will:
    1. Load session metadata (concept) from local or R2
    2. Generate a visual prompt from the concept (LLM)
    3. Create a new thumbnail using the reference image
    4. Generate a motion prompt (LLM)
    5. Create a new video clip via Kling AI
    6. Upload assets to R2 (unless --skip-upload)

    Example:
        coolio visuals output/audio/session_20251206_233300
        coolio visuals session_20251206_233300 --visual-hint "moody red lighting"
    """
    import json
    from pathlib import Path

    console.print(Panel(
        f"[bold]Session:[/bold] {session}",
        title="Visual Asset Regenerator"
    ))
    console.print()

    # Step 1: Resolve session path and load metadata
    console.print("[bold cyan]Step 1:[/bold cyan] Loading session...")
    session_path = Path(session)
    session_id: str
    concept: str = ""

    # Check if it's a local directory path
    if session_path.exists() and session_path.is_dir():
        session_id = session_path.name
        session_dir = session_path
        console.print(f"  Found local session: {session_dir}")

        # Try to load session.json for concept (locally first, then R2)
        session_json = session_dir / "session.json"
        if session_json.exists():
            with open(session_json) as f:
                session_data = json.load(f)
                concept = session_data.get("concept", "")
                console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")
        else:
            # session.json not local (cleaned up), fetch from R2
            console.print("  session.json not found locally, fetching from R2...")
            try:
                r2 = R2Storage()
                session_meta = r2.get_session_metadata(session_id)
                if session_meta:
                    concept = session_meta.get("concept", "")
                    # Save locally for future use
                    with open(session_json, "w") as f:
                        json.dump(session_meta, f, indent=2)
                    console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")
                else:
                    console.print("  [yellow]Session not found in R2[/yellow]")
            except Exception as e:
                console.print(f"  [yellow]Failed to fetch from R2: {e}[/yellow]")
    else:
        # Assume it's a session ID - try R2
        session_id = session if session.startswith("session_") else f"session_{session}"
        session_dir = Path(get_settings().output_dir) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"  Fetching from R2: {session_id}")
        try:
            r2 = R2Storage()
            session_meta = r2.get_session_metadata(session_id)
            if not session_meta:
                console.print(f"[red]Session not found in R2: {session_id}[/red]")
                raise typer.Exit(1)

            concept = session_meta.get("concept", "")
            console.print(f"  Concept: {concept[:60]}{'...' if len(concept) > 60 else ''}")

            # Save session.json locally
            session_json = session_dir / "session.json"
            with open(session_json, "w") as f:
                json.dump(session_meta, f, indent=2)

        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Failed to fetch session from R2: {e}[/red]")
            raise typer.Exit(1)

    if not concept:
        console.print("[red]No concept found in session metadata[/red]")
        console.print("Cannot generate visuals without a concept.")
        raise typer.Exit(1)

    # Step 2: Generate visual prompt from concept
    console.print()
    console.print("[bold cyan]Step 2:[/bold cyan] Generating visual prompt...")

    if visual_hint:
        console.print(f"  Hint: {visual_hint}")

    try:
        visual_data = generate_visual_prompt(concept, visual_hint=visual_hint, model=model)
        visual_prompt = str(visual_data["prompt"])
        scene_type = str(visual_data["scene_type"])
        console.print(f"  Scene type: {scene_type}")
        console.print(f"  Prompt: {visual_prompt[:60]}...")
    except Exception as e:
        console.print(f"[red]Failed to generate visual prompt: {e}[/red]")
        raise typer.Exit(1)

    # Step 3: Generate thumbnail image
    console.print()
    console.print("[bold cyan]Step 3:[/bold cyan] Generating thumbnail...")

    try:
        visual_gen = VisualGenerator()
        thumbnail_path = visual_gen.generate(
            prompt=visual_prompt,
            session_id=session_id,
            output_dir=session_dir,
        )
        console.print(f"  [green]Thumbnail created:[/green] {thumbnail_path.name}")
    except Exception as e:
        console.print(f"[red]Failed to generate thumbnail: {e}[/red]")
        raise typer.Exit(1)

    # Step 4: Generate motion prompt
    console.print()
    console.print("[bold cyan]Step 4:[/bold cyan] Generating motion prompt...")

    if motion_prompt:
        final_motion_prompt = motion_prompt
        console.print("  Using custom motion prompt")
        console.print(f"  Prompt: {final_motion_prompt[:50]}...")
    else:
        try:
            motion_data = generate_video_motion_prompt(
                concept=concept,
                image_prompt=visual_prompt,
                model=model,
            )
            final_motion_prompt = str(motion_data["prompt"])
            motion_type = str(motion_data["motion_type"])
            console.print(f"  Motion type: {motion_type}")
            console.print(f"  Prompt: {final_motion_prompt[:60]}...")
        except Exception as e:
            console.print(f"[red]Failed to generate motion prompt: {e}[/red]")
            raise typer.Exit(1)

    # Step 5: Generate video clip via Kling AI
    console.print()
    console.print("[bold cyan]Step 5:[/bold cyan] Creating video clip via Kling AI...")
    console.print("  This may take a few minutes...")

    try:
        video_gen = KlingAIVideoGenerator()
        video_result = video_gen.generate(
            image_path=thumbnail_path,
            prompt=final_motion_prompt,
            session_id=session_id,
            output_dir=session_dir,
        )
        console.print(f"  [green]Video created:[/green] {video_result.output_path.name}")
        console.print(f"  Duration: {video_result.duration_seconds}s")
    except Exception as e:
        console.print(f"[red]Kling AI video generation failed: {e}[/red]")
        raise typer.Exit(1)

    # Step 6: Upload to R2 (optional)
    r2_info = ""
    if not skip_upload:
        console.print()
        console.print("[bold cyan]Step 6:[/bold cyan] Uploading to R2...")
        try:
            r2 = R2Storage()
            # Upload thumbnail
            thumb_key = r2.upload_image(thumbnail_path, session_id)
            console.print(f"  Thumbnail: {thumb_key}")

            # Upload video clip
            video_key = f"sessions/{session_id}/video/{video_result.output_path.name}"
            r2.upload_file(video_result.output_path, video_key)
            console.print(f"  Video: {video_key}")

            r2_info = f"\nR2 Thumbnail: {thumb_key}\nR2 Video: {video_key}"
        except Exception as e:
            console.print(f"  [yellow]R2 upload failed: {e}[/yellow]")
            r2_info = "\nR2: upload failed"
    else:
        console.print()
        console.print("[bold cyan]Step 6:[/bold cyan] Skipping R2 upload (--skip-upload)")

    # Summary
    console.print()
    console.print(Panel(
        f"[green]Visual assets regenerated![/green]\n\n"
        f"Session: {session_id}\n"
        f"Thumbnail: {thumbnail_path}\n"
        f"Video: {video_result.output_path}\n"
        f"Duration: {video_result.duration_seconds}s"
        f"{r2_info}\n\n"
        f"[dim]Next: coolio mix {session_dir}[/dim]",
        title="Complete",
    ))


@library_app.command("verify")
def library_verify(
    prefix: str = typer.Option(
        "library/tracks/",
        "--prefix",
        "-p",
        help="R2 key prefix to list",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum number of objects to list",
    ),
):
    """
    Verify R2 library connection by listing recent uploads.

    Example:
        coolio library verify
        coolio library verify --prefix library/tracks/techno/ --limit 10
    """
    from coolio.library.storage import R2Storage

    console.print(Panel("[bold]R2 Library Verification[/bold]", title="Coolio"))
    console.print()

    try:
        r2 = R2Storage()
        objects = r2.list_objects(prefix=prefix, max_keys=limit)
    except Exception as e:
        console.print(f"[red]Error connecting to R2: {e}[/red]")
        raise typer.Exit(1)

    if not objects:
        console.print(f"[yellow]No objects found with prefix '{prefix}'[/yellow]")
        console.print()
        console.print("This might mean:")
        console.print("  - The library is empty (no tracks uploaded yet)")
        console.print("  - The prefix doesn't match any objects")
        console.print("  - R2 credentials are misconfigured")
        return

    table = Table(title=f"R2 Objects (prefix: {prefix})")
    table.add_column("Key", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Last Modified")

    for obj in objects:
        size_kb = obj.get("Size", 0) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        last_modified = obj.get("LastModified", "")
        if hasattr(last_modified, "strftime"):
            last_modified = last_modified.strftime("%Y-%m-%d %H:%M")

        table.add_row(obj.get("Key", ""), size_str, str(last_modified))

    console.print(table)
    console.print()
    console.print(f"[green]Found {len(objects)} objects[/green]")


@library_app.command("list")
def library_list(
    genre: str = typer.Option(
        None,
        "--genre",
        "-g",
        help="Filter by genre (e.g., techno, house)",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum number of tracks to list",
    ),
):
    """
    List tracks in the R2 library.

    Example:
        coolio library list
        coolio library list --genre techno
    """
    from coolio.library.storage import R2Storage

    prefix = "library/tracks/"
    if genre:
        prefix = f"library/tracks/{genre}/"

    console.print(Panel("[bold]Track Library[/bold]", title="Coolio"))
    console.print()

    try:
        r2 = R2Storage()
        objects = r2.list_objects(prefix=prefix, max_keys=limit * 2)
    except Exception as e:
        console.print(f"[red]Error connecting to R2: {e}[/red]")
        raise typer.Exit(1)

    # Filter to only .mp3 files
    audio_files = [o for o in objects if o.get("Key", "").endswith(".mp3")][:limit]

    if not audio_files:
        console.print(f"[yellow]No tracks found{' for genre: ' + genre if genre else ''}[/yellow]")
        return

    table = Table(title=f"Tracks{' (' + genre + ')' if genre else ''}")
    table.add_column("Track ID", style="cyan", width=10)
    table.add_column("Genre", style="green", width=12)
    table.add_column("Size", justify="right", width=10)

    for obj in audio_files:
        key = obj.get("Key", "")
        parts = key.split("/")
        if len(parts) >= 4:
            track_genre = parts[2]
            track_id = parts[3].replace(".mp3", "")
        else:
            track_genre = "?"
            track_id = key

        size_kb = obj.get("Size", 0) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"

        table.add_row(track_id, track_genre, size_str)

    console.print(table)
    console.print()
    console.print(f"[green]Found {len(audio_files)} tracks[/green]")


@library_app.command("sessions")
def library_sessions(
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum number of sessions to list",
    ),
):
    """
    List sessions stored in R2.

    Example:
        coolio library sessions
    """
    from coolio.library.storage import R2Storage

    console.print(Panel("[bold]R2 Sessions[/bold]", title="Coolio"))
    console.print()

    try:
        r2 = R2Storage()
        session_ids = r2.list_sessions(max_keys=limit * 5)[:limit]
    except Exception as e:
        console.print(f"[red]Error connecting to R2: {e}[/red]")
        raise typer.Exit(1)

    if not session_ids:
        console.print("[yellow]No sessions found in R2.[/yellow]")
        return

    table = Table(title="Sessions in R2")
    table.add_column("Session ID", style="cyan")
    table.add_column("Genre", style="green")
    table.add_column("Tracks")
    table.add_column("Has Mix")

    for session_id in session_ids:
        # Try to get session metadata
        try:
            meta = r2.get_session_metadata(session_id)
            if meta:
                genre = meta.get("genre", "?")
                track_count = meta.get("final_track_count", meta.get("total_tracks", "?"))
                # Check for mix
                has_mix = r2.exists(f"sessions/{session_id}/audio/final_mix.mp3")
                table.add_row(session_id, genre, str(track_count), "Yes" if has_mix else "No")
            else:
                table.add_row(session_id, "?", "?", "?")
        except Exception:
            table.add_row(session_id, "?", "?", "?")

    console.print(table)
    console.print()
    console.print(f"[green]Found {len(session_ids)} sessions[/green]")


if __name__ == "__main__":
    app()
