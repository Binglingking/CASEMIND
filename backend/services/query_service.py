from __future__ import annotations

import json
from pathlib import Path

from backend.agents.query_agent import QueryAgent
from backend.core.llm import LLMConfig
from backend.services import legacy_service, output_service


MAX_CONTENT_CHARS = 40000


def _resolve_all_mentions(project: str, mentions: list[dict]) -> list[dict]:
    blocks = []
    for m in mentions:
        mtype = (m.get("type") or "").lower()
        if mtype == "legacy_case":
            block = legacy_service.resolve_legacy_case_mention(project, m.get("file_id", ""))
            if block:
                blocks.append(block)
        elif mtype == "legacy_xmind":
            block = legacy_service.resolve_legacy_xmind_mention(project, m.get("file_id", ""))
            if block:
                blocks.append(block)
        elif mtype == "doc":
            path = m.get("path", "")
            try:
                from backend.core.parser import parse_file
                p = Path(path)
                content = parse_file(p) if p.exists() else ""
            except Exception:
                content = ""
            truncated = len(content) > MAX_CONTENT_CHARS
            blocks.append({
                "label": m.get("name", Path(path).name),
                "name": m.get("name", Path(path).name),
                "content": content[:MAX_CONTENT_CHARS],
                "truncated": truncated,
            })
        elif mtype == "output":
            kind = m.get("kind", "")
            filename = m.get("filename", "")
            try:
                data = output_service.read_output_content(project, kind, filename)
                if isinstance(data.get("data"), dict):
                    content = json.dumps(data["data"], ensure_ascii=False, indent=2)
                elif data.get("markdown"):
                    content = data["markdown"]
                else:
                    content = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                content = ""
            truncated = len(content) > MAX_CONTENT_CHARS
            blocks.append({
                "label": filename,
                "name": filename,
                "content": content[:MAX_CONTENT_CHARS],
                "truncated": truncated,
            })
    return blocks


def query_stream(project: str, question: str, mode: str, llm_cfg: LLMConfig,
                 top_k: int | None = None,
                 history: list[dict] | None = None,
                 mentions: list[dict] | None = None,
                 images: list[str] | None = None):
    """流式查询，yield (event_type, text) 元组。"""
    import queue
    import threading

    resolved = _resolve_all_mentions(project, mentions or [])
    agent = QueryAgent(project)
    q: queue.Queue = queue.Queue()

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


def query(project: str, question: str, mode: str, llm_cfg: LLMConfig,
          top_k: int | None = None,
          history: list[dict] | None = None,
          mentions: list[dict] | None = None,
          images: list[str] | None = None) -> dict:
    resolved = _resolve_all_mentions(project, mentions or [])
    return QueryAgent(project).run(
        question=question, mode=mode, llm_cfg=llm_cfg, top_k=top_k,
        history=history or [],
        reference_blocks=resolved,
        images=images or [],
    )
