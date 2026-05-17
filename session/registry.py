from pathlib import Path
from harness.protocols import ProjectProfile
from datetime import datetime
import json

PROJECTS_ROOT = Path.home() / ".ai-harness" / "projects"


class ProjectRegistry:
    """
    Gestiona el registro de proyectos conocidos por el harness.
    Cada proyecto tiene un perfil con su nombre y ruta de directorio.
    """

    def list_projects(self) -> list[ProjectProfile]:
        """
        Retorna todos los proyectos registrados, ordenados por last_used
        (el más reciente primero).
        """
        profiles = []
        if not PROJECTS_ROOT.exists():
            return profiles

        for project_dir in PROJECTS_ROOT.iterdir():
            profile_file = project_dir / "profile.json"
            if profile_file.exists():
                try:
                    profile = ProjectProfile(**json.loads(profile_file.read_text()))
                    profiles.append(profile)
                except Exception:
                    continue

        return sorted(profiles, key=lambda p: p.last_used, reverse=True)

    def get(self, slug: str) -> ProjectProfile | None:
        """Carga el perfil de un proyecto por su slug."""
        profile_file = PROJECTS_ROOT / slug / "profile.json"
        if not profile_file.exists():
            return None
        try:
            return ProjectProfile(**json.loads(profile_file.read_text()))
        except Exception:
            return None

    def save(self, profile: ProjectProfile) -> None:
        """Guarda o actualiza el perfil de un proyecto."""
        project_dir = PROJECTS_ROOT / profile.slug
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "profile.json").write_text(
            profile.model_dump_json(indent=2), encoding="utf-8"
        )

    def touch(self, slug: str) -> None:
        """Actualiza last_used del proyecto al momento actual."""
        profile = self.get(slug)
        if profile:
            profile.last_used = datetime.utcnow()
            self.save(profile)

    def exists(self, slug: str) -> bool:
        return (PROJECTS_ROOT / slug / "profile.json").exists()

    def validate_dir(self, path: str) -> tuple[bool, str]:
        """
        Valida que la ruta proporcionada existe y es un directorio.
        Retorna (es_válida, mensaje_de_error).
        """
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return False, f"La ruta no existe: {p}"
        if not p.is_dir():
            return False, f"La ruta no es un directorio: {p}"
        return True, ""
