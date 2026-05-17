"""Menú del task activo (plan y progreso)."""
import json

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from harness.protocols import TaskPlan, RunProgress
from session.manager import SessionManager

console = Console()


def run_task_menu(session: SessionManager) -> None:
    console.rule("[bold]Task activo")
    if not session.task_exists():
        console.print("[yellow]No hay task.md en esta sesión.[/yellow]")
        Prompt.ask("  Enter", default="")
        return

    task_md = session.load_task()
    plan_path = None
    progress_path = None
    if session.runs_dir.exists():
        sub = sorted([p for p in session.runs_dir.iterdir() if p.is_dir()], reverse=True)
        for rd in sub:
            if (rd / "plan.json").exists():
                plan_path = rd / "plan.json"
                progress_path = rd / "progress.json"
                break

    if plan_path and plan_path.exists():
        plan = TaskPlan(**json.loads(plan_path.read_text()))
        lines = [f"{s.index}. {s.description}" for s in plan.steps]
        console.print(Panel("\n".join(lines), title=f"Plan — {plan.summary[:60]}"))
        if progress_path and progress_path.exists():
            pr = RunProgress(**json.loads(progress_path.read_text()))
            st = pr.status.value if hasattr(pr.status, "value") else pr.status
            console.print(f"\n  Estado run: {st}")
            for k, v in sorted(pr.steps.items(), key=lambda x: int(x[0])):
                console.print(f"    Step {k}: {v.get('status', '?')}")
    else:
        console.print(Panel(task_md[:1200] + ("…" if len(task_md) > 1200 else ""), title="task.md (preview)"))

    Prompt.ask("\n  Enter para volver", default="")
