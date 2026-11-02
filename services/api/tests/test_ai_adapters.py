import json

import httpx
import pytest

from app.ai.gateway import AIGateway, AnthropicProvider, OpenAIProvider, estimate_cost, load_pricing
from app.core.config import Settings
from app.core.errors import AppError
from tests.conftest import uniq

API = "/api/v1"


def transport(handler):
    return httpx.MockTransport(handler)


async def test_anthropic_request_schema_and_response_parsing():
    seen = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), headers=dict(req.headers), body=json.loads(req.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"a":1}'}], "usage": {"input_tokens": 11, "output_tokens": 7}})
    p = AnthropicProvider("sk-test", "model-x", transport(h))
    c = await p.complete("SYS", "USER", 300, 5)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["headers"]["anthropic-version"]
    assert seen["body"] == {"model": "model-x", "max_tokens": 300, "system": "SYS", "messages": [{"role": "user", "content": "USER"}]}
    assert (c.text, c.input_tokens, c.output_tokens) == ('{"a":1}', 11, 7)


async def test_openai_request_schema_and_response_parsing():
    seen = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"b":2}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    c = await OpenAIProvider("sk-o", "m", transport(h)).complete("S", "U", 100, 5)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == "Bearer sk-o"
    assert seen["body"]["messages"] == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}] and seen["body"]["max_completion_tokens"] == 100
    assert (c.text, c.input_tokens, c.output_tokens) == ('{"b":2}', 5, 3)


async def test_provider_errors_timeouts_and_failover_with_accounting(client, make_env, app_ctx):
    _, app, gw = app_ctx
    env = await make_env("fo")
    calls = []

    def bad(req):  # provider 1: rate limited
        calls.append("p1")
        return httpx.Response(429, json={"error": "rate"})

    def timeout(req):
        calls.append("p1b")
        raise httpx.ReadTimeout("slow")

    def good(req):
        calls.append("p2")
        return httpx.Response(200, json={"choices": [{"message": {"content": 'noise {"ok": true} tail'}}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}})
    for first in (bad, timeout):
        calls.clear()
        gw.providers = [AnthropicProvider("k", "m1", transport(first)), OpenAIProvider("k", "m2", transport(good))]
        from app.core.db import Database, make_engine
        import uuid
        db = Database(make_engine(Settings().database_url))
        async with db.tenant_session(uuid.UUID(env.org_id)) as s:
            out, c = await gw.complete_json(s, org_id=uuid.UUID(env.org_id), user_id=None, task="t", system="s", user="u")
        await db.dispose()
        assert out == {"ok": True} and c.provider == "openai" and len(calls) == 2  # JSON extracted from surrounding text; failover happened
    usage = (await client.get(f"{API}/usage/ai", headers=env.h("auditor"))).json()["items"]
    by = {(u["provider"], u["status"]): u for u in usage}
    assert by[("anthropic", "failed")]["calls"] == 2 and by[("openai", "ok")]["input_tokens"] == 18  # failures accounted; tokens summed


async def test_all_providers_failing_raises_clean_error(app_ctx, make_env):
    _, _, gw = app_ctx
    env = await make_env("allfail")
    gw.providers = [AnthropicProvider("k", "m", transport(lambda r: httpx.Response(500)))]
    from app.core.db import Database, make_engine
    import uuid
    db = Database(make_engine(Settings().database_url))
    with pytest.raises(AppError):
        async with db.tenant_session(uuid.UUID(env.org_id)) as s:
            await gw.complete_json(s, org_id=uuid.UUID(env.org_id), user_id=None, task="t", system="s", user="u")
    await db.dispose()


async def test_oversized_input_rejected_before_any_provider_call():
    called = []
    gw = AIGateway(Settings(ai_max_input_chars=100), providers=[AnthropicProvider("k", "m", transport(lambda r: called.append(1) or httpx.Response(200)))])
    with pytest.raises(AppError):
        await gw.complete_json(None, org_id=None, user_id=None, task="t", system="s", user="x" * 101)  # type: ignore[arg-type]
    assert called == []


def test_pricing_is_explicit_dated_and_unavailable_by_default():
    assert estimate_cost({}, "any", 1000, 1000) is None
    pr = load_pricing(json.dumps([{"model": "m", "input_per_mtok_usd": 2.0, "output_per_mtok_usd": 10.0, "effective_date": "2026-01-01", "source": "internal-test-fixture"}]))
    assert estimate_cost(pr, "m", 1_000_000, 500_000) == pytest.approx(7.0)
    assert estimate_cost(pr, "other", 1, 1) is None


async def test_usage_endpoint_reports_cost_null_without_pricing(client, make_env, app_ctx, fake):
    _, app, gw = app_ctx
    env = await make_env("price")
    gw.providers = [fake]
    fake.reply = json.dumps({"answer": "x", "citations": ["C1"], "insufficient_evidence": False})
    await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("n.txt", f"alpha beta {uniq('u')}".encode(), "text/plain")})
    from app.core.config import get_settings
    from app.core.db import Database, make_engine
    from app.worker import Worker
    from tests.conftest import drain
    w = Worker(db=Database(make_engine(get_settings().worker_database_url)))
    await drain(w)
    await w.db.dispose()
    await client.post(f"{API}/intelligence/ask", headers=env.h("staff"), json={"question": "alpha beta"})
    item = (await client.get(f"{API}/usage/ai", headers=env.h("auditor"))).json()["items"][0]
    assert item["cost_usd"] is None and item["pricing"] is None and item["input_tokens"] == 100
    gw.pricing = load_pricing(json.dumps([{"model": "fake-1", "input_per_mtok_usd": 1.0, "output_per_mtok_usd": 2.0, "effective_date": "2026-06-01", "source": "test"}]))
    item = (await client.get(f"{API}/usage/ai", headers=env.h("auditor"))).json()["items"][0]
    assert item["cost_usd"] == pytest.approx((100 * 1 + 50 * 2) / 1e6) and item["pricing"]["effective_date"] == "2026-06-01"
