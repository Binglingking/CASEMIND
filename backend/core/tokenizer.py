"""中文/混合文本分词器。

给 BM25 用，同时给需要"关键词匹配"而不是"向量相似"的场景用。

核心设计：
  - 英文/数字/接口路径/错误码（如 /api/login, E4001, user_id）保留为**整体 token**，
    不被 jieba 切碎——这是混合检索里术语召回的关键（docs/design/02 §5）。
  - 中文走 jieba 精确模式。
  - 支持注入自定义词典（从 knowledge_points.json 的 aliases 和 api_spec 生成）。
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Iterable, Optional

from backend.config import settings


_lock = threading.Lock()
_loaded_dict: Optional[str] = None   # 记录当前已加载的用户词典路径，避免重复加载
_jieba = None                         # 延迟导入，首次调用才加载


# 英文/数字/常见标识符块（含斜杠、点、连字符、下划线）；或整段中文字符
# 允许开头一个可选的 "/"，用于把 /api/login 这样的路径整体保留。
_TOKEN_RE = re.compile(r"/?[A-Za-z0-9][A-Za-z0-9_/\.\-]*|[一-鿿]+")

# 通用中文停用词，仅用于过滤 jieba 切出的单字/虚词
_STOPWORDS = {
    "的", "了", "是", "在", "和", "或", "与", "及", "对", "为", "以",
    "把", "被", "将", "而", "并", "或者", "以及", "一个", "一种", "一些",
    "这", "那", "此", "这个", "那个", "哪个", "什么", "怎么", "怎样",
    "可以", "应该", "需要", "必须", "能够", "进行", "使用", "通过",
}


def _ensure_jieba():
    global _jieba
    if _jieba is None:
        with _lock:
            if _jieba is None:
                import jieba  # 延迟导入，避免启动时就加载 ~50MB 词典
                # 关闭 HMM 新词发现：减少噪声，对术语检索更稳定
                _jieba = jieba
    return _jieba


def reload_user_dict(dict_path: Path) -> None:
    """加载（或重新加载）项目级自定义词典。

    词典格式：一行一个词，纯文本；可附词频/词性（jieba 规范）。
    """
    global _loaded_dict
    if not dict_path.exists():
        return
    jieba = _ensure_jieba()
    key = str(dict_path.resolve())
    with _lock:
        # jieba 的词典是进程级累加的，重载需要先 initialize 再 load_userdict
        if _loaded_dict != key:
            jieba.load_userdict(str(dict_path))
            _loaded_dict = key


def tokenize(text: str) -> list[str]:
    """分词。

    策略：
      1. 正则先切大块：英文/数字/标识符块 整体保留；中文块走 jieba。
      2. jieba 切出的中文词过滤单字（长度 < 2）与通用停用词。
      3. 标识符块全部转小写（大小写不敏感），中文保持原样。

    Examples
    --------
    >>> tokenize("POST /api/login 登录接口 用户名 user_id")
    ['post', '/api/login', '登录', '接口', '用户名', 'user_id']
    >>> tokenize("错误码 E4001 表示密码错误")
    ['错误码', 'e4001', '表示', '密码', '错误']
    """
    if not text:
        return []
    jieba = _ensure_jieba()
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        frag = m.group()
        if frag[0].isascii():
            # 英文/数字/标识符：整体保留，小写
            out.append(frag.lower())
        else:
            # 中文块：jieba 切，过滤单字 + 停用词
            for w in jieba.lcut(frag):
                if len(w) >= 2 and w not in _STOPWORDS:
                    out.append(w)
    return out


def tokenize_many(texts: Iterable[str]) -> list[list[str]]:
    return [tokenize(t) for t in texts]


# ---- 用户词典构建工具 ------------------------------------------------------

def build_user_dict(
    aliases: Iterable[str] = (),
    api_paths: Iterable[str] = (),
    extra_terms: Iterable[str] = (),
) -> Path:
    """根据项目内的术语信息生成全局用户词典，并加载进 jieba。

    Parameters
    ----------
    aliases : iterable of str
        来自 knowledge_points.aliases 的别名集合（中文术语）。
    api_paths : iterable of str
        api_spec 类 KP 中出现的接口路径。实际上对 jieba 没用（英文/数字本就被正则
        整体保留），但仍写入词典以便排查。
    extra_terms : iterable of str
        其他需要强制成词的术语。

    Returns
    -------
    Path
        生成的词典文件路径（settings.vector_dir / "_user_dict.txt"）。
    """
    dict_path = settings.vector_dir / "_user_dict.txt"
    seen: set[str] = set()
    lines: list[str] = []
    for term in list(aliases) + list(api_paths) + list(extra_terms):
        t = (term or "").strip()
        if not t or t in seen or len(t) < 2:
            continue
        seen.add(t)
        # 给一个适中的词频，保证比默认分词优先
        lines.append(f"{t} 1000")
    dict_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    # 强制重载（先把记录位清掉）
    global _loaded_dict
    with _lock:
        _loaded_dict = None
    reload_user_dict(dict_path)
    return dict_path
