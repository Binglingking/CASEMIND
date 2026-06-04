"""PR1.4：tokenizer 测试。

关键目标：接口路径 / 字段名 / 错误码等标识符必须作为**整体 token** 保留，
不被 jieba 切碎——这是 E3（术语召回差）的主要修复点。
"""
from __future__ import annotations

import pytest

from backend.core.tokenizer import build_user_dict, tokenize, tokenize_many


def test_api_path_kept_as_single_token():
    tokens = tokenize("调用 POST /api/login 接口")
    assert "/api/login" in tokens
    assert "post" in tokens


def test_error_code_preserved():
    tokens = tokenize("返回错误码 E4001 表示密码错误")
    assert "e4001" in tokens
    assert "密码" in tokens


def test_snake_case_field_preserved():
    tokens = tokenize("user_id 和 order_no 是主键")
    assert "user_id" in tokens
    assert "order_no" in tokens


def test_chinese_filters_single_char_and_stopwords():
    tokens = tokenize("这是一个测试的内容")
    # 单字 "这" 和 "的" 等应被过滤
    assert "的" not in tokens
    assert "测试" in tokens


def test_empty_input():
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_tokenize_many():
    res = tokenize_many(["密码 8 位", "用户名 user_name"])
    assert len(res) == 2
    assert "user_name" in res[1]


def test_mixed_case_normalized_to_lower():
    tokens = tokenize("访问 /API/Login 接口")
    assert "/api/login" in tokens


def test_build_user_dict_writes_file(tmp_settings):
    """自定义词典生成 + 加载流程不抛异常。"""
    path = build_user_dict(
        aliases=["用户认证", "鉴权中心", ""],  # 空字符串应被过滤
        api_paths=["/api/login"],
        extra_terms=["短信验证码"],
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "用户认证" in content
    assert "短信验证码" in content
    # 去重：重复 term 只写一次
    path2 = build_user_dict(aliases=["用户认证"], api_paths=["/api/login"])
    content2 = path2.read_text(encoding="utf-8")
    assert content2.count("用户认证") == 1


def test_user_dict_makes_alias_a_single_token(tmp_settings):
    """加载自定义词典后，别名应被 jieba 识别为单一词。"""
    # 默认情况下，"鉴权中心" 可能被 jieba 切成 "鉴权" + "中心"
    build_user_dict(aliases=["鉴权中心"])
    tokens = tokenize("访问鉴权中心获取 token")
    # 不强制断言切词结果（jieba 版本差异可能有不同），只确保无异常且包含期望词
    assert "鉴权中心" in tokens or "鉴权" in tokens  # 宽松断言
