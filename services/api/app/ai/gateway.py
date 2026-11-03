"""Provider-independent AI gateway: routing, budgets, usage accounting, strict output validation.

Providers are *configured*, never assumed. With no provider configured the gateway raises `NoProvider` and callers
fall back to deterministic output (clearly labelled). Only evidence-grounded prompts are built by callers; this module
enforces input/output bounds and the org's daily budget.
"""
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models import AiUsage

log = get_logger("ai")
PROMPT_VERSION = "grounded-v1"


class NoProvider(AppError):
    status_code, code = 503, "no_ai_provider"


class BudgetExceeded(AppError):
    status_code, code = 429, "ai_budget_exceeded"


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str
    model: str
    async def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion: ...


@dataclass(frozen=True)
class Price:
    """Explicit, dated price entry supplied via configuration (VAND_AI_PRICING_JSON). Nothing is built in or guessed."""
    model: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    effective_date: str
    source: str


def load_pricing(raw: str) -> dict[str, Price]:
    if not raw.strip():
        return {}
    return {p["model"]: Price(p["model"], float(p["input_per_mtok_usd"]), float(p["output_per_mtok_usd"]), p["effective_date"], p["source"])
            for p in json.loads(raw)}


def estimate_cost(pricing: dict[str, Price], model: str, input_tokens: int, output_tokens: int) -> float | None:
    """None => USD cost unavailable (no configured price). Callers must show tokens only in that case."""
    pr = pricing.get(model)
    return None if pr is None else (input_tokens * pr.input_per_mtok_usd + output_tokens * pr.output_per_mtok_usd) / 1_000_000


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, key: str, model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.key, self.model, self.transport = key, model, transport

    async def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            d = r.json()
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        u = d.get("usage", {})
        return Completion(text, self.name, self.model, u.get("input_tokens", 0), u.get("output_tokens", 0))


class OpenAIProvider:
    name = "openai"

    def __init__(self, key: str, model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.key, self.model, self.transport = key, model, transport

    async def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as c:
            r = await c.post("https://api.openai.com/v1/chat/completions", headers={"authorization": f"Bearer {self.key}"},
                             json={"model": self.model, "max_completion_tokens": max_tokens,
                                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            d = r.json()
        u = d.get("usage", {})
        return Completion(d["choices"][0]["message"]["content"] or "", self.name, self.model,
                          u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


class AIGateway:
    redis: Any = None  # set by the app at startup for operational counters

    def __init__(self, settings: Settings, providers: list[Provider] | None = None):
        self.s = settings
        self.pricing = load_pricing(settings.ai_pricing_json)
        if providers is not None:
            self.providers = providers
        else:
            built: dict[str, Provider] = {}
            if settings.anthropic_api_key:
                built["anthropic"] = AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
            if settings.openai_api_key and settings.openai_model:
                built["openai"] = OpenAIProvider(settings.openai_api_key, settings.openai_model)
            order = [n.strip() for n in settings.ai_provider_order.split(",")]
            self.providers = [built[n] for n in order if n in built]

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    async def tokens_today(self, session: AsyncSession) -> int:
        """Provider-independent budget unit (tokens). USD cost is recorded as an estimate only when PRICES is configured."""
        q = select(func.coalesce(func.sum(AiUsage.input_tokens + AiUsage.output_tokens), 0)).where(
            AiUsage.created_at >= func.date_trunc("day", func.now()))
        return int((await session.execute(q)).scalar_one())

    async def complete_json(self, session: AsyncSession, *, org_id: UUID, user_id: UUID | None, task: str,
                            system: str, user: str) -> tuple[dict[str, Any], Completion]:
        if not self.providers:
            raise NoProvider("No AI provider is configured")
        if len(user) > self.s.ai_max_input_chars:
            raise AppError("AI input exceeds the permitted size", )
        if await self.tokens_today(session) >= self.s.ai_org_daily_token_budget:
            raise BudgetExceeded("Daily AI token budget for this organization is exhausted")
        last: Exception | None = None
        for p in self.providers:
            t0 = time.monotonic()
            try:
                c = await p.complete(system, user, self.s.ai_max_output_tokens, self.s.ai_timeout_seconds)
                parsed = json.loads(_extract_json(c.text))
                if not isinstance(parsed, dict):
                    raise ValueError("model output is not a JSON object")
            except Exception as exc:  # noqa: BLE001 - provider/format failure => record + try next provider
                last = exc
                log.warning("ai_call_failed", extra={"provider": p.name, "err": type(exc).__name__})
                if self.redis is not None:
                    await metrics.incr(self.redis, "ai.failed")
                session.add(AiUsage(org_id=org_id, user_id=user_id, task=task, provider=p.name, model=p.model,
                                    prompt_version=PROMPT_VERSION, status="failed", latency_ms=int((time.monotonic() - t0) * 1000)))
                continue
            est = estimate_cost(self.pricing, p.model, c.input_tokens, c.output_tokens)
            cost = Decimal(str(est)) if est is not None else Decimal(0)  # stored 0 + reported as unavailable when no price is configured
            session.add(AiUsage(org_id=org_id, user_id=user_id, task=task, provider=p.name, model=p.model,
                                prompt_version=PROMPT_VERSION, input_tokens=c.input_tokens, output_tokens=c.output_tokens,
                                cost_usd=cost, status="ok", latency_ms=int((time.monotonic() - t0) * 1000)))
            if self.redis is not None:
                await metrics.incr(self.redis, "ai.calls")
                await metrics.incr(self.redis, "ai.tokens", c.input_tokens + c.output_tokens)
            return parsed, c
        raise AppError("AI providers failed", reason=type(last).__name__ if last else "unknown")


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text
