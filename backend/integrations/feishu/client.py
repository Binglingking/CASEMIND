"""飞书 OpenAPI 客户端适配层。

Protocol 定义业务侧需要的能力。MockFeishuClient 提供内存假数据，
供凭据未就绪期间的端到端集成测试使用。LarkFeishuClient 待 lark-oapi
就绪后填入真实 HTTP 调用。

get_client(project) 工厂根据项目配置自动选择：
  - app_id 为空 → MockFeishuClient
  - app_id 非空 → LarkFeishuClient（暂为 stub，调用即 NotImplementedError）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.integrations.feishu.config import load_config


class FeishuAPIError(RuntimeError):
    """飞书 API 调用失败的统一异常。"""


@dataclass
class BitablePullResult:
    table_name: str
    headers: list[str]
    records: list[dict[str, Any]]                # 每条 = {header: value}


@dataclass
class SheetWriteResult:
    sheet_token: str
    share_url: str
    row_count: int


class FeishuClient(Protocol):
    # ---- F1: 历史用例导入 ----
    def pull_bitable(self, url: str) -> BitablePullResult: ...

    # ---- F8: 用例导出 Sheet ----
    def create_sheet_with_records(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        folder_token: str = "",
    ) -> SheetWriteResult: ...

    # ---- F3/F4/F6: Bot 消息 ----
    def send_card(self, target: str, card: dict[str, Any]) -> None: ...

    # ---- 凭据自检 ----
    def probe_scopes(self) -> dict[str, str]: ...


# ============ Mock ============

# Mock 客户端共享的种子数据；测试可以替换。
_DEFAULT_MOCK_BITABLE = BitablePullResult(
    table_name="历史用例-示例",
    headers=["用例ID", "模块", "标题", "前置条件", "步骤", "预期结果", "优先级"],
    records=[
        {
            "用例ID": "MOCK_001",
            "模块": "登录",
            "标题": "正常账号密码登录",
            "前置条件": "已注册账号",
            "步骤": "1. 打开登录页\n2. 输入账号密码\n3. 点击登录",
            "预期结果": "进入首页",
            "优先级": "P0",
        },
        {
            "用例ID": "MOCK_002",
            "模块": "登录",
            "标题": "密码错误提示",
            "前置条件": "已注册账号",
            "步骤": "1. 打开登录页\n2. 输入错误密码\n3. 点击登录",
            "预期结果": "提示密码错误",
            "优先级": "P1",
        },
    ],
)


@dataclass
class MockFeishuClient:
    """内存假实现，记录所有出站调用便于断言。"""
    project: str
    bitable_fixture: BitablePullResult = field(
        default_factory=lambda: _DEFAULT_MOCK_BITABLE
    )
    sent_cards: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    created_sheets: list[SheetWriteResult] = field(default_factory=list)
    _sheet_counter: int = 0

    def pull_bitable(self, url: str) -> BitablePullResult:
        if not url:
            raise FeishuAPIError("empty url")
        # 简单校验 url 格式
        if not re.search(r"feishu\.cn|larksuite\.com", url):
            raise FeishuAPIError(f"not a feishu url: {url}")
        return self.bitable_fixture

    def create_sheet_with_records(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        folder_token: str = "",
    ) -> SheetWriteResult:
        self._sheet_counter += 1
        token = f"mock_sheet_{self._sheet_counter:04d}"
        result = SheetWriteResult(
            sheet_token=token,
            share_url=f"https://feishu.cn/sheets/{token}",
            row_count=len(rows),
        )
        self.created_sheets.append(result)
        return result

    def send_card(self, target: str, card: dict[str, Any]) -> None:
        if not target:
            raise FeishuAPIError("empty target")
        self.sent_cards.append((target, card))

    def probe_scopes(self) -> dict[str, str]:
        return {
            "bitable:read": "mock",
            "sheets:write": "mock",
            "drive:subscribe": "mock",
            "im:message": "mock",
        }


# ============ Lark (stub) ============

@dataclass
class LarkFeishuClient:
    """真实飞书 OpenAPI 客户端。

    凭据未就绪期间为 stub，调用任何方法都抛 NotImplementedError 并提示
    后续接入位置。lark-oapi SDK 引入后在每个方法实现真实调用。
    """
    project: str
    app_id: str
    app_secret: str

    def _todo(self, fn: str) -> "NotImplementedError":
        return NotImplementedError(
            f"LarkFeishuClient.{fn} 未实现：等待飞书 App 凭据与 lark-oapi SDK 接入。"
            f" 当前请使用 MockFeishuClient（清空项目 app_id 即可自动切换）。"
        )

    def pull_bitable(self, url: str) -> BitablePullResult:
        raise self._todo("pull_bitable")

    def create_sheet_with_records(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        folder_token: str = "",
    ) -> SheetWriteResult:
        raise self._todo("create_sheet_with_records")

    def send_card(self, target: str, card: dict[str, Any]) -> None:
        raise self._todo("send_card")

    def probe_scopes(self) -> dict[str, str]:
        # 真实实现：逐个 scope 试调一次最小 API 看是否被拒。
        # 当前 stub：全部 pending。
        return {
            "bitable:read": "pending_credentials",
            "sheets:write": "pending_credentials",
            "drive:subscribe": "pending_credentials",
            "im:message": "pending_credentials",
        }


# ============ Factory ============

def get_client(project: str) -> FeishuClient:
    """根据项目配置返回 client 实例。

    决策规则：
      - app_id 为空 → MockFeishuClient（开发/测试场景）
      - app_id 非空 → LarkFeishuClient（凭据就绪后才能真正工作）

    业务代码应只依赖 FeishuClient Protocol，不要 isinstance 判断。
    """
    cfg = load_config(project)
    if not cfg.app_id.strip():
        return MockFeishuClient(project=project)
    # 延迟导入 decrypt，避免循环依赖
    from backend.integrations.feishu.config import decrypt_secret
    secret = decrypt_secret(cfg.app_secret_enc)
    return LarkFeishuClient(project=project, app_id=cfg.app_id, app_secret=secret)
