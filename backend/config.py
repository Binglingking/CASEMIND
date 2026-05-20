from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings


ROOT_DIR = Path(__file__).resolve().parent.parent


class Features(BaseModel):
    """实验性功能开关。所有新能力默认关闭；打开后若内部出错，服务不得影响旧流程。"""
    # ---- P0 / Step 3 MVP ----
    enable_knowledge_extraction: bool = False
    enable_hybrid_retrieval: bool = False
    enable_case_gen_pipeline: bool = False
    # ---- P1 / Step 4 ----
    enable_coverage_report: bool = False
    enable_conflict_detection: bool = False
    # ---- P2 / Step 5 ----
    enable_feedback_loop: bool = False
    enable_reranker: bool = False
    # ---- P3 / Step 6 历史用例 ----
    enable_legacy_style_reference: bool = False        # 历史用例作为 few-shot 注入 Generator
    enable_legacy_inference: bool = False              # 启用反哺候选审核（写入 inferred_kps）
    enable_legacy_inference_auto_accept: bool = False  # 五阶段产出的高置信反哺直接写 KP（高风险，默认关）


class ContextBudget(BaseModel):
    """LLM 上下文预算。用例生成流水线每一步都必须读这里。"""
    per_call_max_tokens: int = 30000        # 单次 LLM 调用上下文硬顶
    history_max_chars: int = 12000          # 历史消息字符上限（query_agent 已有，此处对齐）
    retrieval_top_k_chunks: int = 8
    retrieval_top_k_kps: int = 15
    step2_max_parallel: int = 4             # 用例生成 Step 2 并行度


class Settings(BaseSettings):
    app_name: str = "CaseMind"
    docs_dir: Path = ROOT_DIR / "docs"
    memory_dir: Path = ROOT_DIR / "memory"
    vector_dir: Path = ROOT_DIR / "vector_store"
    outputs_dir: Path = ROOT_DIR / "outputs"
    prompts_dir: Path = ROOT_DIR / "prompts"

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    default_openrouter_base: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-3.5-sonnet"

    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 12

    # 新增：实验性功能与上下文预算
    features: Features = Features()
    context_budget: ContextBudget = ContextBudget()

    class Config:
        env_prefix = "CASEMIND_"
        env_nested_delimiter = "__"   # 支持 CASEMIND_FEATURES__ENABLE_HYBRID_RETRIEVAL=true


settings = Settings()

for d in [settings.docs_dir, settings.memory_dir, settings.vector_dir,
          settings.outputs_dir, settings.outputs_dir / "xmind",
          settings.outputs_dir / "testcases", settings.prompts_dir]:
    d.mkdir(parents=True, exist_ok=True)

# 全局特性开关的持久化位置（与项目无关，所有项目共享）
FEATURES_STORE_PATH: Path = settings.memory_dir / "_global" / "features.json"
FEATURES_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
