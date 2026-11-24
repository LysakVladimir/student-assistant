import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db import Base
from backend.app.models import AIProviderState, AIUserSetting, LLMCallLog, User
from backend.app import ai_runtime
from backend.app import provider_client
from backend.app.provider_client import InsufficientBalance
from backend.app.provider_client import InvalidToolCall


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_router_operation_and_modes(monkeypatch):
    monkeypatch.setattr(ai_runtime.settings, "ai_background_model", "deepseek/deepseek-v4-flash")
    monkeypatch.setattr(ai_runtime.settings, "ai_primary_model", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(ai_runtime.provider, "provider_name", lambda: "polza")
    assert ai_runtime.select_model("background_analysis", "quality") == "deepseek/deepseek-v4-flash"
    assert ai_runtime.select_model("rag_answer", "economy") == "deepseek/deepseek-v4-flash"
    assert ai_runtime.select_model("complex_rag", "auto", "complex") == "deepseek/deepseek-v4-pro"
    assert ai_runtime.select_model("rag_answer", "auto", "simple") == "deepseek/deepseek-v4-flash"
    assert ai_runtime.select_model("rag_answer", "quality") == "deepseek/deepseek-v4-pro"


def test_real_selected_model_reaches_provider_mock(monkeypatch):
    db = session(); user = User(telegram_id=10); db.add(user); db.commit()
    db.add(AIUserSetting(user_id=user.id, mode="economy")); db.commit()
    seen = []
    monkeypatch.setattr(ai_runtime.provider, "configured", lambda: True)
    monkeypatch.setattr(ai_runtime.provider, "provider_name", lambda: "polza")
    async def fake_chat(messages, **kwargs):
        seen.append(kwargs["model"])
        return {"role": "assistant", "content": "ok"}, {"provider": "polza", "model": kwargs["model"], "input_tokens": 10, "output_tokens": 2, "provider_cost": .001}
    monkeypatch.setattr(ai_runtime.provider, "chat", fake_chat)
    asyncio.run(ai_runtime.chat(db, user_id=user.id, operation="complex_rag", messages=[{"role": "user", "content": "x"}], complexity="complex"))
    assert seen == ["deepseek/deepseek-v4-flash"]
    assert db.query(LLMCallLog).one().model == "deepseek/deepseek-v4-flash"


def test_402_trips_persistent_breaker_and_is_not_retried(monkeypatch):
    db = session(); user = User(telegram_id=11); db.add(user); db.commit()
    calls = 0
    monkeypatch.setattr(ai_runtime.provider, "configured", lambda: True)
    monkeypatch.setattr(ai_runtime.provider, "provider_name", lambda: "polza")
    async def fail(*args, **kwargs):
        nonlocal calls; calls += 1; raise InsufficientBalance("402")
    monkeypatch.setattr(ai_runtime.provider, "chat", fail)
    try: asyncio.run(ai_runtime.chat(db, user_id=user.id, operation="rag_answer", messages=[{"role": "user", "content": "x"}]))
    except InsufficientBalance: pass
    assert calls == 1
    assert db.query(AIProviderState).one().reason == "insufficient_balance"
    assert db.query(LLMCallLog).one().status == "error"


def test_polza_tool_call_contract(monkeypatch):
    captured = {}
    class Response:
        def json(self):
            return {"model": "deepseek/deepseek-v4-pro", "choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_plan", "arguments": '{"day":"today"}'}}]}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5}, "cost": .01}
    async def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "json": kwargs["json"]}); return Response()
    monkeypatch.setattr(provider_client, "request", fake_request)
    monkeypatch.setattr(provider_client, "configured", lambda: True)
    monkeypatch.setattr(provider_client, "provider_name", lambda: "polza")
    monkeypatch.setattr(provider_client, "base_url", lambda provider=None: "https://polza.ai/api/v1")
    tools = [{"type": "function", "function": {"name": "get_plan", "parameters": {"type": "object"}}}]
    message, usage = asyncio.run(provider_client.chat([{"role": "user", "content": "План"}], model="deepseek/deepseek-v4-pro", tools=tools, tool_choice="required"))
    assert captured["url"] == "https://polza.ai/api/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek/deepseek-v4-pro"
    assert captured["json"]["tools"] == tools and captured["json"]["parallel_tool_calls"] is False
    assert message["tool_calls"][0]["function"]["name"] == "get_plan"
    assert usage["input_tokens"] == 20 and usage["provider_cost"] == .01


def test_invalid_tool_call_502_is_not_retried(monkeypatch):
    calls = 0
    class Response:
        status_code = 502
        text = '{"error":{"message":"Провайдер вернул некорректный вызов инструмента"}}'
    async def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        request = fake_request
    monkeypatch.setattr(provider_client.httpx, "AsyncClient", lambda **kwargs: Client())
    try:
        asyncio.run(provider_client.request("POST", "https://example.invalid"))
    except InvalidToolCall:
        pass
    else:
        assert False, "InvalidToolCall expected"
    assert calls == 1
