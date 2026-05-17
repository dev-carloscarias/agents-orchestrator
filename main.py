import os
import sys
import shutil
import traceback

from dotenv import load_dotenv
import yaml
from pathlib import Path

from harness.budget import BudgetManager
from harness.router import build_router_from_config
from harness.orchestrator import Orchestrator
from session.manager import SessionManager
from harness.protocols import ProjectProfile
from providers.claude_code import ClaudeCodeProvider
from providers.gemini import GeminiProvider
from providers.opencode import OpenCodeProvider, FREE_MODELS
from providers.base import ProviderBase


def load_config() -> dict:
    load_dotenv()
    providers_cfg = yaml.safe_load(Path("config/providers.yaml").read_text(encoding="utf-8"))
    routing_cfg   = yaml.safe_load(Path("config/routing_rules.yaml").read_text(encoding="utf-8"))

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


def build_providers(project_dir: str) -> list[ProviderBase]:
    """
    Construye la lista de providers configurados para operar
    en la carpeta del proyecto activo.
    """
    providers: list[ProviderBase] = []

    if shutil.which("claude"):
        providers.append(ClaudeCodeProvider(
            model="claude-sonnet-4-6",
            project_dir=project_dir,
            priority=1,
        ))
        providers.append(ClaudeCodeProvider(
            model="claude-opus-4-6",
            project_dir=project_dir,
            priority=99,
        ))

    if shutil.which("gemini"):
        providers.append(GeminiProvider(
            model="gemini-2.0-flash",
            project_dir=project_dir,
        ))

    if shutil.which("opencode"):
        for model in FREE_MODELS:
            providers.append(OpenCodeProvider(
                model=model,
                project_dir=project_dir,
            ))

    if not providers:
        raise RuntimeError(
            "No hay ningún provider disponible.\n"
            "Verifica que claude y/o gemini CLI estén instalados."
        )

    return providers


def build_orchestrator(
    profile: ProjectProfile,
    session: SessionManager,
    budget: BudgetManager | None = None,
) -> Orchestrator:
    """
    Construye el orchestrator completo para el proyecto activo.
    Se llama cada vez que el usuario cambia de proyecto o de task.
    """
    load_config()
    b = budget or BudgetManager()
    providers = build_providers(profile.project_dir)
    router = build_router_from_config(providers, b)
    return Orchestrator(router, b, session, project_dir=profile.project_dir)


def main() -> None:
    try:
        from console.app import ConsoleApp
        ConsoleApp().run()
    except KeyboardInterrupt:
        print("\nSaliendo…")
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
