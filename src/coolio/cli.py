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
from coolio.visuals import VisualGenerator, generate_visual_prompt

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
    tracks: int = typer.Option(
        15,
        "--tracks",
        "-t",
        help="Approximate track count (duration is the real target)",
    ),
    duration: int = typer.Option(
        60,
        "--duration",
        "-d",
        help="Target total duration in minutes",
    ),
    budget: float = typer.Option(
        5.00,
        "--budget",
        "-b",
        help="Maximum budget in USD (informational)",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use (default: from settings)",
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
):
    """
    Generate a music session with smart library reuse.

    The planner checks the R2 library for existing tracks that fit your concept,
    then fills gaps with new generation.

    Example:
        coolio generate "Berlin techno, minimal, hypnotic focus"
        coolio generate "lofi hip hop for studying" --no-library
    """
    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}",
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
    console.print(f"  Target: {tracks} tracks, {duration} minutes")
    console.print(f"  Budget: ${budget:.2f}")
    console.print()

    try:
        plan = generate_session_plan(
            concept=concept,
            candidates=candidates,
            track_count=tracks,
            target_duration_minutes=duration,
            model=model,
        )
    except Exception as e:
        console.print(f"[red]Error generating session plan: {e}[/red]")
        raise typer.Exit(1)

    _display_plan(plan)
    console.print()

    # Step 2.5: Generate Visual (unless --skip-visual)
    visual_r2_key: str | None = None
    visual_prompt: str | None = None
    if not skip_visual:
        console.print("[bold cyan]Step 2.5:[/bold cyan] Generating visual thumbnail...")
        try:
            # Generate visual prompt from concept
            visual_data = generate_visual_prompt(concept, model=model)
            visual_prompt = str(visual_data["prompt"])
            scene_type = str(visual_data["scene_type"])
            console.print(f"  Scene type: {scene_type}")
            console.print(f"  Prompt: {visual_prompt[:60]}...")

            # Generate thumbnail image
            visual_gen = VisualGenerator()
            # Use a temporary session ID for now (will be replaced once audio is done)
            from datetime import datetime
            temp_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            thumbnail_path = visual_gen.generate(
                prompt=visual_prompt,
                session_id=temp_session_id,
            )
            console.print(f"  Generated: {thumbnail_path}")

            # Upload to R2 (if not skipping uploads)
            if not skip_upload:
                r2 = R2Storage()
                visual_r2_key = r2.upload_image(thumbnail_path, temp_session_id)
                console.print(f"  Uploaded: {visual_r2_key}")

        except Exception as e:
            console.print(f"  [yellow]Visual generation failed: {e}[/yellow]")
            console.print("  Proceeding without thumbnail.")
        console.print()
    else:
        console.print("[bold cyan]Step 2.5:[/bold cyan] Skipping visual generation (--skip-visual)")
    console.print()

    if skip_audio:
        console.print("[yellow]Skipping audio generation (--skip-audio)[/yellow]")
        return

    # Step 3: Execute Plan
    console.print("[bold cyan]Step 3:[/bold cyan] Executing plan (reuse + generate)...")
    if not skip_upload:
        console.print("  New tracks will be uploaded to R2 library.")
    console.print()

    generator = MusicGenerator(upload_to_r2=not skip_upload)

    try:
        session = generator.execute_plan(plan)
    except Exception as e:
        console.print(f"[red]Error executing plan: {e}[/red]")
        raise typer.Exit(1)

    # Summary
    visual_info = ""
    if visual_r2_key:
        visual_info = f"\nThumbnail: {visual_r2_key}"
    elif visual_prompt and not skip_upload:
        visual_info = "\nThumbnail: (generated locally)"

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
    tracks: int = typer.Option(
        15,
        "--tracks",
        "-t",
        help="Approximate track count (duration is the real target)",
    ),
    duration: int = typer.Option(
        60,
        "--duration",
        "-d",
        help="Target total duration in minutes",
    ),
    budget: float = typer.Option(
        5.00,
        "--budget",
        "-b",
        help="Maximum budget in USD",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use",
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
    """
    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}",
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
    console.print()

    try:
        plan = generate_session_plan(
            concept=concept,
            candidates=candidates,
            track_count=tracks,
            target_duration_minutes=duration,
            model=model,
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
        ("anthropic/claude-sonnet-4.5", "Anthropic", "Fast, reliable, great reasoning"),
        ("anthropic/claude-haiku-4.5", "Anthropic", "Fastest, cheapest Anthropic option"),
        ("openai/gpt-4o", "OpenAI", "Latest GPT, excellent structured output"),
        ("google/gemini-2.0-flash-exp", "Google", "Fast, good value"),
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
    table.add_column("Max Duration")
    table.add_column("Cost")
    table.add_column("Best For")

    table.add_row(
        "stable_audio",
        "190 sec",
        "$0.20/track",
        "Electronic, ambient, synthwave",
    )
    table.add_row(
        "elevenlabs",
        "300 sec",
        "~$0.30/min",
        "Structured compositions, vocals",
    )

    console.print(table)
    console.print()
    console.print(
        "The Curator agent automatically selects the best provider for each track "
        "based on your concept and budget."
    )


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
        help="Path to session directory containing mixed audio and thumbnail",
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
    waveform_color: str = typer.Option(
        "white@0.5",
        "--waveform-color",
        help="Waveform color in FFmpeg format (e.g., 'white@0.5', 'green@0.6')",
    ),
):
    """
    Compose final YouTube video from session assets.

    Combines thumbnail image, mixed audio, and waveform visualization
    into a YouTube-ready MP4 video. Also generates metadata for upload.

    Requires:
        - Thumbnail image (thumbnail.png or similar)
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
        f"[bold]Waveform:[/bold] {waveform_color}\n"
        f"[bold]Upload to R2:[/bold] {not skip_upload}",
        title="Video Composer"
    ))
    console.print()

    # Step 1: Compose video
    console.print("[bold cyan]Step 1:[/bold cyan] Composing video...")
    try:
        composer = VideoComposer(waveform_color=waveform_color)
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
def repair(
    session_id: str = typer.Argument(
        ...,
        help="Session ID to repair (e.g., session_20231125_123456)",
    ),
    slots: str = typer.Option(
        ...,
        "--slots",
        "-s",
        help="Comma-separated slot numbers to regenerate (e.g., '8,12')",
    ),
    skip_upload: bool = typer.Option(
        False,
        "--skip-upload",
        help="Don't upload regenerated tracks to R2 library",
    ),
):
    """
    Repair a session by regenerating specific failed slots.

    Downloads the session metadata from R2, regenerates the specified
    slots, uploads the new tracks to the library, and updates the
    session metadata.

    Example:
        coolio repair session_20231130_161807 --slots 8,12
        coolio repair session_20231130_161807 -s "8, 12, 15"
    """
    from pathlib import Path

    # Parse slot numbers
    try:
        slot_numbers = [int(s.strip()) for s in slots.split(",") if s.strip()]
    except ValueError:
        console.print("[red]Invalid slot format. Use comma-separated numbers (e.g., '8,12')[/red]")
        raise typer.Exit(1)

    if not slot_numbers:
        console.print("[red]No slot numbers provided[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Session:[/bold] {session_id}\n"
        f"[bold]Slots to repair:[/bold] {slot_numbers}\n"
        f"[bold]Upload to R2:[/bold] {not skip_upload}",
        title="Session Repair"
    ))
    console.print()

    try:
        generator = MusicGenerator(upload_to_r2=not skip_upload)
        results = generator.repair_session(
            session_id=session_id,
            slot_numbers=slot_numbers,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Repair failed: {e}[/red]")
        raise typer.Exit(1)

    # Summary
    succeeded = results.get("succeeded", [])
    failed = results.get("failed", [])

    status = "[green]complete[/green]" if not failed else "[yellow]partial[/yellow]"

    console.print()
    console.print(Panel(
        f"Repair {status}!\n\n"
        f"Session: {session_id}\n"
        f"Succeeded: {len(succeeded)} slots {succeeded if succeeded else ''}\n"
        f"Failed: {len(failed)} slots {[f['order'] for f in failed] if failed else ''}\n"
        f"Cost: ${results.get('cost', 0):.2f}",
        title="Repair Results",
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
