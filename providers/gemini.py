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

    def __init__(self, model: str = "gemini-2.0-flash", project_dir: str = ".", timeout: int = 120):
        self.model        = model
        self.project_dir  = project_dir
        self.timeout      = timeout

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
                cwd=self.project_dir,
            )
            if result.returncode != 0:
                if "429" in result.stderr or "RESOURCE_EXHAUSTED" in result.stderr:
                    time.sleep(60)
                    result = subprocess.run(
                        ["gemini", "--model", self.model, f"@{tmp}"],
                        capture_output=True, text=True, timeout=self.timeout,
                        cwd=self.project_dir,
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
