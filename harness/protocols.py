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
