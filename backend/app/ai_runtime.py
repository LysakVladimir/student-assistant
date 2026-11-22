"""Central model router, budgets, circuit breaker and technical call audit."""
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .models import AIProviderState, AIUserSetting, LLMCallLog
from . import provider_client as provider


BACKGROUND_OPERATIONS = {"background_analysis", "intermediate_summary", "embedding", "media_extraction"}
COMPLEX_OPERATIONS = {"complex_rag", "multi_chat_rag", "tool_agent", "detailed_summary"}
PRICE_RUB_PER_MILLION = {
    "deepseek/deepseek-v4-flash": (1.72, 3.44),
    "deepseek/deepseek-v4-pro": (78.0, 156.0),
    "baai/bge-m3": (1.18, 0.0),
}


class AIDisabled(RuntimeError): pass
class AIBudgetExceeded(RuntimeError): pass


def user_settings(db: Session, user_id: int | None) -> AIUserSetting | None:
    if user_id is None: return None
    row = db.query(AIUserSetting).filter_by(user_id=user_id).first()
    if not row:
        row = AIUserSetting(user_id=user_id, mode=settings.ai_default_mode, ai_enabled=True)
        db.add(row); db.flush()
    return row


def select_model(operation: str, mode: str = "auto", complexity: str = "simple") -> str:
    if provider.provider_name() == "gemini":
        return settings.ai_analysis_model or settings.ai_model or settings.gemini_model
    background = settings.ai_background_model or settings.ai_analysis_model or settings.ai_model or settings.gemini_model
    primary = settings.ai_primary_model or settings.ai_model or settings.gemini_model
    if operation in BACKGROUND_OPERATIONS: return background
    if mode == "economy": return background
    if mode == "quality": return primary
    if operation in COMPLEX_OPERATIONS or complexity == "complex": return primary
    return background


def _month_start() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage_stats(db: Session, user_id: int | None = None) -> dict:
    query = db.query(LLMCallLog).filter(LLMCallLog.created_at >= _month_start())
    if user_id is not None: query = query.filter(LLMCallLog.user_id == user_id)
    row = query.with_entities(func.coalesce(func.sum(LLMCallLog.input_tokens), 0), func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                              func.coalesce(func.sum(LLMCallLog.estimated_cost_rub), 0.0), func.count(LLMCallLog.id)).one()
    return {"input_tokens": int(row[0]), "output_tokens": int(row[1]), "estimated_cost_rub": round(float(row[2]), 6), "requests": int(row[3])}


def _check_allowed(db: Session, user_id: int | None, operation: str) -> str:
    if not settings.ai_enabled or not provider.configured(): raise AIDisabled("AI provider is disabled or API key is not configured")
    pref = user_settings(db, user_id)
    if pref and not pref.ai_enabled: raise AIDisabled("AI is disabled for this user")
    if operation in BACKGROUND_OPERATIONS and not settings.ai_background_enabled: raise AIDisabled("Background AI analysis is disabled")
    state = db.query(AIProviderState).filter_by(provider=provider.provider_name()).first()
    if state and state.suspended_until and state.suspended_until > datetime.utcnow():
        raise AIDisabled(f"AI provider temporarily suspended: {state.reason}")
    global_stats = usage_stats(db)
    if global_stats["input_tokens"] + global_stats["output_tokens"] >= settings.ai_monthly_token_limit:
        raise AIBudgetExceeded("Application monthly token budget exhausted")
    if global_stats["estimated_cost_rub"] >= settings.ai_monthly_cost_limit_rub:
        raise AIBudgetExceeded("Application monthly cost budget exhausted")
    if global_stats["requests"] >= settings.ai_monthly_request_limit:
        raise AIBudgetExceeded("Application monthly request budget exhausted")
    if user_id is not None:
        stats = usage_stats(db, user_id)
        limit = pref.monthly_token_limit if pref and pref.monthly_token_limit else settings.ai_user_monthly_token_limit
        if stats["input_tokens"] + stats["output_tokens"] >= limit: raise AIBudgetExceeded("User monthly token budget exhausted")
        if stats["requests"] >= settings.ai_user_monthly_request_limit: raise AIBudgetExceeded("User monthly request budget exhausted")
    if operation in BACKGROUND_OPERATIONS:
        background_tokens = db.query(func.coalesce(func.sum(LLMCallLog.input_tokens + LLMCallLog.output_tokens), 0)).filter(
            LLMCallLog.created_at >= _month_start(), LLMCallLog.operation.in_(BACKGROUND_OPERATIONS)).scalar() or 0
        if int(background_tokens) >= settings.ai_background_monthly_token_limit: raise AIBudgetExceeded("Background monthly token budget exhausted")
        background_requests = db.query(func.count(LLMCallLog.id)).filter(LLMCallLog.created_at >= _month_start(), LLMCallLog.operation.in_(BACKGROUND_OPERATIONS)).scalar() or 0
        if int(background_requests) >= settings.ai_background_monthly_request_limit: raise AIBudgetExceeded("Background monthly request budget exhausted")
    return pref.mode if pref else settings.ai_default_mode


def _estimated_cost(model: str, usage: dict) -> float:
    input_price, output_price = PRICE_RUB_PER_MILLION.get(model, (0.0, 0.0))
    return (usage.get("input_tokens", 0) * input_price + usage.get("output_tokens", 0) * output_price) / 1_000_000


def _log(db: Session, *, user_id: int | None, model: str, operation: str, usage: dict | None,
         duration_ms: int, status: str, error: Exception | None = None, provider_override: str = "") -> None:
    usage = usage or {}
    db.add(LLMCallLog(user_id=user_id, provider=provider_override or usage.get("provider") or provider.provider_name(), model=usage.get("model") or model, operation=operation,
        input_tokens=int(usage.get("input_tokens", 0)), output_tokens=int(usage.get("output_tokens", 0)),
        estimated_cost_rub=_estimated_cost(usage.get("model") or model, usage), provider_cost=usage.get("provider_cost"),
        duration_ms=duration_ms, status=status, error_code=getattr(error, "code", error.__class__.__name__ if error else "")[:50],
        error_message=str(error or "")[:500]))


def _trip_breaker(db: Session, error: Exception) -> None:
    state = db.query(AIProviderState).filter_by(provider=provider.provider_name()).first()
    if not state:
        state = AIProviderState(provider=provider.provider_name()); db.add(state)
    minutes = 60 if isinstance(error, provider.InsufficientBalance) else 15 if isinstance(error, provider.AuthenticationError) else 5
    state.suspended_until = datetime.utcnow() + timedelta(minutes=minutes)
    state.reason = getattr(error, "code", "provider_error")
    state.last_error = str(error)[:500]


async def chat(db: Session, *, user_id: int | None, operation: str, messages: list[dict], complexity: str = "simple",
               json_mode: bool = False, tools: list[dict] | None = None, tool_choice=None, max_tokens: int = 1600) -> tuple[dict, dict]:
    mode = _check_allowed(db, user_id, operation)
    model = select_model(operation, mode, complexity)
    started = time.perf_counter()
    try:
        message, usage = await provider.chat(messages, model=model, json_mode=json_mode, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
        _log(db, user_id=user_id, model=model, operation=operation, usage=usage, duration_ms=int((time.perf_counter()-started)*1000), status="success")
        db.flush()
        return message, usage
    except Exception as exc:
        _log(db, user_id=user_id, model=model, operation=operation, usage=None, duration_ms=int((time.perf_counter()-started)*1000), status="error", error=exc)
        if isinstance(exc, (provider.InsufficientBalance, provider.AuthenticationError, provider.RateLimited)) or type(exc) is provider.AIProviderError:
            _trip_breaker(db, exc)
        db.flush(); raise


async def generate_text(db: Session, *, user_id: int | None, operation: str, prompt: str, system: str = "",
                        complexity: str = "simple", max_tokens: int = 1600) -> tuple[str, dict]:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt[:settings.ai_context_char_limit]}]
    message, usage = await chat(db, user_id=user_id, operation=operation, messages=messages, complexity=complexity, max_tokens=max_tokens)
    return message.get("content") or "", usage


async def generate_json(db: Session, *, user_id: int | None, operation: str, prompt: str, system: str = "") -> tuple[dict, dict]:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt[:settings.ai_context_char_limit]}]
    message, usage = await chat(db, user_id=user_id, operation=operation, messages=messages, json_mode=True)
    return provider.parse_json_content(message), usage


async def embed_many(db: Session, texts: list[str]) -> list[list[float]]:
    _check_allowed(db, None, "embedding")
    model = "baai/bge-m3" if provider.provider_name() == "polza" and settings.ai_embedding_model == "text-embedding-004" else settings.ai_embedding_model
    started = time.perf_counter()
    try:
        vectors, usage = await provider.embeddings(texts, model)
        _log(db, user_id=None, model=model, operation="embedding", usage=usage, duration_ms=int((time.perf_counter()-started)*1000), status="success")
        db.flush(); return vectors
    except Exception as exc:
        _log(db, user_id=None, model=model, operation="embedding", usage=None, duration_ms=int((time.perf_counter()-started)*1000), status="error", error=exc)
        if isinstance(exc, (provider.InsufficientBalance, provider.AuthenticationError, provider.RateLimited)): _trip_breaker(db, exc)
        db.flush(); raise


async def extract_media(db: Session, base64_data: str, mime_type: str, instruction: str) -> str:
    _check_allowed(db, None, "media_extraction")
    use_gemini = not mime_type.startswith("image/") and bool(settings.gemini_api_key)
    model = settings.gemini_model if use_gemini else select_model("media_extraction", settings.ai_default_mode)
    started = time.perf_counter()
    try:
        text, usage = await (provider.gemini_media(base64_data, mime_type, instruction, model) if use_gemini else provider.media(base64_data, mime_type, instruction, model))
        _log(db, user_id=None, model=model, operation="media_extraction", usage=usage, duration_ms=int((time.perf_counter()-started)*1000), status="success", provider_override="gemini" if use_gemini else "")
        db.flush(); return text
    except Exception as exc:
        _log(db, user_id=None, model=model, operation="media_extraction", usage=None, duration_ms=int((time.perf_counter()-started)*1000), status="error", error=exc)
        if isinstance(exc, (provider.InsufficientBalance, provider.AuthenticationError, provider.RateLimited)): _trip_breaker(db, exc)
        db.flush(); raise


def reset_provider(db: Session) -> None:
    state = db.query(AIProviderState).filter_by(provider=provider.provider_name()).first()
    if state: state.suspended_until = None; state.reason = ""; state.last_error = ""
