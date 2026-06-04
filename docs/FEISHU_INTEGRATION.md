# 飞书集成接入指南

## 现状

凭据未就绪期间已落地的**离线骨架**：

| 模块 | 路径 | 说明 |
|------|------|------|
| 总开关 | `backend/config.py` -> `Features.enable_feishu_integration` | 全局，写入 `memory/_global/features.json` |
| 项目级配置 | `memory/<project>/feishu.json` | 凭据 + 7 个子功能开关 + 负责人列表 |
| 加密层 | `backend/integrations/feishu/config.py` | Fernet 对称加密；缺 `CASEMIND_MASTER_KEY` 自动降级明文 + 审计标记 |
| 客户端适配 | `backend/integrations/feishu/client.py` | `FeishuClient` Protocol + `MockFeishuClient`（内存）+ `LarkFeishuClient`（stub） |
| Webhook 工具 | `backend/integrations/feishu/webhook.py` | 签名校验 / challenge / 事件去重 |
| 卡片模板 | `backend/integrations/feishu/cards.py` | 完成通知 / 错误告警 / 反哺审核 / IM 模式选择 |
| 业务编排 | `backend/services/feishu_sync_service.py` | F1 导入 + F8 导出 |
| 路由 | `backend/api/routes_feishu.py` -> `/api/feishu/*` | 双层守卫（总开关 + 项目级 enabled + 子功能） |
| 前端 | `frontend/src/pages/Settings.jsx` | 项目级配置面板（凭据 + 子开关 + 连接测试） |
| 测试 | `backend/tests/test_feishu_*.py` | 25 case 全绿，不依赖凭据 |

业务上 F1（导入）+ F8（导出）的全流程已能通过 `MockFeishuClient` 端到端跑通，包含幂等、列映射、warning 收集。

## 待申请的外部资源

### 1. 飞书 App 权限 scope

每个项目独立应用，需开通：

| scope | 用途 | 涉及功能 |
|-------|------|---------|
| `bitable:read` | 读多维表格记录 | F1 |
| `sheets:write` | 创建/写入电子表格 | F8 |
| `im:message:send_as_bot` | 机器人发消息 | F3 / F4 / F6 |
| `im:message` | 接收 IM 消息（双向） | F9 |
| `drive:subscribe` | 文档变更事件订阅 | F2 |
| `drive:drive` | 文件夹读取（导出位置） | F8 |

### 2. 主密钥环境变量

```bash
# 生成一次，永久保存在密钥管理服务里：
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 注入：
export CASEMIND_MASTER_KEY="..."
```

未注入时：`app_secret` 以 `plain:` 前缀存储，配置文件携带 `security_warning="plaintext_fallback_no_master_key"` + `audit_pending=true`。运行不受影响，等 key 就绪后跑迁移脚本即可。

## 凭据就绪后的上线步骤

1. **开通权限**：在飞书开放平台为每个项目创建 App，按表格申请 scope，等管理员审批。
2. **设置 master key**：`CASEMIND_MASTER_KEY` 注入服务进程环境。
3. **安装真实 SDK**：`pip install lark-oapi cryptography` 加进 `requirements.txt`。
4. **实现 `LarkFeishuClient`**：填充 `backend/integrations/feishu/client.py` 里 5 个 `_todo` 方法。
   - `pull_bitable` -> `lark.Client.bitable.v1.app_table_record.list`
   - `create_sheet_with_records` -> `lark.Client.sheets.v3.spreadsheet.create` + `values_batch_update`
   - `send_card` -> `lark.Client.im.v1.message.create` (msg_type=`interactive`)
   - `probe_scopes` -> 逐 scope 试调最小 API，返回 `ok | denied | pending`
5. **打开开关**：
   - 全局：Settings -> 实验性功能 -> 飞书集成（总开关）
   - 项目级：Settings -> 飞书集成 -> 选项目 -> 填凭据 + 启用项目 + 启用对应子功能
6. **连接测试**：点「连接测试」，看 scope 探测全绿。
7. **迁移历史明文 secret**（如有）：
   ```bash
   python scripts/feishu_secret_migrate.py  # 待 key 就绪后实现
   ```
8. **Webhook 配置**：在飞书后台填入 `https://<host>/api/feishu/webhook/<project>` 与 `card_callback/<project>`。

## 路由清单

| 方法 | 路径 | 守卫 | 功能 |
|------|------|------|------|
| GET | `/api/feishu/config?project=` | — | 读项目配置（secret 不回显） |
| PUT | `/api/feishu/config?project=` | — | 更新项目配置（明文 secret 自动加密） |
| POST | `/api/feishu/test?project=` | — | 凭据/scope 探测 |
| POST | `/api/feishu/legacy/import` | `f1_import` | F1 拉飞书表格走 ingest |
| POST | `/api/feishu/docs/export` | `f8_export_sheet` | F8 用例导出 Sheet |
| POST | `/api/feishu/webhook/{project}` | 总开关 | 事件订阅（F2/F9 业务分发待接入） |
| POST | `/api/feishu/card_callback/{project}` | 总开关 | 卡片交互回调（F6 业务分发待接入） |
| POST | `/api/feishu/subscriptions` | `f2_sync` | F2 订阅创建（stub） |

## Mock → Lark 切换规则

`get_client(project)` 在 `client.py` 里：
- 项目 `app_id` 为空 → 返回 `MockFeishuClient`（开发/测试，内存假数据）
- 项目 `app_id` 非空 → 返回 `LarkFeishuClient`（真实调用，stub 期间所有方法 raise NotImplementedError）

业务代码只依赖 `FeishuClient` Protocol，不做 isinstance 判断，因此凭据就绪后**无需改业务**，仅替换 client 实现即可。

## 待办（按优先级）

- [ ] P6 F2 文档变更订阅业务分发（依赖 `drive:subscribe`）
- [ ] P7 F9 IM 多模式桥接 + 会话状态机（依赖 `im:message`）
- [ ] `scripts/feishu_secret_migrate.py` 明文 → Fernet 迁移
- [ ] F3/F4 钩子点接入：在 `legacy_service.ingest_excel` / `case_gen_service` 完成后挂 `send_card`
- [ ] F6 钩子点接入：在 `kp_store.add_inferred(...)` 时挂 `send_card`，card_callback 解析后回写 `kp_store.update_status`
