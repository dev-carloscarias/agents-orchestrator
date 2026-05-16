# Plan de Implementación — quetz-meta-harness
**Versión:** 1.0  
**Fecha:** 2026-05-15  
**Referencia de diseño:** `META_HARNESS_PLAN.md`

---

## Flujo completo del sistema (para referencia de cada módulo)

```
[1] Usuario ejecuta: harness start
        │
        ▼
[2] INGEST: Pide Notion page URL/ID al usuario
        │
        ▼
[3] Notion Client: descarga bloques de la página
        │
        ▼
[4] Converter (Gemini Flash): convierte bloques → task.md estandarizado
        │
        ▼
[5] SESSION CHECK: ¿existe ~/.quetz-meta-harness/sessions/{page_id}/?
        │
        ├── SÍ: carga task.md + plan.json + progress.json
        │         pregunta al usuario: ¿retomar o reiniciar?
        │
        └── NO: crea directorio de sesión, guarda task.md
        │
        ▼
[6] CLASSIFIER: clasifica complejidad del task (heurística local, sin tokens)
        │
        ▼
[7] BUDGET ROUTER: selecciona mejor PLANNER disponible (sin límite agotado)
        │
        ▼
[8] PLANNER: genera plan estructurado → plan.json (guardado en sesión)
        │
        ▼
[9] Por cada step pendiente (los ya completos se saltan):
        │   BUDGET ROUTER selecciona mejor EXECUTOR disponible
        │   EXECUTOR ejecuta el step
        │   Resultado guardado en progress.json
        │   Failover si el executor falla
        │
        ▼
[10] TaskResult final → sync a Notion (actualiza status de la página)
```

---

## Estructura de directorios objetivo

```
meta-harness/
├── ingest/
│   ├── __init__.py
│   ├── ingester.py          # CLI interactivo: pide page URL → devuelve task.md
│   ├── notion_client.py     # Fetch de bloques Notion REST API
│   └── converter.py         # Gemini Flash: bloques Notion → task.md estandarizado
├── session/
│   ├── __init__.py
│   └── manager.py           # Crea/carga sesiones por page_id
├── harness/
│   ├── __init__.py
│   ├── protocols.py         # Pydantic schemas: TaskPlan, Step, StepResult, TaskResult
│   ├── classifier.py        # Clasifica complejidad (heurística local)
│   ├── budget.py            # BudgetManager: tracking + límites
│   ├── router.py            # Router con failover
│   └── orchestrator.py      # MetaOrchestrator: coordina todo el flujo
├── providers/
│   ├── __init__.py
│   ├── base.py              # ProviderBase ABC
│   ├── claude_code.py       # claude CLI wrapper
│   ├── gemini.py            # gemini CLI wrapper
│   └── opencode.py          # opencode CLI wrapper
├── config/
│   ├── providers.yaml       # Definición de providers, modelos, límites
│   ├── routing_rules.yaml   # Reglas de routing por complejidad
│   └── prompts/
│       ├── planner.md       # System prompt del planner (JSON estructurado)
│       ├── executor.md      # System prompt del executor
│       └── converter.md     # System prompt del converter Notion→MD
├── .env.example
├── pyproject.toml
└── main.py                  # Typer CLI entry point
```

**Almacenamiento en tiempo de ejecución:**
```
~/.quetz-meta-harness/
├── usage.jsonl              # Log de tokens por provider
└── sessions/
    └── {notion_page_id}/
        ├── task.md          # Task en formato estandarizado
        ├── plan.json        # TaskPlan serializado
        └── progress.json    # Estado de cada step
```

---

## Formato estándar de task.md

Todo task ingresado desde Notion se convierte a este formato. Es el contrato entre el ingester y el orchestrator.

```markdown
# {título de la página Notion}

**notion_id:** {page_id}  
**notion_url:** {url}  
**complejidad_estimada:** low | medium | high  
**fecha_ingesta:** {ISO datetime}  

## Objetivo
{Descripción clara de qué se debe lograr. 2-5 oraciones.}

## Contexto
{Información de fondo relevante. Puede incluir decisiones previas, restricciones técnicas, etc.}

## Criterios de Aceptación
- {criterio 1 — verificable y específico}
- {criterio 2}
- {criterio N}

## Archivos Relevantes
- `{ruta/al/archivo.py}` — {por qué es relevante}

## Notas Adicionales
{Cualquier otra información del documento Notion que no encaje arriba.}
```

El converter con Gemini Flash recibe el texto crudo de Notion y devuelve **exactamente** este formato. Si un campo no tiene información, se omite la sección completa (no se pone "N/A").

---

## Formato de progress.json

```json
{
  "notion_page_id": "abc123",
  "started_at": "2026-05-15T10:00:00Z",
  "updated_at": "2026-05-15T10:30:00Z",
  "status": "in_progress",
  "steps": {
    "0": {"status": "completed", "executor": "claude_code", "tokens": 1200},
    "1": {"status": "completed", "executor": "gemini",     "tokens": 800},
    "2": {"status": "pending",   "executor": null,         "tokens": 0},
    "3": {"status": "failed",    "executor": "gemini",     "tokens": 400, "error": "timeout"}
  }
}
```

`status` del task: `"pending"` | `"in_progress"` | `"completed"` | `"failed"`  
`status` de cada step: `"pending"` | `"completed"` | `"failed"` | `"skipped"`

---

---

# MÓDULO 0 — Scaffold del proyecto

**Sesión estimada:** 20 min  
**Dependencias previas:** ninguna  
**Objetivo:** Crear la estructura vacía del proyecto con todos los archivos base.

## Instrucciones para el agente

### 0.1 Crear pyproject.toml

Crear `/home/lito/development/agents-orchestrator/pyproject.toml`:

```toml
[project]
name = "quetz-meta-harness"
version = "0.1.0"
requires-python = ">=3.12"
description = "Meta-harness multi-proveedor para orquestación de agentes de IA"

dependencies = [
    "pydantic>=2.7",
    "typer[all]>=0.12",
    "rich>=13",
    "pyyaml>=6",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "aiofiles>=23",
]

[project.scripts]
harness = "main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ingest", "session", "harness", "providers"]
```

### 0.2 Crear .env.example

Crear `/home/lito/development/agents-orchestrator/.env.example`:

```bash
# Anthropic — solo si se usa API directa (no CLI suscripción)
ANTHROPIC_API_KEY=sk-ant-

# Google AI Studio — gratuito en https://aistudio.google.com/
GOOGLE_API_KEY=AIza

# OpenAI — fallback de pago
OPENAI_API_KEY=sk-

# Notion
NOTION_TOKEN=secret_
NOTION_DATABASE_ID=
```

### 0.3 Crear directorios y __init__.py vacíos

Crear los siguientes archivos vacíos (solo `pass` o vacíos):
- `ingest/__init__.py`
- `session/__init__.py`
- `harness/__init__.py`
- `providers/__init__.py`
- `config/prompts/` (directorio vacío)

### 0.4 Crear config/providers.yaml

```yaml
providers:
  claude_code:
    cli: claude
    priority: 1
    roles: [planner, executor]
    models:
      planner: claude-opus-4-7
      executor: claude-haiku-4-5-20251001
    limits:
      daily_tokens: 2000000
      monthly_tokens: 50000000

  gemini:
    cli: gemini
    priority: 2
    roles: [planner, executor]
    models:
      planner: gemini-2.5-pro
      executor: gemini-2.0-flash
      converter: gemini-2.0-flash   # modelo para Notion→MD
    limits:
      daily_requests: 1500
      rpm: 15

  opencode:
    cli: opencode
    priority: 10
    roles: [planner, executor]
    models:
      planner: gpt-4o
      executor: gpt-4o-mini
    limits:
      daily_tokens: 500000
```

### 0.5 Crear config/routing_rules.yaml

```yaml
routing:
  planner:
    low:    [claude_code, gemini, opencode]
    medium: [claude_code, gemini, opencode]
    high:   [claude_code, gemini, opencode]
  executor:
    low:    [gemini, claude_code, opencode]    # flash primero para tasks simples
    medium: [claude_code, gemini, opencode]
    high:   [claude_code, gemini, opencode]
```

### 0.6 Crear config/prompts/ (tres archivos)

**config/prompts/converter.md** — instrucciones para Gemini Flash al convertir Notion:
```
Eres un asistente que convierte documentos de Notion a formato Markdown estandarizado.

Recibirás el texto crudo de una página de Notion. Debes producir EXACTAMENTE el siguiente formato:

# {título}

**notion_id:** {page_id}
**notion_url:** {url}
**complejidad_estimada:** low | medium | high
**fecha_ingesta:** {ISO datetime actual}

## Objetivo
{extrae o infiere el objetivo principal del documento}

## Contexto
{extrae información de fondo, decisiones previas, restricciones}

## Criterios de Aceptación
- {extrae criterios verificables, uno por línea}

## Archivos Relevantes
- `{ruta}` — {relevancia}

## Notas Adicionales
{cualquier otra información}

REGLAS:
- Si una sección no tiene información, omítela completamente
- No inventes información que no esté en el documento original
- complejidad_estimada: low=cambio puntual, medium=múltiples archivos, high=arquitectura/refactor
- Devuelve SOLO el markdown, sin explicaciones adicionales
```

**config/prompts/planner.md** — system prompt del planner (ver META_HARNESS_PLAN.md sección "Prompts del Sistema")

**config/prompts/executor.md** — system prompt del executor (ver META_HARNESS_PLAN.md sección "Prompts del Sistema")

## Criterio de validación del módulo 0

```bash
# Debe pasar sin errores:
ls meta-harness/ingest/__init__.py meta-harness/session/__init__.py \
   meta-harness/harness/__init__.py meta-harness/providers/__init__.py \
   meta-harness/config/providers.yaml meta-harness/config/routing_rules.yaml \
   meta-harness/config/prompts/converter.md \
   meta-harness/config/prompts/planner.md \
   meta-harness/config/prompts/executor.md \
   meta-harness/pyproject.toml meta-harness/.env.example
```

---

---

# MÓDULO 1 — Schemas y Protocols

**Sesión estimada:** 45 min  
**Dependencias previas:** Módulo 0  
**Objetivo:** Definir todos los tipos Pydantic que el sistema usará. Es el contrato entre módulos.  
**Archivo a crear:** `harness/protocols.py`

## Instrucciones para el agente

Crear `harness/protocols.py` con exactamente estas clases. No agregar métodos extra, no simplificar campos.

```python
from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


class Complexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class StepStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class Step(BaseModel):
    index: int
    description: str
    target_files: list[str]
    validation: str
    expected_output: str
    depends_on: list[int] = Field(default_factory=list)


class TaskPlan(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    notion_page_id: str
    complexity: Complexity
    summary: str
    steps: list[Step]
    context_files: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    planner_used: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StepResult(BaseModel):
    step_index: int
    status: StepStatus
    output: str
    tokens_used: int
    executor_used: str
    duration_seconds: float
    error: Optional[str] = None


class TaskResult(BaseModel):
    task_id: str
    notion_page_id: str
    plan: TaskPlan
    step_results: list[StepResult]
    status: TaskStatus
    total_tokens: int
    total_duration_seconds: float
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class SessionProgress(BaseModel):
    """Serializa a progress.json — estado de la sesión entre ejecuciones."""
    notion_page_id: str
    task_id: str
    started_at: datetime
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: TaskStatus = TaskStatus.pending
    steps: dict[str, dict] = Field(default_factory=dict)
    # steps keys son str(index), values son dicts con status/executor/tokens/error
```

## Criterio de validación del módulo 1

```bash
cd meta-harness
python -c "from harness.protocols import TaskPlan, Step, StepResult, TaskResult, SessionProgress, Complexity; print('OK')"
```

---

---

# MÓDULO 2 — Notion Client y Converter

**Sesión estimada:** 90 min  
**Dependencias previas:** Módulo 0, Módulo 1  
**Objetivo:** Descargar el contenido de una página Notion y convertirlo al formato task.md estándar usando Gemini Flash.  
**Archivos a crear:** `ingest/notion_client.py`, `ingest/converter.py`

## Instrucciones para el agente

### 2.1 — ingest/notion_client.py

Este módulo usa `httpx` para llamar a la Notion REST API. Lee `NOTION_TOKEN` del entorno.

**Interfaces que debe exponer:**

```python
class NotionClient:
    def __init__(self, token: str): ...

    def get_page(self, page_id: str) -> dict:
        """
        GET /v1/pages/{page_id}
        Devuelve el dict completo de la página Notion.
        Extrae: id, url, properties['title'].
        Lanza NotionError si el status HTTP no es 200.
        """

    def get_blocks(self, page_id: str) -> list[dict]:
        """
        GET /v1/blocks/{page_id}/children?page_size=100
        Maneja paginación con cursor (next_cursor).
        Devuelve lista flat de todos los bloques.
        """

    def extract_text(self, blocks: list[dict]) -> str:
        """
        Convierte la lista de bloques a texto plano.
        Tipos de bloque a soportar:
          - paragraph, heading_1/2/3: extrae rich_text
          - bulleted_list_item, numbered_list_item: prefija con "- " o "N. "
          - code: envuelve en ```
          - to_do: prefija con "- [ ] " o "- [x] "
          - quote: prefija con "> "
          - divider: convierte a "---"
          - callout: extrae icon + rich_text
        Tipos ignorados: image, video, file, embed, bookmark
        """

class NotionError(Exception): ...
```

**Constante de cabeceras HTTP a usar:**
```python
HEADERS = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
BASE_URL = "https://api.notion.com/v1"
```

**Nota importante:** `page_id` puede llegar con o sin guiones. Normalizar siempre quitando guiones antes de las llamadas API. La URL de Notion tiene el page_id como los últimos 32 caracteres hex (sin guiones) al final del path.

Incluir función helper:
```python
def parse_page_id(url_or_id: str) -> str:
    """
    Acepta:
      - ID limpio: "abc123def456..."  (32 chars hex)
      - ID con guiones: "abc123de-f456-..."
      - URL de Notion: "https://notion.so/workspace/Title-abc123def456..."
    Devuelve siempre el ID de 32 chars sin guiones.
    Lanza ValueError si no puede extraer un ID válido.
    """
```

### 2.2 — ingest/converter.py

Recibe el texto crudo de Notion y usa Gemini Flash para convertirlo al formato task.md estándar.

**Interface:**

```python
class NotionConverter:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"): ...

    def convert(
        self,
        raw_text: str,
        page_id: str,
        page_url: str,
        page_title: str,
    ) -> str:
        """
        Llama a Gemini Flash con el prompt del converter.
        Devuelve el string completo del task.md estandarizado.
        El system prompt viene de config/prompts/converter.md.
        Inyecta page_id, page_url y fecha actual en el prompt.
        """
```

**Implementación de la llamada a Gemini:**

Usar la API REST de Google Generative AI directamente con `httpx` (no el SDK de Python para mantener dependencias mínimas):

```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
Body:
{
  "system_instruction": {"parts": [{"text": "<contenido de converter.md>"}]},
  "contents": [{
    "role": "user",
    "parts": [{"text": "page_id: {page_id}\npage_url: {page_url}\npage_title: {page_title}\n\n---\n\n{raw_text}"}]
  }]
}
```

Extraer `response["candidates"][0]["content"]["parts"][0]["text"]`.

## Criterio de validación del módulo 2

```bash
cd meta-harness
python -c "
from ingest.notion_client import NotionClient, parse_page_id
# Test parse_page_id
assert parse_page_id('abc123def456abc123def456abc123de') == 'abc123def456abc123def456abc123de'
assert parse_page_id('abc123de-f456-abc1-23de-f456abc123de') == 'abc123def456abc123def456abc123de'
print('parse_page_id OK')
"

# Con credenciales reales:
# python -c "
# from ingest.notion_client import NotionClient
# import os; from dotenv import load_dotenv; load_dotenv()
# client = NotionClient(os.environ['NOTION_TOKEN'])
# page = client.get_page('TU_PAGE_ID')
# print(page['id'])
# "
```

---

---

# MÓDULO 3 — Ingester (CLI de ingesta)

**Sesión estimada:** 45 min  
**Dependencias previas:** Módulo 2  
**Objetivo:** Script interactivo que guía al usuario para ingresar una página Notion y produce el task.md listo para el orchestrator.  
**Archivo a crear:** `ingest/ingester.py`

## Instrucciones para el agente

`ingester.py` es el punto de entrada de la fase de ingesta. Se llama desde `main.py` cuando el usuario ejecuta `harness start`.

**Interface pública:**

```python
def ingest_task(config: dict) -> tuple[str, str]:
    """
    Flujo interactivo completo:
      1. Pide al usuario la URL o ID de la página Notion
      2. Parsea y valida el page_id
      3. Descarga la página con NotionClient
      4. Convierte el contenido con NotionConverter
      5. Devuelve (page_id, task_md_content)
    
    config: dict con keys 'notion_token', 'google_api_key', 'gemini_converter_model'
    Usa rich.console para los mensajes al usuario.
    """
```

**Flujo de mensajes al usuario con Rich:**

```
╔══════════════════════════════════════╗
║  quetz-meta-harness — Ingesta de Task ║
╚══════════════════════════════════════╝

Pega la URL o ID de la página Notion:
> [input del usuario]

⏳ Descargando página...
✓ Página: "Título de la página"

⏳ Convirtiendo a formato estándar con Gemini Flash...
✓ Task generado (847 caracteres)

Vista previa:
─────────────────────────────────────
# Título de la página
**notion_id:** abc123...
...
─────────────────────────────────────
¿Continuar con este task? [S/n]:
```

Si el usuario responde "n", volver a pedir la URL (máximo 3 reintentos).

**Manejo de errores:**
- `NotionError`: mostrar mensaje claro y salir con `raise typer.Exit(1)`
- `ValueError` (page_id inválido): mostrar "No pude extraer el ID de esa URL. Prueba con el ID directo." y reintentar
- Timeout de red: mostrar error y sugerir reintentar

## Criterio de validación del módulo 3

```bash
# Test de smoke (mock de las llamadas externas):
python -c "
from ingest.notion_client import parse_page_id
# Simular el flujo sin llamadas reales
test_url = 'https://www.notion.so/My-Task-Title-abc123def456abc123def456abc1234d'
page_id = parse_page_id(test_url)
assert len(page_id) == 32
print(f'page_id extraído: {page_id}')
print('OK')
"
```

---

---

# MÓDULO 4 — Session Manager

**Sesión estimada:** 60 min  
**Dependencias previas:** Módulo 1  
**Objetivo:** Crear y cargar sesiones por page_id. Permite retomar trabajo interrumpido entre ejecuciones.  
**Archivo a crear:** `session/manager.py`

## Instrucciones para el agente

### Directorio de sesión

Cada sesión vive en `~/.quetz-meta-harness/sessions/{page_id}/`:
- `task.md` — contenido del task en formato estándar
- `plan.json` — TaskPlan serializado (Pydantic model_dump_json)
- `progress.json` — SessionProgress serializado

### Interface completa

```python
from pathlib import Path
from harness.protocols import TaskPlan, SessionProgress, TaskStatus, StepStatus
from datetime import datetime
import json

SESSIONS_DIR = Path.home() / ".quetz-meta-harness" / "sessions"


class SessionManager:
    def __init__(self, page_id: str):
        self.page_id = page_id
        self.session_dir = SESSIONS_DIR / page_id
        self.task_file = self.session_dir / "task.md"
        self.plan_file = self.session_dir / "plan.json"
        self.progress_file = self.session_dir / "progress.json"

    def exists(self) -> bool:
        """True si hay una sesión previa para este page_id."""
        return self.session_dir.exists() and self.task_file.exists()

    def create(self, task_md: str) -> None:
        """
        Crea el directorio de sesión y guarda task.md.
        Si ya existe, sobreescribe solo task.md (no borra plan ni progress).
        """

    def save_plan(self, plan: TaskPlan) -> None:
        """Serializa y guarda plan.json. Crea/actualiza progress.json con todos los steps en 'pending'."""

    def load_plan(self) -> TaskPlan | None:
        """Carga plan.json. Devuelve None si no existe."""

    def load_task(self) -> str:
        """Lee task.md. Lanza FileNotFoundError si no existe."""

    def load_progress(self) -> SessionProgress | None:
        """Carga progress.json. Devuelve None si no existe."""

    def mark_step_completed(self, step_index: int, executor: str, tokens: int) -> None:
        """
        Actualiza progress.json: marca el step como 'completed'.
        También actualiza updated_at y status del task a 'in_progress'.
        """

    def mark_step_failed(self, step_index: int, executor: str, tokens: int, error: str) -> None:
        """Actualiza progress.json: marca el step como 'failed'."""

    def mark_task_completed(self) -> None:
        """Actualiza progress.json: status del task a 'completed'."""

    def mark_task_failed(self) -> None:
        """Actualiza progress.json: status del task a 'failed'."""

    def pending_steps(self, plan: TaskPlan) -> list[int]:
        """
        Devuelve los índices de steps que aún no están 'completed'.
        Si no hay progress.json, devuelve todos los índices.
        """

    def summary(self) -> dict:
        """
        Para mostrar al usuario cuando se retoma una sesión.
        Devuelve dict con:
          - task_title: primera línea de task.md (el # título)
          - started_at: cuándo se empezó
          - updated_at: última actividad
          - completed_steps: N
          - failed_steps: N
          - pending_steps: N
          - status: 'in_progress' | 'failed' | etc.
        """
```

### Comportamiento al retomar sesión

Cuando `SessionManager.exists()` es `True`, el orchestrator debe mostrar al usuario:

```
⚠️  Sesión existente encontrada para esta página

  Task: "Implementar autenticación JWT"
  Iniciada: 2026-05-14 09:30
  Última actividad: 2026-05-14 11:45
  
  Progreso: ██████░░░░ 3/5 steps completados
  Steps fallidos: 1 (step 2)
  
¿Qué deseas hacer?
  [R] Retomar desde donde quedó
  [N] Reiniciar desde cero
  [V] Ver el plan completo

> 
```

## Criterio de validación del módulo 4

```python
# Test sin I/O externo:
import tempfile, os
from unittest.mock import patch

with tempfile.TemporaryDirectory() as tmp:
    with patch("session.manager.SESSIONS_DIR", Path(tmp)):
        from session.manager import SessionManager
        sm = SessionManager("test_page_id_32chars000000000000")
        assert not sm.exists()
        sm.create("# Test Task\n**notion_id:** test_page_id_32chars000000000000")
        assert sm.exists()
        assert "Test Task" in sm.load_task()
        print("SessionManager OK")
```

---

---

# MÓDULO 5 — Budget Manager

**Sesión estimada:** 45 min  
**Dependencias previas:** Módulo 0  
**Objetivo:** Trackear consumo de tokens/requests por provider. Determinar si un provider tiene capacidad disponible.  
**Archivo a crear:** `harness/budget.py`

## Instrucciones para el agente

Implementar exactamente la clase `BudgetManager` especificada en `META_HARNESS_PLAN.md` (sección "Budget Manager"), con estas adiciones:

### Adiciones a la spec de META_HARNESS_PLAN.md

1. `USAGE_FILE = Path.home() / ".quetz-meta-harness" / "usage.jsonl"` (cambia de `~/.quetz-orchestrator/`)

2. Agregar método `daily_summary() -> dict[str, dict]`:
```python
def daily_summary(self) -> dict[str, dict]:
    """
    Devuelve dict por provider con tokens_today, requests_today,
    y porcentaje del límite diario consumido.
    Usado por 'harness status'.
    """
```

3. El margen de seguridad al 90% debe ser configurable:
```python
def __init__(self, limits: dict[str, ProviderLimits], safety_margin: float = 0.9): ...
```

4. Incluir `ProviderLimits` como dataclass en este mismo archivo:
```python
@dataclass
class ProviderLimits:
    daily_tokens: int | None = None
    monthly_tokens: int | None = None
    daily_requests: int | None = None
    rpm: int | None = None
```

### Carga de límites desde YAML

Agregar función helper al final del archivo:
```python
def load_budget_from_config(config_path: str = "config/providers.yaml") -> BudgetManager:
    """Lee providers.yaml y construye un BudgetManager listo para usar."""
    import yaml
    config = yaml.safe_load(Path(config_path).read_text())
    limits = {}
    for name, cfg in config["providers"].items():
        raw = cfg.get("limits", {})
        limits[name] = ProviderLimits(**{
            k: v for k, v in raw.items()
            if k in ProviderLimits.__dataclass_fields__
        })
    return BudgetManager(limits)
```

## Criterio de validación del módulo 5

```python
from harness.budget import BudgetManager, ProviderLimits

budget = BudgetManager({
    "claude_code": ProviderLimits(daily_tokens=100),
    "gemini": ProviderLimits(daily_requests=10),
})
budget.record("claude_code", tokens=80)
assert not budget.has_capacity("claude_code", "planner")   # 80/100 = 80% < 90%... espera
# Corrección: 80 >= 100*0.9=90? No. 80 < 90, entonces SÍ tiene capacity.
# Pero si tokens=95: 95 >= 90, entonces NO tiene capacity.
budget.record("claude_code", tokens=15)  # total=95
assert not budget.has_capacity("claude_code", "planner")   # 95 >= 90
assert budget.has_capacity("gemini", "executor")            # 0/10 requests
print("BudgetManager OK")
```

---

---

# MÓDULO 6 — Providers (Base + Claude Code + Gemini)

**Sesión estimada:** 120 min  
**Dependencias previas:** Módulo 1, Módulo 5  
**Objetivo:** Implementar el patrón Strategy para los providers. Esta sesión cubre los dos providers principales.  
**Archivos a crear:** `providers/base.py`, `providers/claude_code.py`, `providers/gemini.py`

## Instrucciones para el agente

### 6.1 — providers/base.py

```python
from abc import ABC, abstractmethod
from harness.protocols import Step, StepResult, TaskPlan
from typing import Literal


class ProviderBase(ABC):
    name: str
    roles: list[Literal["planner", "executor"]]
    priority: int

    def supports_role(self, role: str) -> bool:
        return role in self.roles

    @abstractmethod
    def generate_plan(self, task_md: str) -> TaskPlan:
        """
        task_md: contenido completo del task.md estandarizado.
        Devuelve TaskPlan parseado desde el JSON que devuelve el modelo.
        Lanza ProviderError si el CLI falla o el JSON es inválido.
        """
        ...

    @abstractmethod
    def execute_step(self, step: Step, task_md: str, plan_summary: str) -> StepResult:
        """
        step: el step a ejecutar.
        task_md: contexto completo del task (para que el executor entienda el objetivo).
        plan_summary: resumen del plan (qué steps hay, cuál es el objetivo global).
        """
        ...


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
```

### 6.2 — providers/claude_code.py

Implementar siguiendo el spec de `META_HARNESS_PLAN.md` sección "Claude Code Provider", con estas diferencias:

1. `generate_plan` recibe `task_md: str` (no `task, context` por separado)
2. El prompt del planner es: `{contenido de planner.md}\n\n{task_md}`
3. El prompt del executor incluye:
   ```
   {contenido de executor.md}
   
   # Task Context
   {task_md}
   
   # Plan Summary
   {plan_summary}
   
   # Step {index}: {description}
   Target files: {target_files}
   Validation: {validation}
   Expected: {expected_output}
   ```
4. `notion_page_id` en `TaskPlan`: el planner no lo sabe. Se lo inyecta el orchestrator después de recibir el plan.
5. Timeout del planner: 300s. Timeout del executor: 180s.

**Manejo de errores del CLI:**
```python
if result.returncode != 0:
    raise ProviderError(self.name, f"CLI exited {result.returncode}: {result.stderr[:500]}")
```

Si el JSON del planner no es parseable, reintentar una vez con el mensaje:
```
El JSON que devolviste tenía errores de parseo. Devuelve SOLO el bloque ```json sin texto adicional.
{output_previo}
```

### 6.3 — providers/gemini.py

Implementar igual que `ClaudeCodeProvider` pero:

1. CLI invocación: `gemini -m {model} @{tmpfile}` (usa archivo temporal para prompts largos)
2. Timeout del planner: 240s. Timeout del executor: 120s.
3. Manejar el rate limit de Gemini: si el CLI devuelve error con "429" o "RESOURCE_EXHAUSTED", esperar 60s y reintentar una vez.

```python
def _run_cli(self, model: str, prompt: str, timeout: int = 120) -> str:
    import tempfile, os, time
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        tmp = f.name
    try:
        result = subprocess.run(
            ["gemini", "-m", model, f"@{tmp}"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr
            if "429" in stderr or "RESOURCE_EXHAUSTED" in stderr:
                time.sleep(60)
                result = subprocess.run(
                    ["gemini", "-m", model, f"@{tmp}"],
                    capture_output=True, text=True, timeout=timeout,
                )
            if result.returncode != 0:
                raise ProviderError(self.name, f"CLI error: {result.stderr[:500]}")
        return result.stdout
    finally:
        os.unlink(tmp)
```

## Criterio de validación del módulo 6

```python
from providers.base import ProviderBase, ProviderError
from providers.claude_code import ClaudeCodeProvider
from providers.gemini import GeminiProvider

# Verificar herencia y atributos
cc = ClaudeCodeProvider("claude-opus-4-7", "claude-haiku-4-5-20251001")
assert cc.supports_role("planner")
assert cc.supports_role("executor")
assert cc.priority == 1

gem = GeminiProvider()
assert gem.supports_role("planner")
assert gem.priority == 2

print("Providers structure OK")
# Nota: no testear llamadas reales al CLI aquí
```

---

---

# MÓDULO 7 — OpenCode Provider

**Sesión estimada:** 30 min  
**Dependencias previas:** Módulo 6  
**Objetivo:** Implementar el provider de fallback de pago.  
**Archivo a crear:** `providers/opencode.py`

## Instrucciones para el agente

Implementar `OpencodeProvider` siguiendo el patrón de `ClaudeCodeProvider`:
- `priority = 10` (último recurso)
- CLI: `opencode run --model {model} --no-interactive "{prompt}"`
- Para prompts largos (>2000 chars), usar archivo temporal igual que Gemini
- Timeout: 300s planner, 180s executor

**Diferencia clave:** `opencode` puede no estar instalado en todos los sistemas. En `__init__`, verificar que el CLI existe:

```python
import shutil

class OpencodeProvider(ProviderBase):
    def __init__(self, planner_model: str = "gpt-4o", executor_model: str = "gpt-4o-mini"):
        if not shutil.which("opencode"):
            raise EnvironmentError(
                "opencode CLI no encontrado. Instalar con: npm install -g opencode-ai"
            )
        ...
```

El orchestrator debe hacer `try/except EnvironmentError` al inicializar este provider y simplemente no incluirlo si no está disponible.

## Criterio de validación del módulo 7

```python
import shutil
if shutil.which("opencode"):
    from providers.opencode import OpencodeProvider
    op = OpencodeProvider()
    assert op.priority == 10
    print("OpencodeProvider OK")
else:
    print("opencode no instalado — provider skipped (OK)")
```

---

---

# MÓDULO 8 — Classifier y Router

**Sesión estimada:** 60 min  
**Dependencias previas:** Módulo 1, Módulo 5, Módulo 6  
**Objetivo:** Implementar la clasificación de complejidad y la selección de provider con failover.  
**Archivos a crear:** `harness/classifier.py`, `harness/router.py`

## Instrucciones para el agente

### 8.1 — harness/classifier.py

Implementar exactamente como en `META_HARNESS_PLAN.md` sección "Clasificador de Complejidad", más:

1. La función `classify_complexity` recibe el contenido de `task.md` completo (no solo la descripción).
2. Si `task.md` tiene el campo `**complejidad_estimada:**` en el frontmatter, usar ese valor directamente sin aplicar heurística.

```python
def classify_complexity(task_md: str) -> str:
    """
    Primero intenta leer 'complejidad_estimada' del frontmatter del task.md.
    Si no está, aplica heurística de palabras clave.
    """
    import re
    match = re.search(r"\*\*complejidad_estimada:\*\*\s*(low|medium|high)", task_md)
    if match:
        return match.group(1)
    # ... heurística de la spec original
```

### 8.2 — harness/router.py

Implementar el `Router` de `META_HARNESS_PLAN.md`, más:

1. Leer el orden de prioridad desde `config/routing_rules.yaml` (no solo por `priority` del provider):

```python
class Router:
    def __init__(
        self,
        providers: list[ProviderBase],
        budget: BudgetManager,
        routing_config: dict,    # contenido de routing_rules.yaml
    ):
        ...

    def select(self, role: str, complexity: str = "medium") -> ProviderBase:
        """
        1. Lee routing_rules.yaml para obtener el orden preferido por complexity
        2. Filtra providers que:
           a. Soportan el role
           b. Tienen capacity según BudgetManager
           c. Están en el orden de la config
        3. Devuelve el primero disponible según ese orden
        4. Si ninguno disponible: lanza ProviderExhausted
        """
```

2. Agregar excepción específica:
```python
class ProviderExhausted(Exception):
    def __init__(self, role: str):
        super().__init__(
            f"Todos los providers para role='{role}' están agotados. "
            "Espera el reset de límites (medianoche UTC) o agrega más providers."
        )
```

## Criterio de validación del módulo 8

```python
from harness.classifier import classify_complexity

# Test con campo explícito
task_with_field = "# Mi Task\n**complejidad_estimada:** high\n## Objetivo\nRefactor total"
assert classify_complexity(task_with_field) == "high"

# Test con heurística
task_heuristic = "# Mi Task\n## Objetivo\nRefactorizar la arquitectura del sistema de múltiples módulos"
result = classify_complexity(task_heuristic)
assert result in ["low", "medium", "high"]

print(f"Classifier OK — heurística devolvió: {result}")
```

---

---

# MÓDULO 9 — Orchestrator Principal

**Sesión estimada:** 120 min  
**Dependencias previas:** Módulos 1, 4, 5, 6, 7, 8  
**Objetivo:** Implementar el coordinador central que une todos los módulos.  
**Archivo a crear:** `harness/orchestrator.py`

## Instrucciones para el agente

### Interface pública

```python
class MetaOrchestrator:
    def __init__(
        self,
        router: Router,
        budget: BudgetManager,
        session_manager: SessionManager,
    ): ...

    def run(
        self,
        task_md: str,
        force_replan: bool = False,
    ) -> TaskResult:
        """
        Flujo completo de ejecución dado un task.md ya ingresado.
        El page_id ya está en session_manager.page_id.
        """
```

### Flujo interno de run()

```python
def run(self, task_md: str, force_replan: bool = False) -> TaskResult:
    complexity = classify_complexity(task_md)

    # --- PLANNING PHASE ---
    plan = self._get_or_create_plan(task_md, complexity, force_replan)

    # --- EXECUTION PHASE ---
    pending = self.session_manager.pending_steps(plan)
    plan_summary = self._build_plan_summary(plan)
    step_results = []

    for step in plan.steps:
        if step.index not in pending:
            # Step ya completado en sesión anterior
            step_results.append(self._build_skipped_result(step))
            continue

        if not self._dependencies_met(step, step_results):
            self.session_manager.mark_step_failed(step.index, "none", 0, "dependency_failed")
            step_results.append(self._build_failed_result(step, "dependency_failed"))
            continue

        result = self._execute_with_failover(step, task_md, plan_summary, complexity)
        step_results.append(result)

        if result.status == StepStatus.completed:
            self.session_manager.mark_step_completed(step.index, result.executor_used, result.tokens_used)
        else:
            self.session_manager.mark_step_failed(step.index, result.executor_used, result.tokens_used, result.error or "")

    all_ok = all(r.status == StepStatus.completed for r in step_results
                 if r.status != StepStatus.skipped)

    if all_ok:
        self.session_manager.mark_task_completed()
    else:
        self.session_manager.mark_task_failed()

    return TaskResult(
        task_id=plan.task_id,
        notion_page_id=self.session_manager.page_id,
        plan=plan,
        step_results=step_results,
        status=TaskStatus.completed if all_ok else TaskStatus.failed,
        total_tokens=sum(r.tokens_used for r in step_results),
        total_duration_seconds=sum(r.duration_seconds for r in step_results),
    )
```

### _get_or_create_plan()

```python
def _get_or_create_plan(self, task_md: str, complexity: str, force: bool) -> TaskPlan:
    if not force:
        existing = self.session_manager.load_plan()
        if existing:
            return existing

    planner = self.router.select("planner", complexity)
    plan = planner.generate_plan(task_md)
    plan.notion_page_id = self.session_manager.page_id
    self.budget.record(planner.name, plan.estimated_tokens)
    self.session_manager.save_plan(plan)
    return plan
```

### _execute_with_failover()

Intenta con el provider seleccionado. Si falla, intenta con el siguiente disponible. Máximo 2 intentos total.

```python
def _execute_with_failover(
    self, step: Step, task_md: str, plan_summary: str, complexity: str
) -> StepResult:
    tried = []
    for attempt in range(2):
        try:
            executor = self.router.select("executor", complexity, exclude=tried)
            result = executor.execute_step(step, task_md, plan_summary)
            self.budget.record(executor.name, result.tokens_used)
            return result
        except ProviderExhausted:
            break
        except ProviderError as e:
            tried.append(e.provider)
            continue
    # Si llegamos aquí, todos fallaron
    return self._build_failed_result(step, "all_providers_failed")
```

**Agregar `exclude` al método `Router.select`:**
```python
def select(self, role: str, complexity: str = "medium", exclude: list[str] = []) -> ProviderBase:
    # Filtrar providers excluidos
    candidates = [p for p in candidates if p.name not in exclude]
    ...
```

## Criterio de validación del módulo 9

El orchestrator no puede probarse completamente sin CLIs reales. Validar estructura:

```python
# Verificar imports y estructura de clases
from harness.orchestrator import MetaOrchestrator
import inspect
sig = inspect.signature(MetaOrchestrator.run)
assert "task_md" in sig.parameters
assert "force_replan" in sig.parameters
print("MetaOrchestrator structure OK")
```

---

---

# MÓDULO 10 — CLI Entry Point

**Sesión estimada:** 60 min  
**Dependencias previas:** Módulos 2, 3, 4, 8, 9  
**Objetivo:** Conectar todos los módulos en el CLI `harness`.  
**Archivo a crear:** `main.py`

## Instrucciones para el agente

### Comandos del CLI

```bash
harness start              # Flujo completo: ingestar → planear → ejecutar
harness start --resume     # Igual, pero asume retomar sesión si existe (no pregunta)
harness start --replan     # Fuerza regenerar el plan aunque exista uno en sesión
harness status             # Muestra capacidad de cada provider
harness usage              # Muestra tokens consumidos hoy
harness sessions           # Lista sesiones existentes con su estado
```

### Flujo de harness start

```python
@app.command()
def start(
    resume: bool = typer.Option(False, "--resume"),
    replan: bool = typer.Option(False, "--replan"),
):
    # 1. Cargar config
    config = load_config()   # lee .env + providers.yaml

    # 2. INGESTA
    page_id, task_md = ingest_task(config)

    # 3. SESSION CHECK
    session = SessionManager(page_id)
    if session.exists() and not resume:
        action = show_resume_prompt(session)  # R / N / V
        if action == "N":
            session.create(task_md)  # sobreescribe task.md, borra plan y progress
        elif action == "V":
            show_plan(session.load_plan())
            action = ask_resume_or_restart()
            if action == "N":
                session.create(task_md)
    else:
        session.create(task_md)

    # 4. CONSTRUIR ORCHESTRATOR
    orchestrator = build_orchestrator(session, config)

    # 5. EJECUTAR
    result = orchestrator.run(task_md, force_replan=replan)

    # 6. MOSTRAR RESULTADO
    show_result(result)
```

### load_config()

```python
def load_config() -> dict:
    from dotenv import load_dotenv
    import os, yaml
    load_dotenv()
    providers_cfg = yaml.safe_load(Path("config/providers.yaml").read_text())
    routing_cfg = yaml.safe_load(Path("config/routing_rules.yaml").read_text())
    return {
        "notion_token": os.environ["NOTION_TOKEN"],
        "google_api_key": os.environ["GOOGLE_API_KEY"],
        "gemini_converter_model": providers_cfg["providers"]["gemini"]["models"]["converter"],
        "providers": providers_cfg,
        "routing": routing_cfg,
    }
```

### build_orchestrator()

```python
def build_orchestrator(session: SessionManager, config: dict) -> MetaOrchestrator:
    import shutil
    from providers.claude_code import ClaudeCodeProvider
    from providers.gemini import GeminiProvider
    from providers.opencode import OpencodeProvider

    pcfg = config["providers"]["providers"]
    providers = []

    if shutil.which("claude"):
        providers.append(ClaudeCodeProvider(
            planner_model=pcfg["claude_code"]["models"]["planner"],
            executor_model=pcfg["claude_code"]["models"]["executor"],
        ))

    if shutil.which("gemini"):
        providers.append(GeminiProvider(
            planner_model=pcfg["gemini"]["models"]["planner"],
            executor_model=pcfg["gemini"]["models"]["executor"],
        ))

    try:
        providers.append(OpencodeProvider(
            planner_model=pcfg["opencode"]["models"]["planner"],
            executor_model=pcfg["opencode"]["models"]["executor"],
        ))
    except EnvironmentError:
        pass   # opencode no instalado, continúa sin él

    if not providers:
        raise RuntimeError("No hay ningún provider de IA disponible. Instala claude o gemini CLI.")

    budget = load_budget_from_config("config/providers.yaml")
    router = Router(providers, budget, config["routing"])
    return MetaOrchestrator(router, budget, session)
```

### harness status

Mostrar tabla Rich con:
- Provider name
- Roles (planner / executor / ambos)
- Tokens hoy / límite diario (con barra de progreso)
- Requests hoy / límite diario
- Disponible: ✓ / ✗

### harness sessions

Listar directorios en `~/.quetz-meta-harness/sessions/`, leer progress.json de cada uno y mostrar tabla con: page_id, status, steps completados, última actividad.

## Criterio de validación del módulo 10

```bash
# Sin credenciales, debe fallar con error claro (no traceback)
cd meta-harness
python main.py --help          # Debe mostrar help con los comandos
python main.py status          # Debe mostrar tabla (posiblemente vacía) sin error
python main.py sessions        # Debe mostrar "Sin sesiones previas" o tabla
```

---

---

# MÓDULO 11 — Integración con Quetz-Orchestrator (opcional)

**Sesión estimada:** 45 min  
**Dependencias previas:** Módulos 1-10 completos y funcionando  
**Objetivo:** Conectar el meta-harness al orchestrator existente para que lo use como agente para tasks de alta complejidad.  
**Nota:** Este módulo es opcional si el harness se usa standalone.

## Instrucciones para el agente

Verificar primero si existe el proyecto quetz-orchestrator en `/home/lito/development/agents-orchestrator/orchestrator/`. Si no existe, omitir este módulo.

Si existe, crear `orchestrator/agents/meta_harness_agent.py` siguiendo la spec de `META_HARNESS_PLAN.md` sección "Integración con el Quetz-Orchestrator Existente".

Agregar a `config/agent_config.yaml` del orchestrator existente:
```yaml
meta_harness:
  class: MetaHarnessAgent
  complexity_min: high
  timeout: 600
```

---

---

# Orden de sesiones recomendado

| Sesión | Módulos | Estimado | Resultado |
|--------|---------|----------|-----------|
| 1 | 0 + 1 | 60 min | Estructura y schemas listos |
| 2 | 2 + 3 | 120 min | Ingesta Notion funcionando |
| 3 | 4 | 60 min | Session manager completo |
| 4 | 5 | 45 min | Budget manager completo |
| 5 | 6 | 120 min | Providers principales |
| 6 | 7 + 8 | 90 min | Opencode + Router/Classifier |
| 7 | 9 | 120 min | Orchestrator completo |
| 8 | 10 | 60 min | CLI funcionando end-to-end |
| 9 | 11 | 45 min | Integración (si aplica) |

**Total estimado:** ~9 horas distribuidas en 9 sesiones de trabajo.

---

# Cómo iniciar cada sesión con un agente worker

Al comenzar cada sesión, dar al agente este contexto:

```
Estás implementando el módulo {N} de quetz-meta-harness.

Archivos de referencia:
- /home/lito/development/agents-orchestrator/META_HARNESS_PLAN.md (diseño técnico)
- /home/lito/development/agents-orchestrator/IMPLEMENTATION_PLAN.md (este plan)

Módulos ya implementados: {lista de módulos previos}
Módulo actual: {N} — {nombre}

Sigue exactamente las instrucciones de la sección "MÓDULO {N}" del IMPLEMENTATION_PLAN.md.
No agregues funcionalidad extra. Valida con el criterio al final de la sección antes de terminar.
```
