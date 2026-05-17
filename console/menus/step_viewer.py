"""Visor de artefactos de un step guardados en disco."""
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax
from rich.prompt import Prompt

console = Console()


def view_step_detail(run_dir: Path, step_index: int) -> None:
    steps = run_dir / "steps"
    out = steps / f"step_{step_index}_output.md"
    diff = steps / f"step_{step_index}_diff.patch"
    meta = steps / f"step_{step_index}_files.json"

    console.rule(f"[bold]Step {step_index} — detalle")
    if out.exists():
        console.print("\n[bold]Output:[/bold]\n")
        console.print(out.read_text(encoding="utf-8", errors="replace"))
    else:
        console.print("[dim]Sin archivo de output.[/dim]")

    if diff.exists():
        text = diff.read_text(encoding="utf-8", errors="replace")
        console.print("\n[bold]Diff:[/bold]\n")
        console.print(Syntax(text, "diff", theme="monokai"))

    if meta.exists():
        console.print("\n[bold]Archivos (JSON):[/bold]\n")
        console.print(meta.read_text(encoding="utf-8", errors="replace"))

    Prompt.ask("\n  Enter para volver", default="")


def browse_steps_interactive(run_dir: Path) -> None:
    steps_dir = run_dir / "steps"
    if not steps_dir.exists():
        console.print("[yellow]No hay steps guardados.[/yellow]")
        Prompt.ask("  Enter", default="")
        return
    outputs = sorted(steps_dir.glob("step_*_output.md"))
    if not outputs:
        console.print("[yellow]Sin outputs de steps.[/yellow]")
        Prompt.ask("  Enter", default="")
        return
    for p in outputs:
        try:
            idx = int(p.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        console.print(f"  Step {idx}")
    raw = Prompt.ask("  Índice del step a ver (o b)", default="b")
    if raw.lower() in ("b", "back", ""):
        return
    try:
        view_step_detail(run_dir, int(raw))
    except ValueError:
        pass
