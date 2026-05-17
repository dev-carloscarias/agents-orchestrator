from rich.console import Console
from rich.prompt import Confirm
from harness.budget import BudgetManager
from providers.base import ProviderBase
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
    config = yaml.safe_load(Path("config/routing_rules.yaml").read_text(encoding="utf-8"))
    return Router(providers, budget, config)
