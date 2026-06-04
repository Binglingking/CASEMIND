"""特性开关（feature flags）读写接口。

全局开关，所有项目共享；持久化到 memory/_global/features.json。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import config as _cfg
from backend.config import Features, settings


router = APIRouter()


def _load_features() -> Features:
    """从磁盘读取；未设置时返回 Settings 默认值（全部 False）。

    注意：通过 _cfg.FEATURES_STORE_PATH 动态取值，以便测试 monkeypatch 生效。
    """
    path = _cfg.FEATURES_STORE_PATH
    if not path.exists():
        return Features()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Features.model_validate(data)
    except Exception:
        # 文件损坏时降级到默认值，不抛异常
        return Features()


def _save_features(features: Features) -> None:
    path = _cfg.FEATURES_STORE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(features.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_runtime_features() -> Features:
    """供其他服务读取当前生效的 features（优先磁盘，否则内存默认）。

    其他模块用这个函数而不是直接读 settings.features，因为磁盘值可能被用户改过。
    """
    return _load_features()


class FeaturesUpdateBody(BaseModel):
    """PUT 请求体——支持部分更新，只提供要改的字段即可。"""
    enable_knowledge_extraction: bool | None = None
    enable_hybrid_retrieval: bool | None = None
    enable_case_gen_pipeline: bool | None = None
    enable_coverage_report: bool | None = None
    enable_conflict_detection: bool | None = None
    enable_feedback_loop: bool | None = None
    enable_reranker: bool | None = None
    enable_legacy_style_reference: bool | None = None
    enable_legacy_inference: bool | None = None
    enable_legacy_inference_auto_accept: bool | None = None
    enable_feishu_integration: bool | None = None


@router.get("/features")
def read_features():
    return _load_features().model_dump()


@router.put("/features")
def update_features(body: FeaturesUpdateBody):
    current = _load_features()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "至少需要提供一个字段")
    merged = current.model_copy(update=updates)
    _save_features(merged)
    return merged.model_dump()
