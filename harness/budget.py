import json, time
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional, Literal
from rich.console import Console

USAGE_FILE = Path.home() / ".ai-harness" / "usage.jsonl"
console    = Console()

_tiktoken_warned = False


def count_tokens(text: str) -> int:
    """Token counting real. Fallback a len//4 si tiktoken no está instalado."""
    global _tiktoken_warned
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        if not _tiktoken_warned:
            console.print(
                "[yellow]⚠  tiktoken no instalado o no disponible — token counting aproximado "
                "(len//4). Instala con: pip install tiktoken[/yellow]"
            )
            _tiktoken_warned = True
        return len(text) // 4


@dataclass
class ProviderLimits:
    window_type:  Literal["daily", "rolling"] = "daily"
    window_hours: int   = 24       # para rolling: tamaño de la ventana
    max_requests: Optional[int] = None
    max_tokens:   Optional[int] = None
    warn_at:      float = 0.70
    critical_at:  float = 0.85


# Límites por provider
PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    "claude_sonnet": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=80,       # estimado conservador para Pro
        warn_at=0.60, critical_at=0.80,
    ),
    "claude_opus": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=20,
        warn_at=0.50, critical_at=0.70,
    ),
    "gemini_flash": ProviderLimits(
        window_type="daily",
        max_requests=1500,
        warn_at=0.75, critical_at=0.90,
    ),
    "opencode_minimax": ProviderLimits(
        window_type="daily",
        max_requests=300,      # estimado — no publicado oficialmente
        warn_at=0.80, critical_at=0.95,
    ),
    "opencode_bigpickle": ProviderLimits(
        window_type="rolling", window_hours=5,
        max_requests=200,
        warn_at=0.75, critical_at=0.90,
    ),
}


@dataclass
class ProviderUsage:
    provider:        str
    tokens_today:    int   = 0
    requests_today:  int   = 0
    tokens_month:    int   = 0
    # Para ventanas rolling: timestamps de requests recientes
    request_times:   list  = None

    def __post_init__(self):
        if self.request_times is None:
            self.request_times = []


class BudgetManager:
    def __init__(self):
        self._usage: dict[str, ProviderUsage] = {}
        self._load_today()

    def record(self, provider: str, prompt: str, response: str, requests: int = 1) -> int:
        """
        Registra uso real. Devuelve tokens contados.
        """
        tokens = count_tokens(prompt + response)
        usage  = self._usage.setdefault(provider, ProviderUsage(provider))
        usage.tokens_today   += tokens
        usage.tokens_month   += tokens
        usage.requests_today += requests
        usage.request_times.append(time.time())
        self._append_log(provider, tokens, requests)
        self._check_alert(provider, usage)
        return tokens

    def has_capacity(self, provider: str) -> bool:
        limits = PROVIDER_LIMITS.get(provider)
        if not limits:
            return True
        usage = self._usage.get(provider, ProviderUsage(provider))

        if limits.window_type == "rolling":
            # Contar requests dentro de la ventana
            cutoff  = time.time() - limits.window_hours * 3600
            recent  = sum(1 for t in usage.request_times if t > cutoff)
            if limits.max_requests and recent >= limits.max_requests * limits.critical_at:
                return False
        else:
            if limits.max_requests and usage.requests_today >= limits.max_requests * limits.critical_at:
                return False
            if limits.max_tokens and usage.tokens_today >= limits.max_tokens * limits.critical_at:
                return False
        return True

    def alert_level(self, provider: str) -> str:
        """Retorna: "ok" | "warn" | "critical" """
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return "ok"
        usage = self._usage.get(provider, ProviderUsage(provider))

        if limits.window_type == "rolling":
            cutoff = time.time() - limits.window_hours * 3600
            count  = sum(1 for t in usage.request_times if t > cutoff)
        else:
            count = usage.requests_today

        ratio = count / limits.max_requests
        if ratio >= limits.critical_at:
            return "critical"
        if ratio >= limits.warn_at:
            return "warn"
        return "ok"

    def daily_summary(self) -> dict[str, dict]:
        summary = {}
        for provider in list(PROVIDER_LIMITS.keys()):
            limits = PROVIDER_LIMITS[provider]
            usage  = self._usage.get(provider, ProviderUsage(provider))

            if limits.window_type == "rolling":
                cutoff  = time.time() - limits.window_hours * 3600
                req_now = sum(1 for t in usage.request_times if t > cutoff)
                req_max = limits.max_requests
            else:
                req_now = usage.requests_today
                req_max = limits.max_requests

            summary[provider] = {
                "requests_now":  req_now,
                "requests_max":  req_max,
                "tokens_today":  usage.tokens_today,
                "pct":           round(req_now / req_max * 100, 1) if req_max else None,
                "alert_level":   self.alert_level(provider),
                "window_type":   limits.window_type,
                "window_hours":  limits.window_hours,
            }
        return summary

    def projected_exhaustion(self, provider: str) -> Optional[str]:
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return None
        usage = self._usage.get(provider, ProviderUsage(provider))
        hour  = max(datetime.utcnow().hour, 1)
        rate  = usage.requests_today / hour
        if rate == 0:
            return None
        remaining = limits.max_requests - usage.requests_today
        return f"~{remaining / rate:.1f}h"

    def _check_alert(self, provider: str, usage: ProviderUsage):
        level  = self.alert_level(provider)
        limits = PROVIDER_LIMITS.get(provider)
        if not limits or not limits.max_requests:
            return
        pct = usage.requests_today / limits.max_requests * 100
        if level == "critical":
            console.print(
                f"\n[bold red]🚨 [{provider}] {pct:.0f}% del límite consumido[/bold red]"
            )
        elif level == "warn":
            console.print(
                f"\n[yellow]⚠  [{provider}] {pct:.0f}% del límite consumido[/yellow]"
            )

    def _append_log(self, provider: str, tokens: int, requests: int):
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("a") as f:
            f.write(json.dumps({
                "ts":       datetime.utcnow().isoformat(),
                "date":     date.today().isoformat(),
                "provider": provider,
                "tokens":   tokens,
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
                    u = self._usage.setdefault(p, ProviderUsage(p))
                    u.tokens_today   += entry.get("tokens", 0)
                    u.requests_today += entry.get("requests", 0)
                    u.tokens_month   += entry.get("tokens", 0)
            except (json.JSONDecodeError, KeyError):
                continue
