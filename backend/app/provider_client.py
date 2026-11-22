"""Low-level AI provider client. Routing, budgets and audit logging are in ai_runtime.py."""
import asyncio
import json
import time
from collections import deque
from typing import Any

import httpx

from .config import settings


class AIProviderError(RuntimeError):
    code = "unavailable"

class InsufficientBalance(AIProviderError): code = "insufficient_balance"
class AuthenticationError(AIProviderError): code = "authentication"
class RateLimited(AIProviderError): code = "rate_limited"
class ContextTooLarge(AIProviderError): code = "context_too_large"
class InvalidToolCall(AIProviderError): code = "invalid_tool_call"


_slots = asyncio.Semaphore(4)
_request_times: deque[float] = deque()
_rate_lock = asyncio.Lock()


def provider_name() -> str:
    return (settings.ai_provider or "gemini").lower().strip()


def api_key(provider: str | None = None) -> str:
    provider = provider or provider_name()
    if provider == "polza": return settings.polza_api_key or settings.ai_api_key
    if provider == "gemini": return settings.gemini_api_key or settings.ai_api_key
    return settings.ai_api_key


def configured() -> bool:
    provider = provider_name()
    return settings.ai_enabled and (bool(api_key(provider)) or (provider == "local" and bool(settings.ai_base_url)))


def base_url(provider: str | None = None) -> str:
    provider = provider or provider_name()
    if provider == "polza": return (settings.polza_base_url or "https://polza.ai/api/v1").rstrip("/")
    if provider == "openrouter": return (settings.ai_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    return (settings.ai_base_url or "https://api.openai.com/v1").rstrip("/")


async def _throttle() -> None:
    async with _rate_lock:
        now = time.monotonic()
        while _request_times and now - _request_times[0] >= 60: _request_times.popleft()
        if len(_request_times) >= max(1, settings.ai_max_requests_per_minute):
            await asyncio.sleep(max(0.0, 60 - (now - _request_times[0])))
        _request_times.append(time.monotonic())


async def request(method: str, url: str, **kwargs) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(max(1, settings.ai_max_retries + 1)):
        try:
            await _throttle()
            async with _slots:
                async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
                    response = await client.request(method, url, **kwargs)
            if response.status_code == 402: raise InsufficientBalance("Polza.ai balance or spending limit is exhausted")
            if response.status_code in {401, 403}: raise AuthenticationError("AI API key is invalid or not permitted")
            if response.status_code == 429:
                if attempt < settings.ai_max_retries: await asyncio.sleep(min(2 ** attempt, 8)); continue
                raise RateLimited("AI provider rate limit exceeded")
            if response.status_code == 400 and any(x in response.text.lower() for x in ("context", "token limit", "too long")):
                raise ContextTooLarge("AI context window exceeded")
            if response.status_code in {500, 502} and any(x in response.text.lower() for x in ("некорректный вызов инструмента", "invalid tool call")):
                raise InvalidToolCall("AI provider rejected the generated tool call")
            if response.status_code == 400:
                raise AIProviderError("AI provider rejected request parameters")
            if response.status_code in {500, 502, 503, 504} and attempt < settings.ai_max_retries:
                await asyncio.sleep(min(2 ** attempt, 8)); continue
            response.raise_for_status(); return response
        except (InsufficientBalance, AuthenticationError, RateLimited, ContextTooLarge, InvalidToolCall): raise
        except (httpx.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt < settings.ai_max_retries: await asyncio.sleep(min(2 ** attempt, 8))
    detail = last.__class__.__name__ if last else "Unavailable"
    raise AIProviderError(f"AI provider request failed ({detail})")


def usage_from(data: dict, provider: str, model: str) -> dict:
    usage = data.get("usage", {})
    return {"provider": provider, "model": data.get("model") or model,
            "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0,
            "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0,
            "provider_cost": usage.get("cost", data.get("cost"))}


async def chat(messages: list[dict], *, model: str, json_mode: bool = False, tools: list[dict] | None = None,
               tool_choice: Any = None, max_tokens: int = 1600) -> tuple[dict, dict]:
    if not configured(): raise AIProviderError("AI API key is not configured or AI is disabled")
    provider = provider_name()
    if provider == "gemini" and not tools:
        prompt = "\n\n".join(f'{m.get("role")}: {m.get("content", "")}' for m in messages)
        body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens}}
        if json_mode: body["generationConfig"]["responseMimeType"] = "application/json"
        response = await request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", params={"key": api_key(provider)}, json=body)
        data = response.json(); meta = data.get("usageMetadata", {})
        return {"role": "assistant", "content": data["candidates"][0]["content"]["parts"][0].get("text", "")}, {"provider": provider, "model": model, "input_tokens": meta.get("promptTokenCount", 0), "output_tokens": meta.get("candidatesTokenCount", 0), "provider_cost": None}
    if provider == "anthropic" and not tools:
        system = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
        response = await request("POST", settings.ai_base_url or "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key(provider), "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system, "messages": [m for m in messages if m.get("role") != "system"]})
        data = response.json(); meta = data.get("usage", {})
        return {"role": "assistant", "content": data["content"][0]["text"]}, {"provider": provider, "model": model, "input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0), "provider_cost": None}
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode: body["response_format"] = {"type": "json_object"}
    if tools:
        body.update({"tools": tools, "parallel_tool_calls": False})
        if tool_choice is not None: body["tool_choice"] = tool_choice
    response = await request("POST", base_url(provider) + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key(provider)}", "Content-Type": "application/json"}, json=body)
    data = response.json()
    return data["choices"][0]["message"], usage_from(data, provider, model)


async def embeddings(texts: list[str], model: str) -> tuple[list[list[float]], dict]:
    provider = provider_name()
    if not texts or not configured(): return [], {}
    if provider == "gemini":
        vectors = []
        for text in texts:
            response = await request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent",
                params={"key": api_key(provider)}, json={"model": f"models/{model}", "content": {"parts": [{"text": text[:8000]}]}})
            vectors.append(response.json().get("embedding", {}).get("values", []))
        return vectors, {"provider": provider, "model": model, "input_tokens": 0, "output_tokens": 0, "provider_cost": None}
    response = await request("POST", base_url(provider) + "/embeddings",
        headers={"Authorization": f"Bearer {api_key(provider)}", "Content-Type": "application/json"},
        json={"model": model, "input": [x[:24000] for x in texts]})
    data = response.json()
    return [x["embedding"] for x in sorted(data.get("data", []), key=lambda x: x.get("index", 0))], usage_from(data, provider, model)


async def media(base64_data: str, mime_type: str, instruction: str, model: str) -> tuple[str, dict]:
    provider = provider_name()
    if provider == "gemini":
        response = await request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key(provider)}, json={"contents": [{"parts": [{"text": instruction}, {"inlineData": {"mimeType": mime_type, "data": base64_data}}]}]})
        data = response.json(); meta = data.get("usageMetadata", {})
        return data["candidates"][0]["content"]["parts"][0].get("text", ""), {"provider": provider, "model": model, "input_tokens": meta.get("promptTokenCount", 0), "output_tokens": meta.get("candidatesTokenCount", 0), "provider_cost": None}
    if not mime_type.startswith("image/"):
        return "", {"provider": provider, "model": model, "input_tokens": 0, "output_tokens": 0, "provider_cost": None}
    message = {"role": "user", "content": [{"type": "text", "text": instruction}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}}]}
    result, usage = await chat([message], model=model)
    return result.get("content") or "", usage


async def gemini_media(base64_data: str, mime_type: str, instruction: str, model: str) -> tuple[str, dict]:
    if not settings.gemini_api_key: return "", {}
    response = await request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": settings.gemini_api_key}, json={"contents": [{"parts": [{"text": instruction}, {"inlineData": {"mimeType": mime_type, "data": base64_data}}]}]})
    data = response.json(); meta = data.get("usageMetadata", {})
    return data["candidates"][0]["content"]["parts"][0].get("text", ""), {"provider": "gemini", "model": model, "input_tokens": meta.get("promptTokenCount", 0), "output_tokens": meta.get("candidatesTokenCount", 0), "provider_cost": None}


def parse_json_content(message: dict) -> dict:
    text = str(message.get("content") or "").strip().removeprefix("```json").removesuffix("```").strip()
    try: return json.loads(text)
    except json.JSONDecodeError as exc: raise AIProviderError(f"Provider returned invalid JSON: {exc}") from exc
