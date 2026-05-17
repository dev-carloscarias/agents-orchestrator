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
