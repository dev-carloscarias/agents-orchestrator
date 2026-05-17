import shutil

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

from harness.protocols import (
    TaskMeta,
    TaskPlan,
    TaskType,
    Complexity,
    ProjectProfile,
)
from harness.budget import BudgetManager
from harness.router import ProviderExhausted, build_router_from_config
from harness.orchestrator import Orchestrator
from session.manager import SessionManager, slugify
from session.registry import ProjectRegistry
from ingestors.notion import NotionIngestor, NotionError, parse_page_id
from pipeline.normalizer import Normalizer
from pipeline.classifier import classify_task
from pipeline.context_collector import collect_project_context
from providers.base import ProviderBase

from console.menus.project_menu import select_or_register_project
from console.menus.budget_menu import show_budget_menu
from console.menus.history_menu import run_history_menu
from console.menus.task_menu import run_task_menu

console = Console()

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                    AI DEV HARNESS v1.0                       ║
╚══════════════════════════════════════════════════════════════╝
"""


def _rebuild_orchestrator(profile: ProjectProfile, session: SessionManager, budget: BudgetManager) -> Orchestrator:
    import main as main_mod

    return main_mod.build_orchestrator(profile, session, budget)


def _bar(pct: float | None, width: int = 10) -> str:
    if pct is None:
        return "░" * width
    filled = int(width * min(float(pct), 100.0) / 100.0)
    return "█" * filled + "░" * (width - filled)


def _alert_glyph(level: str) -> str:
    return {"ok": "✓", "warn": "⚠", "critical": "🚨"}.get(level, "✓")


class MainMenu:
    def __init__(self, config: dict, budget: BudgetManager):
        self.config          = config
        self.budget          = budget
        self.registry        = ProjectRegistry()
        self.active_profile: ProjectProfile | None = None
        self.orchestrator: Orchestrator | None = None
        self._warned_clis    = False

    def run(self) -> None:
        while True:
            self._show()
            choice = Prompt.ask(
                "  >",
                choices=["1", "2", "3", "4", "5", "q", "Q"],
                default="1",
            )
            if choice == "1":
                self._new_task()
            elif choice == "2":
                self._resume_task()
            elif choice == "3":
                self._view_history()
            elif choice == "4":
                show_budget_menu(self.budget)
            elif choice == "5":
                self._change_project()
            elif choice.lower() == "q":
                break

    def _cli_warning(self) -> None:
        if self._warned_clis:
            return
        if not shutil.which("claude") and not shutil.which("gemini"):
            console.print(
                "\n  [yellow]⚠  No hay `claude` ni `gemini` en PATH. "
                "Instala las CLIs para planning/ejecución.[/yellow]"
            )
        elif not shutil.which("claude"):
            console.print("\n  [yellow]⚠  `claude` no está en PATH — sin planner local.[/yellow]")
        elif not shutil.which("gemini"):
            console.print("\n  [yellow]⚠  `gemini` no está en PATH — sin executor por defecto.[/yellow]")
        self._warned_clis = True

    def _show(self) -> None:
        console.clear()
        console.print(BANNER)
        self._cli_warning()

        if self.active_profile:
            console.print(f"  Proyecto activo: [cyan]{self.active_profile.name}[/cyan]")
            console.print(f"  [dim]{self.active_profile.project_dir}[/dim]\n")
        else:
            console.print("  Proyecto activo: [yellow]ninguno[/yellow]\n")

        summary = self.budget.daily_summary()
        console.print("  ┌──────────────────────────────────────────────────────────┐")
        console.print("  │  PLANNERS                                                │")
        for key, label in (
            ("claude_sonnet", "Claude Sonnet"),
            ("claude_opus", "Claude Opus"),
        ):
            s = summary.get(key, {})
            pct = s.get("pct")
            now, mx = s.get("requests_now", 0), s.get("requests_max", 0)
            g = _alert_glyph(s.get("alert_level", "ok"))
            bar = _bar(pct)
            pct_s = f"{pct:.0f}%" if pct is not None else "—"
            console.print(
                f"  │  {label:16} {bar}  {pct_s} ({now}/{mx} req)  {g}      │"
            )
        console.print("  │                                                          │")
        console.print("  │  EXECUTORS                                               │")
        for key, label in (
            ("gemini_flash", "Gemini Flash"),
            ("opencode_minimax", "MiniMax Free"),
            ("opencode_bigpickle", "Big Pickle"),
        ):
            s = summary.get(key, {})
            pct = s.get("pct")
            now, mx = s.get("requests_now", 0), s.get("requests_max", 0)
            g = _alert_glyph(s.get("alert_level", "ok"))
            bar = _bar(pct)
            pct_s = f"{pct:.0f}%" if pct is not None else "—"
            console.print(
                f"  │  {label:16} {bar}  {pct_s} ({now}/{mx})  {g}      │"
            )
        console.print("  └──────────────────────────────────────────────────────────┘\n")

        console.print("  [1] Nuevo task")
        console.print("  [2] Retomar task incompleto")
        console.print("  [3] Ver historial de runs")
        console.print("  [4] Budget y uso detallado")
        console.print("  [5] Cambiar / crear proyecto")
        console.print("  [Q] Salir\n")

    def _change_project(self) -> None:
        try:
            profile = select_or_register_project()
        except KeyboardInterrupt:
            return
        self.active_profile = profile
        self.registry.touch(profile.slug)
        session = SessionManager(profile.name, "_placeholder_")
        self.orchestrator = _rebuild_orchestrator(profile, session, self.budget)
        console.print(f"\n  [green]✓  Proyecto activo: {profile.name}[/green]")
        console.print(f"  [dim]{profile.project_dir}[/dim]\n")

    def _ensure_project_selected(self) -> bool:
        if self.active_profile:
            return True
        console.print("\n  [yellow]No hay proyecto activo.[/yellow]\n")
        try:
            profile = select_or_register_project()
        except KeyboardInterrupt:
            return False
        self.active_profile = profile
        self.registry.touch(profile.slug)
        session = SessionManager(profile.name, "_placeholder_")
        self.orchestrator = _rebuild_orchestrator(profile, session, self.budget)
        return True

    def _classification_menu(self, meta: TaskMeta) -> tuple[TaskType, Complexity, str]:
        task_type = meta.task_type
        complexity = meta.complexity

        while True:
            console.rule("[bold]Clasificación del Task")
            stacks = ", ".join(meta.detected_stack) or "(ninguno)"
            console.print(
                f"\n  Detectado automáticamente:\n"
                f"    Tipo:        [cyan]{task_type.value}[/cyan]\n"
                f"    Complejidad: [cyan]{complexity.value}[/cyan]\n"
                f"    Stack:       {stacks}\n"
            )
            sumv = self.budget.daily_summary().get("claude_opus", {})
            op_pct = sumv.get("pct")
            op_n, op_m = sumv.get("requests_now", 0), sumv.get("requests_max", 0)
            console.print(
                f"  [4] EXTRA HIGH → Claude Opus  [dim](Opus: {op_n}/{op_m}"
                + (f", {op_pct:.0f}%)" if op_pct is not None else ")") + "[/dim]"
            )
            choice = Prompt.ask(
                "  Opción [1]=detección [2]=MEDIUM [3]=LOW [4]=EXTRA HIGH [5]=cambiar tipo",
                choices=["1", "2", "3", "4", "5"],
                default="1",
            )
            if choice == "1":
                return task_type, complexity, complexity.value
            if choice == "2":
                complexity = Complexity.medium
                return task_type, complexity, "medium"
            if choice == "3":
                complexity = Complexity.low
                return task_type, complexity, "low"
            if choice == "4":
                console.print(
                    "  [yellow]⚠  EXTRA HIGH usará Claude Opus (mayor consumo de cuota Pro).[/yellow]"
                )
                if Confirm.ask("  ¿Confirmar?", default=False):
                    complexity = Complexity.extra_high
                    return task_type, complexity, "extra_high"
                continue
            if choice == "5":
                tt = Prompt.ask(
                    "  Nuevo tipo",
                    choices=["backend", "frontend", "refactor", "bugfix", "generic"],
                    default=task_type.value,
                )
                task_type = TaskType(tt)
                continue

    def _approve_plan(self, plan: TaskPlan) -> TaskPlan | str | None:
        while True:
            console.rule("[bold]Plan generado")
            lines = []
            for s in plan.steps:
                lines.append(
                    f"{s.index}. {s.description}\n"
                    f"   Archivos: {', '.join(s.target_files)}\n"
                    f"   Validación: {s.validation}\n"
                )
            console.print(Panel("\n".join(lines), title=plan.summary[:80]))
            ch = Prompt.ask(
                "  [A]probar  [R]egenerar  [V]er JSON  [C]ancelar",
                choices=["a", "r", "v", "c", "A", "R", "V", "C"],
                default="a",
            ).lower()
            if ch == "a":
                return plan
            if ch == "r":
                return None
            if ch == "v":
                console.print(plan.model_dump_json(indent=2))
                continue
            if ch == "c":
                return "cancel"

    def _new_task(self) -> None:
        if not self._ensure_project_selected():
            return
        assert self.active_profile is not None

        notion_url = Prompt.ask("\n  URL o ID de página Notion").strip()
        if not notion_url:
            return

        try:
            preview_id = parse_page_id(notion_url)
            console.print(f"  [dim]ID normalizado: {preview_id}[/dim]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

        try:
            ingestor = NotionIngestor(self.config["notion_token"])
            data = ingestor.ingest(notion_url)
        except NotionError as e:
            console.print(f"[red]Notion: {e}[/red]")
            return

        try:
            normalizer = Normalizer(self.config["google_api_key"])
            task_md = normalizer.convert(
                data["raw_text"],
                data["page_id"],
                data["page_url"],
                data["title"],
            )
        except Exception as e:
            console.print(f"[red]Normalizer: {e}[/red]")
            return

        console.print(Panel(task_md[:2000] + ("…" if len(task_md) > 2000 else ""), title="Vista previa task.md"))
        cont = Prompt.ask(
            "  ¿Continuar con este task? [s/n/v]",
            choices=["s", "S", "n", "N", "v", "V"],
            default="s",
        ).lower()
        if cont == "v":
            console.print(Panel(task_md, title="task.md completo"))
            if not Confirm.ask("  ¿Continuar?", default=True):
                return
        elif cont == "n":
            return

        default_ts = slugify(data.get("title") or "task")[:50]
        ts_raw = Prompt.ask("  Identificador del task (carpeta)", default=default_ts).strip()
        task_slug = slugify(ts_raw) if ts_raw else default_ts

        session = SessionManager(self.active_profile.name, task_slug)
        session.save_task(task_md)

        meta = classify_task(task_md)
        tt, cx, cx_str = self._classification_menu(meta)

        if cx != Complexity.low:
            meta_ctx = TaskMeta(
                task_type=tt,
                complexity=cx,
                detected_stack=meta.detected_stack,
                needs_context_collection=True,
            )
            existing = session.load_project_context()
            ctx = collect_project_context(self.active_profile.name, meta_ctx, existing)
            session.save_project_context(ctx)

        try:
            providers = self._safe_build_providers()
            router = build_router_from_config(providers, self.budget)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            return

        try:
            planner = router.select("planner", cx_str, [])
        except ProviderExhausted:
            console.print("[red]No hay planner disponible.[/red]")
            return

        plan = None
        while True:
            try:
                plan = planner.generate_plan(task_md, tt.value)
                self.budget.record(planner.name, task_md, plan.model_dump_json())
            except Exception as e:
                console.print(f"[red]Plan: {e}[/red]")
                if not Confirm.ask("  ¿Reintentar?", default=True):
                    return
                continue

            plan = plan.model_copy(update={"task_type": tt, "complexity": cx})
            ap = self._approve_plan(plan)
            if ap == "cancel":
                return
            if ap is not None:
                plan = ap
                break
            console.print("[dim]Regenerando plan…[/dim]")

        session.start_new_run(plan)
        self.orchestrator = _rebuild_orchestrator(self.active_profile, session, self.budget)
        self.orchestrator.run(task_md, plan, cx_str)
        run_task_menu(session)

    def _safe_build_providers(self) -> list[ProviderBase]:
        import main as main_mod

        assert self.active_profile is not None
        return main_mod.build_providers(self.active_profile.project_dir)

    def _resume_task(self) -> None:
        if not self._ensure_project_selected():
            return
        assert self.active_profile is not None
        slug_raw = Prompt.ask("  Slug del task").strip()
        if not slug_raw:
            return
        task_slug = slugify(slug_raw)
        session = SessionManager(self.active_profile.name, task_slug)
        if not session.task_exists():
            console.print("[yellow]No existe ese task.[/yellow]")
            return
        plan, prog = session.resume_latest_run()
        if not plan or not prog:
            console.print("[yellow]No hay run incompleto para retomar.[/yellow]")
            return
        task_md = session.load_task()
        cx_str = plan.complexity.value
        self.orchestrator = _rebuild_orchestrator(self.active_profile, session, self.budget)
        self.orchestrator.resume(task_md, plan, prog, cx_str)

    def _view_history(self) -> None:
        if not self._ensure_project_selected():
            return
        assert self.active_profile is not None
        run_history_menu(self.active_profile)
