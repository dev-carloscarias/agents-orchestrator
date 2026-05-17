from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from pathlib import Path
from session.registry import ProjectRegistry, PROJECTS_ROOT
from harness.protocols import ProjectProfile
from session.manager import slugify
from datetime import datetime

console  = Console()
registry = ProjectRegistry()


def select_or_register_project() -> ProjectProfile:
    """
    Punto de entrada del menú de proyecto.
    Retorna el ProjectProfile del proyecto seleccionado o registrado.
    Siempre retorna un perfil válido con project_dir verificado.
    """
    while True:
        console.rule("[bold]Selección de Proyecto")
        console.print("\n  ¿Qué quieres hacer?\n")
        console.print("  [1] Usar un proyecto ya registrado")
        console.print("  [2] Registrar un proyecto nuevo")
        console.print("  [B] Volver al menú principal\n")

        choice = Prompt.ask("  Opción", choices=["1", "2", "b", "B"], default="1")

        if choice.lower() == "b":
            raise KeyboardInterrupt

        if choice == "1":
            profile = _select_existing()
            if profile:
                return profile

        elif choice == "2":
            profile = _register_new()
            if profile:
                return profile


def _select_existing() -> ProjectProfile | None:
    projects = registry.list_projects()

    if not projects:
        console.print("\n  [yellow]No hay proyectos registrados todavía.[/yellow]")
        console.print("  Usa la opción [2] para registrar tu primer proyecto.\n")
        Prompt.ask("  [Enter para volver]", default="")
        return None

    console.print()
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    table.add_column("#",          style="bold", width=4)
    table.add_column("Nombre",     min_width=20)
    table.add_column("Carpeta",    min_width=30)
    table.add_column("Último uso", min_width=15)

    for i, p in enumerate(projects, 1):
        age = _relative_time(p.last_used)
        table.add_row(str(i), p.name, p.project_dir, age)

    console.print(table)
    console.print()

    choices = [str(i) for i in range(1, len(projects) + 1)] + ["b", "B"]
    choice  = Prompt.ask("  Selecciona", choices=choices, default="1")

    if choice.lower() == "b":
        return None

    profile = projects[int(choice) - 1]

    console.print(f"\n  [dim]Verificando carpeta {profile.project_dir}...[/dim]")
    valid, error = registry.validate_dir(profile.project_dir)

    if not valid:
        console.print(f"  [red]✗  {error}[/red]")
        return _handle_missing_dir(profile)

    console.print(f"  [green]✓  Carpeta encontrada y accesible.[/green]")
    console.print(f"  [green]✓  Proyecto activo: {profile.name}  →  {profile.project_dir}[/green]\n")

    registry.touch(profile.slug)
    return profile


def _handle_missing_dir(profile: ProjectProfile) -> ProjectProfile | None:
    console.print("\n  ¿Qué quieres hacer?\n")
    console.print("  [1] Actualizar la ruta del proyecto")
    console.print("  [2] Eliminar este proyecto del registro")
    console.print("  [B] Volver\n")

    choice = Prompt.ask("  Opción", choices=["1", "2", "b", "B"], default="1")

    if choice.lower() == "b":
        return None

    if choice == "2":
        if Confirm.ask(f"  ¿Eliminar '{profile.name}' del registro?", default=False):
            import shutil
            project_path = PROJECTS_ROOT / profile.slug
            if project_path.exists():
                shutil.rmtree(project_path)
            console.print(f"  [green]✓  '{profile.name}' eliminado del registro.[/green]")
        return None

    new_dir = _prompt_project_dir()
    if not new_dir:
        return None

    profile.project_dir = new_dir
    profile.last_used   = datetime.utcnow()
    registry.save(profile)

    console.print(f"  [green]✓  Ruta actualizada y guardada.[/green]")
    console.print(f"  [green]✓  Proyecto activo: {profile.name}  →  {profile.project_dir}[/green]\n")
    return profile


def _register_new() -> ProjectProfile | None:
    console.print()

    name = Prompt.ask("  Nombre del proyecto").strip()
    if not name:
        return None

    slug = slugify(name)

    if registry.exists(slug):
        slug = f"{slug}-{datetime.utcnow().strftime('%H%M%S')}"

    console.print(f"  [dim]Slug: {slug}[/dim]")

    console.print()
    project_dir = _prompt_project_dir()
    if not project_dir:
        return None

    _show_dir_preview(project_dir)

    console.print(f"\n  ¿Confirmar registro?")
    console.print(f"  Nombre: [cyan]{name}[/cyan]")
    console.print(f"  Slug:   [dim]{slug}[/dim]")
    console.print(f"  Ruta:   [cyan]{project_dir}[/cyan]\n")

    if not Confirm.ask("  Confirmar", default=True):
        return None

    profile = ProjectProfile(
        name=name,
        slug=slug,
        project_dir=project_dir,
    )
    registry.save(profile)

    console.print(f"\n  [green]✓  Proyecto registrado.[/green]")
    console.print(f"  [green]✓  Proyecto activo: {name}  →  {project_dir}[/green]\n")
    return profile


def _prompt_project_dir() -> str | None:
    console.print(
        "  Ruta de la carpeta raíz del proyecto:\n"
        "  [dim](Ej: L:\\QUETZ-AI\\ o /home/carlos/quetz-ai)[/dim]"
    )

    for attempt in range(3):
        raw = Prompt.ask("  >").strip()

        if not raw or raw.lower() in ("b", "back", "cancelar"):
            return None

        resolved = str(Path(raw).expanduser().resolve())

        valid, error = ProjectRegistry().validate_dir(resolved)
        if valid:
            console.print(f"  [dim]Verificando carpeta...[/dim]")
            console.print(f"  [green]✓  Carpeta encontrada y accesible.[/green]")
            return resolved

        console.print(f"  [red]✗  {error}[/red]")
        remaining = 2 - attempt
        if remaining > 0:
            console.print(f"  [dim]{remaining} intento(s) restante(s)[/dim]\n")

    console.print("  [red]Demasiados intentos fallidos. Volviendo al menú.[/red]")
    return None


def _show_dir_preview(path: str):
    p = Path(path)
    items = sorted(p.iterdir())[:8]

    if not items:
        console.print("  [dim](carpeta vacía)[/dim]")
        return

    console.print(f"\n  Contenido detectado en {path}:")
    parts = []
    for item in items:
        icon = "📁" if item.is_dir() else "📄"
        parts.append(f"{icon} {item.name}")
    console.print("  " + "   ".join(parts))

    all_items = list(p.iterdir())
    if len(all_items) > 8:
        console.print(f"  [dim]... y {len(all_items) - 8} elementos más[/dim]")


def _relative_time(dt: datetime) -> str:
    now = datetime.utcnow()
    ref = dt.replace(tzinfo=None) if dt.tzinfo else dt
    diff = now - ref
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "hace un momento"
    if seconds < 3600:
        m = seconds // 60
        return f"hace {m} min"
    if seconds < 86400:
        h = seconds // 3600
        return f"hace {h}h"
    if seconds < 604800:
        d = seconds // 86400
        return f"hace {d} día{'s' if d > 1 else ''}"
    w = seconds // 604800
    return f"hace {w} semana{'s' if w > 1 else ''}"
