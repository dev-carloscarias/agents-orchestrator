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
