"""CLI interface for Coolio music generation."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from coolio.core.config import get_settings
from coolio.agents.curator import generate_curation_plan
from coolio.library.query import LibraryQuery
from coolio.models import SessionPlan
from coolio.music.generator import MusicGenerator

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
    genre: str = typer.Option(
        ...,
        "--genre",
        "-g",
        help="Required: Genre for library lookup and organization (e.g., techno, house, lofi)",
    ),
    tracks: int = typer.Option(
        15,
        "--tracks",
        "-t",
        help="Target number of tracks (12-20 recommended for 1hr)",
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
):
    """
    Generate a music session with smart library reuse.

    The Curator agent first checks the R2 library for existing tracks that fit
    your concept, then fills gaps with new generation. This is the unified
    entry point for all music generation.

    Example:
        coolio generate "Berlin techno, minimal, hypnotic focus" --genre techno
        coolio generate "lofi hip hop for studying" --genre lofi --no-library
    """
    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}\n[bold]Genre:[/bold] {genre}",
        title="Coolio Music Generator"
    ))
    console.print()

    # Step 1: Query Library (unless --no-library)
    candidates = []
    if not no_library:
        console.print("[bold cyan]Step 1:[/bold cyan] Querying library for reusable tracks...")
        try:
            query = LibraryQuery()
            candidates = query.query_tracks(genre=genre, exclude_days=exclude_days)
            if candidates:
                console.print(f"  Found {len(candidates)} available tracks for potential reuse.")
            else:
                console.print("  [yellow]No matching tracks found in library.[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Library query failed: {e}[/yellow]")
            console.print("  Proceeding with full generation.")
    else:
        console.print("[bold cyan]Step 1:[/bold cyan] Skipping library lookup (--no-library)")
    console.print()

    # Step 2: Curator Agent Plans Session
    console.print("[bold cyan]Step 2:[/bold cyan] Curator agent planning session...")
    console.print(f"  Model: {model or get_settings().openrouter_model}")
    console.print(f"  Target: {tracks} tracks, {duration} minutes")
    console.print(f"  Budget: ${budget:.2f}")
    console.print()

    try:
        plan = generate_curation_plan(
            concept=concept,
            genre=genre,
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
    genre: str = typer.Option(
        ...,
        "--genre",
        "-g",
        help="Required: Genre for library lookup",
    ),
    tracks: int = typer.Option(
        15,
        "--tracks",
        "-t",
        help="Target number of tracks (12-20 recommended for 1hr)",
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

    Shows how the Curator would mix library tracks with new generation.
    Useful for previewing before spending credits.

    Example:
        coolio plan "lofi hip hop, rainy day vibes" --genre lofi
    """
    console.print(Panel(
        f"[bold]Concept:[/bold] {concept}\n[bold]Genre:[/bold] {genre}",
        title="Session Plan Preview"
    ))
    console.print()

    # Query Library
    candidates = []
    if not no_library:
        console.print("Querying library for reusable tracks...")
        try:
            query = LibraryQuery()
            candidates = query.query_tracks(genre=genre, exclude_days=exclude_days)
            if candidates:
                console.print(f"Found {len(candidates)} available tracks.")
            else:
                console.print("[yellow]No matching tracks in library.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Library query failed: {e}[/yellow]")
    console.print()

    # Generate Plan
    console.print(f"Planning with model: {model or get_settings().openrouter_model}")
    console.print()

    try:
        plan = generate_curation_plan(
            concept=concept,
            genre=genre,
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


# Keep curate as an alias for backwards compatibility
@app.command(hidden=True)
def curate(
    concept: str = typer.Argument(...),
    genre: str = typer.Option(..., "--genre", "-g"),
    tracks: int = typer.Option(15, "--tracks", "-t"),
    duration: int = typer.Option(60, "--duration", "-d"),
    exclude_days: int = typer.Option(7, "--exclude-days"),
    budget: float = typer.Option(5.00, "--budget", "-b"),
    model: str = typer.Option(None, "--model", "-m"),
    skip_audio: bool = typer.Option(False, "--skip-audio"),
    skip_upload: bool = typer.Option(False, "--skip-upload"),
):
    """
    [DEPRECATED] Use 'coolio generate' instead.

    This command is kept for backwards compatibility.
    """
    console.print("[yellow]Note: 'curate' is deprecated. Use 'generate' instead.[/yellow]")
    console.print()

    # Forward to generate
    generate(
        concept=concept,
        genre=genre,
        tracks=tracks,
        duration=duration,
        budget=budget,
        model=model,
        exclude_days=exclude_days,
        no_library=False,
        skip_audio=skip_audio,
        skip_upload=skip_upload,
    )


if __name__ == "__main__":
    app()
