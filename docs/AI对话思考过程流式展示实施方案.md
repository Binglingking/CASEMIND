# AI 对话思考过程与答案流式展示 — 完整实施方案

> 版本：v1.0  
> 日期：2026-05-27  
> 状态：待实施

---

## 一、背景与目标

当前 CaseMind 平台「AI 对话」模块已具备基础的思考过程展示能力（解析 LLM 返回的 `<think>` 标签），但存在以下不足：

| 问题 | 描述 |
|------|------|
| **非流式** | 必须等 LLM 完整响应返回后才一次性渲染，用户等待时只能看静态 spinner |
| **UI 简陋** | 思考过程仅一个折叠 `<pre>` 块，缺乏耗时、脉冲动画等体验细节 |
| **模式覆盖不全** | 只有 `qa`/`chat` 模式解析 thinking，`testcase`/`xmind`/`req_analysis` 不解析 |
| **流式开关未接线** | 设置页的「流式输出响应」Toggle 存在但不起作用 |

**目标**：实现 AI 思考过程实时逐行展示 + 答案打字机流式输出，达到类似 ChatGPT / DeepSeek 官网的交互体验。

---

## 二、总体架构变更

```
改造前（同步阻塞）：
┌────────┐   POST /api/query    ┌────────┐   httpx.post()    ┌─────────┐
│  前端   │ ──────────────────▶ │  后端   │ ───────────────▶ │ LLM API │
│        │ ◀────────────────── │        │ ◀─────────────── │         │
└────────┘   完整 JSON (10-60s) └────────┘   完整响应         └─────────┘
     ↑ 用户看 spinner 等待


改造后（SSE 流式）：
┌────────┐  POST /api/query/stream  ┌────────┐  httpx.stream()  ┌─────────┐
│  前端   │ ──────────────────────▶ │  后端   │ ──────────────▶ │ LLM API │
│        │ ◀── SSE: thinking chunk  │        │ ◀── stream chunk │         │
│        │ ◀── SSE: answer chunk    │        │ ◀── stream chunk │         │
│        │ ◀── SSE: done            │        │                  │         │
└────────┘                          └────────┘                  └─────────┘
     ↑ 实时看思考过程 + 打字机答案
```

---

## 三、阶段一：增强非流式体验（2天）

> 目标：无需改动后端架构，让现有非流式模式下的思考展示更完善。

### 3.1 升级 ThinkingBlock 组件

**文件**：`frontend/src/pages/Chat.jsx`

将现有的简单 `<button>` + `<pre>` 替换为设计稿风格的分步骤折叠面板：

**改造前**（`ThinkingBlock` 函数）：

```jsx
function ThinkingBlock({ text }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="thinking">
      <button className="ghost" onClick={() => setOpen(v => !v)} style={{ padding: '4px 10px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 13, verticalAlign: -2, marginRight: 4, color: '#e7c365' }}>bolt</span>
        深度思考过程
      </button>
      {open && <pre className="thinking-body">{text}</pre>}
    </div>
  );
}
```

**改造后**：

```jsx
function ThinkingBlock({ text, elapsedMs }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;

  // 将思考内容按空行或编号分步
  const steps = text
    .split(/\n(?=\d+[\.\、\)])/g)
    .filter(s => s.trim())
    .map(s => s.trim());

  const elapsed = elapsedMs
    ? `${(elapsedMs / 1000).toFixed(1)}s`
    : null;

  return (
    <details
      className="thinking-details"
      open={open}
      onToggle={(e) => setOpen(e.target.open)}
    >
      <summary className="thinking-summary">
        <span className="mi thinking-chevron">chevron_right</span>
        <span className="thinking-pulse" />
        <span className="thinking-label">深度思考过程</span>
        {elapsed && <span className="thinking-time">已耗时 {elapsed}</span>}
      </summary>
      <div className="thinking-body-v2">
        {steps.length <= 1
          ? <p>{text}</p>
          : steps.map((s, i) => <p key={i}>{s}</p>)
        }
      </div>
    </details>
  );
}
```

### 3.2 增加思考耗时统计

**文件**：`frontend/src/pages/Chat.jsx` — `send()` 函数

在 `setBusy(true)` 之后记录起始时间戳，解析响应后计算耗时：

```jsx
setBusy(true);
const sendStart = performance.now();  // ← 新增

// ... 原有的 API 调用和解析逻辑 ...

const elapsedMs = Math.round(performance.now() - sendStart);  // ← 新增
msgAI = { role: 'assistant', content: displayText, sources, thinking, elapsedMs };  // ← 新增 elapsedMs
```

同时在消息渲染处传入耗时：

```jsx
{m.role === 'assistant' && <ThinkingBlock text={m.thinking} elapsedMs={m.elapsedMs} />}
```

### 3.3 扩展 thinking 解析到所有模式

**文件**：`frontend/src/pages/Chat.jsx` — `send()` 函数

当前只有 `qa`/`chat` 模式解析 thinking。改为所有模式统一解析：

```jsx
// 所有模式统一解析 thinking 标签
const sp = splitThinking(r.answer || '');
thinking = sp.thinking;
const answerBody = sp.answer;

if (r.mode === 'qa' || r.mode === 'chat') {
  displayText = answerBody;
} else if (r.mode === 'testcase') {
  displayText = answerBody || `已生成 ${r.data?.cases?.length || 0} 条测试用例。...`;
  // ...
} else if (r.mode === 'xmind') {
  displayText = answerBody || `已生成 XMind。...`;
  // ...
}
```

### 3.4 新增 ThinkingBlock v2 CSS 样式

**文件**：`frontend/src/styles.css`

在现有 `.thinking` / `.thinking-body` 样式之后追加：

```css
/* --- v2 thinking (collapsible details) --- */
.thinking-details {
  background: rgba(15, 13, 19, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 10px;
}
.thinking-details > summary {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 160ms ease;
}
.thinking-details > summary::-webkit-details-marker { display: none; }
.thinking-details > summary:hover { background: rgba(255, 255, 255, 0.03); }
.thinking-chevron {
  font-size: 14px;
  color: #b5afbd;
  transition: transform 200ms ease;
}
.thinking-details[open] .thinking-chevron { transform: rotate(90deg); }
.thinking-pulse {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #cfbcff;
  animation: thinking-pulse 1.6s ease-in-out infinite;
}
@keyframes thinking-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.15); }
}
.thinking-label {
  font-size: 13px;
  color: #cbc4d2;
  font-style: italic;
}
.thinking-time {
  margin-left: auto;
  font-size: 11px;
  color: #948e9c;
  font-family: 'Space Grotesk', monospace;
}
.thinking-body-v2 {
  padding: 0 14px 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  color: #b5afbd;
  font-size: 13px;
  line-height: 1.7;
}
.thinking-body-v2 p { margin: 6px 0 0 0; }
```

### 3.5 让 Settings 的 streamOutput 开关接线

**文件**：`frontend/src/store.js`

新增 stream output 偏好的全局状态管理：

```javascript
// --------- stream output preference ---------
const LS_STREAM = 'casemind.stream_output';

export function getStreamOutput() {
  const v = localStorage.getItem(LS_STREAM);
  return v === 'true';
}
export function setStreamOutput(val) {
  localStorage.setItem(LS_STREAM, val ? 'true' : 'false');
  window.dispatchEvent(new Event('casemind:stream'));
}
export function useStreamOutput() {
  const [v, setV] = useState(() => getStreamOutput());
  useEffect(() => {
    const h = () => setV(getStreamOutput());
    window.addEventListener('casemind:stream', h);
    return () => window.removeEventListener('casemind:stream', h);
  }, []);
  return [v, (val) => { setStreamOutput(val); setV(val); }];
}
```

**文件**：`frontend/src/pages/Settings.jsx`

将本地 `useState` 替换为全局 store：

```jsx
import { useLLMStore, useStreamOutput } from '../store.js';

// 替换：
//   const [streamOutput, setStreamOutput] = useState(false);
// 为：
const [streamOutput, setStreamOutput] = useStreamOutput();
```

**文件**：`frontend/src/pages/Chat.jsx`

在 `send()` 中读取开关决定走流式还是非流式：

```jsx
import { getStreamOutput } from '../store.js';

async function send() {
  const useStream = getStreamOutput();
  if (!useStream) {
    // 走原有非流式逻辑
  } else {
    // 走 SSE 流式逻辑（阶段二实现）
  }
}
```

---

## 四、阶段二：实现 SSE 流式输出（8天）

> 核心目标：前端实时看到思考过程逐行出现，答案逐字出现（打字机效果）。

### 4.1 后端 — 新增流式 LLM 调用函数

**文件**：`backend/core/llm.py`

新增 `chat_stream()` 生成器函数，逐 chunk 产出 SSE 事件：

```python
def chat_stream(messages: list[dict], cfg: LLMConfig,
                temperature: float = 0.2, json_mode: bool = False,
                timeout: float = 180.0):
    """流式调用 LLM，逐 chunk yield (event_type, text)。

    event_type:
      - 'thinking'  : 模型 reasoning/thinking 内容
      - 'answer'    : 模型正文内容
      - 'error'     : 错误信息
      - 'done'      : 流结束信号
    """
    if not cfg.api_key:
        yield ('error', 'LLM API Key 未配置')
        return
    if not cfg.base_url:
        yield ('error', 'LLM Base URL 未配置')
        return

    url = f"{cfg.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "HTTP-Referer": "https://casemind.local",
        "X-Title": "CaseMind",
    }
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, json=payload, headers=headers) as r:
                if r.status_code >= 400:
                    body_snippet = ""
                    try:
                        body_snippet = r.read().decode("utf-8", errors="replace")[:500]
                    except Exception:
                        pass
                    yield ('error', f"LLM 调用失败 [HTTP {r.status_code}]：{body_snippet}")
                    return

                for line in r.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        yield ('done', '')
                        return
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # DeepSeek / OpenRouter: reasoning_content 即思考过程
                    reasoning = delta.get("reasoning_content") or ""
                    if reasoning:
                        yield ('thinking', reasoning)

                    # 正文内容
                    content = delta.get("content") or ""
                    if content:
                        yield ('answer', content)

                yield ('done', '')

    except httpx.TimeoutException:
        yield ('error', f"LLM 请求超时（{timeout}s）")
    except httpx.RequestError as e:
        yield ('error', f"LLM 请求网络错误：{e}")
```

### 4.2 后端 — QueryAgent 支持流式回调

**文件**：`backend/agents/query_agent.py`

为 `run()` 新增 `stream_callback` 参数，新增 `_run_stream()` 方法。各模式使用 `chat_stream()` 替代 `chat()`，根据事件类型调用回调：

```python
from backend.core.llm import LLMConfig, chat, chat_stream, try_parse_json

class QueryAgent(AgentBase):
    name = "query"

    def run(self, question: str, mode: QueryMode, llm_cfg: LLMConfig,
            top_k: int | None = None,
            history: list[dict] | None = None,
            reference_blocks: list[dict] | None = None,
            images: list[str] | None = None,
            stream_callback=None) -> dict:
        """stream_callback(event_type, text) 用于实时推送"""
        hist = _compact_history(history or [])
        ref_text = _format_references(reference_blocks or [])
        image_urls = images or []

        if stream_callback:
            return self._run_stream(
                question, mode, llm_cfg, top_k, hist, ref_text, image_urls,
                stream_callback,
            )

        # 原有非流式逻辑保持不变
        if mode == "chat":
            return self._chat(question, llm_cfg, hist, ref_text, image_urls)
        # ...

    def _run_stream(self, question, mode, llm_cfg, top_k, hist,
                    ref_text, image_urls, callback):
        """流式运行：检索后逐 chunk 推送给前端。"""
        # chat 模式：无需检索，直接流式回答
        if mode == "chat":
            sys_prompt = (
                "你是通用对话助手。直接根据用户问题进行回答，"
                "不要使用项目需求文档、系统记忆或检索结果，"
                "也不要在回答中标注任何 `[文件名 #序号]` 引用。"
                "如果用户提供了图片，请结合图片内容进行分析回答。"
            )
            msgs = self._build_messages(sys_prompt, question, hist, ref_text, image_urls)
            full_text = ""
            for evt, text in chat_stream(msgs, llm_cfg, temperature=0.5):
                if evt == 'error':
                    callback('error', text)
                    return {"mode": mode, "answer": full_text, "sources": []}
                if evt == 'done':
                    callback('done', '')
                    return {"mode": mode, "answer": full_text, "sources": []}
                if evt == 'thinking':
                    callback('thinking', text)
                    full_text += f"<think>{text}</think>"
                    continue
                if evt == 'answer':
                    full_text += text
                    callback('answer', text)
                    continue
            return {"mode": mode, "answer": full_text, "sources": []}

        # qa / testcase / xmind 模式：先检索，再流式回答
        if mode in ("qa", "testcase", "xmind"):
            top_k = top_k or settings.top_k
            retrieved = self._retrieve(question, top_k)
            ctx = "\n\n".join(
                f"[{c.source} #{c.index}] (score={s:.3f})\n{c.text}"
                for c, s in retrieved
            ) or "(无检索结果)"
            memory_prompt = _memory_prompt(self.project)

            # 按模式选择 prompt 和参数
            if mode == "qa":
                base = load_prompt("query.txt") or "..."
                sys_prompt = (memory_prompt + "\n\n" + base).strip()
                user = f"问题: {question}\n\n...{ctx}..."
                json_mode = False
            elif mode == "testcase":
                base = load_prompt("testcase.txt") or DEFAULT_TESTCASE
                sys_prompt = (memory_prompt + "\n\n" + base).strip()
                user = f"需求描述/目标: {question}\n\n...{ctx}..."
                json_mode = True
            else:  # xmind
                base = load_prompt("xmind.txt") or DEFAULT_XMIND
                sys_prompt = (memory_prompt + "\n\n" + base).strip()
                user = f"主题: {question}\n\n...{ctx}..."
                json_mode = False

            msgs = self._build_messages(sys_prompt, user, hist, ref_text, image_urls)
            full_text = ""
            for evt, text in chat_stream(msgs, llm_cfg,
                                         temperature=0.2, json_mode=json_mode):
                if evt == 'error':
                    callback('error', text)
                    return {"mode": mode, "answer": full_text, "sources": []}
                if evt == 'done':
                    callback('done', '')
                    sources = [
                        {"source": c.source, "index": c.index, "score": s, "text": c.text}
                        for c, s in retrieved
                    ]
                    return {"mode": mode, "answer": full_text, "sources": sources}
                if evt == 'thinking':
                    callback('thinking', text)
                    full_text += f"<think>{text}</think>"
                    continue
                if evt == 'answer':
                    full_text += text
                    callback('answer', text)
                    continue
            return {"mode": mode, "answer": full_text, "sources": []}
```

### 4.3 后端 — 新增 SSE 端点

**文件**：`backend/api/routes.py`

在 import 中新增 `StreamingResponse`：

```python
from fastapi.responses import FileResponse, StreamingResponse
```

新增流式查询端点：

```python
# ---------- query stream ----------

@router.post("/query/stream")
async def query_stream(body: QueryBody):
    """SSE 流式查询端点。"""
    mode = body.mode.lower().strip()
    if mode not in {"qa", "chat", "testcase", "xmind", "req_analysis"}:
        raise HTTPException(400, "mode must be qa | chat | testcase | xmind | req_analysis")
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    history = [m.model_dump() for m in (body.history or [])]

    from backend.services.query_service import query_stream as qs

    async def event_generator():
        try:
            for evt, text in qs(
                body.project, body.question, mode, cfg, body.top_k, history,
                mentions=body.mentions or [],
                images=body.images or [],
            ):
                yield f"event: {evt}\ndata: {text}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )
```

### 4.4 后端 — query_service 流式桥接

**文件**：`backend/services/query_service.py`

新增 `query_stream()` 函数，用 `queue.Queue` + `threading` 桥接同步 QueryAgent 到异步 SSE：

```python
import queue
import threading
import json

def query_stream(project: str, question: str, mode: str, llm_cfg: LLMConfig,
                 top_k: int | None = None,
                 history: list[dict] | None = None,
                 mentions: list[dict] | None = None,
                 images: list[str] | None = None):
    """流式查询，yield (event_type, text) 元组。"""
    from backend.agents.query_agent import QueryAgent

    resolved = _resolve_all_mentions(project, mentions or [])
    agent = QueryAgent(project)
    q = queue.Queue()

    def _stream_callback(evt, text):
        q.put((evt, text))

    def _run():
        try:
            result = agent.run(
                question=question, mode=mode, llm_cfg=llm_cfg, top_k=top_k,
                history=history or [],
                reference_blocks=resolved,
                images=images or [],
                stream_callback=_stream_callback,
            )
            q.put(('__done__', result))
        except Exception as e:
            q.put(('error', str(e)))

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    while True:
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            if not t.is_alive():
                break
            continue

        if item[0] == '__done__':
            yield ('done', json.dumps(item[1], ensure_ascii=False))
            break
        yield item
```

### 4.5 前端 — 新增流式 API 方法

**文件**：`frontend/src/api.js`

```javascript
// query stream (SSE)
queryStream: (project, question, mode, llm, top_k, history, mentions, images, callbacks) => {
  // callbacks: { onThinking, onAnswer, onDone, onError }
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project, question, mode, top_k, llm, history, mentions, images }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        const text = await resp.text();
        callbacks.onError?.(new Error(text));
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (currentEvent === 'thinking') {
              callbacks.onThinking?.(data);
            } else if (currentEvent === 'answer') {
              callbacks.onAnswer?.(data);
            } else if (currentEvent === 'done') {
              try {
                callbacks.onDone?.(JSON.parse(data));
              } catch {
                callbacks.onDone?.({});
              }
              return;
            } else if (currentEvent === 'error') {
              callbacks.onError?.(new Error(data));
              return;
            }
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        callbacks.onError?.(e);
      }
    }
  })();

  return controller; // 可调用 controller.abort() 取消
},
```

### 4.6 前端 — send() 流式改造

**文件**：`frontend/src/pages/Chat.jsx`

核心思路：发送后先插入占位 AI 消息，SSE 每收到 chunk 就原地更新该消息的内容。

```jsx
async function send() {
  // ... 前置校验、图片上传不变 ...

  const useStream = getStreamOutput();

  // 1) 持久化用户消息
  const chatsAfterUser = chats.map(c => c.id === active.id ? ({
    ...c,
    messages: [...c.messages, msgUser],
    title: isFirstMsg ? smartTitle(q) : c.title,
    updatedAt: Date.now(),
  }) : c);
  chatsApi.save(chatsAfterUser);
  setBusy(true);

  // 2) 先插入占位 AI 消息
  const placeholderMsg = {
    role: 'assistant', content: '', thinking: '',
    sources: [], elapsedMs: 0, _streaming: true,
  };
  let chatsWithPlaceholder = chatsAfterUser.map(c => c.id === active.id ? ({
    ...c, messages: [...c.messages, placeholderMsg], updatedAt: Date.now(),
  }) : c);
  chatsApi.save(chatsWithPlaceholder);

  if (!useStream) {
    // ---- 非流式模式（阶段一逻辑） ----
    // ... 保留 ...
    return;
  }

  // ---- 流式模式 ----
  let streamThinking = '';
  let streamAnswer = '';

  const controller = api.queryStream(
    project, q, mode, llm, null, history, mentions,
    imageUrls.length > 0 ? imageUrls : null,
    {
      onThinking(text) {
        streamThinking += text;
        updateLastMsg({ content: streamAnswer, thinking: streamThinking, _streaming: true });
      },
      onAnswer(text) {
        streamAnswer += text;
        updateLastMsg({ content: streamAnswer, thinking: streamThinking, _streaming: true });
      },
      onDone(result) {
        const elapsedMs = Math.round(performance.now() - sendStart);
        updateLastMsg({
          content: streamAnswer || result.answer || '',
          thinking: streamThinking,
          sources: result.sources || [],
          elapsedMs,
          _streaming: false,
        });
        setBusy(false);
      },
      onError(err) {
        updateLastMsg({
          content: '错误：' + (err.message || String(err)),
          thinking: streamThinking, _streaming: false,
        });
        setBusy(false);
      },
    }
  );
}
```

其中 `updateLastMsg` 是一个辅助函数，用于在流式过程中原地更新最后一条 AI 消息：

```jsx
// 更新最后一条消息（通过直接操作 localStorage 触发重渲染）
const updateLastMsg = (updater) => {
  const currentChats = JSON.parse(
    localStorage.getItem(`casemind.chats.${project}`) || '[]'
  );
  const updated = currentChats.map(c => {
    if (c.id !== active.id) return c;
    const msgs = [...c.messages];
    msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...updater };
    return { ...c, messages: msgs, updatedAt: Date.now() };
  });
  localStorage.setItem(`casemind.chats.${project}`, JSON.stringify(updated));
  window.dispatchEvent(new Event('casemind:chats'));
};
```

### 4.7 流式渲染时自动滚动优化

**文件**：`frontend/src/pages/Chat.jsx`

在流式模式下，消息内容持续更新但消息数量不变，需要更频繁的自动滚动：

```jsx
// 流式模式下内容持续更新，需要更频繁的自动滚动
useEffect(() => {
  if (!busy) return;
  const lastMsg = active?.messages?.[active.messages.length - 1];
  if (!lastMsg?._streaming) return;
  const timer = setInterval(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, 100);
  return () => clearInterval(timer);
}, [busy, active?.messages]);
```

---

## 五、阶段三：可选增强（2.5天）

### 5.1 流式取消功能

用户在等待时可点击「停止生成」按钮：

```jsx
// 保存 AbortController 引用
const streamCtrlRef = useRef(null);

// 在流式调用处
streamCtrlRef.current = api.queryStream(...);

// UI 按钮
{busy ? (
  <button onClick={() => {
    streamCtrlRef.current?.abort();
    streamCtrlRef.current = null;
    setBusy(false);
  }}>
    停止
  </button>
) : (
  <button onClick={send}>发送</button>
)}
```

### 5.2 思考过程标签实时解析

当模型不输出独立的 `reasoning_content` 字段，而是在 `content` 中嵌入 `<think>` 标签时，在流式处理中做实时标签解析。维护一个解析状态机，根据遇到的 `<think>` 和 `</think>` 标签动态分发到 thinking 或 answer 事件。

### 5.3 Markdown 实时渲染

当前答案正文是纯文本。可引入轻量 Markdown 渲染，让代码块、表格、列表在流式输出时也能正确渲染。推荐使用 `react-markdown` 或自行实现简单的正则替换。

---

## 六、Nginx 配置要求

如果前端通过 Nginx 代理访问后端，需禁用 SSE 缓冲：

```nginx
location /api/query/stream {
    proxy_pass http://backend:8888;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header X-Accel-Buffering no;
    chunked_transfer_encoding on;
}
```

---

## 七、模型支持情况

当前系统通过 OpenRouter 接入，以下模型原生支持输出思考过程：

| 模型 | 思考输出格式 | 说明 |
|------|-------------|------|
| `deepseek/deepseek-v3.2-20251201` | `reasoning_content` 字段 | DeepSeek 原生推理模型 |
| `deepseek/deepseek-v4-flash-20260423` | 同上 | 同上 |
| `deepseek/deepseek-v4-pro-20260423` | 同上 | 同上 |
| `qwen/qwen3.5-flash-20260224` | 部分支持 | Qwen 推理模型 |
| `qwen/qwen3.6-plus-04-02` | 部分支持 | 同上 |

OpenRouter API 在流式模式下 (`stream: true`)，DeepSeek 模型的每个 SSE chunk 会包含两个字段：
- `delta.reasoning_content` — 思考过程
- `delta.content` — 答案正文

---

## 八、工作量估算

| 阶段 | 任务 | 预估工时 |
|------|------|---------|
| **阶段一** | 3.1 ThinkingBlock 升级 | 0.5天 |
| | 3.2 耗时统计 | 0.5天 |
| | 3.3 全模式 thinking 解析 | 0.5天 |
| | 3.4 CSS 样式 | 0.5天 |
| | 3.5 streamOutput 开关接线 | 0.5天 |
| **小计** | | **2天** |
| **阶段二** | 4.1 chat_stream() | 1天 |
| | 4.2 QueryAgent 流式改造 | 2天 |
| | 4.3 SSE 端点 | 1天 |
| | 4.4 query_service 桥接 | 0.5天 |
| | 4.5 前端 API 方法 | 0.5天 |
| | 4.6 send() 流式改造 | 2天 |
| | 4.7 自动滚动优化 | 0.5天 |
| | 联调测试 | 1.5天 |
| **小计** | | **8天** |
| **阶段三** | 5.1 取消功能 | 0.5天 |
| | 5.2 标签实时解析 | 1天 |
| | 5.3 Markdown 渲染 | 1天 |
| **小计** | | **2.5天** |
| **总计** | | **约 12.5 天** |

---

## 九、风险与注意事项

| 风险 | 应对 |
|------|------|
| **OpenRouter streaming 兼容性** | 不同模型的 `reasoning_content` 字段行为可能不一致，需实际测试 DeepSeek、Qwen 等模型 |
| **Nginx SSE 缓冲** | 必须配置 `proxy_buffering off`，否则所有 chunk 会被缓冲后一次性推送 |
| **线程安全** | `query_service.py` 用 `queue.Queue` 桥接同步/异步，需注意 FastAPI async event loop 与后台线程的协作 |
| **localStorage 高频写入** | 流式更新时每收到 chunk 就写 localStorage，可在阶段三优化为 debounce（每 100ms 写一次） |
| **旧对话兼容** | 流式消息的 `_streaming` 字段旧数据没有，渲染时需做 undefined 判断 |

---

## 十、相关文件索引

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `frontend/src/pages/Chat.jsx` | 重度修改 | ThinkingBlock、send()、滚动逻辑 |
| `frontend/src/styles.css` | 追加 | thinking-details 等 v2 样式 |
| `frontend/src/store.js` | 追加 | useStreamOutput hook |
| `frontend/src/pages/Settings.jsx` | 小改 | streamOutput 接入 store |
| `frontend/src/api.js` | 追加 | queryStream() 方法 |
| `backend/core/llm.py` | 追加 | chat_stream() 函数 |
| `backend/agents/query_agent.py` | 追加 | _run_stream() 方法 |
| `backend/api/routes.py` | 追加 | /query/stream 端点 |
| `backend/services/query_service.py` | 追加 | query_stream() 桥接函数 |
| `UI/ai/code.html` | 只读参考 | 设计稿，Thinking 组件交互参考 |
