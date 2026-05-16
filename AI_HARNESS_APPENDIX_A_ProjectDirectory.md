# Apéndice A — Gestión de Directorio de Proyecto

**Documento:** AI Dev Harness Design v1.0  
**Sección:** Apéndice A  
**Fecha:** 2026-05-16

---

## Contexto del problema

Cuando el harness invoca a Gemini CLI, Claude Code o OpenCode como subprocesos de Python, esos procesos heredan el directorio de trabajo (`cwd`) del proceso padre. Si el harness se lanza desde cualquier carpeta del sistema, los agentes buscarán y editarán archivos ahí — no en el proyecto correcto.

La solución es registrar la ruta absoluta de cada proyecto en un perfil persistente y pasarla como `cwd` a cada subprocess de provider. Así el agente opera siempre dentro de la carpeta correcta, sin importar desde dónde se haya lanzado el harness.

---

## Schema: ProjectProfile

**Archivo:** `harness/protocols.py` (agregar a los schemas existentes)

```python
class ProjectProfile(BaseModel):
    """
    Perfil persistente de un proyecto registrado en el harness.
    Se guarda en ~/.ai-harness/projects/{slug}/profile.json
    """
    name:        str
    slug:        str        # versión slugificada del nombre para uso en paths
    project_dir: str        # ruta absoluta a la carpeta raíz del proyecto
                            # ej: "L:\\QUETZ-AI\\" en Windows
                            # ej: "/home/carlos/quetz-ai" en Linux/Mac
    created_at:  datetime = Field(default_factory=datetime.utcnow)
    last_used:   datetime = Field(default_factory=datetime.utcnow)
```

**Ubicación en disco:**

```
~/.ai-harness/
└── projects/
    ├── quetz-ai/
    │   ├── profile.json          ← ProjectProfile serializado
    │   ├── project_context.json  ← contexto del proyecto (stack, restricciones)
    │   └── {task-slug}/
    │       └── runs/
    │           └── ...
    ├── business-app/
    │   ├── profile.json
    │   └── ...
    └── otro-proyecto/
        └── ...
```

---

## ProjectRegistry — Gestión de perfiles

**Archivo:** `session/registry.py` (archivo nuevo)

```python
from pathlib import Path
from harness.protocols import ProjectProfile
from datetime import datetime
import json

PROJECTS_ROOT = Path.home() / ".ai-harness" / "projects"


class ProjectRegistry:
    """
    Gestiona el registro de proyectos conocidos por el harness.
    Cada proyecto tiene un perfil con su nombre y ruta de directorio.
    """

    def list_projects(self) -> list[ProjectProfile]:
        """
        Retorna todos los proyectos registrados, ordenados por last_used
        (el más reciente primero).
        """
        profiles = []
        if not PROJECTS_ROOT.exists():
            return profiles

        for project_dir in PROJECTS_ROOT.iterdir():
            profile_file = project_dir / "profile.json"
            if profile_file.exists():
                try:
                    profile = ProjectProfile(**json.loads(profile_file.read_text()))
                    profiles.append(profile)
                except Exception:
                    continue

        return sorted(profiles, key=lambda p: p.last_used, reverse=True)

    def get(self, slug: str) -> ProjectProfile | None:
        """Carga el perfil de un proyecto por su slug."""
        profile_file = PROJECTS_ROOT / slug / "profile.json"
        if not profile_file.exists():
            return None
        try:
            return ProjectProfile(**json.loads(profile_file.read_text()))
        except Exception:
            return None

    def save(self, profile: ProjectProfile) -> None:
        """Guarda o actualiza el perfil de un proyecto."""
        project_dir = PROJECTS_ROOT / profile.slug
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "profile.json").write_text(
            profile.model_dump_json(indent=2), encoding="utf-8"
        )

    def touch(self, slug: str) -> None:
        """Actualiza last_used del proyecto al momento actual."""
        profile = self.get(slug)
        if profile:
            profile.last_used = datetime.utcnow()
            self.save(profile)

    def exists(self, slug: str) -> bool:
        return (PROJECTS_ROOT / slug / "profile.json").exists()

    def validate_dir(self, path: str) -> tuple[bool, str]:
        """
        Valida que la ruta proporcionada existe y es un directorio.
        Retorna (es_válida, mensaje_de_error).
        """
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return False, f"La ruta no existe: {p}"
        if not p.is_dir():
            return False, f"La ruta no es un directorio: {p}"
        return True, ""
```

---

## Menú de Selección de Proyecto — Flujo Completo

Este menú se muestra al usuario al inicio de un nuevo task o al cambiar de proyecto desde el menú principal. Es el punto donde se asocia la carpeta del proyecto con la sesión activa.

### Pantalla 1 — ¿Proyecto nuevo o existente?

```
── Selección de Proyecto ──────────────────────────────────────

  ¿Qué quieres hacer?

  [1] Usar un proyecto ya registrado
  [2] Registrar un proyecto nuevo
  [B] Volver al menú principal

  > _
```

---

### Pantalla 2A — Proyecto ya registrado

Se muestra cuando el usuario elige `[1]`. Lista todos los proyectos conocidos con su nombre, ruta y última actividad.

```
── Proyectos Registrados ──────────────────────────────────────

  #   Nombre            Carpeta                    Último uso
  ──────────────────────────────────────────────────────────────
  1   quetz-ai          L:\QUETZ-AI\               hace 2 días
  2   business-app      L:\BUSINESS-APP\           hace 1 semana
  3   portfolio-web     C:\dev\portfolio\          hace 3 semanas

  [1-3] Seleccionar proyecto
  [B]   Volver

  > 1

  ⏳ Verificando carpeta L:\QUETZ-AI\...
  ✓  Carpeta encontrada y accesible.
  ✓  Proyecto activo: quetz-ai  →  L:\QUETZ-AI\
```

**Si la carpeta ya no existe** (fue movida o eliminada):

```
  ⏳ Verificando carpeta L:\QUETZ-AI\...
  ✗  La carpeta no existe o no es accesible: L:\QUETZ-AI\

  ¿Qué quieres hacer?
  [1] Actualizar la ruta del proyecto
  [2] Eliminar este proyecto del registro
  [B] Volver

  > 1

  Nueva ruta para 'quetz-ai':
  > L:\proyectos\QUETZ-AI\

  ⏳ Verificando nueva carpeta...
  ✓  Carpeta encontrada.
  ✓  Ruta actualizada y guardada.
  ✓  Proyecto activo: quetz-ai  →  L:\proyectos\QUETZ-AI\
```

---

### Pantalla 2B — Proyecto nuevo

Se muestra cuando el usuario elige `[2]`. Pide nombre y ruta. El nombre puede ser cualquier texto — el slug se genera automáticamente.

```
── Registrar Proyecto Nuevo ───────────────────────────────────

  Nombre del proyecto:
  > QUETZ-AI Client App

  Slug generado: quetz-ai-client-app
  ¿Usar este slug? [S/n]: S

  Ruta de la carpeta raíz del proyecto:
  (Pega la ruta completa. Ej: L:\QUETZ-AI\ o /home/carlos/quetz-ai)
  > L:\QUETZ-AI\

  ⏳ Verificando carpeta...
  ✓  Carpeta encontrada y accesible.

  Contenido detectado en L:\QUETZ-AI\:
    📁 lib/          📁 test/         📁 android/
    📄 pubspec.yaml  📄 README.md

  ¿Confirmar registro?
  Nombre: QUETZ-AI Client App
  Slug:   quetz-ai-client-app
  Ruta:   L:\QUETZ-AI\
  [S/n]: S

  ✓  Proyecto registrado.
  ✓  Proyecto activo: quetz-ai-client-app  →  L:\QUETZ-AI\
```

**Validaciones durante el ingreso de ruta:**

```
  Ruta de la carpeta raíz del proyecto:
  > L:\carpeta-que-no-existe\

  ✗  La ruta no existe: L:\carpeta-que-no-existe\
     Verifica que la carpeta exista y vuelve a intentarlo.

  Ruta de la carpeta raíz del proyecto:
  > L:\QUETZ-AI\pubspec.yaml

  ✗  La ruta apunta a un archivo, no a una carpeta.
     Ingresa la carpeta raíz del proyecto, no un archivo dentro de él.

  Ruta de la carpeta raíz del proyecto:
  > L:\QUETZ-AI\

  ✓  Carpeta encontrada y accesible.
```

---

### Pantalla 3 — Confirmación del proyecto activo antes de continuar

Después de seleccionar o registrar el proyecto, el harness siempre muestra una confirmación antes de continuar con la ingesta del task.

```
── Proyecto Activo ────────────────────────────────────────────

  ✓  quetz-ai-client-app
     L:\QUETZ-AI\

  Continuando con ingesta del task desde Notion...
```

---

## Implementación: ProjectMenu

**Archivo:** `console/menus/project_menu.py`

```python
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from pathlib import Path
from session.registry import ProjectRegistry
from harness.protocols import ProjectProfile
from session.manager import slugify
from datetime import datetime, timezone

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
            raise KeyboardInterrupt   # señal para volver al menú principal

        if choice == "1":
            profile = _select_existing()
            if profile:
                return profile
            # Si retorna None, vuelve al inicio del while (re-muestra el menú)

        elif choice == "2":
            profile = _register_new()
            if profile:
                return profile


def _select_existing() -> ProjectProfile | None:
    """
    Lista proyectos registrados y permite seleccionar uno.
    Verifica que la carpeta exista. Si no existe, ofrece actualizar la ruta.
    Retorna None si el usuario quiere volver.
    """
    projects = registry.list_projects()

    if not projects:
        console.print("\n  [yellow]No hay proyectos registrados todavía.[/yellow]")
        console.print("  Usa la opción [2] para registrar tu primer proyecto.\n")
        Prompt.ask("  [Enter para volver]", default="")
        return None

    # Mostrar tabla de proyectos
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

    # Verificar que la carpeta siga existiendo
    console.print(f"\n  [dim]Verificando carpeta {profile.project_dir}...[/dim]")
    valid, error = registry.validate_dir(profile.project_dir)

    if not valid:
        console.print(f"  [red]✗  {error}[/red]")
        return _handle_missing_dir(profile)

    console.print(f"  [green]✓  Carpeta encontrada y accesible.[/green]")
    console.print(f"  [green]✓  Proyecto activo: {profile.name}  →  {profile.project_dir}[/green]\n")

    # Actualizar last_used
    registry.touch(profile.slug)
    return profile


def _handle_missing_dir(profile: ProjectProfile) -> ProjectProfile | None:
    """
    Maneja el caso donde la carpeta del proyecto ya no existe.
    Ofrece actualizar la ruta o eliminar el proyecto del registro.
    """
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
            from session.registry import PROJECTS_ROOT
            project_path = PROJECTS_ROOT / profile.slug
            if project_path.exists():
                shutil.rmtree(project_path)
            console.print(f"  [green]✓  '{profile.name}' eliminado del registro.[/green]")
        return None

    # Opción 1: actualizar ruta
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
    """
    Registra un proyecto nuevo preguntando nombre y ruta.
    Retorna None si el usuario cancela.
    """
    console.print()

    # Nombre
    name = Prompt.ask("  Nombre del proyecto").strip()
    if not name:
        return None

    slug = slugify(name)

    # Verificar si el slug ya existe
    if registry.exists(slug):
        console.print(f"\n  [yellow]Ya existe un proyecto con slug '{slug}'.[/yellow]")
        existing = registry.get(slug)
        console.print(f"  Proyecto existente: {existing.name}  →  {existing.project_dir}")
        if not Confirm.ask("  ¿Registrar igualmente con un slug diferente?", default=False):
            return None
        # Agregar timestamp para hacerlo único
        slug = f"{slug}-{datetime.utcnow().strftime('%H%M%S')}"

    console.print(f"  [dim]Slug: {slug}[/dim]")

    # Ruta del proyecto
    console.print()
    project_dir = _prompt_project_dir()
    if not project_dir:
        return None

    # Mostrar contenido detectado para confirmar
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
    """
    Pregunta la ruta del directorio con validación en loop.
    Retorna la ruta normalizada como string, o None si el usuario cancela.
    Permite hasta 3 intentos fallidos antes de cancelar automáticamente.
    """
    console.print(
        "  Ruta de la carpeta raíz del proyecto:\n"
        "  [dim](Ej: L:\\QUETZ-AI\\ o /home/carlos/quetz-ai)[/dim]"
    )

    for attempt in range(3):
        raw = Prompt.ask("  >").strip()

        if not raw or raw.lower() in ("b", "back", "cancelar"):
            return None

        # Expandir ~ y resolver ruta absoluta
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
    """
    Muestra los primeros N elementos del directorio para que el usuario
    confirme visualmente que es la carpeta correcta.
    """
    p = Path(path)
    items = sorted(p.iterdir())[:8]   # máximo 8 items

    if not items:
        console.print("  [dim](carpeta vacía)[/dim]")
        return

    console.print(f"\n  Contenido detectado en {path}:")
    parts = []
    for item in items:
        icon = "📁" if item.is_dir() else "📄"
        parts.append(f"{icon} {item.name}")
    console.print("  " + "   ".join(parts))

    if len(list(p.iterdir())) > 8:
        total = len(list(p.iterdir()))
        console.print(f"  [dim]... y {total - 8} elementos más[/dim]")


def _relative_time(dt: datetime) -> str:
    """Convierte datetime a string legible: 'hace 2 días', 'hace 1 semana', etc."""
    # Asegurar timezone-aware
    now = datetime.utcnow()
    if dt.tzinfo is not None:
        from datetime import timezone
        now = datetime.now(timezone.utc)

    diff = now - dt
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
```

---

## Cómo se propaga `project_dir` por el sistema

Una vez que el usuario selecciona el proyecto, la ruta viaja hasta cada subprocess de provider a través del parámetro `cwd`.

```
ProjectProfile.project_dir  ("L:\\QUETZ-AI\\")
        │
        ▼
main.py — build_providers(project_dir)
        │
        ├── ClaudeCodeProvider(project_dir=...)
        ├── GeminiProvider(project_dir=...)
        └── OpenCodeProvider(project_dir=...)
                │
                ▼
        subprocess.run(..., cwd=project_dir)
                │
                ▼
        El agente opera en L:\QUETZ-AI\
        lee lib/main.dart como L:\QUETZ-AI\lib\main.dart
        crea archivos en la carpeta correcta
        ejecuta comandos relativos al proyecto
```

---

## Cambios en providers para soportar `project_dir`

### providers/claude_code.py

```python
class ClaudeCodeProvider(ProviderBase):

    def __init__(self, model: str, project_dir: str, priority: int = 1, timeout: int = 240):
        self.model       = model
        self.project_dir = project_dir   # ← nuevo
        self.priority    = priority
        self.timeout     = timeout
        model_short = "sonnet" if "sonnet" in model else "opus"
        self.name   = f"claude_{model_short}"

    def _run(self, prompt: str) -> str:
        result = subprocess.run(
            ["claude", "--print", "--model", self.model,
             "--allowedTools", "Read,Edit,Bash",
             "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.project_dir,        # ← Claude opera en la carpeta del proyecto
        )
        # ... resto igual
```

### providers/gemini.py

```python
class GeminiProvider(ProviderBase):

    def __init__(self, model: str = "gemini-2.0-flash", project_dir: str = ".", timeout: int = 120):
        self.model       = model
        self.project_dir = project_dir   # ← nuevo
        self.timeout     = timeout

    def _run(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(...) as f:
            f.write(prompt)
            tmp = f.name
        try:
            result = subprocess.run(
                ["gemini", "--model", self.model, f"@{tmp}"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.project_dir,    # ← Gemini opera en la carpeta del proyecto
            )
            # ... resto igual
```

### providers/opencode.py

```python
class OpenCodeProvider(ProviderBase):

    def __init__(self, model: str, project_dir: str, timeout: int = 150):
        self.model       = model
        self.project_dir = project_dir   # ← nuevo
        self.timeout     = timeout
        self.name, self.priority = FREE_MODELS.get(model, ("opencode_unknown", 10))

    def _run_inline(self, prompt: str) -> str:
        result = subprocess.run(
            ["opencode", "run", "--model", self.model,
             "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.project_dir,        # ← OpenCode opera en la carpeta del proyecto
        )
        return self._check(result)

    def _run_via_file(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(...) as f:
            f.write(prompt)
            tmp = f.name
        try:
            result = subprocess.run(
                ["opencode", "run", "--model", self.model,
                 "--dangerously-skip-permissions",
                 "--file", tmp,
                 "Ejecuta las instrucciones del archivo adjunto."],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.project_dir,    # ← mismo cwd
            )
            return self._check(result)
        finally:
            os.unlink(tmp)
```

---

## Cambios en `main.py` — build_providers recibe project_dir

```python
# main.py

def build_providers(project_dir: str) -> list[ProviderBase]:
    """
    Construye la lista de providers configurados para operar
    en la carpeta del proyecto activo.
    """
    import shutil

    providers = []

    # Planner — Claude Sonnet (default)
    if shutil.which("claude"):
        providers.append(ClaudeCodeProvider(
            model="claude-sonnet-4-6",
            project_dir=project_dir,
            priority=1,
        ))
        # Planner — Claude Opus (extra_high, prioridad 99)
        providers.append(ClaudeCodeProvider(
            model="claude-opus-4-6",
            project_dir=project_dir,
            priority=99,
        ))

    # Executor default — Gemini Flash
    if shutil.which("gemini"):
        providers.append(GeminiProvider(
            model="gemini-2.0-flash",
            project_dir=project_dir,
        ))

    # Executors fallback — OpenCode free models
    if shutil.which("opencode"):
        for model, (name, priority) in FREE_MODELS.items():
            providers.append(OpenCodeProvider(
                model=model,
                project_dir=project_dir,
            ))

    if not providers:
        raise RuntimeError(
            "No hay ningún provider disponible.\n"
            "Verifica que claude y/o gemini CLI estén instalados."
        )

    return providers


def build_orchestrator(profile: ProjectProfile, session: SessionManager) -> Orchestrator:
    """
    Construye el orchestrator completo para el proyecto activo.
    Se llama cada vez que el usuario cambia de proyecto.
    """
    config    = load_config()
    budget    = BudgetManager()
    providers = build_providers(profile.project_dir)
    router    = build_router_from_config(providers, budget)
    return Orchestrator(router, budget, session)
```

---

## Cambios en `main_menu.py` — Cambio de proyecto reconstruye providers

```python
# console/menus/main_menu.py

class MainMenu:
    def __init__(self):
        self.registry        = ProjectRegistry()
        self.active_profile: ProjectProfile | None = None
        self.orchestrator:   Orchestrator   | None = None

    def run(self):
        while True:
            self._show()
            choice = Prompt.ask("  >", choices=["1","2","3","4","5","q","Q"])

            if choice == "1":
                self._new_task()

            elif choice == "2":
                self._resume_task()

            elif choice == "3":
                self._view_history()

            elif choice == "4":
                self._show_budget()

            elif choice == "5":
                self._change_project()     # ← reconstruye orchestrator con nuevo project_dir

            elif choice.lower() == "q":
                break

    def _change_project(self):
        """
        Permite cambiar el proyecto activo.
        Reconstruye los providers con el nuevo project_dir.
        """
        try:
            profile = select_or_register_project()
        except KeyboardInterrupt:
            return

        self.active_profile = profile
        self.registry.touch(profile.slug)

        # Reconstruir orchestrator con el nuevo project_dir
        # Los providers ahora apuntan a la nueva carpeta
        session = SessionManager(profile.name, "")   # placeholder hasta que haya task
        self.orchestrator = build_orchestrator(profile, session)

        console.print(f"\n  [green]✓  Proyecto activo: {profile.name}[/green]")
        console.print(f"  [dim]  {profile.project_dir}[/dim]\n")

    def _ensure_project_selected(self) -> bool:
        """
        Verifica que haya un proyecto activo antes de ejecutar una acción.
        Si no hay ninguno, lanza el menú de selección.
        """
        if self.active_profile:
            return True

        console.print("\n  [yellow]No hay proyecto activo.[/yellow]")
        console.print("  Selecciona o registra un proyecto para continuar.\n")

        try:
            profile = select_or_register_project()
            self.active_profile = profile
            self.registry.touch(profile.slug)
            session = SessionManager(profile.name, "")
            self.orchestrator = build_orchestrator(profile, session)
            return True
        except KeyboardInterrupt:
            return False
```

---

## Beneficio de rutas relativas en los planes

Al operar con `cwd` en la carpeta del proyecto, el planner y el executor pueden usar rutas relativas en todo momento. Esto hace los planes más portables y legibles.

**Sin `cwd` configurado:**

```json
{
  "target_files": ["L:\\QUETZ-AI\\lib\\features\\auth\\presentation\\login_page.dart"]
}
```

**Con `cwd` configurado en `L:\QUETZ-AI\`:**

```json
{
  "target_files": ["lib/features/auth/presentation/login_page.dart"]
}
```

El prompt del executor incluye siempre la ruta del proyecto para que el agente entienda el contexto completo si lo necesita:

```python
# En Orchestrator._build_summary()

def _build_summary(self, plan: TaskPlan, project_dir: str) -> str:
    return (
        f"Proyecto en: {project_dir}\n"
        f"Objetivo: {plan.summary}\n"
        f"Tipo: {plan.task_type.value}\n"
        "Steps:\n" +
        "\n".join(f"  {s.index}. {s.description}" for s in plan.steps)
    )
```

---

## Resumen de cambios respecto al diseño base

| Componente | Cambio |
|-----------|--------|
| `harness/protocols.py` | Agregar `ProjectProfile` schema |
| `session/registry.py` | Archivo nuevo — `ProjectRegistry` |
| `console/menus/project_menu.py` | Archivo nuevo — menú completo con flujo nuevo/existente |
| `console/menus/main_menu.py` | `_change_project()` reconstruye providers |
| `providers/claude_code.py` | `project_dir` en constructor y `cwd` en subprocess |
| `providers/gemini.py` | `project_dir` en constructor y `cwd` en subprocess |
| `providers/opencode.py` | `project_dir` en constructor y `cwd` en subprocess |
| `main.py` | `build_providers(project_dir)` recibe la ruta |
| `config/providers.yaml` | Sin cambios |
| `harness/protocols.py` demás schemas | Sin cambios |
