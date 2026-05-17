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
      - ClaudeCodeProvider("claude-sonnet-4-6", project_dir, priority=1)  → default
      - ClaudeCodeProvider("claude-opus-4-6", project_dir, priority=99) → extra_high
    """
    roles = ["planner"]

    def __init__(self, model: str, project_dir: str, priority: int = 1, timeout: int = 240):
        self.model       = model
        self.project_dir = project_dir
        self.priority    = priority
        self.timeout     = timeout
        self.name        = f"claude_{'sonnet' if 'sonnet' in model else 'opus'}"

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
            cwd=self.project_dir,
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
