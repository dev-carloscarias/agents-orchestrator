from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from harness.protocols import *
from harness.router import Router, ProviderExhausted
from harness.budget import BudgetManager
from session.manager import SessionManager
from pipeline.diff_reporter import capture_snapshot, compute_diff, detect_file_changes
from providers.base import ProviderError

console = Console()


class Orchestrator:
    def __init__(
        self,
        router: Router,
        budget: BudgetManager,
        session: SessionManager,
        project_dir: str | None = None,
    ):
        self.router       = router
        self.budget       = budget
        self.session      = session
        self.project_dir  = project_dir

    def run(self, task_md: str, plan: TaskPlan, complexity: str):
        """Ejecuta el plan completo step-by-step con confirmación del usuario."""
        pending = [s.index for s in plan.steps]
        self._execute_steps(task_md, plan, pending, complexity)

    def resume(self, task_md: str, plan: TaskPlan, progress: RunProgress, complexity: str):
        """Retoma un run incompleto desde los steps pendientes."""
        pending = self.session.pending_steps(plan, progress)
        if not pending:
            console.print("[green]No hay steps pendientes — el run ya está completo.[/green]")
            return
        console.print(f"[cyan]Retomando — {len(pending)} step(s) pendiente(s)[/cyan]")
        self._execute_steps(task_md, plan, pending, complexity)

    def _execute_steps(self, task_md: str, plan: TaskPlan, pending: list[int], complexity: str):
        task_type    = plan.task_type.value
        plan_summary = self._build_summary(plan, self.project_dir)

        for step in plan.steps:
            if step.index not in pending:
                continue

            # Verificar dependencias
            if not self._deps_met(step, plan):
                console.print(f"[yellow]Step {step.index}: dependencias no cumplidas — saltando[/yellow]")
                self.session.mark_step_skipped(step.index)
                continue

            result = self._run_step(step, task_md, plan_summary, task_type, complexity)

            if result is None:   # usuario canceló o agotó reintentos
                self.session.mark_step_cancelled(step.index)
                self.session.mark_run_cancelled()
                console.print("\n[yellow]Ejecución cancelada.[/yellow]")
                return

            self.session.save_step_artifacts(
                step.index, result.output, result.diff_patch,
                [f.model_dump() for f in result.files_changed],
            )

            if result.status == StepStatus.completed:
                self.session.mark_step_completed(
                    step.index, result.executor_used,
                    result.tokens_used, len(result.files_changed),
                )
            elif result.status == StepStatus.skipped:
                self.session.mark_step_skipped(step.index)
            else:
                self.session.mark_step_failed(step.index, result.executor_used, result.error or "")
                if not Confirm.ask(f"\n[red]Step {step.index} falló.[/red] ¿Continuar con el siguiente?"):
                    self.session.mark_run_failed()
                    return

        self.session.mark_run_completed()
        self._show_summary(plan)

    def _run_step(
        self, step: Step, task_md: str, plan_summary: str,
        task_type: str, complexity: str,
    ) -> StepResult | None:
        console.rule(f"[bold cyan]Step {step.index}: {step.description}")
        console.print(f"  Archivos: [cyan]{', '.join(step.target_files)}[/cyan]")
        console.print(f"  Validación: [dim]{step.validation}[/dim]\n")

        choice = self._step_menu()
        if choice == "cancel":
            return None
        if choice == "skip":
            return StepResult(
                step_index=step.index, status=StepStatus.skipped,
                output="Skipped by user", tokens_used=0,
                executor_used="none", provider_model="none", duration_seconds=0,
            )

        # Snapshot antes
        snapshot_before = capture_snapshot(step.target_files)

        # Ejecutar con failover interactivo
        tried = []
        for attempt in range(3):
            try:
                executor = self.router.select_with_failover("executor", complexity, tried)
            except ProviderExhausted:
                console.print("[red]Todos los executors agotados.[/red]")
                return StepResult(
                    step_index=step.index, status=StepStatus.failed, output="",
                    tokens_used=0, executor_used="none", provider_model="none",
                    duration_seconds=0, error="all_providers_exhausted",
                )

            console.print(f"  [dim]Ejecutando con {executor.name}...[/dim]")
            try:
                result = executor.execute_step(step, task_md, plan_summary, task_type)

                # Registrar tokens reales
                tokens = self.budget.record(executor.name, task_md, result.output)
                result.tokens_used = tokens

                # Diff
                snapshot_after     = capture_snapshot(step.target_files)
                result.diff_patch  = compute_diff(snapshot_before, snapshot_after)
                result.files_changed = detect_file_changes(snapshot_before, snapshot_after)

                self._show_result(result)
                return result

            except ProviderError as e:
                tried.append(e.provider)
                console.print(f"\n[red]Error con {e.provider}:[/red] {e}")
                if not Confirm.ask("¿Reintentar con otro provider?"):
                    return StepResult(
                        step_index=step.index, status=StepStatus.failed, output="",
                        tokens_used=0, executor_used=e.provider, provider_model="",
                        duration_seconds=0, error=str(e),
                    )

        return None

    def _step_menu(self) -> str:
        console.print("  [1] Ejecutar   [2] Saltar   [3] Cancelar todo")
        choice = Prompt.ask("  Opción", choices=["1", "2", "3"], default="1")
        return {"1": "execute", "2": "skip", "3": "cancel"}[choice]

    def _show_result(self, result: StepResult):
        console.print(f"\n[bold green]✓ Step {result.step_index} completado[/bold green]")
        console.print(
            f"  Provider: [cyan]{result.executor_used}[/cyan]  "
            f"Tokens: [cyan]{result.tokens_used:,}[/cyan]  "
            f"Tiempo: [cyan]{result.duration_seconds:.1f}s[/cyan]"
        )
        if result.files_changed:
            console.print(f"  Archivos tocados ({len(result.files_changed)}):")
            for fc in result.files_changed:
                console.print(f"    [dim]{fc.action}[/dim]  {fc.path}")

        console.print("\n  [bold]Output:[/bold]")
        preview = result.output[:600] + ("\n  [dim]...(truncado)[/dim]" if len(result.output) > 600 else "")
        console.print(preview)

        if result.diff_patch:
            console.print("\n  [bold]Diff:[/bold]")
            console.print(Syntax(result.diff_patch[:1200], "diff", theme="monokai"))

    def _show_summary(self, plan: TaskPlan):
        console.rule("[bold green]Run Completado")
        console.print(f"  Task:  {plan.summary}")
        console.print(f"  Steps: {len(plan.steps)} completados")

    @staticmethod
    def _build_summary(plan: TaskPlan, project_dir: str | None = None) -> str:
        lines = []
        if project_dir:
            lines.append(f"Directorio del proyecto: {project_dir}")
        lines.extend([
            f"Objetivo: {plan.summary}",
            f"Tipo: {plan.task_type.value}",
            "Steps:",
        ])
        for s in plan.steps:
            lines.append(f"  {s.index}. {s.description}")
        return "\n".join(lines)

    @staticmethod
    def _deps_met(step: Step, plan: TaskPlan) -> bool:
        # En v1.0 asumimos linear — en v2 trackear completed steps
        return True
