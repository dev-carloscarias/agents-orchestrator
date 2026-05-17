# Plan de Implementación — AI Dev Harness v1.0

**Proyecto:** `ai-harness`
**Versión:** 1.0
**Fecha:** 2026-05-16
**Referencias de diseño:**
- [AI_HARNESS_DESIGN_v1.0.md](AI_HARNESS_DESIGN_v1.0.md)
- [AI_HARNESS_APPENDIX_A_ProjectDirectory.md](AI_HARNESS_APPENDIX_A_ProjectDirectory.md)

---

## Cómo usar este documento

Este plan está organizado en **9 módulos independientes** pensados para ejecutarse en sesiones separadas de agentes. Cada módulo:

1. Declara explícitamente **qué módulos previos deben estar completos** (`Requiere`).
2. Lista todos los **archivos a crear** con su ruta exacta.
3. Da instrucciones detalladas — qué clases/funciones implementar, qué firmas tener, qué validar.
4. Incluye **criterios de aceptación** verificables al final.

> **Regla de oro para el agente ejecutor:**
> El código de referencia en los archivos de diseño es la fuente de verdad. Cópialo literalmente cuando lo encuentres ahí. Solo desvía si el diseño es ambiguo o contradice este plan, y en ese caso documenta la decisión.

**Orden recomendado:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Los módulos 3, 4 y 5 pueden ejecutarse en paralelo después del 2.

---

## Tabla de Módulos

| # | Módulo | Requiere | Carpetas/Archivos clave |
|---|--------|----------|-------------------------|
| 1 | Foundation: scaffolding y schemas | — | `pyproject.toml`, `harness/protocols.py`, `.env.example` |
| 2 | Configuración estática (YAML + prompts) | 1 | `config/` |
| 3 | Session & Project Registry | 1 | `session/` |
| 4 | Pipeline core (classifier, normalizer, context, diff) | 1 | `pipeline/` |
| 5 | Ingestor de Notion | 1 | `ingestors/` |
| 6 | Providers (Claude, Gemini, OpenCode) | 1, 2 | `providers/` |
| 7 | Harness core (Budget, Router, Orchestrator) | 1, 2, 3, 6 | `harness/budget.py`, `harness/router.py`, `harness/orchestrator.py` |
| 8 | Consola TUI (menús Rich) | 3, 7 | `console/` |
| 9 | Entry point y wiring | 1–8 | `main.py` |

---

## Módulo 1 — Foundation: scaffolding y schemas

**Objetivo:** dejar listo el esqueleto del proyecto y todos los modelos Pydantic compartidos.

**Requiere:** nada.

### Archivos a crear

```
ai-harness/
├── pyproject.toml
├── .env.example
├── .gitignore
├── harness/
│   ├── __init__.py
│   └── protocols.py
├── console/
│   └── __init__.py
├── console/menus/
│   └── __init__.py
├── ingestors/
│   └── __init__.py
├── pipeline/
│   └── __init__.py
├── providers/
│   └── __init__.py
└── session/
    └── __init__.py
```

### Instrucciones

1. **`pyproject.toml`** — copiar literalmente de [AI_HARNESS_DESIGN_v1.0.md §18](AI_HARNESS_DESIGN_v1.0.md). Requiere Python ≥ 3.12. Dependencias: `pydantic>=2.7`, `rich>=13`, `pyyaml>=6`, `python-dotenv>=1.0`, `httpx>=0.27`, `tiktoken>=0.7`. Entry-point `harness = "main:main"`.

2. **`.env.example`** — copiar literalmente de [AI_HARNESS_DESIGN_v1.0.md §18](AI_HARNESS_DESIGN_v1.0.md). Documenta `NOTION_TOKEN` y `GOOGLE_API_KEY` como requeridos; el resto comentado.

3. **`.gitignore`** — debe ignorar como mínimo: `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, y `~/.ai-harness/` no aplica (vive en `$HOME`).

4. **`harness/protocols.py`** — implementar exactamente los schemas Pydantic definidos en [AI_HARNESS_DESIGN_v1.0.md §5](AI_HARNESS_DESIGN_v1.0.md):
    - Enums: `Complexity`, `TaskType`, `StepStatus`, `TaskStatus`.
    - Modelos: `TaskMeta`, `ProjectContext`, `Step`, `TaskPlan`, `FileChange`, `StepResult`, `TaskResult`, `RunProgress`.
    - **Adicional (Appendix A):** modelo `ProjectProfile` con campos `name: str`, `slug: str`, `project_dir: str`, `created_at: datetime`, `last_used: datetime` (factories `datetime.utcnow`).

5. **`__init__.py`** vacíos en cada paquete declarado arriba.

### Criterios de aceptación

- `pip install -e .` instala sin errores en una venv 3.12.
- `python -c "from harness.protocols import TaskPlan, ProjectProfile, RunProgress; print('ok')"` imprime `ok`.
- `Complexity("extra_high")` y `TaskType("backend")` funcionan.

---

## Módulo 2 — Configuración estática (YAML + prompts)

**Objetivo:** materializar todos los archivos de configuración no-Python que el sistema lee al arrancar.

**Requiere:** Módulo 1.

### Archivos a crear

```
config/
├── providers.yaml
├── routing_rules.yaml
├── budget_alerts.yaml
└── prompts/
    ├── converter.md
    ├── planner_backend.md
    ├── planner_frontend.md
    ├── planner_refactor.md
    ├── planner_bugfix.md
    ├── planner_generic.md
    ├── executor_backend.md
    ├── executor_frontend.md
    ├── executor_refactor.md
    ├── executor_bugfix.md
    └── executor_generic.md
```

### Instrucciones

1. **`config/providers.yaml`** — copia literal de [AI_HARNESS_DESIGN_v1.0.md §18](AI_HARNESS_DESIGN_v1.0.md). Cinco entradas: `claude_sonnet`, `claude_opus`, `gemini_flash`, `opencode_minimax`, `opencode_bigpickle`.

2. **`config/routing_rules.yaml`** — copia literal del diseño §18. Estructura:
    ```yaml
    routing:
      planner:
        low|medium|high: [claude_sonnet]
        extra_high: [claude_opus, claude_sonnet]
      executor:
        low|medium|high|extra_high: [gemini_flash, opencode_minimax, opencode_bigpickle]
    ```

3. **`config/budget_alerts.yaml`** — copia literal del diseño §18 con `thresholds.default` y `per_provider` para los cinco providers.

4. **`config/prompts/converter.md`** — copia literal de [AI_HARNESS_DESIGN_v1.0.md §17](AI_HARNESS_DESIGN_v1.0.md). Es el system prompt que usa el `Normalizer` (Gemini Flash) para convertir texto Notion a `task.md` estándar.

5. **Prompts de planner** (`planner_backend.md`, `planner_frontend.md`, `planner_refactor.md`, `planner_bugfix.md`, `planner_generic.md`):
    - `backend`, `frontend`, `refactor`, `bugfix` — copia literal de §17. El JSON schema final es el mismo que `planner_backend.md`; los otros añaden su sección de especialización y luego referencian el mismo schema (deben incluir el schema explícito completo, no la frase "[mismo JSON schema que…]").
    - `planner_generic.md` — usa el JSON schema de `planner_backend.md` sin sección de especialización; el rol es "ingeniero senior generando un plan de implementación".

6. **Prompts de executor** (`executor_backend.md`, `executor_frontend.md`, `executor_refactor.md`, `executor_bugfix.md`, `executor_generic.md`):
    - `executor_generic.md` — copia literal de §17.
    - Los otros cuatro: idéntico contenido a `executor_generic.md` más una sección de **especialización** al inicio:
        - `backend`: "Manten transacciones explícitas. Valida inputs y outputs. Respeta capa controller/service/repository si aplica."
        - `frontend`: "Cuida los estados loading/error/empty/success en cada componente. Respeta el design system del proyecto."
        - `refactor`: "El comportamiento externo NO debe cambiar. Si necesitas tocar tests, hazlo con cuidado mínimo."
        - `bugfix`: "Aplica la corrección MÍNIMA. No refactorices más de lo necesario. Verifica que el bug ya no se reproduce."

### Criterios de aceptación

- `yaml.safe_load` lee los 3 yaml sin error.
- Todos los archivos `.md` de prompts existen y no están vacíos.
- `planner_*.md` contienen un bloque ```json``` con la estructura completa.

---

## Módulo 3 — Session & Project Registry

**Objetivo:** persistencia en disco bajo `~/.ai-harness/projects/{slug}/...` (tasks, runs, contexto, perfiles de proyecto).

**Requiere:** Módulo 1.

### Archivos a crear

```
session/
├── manager.py
└── registry.py
```

### Instrucciones

1. **`session/manager.py`** — implementar `SessionManager` exactamente como en [AI_HARNESS_DESIGN_v1.0.md §12](AI_HARNESS_DESIGN_v1.0.md):
    - Función auxiliar `slugify(text: str) -> str` (lowercase, `[^\w\s-]` removido, espacios→guiones, máx 60 chars). **Esta función la importan otros módulos (especialmente Module 4 y Module 8) — debe vivir aquí.**
    - Constante `SESSIONS_ROOT = Path.home() / ".ai-harness" / "projects"`.
    - Clase `SessionManager(project_name, task_name)` con todos los métodos del diseño:
        - propiedades: `task_file`, `ctx_json`, `ctx_md`.
        - estado: `task_exists()`, `list_runs()`, `has_incomplete_run()`, `summary()`.
        - task/contexto: `save_task`, `load_task`, `save_project_context`, `load_project_context`.
        - runs: `start_new_run(plan)`, `resume_latest_run()`, `pending_steps(plan, progress)`, `mark_step_*`, `save_step_artifacts`, `mark_run_*`, `clear_history`.
        - privados: `_update_step`, `_update_run_status`, `_save_progress`.
    - Función auxiliar `_context_to_md(ctx: ProjectContext) -> str` para volcado humano-legible.

2. **`session/registry.py`** — implementar `ProjectRegistry` exactamente como en [AI_HARNESS_APPENDIX_A_ProjectDirectory.md](AI_HARNESS_APPENDIX_A_ProjectDirectory.md):
    - Constante `PROJECTS_ROOT = Path.home() / ".ai-harness" / "projects"` (mismo path que SESSIONS_ROOT; los profiles viven al lado de los tasks dentro de cada slug).
    - Métodos: `list_projects()`, `get(slug)`, `save(profile)`, `touch(slug)`, `exists(slug)`, `validate_dir(path)`.
    - `validate_dir` debe expandir `~` y resolver path absoluto antes de validar.

### Criterios de aceptación

- `SessionManager("proj","task").task_dir == Path.home()/".ai-harness/projects/proj/task"`.
- Llamar `start_new_run(plan)` crea `runs/run_YYYYMMDD_HHMMSS/{plan.json, progress.json, steps/}`.
- `ProjectRegistry().save(ProjectProfile(name="X", slug="x", project_dir="/tmp"))` crea `~/.ai-harness/projects/x/profile.json`.
- `list_projects()` ordena por `last_used` descendente.

---

## Módulo 4 — Pipeline core (classifier, normalizer, context_collector, diff_reporter)

**Objetivo:** lógica de negocio pura entre la ingesta y el planning/ejecución.

**Requiere:** Módulo 1.

### Archivos a crear

```
pipeline/
├── classifier.py
├── normalizer.py
├── context_collector.py
└── diff_reporter.py
```

### Instrucciones

1. **`pipeline/classifier.py`** — implementar `classify_task(task_md: str) -> TaskMeta` literalmente como en [AI_HARNESS_DESIGN_v1.0.md §8](AI_HARNESS_DESIGN_v1.0.md):
    - Listas `BACKEND_SIGNALS`, `FRONTEND_SIGNALS`, `REFACTOR_SIGNALS`, `BUGFIX_SIGNALS`, `HIGH_SIGNALS`, `LOW_SIGNALS`, `STACK_HINTS`.
    - `_count`, `_read_field` privadas.
    - **Invariante:** `extra_high` NUNCA es devuelto por esta función. Solo lo asigna el menú de complexity (Module 8).
    - Lógica de fallback: si no hay campo explícito y empate en señales → `TaskType.generic` / `Complexity.medium`.
    - `needs_context_collection = complexity != Complexity.low`.

2. **`pipeline/normalizer.py`** — implementar `Normalizer` literalmente como en [AI_HARNESS_DESIGN_v1.0.md §7](AI_HARNESS_DESIGN_v1.0.md):
    - Constructor `__init__(api_key, model="gemini-2.0-flash")` lee `config/prompts/converter.md` (depende de Module 2).
    - `convert(raw_text, page_id, page_url, page_title) -> str` llama a Google Gemini REST API (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`) con timeout 60s, `temperature=0.1`, `maxOutputTokens=2048`.
    - Retorna el texto del primer candidate part.

3. **`pipeline/context_collector.py`** — implementar `collect_project_context(project_name, task_meta, existing_context) -> ProjectContext` como en [AI_HARNESS_DESIGN_v1.0.md §9](AI_HARNESS_DESIGN_v1.0.md):
    - Si hay `existing_context`, muestra y pregunta con `Confirm.ask("¿Reutilizar este contexto?", default=True)`.
    - Si no, hace 4 preguntas con `Prompt.ask`: stack, archivos clave, restricciones, convenciones.
    - Stack/archivos se splitean por coma; restricciones/convenciones por punto, ignorando entradas igual a `"ninguna"`.
    - `_display_context(ctx)` helper para mostrar el contexto guardado.

4. **`pipeline/diff_reporter.py`** — implementar tres funciones públicas como en [AI_HARNESS_DESIGN_v1.0.md §13](AI_HARNESS_DESIGN_v1.0.md):
    - `capture_snapshot(file_paths) -> dict[str, str]`: lee contenido actual con `errors="replace"`; ignora rutas inexistentes.
    - `compute_diff(before, after) -> str | None`: usa `difflib.unified_diff` con etiquetas `a/{path}` y `b/{path}`; `None` si no hubo cambios.
    - `detect_file_changes(before, after) -> list[FileChange]`: marca `created`/`deleted`/`modified` y cuenta líneas agregadas.

### Criterios de aceptación

- `classify_task("**task_type:** backend\n**complejidad_estimada:** high\n... endpoint API ...")` → `TaskMeta(task_type=backend, complexity=high)`.
- `classify_task("texto vacío")` → `TaskType.generic`, `Complexity.medium`.
- `Normalizer(api_key="...").convert(...)` realiza un POST a la URL correcta (verificable con mock httpx).
- `compute_diff({}, {"a.txt":"hola"})` retorna un patch unified que crea `a.txt`.

---

## Módulo 5 — Ingestor de Notion

**Objetivo:** descargar páginas Notion y convertirlas a texto plano consumible por el Normalizer.

**Requiere:** Módulo 1. (Independiente de Module 4: el Normalizer se compone aparte en `main.py`.)

### Archivos a crear

```
ingestors/
├── base.py
└── notion.py
```

### Instrucciones

1. **`ingestors/base.py`** — definir ABC mínimo para futuros ingestores:
    ```python
    from abc import ABC, abstractmethod
    class IngestorBase(ABC):
        @abstractmethod
        def ingest(self, source: str) -> dict: ...
        # debe retornar {"page_id", "page_url", "title", "raw_text"}
    ```

2. **`ingestors/notion.py`** — implementar literalmente lo descrito en [AI_HARNESS_DESIGN_v1.0.md §7](AI_HARNESS_DESIGN_v1.0.md):
    - Constantes `BASE_URL = "https://api.notion.com/v1"`, `NOTION_VERSION = "2022-06-28"`.
    - Excepción `NotionError(Exception)`.
    - Función `parse_page_id(url_or_id) -> str` que quita guiones y extrae 32 hex; lanza `ValueError` con mensaje claro si no encuentra match.
    - Clase `NotionClient(token)` con métodos:
        - `get_page(page_id) -> dict` ({id, url, title}); extrae título iterando properties con `type == "title"`.
        - `get_blocks(page_id) -> list[dict]` con paginación (`has_more`/`next_cursor`).
        - `extract_text(blocks) -> str`: soporta `paragraph`, `heading_1/2/3`, `bulleted_list_item`, `numbered_list_item` (con contador), `to_do` (checked/unchecked), `code` (con lenguaje), `quote`, `callout` (con emoji), `divider`. Tipos no soportados se ignoran sin error.
        - `_rich_text(rich_text)` static que concatena `plain_text` de cada run.
    - Implementar `NotionIngestor(IngestorBase)` que envuelve `NotionClient` y devuelve dict con `{page_id, page_url, title, raw_text}` listo para pasarle al `Normalizer`.

### Criterios de aceptación

- `parse_page_id("https://notion.so/Title-abc123def456abc123def456abc12345")` → `"abc123def456abc123def456abc12345"`.
- `parse_page_id("abc1-23de-f456-abc1-23de-f456abc123de")` → `"abc123def456abc123def456abc123de"`.
- `parse_page_id("no hay id")` lanza `ValueError`.
- `NotionClient.extract_text` produce markdown coherente para los 9 tipos soportados.

---

## Módulo 6 — Providers (Claude, Gemini, OpenCode)

**Objetivo:** wrappers `subprocess` de los CLIs externos, todos con soporte `project_dir` (Appendix A).

**Requiere:** Módulos 1 y 2.

### Archivos a crear

```
providers/
├── base.py
├── claude_code.py
├── gemini.py
└── opencode.py
```

### Instrucciones

1. **`providers/base.py`** — copia literal de [AI_HARNESS_DESIGN_v1.0.md §14](AI_HARNESS_DESIGN_v1.0.md):
    - `ProviderError(provider, message)` con prefijo `[{provider}]`.
    - ABC `ProviderBase`: campos `name`, `roles`, `priority`; métodos `supports_role(role)`, `planner_model_for(task_type)`, abstractos `generate_plan(task_md, task_type)` y `execute_step(step, task_md, plan_summary, task_type)`.

2. **`providers/claude_code.py`** — implementar `ClaudeCodeProvider` combinando [AI_HARNESS_DESIGN_v1.0.md §14](AI_HARNESS_DESIGN_v1.0.md) **y** [AI_HARNESS_APPENDIX_A_ProjectDirectory.md](AI_HARNESS_APPENDIX_A_ProjectDirectory.md):
    - Constructor: `__init__(self, model: str, project_dir: str, priority: int = 1, timeout: int = 240)`.
    - `self.name = f"claude_{'sonnet' if 'sonnet' in model else 'opus'}"`.
    - `_run(prompt)` usa `subprocess.run([...], cwd=self.project_dir, input=prompt, ...)`. Flags exactamente: `["claude", "--print", "--model", self.model, "--allowedTools", "Read,Edit,Bash", "--output-format", "json"]`.
    - `_parse(raw)` extrae bloque ```json``` con regex; un único reintento si falla `json.loads` pidiendo "SOLO el bloque ```json sin texto adicional".
    - `execute_step` lanza `NotImplementedError`.

3. **`providers/gemini.py`** — implementar `GeminiProvider`:
    - Constructor: `__init__(self, model="gemini-2.0-flash", project_dir: str = ".", timeout: int = 120)`.
    - Atributos de clase: `name = "gemini_flash"`, `roles = ["executor"]`, `priority = 1`.
    - `execute_step` arma el prompt con `executor_{task_type}.md` (fallback `executor_generic.md`) usando `_build_prompt`.
    - `_run(prompt)`: escribe a tempfile y llama `subprocess.run(["gemini", "--model", model, f"@{tmp}"], cwd=self.project_dir, ...)`. Si el primer intento devuelve `429`/`RESOURCE_EXHAUSTED`, sleep 60s y reintenta una vez.
    - `generate_plan`/`planner_model_for` lanzan `NotImplementedError`.

4. **`providers/opencode.py`** — implementar `OpenCodeProvider`:
    - Diccionario `FREE_MODELS = {"opencode/minimax-m2-5-free": ("opencode_minimax", 2), "opencode/big-pickle": ("opencode_bigpickle", 3)}`.
    - Constructor: `__init__(self, model, project_dir: str, timeout: int = 150)` — verifica `shutil.which("opencode")`, levanta `EnvironmentError` con mensaje de instalación si falta.
    - `(self.name, self.priority) = FREE_MODELS.get(model, ("opencode_unknown", 10))`.
    - Classmethod `build_chain(project_dir)` que arma `[OpenCodeProvider(m, project_dir) for m in FREE_MODELS]` capturando `EnvironmentError`.
    - `_run`: si `len(prompt) > 1500` → `_run_via_file`, si no → `_run_inline`. Ambos con `cwd=self.project_dir` y `--dangerously-skip-permissions`.
    - `_check(result)` lanza `ProviderError` si `returncode != 0` o `stdout` está vacío (sin output = hang sospechoso).

### Criterios de aceptación

- Importar los tres providers sin error.
- Construir `ClaudeCodeProvider(model="claude-sonnet-4-6", project_dir="/tmp")` no llama subprocess.
- Mock de `subprocess.run` recibe `cwd="/tmp"` en los tres.
- `OpenCodeProvider.build_chain("/tmp")` devuelve `[]` cuando `opencode` no está instalado en `PATH`.

---

## Módulo 7 — Harness core (Budget, Router, Orchestrator)

**Objetivo:** los tres componentes coordinadores que conectan providers, presupuesto y ejecución step-by-step.

**Requiere:** Módulos 1, 2, 3, 6.

### Archivos a crear

```
harness/
├── budget.py
├── router.py
└── orchestrator.py
```

### Instrucciones

1. **`harness/budget.py`** — implementar literalmente [AI_HARNESS_DESIGN_v1.0.md §10](AI_HARNESS_DESIGN_v1.0.md):
    - Constante `USAGE_FILE = Path.home() / ".ai-harness" / "usage.jsonl"`.
    - Función `count_tokens(text)` con `tiktoken.get_encoding("cl100k_base")`; fallback `len(text)//4` y warning una sola vez (`_tiktoken_warned`).
    - Dataclass `ProviderLimits(window_type, window_hours, max_requests, max_tokens, warn_at, critical_at)`.
    - Diccionario `PROVIDER_LIMITS` con las 5 entradas exactas del diseño.
    - Dataclass `ProviderUsage(provider, tokens_today, requests_today, tokens_month, request_times)` con `__post_init__` que inicializa la lista.
    - Clase `BudgetManager`:
        - `__init__` llama `_load_today` que rehidrata desde `usage.jsonl` filtrando por `date.today().isoformat()`.
        - `record(provider, prompt, response, requests=1) -> int` — cuenta tokens, actualiza usage, agrega timestamp, append a jsonl, chequea alerta. Retorna tokens contados.
        - `has_capacity(provider) -> bool` — para rolling: cuenta requests en `request_times` con cutoff `now - window_hours*3600`; threshold = `critical_at`.
        - `alert_level(provider) -> "ok"|"warn"|"critical"`.
        - `daily_summary() -> dict` con `requests_now/requests_max/tokens_today/pct/alert_level/window_type/window_hours` por provider.
        - `projected_exhaustion(provider) -> str|None` — proyecta `~Nh` según tasa horaria actual.
        - `_check_alert`, `_append_log`, `_load_today` privadas.

2. **`harness/router.py`** — implementar literalmente [AI_HARNESS_DESIGN_v1.0.md §11](AI_HARNESS_DESIGN_v1.0.md):
    - Excepción `ProviderExhausted(role)` con mensaje informativo sobre esperar reset o revisar menú de Budget.
    - Clase `Router(providers, budget, routing_config)`:
        - `select(role, complexity="medium", exclude=[]) -> ProviderBase` itera la lista `routing_config["routing"][role][complexity]`. Si el candidato no tiene capacity, muestra `pct` del summary, busca `next_available` y pregunta con `Confirm.ask`. Si el siguiente es OpenCode, **muestra aviso de privacidad** antes del Confirm. Si el usuario rechaza o no hay siguiente → `ProviderExhausted`.
        - `select_with_failover(role, complexity, tried=[])` delega en `select` con `exclude=tried`.
        - `status() -> dict` devuelve `{has_capacity, alert_level, summary}` por provider.
    - Función `build_router_from_config(providers, budget) -> Router` que lee `config/routing_rules.yaml`.

3. **`harness/orchestrator.py`** — implementar literalmente [AI_HARNESS_DESIGN_v1.0.md §15](AI_HARNESS_DESIGN_v1.0.md):
    - Clase `Orchestrator(router, budget, session)`:
        - `run(task_md, plan, complexity)` — ejecuta todos los steps en orden.
        - `resume(task_md, plan, progress, complexity)` — recalcula `pending_steps` y continúa.
        - `_execute_steps`: por cada step verifica deps con `_deps_met`, llama `_run_step`. Si `None` → marca `cancelled` y sale. Si `completed`/`skipped`/`failed` actualiza session. Si `failed` pregunta si continuar.
        - `_run_step` muestra cabecera con `console.rule`, archivos, validación; `_step_menu` (1=ejecutar, 2=skip, 3=cancel). Captura snapshot, hace failover con hasta 3 intentos: cada uno llama `router.select_with_failover("executor", complexity, tried)`, ejecuta, registra tokens con `budget.record`, computa diff y `detect_file_changes`, llama `_show_result`. Si `ProviderError` agrega al `tried` y pregunta si reintentar con otro.
        - `_show_result` imprime resumen + output truncado 600 chars + diff truncado 1200 chars (con `Syntax(..., "diff", theme="monokai")`).
        - `_show_summary`, `_build_summary` (con `project_dir` opcional en el header del prompt si el orchestrator lo conoce), `_deps_met` (en v1.0 retorna `True`).

### Criterios de aceptación

- `BudgetManager().record("gemini_flash", "x"*4000, "y"*4000)` retorna >100 tokens y crea `~/.ai-harness/usage.jsonl`.
- `Router([gemini], budget, {"routing":{"executor":{"medium":["gemini_flash"]}}}).select("executor", "medium")` retorna el provider.
- `Orchestrator(...).run(task_md, plan, "medium")` ejecuta el menú interactivo para cada step.

---

## Módulo 8 — Consola TUI (menús Rich)

**Objetivo:** implementar la UI completa de consola. Cubre los flujos de §16 del diseño y todos los menús de proyecto del Apéndice A.

**Requiere:** Módulos 3, 7.

### Archivos a crear

```
console/
├── app.py
└── menus/
    ├── main_menu.py
    ├── project_menu.py
    ├── task_menu.py
    ├── step_viewer.py
    ├── history_menu.py
    └── budget_menu.py
```

### Instrucciones

> Cada menú usa `rich.console.Console`, `rich.prompt.{Prompt,Confirm}`, `rich.table.Table`, `rich.panel.Panel`. El usuario manda — toda acción destructiva o de cambio se confirma.

1. **`console/menus/project_menu.py`** — copia literal del Appendix A:
    - `select_or_register_project() -> ProjectProfile` con bucle: 1=existente, 2=nuevo, B=volver (lanza `KeyboardInterrupt` para que el caller lo capture como "volver").
    - `_select_existing()` — tabla con `#/Nombre/Carpeta/Último uso`, usa `_relative_time(dt)` para formatear ("hace 2 días", "hace 5h", etc.). Valida la carpeta con `registry.validate_dir`. Si falta → `_handle_missing_dir`.
    - `_handle_missing_dir(profile)` — opciones: actualizar ruta / eliminar / volver. Si elimina, usa `shutil.rmtree(PROJECTS_ROOT/slug)` previa confirmación.
    - `_register_new()` — pide nombre, genera slug con `slugify`, valida unicidad (si colisión, sufija con `HHMMSS`). Pide ruta con `_prompt_project_dir`. Muestra preview con `_show_dir_preview` (primeros 8 items, iconos `📁`/`📄`). Confirma y persiste con `registry.save`.
    - `_prompt_project_dir() -> str | None` — loop de hasta 3 intentos; `expanduser().resolve()`. Devuelve `None` si el usuario escribe `b`/`back`/`cancelar` o agota intentos.

2. **`console/menus/main_menu.py`** — basado en §16 + `_change_project` y `_ensure_project_selected` del Appendix A:
    - Banner ASCII "AI DEV HARNESS v1.0" + panel de budget (usar `BudgetManager.daily_summary()` para barras de progreso y estado OK/WARN/CRITICAL — íconos `✓`/`⚠`/`🚨`).
    - Opciones: `[1]` Nuevo task, `[2]` Retomar, `[3]` Historial, `[4]` Budget detallado, `[5]` Cambiar proyecto, `[Q]` Salir.
    - `_new_task()`: garantiza proyecto activo (`_ensure_project_selected`), luego pide URL/ID Notion, ejecuta pipeline (NotionIngestor → Normalizer → SessionManager → classifier → confirmación de complexity → context collection → planner → aprobación plan → orchestrator).
    - **Menú de Clasificación y Complexity** (§16): opciones 1=usar detección, 2=bajar a MEDIUM, 3=bajar a LOW, 4=EXTRA HIGH (con aviso de uso de Opus tomado de `budget.daily_summary()["claude_opus"]`), 5=cambiar tipo. **Solo aquí se asigna `extra_high`.**
    - **Menú de Aprobación de Plan**: muestra los steps en panel; opciones A=aprobar, R=regenerar, V=ver JSON, C=cancelar.

3. **`console/menus/task_menu.py`** — menú del task activo: ver plan, lanzar ejecución, ver progreso del run actual.

4. **`console/menus/step_viewer.py`** — vista detallada de un step: output completo, diff completo, archivos tocados, notas del usuario.

5. **`console/menus/history_menu.py`** — `[H]` por proyecto/task: tabla de runs con estado y conteo de steps; sub-vista de detalle con steps individuales y opciones `[S]` ver output, `[D]` ver diff, `[R]` retomar, `[L]` limpiar historial (preserva `task.md` y `project_context.json`).

6. **`console/menus/budget_menu.py`** — pantalla de §16 con dos tablas (PLANNERS rolling 5h, EXECUTORS) usando `budget.daily_summary()` y `projected_exhaustion()`.

7. **`console/app.py`** — clase `ConsoleApp`:
    - `__init__` carga config, crea `BudgetManager`, `MainMenu`.
    - `run()` ejecuta el loop principal; captura `KeyboardInterrupt` y `EOFError` para salida limpia.

### Criterios de aceptación

- `python -c "from console.menus.project_menu import select_or_register_project; print('ok')"` imprime ok.
- `python main.py` muestra el banner y menú principal sin error si las CLIs externas no están instaladas (con warning).
- Seleccionar `[5] Cambiar proyecto` sin proyectos previos lleva al menú de registro nuevo.

---

## Módulo 9 — Entry point y wiring

**Objetivo:** `main.py` orquesta la carga de config, construye providers/router/orchestrator y lanza la consola.

**Requiere:** Módulos 1–8.

### Archivos a crear

```
main.py
```

### Instrucciones

1. **`load_config()`** — copia literal del diseño §18 (lee `.env`, valida `NOTION_TOKEN` y `GOOGLE_API_KEY`, carga los dos YAML).

2. **`build_providers(project_dir: str) -> list[ProviderBase]`** — copia literal del Appendix A:
    - Si `shutil.which("claude")` → agrega `ClaudeCodeProvider(model="claude-sonnet-4-6", project_dir=..., priority=1)` y `ClaudeCodeProvider(model="claude-opus-4-6", project_dir=..., priority=99)`.
    - Si `shutil.which("gemini")` → agrega `GeminiProvider(model="gemini-2.0-flash", project_dir=...)`.
    - Si `shutil.which("opencode")` → agrega `OpenCodeProvider` por cada modelo de `FREE_MODELS` con `project_dir=...`.
    - Si la lista resultante está vacía → `RuntimeError` con mensaje claro.

3. **`build_orchestrator(profile: ProjectProfile, session: SessionManager) -> Orchestrator`** — copia literal del Appendix A: lee config, crea `BudgetManager`, `build_providers(profile.project_dir)`, `build_router_from_config`, retorna `Orchestrator`.

4. **`main()`** — entry point:
    ```python
    def main():
        try:
            ConsoleApp().run()
        except KeyboardInterrupt:
            print("\nSaliendo…")
        except Exception as e:
            import traceback; traceback.print_exc()
            sys.exit(1)
    ```

5. **Comportamiento clave del wiring (importante):** el orchestrator y los providers **se reconstruyen** cada vez que el usuario cambia de proyecto activo. `MainMenu._change_project` debe invocar `build_orchestrator(new_profile, session)`. Esto está documentado en el Appendix A — copiarlo exactamente.

### Criterios de aceptación

- `python main.py` con `.env` válido arranca y muestra el menú principal.
- Si falta `NOTION_TOKEN` o `GOOGLE_API_KEY`, el error sale ANTES de lanzar la consola, con mensaje legible.
- Cambiar de proyecto desde el menú principal regenera providers con el nuevo `cwd`.

---

## Cierre — Checklist global de validación

Una vez todos los módulos estén listos, validar end-to-end:

- [ ] `pip install -e .` instala sin errores.
- [ ] `python main.py` arranca y muestra el banner.
- [ ] Registrar un proyecto nuevo escribe `~/.ai-harness/projects/<slug>/profile.json`.
- [ ] Ingestar una página de Notion con un task de ejemplo produce un `task.md` plausible.
- [ ] El classifier asigna tipo/complejidad sin tokens.
- [ ] El planner genera un `TaskPlan` válido (Pydantic no levanta excepción).
- [ ] El usuario aprueba el plan y se crea `run_YYYYMMDD_HHMMSS/`.
- [ ] El primer step se ejecuta con Gemini, se captura diff, se guardan `step_0_output.md` / `step_0_diff.patch` / `step_0_files.json`.
- [ ] El budget se actualiza en `~/.ai-harness/usage.jsonl`.
- [ ] El menú de Budget muestra porcentajes coherentes.
- [ ] Cambiar de proyecto regenera los providers con el `cwd` correcto (verificable inspeccionando un subprocess con `lsof`/`ps`).
- [ ] Forzar agotamiento de un provider (manipular `usage.jsonl`) dispara el flujo de failover interactivo con aviso de privacidad antes de OpenCode.

---

## Notas de seguridad y consideraciones finales

1. **Aviso de privacidad obligatorio** — toda activación de modelos free de OpenCode Zen debe mostrar la advertencia antes de la `Confirm.ask`. Esto vive en `harness/router.py` y NO debe omitirse.
2. **`--dangerously-skip-permissions`** se usa solo con OpenCode por el bug conocido (#13851). Documentarlo en el código con un comentario que linkee al issue.
3. **`cwd` en subprocess** es la línea de defensa contra que los agentes editen archivos fuera del proyecto. Cualquier nuevo provider debe seguir la misma convención del Apéndice A.
4. **Token counting** usa `tiktoken` cuando está disponible; el fallback `len//4` es solo aproximado y emite un warning por sesión.
5. **`extra_high`** nunca se asigna programáticamente — única ruta de entrada es el menú de confirmación de complejidad. El classifier debe respetar esta invariante.
