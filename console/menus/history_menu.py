"""Historial de runs por proyecto y task."""
import json
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax

from harness.protocols import TaskPlan, RunProgress, ProjectProfile
from session.manager import SessionManager
from session.registry import PROJECTS_ROOT
from console.menus.step_viewer import view_step_detail

console = Console()


def _list_task_slugs(project_slug: str) -> list[str]:
    root = PROJECTS_ROOT / project_slug
    if not root.exists():
        return []
    slugs = []
    for p in root.iterdir():
        if p.is_dir() and (p / "task.md").exists():
            slugs.append(p.name)
    return sorted(slugs)


def run_history_menu(profile: ProjectProfile) -> None:
    console.rule("[bold]Historial de Runs")
    tasks = _list_task_slugs(profile.slug)
    if not tasks:
        console.print("\n[yellow]No hay tasks guardados para este proyecto.[/yellow]\n")
        Prompt.ask("  Enter", default="")
        return

    console.print("\n  Tasks:\n")
    for i, t in enumerate(tasks, 1):
        console.print(f"    [{i}] {t}")
    console.print()
    ch = Prompt.ask("  Elige task (número) o b", default="1")
    if ch.lower() in ("b", "back"):
        return
    try:
        task_slug = tasks[int(ch) - 1]
    except (ValueError, IndexError):
        return

    sm = SessionManager(profile.name, task_slug)
    runs = sm.list_runs()
    if not runs:
        console.print("[yellow]No hay runs.[/yellow]")
        Prompt.ask("  Enter", default="")
        return

    while True:
        console.print(f"\n  Historial: [cyan]{profile.name}[/cyan] / [cyan]{task_slug}[/cyan]\n")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Run")
        table.add_column("Estado")
        table.add_column("Steps")
        table.add_column("Última act.")
        for i, r in enumerate(runs, 1):
            st = r["status"]
            if hasattr(st, "value"):
                st = st.value
            ok = r["steps_ok"]
            fl = r["steps_fail"]
            table.add_row(str(i), str(st), f"{ok} ok / {fl} fail", str(r["updated_at"])[:19])
        console.print(table)
        console.print("\n  [1-N] Detalle   [L] Limpiar historial   [B] Volver\n")
        choice = Prompt.ask("  Opción", default="b")
        if choice.lower() == "b":
            break
        if choice.lower() == "l":
            if Confirm.ask("  ¿Borrar todos los runs? (se conservan task.md y contexto)", default=False):
                sm.clear_history()
                console.print("[green]Historial limpiado.[/green]")
                runs = sm.list_runs()
                if not runs:
                    break
            continue
        try:
            idx = int(choice) - 1
            r = runs[idx]
        except (ValueError, IndexError):
            continue
        _run_detail_menu(sm, r["run_dir"])


def _run_detail_menu(sm: SessionManager, run_dir: Path) -> None:
    plan_path = run_dir / "plan.json"
    prog_path = run_dir / "progress.json"
    if not plan_path.exists():
        return
    plan = TaskPlan(**json.loads(plan_path.read_text()))
    progress = RunProgress(**json.loads(prog_path.read_text())) if prog_path.exists() else None

    console.rule(f"[bold]Detalle {run_dir.name}")
    console.print(f"\n  Plan: {plan.summary}")
    if progress:
        st = progress.status.value if hasattr(progress.status, "value") else progress.status
        console.print(f"  Estado run: {st}\n")

    for step in plan.steps:
        key = str(step.index)
        st = "pending"
        if progress and key in progress.steps:
            st = progress.steps[key].get("status", "?")
        console.print(f"  Step {step.index}: {st} — {step.description[:60]}...")

    console.print("\n  [S] Output step   [D] Diff step   [R] Retomar   [B] Atrás\n")
    choice = Prompt.ask("  Opción", default="b").lower()
    if choice == "b":
        return
    if choice == "r":
        sm._current_run = run_dir
        console.print("[dim]Run marcado para sesión; usa Retomar en el menú principal.[/dim]")
        Prompt.ask("  Enter", default="")
        return
    if choice in ("s", "d"):
        raw = Prompt.ask("  Índice de step")
        try:
            si = int(raw)
        except ValueError:
            return
        if choice == "s":
            view_step_detail(run_dir, si)
        else:
            p = run_dir / "steps" / f"step_{si}_diff.patch"
            if p.exists():
                console.print(Syntax(p.read_text(encoding="utf-8", errors="replace"), "diff", theme="monokai"))
            Prompt.ask("  Enter", default="")
