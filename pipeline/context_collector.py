from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from harness.protocols import ProjectContext, TaskMeta
from pathlib import Path
import json

console = Console()


def collect_project_context(
    project_name:     str,
    task_meta:        TaskMeta,
    existing_context: ProjectContext | None,
) -> ProjectContext:
    """
    Recopila contexto del proyecto interactivamente.
    Si hay contexto guardado, ofrece reutilizarlo.
    """
    console.rule("[bold cyan]Contexto del Proyecto")

    if existing_context:
        console.print(f"\n[yellow]Se encontró contexto guardado para '{project_name}':[/yellow]")
        _display_context(existing_context)
        if Confirm.ask("\n¿Reutilizar este contexto?", default=True):
            return existing_context
        console.print("[dim]Actualizando contexto...[/dim]\n")

    # Sugerir stack detectado automáticamente
    stack_default = ", ".join(task_meta.detected_stack) if task_meta.detected_stack else ""
    if stack_default:
        console.print(f"[dim]Stack detectado en el task: {stack_default}[/dim]")

    console.print()
    stack       = Prompt.ask("Stack tecnológico del proyecto", default=stack_default)
    key_files   = Prompt.ask("Archivos clave del proyecto (separados por coma)", default="")
    constraints = Prompt.ask("Restricciones técnicas que el agente debe respetar", default="Ninguna")
    conventions = Prompt.ask("Convenciones del proyecto (naming, patterns, etc.)", default="Ninguna")

    return ProjectContext(
        project_name=project_name,
        stack=[s.strip() for s in stack.split(",") if s.strip()],
        key_files=[f.strip() for f in key_files.split(",") if f.strip()],
        constraints=[c.strip() for c in constraints.split(".") if c.strip() and c.strip().lower() != "ninguna"],
        conventions=[c.strip() for c in conventions.split(".") if c.strip() and c.strip().lower() != "ninguna"],
    )


def _display_context(ctx: ProjectContext):
    console.print(f"  [cyan]Stack:[/cyan]         {', '.join(ctx.stack) or '(no especificado)'}")
    console.print(f"  [cyan]Archivos clave:[/cyan] {', '.join(ctx.key_files) or '(no especificado)'}")
    console.print(f"  [cyan]Restricciones:[/cyan]  {', '.join(ctx.constraints) or 'Ninguna'}")
    console.print(f"  [cyan]Convenciones:[/cyan]   {', '.join(ctx.conventions) or 'Ninguna'}")
