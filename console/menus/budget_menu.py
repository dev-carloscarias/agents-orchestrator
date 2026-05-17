from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from datetime import datetime

from harness.budget import BudgetManager

console = Console()

PLANNER_KEYS = ("claude_sonnet", "claude_opus")
EXECUTOR_KEYS = ("gemini_flash", "opencode_minimax", "opencode_bigpickle")

LABELS = {
    "claude_sonnet": "Claude Sonnet",
    "claude_opus": "Claude Opus",
    "gemini_flash": "Gemini Flash",
    "opencode_minimax": "MiniMax Free",
    "opencode_bigpickle": "Big Pickle",
}


def _icon(level: str) -> str:
    return {"ok": "✓ OK", "warn": "⚠ WARN", "critical": "🚨 CRIT"}.get(level, "—")


def show_budget_menu(budget: BudgetManager) -> None:
    console.rule("[bold]Budget y Uso")
    console.print(f"\n  Fecha: {datetime.utcnow().date()}   UTC: {datetime.utcnow().strftime('%H:%M')}\n")

    summary = budget.daily_summary()

    console.print("  [bold]PLANNERS[/bold] [dim](ventana deslizante 5h donde aplica)[/dim]\n")
    t1 = Table(show_header=True, header_style="bold cyan")
    t1.add_column("Provider")
    t1.add_column("Usados", justify="right")
    t1.add_column("Límite", justify="right")
    t1.add_column("Estado")
    for key in PLANNER_KEYS:
        s = summary.get(key, {})
        lim = s.get("requests_max") or 0
        now = s.get("requests_now", 0)
        pct = s.get("pct")
        lim_s = f"~{lim} req" if s.get("window_type") == "rolling" else f"{lim}/día"
        st = _icon(s.get("alert_level", "ok"))
        pct_s = f" ({pct:.0f}%)" if pct is not None else ""
        t1.add_row(LABELS[key], f"{now} req", lim_s, f"{st}{pct_s}")
    console.print(t1)

    console.print("\n  [bold]EXECUTORS[/bold]\n")
    t2 = Table(show_header=True, header_style="bold cyan")
    t2.add_column("Provider")
    t2.add_column("Usados", justify="right")
    t2.add_column("Límite", justify="right")
    t2.add_column("Estado")
    for key in EXECUTOR_KEYS:
        s = summary.get(key, {})
        now = s.get("requests_now", 0)
        lim = s.get("requests_max") or 0
        pct = s.get("pct")
        if key == "gemini_flash":
            lim_s = f"{lim}/día"
        elif key == "opencode_minimax":
            lim_s = f"~{lim}/día"
        else:
            lim_s = f"{lim}/5h"
        st = _icon(s.get("alert_level", "ok"))
        pct_s = f" ({pct:.0f}%)" if pct is not None else ""
        t2.add_row(LABELS[key], f"{now:,} req" if now > 100 else f"{now} req", lim_s, f"{st}{pct_s}")
    console.print(t2)

    console.print()
    for key in EXECUTOR_KEYS:
        msg = budget.projected_exhaustion(key)
        if msg:
            console.print(f"  [dim]{LABELS[key]}: agotamiento estimado {msg} a la tasa actual.[/dim]")

    tot = sum(summary.get(k, {}).get("tokens_today", 0) for k in list(summary.keys()))
    console.print(f"\n  [dim]Tokens totales hoy (aprox.): {tot:,}[/dim]\n")

    Prompt.ask("  Pulsa Enter para volver", default="")
