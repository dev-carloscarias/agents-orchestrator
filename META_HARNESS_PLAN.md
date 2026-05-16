# Meta-Harness para Orquestación de Agentes de IA

**Proyecto:** quetz-meta-harness  
**Fecha:** 2026-05-15  
**Contexto:** Extensión del quetz-orchestrator existente hacia un harness multi-proveedor inteligente

---

## Visión General

Un meta-harness que coordina múltiples CLIs y modelos de IA con dos responsabilidades bien separadas:

- **Planners** (modelos lentos y potentes): generan planes estructurados de implementación
- **Executors** (modelos rápidos y eficientes): ejecutan los pasos del plan

Cuando un proveedor alcanza sus límites, el harness hace failover automático al siguiente disponible. El sistema maximiza el uso de suscripciones existentes antes de consumir API de pago.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                      META-HARNESS                           │
│                                                             │
│   Task Input ──▶ Classifier ──▶ BudgetRouter                │
│                                      │                      │
│                          ┌───────────┴───────────┐          │
│                          ▼                       ▼          │
│                    PLANNER POOL           EXECUTOR POOL     │
│                          │                       │          │
│            ┌─────────────┤           ┌───────────┤          │
│            │  Claude     │           │  Gemini   │          │
│            │  Opus 4.7   │           │  Flash    │          │
│            ├─────────────┤           ├───────────┤          │
│            │  Gemini     │           │  Claude   │          │
│            │  2.5 Pro    │           │  Haiku    │          │
│            ├─────────────┤           ├───────────┤          │
│            │  GPT-4o     │           │  GPT-4o   │          │
│            │  (Opencode) │           │  mini     │          │
│            └──────┬──────┘           └─────┬─────┘          │
│                   │                        │                │
│                   ▼                        ▼                │
│             TaskPlan (JSON) ──▶ Steps ──▶ Results           │
│                                                             │
│                     BudgetManager                           │
│              [usage.jsonl | limits.yaml]                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Providers y su Rol

### Planner Pool (modelos de razonamiento)

| Provider | CLI | Modelo | Tipo acceso | Costo |
|----------|-----|--------|-------------|-------|
| Claude Code | `claude` | `claude-opus-4-7` | Suscripción Max | Incluido |
| Gemini CLI | `gemini` | `gemini-2.5-pro` | API key gratuita | Free tier |
| OpenCode | `opencode` | `gpt-4o` | API key OpenAI | Pay-per-token |
| Cursor | headless | Composer model | Suscripción | Incluido |

### Executor Pool (modelos rápidos)

| Provider | CLI | Modelo | Tipo acceso | Costo |
|----------|-----|--------|-------------|-------|
| Claude Code | `claude` | `claude-haiku-4-5-20251001` | Suscripción | Incluido |
| Gemini CLI | `gemini` | `gemini-2.0-flash` | API key gratuita | Free tier |
| OpenCode | `opencode` | `gpt-4o-mini` | API key OpenAI | Pay-per-token |
| Aider | `aider` | cualquiera | API key | Pay-per-token |

**Prioridad de selección:** suscripciones incluidas > tier gratuito > pay-per-token

---

## Estructura de Archivos

```
meta-harness/
├── harness/
│   ├── __init__.py
│   ├── orchestrator.py       # Coordinador principal
│   ├── classifier.py         # Clasifica complejidad del task
│   ├── planner.py            # Coordina la fase de planeación
│   ├── executor.py           # Coordina la fase de ejecución
│   ├── supervisor.py         # Verifica output del executor
│   ├── router.py             # Selección de provider con failover
│   ├── budget.py             # Tracking de uso y límites
│   └── protocols.py          # Schemas: TaskPlan, Step, Result
├── providers/
│   ├── __init__.py
│   ├── base.py               # ProviderBase ABC
│   ├── claude_code.py        # Wrapper para claude CLI
│   ├── opencode.py           # Wrapper para opencode CLI
│   ├── gemini.py             # Wrapper para gemini CLI
│   ├── cursor.py             # Wrapper headless de Cursor
│   └── aider.py              # Wrapper para aider
├── config/
│   ├── providers.yaml        # Definición de providers y límites
│   ├── routing_rules.yaml    # Reglas de cuándo usar cada provider
│   └── prompts/
│       ├── planner.md        # System prompt del planner
│       └── executor.md       # System prompt del executor
├── storage/
│   ├── usage.jsonl           # Log de tokens/requests por provider
│   ├── plan_cache.json       # Cache de planes por hash de task
│   └── task_history.jsonl    # Historial de ejecución
└── main.py                   # CLI entry point (Typer)
```

---

## Schemas Core (protocols.py)

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime

class Complexity(str, Enum):
    low = "low"       # cambios de 1-2 archivos, bien definidos
    medium = "medium" # múltiples archivos, requiere coordinación
    high = "high"     # arquitectura, refactor sistémico, diseño

class TaskPlan(BaseModel):
    task_id: str
    complexity: Complexity
    summary: str
    steps: list["Step"]
    context_files: list[str] = []
    estimated_tokens: int = 0
    planner_used: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Step(BaseModel):
    index: int
    description: str
    target_files: list[str]
    validation: str          # qué verificar para saber que salió bien
    expected_output: str
    depends_on: list[int] = []   # índices de steps previos requeridos

class StepResult(BaseModel):
    step_index: int
    success: bool
    output: str
    tokens_used: int
    executor_used: str
    duration_seconds: float
    error: Optional[str] = None

class TaskResult(BaseModel):
    task_id: str
    plan: TaskPlan
    step_results: list[StepResult]
    success: bool
    total_tokens: int
    total_duration_seconds: float
```

---

## Budget Manager (budget.py)

Responsable de saber en todo momento cuánto se ha consumido y proyectar cuándo se agotará cada provider.

```python
import json
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional

USAGE_FILE = Path.home() / ".quetz-meta-harness" / "usage.jsonl"

@dataclass
class ProviderUsage:
    provider: str
    tokens_today: int = 0
    tokens_month: int = 0
    requests_today: int = 0
    requests_minute: int = 0  # ventana deslizante de 60s

@dataclass
class ProviderLimits:
    daily_tokens: Optional[int] = None
    monthly_tokens: Optional[int] = None
    daily_requests: Optional[int] = None
    rpm: Optional[int] = None   # requests per minute

class BudgetManager:
    def __init__(self, limits: dict[str, ProviderLimits]):
        self.limits = limits
        self._usage: dict[str, ProviderUsage] = {}
        self._load_today()

    def record(self, provider: str, tokens: int, requests: int = 1):
        usage = self._usage.setdefault(provider, ProviderUsage(provider))
        usage.tokens_today += tokens
        usage.tokens_month += tokens
        usage.requests_today += requests
        self._append_log(provider, tokens, requests)

    def has_capacity(self, provider: str, role: str) -> bool:
        usage = self._usage.get(provider, ProviderUsage(provider))
        limits = self.limits.get(provider)
        if not limits:
            return True
        # Deja 10% de margen de seguridad antes del límite
        if limits.daily_tokens and usage.tokens_today >= limits.daily_tokens * 0.9:
            return False
        if limits.daily_requests and usage.requests_today >= limits.daily_requests * 0.9:
            return False
        return True

    def projected_exhaustion(self, provider: str) -> Optional[str]:
        """Estima a qué hora se agotará el budget del día."""
        usage = self._usage.get(provider)
        limits = self.limits.get(provider)
        if not usage or not limits or not limits.daily_tokens:
            return None
        hour = datetime.utcnow().hour or 1
        rate = usage.tokens_today / hour  # tokens/hora
        if rate == 0:
            return None
        remaining = limits.daily_tokens - usage.tokens_today
        hours_left = remaining / rate
        return f"{hours_left:.1f}h"

    def _append_log(self, provider: str, tokens: int, requests: int):
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.utcnow().isoformat(),
                "date": date.today().isoformat(),
                "provider": provider,
                "tokens": tokens,
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
                    usage = self._usage.setdefault(p, ProviderUsage(p))
                    usage.tokens_today += entry.get("tokens", 0)
                    usage.requests_today += entry.get("requests", 0)
            except (json.JSONDecodeError, KeyError):
                continue
```

---

## Router con Failover (router.py)

```python
from harness.budget import BudgetManager
from providers.base import ProviderBase

class Router:
    def __init__(self, providers: list[ProviderBase], budget: BudgetManager):
        self.providers = providers
        self.budget = budget

    def select(self, role: str, complexity: str = "medium") -> ProviderBase:
        """
        role: 'planner' | 'executor'
        Devuelve el mejor provider disponible según:
          1. Tiene capacity (no ha llegado al límite)
          2. Soporta el role
          3. Prioridad configurada (suscripción > free > pay)
        """
        candidates = [
            p for p in self.providers
            if p.supports_role(role)
            and self.budget.has_capacity(p.name, role)
        ]
        if not candidates:
            raise RuntimeError(
                f"Todos los providers para role='{role}' están agotados. "
                "Espera el reset de límites o agrega más providers."
            )
        # Ordenar por prioridad configurada (menor = más prioritario)
        return sorted(candidates, key=lambda p: p.priority)[0]

    def status(self) -> dict:
        """Para el dashboard de uso."""
        return {
            p.name: {
                "role": p.roles,
                "has_capacity_planner": self.budget.has_capacity(p.name, "planner"),
                "has_capacity_executor": self.budget.has_capacity(p.name, "executor"),
                "projected_exhaustion": self.budget.projected_exhaustion(p.name),
            }
            for p in self.providers
        }
```

---

## Provider Base ABC (providers/base.py)

```python
from abc import ABC, abstractmethod
from harness.protocols import Step, StepResult, TaskPlan
from typing import Literal

class ProviderBase(ABC):
    name: str
    roles: list[Literal["planner", "executor"]]
    priority: int   # menor = más prioritario

    @abstractmethod
    def supports_role(self, role: str) -> bool:
        return role in self.roles

    @abstractmethod
    def generate_plan(self, task_description: str, context: str = "") -> TaskPlan:
        """Solo providers con role=planner implementan esto."""
        ...

    @abstractmethod
    def execute_step(self, step: Step, plan_context: str = "") -> StepResult:
        """Solo providers con role=executor implementan esto."""
        ...
```

---

## Claude Code Provider (providers/claude_code.py)

Usa el CLI `claude` directamente. Aprovecha la suscripción Max sin consumir tokens adicionales.

```python
import subprocess
import json
import time
from providers.base import ProviderBase
from harness.protocols import Step, StepResult, TaskPlan

PLANNER_SYSTEM = Path("config/prompts/planner.md").read_text()
EXECUTOR_SYSTEM = Path("config/prompts/executor.md").read_text()

class ClaudeCodeProvider(ProviderBase):
    name = "claude_code"
    roles = ["planner", "executor"]
    priority = 1  # Primera opción: incluido en suscripción

    def __init__(self, planner_model: str, executor_model: str):
        self.planner_model = planner_model    # claude-opus-4-7
        self.executor_model = executor_model  # claude-haiku-4-5-20251001

    def generate_plan(self, task: str, context: str = "") -> TaskPlan:
        prompt = f"{PLANNER_SYSTEM}\n\n# Task\n{task}\n\n# Context\n{context}"
        raw = self._run_cli(self.planner_model, prompt)
        # El planner devuelve JSON estructurado según TaskPlan schema
        data = json.loads(self._extract_json(raw))
        return TaskPlan(**data, planner_used=self.name)

    def execute_step(self, step: Step, plan_context: str = "") -> StepResult:
        prompt = (
            f"{EXECUTOR_SYSTEM}\n\n"
            f"# Plan Context\n{plan_context}\n\n"
            f"# Step {step.index}: {step.description}\n"
            f"Target files: {', '.join(step.target_files)}\n"
            f"Expected: {step.expected_output}"
        )
        start = time.time()
        raw = self._run_cli(self.executor_model, prompt)
        duration = time.time() - start
        return StepResult(
            step_index=step.index,
            success="error" not in raw.lower(),
            output=raw,
            tokens_used=self._estimate_tokens(prompt + raw),
            executor_used=self.name,
            duration_seconds=duration,
        )

    def _run_cli(self, model: str, prompt: str) -> str:
        """
        Usa claude --print para modo no-interactivo.
        --print hace que devuelva solo el texto y salga.
        """
        result = subprocess.run(
            ["claude", "--model", model, "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI error: {result.stderr}")
        return result.stdout

    def _estimate_tokens(self, text: str) -> int:
        # Estimación gruesa: 1 token ≈ 4 caracteres
        return len(text) // 4

    def _extract_json(self, text: str) -> str:
        # Extrae bloque ```json ... ``` del output del planner
        import re
        match = re.search(r"```json\s*([\s\S]+?)```", text)
        return match.group(1) if match else text
```

---

## Gemini Provider (providers/gemini.py)

Usa el CLI `gemini` de Google. Tier gratuito tiene 1500 req/día y 1M tokens/min.

```python
import subprocess
import time
from providers.base import ProviderBase
from harness.protocols import Step, StepResult, TaskPlan

class GeminiProvider(ProviderBase):
    name = "gemini"
    roles = ["planner", "executor"]
    priority = 2  # Segunda opción: tier gratuito

    def __init__(self, planner_model: str = "gemini-2.5-pro",
                 executor_model: str = "gemini-2.0-flash"):
        self.planner_model = planner_model
        self.executor_model = executor_model

    def generate_plan(self, task: str, context: str = "") -> TaskPlan:
        system = Path("config/prompts/planner.md").read_text()
        prompt = f"{system}\n\n# Task\n{task}\n\n# Context\n{context}"
        raw = self._run_cli(self.planner_model, prompt)
        data = json.loads(self._extract_json(raw))
        return TaskPlan(**data, planner_used=self.name)

    def execute_step(self, step: Step, plan_context: str = "") -> StepResult:
        system = Path("config/prompts/executor.md").read_text()
        prompt = (
            f"{system}\n\n"
            f"Step {step.index}: {step.description}\n"
            f"Files: {', '.join(step.target_files)}"
        )
        start = time.time()
        raw = self._run_cli(self.executor_model, prompt)
        duration = time.time() - start
        return StepResult(
            step_index=step.index,
            success=True,
            output=raw,
            tokens_used=len(prompt + raw) // 4,
            executor_used=self.name,
            duration_seconds=duration,
        )

    def _run_cli(self, model: str, prompt: str) -> str:
        """
        gemini CLI: gemini -m <model> "<prompt>"
        Para prompts largos usa stdin con echo o archivo temporal.
        """
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(prompt)
            tmp = f.name
        try:
            result = subprocess.run(
                ["gemini", "-m", model, f"@{tmp}"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                raise RuntimeError(f"gemini CLI error: {result.stderr}")
            return result.stdout
        finally:
            os.unlink(tmp)
```

---

## OpenCode Provider (providers/opencode.py)

Fallback de pago. Útil cuando Claude y Gemini están agotados.

```python
import subprocess
from providers.base import ProviderBase
from harness.protocols import Step, StepResult, TaskPlan

class OpencodeProvider(ProviderBase):
    name = "opencode"
    roles = ["planner", "executor"]
    priority = 10  # Última opción: pago por token

    def __init__(self, planner_model: str = "gpt-4o",
                 executor_model: str = "gpt-4o-mini"):
        self.planner_model = planner_model
        self.executor_model = executor_model

    def generate_plan(self, task: str, context: str = "") -> TaskPlan:
        prompt = f"# Task\n{task}\n\n# Context\n{context}"
        raw = self._run_cli(self.planner_model, prompt)
        data = json.loads(self._extract_json(raw))
        return TaskPlan(**data, planner_used=self.name)

    def execute_step(self, step: Step, plan_context: str = "") -> StepResult:
        prompt = f"Execute step: {step.description}\nFiles: {', '.join(step.target_files)}"
        import time
        start = time.time()
        raw = self._run_cli(self.executor_model, prompt)
        return StepResult(
            step_index=step.index,
            success=True,
            output=raw,
            tokens_used=len(prompt + raw) // 4,
            executor_used=self.name,
            duration_seconds=time.time() - start,
        )

    def _run_cli(self, model: str, prompt: str) -> str:
        """opencode run --model <model> --no-interactive "<prompt>" """
        result = subprocess.run(
            ["opencode", "run", "--model", model, "--no-interactive", prompt],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"opencode error: {result.stderr}")
        return result.stdout
```

---

## Orchestrator Principal (harness/orchestrator.py)

```python
from harness.router import Router
from harness.budget import BudgetManager
from harness.protocols import TaskPlan, StepResult, TaskResult
from harness.classifier import classify_complexity
import hashlib, json, time
from pathlib import Path

PLAN_CACHE = Path(".harness/plan_cache.json")

class MetaOrchestrator:
    def __init__(self, router: Router, budget: BudgetManager):
        self.router = router
        self.budget = budget
        self._cache: dict = self._load_cache()

    def run(self, task_description: str, context_files: list[str] = [],
            force_replan: bool = False) -> TaskResult:
        
        complexity = classify_complexity(task_description)
        context = self._build_context(context_files)
        
        # 1. PLANNING PHASE
        plan = self._get_or_create_plan(task_description, context, complexity, force_replan)
        
        # 2. EXECUTION PHASE
        step_results = []
        plan_context = plan.model_dump_json(indent=2)
        
        for step in plan.steps:
            # Verifica dependencias
            if not self._dependencies_met(step, step_results):
                step_results.append(StepResult(
                    step_index=step.index,
                    success=False,
                    output="Dependencias no cumplidas",
                    tokens_used=0,
                    executor_used="none",
                    duration_seconds=0,
                    error="dependency_failed",
                ))
                continue

            executor = self.router.select("executor", complexity)
            result = executor.execute_step(step, plan_context)
            self.budget.record(executor.name, result.tokens_used)
            step_results.append(result)
            
            if not result.success:
                # Reintentar con otro executor si hay failover disponible
                fallback = self._try_fallback_executor(step, plan_context, executor.name)
                if fallback:
                    step_results[-1] = fallback

        return TaskResult(
            task_id=plan.task_id,
            plan=plan,
            step_results=step_results,
            success=all(r.success for r in step_results),
            total_tokens=sum(r.tokens_used for r in step_results),
            total_duration_seconds=sum(r.duration_seconds for r in step_results),
        )

    def _get_or_create_plan(self, task: str, context: str,
                             complexity: str, force: bool) -> TaskPlan:
        cache_key = hashlib.sha256(f"{task}{context}".encode()).hexdigest()[:16]
        
        if not force and cache_key in self._cache:
            return TaskPlan(**self._cache[cache_key])

        planner = self.router.select("planner", complexity)
        plan = planner.generate_plan(task, context)
        self.budget.record(planner.name, plan.estimated_tokens)
        
        self._cache[cache_key] = plan.model_dump()
        self._save_cache()
        return plan

    def _try_fallback_executor(self, step, context: str,
                                exclude: str) -> StepResult | None:
        fallbacks = [
            p for p in self.router.providers
            if p.name != exclude
            and p.supports_role("executor")
            and self.budget.has_capacity(p.name, "executor")
        ]
        if not fallbacks:
            return None
        result = fallbacks[0].execute_step(step, context)
        self.budget.record(fallbacks[0].name, result.tokens_used)
        return result

    def _dependencies_met(self, step, results: list[StepResult]) -> bool:
        completed = {r.step_index for r in results if r.success}
        return all(d in completed for d in step.depends_on)

    def _build_context(self, files: list[str]) -> str:
        parts = []
        for path in files:
            p = Path(path)
            if p.exists():
                parts.append(f"### {path}\n```\n{p.read_text()[:3000]}\n```")
        return "\n\n".join(parts)

    def _load_cache(self) -> dict:
        if PLAN_CACHE.exists():
            return json.loads(PLAN_CACHE.read_text())
        return {}

    def _save_cache(self):
        PLAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PLAN_CACHE.write_text(json.dumps(self._cache, indent=2))
```

---

## Clasificador de Complejidad (harness/classifier.py)

```python
import re

def classify_complexity(task: str) -> str:
    """
    Heurística rápida y local (sin consumir tokens).
    Patrones que indican alta complejidad:
    """
    task_lower = task.lower()
    
    HIGH_SIGNALS = [
        r"\brefactor\b", r"\barquitectura\b", r"\bmigra\w+\b",
        r"\bdiseño\b", r"\bsistema\b", r"\bmúltiples módulos\b",
        r"\bintegra\w+\b", r"\bdependencias\b",
    ]
    LOW_SIGNALS = [
        r"\bfix\b", r"\bcorrige\b", r"\btipo\b", r"\brenombra\b",
        r"\bagrega un método\b", r"\bcomenta\b", r"\bdocumenta\b",
    ]
    
    high_score = sum(1 for p in HIGH_SIGNALS if re.search(p, task_lower))
    low_score = sum(1 for p in LOW_SIGNALS if re.search(p, task_lower))
    
    if high_score >= 2:
        return "high"
    if low_score >= 2:
        return "low"
    return "medium"
```

---

## Configuración de Providers (config/providers.yaml)

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
      # Límites conservadores para suscripción Max
      daily_tokens: 2000000
      monthly_tokens: 50000000
    flags:
      planner: ["--print"]
      executor: ["--print"]
    auth_env: ANTHROPIC_API_KEY   # solo para fallback API directa

  gemini:
    cli: gemini
    priority: 2
    roles: [planner, executor]
    models:
      planner: gemini-2.5-pro
      executor: gemini-2.0-flash
    limits:
      # Tier gratuito de Google AI Studio
      daily_requests: 1500
      rpm: 15
    auth_env: GOOGLE_API_KEY

  opencode:
    cli: opencode
    priority: 10
    roles: [planner, executor]
    models:
      planner: gpt-4o
      executor: gpt-4o-mini
    limits:
      daily_tokens: 500000   # presupuesto diario en tokens
    auth_env: OPENAI_API_KEY

  cursor:
    cli: cursor           # modo headless experimental
    priority: 3
    roles: [executor]
    models:
      executor: composer  # nombre interno de Cursor
    limits:
      daily_requests: 500
    auth_env: CURSOR_SESSION_TOKEN
```

---

## Estrategias de Optimización de Tokens

### 1. Cache de Planes

Cuando una tarea es idéntica o muy similar (mismo hash SHA-256 de descripción + contexto), el plan ya generado se reutiliza sin llamar al planner de nuevo. Ahorro típico: **100% del costo del planner en tareas repetidas**.

### 2. Compresión de Contexto

Antes de enviar archivos al modelo, el orchestrator:
- Trunca archivos a los primeros 3000 caracteres (configurable)
- Omite archivos sin relación semántica con el task (TF-IDF simple)
- Colapsa importaciones repetitivas con `# ... (N imports omitted)`

### 3. Prompt Caching de Anthropic

Para Claude Code, el system prompt del planner/executor se mantiene constante y se beneficia del [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) automático. Requiere que el system prompt supere 1024 tokens. Ahorro típico: **60-80% en llamadas repetidas**.

```python
# El system prompt se carga una vez y se pasa siempre en la misma posición
PLANNER_SYSTEM = Path("config/prompts/planner.md").read_text()
# claude CLI lo cachea automáticamente si el contenido no cambia
```

### 4. Ejecución Paralela de Steps Independientes

Los steps sin dependencias entre sí se ejecutan en paralelo usando `asyncio.gather`:

```python
import asyncio

async def execute_parallel_steps(steps_batch, executor, plan_context):
    tasks = [executor.execute_step(s, plan_context) for s in steps_batch]
    return await asyncio.gather(*tasks)
```

Esto reduce el tiempo total de ejecución sin aumentar el consumo de tokens.

### 5. Modelo Correcto para Cada Tipo de Tarea

| Tipo de operación | Modelo recomendado | Razón |
|-------------------|-------------------|-------|
| Generar plan arquitectónico | claude-opus-4-7 / gemini-2.5-pro | Razonamiento largo |
| Implementar función definida | claude-haiku-4-5 / gemini-2.0-flash | Contexto claro, velocidad |
| Fix de un bug con stack trace | claude-haiku-4-5 | Contexto pequeño |
| Refactor de sistema completo | claude-opus-4-7 | Coherencia global |
| Escribir tests unitarios | gpt-4o-mini / gemini-flash | Tarea mecánica |
| Revisar código de seguridad | claude-opus-4-7 | Razonamiento profundo |

---

## Prompts del Sistema

### config/prompts/planner.md

```markdown
Eres un arquitecto de software que genera planes de implementación estructurados.

Dado un task de desarrollo, produce EXACTAMENTE un JSON con este schema:
{
  "task_id": "<uuid>",
  "complexity": "low|medium|high",
  "summary": "<1 oración que describe el objetivo>",
  "estimated_tokens": <int>,
  "context_files": ["<archivos relevantes>"],
  "steps": [
    {
      "index": 0,
      "description": "<qué hacer en lenguaje imperativo>",
      "target_files": ["<archivo.py>"],
      "validation": "<cómo verificar que el step tuvo éxito>",
      "expected_output": "<qué debe cambiar o producirse>",
      "depends_on": []
    }
  ]
}

Reglas:
- Cada step debe ser atómico (ejecutable de forma independiente por un modelo sin contexto previo)
- Máximo 8 steps por plan
- Especifica archivos concretos, no directorios
- depends_on lista índices de steps que deben completarse primero
- Devuelve SOLO el JSON dentro de un bloque ```json
```

### config/prompts/executor.md

```markdown
Eres un ingeniero de software senior implementando un step específico de un plan.

Recibirás:
1. El plan completo como contexto (para entender el objetivo global)
2. El step específico a implementar

Tu trabajo:
- Implementar SOLO el step indicado
- Devolver los cambios de código como diffs o el archivo completo si es nuevo
- Si el step falla, explicar el error en detalle
- No implementar steps futuros
- No reformatear código no relacionado
```

---

## CLI Entry Point (main.py)

```python
import typer
import yaml
from pathlib import Path
from rich.table import Table
from rich import print as rprint

from harness.orchestrator import MetaOrchestrator
from harness.router import Router
from harness.budget import BudgetManager, ProviderLimits
from providers.claude_code import ClaudeCodeProvider
from providers.gemini import GeminiProvider
from providers.opencode import OpencodeProvider

app = typer.Typer(name="harness", help="Meta-harness de agentes de IA")

def _build_orchestrator() -> MetaOrchestrator:
    config = yaml.safe_load(Path("config/providers.yaml").read_text())
    
    providers = [
        ClaudeCodeProvider(
            planner_model=config["providers"]["claude_code"]["models"]["planner"],
            executor_model=config["providers"]["claude_code"]["models"]["executor"],
        ),
        GeminiProvider(
            planner_model=config["providers"]["gemini"]["models"]["planner"],
            executor_model=config["providers"]["gemini"]["models"]["executor"],
        ),
        OpencodeProvider(
            planner_model=config["providers"]["opencode"]["models"]["planner"],
            executor_model=config["providers"]["opencode"]["models"]["executor"],
        ),
    ]
    
    limits = {
        name: ProviderLimits(**{
            k: v for k, v in cfg.get("limits", {}).items()
        })
        for name, cfg in config["providers"].items()
    }
    
    budget = BudgetManager(limits)
    router = Router(providers, budget)
    return MetaOrchestrator(router, budget)


@app.command()
def run(
    task: str = typer.Argument(..., help="Descripción del task a ejecutar"),
    context: list[str] = typer.Option([], "--context", "-c", help="Archivos de contexto"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo genera el plan, no ejecuta"),
    force_replan: bool = typer.Option(False, "--force-replan", help="Ignora cache de planes"),
):
    """Ejecuta un task usando el mejor agente disponible."""
    orchestrator = _build_orchestrator()
    
    if dry_run:
        planner = orchestrator.router.select("planner")
        plan = planner.generate_plan(task, "")
        rprint(plan.model_dump_json(indent=2))
        return
    
    result = orchestrator.run(task, list(context), force_replan)
    
    if result.success:
        rprint(f"[green]✓ Task completado[/green] — {result.total_tokens:,} tokens en {result.total_duration_seconds:.1f}s")
    else:
        failed = [r for r in result.step_results if not r.success]
        rprint(f"[red]✗ Fallaron {len(failed)} steps[/red]")
        for r in failed:
            rprint(f"  Step {r.step_index}: {r.error}")


@app.command()
def status():
    """Muestra el estado de uso de cada provider."""
    orchestrator = _build_orchestrator()
    info = orchestrator.router.status()
    
    table = Table(title="Estado de Providers")
    table.add_column("Provider")
    table.add_column("Planner")
    table.add_column("Executor")
    table.add_column("Se agota en")
    
    for name, data in info.items():
        table.add_row(
            name,
            "[green]OK[/green]" if data["has_capacity_planner"] else "[red]AGOTADO[/red]",
            "[green]OK[/green]" if data["has_capacity_executor"] else "[red]AGOTADO[/red]",
            data.get("projected_exhaustion", "N/A"),
        )
    
    rprint(table)


@app.command()
def usage():
    """Muestra el consumo de tokens del día de hoy."""
    from harness.budget import USAGE_FILE
    import json
    from datetime import date
    
    if not USAGE_FILE.exists():
        rprint("Sin datos de uso todavía.")
        return
    
    today = date.today().isoformat()
    totals: dict[str, int] = {}
    
    for line in USAGE_FILE.read_text().splitlines():
        try:
            entry = json.loads(line)
            if entry["date"] == today:
                p = entry["provider"]
                totals[p] = totals.get(p, 0) + entry.get("tokens", 0)
        except (json.JSONDecodeError, KeyError):
            continue
    
    table = Table(title=f"Uso de tokens — {today}")
    table.add_column("Provider")
    table.add_column("Tokens hoy", justify="right")
    
    for provider, tokens in sorted(totals.items(), key=lambda x: -x[1]):
        table.add_row(provider, f"{tokens:,}")
    
    rprint(table)


if __name__ == "__main__":
    app()
```

---

## Lógica de Failover — Diagrama de Flujo

```
Task recibido
     │
     ▼
Classify complexity
     │
     ▼
Select PLANNER (priority order):
  1. claude_code (Opus)      ──has_capacity?──► NO ──┐
  2. gemini (2.5-pro)        ──has_capacity?──► NO ──┤
  3. opencode (gpt-4o)       ──has_capacity?──► NO ──┤
                                                     ▼
                                              RuntimeError (todos agotados)
     │
     ▼ (primer provider con capacity)
Generate Plan ──► Cache plan
     │
     ▼
Por cada Step:
     │
     ├── Select EXECUTOR (priority order):
     │     1. claude_code (Haiku)  ──► NO ──┐
     │     2. gemini (flash)       ──► NO ──┤
     │     3. opencode (gpt-4o-mini) ─► NO ──┤
     │                                       ▼ usar fallback o abortar
     │
     ├── Execute Step
     │     │
     │     ├── SUCCESS ──► record usage ──► next step
     │     │
     │     └── FAILURE ──► try fallback executor ──► retry
     │                           │
     │                     SUCCESS ──► record + next step
     │                     FAILURE ──► mark step failed + continue
     │
     ▼
Aggregate TaskResult ──► sync to Notion (opcional)
```

---

## Integración con el Quetz-Orchestrator Existente

El meta-harness se integra en el orchestrator actual extendiendo `AgentBase`:

```python
# orchestrator/agents/meta_harness_agent.py

from orchestrator.agents.base import AgentBase
from orchestrator.task import Task

class MetaHarnessAgent(AgentBase):
    """
    Delega al meta-harness cuando el task es muy complejo
    o cuando Claude Code y los otros agentes simples han fallado.
    """
    name = "meta_harness"

    def run(self, task: Task) -> str:
        from meta_harness.harness.orchestrator import MetaOrchestrator
        from meta_harness.main import _build_orchestrator
        
        orchestrator = _build_orchestrator()
        context_files = task.metadata.get("context_files", [])
        result = orchestrator.run(task.spec_content, context_files)
        
        return "\n".join(r.output for r in result.step_results if r.success)
```

Registrar en `config/agent_config.yaml`:
```yaml
agents:
  meta_harness:
    class: MetaHarnessAgent
    complexity_min: high    # solo recibe tasks de alta complejidad
    timeout: 600
```

---

## Dependencias del Proyecto

```toml
# pyproject.toml
[project]
name = "quetz-meta-harness"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "pydantic>=2.7",
    "typer[all]>=0.12",
    "rich>=13",
    "pyyaml>=6",
    "python-dotenv>=1.0",
    "httpx>=0.27",      # para Notion sync
    "aiofiles>=23",     # ejecución async de steps
]

[project.scripts]
harness = "main:app"
```

```bash
pip install -e .
harness run "implementa autenticación JWT en FastAPI" -c app/main.py -c app/models.py
harness status
harness usage
```

---

## Variables de Entorno (.env)

```bash
# Anthropic — solo si se usa API directa (no CLI suscripción)
ANTHROPIC_API_KEY=sk-ant-...

# Google AI Studio — gratuito
GOOGLE_API_KEY=AIza...

# OpenAI — fallback de pago
OPENAI_API_KEY=sk-...

# Notion — sync de tasks
NOTION_TOKEN=secret_...
NOTION_DATABASE_ID=...

# Cursor headless (experimental)
CURSOR_SESSION_TOKEN=...
```

---

## Roadmap de Implementación

### Fase 1 — Fundación (1-2 días)
- [ ] Implementar `protocols.py`, `budget.py`, `base.py`
- [ ] Implementar `ClaudeCodeProvider` con `--print` flag
- [ ] CLI básico: `harness run`, `harness status`
- [ ] Pruebas con tasks simples (complejidad low)

### Fase 2 — Multi-provider (2-3 días)
- [ ] Implementar `GeminiProvider`
- [ ] Implementar `Router` con failover
- [ ] Cache de planes en `plan_cache.json`
- [ ] Clasificador de complejidad

### Fase 3 — Optimización (2-3 días)
- [ ] Compresión de contexto antes de enviar al modelo
- [ ] Ejecución paralela de steps independientes
- [ ] Supervisor para verificar outputs
- [ ] `OpencodeProvider` como último fallback

### Fase 4 — Integración (1 día)
- [ ] `MetaHarnessAgent` en el orchestrator existente
- [ ] Sync de resultados a Notion
- [ ] Dashboard de uso con `harness usage`

---

## Notas Importantes

- **claude CLI `--print` flag**: hace que el CLI sea no-interactivo y devuelva solo el texto de respuesta. Es la forma correcta de llamar a Claude Code desde scripts.
- **Gemini CLI**: soporta `@archivo.txt` para prompts largos, evitando límites de argumento de shell.
- **Cursor headless**: experimental, requiere que Cursor esté instalado y el usuario autenticado. La sesión se mantiene en `~/.cursor/`.
- **Reset de límites**: los límites de Gemini free tier y Claude Code se resetean a medianoche UTC. El `BudgetManager` lee solo entradas del día actual en `usage.jsonl`.
- **Token estimation**: la estimación `len(text) // 4` es una aproximación. Para exactitud, usar `tiktoken` (OpenAI) o la API de Anthropic con `count_tokens`.
