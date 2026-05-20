"""OpenRouter-compatible LLM client (OpenAI chat-completions schema)."""
from __future__ import annotations

import json
import os
import re
import base64
from typing import Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.config import settings


T = TypeVar("T", bound=BaseModel)


# Explicit env refs: $NAME, ${NAME}, ${env:NAME} —— 明确意图，找不到就报错。
_ENV_EXPLICIT_RE = re.compile(
    r"^(?:"
    r"\$\{\s*(?:env[:.])?\s*([A-Za-z_][A-Za-z0-9_]{1,63})\s*\}"
    r"|\$([A-Za-z_][A-Za-z0-9_]{1,63})"
    r")$"
)
# 裸大写 NAME：意图模糊（可能是环境变量，也可能是刚好长得像的字面 key），
# 找不到时回退到字面值，保留旧行为。
_ENV_BARE_RE = re.compile(r"^([A-Z][A-Z0-9_]{1,63})$")


def _resolve_api_key(raw: Optional[str]) -> str:
    """Resolve API key reference:

    - Explicit env refs ($NAME / ${NAME} / ${env:NAME}) MUST resolve, else raise.
    - Bare uppercase NAME: try env first; if not set, fall back to literal (legacy).
    - Anything else: pass through as a literal key.
    - Base64 encoded keys (from frontend) will be decoded.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    
    # 尝试 Base64 解码（前端传来的编码后的 Key）
    try:
        # 检查是否是合法的 Base64 字符
        if re.match(r'^[A-Za-z0-9+/]+=*$', s) and len(s) % 4 == 0:
            decoded = base64.b64decode(s).decode('utf-8')
            # 解码后的内容看起来像 Key（包含 sk- 或其他常见前缀，或长度较长）
            if len(decoded) > 10 or decoded.startswith('sk-') or decoded.startswith('sk_or-'):
                s = decoded
    except Exception:
        pass  # 如果解码失败，继续使用原字符串
    
    m = _ENV_EXPLICIT_RE.match(s)
    if m:
        name = m.group(1) or m.group(2)
        val = os.environ.get(name, "").strip()
        if val:
            return val
        raise RuntimeError(
            f"API Key 指向环境变量 `{name}`，但该变量未设置或为空。"
            "请在系统环境变量中配置该变量，或直接在「设置」里粘贴 key。"
        )
    m = _ENV_BARE_RE.match(s)
    if m:
        val = os.environ.get(m.group(1), "").strip()
        if val:
            return val
        # 没有匹配到环境变量 → 当作字面 key 使用
        return s
    return s


def _normalize_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return u
    # User pasted the full endpoint by mistake
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")].rstrip("/")
    low = u.lower()
    # OpenRouter: API lives at /api/v1 — accept any of
    #   openrouter.ai, openrouter.ai/api, openrouter.ai/api/v1
    if "openrouter.ai" in low:
        host_end = low.find("openrouter.ai") + len("openrouter.ai")
        path = u[host_end:]
        if not path.startswith("/api/v1"):
            u = u[:host_end] + "/api/v1"
    return u.rstrip("/")


class LLMConfig:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        self.base_url = _normalize_base_url(base_url or settings.default_openrouter_base)
        self.api_key = _resolve_api_key(api_key)
        self.model = model or settings.default_model


def _preview(text: str, n: int = 400) -> str:
    t = (text or "").strip().replace("\r", "")
    if len(t) > n:
        return t[:n] + "...(truncated)"
    return t


def chat(messages: list[dict], cfg: LLMConfig, temperature: float = 0.2,
         json_mode: bool = False, timeout: float = 180.0) -> str:
    if not cfg.api_key:
        raise RuntimeError(
            "LLM API Key 未配置，请在前端「设置」页填写 OpenRouter API Key。"
        )
    if not cfg.base_url:
        raise RuntimeError("LLM Base URL 未配置。")

    url = f"{cfg.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "HTTP-Referer": "https://casemind.local",
        "X-Title": "CaseMind",
    }
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise RuntimeError(f"LLM 请求超时（{timeout}s）：{e}") from e
    except httpx.RequestError as e:
        raise RuntimeError(
            f"LLM 请求网络错误：{e}. 请检查 Base URL ({cfg.base_url}) 与网络连接。"
        ) from e

    body_text = r.text or ""
    status = r.status_code
    ctype = r.headers.get("content-type", "")

    # 1) HTTP error: bubble up the real body
    if status >= 400:
        raise RuntimeError(
            f"LLM 调用失败 [HTTP {status}]，Content-Type={ctype}。"
            f"响应体片段：{_preview(body_text)}"
        )

    # 2) Empty body
    if not body_text.strip():
        raise RuntimeError(
            f"LLM 返回空响应（HTTP {status}，Content-Type={ctype}）。"
            "可能原因：API Key 被拒、模型名错误、上游网关异常。请在「设置」里检查 Base URL / API Key / 模型名。"
        )

    # 3) Not JSON (e.g. HTML error page from gateway)
    try:
        data = json.loads(body_text)
    except json.JSONDecodeError as e:
        hint = ""
        low = body_text.lower()
        if "<!doctype html" in low or "<html" in low:
            hint = (
                " 看起来收到的是一个 HTML 页面而不是 API 响应——"
                "最常见的原因是 Base URL 漏了 API 路径前缀。"
                f"当前 Base URL={cfg.base_url}；"
                "OpenRouter 应为 https://openrouter.ai/api/v1，"
                "OpenAI 官方应为 https://api.openai.com/v1。"
            )
        raise RuntimeError(
            f"LLM 返回非 JSON 响应（HTTP {status}，Content-Type={ctype}）：{e.msg}。"
            f"{hint}响应体片段：{_preview(body_text)}"
        ) from e

    # 4) OpenAI-compatible error payload: {"error": {...}}
    if isinstance(data, dict) and "error" in data and "choices" not in data:
        err = data["error"]
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(err, ensure_ascii=False)
            code = err.get("code") or err.get("type") or ""
            raise RuntimeError(f"LLM 返回错误 [{code}]: {msg}")
        raise RuntimeError(f"LLM 返回错误: {err}")

    # 5) Extract content defensively
    try:
        choices = data["choices"]
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices empty")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
    except (KeyError, TypeError, IndexError) as e:
        raise RuntimeError(
            f"LLM 响应结构异常：{e}。响应体片段：{_preview(body_text)}"
        ) from e

    if content is None:
        raise RuntimeError(
            f"LLM 响应中 content 为空。可能是模型拒答或触发内容过滤。"
            f"响应体片段：{_preview(body_text)}"
        )
    if isinstance(content, list):
        # some providers return a list of content parts
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text") or c.get("content") or "")
            else:
                parts.append(str(c))
        content = "".join(parts)
    if not isinstance(content, str):
        content = str(content)

    if not content.strip():
        raise RuntimeError(
            "LLM 返回的 content 为空字符串。可能是 max_tokens 过小、模型拒答或上游异常。"
        )

    return content


def try_parse_json(raw: str):
    """Best-effort JSON parse for model output (may contain fences / prose)."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        for opener, closer in [("{", "}"), ("[", "]")]:
            i = s.find(opener)
            j = s.rfind(closer)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(s[i:j + 1])
                except Exception:
                    continue
    return None


class SchemaValidationError(ValueError):
    """LLM 输出未通过 pydantic Schema 校验（重试用完后抛出）。"""

    def __init__(self, message: str, raw_output: str = "", validation_error: str = ""):
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_error = validation_error


def parse_with_schema(
    raw: str,
    schema: Type[T],
    *,
    retry_cfg: Optional[LLMConfig] = None,
    retry_messages: Optional[list[dict]] = None,
    max_retries: int = 1,
) -> T:
    """严格解析 LLM 输出到 pydantic 模型。

    - 成功：返回 schema 实例。
    - JSON 解析失败或 Schema 校验失败：若提供了 retry_cfg + retry_messages，
      把错误回传给 LLM 并重试（temperature 强制 0.0，启用 json_mode），
      重试用尽仍失败则抛 SchemaValidationError。

    设计约束（详见 docs/design/05 §7）：
      - 永不静默降级（不要再走 try_parse_json 返回 None 后拿 DEFAULT_XXX 兜底的老路）；
      - 重试 Prompt 把校验错误完整回传，让 LLM 有修正依据。

    Parameters
    ----------
    raw : str
        LLM 原始输出。
    schema : Type[BaseModel]
        目标 pydantic 模型。
    retry_cfg : Optional[LLMConfig]
        重试用的 LLM 配置；None 表示不重试，直接抛错。
    retry_messages : Optional[list[dict]]
        重试用的消息序列（通常是原始 system + user 对话），函数会在其后追加
        `{role: assistant, content: <上一轮 raw>}` + `{role: user, content: <校验错误>}`。
    max_retries : int
        最大重试次数，默认 1。
    """
    last_err: str
    try:
        data = try_parse_json(raw)
        if data is None:
            last_err = "output is not valid JSON"
        else:
            return schema.model_validate(data)
    except ValidationError as e:
        last_err = _format_validation_error(e)

    if retry_cfg is None or retry_messages is None or max_retries <= 0:
        raise SchemaValidationError(
            f"LLM 输出 Schema 校验失败：{last_err}",
            raw_output=raw, validation_error=last_err,
        )

    # 追加修正指令重试
    fix_instruction = (
        "上一轮输出未通过 JSON Schema 校验。错误详情：\n"
        f"{last_err}\n\n"
        "请严格按原 Schema 重新输出，只返回合法 JSON，不要 Markdown 围栏、不要解释、不要前言。"
    )
    new_messages = list(retry_messages) + [
        {"role": "assistant", "content": raw},
        {"role": "user", "content": fix_instruction},
    ]
    retry_raw = chat(
        messages=new_messages, cfg=retry_cfg,
        temperature=0.0, json_mode=True,
    )
    return parse_with_schema(
        retry_raw, schema,
        retry_cfg=retry_cfg, retry_messages=retry_messages,
        max_retries=max_retries - 1,
    )


def _format_validation_error(err: ValidationError) -> str:
    """把 pydantic 的 ValidationError 压缩成适合塞进 Prompt 的简短中文描述。"""
    parts: list[str] = []
    for e in err.errors()[:10]:   # 最多列 10 条，避免 Prompt 炸
        loc = ".".join(str(x) for x in e.get("loc", []))
        msg = e.get("msg", "")
        parts.append(f"- 字段 `{loc}`: {msg}")
    if len(err.errors()) > 10:
        parts.append(f"- （还有 {len(err.errors()) - 10} 条类似错误未列出）")
    return "\n".join(parts)
