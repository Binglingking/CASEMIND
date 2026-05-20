from __future__ import annotations

from backend.agents.memory_agent import MemoryAgent
from backend.core.llm import LLMConfig
from backend.services import build_log_service, memory_version_service


def scan(project: str) -> dict:
    return MemoryAgent(project).scan()


def build(project: str, llm_cfg: LLMConfig,
          force_files: list[str] | None = None,
          rebuild_all: bool = False,
          incremental: bool = True) -> dict:
    # rebuild_all=True → 清空缓存，完全重建；否则增量构建
    build_type = "full" if rebuild_all else "incremental"
    build_id = build_log_service.create_build_log(project, build_type)

    result = MemoryAgent(project).build(
        llm_cfg, force_files,
        rebuild_all=rebuild_all,
        incremental=not rebuild_all,
    )

    # persist build log
    if result.get("log"):
        build_log_service.append_log_lines(project, build_id, result["log"])

    summary = (
        f"新增 {len(result.get('added') or [])} · "
        f"更新 {len(result.get('updated') or [])} · "
        f"跳过 {len(result.get('skipped') or [])} · "
        f"删除 {len(result.get('removed') or [])}"
    )
    build_log_service.complete_build(project, build_id, summary)

    # create memory version
    ver = memory_version_service.create_version(project, "ai_build", summary)
    if ver:
        build_log_service.set_build_version(project, build_id, ver["id"])

    return result


def read(project: str) -> dict:
    return MemoryAgent(project).read_memory()


def save(project: str, memory_md: str, regenerate_prompt: bool = True) -> dict:
    result = MemoryAgent(project).save_memory(memory_md, regenerate_prompt)
    memory_version_service.create_version(project, "user_edit", "用户手动编辑 memory.md")
    return result


def save_prompt(project: str, prompt_text: str) -> dict:
    return MemoryAgent(project).save_prompt(prompt_text)


def augment(project: str, info: str, llm_cfg: LLMConfig, note: str = "") -> dict:
    result = MemoryAgent(project).augment(info, llm_cfg, note)
    memory_version_service.create_version(project, "ai_augment", note or "用户补充信息融合")
    return result