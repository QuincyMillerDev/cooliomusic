"""CLI interface for Coolio music generation."""

import typer
from collections import Counter
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from coolio.config import get_settings
from coolio.djcoolio import generate_session_plan
from coolio.library.query import LibraryQuery
from coolio.library.storage import R2Storage
from coolio.models import SessionPlan
from coolio.generator import MusicGenerator

app = typer.Typer(
    name="coolio",
    help="Generate study/productivity music for YouTube using AI.",
    no_args_is_help=True,
)
library_app = typer.Typer(help="Manage the R2 track library.")
app.add_typer(library_app, name="library")

console = Console()

_ELEVENLABS_MAX_DURATION_MS = 300_000
_STABLE_AUDIO_MAX_DURATION_MS = 190_000


def _audit_plan(plan: SessionPlan) -> list[str]:
    """Return human-readable warnings about a plan.

    This is intentionally lightweight and offline: it validates the structure and
    basic invariants of the plan as returned by the planner, without making any
    R2/network calls.
    """
    warnings: list[str] = []

    if not plan.slots:
        return ["Plan has 0 slots."]

    # Slot order sanity
    orders = [s.order for s in plan.slots]
    order_counts = Counter(orders)
    duplicate_orders = sorted([o for o, c in order_counts.items() if c > 1])
    if duplicate_orders:
        warnings.append(f"Duplicate slot order numbers: {duplicate_orders}")
    expected_orders = list(range(1, len(plan.slots) + 1))
    if sorted(orders) != expected_orders:
        warnings.append(
            f"Non-sequential/missing order numbers. Expected {expected_orders}, got {sorted(orders)}"
        )

    # Library track duplication within a single session
    library_keys: list[str] = []
    for slot in plan.library_tracks:
        if not slot.track_id:
            warnings.append(f"Library slot #{slot.order} missing track_id.")
            continue
        # Track IDs are only 8 chars; include genre to avoid false positives.
        library_keys.append(f"{slot.track_genre or plan.genre}:{slot.track_id}")
        if not slot.title:
            warnings.append(
                f"Library slot #{slot.order} has no title. (Planner should supply one for readability.)"
            )
        if slot.duration_ms <= 0:
            warnings.append(f"Library slot #{slot.order} has invalid duration_ms={slot.duration_ms}.")

    lib_counts = Counter(library_keys)
    duplicate_lib = sorted([k for k, c in lib_counts.items() if c > 1])
    if duplicate_lib:
        warnings.append(f"Duplicate library tracks in one session: {duplicate_lib}")

    # Generation slot invariants and provider duration sanity
    for slot in plan.generation_tracks:
        if not slot.prompt:
            warnings.append(f"Generate slot #{slot.order} missing prompt.")
        if slot.duration_ms <= 0:
            warnings.append(f"Generate slot #{slot.order} has invalid duration_ms={slot.duration_ms}.")

        provider = slot.provider or "?"
        if provider == "elevenlabs" and slot.duration_ms > _ELEVENLABS_MAX_DURATION_MS:
            warnings.append(
                f"Generate slot #{slot.order} requests {slot.duration_ms/1000:.0f}s on elevenlabs "
                f"(max {_ELEVENLABS_MAX_DURATION_MS/1000:.0f}s)."
            )
        if provider == "stable_audio" and slot.duration_ms > _STABLE_AUDIO_MAX_DURATION_MS:
            warnings.append(
                f"Generate slot #{slot.order} requests {slot.duration_ms/1000:.0f}s on stable_audio "
                f"(max {_STABLE_AUDIO_MAX_DURATION_MS/1000:.0f}s)."
            )

    # Informational note: library titles are not canonicalized in plan display.
    if plan.library_tracks:
        warnings.append(
            "Note: library slot titles shown here come from the planner output; "
            "the generator will use the library metadata title when downloading."
        )

    return warnings


def _print_plan_audit(plan: SessionPlan) -> None:
    warnings = _audit_plan(plan)
    if not warnings:
        console.print(Panel("[green]No issues detected.[/green]", title="Plan audit"))
        return

    content = "\n".join(f"- {w}" for w in warnings)
    console.print(Panel(content, title="Plan audit"))


def _print_estimate_note() -> None:
    console.print(
        Panel(
            "Plan durations are estimates from the planner.\n"
            "Final mix duration and tracklist timestamps are computed during `coolio mix` "
            "from the actual audio and crossfade overlap.",
            title="Timing note",
        )
    )


def _display_plan(plan: SessionPlan) -> None:
    """Display a session plan in a formatted table."""
    table = Table(title="Session Plan")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Source", style="bold", width=10)
    table.add_column("Title", style="white", width=30)
    table.add_column("Duration", width=8)
    table.add_column("Provider/ID", style="magenta", width=20)

    for slot in plan.slots:
        duration_sec = slot.duration_ms // 1000
        duration_str = f"{duration_sec // 60}:{duration_sec % 60:02d}"

        source_style = "green" if slot.source == "library" else "yellow"
        source_display = f"[{source_style}]{slot.source.upper()}[/{source_style}]"

        provider_or_id = slot.track_id if slot.source == "library" else (slot.provider or "?")
        title_display = (slot.title or "TBD")[:28] + ".." if slot.title and len(slot.title) > 30 else (slot.title or "TBD")

        table.add_row(
            str(slot.order),
            source_display,
            title_display,
            duration_str,
            provider_or_id,
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
    test_track: bool = typer.Option(
        False,
        "--test-track",
        help="Generate a single local-only test track (skips planning and uploads)",
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

    if test_track:
        console.print("[bold cyan]Test mode:[/bold cyan] Generating a single local-only track...")
        console.print("  Using the planner to generate a realistic prompt (no library lookup).")
        console.print("  Uploads disabled.")
        console.print()

        generator = MusicGenerator(
            upload_to_r2=False,
            auto_cleanup=False,
            provider_override=provider,
        )

        try:
            track = generator.generate_test_track(concept)
        except Exception as e:
            console.print(f"[red]Error generating test track: {e}[/red]")
            raise typer.Exit(1)

        console.print()
        console.print(Panel(
            f"[green]Test track complete![/green]\n\n"
            f"Output: {track.audio_path}\n"
            f"Metadata: {track.metadata_path}\n"
            f"Provider: {track.provider}\n"
            f"Duration: {track.duration_ms/1000:.0f}s",
            title="Complete",
        ))
        return

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
    _print_plan_audit(plan)
    console.print()
    _print_estimate_note()
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

    console.print()
    console.print(Panel(
        f"[green]Session complete![/green]\n\n"
        f"Session ID: {session.session_id}\n"
        f"Output: {session.session_dir}\n"
        f"Reused: {session.reused_count} tracks\n"
        f"Generated: {session.generated_count} tracks\n"
        f"Total cost: ${session.estimated_cost:.2f}",
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
    _print_plan_audit(plan)
    console.print()
    _print_estimate_note()

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
    table.add_row("YouTube Metadata Model", s.openrouter_youtube_metadata_model)
    table.add_row("Stable Audio Model", s.stable_audio_model)
    table.add_row(
        "Kling AI Access Key",
        mask_key(s.kling_ai_access_key) if s.kling_ai_access_key else "(not set)",
    )
    table.add_row(
        "Kling AI Secret Key",
        mask_key(s.kling_ai_secret_key) if s.kling_ai_secret_key else "(not set)",
    )
    table.add_row("Kling Base URL", s.kling_base_url)
    table.add_row("Kling Model", s.kling_model_name)
    table.add_row("Kling Mode", s.kling_mode)
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
        ("openai/gpt-5.2", "OpenAI", "Latest GPT, excellent structured output"),
        ("google/gemini-3-pro-preview", "Google", "Fast, good value"),
        ("moonshotai/kimi-k2-thinking", "MoonshotAI", "Reasoning-heavy; try for planning quality"),
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
                console.print(f"  [yellow]?[/yellow] track_{order:02d} - no track_id found for '{title}'")
                continue

            # Build R2 key - tracks are stored in library/tracks/{track_genre}/{track_id}.mp3
            audio_key = f"library/tracks/{track_genre}/{track_id}.mp3"
            metadata_key = f"library/tracks/{track_genre}/{track_id}.json"

            # Download audio file
            filename = f"track_{order:02d}.mp3"
            local_path = dest_dir / filename

            try:
                r2.download_file(audio_key, local_path)
                console.print(f"  [green]✓[/green] {filename} - {title}")
                downloaded += 1

                # Try to download metadata too
                import json
                meta_path = dest_dir / f"track_{order:02d}.json"
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

        # Save session metadata
        import json
        session_meta_path = dest_dir / "session.json"
        with open(session_meta_path, "w") as f:
            json.dump(session_meta, f, indent=2, default=str)

        console.print()
        console.print(Panel(
            f"[green]Downloaded {downloaded}/{len(slots)} tracks[/green]\n\n"
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
    only_consecutive: bool = typer.Option(
        False,
        "--only-consecutive",
        help="Only mix consecutive tracks starting from track_01 until the first missing track number",
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
            only_consecutive=only_consecutive,
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
def image(
    session_dir: str = typer.Argument(
        ...,
        help="Path to session directory (should contain session.json; typically after `coolio mix`)",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter text model to generate the background brief (default: OPENROUTER_MODEL)",
    ),
    image_model: str = typer.Option(
        None,
        "--image-model",
        help="OpenRouter image model to generate the session image (default: google/gemini-3-pro-image-preview)",
    ),
    ref_image: str = typer.Option(
        None,
        "--ref-image",
        help="Reference image to anchor the foreground (default: bundled djreferenceimage.png)",
    ),
):
    """
    Generate a session image anchored to the reference DJ photo.

    This is a standalone command (not orchestrated yet). It reads session metadata,
    generates a background-only visual brief, then uses an image model with the
    reference image as input so the DJ/gear remain consistent while only the
    setting behind the DJ changes.
    """
    from pathlib import Path
    import json

    from coolio.session_image import (
        build_image_prompt,
        build_visual_seed,
        generate_background_brief,
        load_session_json,
        now_iso,
    )
    from coolio.providers.openrouter_image import generate_image_from_reference

    s = get_settings()
    session_path = Path(session_dir)
    if not session_path.exists():
        console.print(f"[red]Session directory not found: {session_path}[/red]")
        raise typer.Exit(1)

    # Validate expected files
    session_json_path = session_path / "session.json"
    if not session_json_path.exists():
        console.print(f"[red]Missing session.json in: {session_path}[/red]")
        console.print("Tip: run `coolio generate ...` first (and optionally `coolio mix ...`).")
        raise typer.Exit(1)

    # Default output paths (always overwritten to keep workflow simple)
    out_png = session_path / "session_image.png"
    out_json = session_path / "session_image.json"
    if out_png.exists() or out_json.exists():
        console.print("[yellow]Overwriting existing session image outputs...[/yellow]")
        console.print(f"  PNG:  {out_png}")
        console.print(f"  JSON: {out_json}")

    # Defaults
    ref_override = s.coolio_reference_dj_image_path
    default_ref = (
        ref_override
        if ref_override is not None
        else (Path(__file__).resolve().parent / "assets" / "images" / "djreferenceimage.png")
    )
    ref_path = Path(ref_image) if ref_image else default_ref
    chosen_image_model = image_model or getattr(s, "openrouter_image_model", None) or "google/gemini-3-pro-image-preview"
    chosen_brief_model = model or s.openrouter_model

    if not ref_path.exists():
        console.print(f"[red]Reference image not found: {ref_path}[/red]")
        raise typer.Exit(1)

    # Load metadata and generate background brief
    session_meta = load_session_json(session_path)
    seed = build_visual_seed(session_meta)

    console.print(Panel(
        f"[bold]Session:[/bold] {session_path.name}\n"
        f"[bold]Brief model:[/bold] {chosen_brief_model}\n"
        f"[bold]Image model:[/bold] {chosen_image_model}\n"
        f"[bold]Reference:[/bold] {ref_path}",
        title="Session Image",
    ))
    console.print()
    console.print("[bold cyan]Step 1:[/bold cyan] Generating background brief...")

    try:
        brief = generate_background_brief(seed=seed, model=chosen_brief_model)
    except Exception as e:
        console.print(f"[red]Failed to generate background brief: {e}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        json.dumps(brief.to_dict(), indent=2),
        title="Background brief (background only)",
    ))
    console.print()

    # Generate the image
    console.print("[bold cyan]Step 2:[/bold cyan] Generating anchored session image...")
    prompt = build_image_prompt(brief)

    try:
        result = generate_image_from_reference(
            reference_image_path=ref_path,
            prompt=prompt,
            image_model=chosen_image_model,
        )
    except Exception as e:
        # Persist debugging context for quick iteration (doesn't affect success path).
        error_path = session_path / "session_image_error.json"
        try:
            error_payload = {
                "session_id": session_path.name,
                "created_at": now_iso(),
                "reference_image": str(ref_path),
                "brief_model": chosen_brief_model,
                "image_model": chosen_image_model,
                "background_brief": brief.to_dict(),
                "prompt": prompt,
                "error": str(e),
            }
            error_path.write_text(json.dumps(error_payload, indent=2))
            console.print(f"[yellow]Wrote debug file: {error_path}[/yellow]")
        except Exception:
            # Best effort only; do not mask the original error.
            pass
        console.print(f"[red]Failed to generate session image: {e}[/red]")
        raise typer.Exit(1)

    # Persist outputs
    out_png.write_bytes(result.image_bytes)
    meta_out = {
        "session_id": session_path.name,
        "created_at": now_iso(),
        "reference_image": str(ref_path),
        "brief_model": chosen_brief_model,
        "image_model": result.model_used,
        "background_brief": brief.to_dict(),
        "prompt": result.prompt,
        "mime_type": result.mime_type,
        "output_image": str(out_png),
        "raw_response": result.raw_response,
    }
    out_json.write_text(json.dumps(meta_out, indent=2))

    console.print()
    console.print(Panel(
        f"[green]Session image complete![/green]\n\n"
        f"Image: {out_png}\n"
        f"Metadata: {out_json}",
        title="Complete",
    ))


@app.command()
def clip(
    session_dir: str = typer.Argument(
        ...,
        help="Path to session directory (must contain session_image.png)",
    ),
    prompt: str = typer.Option(
        None,
        "--prompt",
        help="Prompt for Kling image-to-video (default: chill DJ prompt).",
    ),
    negative_prompt: str = typer.Option(
        None,
        "--negative-prompt",
        help="Negative prompt for Kling image-to-video (default: conservative anti-warping prompt).",
    ),
    model_name: str = typer.Option(
        None,
        "--model-name",
        help="Kling model_name (default: KLING_MODEL_NAME or kling-v2-5-turbo).",
    ),
    mode: str = typer.Option(
        None,
        "--mode",
        help="Kling mode: std or pro (default: KLING_MODE or std).",
    ),
    fps: int = typer.Option(
        15,
        "--fps",
        help="Frame sampling rate used for loop selection (higher = slower but more precise).",
    ),
    loop_min_seconds: float = typer.Option(
        8.0,
        "--loop-min-seconds",
        help="Minimum loop duration to consider (final clip duration is flexible).",
    ),
    loop_max_seconds: float = typer.Option(
        10.0,
        "--loop-max-seconds",
        help="Maximum loop duration to consider.",
    ),
    seam_seconds: float = typer.Option(
        0.3,
        "--seam-seconds",
        help="Crossfade duration across the loop seam (kept short to avoid ghosting).",
    ),
):
    """
    Generate a 10s Kling clip from session_image.png, then post-process into a perfect loop.

    Kling must generate 10 seconds, but the final looped clip duration is flexible.
    """
    import base64
    import json
    import tempfile
    from pathlib import Path

    from coolio.providers.kling import (
        KlingError,
        create_image2video_task,
        download_video_bytes,
        extract_video_url,
        poll_task_until_complete,
    )
    from coolio.session_image import now_iso
    from coolio.video_loop import VideoLoopError, render_forward_only_loop, select_best_loop

    s = get_settings()
    if not s.kling_ai_access_key or not s.kling_ai_secret_key:
        console.print(
            "[red]Missing Kling keys (required for `coolio clip`).[/red]\n"
            "[dim]Set both KLING_AI_ACCESS_KEY and KLING_AI_SECRET_KEY.[/dim]"
        )
        raise typer.Exit(1)

    session_path = Path(session_dir)
    if not session_path.exists():
        console.print(f"[red]Session directory not found: {session_path}[/red]")
        raise typer.Exit(1)

    image_path = session_path / "session_image.png"
    if not image_path.exists():
        console.print(f"[red]Missing session_image.png in: {session_path}[/red]")
        console.print("Tip: run `coolio image <session_dir>` first.")
        raise typer.Exit(1)

    out_mp4 = session_path / "session_clip.mp4"
    if out_mp4.exists():
        console.print("[yellow]Overwriting existing session clip output...[/yellow]")
        console.print(f"  MP4: {out_mp4}")

    chosen_model = model_name or getattr(s, "kling_model_name", None) or "kling-v2-5-turbo"
    chosen_mode = mode or getattr(s, "kling_mode", None) or "std"

    default_prompt = (
        "This monkey is a very chill DJ. Movement just like a human. "
        "Slow, in the zone, focused on the set. Subtle head nods, small hand movements. "
        "No big camera moves."
    )
    default_negative = (
        "no camera shake, no fast motion, no scene change, no face distortion, "
        "no extra limbs, no text, no logos, no flicker, no heavy zoom"
    )

    final_prompt = prompt or default_prompt
    final_negative = negative_prompt or default_negative

    console.print(Panel(
        f"[bold]Session:[/bold] {session_path.name}\n"
        f"[bold]Model:[/bold] {chosen_model}\n"
        f"[bold]Mode:[/bold] {chosen_mode}\n"
        f"[bold]Duration:[/bold] 10s (Kling constraint)\n"
        f"[bold]Loop target:[/bold] {loop_min_seconds:.1f}s–{loop_max_seconds:.1f}s (forward-only)\n"
        f"[bold]Output:[/bold] {out_mp4}",
        title="Session Clip (Kling → Loop)",
    ))
    console.print()

    task_id: str | None = None
    video_url: str | None = None

    try:
        console.print("[bold cyan]Step 1:[/bold cyan] Creating Kling image-to-video task...")
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        task_id = create_image2video_task(
            access_key=s.kling_ai_access_key,
            secret_key=s.kling_ai_secret_key,
            base_url=s.kling_base_url,
            image_b64=image_b64,
            prompt=final_prompt,
            negative_prompt=final_negative,
            model_name=chosen_model,
            mode=chosen_mode,
            duration="10",
        )
        console.print(f"  Task: {task_id}")

        console.print()
        console.print("[bold cyan]Step 2:[/bold cyan] Waiting for Kling to finish...")
        task_result = poll_task_until_complete(
            access_key=s.kling_ai_access_key,
            secret_key=s.kling_ai_secret_key,
            base_url=s.kling_base_url,
            task_id=task_id,
        )
        video_url = extract_video_url(task_result)

        console.print()
        console.print("[bold cyan]Step 3:[/bold cyan] Downloading 10s clip...")
        raw_bytes = download_video_bytes(url=video_url)

        with tempfile.TemporaryDirectory(prefix="coolio_kling_") as d:
            tmp = Path(d)
            raw_path = tmp / "kling_raw.mp4"
            raw_path.write_bytes(raw_bytes)

            console.print()
            console.print("[bold cyan]Step 4:[/bold cyan] Selecting best forward-only loop...")
            selection = select_best_loop(
                raw_path,
                fps=fps,
                loop_min_seconds=loop_min_seconds,
                loop_max_seconds=loop_max_seconds,
            )
            console.print(
                f"  Selected: {selection.start_seconds:.2f}s → {selection.end_seconds:.2f}s "
                f"({selection.duration_seconds:.2f}s), score={selection.score:.3f}"
            )

            console.print()
            console.print("[bold cyan]Step 5:[/bold cyan] Rendering seamless loop...")
            render_forward_only_loop(
                input_video_path=raw_path,
                output_video_path=out_mp4,
                selection=selection,
                seam_seconds=seam_seconds,
            )

    except (KlingError, VideoLoopError, Exception) as e:
        error_path = session_path / "session_clip_error.json"
        try:
            payload = {
                "session_id": session_path.name,
                "created_at": now_iso(),
                "session_image": str(image_path),
                "output_video": str(out_mp4),
                "kling": {
                    "base_url": s.kling_base_url,
                    "model_name": chosen_model,
                    "mode": chosen_mode,
                    "duration": "10",
                    "task_id": task_id,
                    "video_url": video_url,
                },
                "prompt": final_prompt,
                "negative_prompt": final_negative,
                "loop": {
                    "fps": fps,
                    "loop_min_seconds": loop_min_seconds,
                    "loop_max_seconds": loop_max_seconds,
                    "seam_seconds": seam_seconds,
                },
                "error": str(e),
                "error_type": type(e).__name__,
            }
            if isinstance(e, KlingError):
                payload["kling"]["raw_error"] = e.raw
            error_path.write_text(json.dumps(payload, indent=2))
            console.print(f"[yellow]Wrote debug file: {error_path}[/yellow]")
        except Exception:
            pass

        console.print(f"[red]Failed to generate session clip: {e}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[green]Session clip complete![/green]\n\n"
        f"Video: {out_mp4}",
        title="Complete",
    ))


@app.command()
def compose(
    session_dir: str = typer.Argument(
        ...,
        help="Path to session directory (must contain final_mix.mp3, tracklist.txt, session_clip.mp4, session.json)",
    ),
):
    """
    Compose the final upload bundle for YouTube (video + metadata).

    This command renders:
    - final_youtube.mp4 (looped session_clip.mp4 over final_mix.mp3 with a short fade-in)
    - youtube_metadata.json
    - youtube_metadata.txt
    """
    from pathlib import Path

    from coolio.compose import ComposeError, compose_session

    session_path = Path(session_dir)
    console.print(
        Panel(
            f"[bold]Session:[/bold] {session_path}\n"
            "Outputs:\n"
            "  - final_youtube.mp4\n"
            "  - youtube_metadata.json\n"
            "  - youtube_metadata.txt",
            title="Compose (Final YouTube Bundle)",
        )
    )
    console.print()

    try:
        result = compose_session(session_path)
    except ComposeError as e:
        console.print(f"[red]Compose failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Compose failed: {e}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(
        Panel(
            f"[green]Compose complete![/green]\n\n"
            f"Video: {result.final_video_path}\n"
            f"Metadata (JSON): {result.youtube_metadata_json_path}\n"
            f"Metadata (TXT): {result.youtube_metadata_txt_path}",
            title="Complete",
        )
    )


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


@library_app.command("purge-r2")
def library_purge_r2(
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Actually delete objects (default: dry-run).",
    ),
    delete_orphans: bool = typer.Option(
        False,
        "--delete-orphans",
        help="Delete library/tracks/*.mp3 with no readable metadata JSON.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        help="How many example keys to print for keep/delete.",
    ),
):
    """
    Delete all R2 objects except ElevenLabs library tracks.

    Keeps:
      - library/tracks/**/{track_id}.json where provider == "elevenlabs"
      - the matching library/tracks/**/{track_id}.mp3

    Everything else is deleted (sessions/*, non-elevenlabs library tracks, etc).
    """
    s = get_settings()
    console.print(Panel("[bold]R2 Purge (keep ElevenLabs library songs)[/bold]", title="Coolio"))
    console.print(f"[bold]Endpoint:[/bold] {s.r2_endpoint_url}")
    console.print(f"[bold]Bucket:[/bold] {s.r2_bucket_name}")
    console.print(f"[bold]Mode:[/bold] {'DELETE' if yes else 'DRY-RUN'}")
    console.print(f"[bold]Delete orphans:[/bold] {delete_orphans}")
    console.print()

    r2 = R2Storage()

    # ---------------------------------------------------------------------
    # Phase 1: Determine which library tracks to keep (provider == elevenlabs)
    # ---------------------------------------------------------------------
    library_prefix = "library/tracks/"
    mp3_keys: set[str] = set()
    json_keys: set[str] = set()

    keep_keys: set[str] = set()
    elevenlabs_tracks = 0
    non_elevenlabs_tracks = 0
    unreadable_metadata = 0

    # Collect all library keys first so we can detect missing metadata.
    for obj in r2.iter_objects(prefix=library_prefix):
        key = str(obj.get("Key", ""))
        if not key:
            continue
        if key.endswith(".mp3"):
            mp3_keys.add(key)
        elif key.endswith(".json"):
            json_keys.add(key)

    # Read metadata JSON to decide what to keep.
    for meta_key in sorted(json_keys):
        try:
            data = r2.read_json(meta_key)
        except Exception:
            unreadable_metadata += 1
            # Unknown provider -> keep by default unless caller explicitly deletes orphans.
            if not delete_orphans:
                keep_keys.add(meta_key)
                audio_key = meta_key[:-5] + ".mp3"
                if audio_key in mp3_keys:
                    keep_keys.add(audio_key)
            continue

        provider = str(data.get("provider", "")).lower()
        audio_key = meta_key[:-5] + ".mp3"

        if provider == "elevenlabs":
            elevenlabs_tracks += 1
            keep_keys.add(meta_key)
            if audio_key in mp3_keys:
                keep_keys.add(audio_key)
        else:
            non_elevenlabs_tracks += 1

    # Orphan MP3s with no metadata JSON at all.
    orphan_mp3_keys: list[str] = []
    for audio_key in sorted(mp3_keys):
        meta_key = audio_key[:-4] + ".json"
        if meta_key not in json_keys:
            orphan_mp3_keys.append(audio_key)

    if orphan_mp3_keys and not delete_orphans:
        for k in orphan_mp3_keys:
            keep_keys.add(k)

    # ---------------------------------------------------------------------
    # Phase 2: Scan whole bucket and delete everything not in keep-set
    # ---------------------------------------------------------------------
    total_objects = 0
    kept_objects = 0
    delete_count = 0
    sample_keep: list[str] = []
    sample_delete: list[str] = []

    delete_batch: list[str] = []
    deleted_total = 0
    error_total = 0

    def flush_batch() -> None:
        nonlocal deleted_total, error_total
        if not yes or not delete_batch:
            return
        result = r2.delete_objects(delete_batch)
        deleted_total += len(result.get("Deleted", []) or [])
        error_total += len(result.get("Errors", []) or [])
        delete_batch.clear()

    for obj in r2.iter_objects(prefix=""):
        key = str(obj.get("Key", ""))
        if not key:
            continue

        total_objects += 1
        if key in keep_keys:
            kept_objects += 1
            if len(sample_keep) < sample:
                sample_keep.append(key)
            continue

        delete_count += 1
        if len(sample_delete) < sample:
            sample_delete.append(key)

        if yes:
            delete_batch.append(key)
            # Stay well under S3's 1000-key delete limit to bound memory.
            if len(delete_batch) >= 500:
                flush_batch()

    if yes:
        flush_batch()

    # ---------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------
    console.print(Panel("[bold]Summary[/bold]", title="R2 Purge"))
    console.print(f"[bold]Total objects scanned:[/bold] {total_objects}")
    console.print(f"[bold]Kept objects:[/bold] {kept_objects}")
    console.print(f"[bold]Deleted objects:[/bold] {delete_count}")
    console.print()
    console.print(Panel("[bold]Library classification[/bold]", title="Keep Logic"))
    console.print(f"[bold]ElevenLabs tracks (by metadata JSON):[/bold] {elevenlabs_tracks}")
    console.print(f"[bold]Non-ElevenLabs tracks (by metadata JSON):[/bold] {non_elevenlabs_tracks}")
    console.print(f"[bold]Unreadable metadata JSON:[/bold] {unreadable_metadata}")
    console.print(f"[bold]Orphan MP3 (no metadata JSON):[/bold] {len(orphan_mp3_keys)}")
    console.print()

    if sample_keep:
        console.print(Panel("[bold]Example kept keys[/bold]", title=f"Keep (first {min(sample, len(sample_keep))})"))
        for k in sample_keep:
            console.print(f"  [green]KEEP[/green] {k}")
        console.print()

    if sample_delete:
        console.print(Panel("[bold]Example deleted keys[/bold]", title=f"Delete (first {min(sample, len(sample_delete))})"))
        for k in sample_delete:
            console.print(f"  [red]DEL[/red]  {k}")
        console.print()

    if yes:
        console.print(Panel("[bold]Delete results[/bold]", title="R2"))
        console.print(f"[bold]Deleted reported by API:[/bold] {deleted_total}")
        if error_total:
            console.print(f"[bold red]Delete errors reported by API:[/bold red] {error_total}")
        else:
            console.print("[green]No delete errors reported by API.[/green]")


if __name__ == "__main__":
    app()
