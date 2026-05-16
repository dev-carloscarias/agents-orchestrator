# AI Dev Harness — Design Document v1.0

**Proyecto:** ai-harness  
**Versión:** 1.0  
**Fecha:** 2026-05-16  
**Autor:** Carlos Carias  
**Estado:** Diseño aprobado

---

## Tabla de Contenidos

1. [Visión General](#1-visión-general)
2. [Stack de Providers](#2-stack-de-providers)
3. [Arquitectura del Sistema](#3-arquitectura-del-sistema)
4. [Estructura de Directorios](#4-estructura-de-directorios)
5. [Schemas Core](#5-schemas-core)
6. [Flujo Completo del Sistema](#6-flujo-completo-del-sistema)
7. [Ingesta desde Notion](#7-ingesta-desde-notion)
8. [Clasificador de Tasks](#8-clasificador-de-tasks)
9. [Context Collector](#9-context-collector)
10. [Budget Manager](#10-budget-manager)
11. [Router con Failover Interactivo](#11-router-con-failover-interactivo)
12. [Session Manager](#12-session-manager)
13. [Diff Reporter](#13-diff-reporter)
14. [Providers](#14-providers)
15. [Orchestrator](#15-orchestrator)
16. [Consola TUI — Menús Completos](#16-consola-tui--menús-completos)
17. [Prompts Especializados](#17-prompts-especializados)
18. [Configuración](#18-configuración)
19. [Orden de Implementación](#19-orden-de-implementación)

---

## 1. Visión General

AI Harness es una herramienta de consola interactiva para orquestar agentes de IA en tareas de desarrollo de software. Toma tasks desde Notion, los convierte a un formato estándar, genera un plan con Claude Sonnet (u Opus cuando el usuario lo decide), y ejecuta cada step con Gemini Flash como agente real sobre el filesystem del proyecto — con confirmación del usuario en cada paso.

### Principios de diseño

| Principio | Descripción |
|-----------|-------------|
| **El usuario manda** | Nada se ejecuta sin confirmación explícita. El sistema propone, el usuario aprueba. |
| **Genérico** | No está atado a ningún proyecto específico. Funciona con cualquier codebase. |
| **Trazabilidad total** | Cada run guarda output, diff de archivos y logs. Se puede revisar cualquier ejecución anterior. |
| **Frugal con el límite** | Sonnet por defecto para planning. Opus solo cuando el usuario lo pide. Gemini para execution. |
| **Failover transparente** | Si un provider se agota, el sistema notifica y pregunta antes de cambiar. |
| **Privacidad explícita** | Avisa cuando activa modelos que pueden usar datos para entrenamiento. |

---

## 2. Stack de Providers

### Decisión de stack

```
PLANNER                              EXECUTOR
───────                              ────────

1. Claude Sonnet 4.6  ← DEFAULT      1. Gemini Flash 2.0  ← DEFAULT
   claude -p                            gemini CLI
   Suscripción Pro                       Free tier (1500 req/día)
   Todos los niveles de complejidad      Todos los steps

2. Claude Opus 4.6    ← MANUAL        2. OpenCode + MiniMax M2.5 Free
   Solo cuando usuario                   Fallback cuando Gemini se agota
   selecciona extra_high                 Gratis (datos pueden usarse p/training)

                                      3. OpenCode + Big Pickle
                                          Último recurso gratuito
                                          200 req / ventana de 5h
```

### Justificación

**¿Por qué Sonnet y no Opus por defecto?**  
Sonnet 4.6 tiene razonamiento suficiente para generar planes estructurados en la mayoría de tasks de desarrollo. Claude Pro tiene una ventana de 5 horas con límite de requests. Usar Opus en todo consumiría el límite mucho más rápido y no hay ganancia real en planning de tasks low/medium/high. Opus solo se justifica en tasks de refactor sistémico complejo o diseño arquitectónico mayor — y esa decisión la toma el usuario, no el sistema.

**¿Por qué Gemini como executor y no Claude?**  
Dos razones: primero, Gemini Flash es un agente real con filesystem igual que Claude — puede leer, editar y ejecutar. Segundo, sus 1500 requests diarias son completamente independientes del límite Pro de Claude. Usar Claude para planning y execution agotaría el límite Pro en horas.

**¿Por qué OpenCode con modelos free como fallback?**  
Cuando Gemini agota sus 1500 requests, OpenCode con modelos Zen gratuitos (MiniMax M2.5 Free: 80.2% en SWE-Bench) cubre el trabajo rutinario sin costo adicional. El costo es privacidad: los datos enviados a modelos free pueden usarse para entrenamiento. El sistema avisa siempre que activa estos providers.

**Nota sobre OpenCode headless:**  
OpenCode tiene un bug conocido (issue #13851 en su repositorio) donde `opencode run` puede colgar esperando confirmación de permisos al escribir archivos. Se mitiga con `--dangerously-skip-permissions` y timeout explícito en el harness.

### Tabla de providers

| Rol | CLI | Modelo | Costo | Límite real | Condición de uso |
|-----|-----|--------|-------|-------------|-----------------|
| Planner | `claude -p` | claude-sonnet-4-6 | Sub. Pro | ~80 req/5h* | Default siempre |
| Planner | `claude -p` | claude-opus-4-6 | Sub. Pro | ~20 req/5h* | Solo `extra_high` manual |
| Executor | `gemini` CLI | gemini-2.0-flash | Gratis | 1500 req/día | Default siempre |
| Executor | `opencode run` | opencode/minimax-m2-5-free | Gratis† | ~300 req/día | Cuando Gemini se agota |
| Executor | `opencode run` | opencode/big-pickle | Gratis† | 200 req/5h | Último recurso |

*Estimado conservador. Claude Pro usa ventana deslizante de 5h, no límite diario publicado.  
†Los datos enviados a modelos Free de OpenCode Zen pueden usarse para entrenar el modelo.

---

## 2. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI DEV HARNESS v1.0                         │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    CONSOLE TUI (Rich)                         │   │
│  │  MainMenu → ProjectMenu → TaskMenu → StepViewer → History   │   │
│  └─────────────────────┬────────────────────────────────────────┘   │
│                         │                                           │
│  ┌──────────────────────▼────────────────────────────────────────┐  │
│  │                     TASK PIPELINE                              │  │
│  │                                                                │  │
│  │  [NotionIngestor]                                              │  │
│  │   • Pide page URL/ID al usuario                               │  │
│  │   • Descarga página via Notion REST API                        │  │
│  │   • Extrae texto de bloques                                    │  │
│  │         │                                                      │  │
│  │         ▼                                                      │  │
│  │  [Normalizer]                                                  │  │
│  │   • Convierte raw text → task.md estándar                     │  │
│  │   • Usa Gemini Flash como converter (sin tokens de Claude)     │  │
│  │         │                                                      │  │
│  │         ▼                                                      │  │
│  │  [TaskClassifier]  ← sin tokens, heurística local             │  │
│  │   • Detecta TaskType: backend/frontend/refactor/bugfix/generic │  │
│  │   • Detecta Complexity: low/medium/high                        │  │
│  │   • Usuario puede ajustar (incluido subir a extra_high → Opus) │  │
│  │         │                                                      │  │
│  │         ▼                                                      │  │
│  │  [ContextCollector]  ← solo si complexity >= medium           │  │
│  │   • Preguntas interactivas: stack, archivos clave,             │  │
│  │     restricciones, convenciones                                │  │
│  │   • Reutiliza contexto guardado de sesiones anteriores         │  │
│  │         │                                                      │  │
│  │         ▼                                                      │  │
│  │  [Planner]  ← Claude Sonnet o Opus                            │  │
│  │   • Genera TaskPlan JSON estructurado                          │  │
│  │   • Usuario aprueba el plan antes de continuar                 │  │
│  │         │                                                      │  │
│  │         ▼                                                      │  │
│  │  [Orchestrator]  ← step-by-step con confirmación              │  │
│  │   • Por cada step: mostrar → usuario confirma → ejecutar       │  │
│  │   • Captura snapshot antes, computa diff después               │  │
│  │   • Muestra output + diff + archivos tocados                   │  │
│  │   • Guarda artefactos en sesión                                │  │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    PROVIDER LAYER                             │   │
│  │                                                               │   │
│  │  BudgetManager (token counting real + alertas 70%/85%)        │   │
│  │       │                                                       │   │
│  │  Router (notifica y pregunta antes de cambiar provider)       │   │
│  │       │                                                       │   │
│  │  ┌────┴──────────────┬──────────────────────────────────┐    │   │
│  │  │ ClaudeCodeProvider│ GeminiProvider  │ OpenCodeProvider│    │   │
│  │  │ Sonnet (planner)  │ Flash (executor)│ MiniMax/BigPkl  │    │   │
│  │  │ Opus (extra_high) │ priority=1      │ priority=2,3    │    │   │
│  │  └───────────────────┴─────────────────┴────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   SESSION STORE                               │   │
│  │  ~/.ai-harness/projects/{project}/{task}/runs/{run_id}/       │   │
│  │  • task.md, project_context.md                                │   │
│  │  • plan.json, progress.json                                   │   │
│  │  • steps/step_N_output.md, step_N_diff.patch, step_N_files   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Estructura de Directorios

```
ai-harness/
│
├── main.py                          # Entry point — lanza ConsoleApp
├── pyproject.toml
├── .env.example
│
├── console/                         # Capa de presentación (TUI con Rich)
│   ├── __init__.py
│   ├── app.py                       # ConsoleApp: loop principal
│   └── menus/
│       ├── main_menu.py             # Menú principal con panel de budget
│       ├── project_menu.py          # Seleccionar o crear proyecto
│       ├── task_menu.py             # Menú del task activo (plan + steps)
│       ├── step_viewer.py           # Vista de step: output + diff
│       ├── history_menu.py          # Historial de runs anteriores
│       └── budget_menu.py           # Detalle de uso por provider
│
├── ingestors/                       # Pluggable — cada uno produce task.md
│   ├── __init__.py
│   ├── base.py                      # IngestorBase ABC
│   └── notion.py                    # NotionIngestor (v1.0 — único ingestor)
│
├── pipeline/                        # Lógica de negocio pura (sin UI)
│   ├── __init__.py
│   ├── normalizer.py                # raw Notion text → task.md estándar
│   ├── classifier.py                # TaskType + Complexity (sin tokens)
│   ├── context_collector.py         # Recopila contexto interactivo
│   └── diff_reporter.py             # Snapshot before/after + diff unificado
│
├── harness/                         # Core del sistema
│   ├── __init__.py
│   ├── protocols.py                 # Pydantic schemas
│   ├── orchestrator.py              # Coordinator step-by-step
│   ├── budget.py                    # BudgetManager (tracking real + alertas)
│   └── router.py                    # Router con failover interactivo
│
├── providers/                       # Wrappers de CLIs
│   ├── __init__.py
│   ├── base.py                      # ProviderBase ABC + ProviderError
│   ├── claude_code.py               # ClaudeCodeProvider (planner)
│   ├── gemini.py                    # GeminiProvider (executor default)
│   └── opencode.py                  # OpenCodeProvider (executor fallback)
│
├── session/                         # Persistencia entre ejecuciones
│   ├── __init__.py
│   └── manager.py                   # SessionManager v1.0
│
└── config/
    ├── providers.yaml               # Definición de providers y límites
    ├── routing_rules.yaml           # Orden de prioridad por role/complexity
    ├── budget_alerts.yaml           # Umbrales de alerta configurables
    └── prompts/
        ├── converter.md             # Para Normalizer (Gemini Flash convierte Notion)
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

**Almacenamiento en tiempo de ejecución:**

```
~/.ai-harness/
├── usage.jsonl                         # Log de uso real por provider (append-only)
└── projects/
    └── {project-slug}/
        └── {task-slug}/
            ├── task.md                 # Task normalizado (última versión)
            ├── project_context.json    # Contexto del proyecto (reutilizable)
            ├── project_context.md      # Misma info, legible para humanos
            └── runs/
                ├── run_20260516_143022/
                │   ├── plan.json
                │   ├── progress.json
                │   └── steps/
                │       ├── step_0_output.md
                │       ├── step_0_diff.patch
                │       ├── step_0_files.json
                │       ├── step_1_output.md
                │       └── ...
                └── run_20260516_162045/
                    └── ...
```

---

## 5. Schemas Core

**Archivo:** `harness/protocols.py`

```python
from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


# ── Enums ──────────────────────────────────────────────────────────────────

class Complexity(str, Enum):
    low        = "low"
    medium     = "medium"
    high       = "high"
    extra_high = "extra_high"   # NUNCA asignado automáticamente
                                # Solo el usuario puede seleccionarlo
                                # → activa Claude Opus como planner


class TaskType(str, Enum):
    backend  = "backend"    # APIs, DB, servicios, auth
    frontend = "frontend"   # UI, componentes, estilos
    refactor = "refactor"   # reestructuración sin cambio de comportamiento
    bugfix   = "bugfix"     # corrección de error conocido
    generic  = "generic"    # no encaja en las anteriores


class StepStatus(str, Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"
    skipped   = "skipped"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    pending     = "pending"
    in_progress = "in_progress"
    completed   = "completed"
    failed      = "failed"
    cancelled   = "cancelled"


# ── Pipeline ───────────────────────────────────────────────────────────────

class TaskMeta(BaseModel):
    """Resultado del classifier — enriquece el task antes del planning."""
    task_type:                TaskType
    complexity:               Complexity
    detected_stack:           list[str]   = Field(default_factory=list)
    needs_context_collection: bool        = False
    # True cuando complexity es medium, high o extra_high


class ProjectContext(BaseModel):
    """
    Contexto del proyecto recopilado interactivamente.
    Se persiste en project_context.json para reutilizar en runs futuros.
    Solo se recopila cuando complexity >= medium.
    """
    project_name: str
    stack:        list[str]
    key_files:    list[str]
    constraints:  list[str]
    conventions:  list[str]
    collected_at: datetime = Field(default_factory=datetime.utcnow)


# ── Plan ───────────────────────────────────────────────────────────────────

class Step(BaseModel):
    index:            int
    description:      str
    target_files:     list[str]
    validation:       str          # criterio verificable de éxito
    expected_output:  str
    depends_on:       list[int] = Field(default_factory=list)
    estimated_tokens: int = 0


class TaskPlan(BaseModel):
    plan_id:       str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type:     TaskType
    complexity:    Complexity
    summary:       str
    steps:         list[Step]
    context_files: list[str] = Field(default_factory=list)
    planner_used:  str
    planner_model: str
    created_at:    datetime = Field(default_factory=datetime.utcnow)


# ── Ejecución ──────────────────────────────────────────────────────────────

class FileChange(BaseModel):
    path:       str
    action:     str    # "created" | "modified" | "deleted"
    diff_lines: int


class StepResult(BaseModel):
    step_index:       int
    status:           StepStatus
    output:           str
    files_changed:    list[FileChange] = Field(default_factory=list)
    diff_patch:       Optional[str]    = None
    tokens_used:      int              = 0
    executor_used:    str
    provider_model:   str
    duration_seconds: float
    error:            Optional[str]    = None
    user_notes:       Optional[str]    = None


class TaskResult(BaseModel):
    run_id:                str
    project_name:          str
    task_slug:             str
    plan:                  TaskPlan
    step_results:          list[StepResult]
    status:                TaskStatus
    total_tokens:          int
    total_duration_seconds: float
    completed_at:          datetime = Field(default_factory=datetime.utcnow)


# ── Sesión ─────────────────────────────────────────────────────────────────

class RunProgress(BaseModel):
    """Estado de un run en curso — persiste en progress.json."""
    run_id:     str
    plan_id:    str
    started_at: datetime
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status:     TaskStatus = TaskStatus.pending
    steps:      dict[str, dict] = Field(default_factory=dict)
    # key: str(step_index)
    # value: {status, executor, tokens, error, files_changed}
```

---

## 6. Flujo Completo del Sistema

Este es el flujo de extremo a extremo desde que el usuario lanza el harness hasta que se completa un task.

```
Usuario ejecuta: python main.py
        │
        ▼
[ConsoleApp.run()]
        │
        ▼
[MainMenu] — muestra panel de budget + opciones
        │
        ├─ [1] Nuevo task
        │         │
        │         ▼
        │   [ProjectMenu.select_or_create()]
        │         │ usuario elige proyecto activo o crea uno nuevo
        │         ▼
        │   [NotionIngestor.ingest()]
        │         │ pide URL o ID de página Notion
        │         │ descarga y extrae texto de bloques
        │         ▼
        │   [Normalizer.convert()]
        │         │ Gemini Flash convierte texto → task.md estándar
        │         │ muestra preview y pide confirmación
        │         ▼
        │   [SessionManager.check()]
        │         │
        │         ├─ Sesión nueva → SessionManager.save_task()
        │         │
        │         └─ Sesión existente → mostrar historial
        │                   │ usuario elige: retomar / nuevo run / ver historial
        │         ▼
        │   [TaskClassifier.classify()]
        │         │ detecta TaskType y Complexity (sin tokens)
        │         │
        │         ▼
        │   [ComplexityConfirmationMenu]
        │         │ muestra clasificación detectada
        │         │ usuario confirma o ajusta
        │         │ si elige extra_high → avisa impacto en budget de Opus
        │         ▼
        │   [ContextCollector.collect()]  ← solo si complexity >= medium
        │         │ si existe contexto guardado → pregunta si reutilizar
        │         │ si no → preguntas interactivas: stack, archivos, restricciones, convenciones
        │         │ guarda en project_context.json
        │         ▼
        │   [Planner → Router.select("planner")]
        │         │ selecciona Claude Sonnet (o Opus si extra_high)
        │         │ genera TaskPlan JSON
        │         │ BudgetManager.record() con tokens reales
        │         ▼
        │   [PlanApprovalMenu]
        │         │ muestra el plan completo con todos los steps
        │         │ usuario aprueba, rechaza o pide regenerar
        │         ▼
        │   [SessionManager.start_new_run()]
        │         │ crea directorio del run, guarda plan.json
        │         ▼
        │   [Orchestrator.execute_steps()]
        │         │
        │         └─ Por cada step pendiente:
        │                   │
        │                   ▼
        │             [StepMenu]
        │                   │ muestra descripción, archivos, validación
        │                   │ usuario elige: Ejecutar / Saltar / Cancelar todo
        │                   ▼
        │             [DiffReporter.capture_snapshot()] ← antes
        │                   ▼
        │             [Router.select_with_failover("executor")]
        │                   │ selecciona Gemini Flash
        │                   │ si agotado → notifica + pregunta → MiniMax
        │                   │ si agotado → notifica + pregunta → Big Pickle
        │                   ▼
        │             [Executor.execute_step()]
        │                   │ llama al CLI con prompt completo
        │                   │ timeout controlado
        │                   ▼
        │             [DiffReporter.compute_diff()] ← después
        │                   ▼
        │             [StepResultViewer]
        │                   │ muestra output + diff + archivos tocados
        │                   │ usuario puede agregar notas
        │                   ▼
        │             [SessionManager.mark_step_completed/failed()]
        │                   │ guarda artefactos: output.md, diff.patch, files.json
        │                   │
        │                   └─ si step falló → preguntar: continuar / retry / cancelar
        │         ▼
        │   [SessionManager.mark_run_completed/failed()]
        │         ▼
        │   [RunSummaryView]
        │         │ resumen final: steps ok/fail, tokens totales, tiempo
        │         ▼
        │   [MainMenu]
        │
        ├─ [2] Retomar task incompleto → selecciona proyecto/task/run
        ├─ [3] Ver historial → navega runs anteriores
        ├─ [4] Budget y uso → detalle por provider con alertas
        ├─ [5] Cambiar proyecto
        └─ [Q] Salir
```

---

## 7. Ingesta desde Notion

**Archivo:** `ingestors/notion.py`

### Flujo de ingesta

```
Usuario pega URL o ID de página Notion
        │
        ▼
parse_page_id(url_or_id)
        │ normaliza a 32 chars hex sin guiones
        ▼
NotionClient.get_page(page_id)
        │ GET /v1/pages/{page_id}
        │ extrae: título, id, url
        ▼
NotionClient.get_blocks(page_id)
        │ GET /v1/blocks/{page_id}/children?page_size=100
        │ maneja paginación con next_cursor
        ▼
NotionClient.extract_text(blocks)
        │ convierte bloques a texto plano
        ▼
Normalizer.convert(raw_text, page_id, page_url, title)
        │ Gemini Flash: texto crudo → task.md estándar
        ▼
Preview + confirmación del usuario
```

### Implementación: NotionClient

```python
# ingestors/notion.py

import httpx
from typing import Optional

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    pass


def parse_page_id(url_or_id: str) -> str:
    """
    Acepta:
      - ID limpio:     "abc123def456abc123def456abc123de"  (32 hex)
      - ID con guiones:"abc123de-f456-abc1-23de-f456abc123de"
      - URL de Notion: "https://notion.so/workspace/Title-abc123def456abc123def456abc1234d"
    Devuelve siempre el ID de 32 chars hex sin guiones.
    Lanza ValueError si no puede extraer un ID válido.
    """
    import re
    # Quitar guiones primero
    cleaned = url_or_id.replace("-", "")
    # Buscar 32 chars hex en cualquier posición
    match = re.search(r"[0-9a-f]{32}", cleaned.lower())
    if not match:
        raise ValueError(
            f"No se pudo extraer un Notion page ID válido de: {url_or_id!r}\n"
            "Asegúrate de pegar la URL completa de Notion o el ID de 32 caracteres."
        )
    return match.group(0)


class NotionClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization":  f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        }

    def get_page(self, page_id: str) -> dict:
        """Retorna metadata de la página: id, url, título."""
        url = f"{BASE_URL}/pages/{page_id}"
        with httpx.Client() as client:
            resp = client.get(url, headers=self._headers, timeout=15)
        if resp.status_code != 200:
            raise NotionError(
                f"Error al obtener página {page_id}: "
                f"HTTP {resp.status_code} — {resp.text[:300]}"
            )
        data = resp.json()
        # Extraer título de las properties
        title = ""
        props = data.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                rich = prop.get("title", [])
                title = "".join(r.get("plain_text", "") for r in rich)
                break
        return {
            "id":    data["id"].replace("-", ""),
            "url":   data["url"],
            "title": title,
        }

    def get_blocks(self, page_id: str) -> list[dict]:
        """Descarga todos los bloques de la página, manejando paginación."""
        blocks   = []
        url      = f"{BASE_URL}/blocks/{page_id}/children"
        params   = {"page_size": 100}
        with httpx.Client() as client:
            while True:
                resp = client.get(url, headers=self._headers, params=params, timeout=15)
                if resp.status_code != 200:
                    raise NotionError(f"Error obteniendo bloques: HTTP {resp.status_code}")
                data = resp.json()
                blocks.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                params["start_cursor"] = data["next_cursor"]
        return blocks

    def extract_text(self, blocks: list[dict]) -> str:
        """
        Convierte lista de bloques Notion a texto plano.
        Tipos soportados:
          paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item,
          code, to_do, quote, divider, callout
        Tipos ignorados: image, video, file, embed, bookmark, etc.
        """
        lines   = []
        counters: dict[str, int] = {}

        for block in blocks:
            btype = block.get("type", "")
            data  = block.get(btype, {})

            if btype in ("paragraph", "heading_1", "heading_2", "heading_3"):
                text = self._rich_text(data.get("rich_text", []))
                if btype == "heading_1":
                    lines.append(f"# {text}")
                elif btype == "heading_2":
                    lines.append(f"## {text}")
                elif btype == "heading_3":
                    lines.append(f"### {text}")
                else:
                    lines.append(text)

            elif btype == "bulleted_list_item":
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"- {text}")

            elif btype == "numbered_list_item":
                n = counters.get("numbered", 0) + 1
                counters["numbered"] = n
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"{n}. {text}")

            elif btype == "to_do":
                checked = data.get("checked", False)
                text = self._rich_text(data.get("rich_text", []))
                prefix = "- [x]" if checked else "- [ ]"
                lines.append(f"{prefix} {text}")

            elif btype == "code":
                lang = data.get("language", "")
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"```{lang}\n{text}\n```")

            elif btype == "quote":
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"> {text}")

            elif btype == "callout":
                icon = data.get("icon", {}).get("emoji", "📌")
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"{icon} {text}")

            elif btype == "divider":
                lines.append("---")

            else:
                # Ignorar tipos no soportados sin error
                pass

            # Reset contador numbered si el bloque no es numbered_list_item
            if btype != "numbered_list_item":
                counters["numbered"] = 0

        return "\n".join(lines)

    @staticmethod
    def _rich_text(rich_text: list[dict]) -> str:
        return "".join(rt.get("plain_text", "") for rt in rich_text)
```

### Implementación: Normalizer (Gemini Flash como converter)

```python
# pipeline/normalizer.py

import httpx
from pathlib import Path
from datetime import datetime


class Normalizer:
    """
    Convierte texto crudo de Notion al formato task.md estándar.
    Usa Gemini Flash como LLM converter (no consume tokens de Claude).
    """
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model   = model
        self._system = (Path("config/prompts/converter.md")).read_text(encoding="utf-8")

    def convert(
        self,
        raw_text:   str,
        page_id:    str,
        page_url:   str,
        page_title: str,
    ) -> str:
        """
        Llama a Gemini Flash y devuelve el task.md normalizado.
        """
        user_content = (
            f"page_id: {page_id}\n"
            f"page_url: {page_url}\n"
            f"page_title: {page_title}\n"
            f"fecha_ingesta: {datetime.utcnow().isoformat()}\n\n"
            f"---\n\n{raw_text}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": self._system}]},
            "contents": [{
                "role": "user",
                "parts": [{"text": user_content}],
            }],
            "generationConfig": {
                "temperature": 0.1,   # baja temperatura para output determinístico
                "maxOutputTokens": 2048,
            },
        }
        url = self.GEMINI_URL.format(model=self.model)
        with httpx.Client() as client:
            resp = client.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
```

### Formato estándar task.md

Todo task ingresado desde Notion se convierte a este formato exacto. Es el contrato entre el ingestor y el orchestrator:

```markdown
# {título de la página Notion}

**notion_id:** {page_id}
**notion_url:** {url}
**task_type:** backend | frontend | refactor | bugfix | generic
**complejidad_estimada:** low | medium | high
**fecha_ingesta:** {ISO datetime}

## Objetivo
{Descripción clara de qué se debe lograr. 2-5 oraciones.}

## Contexto
{Información de fondo relevante. Decisiones previas, restricciones técnicas, etc.}

## Criterios de Aceptación
- {criterio 1 — verificable y específico}
- {criterio 2}
- {criterio N}

## Archivos Relevantes
- `{ruta/al/archivo.ext}` — {por qué es relevante}

## Notas Adicionales
{Cualquier otra información del documento Notion que no encaje en las secciones anteriores.}
```

**Reglas del converter:**
- Si una sección no tiene información, se omite completamente (no se pone "N/A")
- No inventar información que no esté en el documento original
- `task_type` y `complejidad_estimada` son sugerencias del modelo — el classifier local los puede sobreescribir con su heurística

---

## 8. Clasificador de Tasks

**Archivo:** `pipeline/classifier.py`

El classifier determina `TaskType` y `Complexity` **sin consumir tokens**. Usa señales del texto del task.md para evitar llamadas innecesarias al LLM.

```python
import re
from harness.protocols import TaskType, Complexity, TaskMeta

# ── Señales por tipo de task ──────────────────────────────────────────────

BACKEND_SIGNALS = [
    r"\bapi\b", r"\bendpoint\b", r"\bdatabase\b", r"\bdb\b", r"\bsql\b",
    r"\bauth\b", r"\btoken\b", r"\bjwt\b", r"\bmiddleware\b", r"\bservicio\b",
    r"\brepository\b", r"\bsupabase\b", r"\bpostgres\b", r"\bdocker\b",
    r"\bmigración\b", r"\bschema\b", r"\bcrud\b", r"\bbackend\b",
    r"\bwebhook\b", r"\bcache\b", r"\bqueue\b",
]

FRONTEND_SIGNALS = [
    r"\bui\b", r"\bcomponente\b", r"\bpantalla\b", r"\bwidget\b",
    r"\bestilo\b", r"\bcss\b", r"\blayout\b", r"\bnavegación\b",
    r"\bflutter\b", r"\breact\b", r"\bvue\b", r"\banimación\b",
    r"\bformulario\b", r"\bresponsive\b", r"\bfrontend\b",
    r"\btema\b", r"\bcolores?\b", r"\btipografía\b",
]

REFACTOR_SIGNALS = [
    r"\brefactor\b", r"\breestructur\w+\b", r"\bmigra\w+\b",
    r"\barquitectura\b", r"\bclean architecture\b", r"\bpattern\b",
    r"\bextrae\b", r"\bsepara\b", r"\bmodulariz\w+\b",
    r"\babstrae\b", r"\bdesacopla\b",
]

BUGFIX_SIGNALS = [
    r"\bfix\b", r"\bbug\b", r"\berror\b", r"\bexception\b",
    r"\bcrash\b", r"\bstack trace\b", r"\bfalla\b", r"\bno funciona\b",
    r"\breproduc\w+\b", r"\bregresión\b", r"\bnull pointer\b",
    r"\bthrowing\b", r"\bthrows\b",
]

# ── Señales de complejidad ────────────────────────────────────────────────
# extra_high NUNCA se asigna automáticamente — solo el usuario puede hacerlo

HIGH_SIGNALS = [
    r"\brefactor\b", r"\barquitectura\b", r"\bmúltiples módulos\b",
    r"\bdiseño del sistema\b", r"\bmigra\w+\b", r"\breestructur\w+\b",
    r"\bintegra\w+\b", r"\bdependencias\b", r"\bsistema completo\b",
]

LOW_SIGNALS = [
    r"\bfix\b", r"\bcorrige\b", r"\btipo\b", r"\brenombra\b",
    r"\bagrega un método\b", r"\bcomenta\b", r"\bdocumenta\b",
    r"\bcambia el color\b", r"\bactualiza el texto\b", r"\btypo\b",
]

# ── Stack hints para detectar tecnologías ────────────────────────────────

STACK_HINTS = {
    "Flutter":    [r"\bflutter\b", r"\bdart\b", r"\bwidget\b", r"\bcubit\b", r"\bbloc\b"],
    "React":      [r"\breact\b", r"\bjsx\b", r"\bhooks?\b"],
    "Supabase":   [r"\bsupabase\b", r"\brls\b", r"\bedge function\b"],
    "ASP.NET":    [r"\basp\.net\b", r"\bc#\b", r"\b\.net\b", r"\bcontroller\b"],
    "PostgreSQL": [r"\bpostgres\b", r"\bpsql\b"],
    "Docker":     [r"\bdocker\b", r"\bcontainer\b", r"\bcompose\b"],
    "FastAPI":    [r"\bfastapi\b", r"\bpydantic\b"],
    "Next.js":    [r"\bnext\.js\b", r"\bnextjs\b", r"\bapp router\b"],
}


def classify_task(task_md: str) -> TaskMeta:
    """
    Clasifica el task sin consumir tokens.

    Prioridad para tipo:
      1. Campo explícito **task_type:** en task.md → usa ese valor
      2. Heurística de señales → mayor score gana
      3. Empate o sin señales → generic

    Prioridad para complejidad:
      1. Campo explícito **complejidad_estimada:** en task.md → usa ese valor
      2. Heurística de señales
      3. Sin señales claras → medium

    IMPORTANTE: extra_high NUNCA se asigna aquí.
    Solo se puede asignar desde el menú de confirmación.
    """
    text = task_md.lower()

    # Intentar leer campos explícitos del frontmatter
    task_type_raw  = _read_field(task_md, "task_type")
    complexity_raw = _read_field(task_md, "complejidad_estimada")

    # Tipo de task
    if task_type_raw and task_type_raw in TaskType.__members__:
        task_type = TaskType(task_type_raw)
    else:
        scores = {
            TaskType.bugfix:   _count(text, BUGFIX_SIGNALS),
            TaskType.refactor: _count(text, REFACTOR_SIGNALS),
            TaskType.backend:  _count(text, BACKEND_SIGNALS),
            TaskType.frontend: _count(text, FRONTEND_SIGNALS),
        }
        best_type, best_score = max(scores.items(), key=lambda x: x[1])
        task_type = best_type if best_score > 0 else TaskType.generic

    # Complejidad (solo low/medium/high — nunca extra_high automáticamente)
    if complexity_raw and complexity_raw in ("low", "medium", "high"):
        complexity = Complexity(complexity_raw)
    else:
        high_score = _count(text, HIGH_SIGNALS)
        low_score  = _count(text, LOW_SIGNALS)
        if high_score >= 2:
            complexity = Complexity.high
        elif low_score >= 2:
            complexity = Complexity.low
        else:
            complexity = Complexity.medium

    # Stack detectado
    detected_stack = [
        tech for tech, patterns in STACK_HINTS.items()
        if any(re.search(p, text) for p in patterns)
    ]

    return TaskMeta(
        task_type=task_type,
        complexity=complexity,
        detected_stack=detected_stack,
        needs_context_collection=(complexity != Complexity.low),
    )


def _count(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if re.search(p, text))


def _read_field(task_md: str, field: str) -> str | None:
    match = re.search(rf"\*\*{field}:\*\*\s*(\w+)", task_md)
    return match.group(1).lower() if match else None
```

---

## 9. Context Collector

**Archivo:** `pipeline/context_collector.py`

Solo se activa cuando `complexity >= medium`. Si existe un `project_context.json` guardado de una sesión anterior, lo muestra y pregunta si reutilizarlo.

```python
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
```

---

## 10. Budget Manager

**Archivo:** `harness/budget.py`

Tracking real de uso con `tiktoken`. Alertas configurables por provider. Maneja dos tipos de ventana: diaria y rolling de N horas.

```python
import json, time
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional, Literal
from collections import deque
from rich.console import Console

USAGE_FILE = Path.home() / ".ai-harness" / "usage.jsonl"
console    = Console()

_tiktoken_warned = False


def count_tokens(text: str) -> int:
    """Token counting real. Fallback a len//4 si tiktoken no está instalado."""
    global _tiktoken_warned
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        if not _tiktoken_warned:
            console.print(
                "[yellow]⚠  tiktoken no instalado — token counting aproximado. "
                "Instala con: pip install tiktoken[/yellow]"
            )
            _tiktoken_warned = True
        return len(text) // 4


@dataclass
class ProviderLimits:
    window_type:  Literal["daily", "rolling"] = "daily"
    window_hours: int   = 24       # para rolling: tamaño de la ventana
    max_requests: Optional[int] = None
    max_tokens:   Optional[int] = None
    warn_at:      float = 0.70
    critical_at:  float = 0.85


# Límites por provider
PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    "claude_sonnet": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=80,       # estimado conservador para Pro
        warn_at=0.60, critical_at=0.80,
    ),
    "claude_opus": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=20,
        warn_at=0.50, critical_at=0.70,
    ),
    "gemini_flash": ProviderLimits(
        window_type="daily",
        max_requests=1500,
        warn_at=0.75, critical_at=0.90,
    ),
    "opencode_minimax": ProviderLimits(
        window_type="daily",
        max_requests=300,      # estimado — no publicado oficialmente
        warn_at=0.80, critical_at=0.95,
    ),
    "opencode_bigpickle": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=200,
        warn_at=0.75, critical_at=0.90,
    ),
}


@dataclass
class ProviderUsage:
    provider:        str
    tokens_today:    int   = 0
    requests_today:  int   = 0
    tokens_month:    int   = 0
    # Para ventanas rolling: timestamps de requests recientes
    request_times:   list  = None

    def __post_init__(self):
        if self.request_times is None:
            self.request_times = []


class BudgetManager:
    def __init__(self):
        self._usage: dict[str, ProviderUsage] = {}
        self._load_today()

    def record(self, provider: str, prompt: str, response: str, requests: int = 1) -> int:
        """
        Registra uso real. Devuelve tokens contados.
        """
        tokens = count_tokens(prompt + response)
        usage  = self._usage.setdefault(provider, ProviderUsage(provider))
        usage.tokens_today   += tokens
        usage.tokens_month   += tokens
        usage.requests_today += requests
        usage.request_times.append(time.time())
        self._append_log(provider, tokens, requests)
        self._check_alert(provider, usage)
        return tokens

    def has_capacity(self, provider: str) -> bool:
        limits = PROVIDER_LIMITS.get(provider)
        if not limits:
            return True
        usage = self._usage.get(provider, ProviderUsage(provider))

        if limits.window_type == "rolling":
            # Contar requests dentro de la ventana
            cutoff  = time.time() - limits.window_hours * 3600
            recent  = sum(1 for t in usage.request_times if t > cutoff)
            if limits.max_requests and recent >= limits.max_requests * limits.critical_at:
                return False
        else:
            if limits.max_requests and usage.requests_today >= limits.max_requests * limits.critical_at:
                return False
            if limits.max_tokens and usage.tokens_today >= limits.max_tokens * limits.critical_at:
                return False
        return True

    def alert_level(self, provider: str) -> str:
        """Retorna: "ok" | "warn" | "critical" """
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return "ok"
        usage = self._usage.get(provider, ProviderUsage(provider))

        if limits.window_type == "rolling":
            cutoff = time.time() - limits.window_hours * 3600
            count  = sum(1 for t in usage.request_times if t > cutoff)
        else:
            count = usage.requests_today

        ratio = count / limits.max_requests
        if ratio >= limits.critical_at:
            return "critical"
        if ratio >= limits.warn_at:
            return "warn"
        return "ok"

    def daily_summary(self) -> dict[str, dict]:
        summary = {}
        for provider in list(PROVIDER_LIMITS.keys()):
            limits = PROVIDER_LIMITS[provider]
            usage  = self._usage.get(provider, ProviderUsage(provider))

            if limits.window_type == "rolling":
                cutoff  = time.time() - limits.window_hours * 3600
                req_now = sum(1 for t in usage.request_times if t > cutoff)
                req_max = limits.max_requests
            else:
                req_now = usage.requests_today
                req_max = limits.max_requests

            summary[provider] = {
                "requests_now":  req_now,
                "requests_max":  req_max,
                "tokens_today":  usage.tokens_today,
                "pct":           round(req_now / req_max * 100, 1) if req_max else None,
                "alert_level":   self.alert_level(provider),
                "window_type":   limits.window_type,
                "window_hours":  limits.window_hours,
            }
        return summary

    def projected_exhaustion(self, provider: str) -> Optional[str]:
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return None
        usage = self._usage.get(provider, ProviderUsage(provider))
        hour  = max(datetime.utcnow().hour, 1)
        rate  = usage.requests_today / hour
        if rate == 0:
            return None
        remaining = limits.max_requests - usage.requests_today
        return f"~{remaining / rate:.1f}h"

    def _check_alert(self, provider: str, usage: ProviderUsage):
        level  = self.alert_level(provider)
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return
        pct = usage.requests_today / limits.max_requests * 100
        if level == "critical":
            console.print(
                f"\n[bold red]🚨 [{provider}] {pct:.0f}% del límite consumido[/bold red]"
            )
        elif level == "warn":
            console.print(
                f"\n[yellow]⚠  [{provider}] {pct:.0f}% del límite consumido[/yellow]"
            )

    def _append_log(self, provider: str, tokens: int, requests: int):
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("a") as f:
            f.write(json.dumps({
                "ts":       datetime.utcnow().isoformat(),
                "date":     date.today().isoformat(),
                "provider": provider,
                "tokens":   tokens,
                "requests": requests,
            }) + "\n")

    def _load_today(self):
        if not USAGE_FILE.exists():
            return
        today = date.today().isoformat()
        for line in USAGE_FILE.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry["date"] == today:
                    p = entry["provider"]
                    u = self._usage.setdefault(p, ProviderUsage(p))
                    u.tokens_today   += entry.get("tokens", 0)
                    u.requests_today += entry.get("requests", 0)
                    u.tokens_month   += entry.get("tokens", 0)
            except (json.JSONDecodeError, KeyError):
                continue
```

---

## 11. Router con Failover Interactivo

**Archivo:** `harness/router.py`

El router nunca cambia de provider silenciosamente. Notifica al usuario y pregunta antes de cada cambio.

```python
from rich.console import Console
from rich.prompt import Confirm
from harness.budget import BudgetManager
from providers.base import ProviderBase, ProviderError
import yaml
from pathlib import Path

console = Console()


class ProviderExhausted(Exception):
    def __init__(self, role: str):
        super().__init__(
            f"Todos los providers para '{role}' están agotados o fueron rechazados.\n"
            "Opciones: esperar reset de límites (medianoche UTC) o revisar el menú de Budget."
        )


class Router:
    def __init__(
        self,
        providers:      list[ProviderBase],
        budget:         BudgetManager,
        routing_config: dict,
    ):
        self.providers      = {p.name: p for p in providers}
        self.budget         = budget
        self.routing_config = routing_config

    def select(
        self,
        role:       str,
        complexity: str = "medium",
        exclude:    list[str] = [],
    ) -> ProviderBase:
        """
        Selecciona el mejor provider disponible.
        Si el ideal no tiene capacity, NOTIFICA y PREGUNTA antes de cambiar.
        """
        order = self.routing_config["routing"][role].get(complexity, [])
        candidates = [
            self.providers[name]
            for name in order
            if name in self.providers and name not in exclude
        ]

        for candidate in candidates:
            if self.budget.has_capacity(candidate.name):
                return candidate

            # No tiene capacity — notificar y preguntar
            alert = self.budget.alert_level(candidate.name)
            summary = self.budget.daily_summary().get(candidate.name, {})
            pct = summary.get("pct", "?")

            console.print(
                f"\n[yellow]⚠  [{candidate.name}] sin capacidad disponible "
                f"({pct}% del límite).[/yellow]"
            )

            # Encontrar siguiente disponible para mostrarle al usuario
            next_available = next(
                (self.providers[n].name for n in order
                 if n in self.providers
                 and n not in exclude
                 and n != candidate.name
                 and self.budget.has_capacity(self.providers[n].name)),
                None,
            )

            if not next_available:
                raise ProviderExhausted(role)

            # Si el siguiente es un modelo free de OpenCode → aviso de privacidad
            if "opencode" in next_available:
                console.print(
                    f"  [yellow]⚠  AVISO DE PRIVACIDAD:[/yellow] "
                    f"[dim]{next_available} es un modelo free de OpenCode Zen. "
                    f"Los datos enviados pueden usarse para entrenamiento del modelo.[/dim]"
                )

            console.print(f"  Siguiente disponible: [cyan]{next_available}[/cyan]")
            if not Confirm.ask(f"¿Continuar con {next_available}?", default=True):
                raise ProviderExhausted(role)

        raise ProviderExhausted(role)

    def select_with_failover(
        self,
        role:       str,
        complexity: str,
        tried:      list[str] = [],
    ) -> ProviderBase:
        """Versión usada durante ejecución de steps — permite excluir providers ya intentados."""
        return self.select(role, complexity, exclude=tried)

    def status(self) -> dict:
        return {
            name: {
                "has_capacity":  self.budget.has_capacity(name),
                "alert_level":   self.budget.alert_level(name),
                "summary":       self.budget.daily_summary().get(name, {}),
            }
            for name in self.providers
        }


def build_router_from_config(
    providers: list[ProviderBase],
    budget:    BudgetManager,
) -> Router:
    config = yaml.safe_load(Path("config/routing_rules.yaml").read_text())
    return Router(providers, budget, config)
```

---

## 12. Session Manager

**Archivo:** `session/manager.py`

Identifica sesiones por `{project-slug}/{task-slug}`. Guarda historial completo de runs con opción de limpiar.

```python
from pathlib import Path
from harness.protocols import TaskPlan, RunProgress, TaskStatus, ProjectContext
from datetime import datetime
import json, re, shutil

SESSIONS_ROOT = Path.home() / ".ai-harness" / "projects"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60]


class SessionManager:
    def __init__(self, project_name: str, task_name: str):
        self.project_name  = project_name
        self.task_slug     = slugify(task_name)
        self.project_slug  = slugify(project_name)
        self.task_dir      = SESSIONS_ROOT / self.project_slug / self.task_slug
        self.runs_dir      = self.task_dir / "runs"
        self._current_run: Path | None = None

    # ── Paths ──────────────────────────────────────────────────────────────

    @property
    def task_file(self)    -> Path: return self.task_dir / "task.md"
    @property
    def ctx_json(self)     -> Path: return self.task_dir / "project_context.json"
    @property
    def ctx_md(self)       -> Path: return self.task_dir / "project_context.md"

    # ── Estado ────────────────────────────────────────────────────────────

    def task_exists(self) -> bool:
        return self.task_file.exists()

    def list_runs(self) -> list[dict]:
        """Retorna runs anteriores (más reciente primero)."""
        if not self.runs_dir.exists():
            return []
        runs = []
        for run_dir in sorted(self.runs_dir.iterdir(), reverse=True):
            pf = run_dir / "progress.json"
            if pf.exists():
                try:
                    prog = RunProgress(**json.loads(pf.read_text()))
                    steps = list(prog.steps.values())
                    runs.append({
                        "run_id":     prog.run_id,
                        "status":     prog.status,
                        "steps_ok":   sum(1 for s in steps if s.get("status") == "completed"),
                        "steps_fail": sum(1 for s in steps if s.get("status") == "failed"),
                        "updated_at": prog.updated_at,
                        "run_dir":    run_dir,
                    })
                except Exception:
                    continue
        return runs

    def has_incomplete_run(self) -> bool:
        return any(
            r["status"] not in ("completed", "cancelled")
            for r in self.list_runs()
        )

    # ── Task y contexto ───────────────────────────────────────────────────

    def save_task(self, task_md: str):
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.task_file.write_text(task_md, encoding="utf-8")

    def load_task(self) -> str:
        return self.task_file.read_text(encoding="utf-8")

    def save_project_context(self, context: ProjectContext):
        self.ctx_json.write_text(context.model_dump_json(indent=2), encoding="utf-8")
        self.ctx_md.write_text(_context_to_md(context), encoding="utf-8")

    def load_project_context(self) -> ProjectContext | None:
        if self.ctx_json.exists():
            try:
                return ProjectContext(**json.loads(self.ctx_json.read_text()))
            except Exception:
                return None
        return None

    # ── Runs ──────────────────────────────────────────────────────────────

    def start_new_run(self, plan: TaskPlan) -> str:
        run_id  = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        run_dir = self.runs_dir / run_id
        (run_dir / "steps").mkdir(parents=True, exist_ok=True)
        self._current_run = run_dir

        (run_dir / "plan.json").write_text(plan.model_dump_json(indent=2))

        progress = RunProgress(
            run_id=run_id,
            plan_id=plan.plan_id,
            started_at=datetime.utcnow(),
            steps={str(s.index): {"status": "pending"} for s in plan.steps},
        )
        self._save_progress(progress)
        return run_id

    def resume_latest_run(self) -> tuple[TaskPlan | None, RunProgress | None]:
        runs = [r for r in self.list_runs() if r["status"] not in ("completed", "cancelled")]
        if not runs:
            return None, None
        run_dir = runs[0]["run_dir"]
        self._current_run = run_dir
        plan     = TaskPlan(**json.loads((run_dir / "plan.json").read_text()))
        progress = RunProgress(**json.loads((run_dir / "progress.json").read_text()))
        return plan, progress

    def pending_steps(self, plan: TaskPlan, progress: RunProgress) -> list[int]:
        completed = {
            int(idx) for idx, s in progress.steps.items()
            if s.get("status") == "completed"
        }
        return [s.index for s in plan.steps if s.index not in completed]

    def mark_step_completed(self, step_index: int, executor: str, tokens: int, files: int):
        self._update_step(step_index, "completed", {
            "executor": executor, "tokens": tokens, "files_changed": files,
        })

    def mark_step_failed(self, step_index: int, executor: str, error: str):
        self._update_step(step_index, "failed", {"executor": executor, "error": error})

    def mark_step_skipped(self, step_index: int):
        self._update_step(step_index, "skipped", {})

    def mark_step_cancelled(self, step_index: int):
        self._update_step(step_index, "cancelled", {})

    def save_step_artifacts(self, step_index: int, output: str, diff: str | None, files: list[dict]):
        if not self._current_run:
            return
        d = self._current_run / "steps"
        (d / f"step_{step_index}_output.md").write_text(output, encoding="utf-8")
        if diff:
            (d / f"step_{step_index}_diff.patch").write_text(diff, encoding="utf-8")
        (d / f"step_{step_index}_files.json").write_text(json.dumps(files, indent=2))

    def mark_run_completed(self): self._update_run_status("completed")
    def mark_run_failed(self):    self._update_run_status("failed")
    def mark_run_cancelled(self): self._update_run_status("cancelled")

    def clear_history(self):
        """Borra todos los runs. El task.md y contexto se conservan."""
        if self.runs_dir.exists():
            shutil.rmtree(self.runs_dir)

    # ── Privados ──────────────────────────────────────────────────────────

    def _update_step(self, index: int, status: str, data: dict):
        if not self._current_run:
            return
        pf   = self._current_run / "progress.json"
        prog = RunProgress(**json.loads(pf.read_text()))
        prog.steps[str(index)] = {"status": status, **data}
        prog.updated_at        = datetime.utcnow()
        prog.status            = TaskStatus.in_progress
        self._save_progress(prog)

    def _update_run_status(self, status: str):
        if not self._current_run:
            return
        pf   = self._current_run / "progress.json"
        prog = RunProgress(**json.loads(pf.read_text()))
        prog.status     = TaskStatus(status)
        prog.updated_at = datetime.utcnow()
        self._save_progress(prog)

    def _save_progress(self, progress: RunProgress):
        pf = self._current_run / "progress.json"
        pf.write_text(progress.model_dump_json(indent=2))

    def summary(self) -> dict:
        runs = self.list_runs()
        return {
            "task_slug":    self.task_slug,
            "total_runs":   len(runs),
            "last_status":  runs[0]["status"] if runs else "never_run",
            "has_incomplete": self.has_incomplete_run(),
        }


def _context_to_md(ctx: ProjectContext) -> str:
    return "\n".join([
        f"# Contexto del Proyecto: {ctx.project_name}",
        f"**Recopilado:** {ctx.collected_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Stack",
        *[f"- {s}" for s in ctx.stack],
        "",
        "## Archivos Clave",
        *[f"- `{f}`" for f in ctx.key_files],
        "",
        "## Restricciones",
        *([f"- {c}" for c in ctx.constraints] if ctx.constraints else ["- Ninguna"]),
        "",
        "## Convenciones",
        *([f"- {c}" for c in ctx.conventions] if ctx.conventions else ["- Ninguna"]),
    ])
```

---

## 13. Diff Reporter

**Archivo:** `pipeline/diff_reporter.py`

Captura snapshot de los archivos objetivo antes del step y computa el diff unificado después.

```python
import difflib
from pathlib import Path
from harness.protocols import FileChange


def capture_snapshot(file_paths: list[str]) -> dict[str, str]:
    """
    Captura contenido actual de los archivos ANTES de ejecutar el step.
    Solo incluye archivos que existen y son legibles.
    """
    snapshot = {}
    for path_str in file_paths:
        p = Path(path_str)
        if p.exists() and p.is_file():
            try:
                snapshot[path_str] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return snapshot


def compute_diff(before: dict[str, str], after: dict[str, str]) -> str | None:
    """
    Genera diff unificado entre snapshots antes/después.
    Retorna el patch como string, o None si no hubo cambios.
    """
    patches = []
    for path in sorted(set(before) | set(after)):
        before_lines = before.get(path, "").splitlines(keepends=True)
        after_lines  = after.get(path, "").splitlines(keepends=True)
        if before_lines == after_lines:
            continue
        diff = "".join(difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{path}", tofile=f"b/{path}",
        ))
        if diff:
            patches.append(diff)
    return "\n".join(patches) if patches else None


def detect_file_changes(
    before: dict[str, str],
    after:  dict[str, str],
) -> list[FileChange]:
    changes = []
    all_files = sorted(set(before) | set(after))
    for f in all_files:
        if f not in before:
            changes.append(FileChange(
                path=f, action="created",
                diff_lines=len(after[f].splitlines()),
            ))
        elif f not in after:
            changes.append(FileChange(path=f, action="deleted", diff_lines=0))
        elif before[f] != after[f]:
            added   = sum(1 for l in after[f].splitlines() if l not in before[f])
            changes.append(FileChange(path=f, action="modified", diff_lines=added))
    return changes
```

---

## 14. Providers

### providers/base.py

```python
from abc import ABC, abstractmethod
from harness.protocols import Step, StepResult, TaskPlan


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderBase(ABC):
    name:     str
    roles:    list[str]   # ["planner"] | ["executor"] | ["planner", "executor"]
    priority: int

    def supports_role(self, role: str) -> bool:
        return role in self.roles

    def planner_model_for(self, task_type: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_plan(self, task_md: str, task_type: str) -> TaskPlan: ...

    @abstractmethod
    def execute_step(
        self, step: Step, task_md: str, plan_summary: str, task_type: str
    ) -> StepResult: ...
```

### providers/claude_code.py

```python
import subprocess, json, re, time
from pathlib import Path
from providers.base import ProviderBase, ProviderError
from harness.protocols import Step, StepResult, TaskPlan

PROMPTS = Path("config/prompts")


class ClaudeCodeProvider(ProviderBase):
    """
    Planner usando claude CLI en modo headless (claude -p).
    Actúa como agente real: lee el filesystem con --allowedTools Read,Edit,Bash.

    Instancias:
      - ClaudeCodeProvider("claude-sonnet-4-6", priority=1)  → default
      - ClaudeCodeProvider("claude-opus-4-6",   priority=99) → extra_high
    """
    roles = ["planner"]

    def __init__(self, model: str, priority: int = 1, timeout: int = 240):
        self.model    = model
        self.priority = priority
        self.timeout  = timeout
        # Nombre para budget tracking
        model_short = "sonnet" if "sonnet" in model else "opus"
        self.name   = f"claude_{model_short}"

    def planner_model_for(self, task_type: str) -> str:
        return self.model

    def generate_plan(self, task_md: str, task_type: str = "generic") -> TaskPlan:
        prompt_file = PROMPTS / f"planner_{task_type}.md"
        if not prompt_file.exists():
            prompt_file = PROMPTS / "planner_generic.md"

        system = prompt_file.read_text(encoding="utf-8")
        prompt = f"{system}\n\n---\n\n{task_md}"
        raw    = self._run(prompt)
        return self._parse(raw)

    def execute_step(self, step, task_md, plan_summary, task_type):
        raise NotImplementedError("ClaudeCodeProvider es solo planner")

    def _run(self, prompt: str) -> str:
        result = subprocess.run(
            ["claude", "--print", "--model", self.model,
             "--allowedTools", "Read,Edit,Bash",
             "--output-format", "json"],
            input=prompt, capture_output=True, text=True, timeout=self.timeout,
        )
        if result.returncode != 0:
            raise ProviderError(self.name, f"exit {result.returncode}: {result.stderr[:400]}")
        try:
            return json.loads(result.stdout).get("result", result.stdout)
        except json.JSONDecodeError:
            return result.stdout

    def _parse(self, raw: str) -> TaskPlan:
        match = re.search(r"```json\s*([\s\S]+?)```", raw)
        json_str = match.group(1).strip() if match else raw.strip()
        try:
            data = json.loads(json_str)
            return TaskPlan(**data, planner_used=self.name, planner_model=self.model)
        except Exception as e:
            # Reintentar una vez
            retry = (
                f"Tu respuesta tenía error JSON: {e}\n"
                f"Devuelve SOLO el bloque ```json sin texto adicional.\n\n"
                f"Respuesta anterior:\n{raw[:800]}"
            )
            raw2  = self._run(retry)
            match2 = re.search(r"```json\s*([\s\S]+?)```", raw2)
            data  = json.loads(match2.group(1) if match2 else raw2)
            return TaskPlan(**data, planner_used=self.name, planner_model=self.model)
```

### providers/gemini.py

```python
import subprocess, time, os, tempfile
from pathlib import Path
from providers.base import ProviderBase, ProviderError
from harness.protocols import Step, StepResult, StepStatus

PROMPTS = Path("config/prompts")


class GeminiProvider(ProviderBase):
    """
    Executor usando gemini CLI (agente real con filesystem).
    Modelo: gemini-2.0-flash — free tier 1500 req/día.
    """
    name     = "gemini_flash"
    roles    = ["executor"]
    priority = 1

    def __init__(self, model: str = "gemini-2.0-flash", timeout: int = 120):
        self.model   = model
        self.timeout = timeout

    def planner_model_for(self, task_type): raise NotImplementedError
    def generate_plan(self, task_md, task_type): raise NotImplementedError

    def execute_step(self, step: Step, task_md: str, plan_summary: str, task_type: str) -> StepResult:
        prompt_file = PROMPTS / f"executor_{task_type}.md"
        if not prompt_file.exists():
            prompt_file = PROMPTS / "executor_generic.md"

        prompt = self._build_prompt(
            prompt_file.read_text(encoding="utf-8"),
            step, task_md, plan_summary,
        )
        start = time.time()
        raw   = self._run(prompt)
        return StepResult(
            step_index=step.index, status=StepStatus.completed,
            output=raw, tokens_used=0,
            executor_used=self.name, provider_model=self.model,
            duration_seconds=time.time() - start,
        )

    def _run(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(prompt)
            tmp = f.name
        try:
            result = subprocess.run(
                ["gemini", "--model", self.model, f"@{tmp}"],
                capture_output=True, text=True, timeout=self.timeout,
            )
            if result.returncode != 0:
                if "429" in result.stderr or "RESOURCE_EXHAUSTED" in result.stderr:
                    time.sleep(60)
                    result = subprocess.run(
                        ["gemini", "--model", self.model, f"@{tmp}"],
                        capture_output=True, text=True, timeout=self.timeout,
                    )
                if result.returncode != 0:
                    raise ProviderError(self.name, result.stderr[:400])
            return result.stdout
        finally:
            os.unlink(tmp)

    @staticmethod
    def _build_prompt(system: str, step: Step, task_md: str, plan_summary: str) -> str:
        return (
            f"{system}\n\n"
            f"# Task\n{task_md}\n\n"
            f"# Plan (contexto global)\n{plan_summary}\n\n"
            f"# Step {step.index}: {step.description}\n"
            f"Archivos objetivo: {', '.join(step.target_files)}\n"
            f"Validación: {step.validation}\n"
            f"Output esperado: {step.expected_output}"
        )
```

### providers/opencode.py

```python
import subprocess, shutil, time, os, tempfile
from pathlib import Path
from providers.base import ProviderBase, ProviderError
from harness.protocols import Step, StepResult, StepStatus

PROMPTS = Path("config/prompts")

FREE_MODELS = {
    "opencode/minimax-m2-5-free": ("opencode_minimax", 2),
    "opencode/big-pickle":        ("opencode_bigpickle", 3),
}


class OpenCodeProvider(ProviderBase):
    """
    Executor de fallback usando opencode CLI con modelos Zen gratuitos.

    BUG CONOCIDO (issue #13851):
    opencode run puede colgar esperando permisos al escribir archivos.
    Se mitiga con --dangerously-skip-permissions y timeout.

    AVISO DE PRIVACIDAD:
    Los modelos free de OpenCode Zen pueden usar los datos para entrenamiento.
    El harness muestra un aviso cada vez que se activa este provider.
    """
    roles = ["executor"]

    def __init__(self, model: str = "opencode/minimax-m2-5-free", timeout: int = 150):
        if not shutil.which("opencode"):
            raise EnvironmentError("opencode CLI no encontrado. Instalar: npm install -g opencode-ai")
        self.model   = model
        self.timeout = timeout
        self.name, self.priority = FREE_MODELS.get(model, ("opencode_unknown", 10))

    @classmethod
    def build_chain(cls) -> list["OpenCodeProvider"]:
        """Construye la cadena completa de fallbacks gratuitos."""
        providers = []
        for model in FREE_MODELS:
            try:
                providers.append(cls(model=model))
            except EnvironmentError:
                break
        return providers

    def planner_model_for(self, task_type): raise NotImplementedError
    def generate_plan(self, task_md, task_type): raise NotImplementedError

    def execute_step(self, step: Step, task_md: str, plan_summary: str, task_type: str) -> StepResult:
        prompt_file = PROMPTS / f"executor_{task_type}.md"
        if not prompt_file.exists():
            prompt_file = PROMPTS / "executor_generic.md"

        prompt = (
            f"{prompt_file.read_text(encoding='utf-8')}\n\n"
            f"# Task\n{task_md}\n\n"
            f"# Plan\n{plan_summary}\n\n"
            f"# Step {step.index}: {step.description}\n"
            f"Archivos: {', '.join(step.target_files)}\n"
            f"Validación: {step.validation}\n"
            f"Expected: {step.expected_output}"
        )
        start = time.time()
        raw   = self._run(prompt)
        return StepResult(
            step_index=step.index, status=StepStatus.completed,
            output=raw, tokens_used=0,
            executor_used=self.name, provider_model=self.model,
            duration_seconds=time.time() - start,
        )

    def _run(self, prompt: str) -> str:
        # Prompts largos → archivo temporal con --file
        if len(prompt) > 1500:
            return self._run_via_file(prompt)
        return self._run_inline(prompt)

    def _run_inline(self, prompt: str) -> str:
        result = subprocess.run(
            ["opencode", "run", "--model", self.model,
             "--dangerously-skip-permissions", prompt],
            capture_output=True, text=True, timeout=self.timeout,
        )
        return self._check(result)

    def _run_via_file(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(prompt)
            tmp = f.name
        try:
            result = subprocess.run(
                ["opencode", "run", "--model", self.model,
                 "--dangerously-skip-permissions",
                 "--file", tmp,
                 "Ejecuta las instrucciones del archivo adjunto."],
                capture_output=True, text=True, timeout=self.timeout,
            )
            return self._check(result)
        finally:
            os.unlink(tmp)

    def _check(self, result: subprocess.CompletedProcess) -> str:
        if result.returncode != 0:
            raise ProviderError(self.name, f"exit {result.returncode}: {result.stderr[:400]}")
        if not result.stdout.strip():
            raise ProviderError(self.name, "Sin output — posible hang o timeout del modelo")
        return result.stdout
```

---

## 15. Orchestrator

**Archivo:** `harness/orchestrator.py`

Coordina el flujo completo: confirmación de cada step, captura de diff, failover interactivo, guardado de artefactos.

```python
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
    def __init__(self, router: Router, budget: BudgetManager, session: SessionManager):
        self.router  = router
        self.budget  = budget
        self.session = session

    def run(self, task_md: str, plan: TaskPlan, complexity: str):
        """Ejecuta el plan completo step-by-step con confirmación del usuario."""
        pending = list(range(len(plan.steps)))
        self._execute_steps(task_md, plan, pending, complexity)

    def resume(self, task_md: str, plan: TaskPlan, progress: RunProgress, complexity: str):
        """Retoma un run incompleto desde los steps pendientes."""
        from session.manager import SessionManager
        pending = self.session.pending_steps(plan, progress)
        if not pending:
            console.print("[green]No hay steps pendientes — el run ya está completo.[/green]")
            return
        console.print(f"[cyan]Retomando — {len(pending)} step(s) pendiente(s)[/cyan]")
        self._execute_steps(task_md, plan, pending, complexity)

    def _execute_steps(self, task_md: str, plan: TaskPlan, pending: list[int], complexity: str):
        task_type    = plan.task_type.value
        plan_summary = self._build_summary(plan)

        for step in plan.steps:
            if step.index not in pending:
                continue

            # Verificar dependencias
            if not self._deps_met(step, plan):
                console.print(f"[yellow]Step {step.index}: dependencias no cumplidas — saltando[/yellow]")
                self.session.mark_step_skipped(step.index)
                continue

            result = self._run_step(step, task_md, plan_summary, task_type, complexity)

            if result is None:   # usuario canceló
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
    def _build_summary(plan: TaskPlan) -> str:
        lines = [f"Objetivo: {plan.summary}", f"Tipo: {plan.task_type.value}", "Steps:"]
        for s in plan.steps:
            lines.append(f"  {s.index}. {s.description}")
        return "\n".join(lines)

    @staticmethod
    def _deps_met(step: Step, plan: TaskPlan) -> bool:
        # En v1.0 asumimos linear — en v2 trackear completed steps
        return True
```

---

## 16. Consola TUI — Menús Completos

### Menú Principal

```
╔══════════════════════════════════════════════════════════════╗
║                    AI DEV HARNESS v1.0                       ║
╚══════════════════════════════════════════════════════════════╝

  Proyecto activo: [ninguno]   [P: cambiar]

  ┌──────────────────────────────────────────────────────────┐
  │  PLANNERS                                                │
  │  Claude Sonnet  ██░░░░░░░░  18% (14/80 req)  ✓ OK       │
  │  Claude Opus    ░░░░░░░░░░   0% ( 0/20 req)  ✓ OK       │
  │                                                          │
  │  EXECUTORS                                               │
  │  Gemini Flash   ████████░░  76% (1142/1500)  ⚠ WARN     │
  │  MiniMax Free   ░░░░░░░░░░   0% (0/300)      ✓ OK       │
  │  Big Pickle     ░░░░░░░░░░   0% (0/200)      ✓ OK       │
  └──────────────────────────────────────────────────────────┘

  [1] Nuevo task
  [2] Retomar task incompleto
  [3] Ver historial de runs
  [4] Budget y uso detallado
  [5] Cambiar / crear proyecto
  [Q] Salir

  > _
```

### Menú de Nuevo Task — Selección de Proyecto

```
── Proyecto ───────────────────────────────────────────────────

  Proyectos recientes:
    [1] quetz-ai          (2 tasks, último run: hace 2 días)
    [2] business-app      (1 task,  último run: hace 1 semana)
    [3] + Crear nuevo proyecto

  > 3

  Nombre del proyecto: mi-proyecto-nuevo
  ✓ Proyecto creado: mi-proyecto-nuevo
```

### Menú de Nuevo Task — Ingesta Notion

```
── Ingesta desde Notion ───────────────────────────────────────

  Pega la URL o ID de la página Notion:
  > https://www.notion.so/mi-workspace/Implementar-JWT-abc123def456abc123def456abc12345

  ⏳ Extrayendo page ID...
  ✓  ID: abc123def456abc123def456abc12345

  ⏳ Descargando página desde Notion...
  ✓  Título: "Implementar autenticación JWT en ASP.NET Core"

  ⏳ Normalizando con Gemini Flash...
  ✓  task.md generado (1,243 caracteres)

  ── Vista previa del task ──────────────────────────────────

  # Implementar autenticación JWT en ASP.NET Core

  **notion_id:** abc123def456abc123def456abc12345
  **task_type:** backend
  **complejidad_estimada:** high
  **fecha_ingesta:** 2026-05-16T14:30:22

  ## Objetivo
  Agregar autenticación JWT al proyecto ASP.NET Core 8.
  Los usuarios deben poder hacer login y recibir un token
  válido por 24 horas para acceder a endpoints protegidos.

  ## Criterios de Aceptación
  - POST /auth/login retorna JWT válido con credenciales correctas
  - Endpoints con [Authorize] rechazan requests sin token válido
  - Token expira correctamente a las 24 horas

  [dim]... (ver completo con opción V)[/dim]

  ¿Continuar con este task? [S/n/V(er completo)]: S
```

### Menú de Clasificación y Complexity

```
── Clasificación del Task ─────────────────────────────────────

  Detectado automáticamente:
    Tipo:        [cyan]backend[/cyan]
    Complejidad: [cyan]high[/cyan]
    Stack:       ASP.NET, PostgreSQL, Docker

  Planner que se usará: Claude Sonnet 4.6

  ¿La clasificación es correcta?
  [1] Sí, usar HIGH con Sonnet          ← recomendado
  [2] Bajar a MEDIUM con Sonnet
  [3] Bajar a LOW con Sonnet
  [4] EXTRA HIGH → Claude Opus          ⚠ (14 usos Opus restantes hoy)
  [5] Cambiar tipo de task

  > 1

  ✓ Complejidad: HIGH — Planner: Claude Sonnet
```

### Menú de Contexto del Proyecto

```
── Contexto del Proyecto: mi-proyecto-nuevo ──────────────────

  No se encontró contexto previo para este proyecto.
  Se recopilará ahora (solo necesario una vez).

  Stack tecnológico del proyecto:
  > ASP.NET Core 8, PostgreSQL, Docker, Entity Framework

  Archivos clave del proyecto (separados por coma):
  > Program.cs, appsettings.json, Controllers/AuthController.cs

  Restricciones técnicas que el agente debe respetar:
  > No modificar el schema de base de datos sin crear migración

  Convenciones del proyecto (naming, patterns, etc.):
  > Usar Clean Architecture. Repositorios en Infrastructure/. DTOs con sufijo Dto.

  ✓ Contexto guardado en ~/.ai-harness/projects/mi-proyecto-nuevo/
```

### Aprobación del Plan

```
── Plan Generado ──────────────────────────────────────────────

  Planner: Claude Sonnet 4.6   Tokens: 1,847   Tiempo: 12.3s

  Task: "Implementar autenticación JWT en ASP.NET Core"
  Tipo: backend   Complejidad: high   Steps: 5

  ┌──────────────────────────────────────────────────────────┐
  │  0. Crear JwtService con generación y validación de tokens│
  │     Archivos: Infrastructure/Auth/JwtService.cs           │
  │     Validación: clase compilable, método GenerateToken()  │
  │                                                           │
  │  1. Registrar JwtService en DI y configurar JWT Bearer    │
  │     Archivos: Program.cs, appsettings.json                │
  │     Validación: app arranca sin errores de DI             │
  │     Depende de: step 0                                    │
  │                                                           │
  │  2. Crear AuthController con endpoints login/refresh      │
  │     Archivos: Controllers/AuthController.cs               │
  │     Validación: POST /auth/login retorna 200 con token    │
  │     Depende de: steps 0, 1                                │
  │                                                           │
  │  3. Agregar [Authorize] a endpoints protegidos            │
  │     Archivos: Controllers/ProductsController.cs           │
  │     Validación: GET /products retorna 401 sin token       │
  │     Depende de: step 1                                    │
  │                                                           │
  │  4. Escribir tests de integración para auth               │
  │     Archivos: Tests/Auth/AuthControllerTests.cs           │
  │     Validación: dotnet test pasa sin errores              │
  │     Depende de: steps 2, 3                                │
  └──────────────────────────────────────────────────────────┘

  [A] Aprobar y comenzar ejecución
  [R] Rechazar y regenerar plan
  [V] Ver plan completo (JSON)
  [C] Cancelar

  > A

  ✓ Plan aprobado. Iniciando run_20260516_143022...
```

### Ejecución Step por Step

```
── Step 0: Crear JwtService ───────────────────────────────────

  Archivos objetivo: Infrastructure/Auth/JwtService.cs
  Validación: clase compilable, método GenerateToken() retorna JWT válido

  [1] Ejecutar   [2] Saltar   [3] Cancelar todo
  > 1

  [dim]Ejecutando con gemini_flash (gemini-2.0-flash)...[/dim]

  ✓ Step 0 completado
  Provider: gemini_flash   Tokens: 2,341   Tiempo: 8.7s

  Archivos tocados (1):
    created  Infrastructure/Auth/JwtService.cs

  Output:
  He creado el archivo JwtService.cs con las siguientes responsabilidades:
  - GenerateToken(User user): genera JWT con claims de userId y email
  - ValidateToken(string token): valida y retorna ClaimsPrincipal
  - Tiempo de expiración configurable desde appsettings...

  Diff:
  ─────────────────────────────────────────────────────────────
  --- a/Infrastructure/Auth/JwtService.cs
  +++ b/Infrastructure/Auth/JwtService.cs
  @@ -0,0 +1,48 @@
  +using Microsoft.IdentityModel.Tokens;
  +using System.IdentityModel.Tokens.Jwt;
  +...
  ─────────────────────────────────────────────────────────────

  [Enter para continuar con Step 1]
```

### Pantalla de Step con Provider Agotado

```
── Step 2: Crear AuthController ──────────────────────────────

  Archivos objetivo: Controllers/AuthController.cs
  Validación: POST /auth/login retorna 200 con token válido

  [1] Ejecutar   [2] Saltar   [3] Cancelar todo
  > 1

  ⚠  [gemini_flash] sin capacidad disponible (91% del límite diario).

  ⚠  AVISO DE PRIVACIDAD: opencode_minimax es un modelo free de OpenCode Zen.
     Los datos enviados pueden usarse para entrenamiento del modelo.

  Siguiente disponible: opencode_minimax
  ¿Continuar con opencode_minimax? [S/n]: S

  [dim]Ejecutando con opencode_minimax (opencode/minimax-m2-5-free)...[/dim]

  ✓ Step 2 completado
  ...
```

### Historial de Runs

```
── Historial: mi-proyecto-nuevo / jwt-implementation ─────────

  Run                   Estado       Steps        Última actividad
  ──────────────────────────────────────────────────────────────
  run_20260516_162045   completed    5/5 ✓        hace 2 horas
  run_20260516_143022   failed       3/5 (1 fail)  hace 4 horas
  run_20260515_094511   cancelled    1/5            ayer

  [1] Ver detalles de run_20260516_162045
  [2] Ver detalles de run_20260516_143022
  [3] Ver detalles de run_20260515_094511
  [L] Limpiar historial (conservar task.md y contexto)
  [B] Volver

  > 2

  ── Detalle: run_20260516_143022 ─────────────────────────────

  Plan: "Implementar autenticación JWT en ASP.NET Core"
  Estado: failed   Tiempo total: 47.3s   Tokens: 8,234

  Step 0  ✓ completed   gemini_flash   2,341 tokens   8.7s
  Step 1  ✓ completed   gemini_flash   1,892 tokens   6.2s
  Step 2  ✗ failed      gemini_flash   0 tokens       timeout
  Step 3  - pending
  Step 4  - pending

  [S] Ver output del step 0   [D] Ver diff del step 0
  [R] Retomar este run        [B] Volver

  > _
```

### Menú de Budget Detallado

```
── Budget y Uso ───────────────────────────────────────────────

  Fecha: 2026-05-16   Hora UTC: 14:35

  PLANNERS (ventana deslizante de 5 horas)
  ┌──────────────────┬───────────┬──────────┬──────────────┐
  │ Provider         │ Usados    │ Límite   │ Estado       │
  ├──────────────────┼───────────┼──────────┼──────────────┤
  │ Claude Sonnet    │ 14 req    │ ~80 req  │ ✓ OK  (18%)  │
  │ Claude Opus      │  0 req    │ ~20 req  │ ✓ OK   (0%)  │
  └──────────────────┴───────────┴──────────┴──────────────┘

  EXECUTORS
  ┌──────────────────┬───────────┬──────────┬──────────────┐
  │ Provider         │ Usados    │ Límite   │ Estado       │
  ├──────────────────┼───────────┼──────────┼──────────────┤
  │ Gemini Flash     │ 1,142 req │ 1500/día │ ⚠ WARN (76%) │
  │ MiniMax Free     │    0 req  │ ~300/día │ ✓ OK   (0%)  │
  │ Big Pickle       │    0 req  │ 200/5h   │ ✓ OK   (0%)  │
  └──────────────────┴───────────┴──────────┴──────────────┘

  Gemini Flash: se agota en ~2.1h a la tasa actual.
  Tokens totales hoy: 48,234 (Claude Sonnet: 21,847 | Gemini: 26,387)

  [B] Volver al menú principal
```

---

## 17. Prompts Especializados

### config/prompts/converter.md

```markdown
Eres un asistente que convierte documentos de Notion a formato Markdown estandarizado.

Recibirás:
- page_id, page_url, page_title, fecha_ingesta
- El texto crudo de la página Notion

Produce EXACTAMENTE este formato (omite secciones sin información — no pongas "N/A"):

# {page_title}

**notion_id:** {page_id}
**notion_url:** {page_url}
**task_type:** backend | frontend | refactor | bugfix | generic
**complejidad_estimada:** low | medium | high
**fecha_ingesta:** {fecha_ingesta}

## Objetivo
{objetivo principal del documento en 2-5 oraciones}

## Contexto
{información de fondo, decisiones previas, restricciones técnicas}

## Criterios de Aceptación
- {criterio verificable y específico}

## Archivos Relevantes
- `{ruta/archivo}` — {por qué es relevante}

## Notas Adicionales
{información que no encaja en las secciones anteriores}

REGLAS:
- task_type: backend=API/DB/auth, frontend=UI/componentes, refactor=reestructuración,
  bugfix=corrección de error, generic=otro
- complejidad_estimada: low=1-2 archivos, medium=múltiples archivos, high=arquitectura/sistema
- Devuelve SOLO el markdown, sin explicaciones ni texto adicional
```

### config/prompts/planner_backend.md

```markdown
Eres un arquitecto de software backend generando un plan de implementación estructurado.

Recibirás el task en formato estándar y opcionalmente contexto del proyecto
(stack, archivos clave, restricciones, convenciones).

ESPECIALIZACIÓN BACKEND:
- Considera impacto en DB: migraciones, schemas, índices, transacciones
- Evalúa seguridad: validación de inputs, autenticación, autorización, sanitización
- Planifica manejo de errores en cada capa (controller, service, repository)
- Especifica archivos por capa: controllers/, services/, repositories/, DTOs/
- Si hay cambios de schema → incluir step explícito para la migración

Produce EXACTAMENTE este JSON (sin texto adicional, solo el bloque ```json):

```json
{
  "plan_id": "<8 chars aleatorios>",
  "task_type": "backend",
  "complexity": "low|medium|high|extra_high",
  "summary": "<1 oración que describe el objetivo>",
  "steps": [
    {
      "index": 0,
      "description": "<qué hacer — verbo imperativo>",
      "target_files": ["<ruta/exacta/archivo.ext>"],
      "validation": "<criterio verificable de éxito>",
      "expected_output": "<qué debe existir o cambiar>",
      "depends_on": [],
      "estimated_tokens": 500
    }
  ]
}
```

REGLAS:
- Máximo 8 steps. Cada step debe ser atómico y ejecutable de forma aislada.
- Archivos concretos (nunca directorios). Usa rutas relativas al proyecto.
- depends_on: lista de índices de steps que deben completarse primero.
- El executor que ejecuta cada step NO tiene contexto de steps anteriores.
  Descríbelo con suficiente detalle para ejecutarse de forma independiente.
```

### config/prompts/planner_frontend.md

```markdown
Eres un arquitecto de software frontend generando un plan de implementación.

ESPECIALIZACIÓN FRONTEND:
- Planifica la jerarquía de componentes antes de asignar archivos
- Considera estados: loading, error, empty, success en cada componente
- Especifica cambios en routing/navegación si los hay
- Si es Flutter: indica si el step toca BLoC/Cubit, StatefulWidget, o solo UI pura
- Si es React: indica si el step toca Context, hooks custom, o solo JSX

[mismo JSON schema que planner_backend.md]
```

### config/prompts/planner_refactor.md

```markdown
Eres un arquitecto de software generando un plan de refactorización segura.

ESPECIALIZACIÓN REFACTOR:
- El comportamiento externo NO debe cambiar. Esto es lo más importante.
- Orden recomendado: tests existentes → refactor → validación
- Identifica el "punto de corte" seguro: interfaces públicas que NO deben cambiar
- Cada step debe dejar el código en estado ejecutable (sin pasos intermedios rotos)
- Para refactors grandes: usa strangler fig — implementa nuevo en paralelo, luego migra

[mismo JSON schema que planner_backend.md]
```

### config/prompts/planner_bugfix.md

```markdown
Eres un ingeniero diagnosticando y corrigiendo un bug.

ESPECIALIZACIÓN BUGFIX:
- Si hay stack trace → úsalo como punto de partida exacto
- Genera un step de diagnóstico primero (reproducir, identificar causa raíz)
- Propón la corrección mínima — no refactorices más de lo necesario
- Incluye step de validación: verifica el fix y ausencia de regresiones
- Si hay múltiples causas posibles → menciónalas en el summary

[mismo JSON schema que planner_backend.md]
```

### config/prompts/executor_generic.md

```markdown
Eres un ingeniero senior implementando un step específico de un plan de desarrollo.

Recibirás:
1. El task completo (para entender el objetivo global)
2. El plan resumido (todos los steps y su propósito)
3. El step específico que debes implementar ahora

TU TRABAJO:
- Implementar SOLO el step indicado. No adelantes steps futuros.
- Seguir las convenciones y restricciones del proyecto si están indicadas en el task.
- Devolver el código completo del archivo si es nuevo.
- Devolver el archivo completo modificado si es una edición (no solo el diff).
- Si encuentras un problema bloqueante, explícalo con detalle y sugiere alternativas.

NO debes:
- Implementar steps no indicados
- Reformatear código no relacionado con el step
- Cambiar lógica existente que no sea parte del step
- Inventar restricciones o convenciones no mencionadas
```

---

## 18. Configuración

### config/providers.yaml

```yaml
providers:

  claude_sonnet:
    cli:     claude
    type:    planner
    priority: 1
    model:   claude-sonnet-4-6
    access:  subscription_pro
    flags:   ["--print", "--allowedTools", "Read,Edit,Bash", "--output-format", "json"]
    limits:
      window_type:  rolling
      window_hours: 5
      max_requests: 80
    timeout_seconds: 240

  claude_opus:
    cli:     claude
    type:    planner
    priority: 99
    model:   claude-opus-4-6
    access:  subscription_pro
    flags:   ["--print", "--allowedTools", "Read,Edit,Bash", "--output-format", "json"]
    limits:
      window_type:  rolling
      window_hours: 5
      max_requests: 20
    timeout_seconds: 360
    note: "Solo se activa cuando el usuario selecciona extra_high explícitamente"

  gemini_flash:
    cli:     gemini
    type:    executor
    priority: 1
    model:   gemini-2.0-flash
    access:  free_api_key
    limits:
      window_type:  daily
      max_requests: 1500
      rpm:          15
    timeout_seconds: 120

  opencode_minimax:
    cli:     opencode
    type:    executor
    priority: 2
    model:   opencode/minimax-m2-5-free
    access:  free_zen
    flags:   ["run", "--dangerously-skip-permissions"]
    limits:
      window_type:  daily
      max_requests: 300
    timeout_seconds: 150
    privacy_warning: true
    known_issues:
      - "Bug #13851: puede colgar sin --dangerously-skip-permissions"

  opencode_bigpickle:
    cli:     opencode
    type:    executor
    priority: 3
    model:   opencode/big-pickle
    access:  free_zen
    flags:   ["run", "--dangerously-skip-permissions"]
    limits:
      window_type:  rolling
      window_hours: 5
      max_requests: 200
    timeout_seconds: 120
    privacy_warning: true
```

### config/routing_rules.yaml

```yaml
routing:
  planner:
    low:        [claude_sonnet]
    medium:     [claude_sonnet]
    high:       [claude_sonnet]
    extra_high: [claude_opus, claude_sonnet]   # Opus primero, Sonnet como fallback

  executor:
    low:        [gemini_flash, opencode_minimax, opencode_bigpickle]
    medium:     [gemini_flash, opencode_minimax, opencode_bigpickle]
    high:       [gemini_flash, opencode_minimax, opencode_bigpickle]
    extra_high: [gemini_flash, opencode_minimax, opencode_bigpickle]
```

### config/budget_alerts.yaml

```yaml
thresholds:
  default:
    warn_at:     0.70
    critical_at: 0.85

per_provider:
  claude_sonnet:
    warn_at:     0.60
    critical_at: 0.80
  claude_opus:
    warn_at:     0.50
    critical_at: 0.70
  gemini_flash:
    warn_at:     0.75
    critical_at: 0.90
  opencode_minimax:
    warn_at:     0.80
    critical_at: 0.95
  opencode_bigpickle:
    warn_at:     0.75
    critical_at: 0.90
```

### .env.example

```bash
# Notion — para ingesta de tasks
NOTION_TOKEN=secret_

# Google AI Studio — para Gemini Flash (executor) y Gemini Flash converter
# Gratuito en: https://aistudio.google.com/
GOOGLE_API_KEY=AIza

# OpenCode — solo necesario si se usa opencode CLI con modelos de pago
# Los modelos Zen gratuitos (Big Pickle, MiniMax Free) no requieren API key
# OPENCODE_API_KEY=

# Claude — NO necesario para claude CLI con suscripción Pro
# Solo si se quisiera usar la API directa (no recomendado con Pro)
# ANTHROPIC_API_KEY=sk-ant-
```

### pyproject.toml

```toml
[project]
name = "ai-harness"
version = "1.0.0"
requires-python = ">=3.12"
description = "Multi-agent AI orchestration harness for development tasks"

dependencies = [
    "pydantic>=2.7",
    "rich>=13",
    "pyyaml>=6",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "tiktoken>=0.7",     # token counting real
]

[project.scripts]
harness = "main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---


## Variables de Entorno en Runtime

```python
# main.py — carga de configuración

import os
from dotenv import load_dotenv
import yaml
from pathlib import Path

def load_config() -> dict:
    load_dotenv()
    providers_cfg = yaml.safe_load(Path("config/providers.yaml").read_text())
    routing_cfg   = yaml.safe_load(Path("config/routing_rules.yaml").read_text())

    notion_token = os.getenv("NOTION_TOKEN")
    google_key   = os.getenv("GOOGLE_API_KEY")

    if not notion_token:
        raise RuntimeError("NOTION_TOKEN no configurado. Revisa tu .env")
    if not google_key:
        raise RuntimeError("GOOGLE_API_KEY no configurado. Revisa tu .env")

    return {
        "notion_token":    notion_token,
        "google_api_key":  google_key,
        "providers":       providers_cfg,
        "routing":         routing_cfg,
    }
```
