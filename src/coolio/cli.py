"""CLI interface for Coolio music generation."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from coolio.core.config import get_settings
from coolio.music.agent import generate_session_plan
from coolio.music.generator import MusicGenerator

app = typer.Typer(
    name="coolio",
    help="Generate study/productivity music for YouTube using AI.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def generate(
    concept: str = typer.Argument(
        ...,
        help="Video concept describing genre, vibe, mood, and purpose",
    ),
    tracks: int = typer.Option(
        5,
        "--tracks",
        "-t",
        help="Number of tracks to generate",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use (default: from settings)",
    ),
    skip_audio: bool = typer.Option(
        False,
        "--skip-audio",
        help="Only generate track plans, don't create audio",
    ),
    no_composition_plan: bool = typer.Option(
        False,
        "--no-composition-plan",
        help="Generate audio directly from prompts (skip composition plan step)",
    ),
):
    """
    Generate tracks for a video concept.

    The AI agent will interpret your concept and create a cohesive set of tracks
    that flow together for a study/productivity session.

    Example:
        coolio generate "2hr Berlin techno mix, minimal, hypnotic, for deep focus"
    """
    console.print(Panel(f"[bold]Concept:[/bold] {concept}", title="Coolio Music Generator"))
    console.print()

    # Step 1: Generate session plan using AI agent
    console.print("[bold cyan]Step 1:[/bold cyan] Generating track plans with AI...")
    console.print(f"  Model: {model or get_settings().openrouter_model}")
    console.print(f"  Tracks: {tracks}")
    console.print()

    try:
        session_plan = generate_session_plan(
            concept=concept,
            track_count=tracks,
            model=model,
        )
    except Exception as e:
        console.print(f"[red]Error generating session plan: {e}[/red]")
        raise typer.Exit(1)

    # Display track plans
    table = Table(title="Track Plans")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Role", style="green", width=12)
    table.add_column("Duration", width=10)
    table.add_column("Prompt Preview", style="dim")

    for track in session_plan.tracks:
        duration_sec = track.duration_ms // 1000
        duration_str = f"{duration_sec // 60}:{duration_sec % 60:02d}"
        prompt_preview = track.prompt[:60] + "..." if len(track.prompt) > 60 else track.prompt

        table.add_row(
            str(track.order),
            track.role,
            duration_str,
            prompt_preview,
        )

    console.print(table)
    console.print()

    if skip_audio:
        console.print("[yellow]Skipping audio generation (--skip-audio)[/yellow]")
        return

    # Step 2: Generate audio with ElevenLabs
    console.print("[bold cyan]Step 2:[/bold cyan] Generating audio with ElevenLabs...")
    console.print()

    generator = MusicGenerator()

    try:
        session = generator.generate_session(
            session_plan=session_plan,
            use_composition_plan=not no_composition_plan,
        )
    except Exception as e:
        console.print(f"[red]Error generating audio: {e}[/red]")
        raise typer.Exit(1)

    # Summary
    console.print()
    console.print(Panel(
        f"[green]Successfully generated {len(session.tracks)} tracks![/green]\n\n"
        f"Session ID: {session.session_id}\n"
        f"Output: {session.session_dir}",
        title="Complete",
    ))


@app.command()
def plan(
    concept: str = typer.Argument(
        ...,
        help="Video concept describing genre, vibe, mood, and purpose",
    ),
    tracks: int = typer.Option(
        5,
        "--tracks",
        "-t",
        help="Number of tracks to plan",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="OpenRouter model to use",
    ),
):
    """
    Generate and display track plans without creating audio.

    Useful for previewing what the AI will generate before spending ElevenLabs credits.

    Example:
        coolio plan "lofi hip hop, rainy day vibes, cozy study session"
    """
    console.print(Panel(f"[bold]Concept:[/bold] {concept}", title="Track Planning"))
    console.print()

    console.print(f"Generating {tracks} track plans...")
    console.print(f"Model: {model or get_settings().openrouter_model}")
    console.print()

    try:
        session_plan = generate_session_plan(
            concept=concept,
            track_count=tracks,
            model=model,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    for track in session_plan.tracks:
        duration_sec = track.duration_ms // 1000
        duration_str = f"{duration_sec // 60}:{duration_sec % 60:02d}"

        console.print(Panel(
            f"[bold]Prompt:[/bold]\n{track.prompt}\n\n"
            f"[bold]Notes:[/bold] {track.notes}",
            title=f"Track {track.order}: {track.role} ({duration_str})",
        ))
        console.print()


@app.command()
def config():
    """Show current configuration."""
    console.print(Panel("[bold]Current Configuration[/bold]", title="Coolio"))

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    # API Keys (masked)
    s = get_settings()
    elevenlabs_key = s.elevenlabs_api_key
    elevenlabs_preview = f"{elevenlabs_key[:8]}...{elevenlabs_key[-4:]}" if len(elevenlabs_key) > 12 else "***"

    openrouter_key = s.openrouter_api_key
    openrouter_preview = f"{openrouter_key[:8]}...{openrouter_key[-4:]}" if len(openrouter_key) > 12 else "***"

    table.add_row("ElevenLabs API Key", elevenlabs_preview)
    table.add_row("OpenRouter API Key", openrouter_preview)
    table.add_row("OpenRouter Model", s.openrouter_model)
    table.add_row("OpenRouter Base URL", s.openrouter_base_url)
    table.add_row("Output Directory", str(s.output_dir))
    table.add_row("Default Track Count", str(s.default_track_count))
    table.add_row("Default Duration", f"{s.default_track_duration_ms // 1000}s")
    table.add_row("Max Duration", f"{s.max_track_duration_ms // 1000}s")

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
        ("openai/gpt-5.1", "OpenAI", "Latest GPT, excellent structured output"),
        ("google/gemini-3-pro-preview", "Google", "Large context, good value"),
        ("moonshotai/kimi-k2-thinking", "Moonshot", "Strong reasoning capabilities"),
    ]

    for model_id, provider, notes in models_list:
        table.add_row(model_id, provider, notes)

    console.print(table)
    console.print()
    console.print("Use with: [cyan]coolio generate \"...\" --model <model-id>[/cyan]")


if __name__ == "__main__":
    app()

