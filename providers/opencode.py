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

    def __init__(self, model: str, project_dir: str, timeout: int = 150):
        if not shutil.which("opencode"):
            raise EnvironmentError("opencode CLI no encontrado. Instalar: npm install -g opencode-ai")
        self.model        = model
        self.project_dir  = project_dir
        self.timeout      = timeout
        self.name, self.priority = FREE_MODELS.get(model, ("opencode_unknown", 10))

    @classmethod
    def build_chain(cls, project_dir: str) -> list["OpenCodeProvider"]:
        """Construye la cadena completa de fallbacks gratuitos."""
        providers = []
        for model in FREE_MODELS:
            try:
                providers.append(cls(model=model, project_dir=project_dir))
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
            cwd=self.project_dir,
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
                cwd=self.project_dir,
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
