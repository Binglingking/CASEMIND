# CaseMind — AI 需求理解与记忆中枢平台

一站式"本地文档目录 → 差异摄取 → 压缩系统记忆（memory.md）→ 结构化知识库（KnowledgePoint）→ 可复用 Prompt → 问答 / 用例流水线 / XMind / 覆盖率 / 冲突检测"生成平台。
支持多项目隔离、**增量差异更新**、纯本地嵌入、**BM25+向量混合检索（可选 cross-encoder 精排）**、通过 OpenRouter 调用任意大模型。

> ⚠️ **隐私声明**：本项目设计为完全本地运行，所有文档、记忆、向量索引均存储在本地 `memory/` 和 `vector_store/` 目录，不会上传到任何服务器。LLM 调用仅发送必要的上下文到配置的 API 端点。

## 功能一览

### 核心能力
- **项目管理**（多项目隔离，独立 memory / 向量库 / 输出）
- **目录管理**：添加多个本地文件夹，递归扫描，按扩展名分类统计，展开可查看每个文件的名称/大小/修改时间
- **增量构建**：基于 (size, mtime, sha256) 的差异检测——未变更的文件不再重读，新增/修改/删除文件自动识别
- **memory.md**：AI 合成的系统级压缩理解（可查看/编辑）
- **memory_prompt.txt**：基于 memory.md 的可复用系统提示
- **QueryAgent（RAG）**：memory_prompt + 混合检索，支持问答 / 测试用例 / XMind / 通用聊天四种模式
- **历史用例 / XMind 模块**（取代旧的「风格参考」）：上传团队 10 列 Excel 用例 + 历史 XMind，幂等存储、列映射自动推断 + UI 确认；`@文件名` 注入生成流程；`POST /legacy/analyze` 五阶段分析产出 StyleProfile + 反哺候选 InferredKP（人工审核后入 KP 库）
- **LLM 配置**：Base URL / API Key / 模型（浏览器 localStorage，后端不持久化）；Key 支持环境变量引用 `${env:NAME}`

### 实验性能力（Feature Flags，默认关闭）
全局配置保存在 `memory/_global/features.json`，前端「设置 → 实验性功能」一键开关，后端运行时读取，无需重启。

| Flag | 能力 | 关键模块 |
|---|---|---|
| `enable_knowledge_extraction` | 结构化知识抽取：MemoryAgent 末尾串联 KnowledgeExtractor，把 chunk 升级为 KnowledgePoint | `agents/knowledge_extractor.py` |
| `enable_hybrid_retrieval` | 混合检索（BM25 + 向量 + RRF 融合，jieba 中文分词） | `core/hybrid_retriever.py`、`core/bm25_index.py` |
| `enable_reranker` | cross-encoder 精排（`BAAI/bge-reranker-base`，首次使用下载 ~300MB） | `core/reranker.py` |
| `enable_case_gen_pipeline` | 用例生成 4 步流水线（Slicer → Generator → Merger → Validator） | `agents/case_gen/` |
| `enable_coverage_report` | 三层命中覆盖率（explicit / same_chunk / semantic）+ 加权分 + 模块聚合 | `services/coverage_service.py` |
| `enable_conflict_detection` | 跨文档 KP 冲突检测（向量相似度 + LLM 裁判） | `agents/conflict_detector.py` |
| `enable_feedback_loop` | 用例反馈闭环（👍/👎），upvoted 用例作为同模块 few-shot 注入 Step2 生成器 | `services/feedback_service.py` |
| `enable_legacy_style_reference` | 同模块/子项历史用例作为 few-shot + 团队风格画像（步骤数/动词/标题）作为约束注入 Step2 system prompt | `services/legacy_service.py`、`agents/case_gen/pipeline.py` |
| `enable_legacy_inference` | 五阶段分析产生的 InferredKnowledgePoint 进入 Memory「反哺审核」队列，人工 accept 后才合入 KP 库 | `services/legacy_analyze_service.py`、`memory/<project>/legacy/inferred/` |
| `enable_legacy_inference_auto_accept` | 高 confidence 反哺候选直接合入 KP 库，跳过审核（高风险） | 同上 |

## 一键启动 ⚡

将仓库 clone / 解压到任意路径，满足前置条件（`Python 3.11+` + `Node.js 18+`），然后：

### 跨平台（推荐）

```bash
python run.py                # 启动
python run.py --no-browser   # 不自动开浏览器
python run.py --no-reload    # 后端关闭 --reload（推荐生产态）
python run.py --backend-only # 只启动后端
python run.py --frontend-only# 只启动前端
python stop.py               # 停止两端
```

### Windows（双击）

```
start.bat   ← 双击即可，自动创建 venv / pip install / npm install / 启动前后端 / 打开浏览器
stop.bat    ← 停止两个服务
```

### Windows（PowerShell）

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh     # Ctrl+C 停止
```

脚本会自动：
1. 检测 Python / Node
2. 首次运行创建 `.venv` 并 `pip install -r backend/requirements.txt`
3. 首次运行执行 `npm install`
4. 启动后端 `uvicorn backend.main:app --reload --port 8888`
5. 启动前端 `vite dev --port 5173`
6. 打开浏览器到 `http://127.0.0.1:5173`

> 首次后端启动会下载嵌入模型 `BAAI/bge-small-zh-v1.5`（约 100MB），需联网；之后可离线运行（LLM 调用仍需网络）。开启 `enable_reranker` 后首次检索会额外下载 `BAAI/bge-reranker-base`（约 300MB）。

## 手动启动（备选）

```bash
# 后端（项目根）
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r backend\requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8888
```

```bash
# 前端（新终端）
cd frontend
npm install
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 自动代理 `/api/*` → 后端 `:8888`。

## 配置 LLM

进入前端「设置」页填：

- Base URL: `https://openrouter.ai/api/v1`
- API Key: 你的 OpenRouter Key（`sk-or-v1-...`），也支持环境变量引用：
  - 裸大写名：`OPENROUTER_API_KEY`（找不到时当字面 key 传递）
  - `$NAME` / `${env:NAME}`：强制走环境变量，找不到会报错
  - 可点「检查后端能否读到该密钥」做诊断（不回传 key 内容）
- 模型: 如 `anthropic/claude-opus-4-7` / `openai/gpt-5.4` / `deepseek/deepseek-v4-pro` / `moonshotai/kimi-k2.6` ...

Key 仅存浏览器 localStorage；每次调用时随请求体发给后端，后端转发 OpenRouter，不落盘。

## 使用流程

### 基本流程（仅需基础能力）

1. **项目管理** → 创建并切换项目
2. **目录管理** → 添加本地文件夹（可多个），查看扫描到的文件列表
3. **记忆面板** → 点「构建 AI 记忆」
   - 首次：扫描全部 → 逐文档摘要 → 合成 memory.md → 生成 memory_prompt.txt
   - 再次：只处理新增/修改/删除的文件（差异更新）
4. 可直接在页面上编辑 `memory.md`，保存时 prompt 同步重建
5. **AI 交互** → 选模式提问：
   - `问答` — 基于 memory + 混合检索回答
   - `测试用例` — 直接生成结构化 JSON（单步）
   - `XMind` — 生成 Markdown 层级（可导入 XMind）
   - `聊天` — 纯对话模式，不注入任何项目上下文
6. **输出展示** → 查看 / 下载结果；支持 `@文件名` 引用已上传的历史用例 / XMind

### 进阶流程（开启实验性 Flag 后）

- **用例流水线**（`enable_case_gen_pipeline`）
  1. Slicer：把需求切成 FeaturePoint 列表，自检覆盖率
  2. Generator：按 FP 并行生成用例（支持反馈 few-shot 注入）
  3. Merger：跨 FP 去重 + 集成用例补充
  4. Validator：字段完整性 / kp_id / chunk_id / fp_id 合法性校验
  - 每步独立可重跑 / 回退 / 用户编辑产物
- **覆盖率报告**（`enable_coverage_report`）：为流水线跑出的用例集计算 explicit / same_chunk / semantic 三层命中率
- **冲突检测**（`enable_conflict_detection`）：扫全项目 KP，按模块聚合向量相似对 → LLM 裁判 → 冲突列表 + 解决方案建议
- **反馈闭环**（`enable_feedback_loop`）：用例卡 👍/👎；upvoted 用例作为同模块 few-shot 在下次 Step2 生成时注入
- **历史资产 / 风格 few-shot**（`enable_legacy_style_reference`）：`Folders → 历史用例 / 历史 XMind` 上传团队 10 列 Excel + .xmind / .md；列映射自动推断 + UI 确认 + 「列映射管理」回查/重编；同模块/子项的历史用例作为 few-shot 注入 Step2，团队风格画像（StyleProfile）拼到 system prompt
- **历史反哺**（`enable_legacy_inference`）：`POST /legacy/analyze` 跑五阶段（聚类 → 风格抽取 → 反哺）；候选写入 `Memory → 反哺审核` Tab，人工 accept 才合入 KP 库（开 `_auto_accept` 可跳过审核，高风险）

## 目录结构

```
D:\CaseMind\
├── run.py / stop.py                  ← 跨平台启动/停止
├── start.bat / start.ps1 / start.sh  ← 平台脚本（内部转发到 run.py）
├── stop.bat                          ← Windows 停止脚本
├── docker-compose.yml                ← 容器化启动
├── backend\                          ← FastAPI + Agents
│   ├── main.py
│   ├── config.py                     ← settings / Features / 路径约束
│   ├── agents\
│   │   ├── base.py
│   │   ├── memory_agent.py           ← 差异摄取 + 摘要 + memory.md 合成
│   │   ├── query_agent.py            ← RAG 问答 / testcase / xmind / chat
│   │   ├── knowledge_extractor.py    ← chunk → KnowledgePoint 结构化抽取
│   │   ├── conflict_detector.py      ← 跨文档 KP 冲突判定
│   │   └── case_gen\                 ← 4 步流水线
│   │       ├── pipeline.py           ← 编排器（few-shot + style_hint 注入）
│   │       ├── pipeline_io.py        ← state / 产物 落盘
│   │       ├── slicer.py             ← Step1
│   │       ├── generator.py          ← Step2（feedback few-shot + legacy few-shot + style_hint）
│   │       ├── merger.py             ← Step3
│   │       └── validator.py          ← Step4
│   ├── core\
│   │   ├── parser.py / chunker.py / tokenizer.py
│   │   ├── embeddings.py             ← bge-small-zh-v1.5
│   │   ├── vector_store.py           ← FAISS / NumPy 双后端，按 namespace 隔离
│   │   ├── bm25_index.py             ← jieba + rank_bm25，持久化 pkl
│   │   ├── hybrid_retriever.py       ← BM25 + 向量 + RRF + 元数据过滤
│   │   ├── reranker.py               ← bge-reranker-base 懒加载
│   │   ├── kp_store.py               ← KnowledgePoint 存储
│   │   ├── feedback_store.py         ← 反馈记录存储
│   │   ├── conflict_store.py         ← 冲突对 + 解决方案存储
│   │   ├── legacy\                   ← 历史资产解析与存储
│   │   │   ├── legacy_store.py       ← LegacyCase / XMindTree / StyleProfile / InferredKP IO
│   │   │   ├── excel_parser.py       ← 10 列模板解析 + 警告
│   │   │   ├── xmind_parser.py       ← .xmind / .md 树状解析
│   │   │   ├── column_mapper.py      ← 表头 → 标准列自动推断 + fingerprint
│   │   │   └── _hash.py              ← bytes_content_id (sha1[:8])
│   │   ├── llm.py                    ← OpenAI 兼容 chat-completions 调用
│   │   ├── timeutil.py               ← tz-aware UTC 时间工具
│   │   ├── file_scanner.py / file_index.py / folders.py
│   │   └── project.py                ← 项目隔离
│   ├── services\
│   │   ├── folder_service.py / memory_service.py / query_service.py
│   │   ├── case_gen_service.py / coverage_service.py
│   │   ├── conflict_service.py / feedback_service.py
│   │   ├── excel_service.py          ← 团队 10 列模板导出（write_with_team_template）
│   │   └── legacy_service.py         ← 历史用例 / XMind 上传、@mention、few-shot 检索
│   ├── schemas\                      ← pydantic 数据契约
│   ├── agents\legacy_analyzer\        ← 五阶段历史分析
│   │   ├── runner.py                  ← 编排
│   │   ├── stage1_normalize.py        ← 标准化
│   │   ├── stage2_extract.py          ← 抽取
│   │   ├── stage3_style.py            ← StyleProfile 抽取
│   │   ├── stage4_aggregate.py        ← 聚类
│   │   └── stage5_inferred.py         ← InferredKnowledgePoint 反哺
│   ├── api\
│   │   ├── routes.py                 ← /api 主路由 + 子路由挂载
│   │   ├── routes_settings.py        ← /api/settings/features
│   │   ├── routes_knowledge.py       ← /api/knowledge/*
│   │   ├── routes_case_gen.py        ← /api/case-gen/*
│   │   ├── routes_coverage.py        ← /api/coverage/*
│   │   ├── routes_conflict.py        ← /api/conflict/*
│   │   ├── routes_feedback.py        ← /api/feedback/*
│   │   └── routes_legacy.py          ← /api/legacy/*（历史用例 / XMind / 反哺审核）
│   ├── tests\                        ← pytest（308+ 用例，含历史资产 21 个新测试）
│   └── requirements.txt
├── frontend\                         ← React + Vite
│   └── src\
│       ├── pages\
│       │   ├── Projects.jsx
│       │   ├── Folders.jsx           ← 文件夹 + 历史用例 Tab + 历史 XMind Tab + 列映射管理
│       │   ├── Memory.jsx            ← memory.md / KP / 反哺审核 Tab
│       │   ├── Chat.jsx              ← RAG 问答 / 用例 / XMind / 聊天
│       │   ├── CaseGen.jsx           ← 4 步流水线 UI（含反馈按钮）
│       │   ├── Conflicts.jsx         ← 冲突检测 UI
│       │   ├── Results.jsx
│       │   └── Settings.jsx
│       └── components\LegacyExcelMappingDialog.jsx ← 列映射确认对话框
├── prompts\                          ← per_doc / memory / memory_prompt / query / testcase / xmind / kp_extract / slicer / generator / merger / validator / conflict_judge
├── memory\
│   ├── _global\features.json         ← 全局 feature flags（所有项目共享）
│   └── <project>\
│       ├── folders.json              ← 登记的本地路径
│       ├── file_index.json           ← 差异检测状态
│       ├── per_doc\<sha>.md          ← 逐文档摘要缓存
│       ├── memory.md                 ← 合成的系统记忆
│       ├── memory_prompt.txt         ← 可复用提示
│       ├── knowledge_points.jsonl    ← 结构化知识库
│       ├── feedback.jsonl            ← 反馈记录
│       ├── conflicts.json            ← 冲突对 + 解决方案
│       └── legacy\                   ← 历史资产（取代旧 references/）
│           ├── raw\<file_id>.{xlsx,xmind,md}
│           ├── cases\<file_id>.json  ← LegacyCase[]
│           ├── case_files.json       ← Excel 索引
│           ├── xmind\<file_id>.json  ← XMindTree
│           ├── xmind_files.json      ← XMind 索引
│           ├── column_mapping.json   ← ProjectColumnMappingStore
│           ├── style_profile.json    ← StyleProfile
│           └── inferred\inferred_kps.json  ← 反哺候选审核队列
├── vector_store\                     ← FAISS / NumPy 索引（按 namespace 分开）
│   ├── <project>.chunks.faiss
│   ├── <project>.knowledge_points.faiss
│   └── <project>.bm25.<namespace>.pkl
└── outputs\
    ├── testcases\<project>\
    │   ├── testcase_*.json           ← 单步生成产物
    │   └── pl_<yyyymmdd>_<hhmmss>_<rand4>\  ← 流水线产物
    │       ├── pipeline_state.json
    │       ├── step1_slicer.json / step2_generator.json / step3_merger.json / step4_validator.json
    │       ├── cases.json            ← 最终产物
    │       ├── generation_trace.json ← 运行指标
    │       ├── coverage.json / coverage.md (可选)
    └── xmind\<project>\xmind_*.md
```

## API 列表

所有接口前缀 `/api`。斜体路由受对应 feature flag 控制。

### 基础

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/health` | 健康检查 |
| GET  | `/projects` | 列出所有项目 |
| POST | `/projects` | 创建项目 `{name}` |
| GET  | `/projects/{name}/stats` | 向量库 & 路径概览 |
| GET  | `/folders?project=` | 列出路径 + 文件数 + 扩展名分布 |
| GET  | `/folders/files?project=&path=` | 单目录详细文件列表（按需加载） |
| POST | `/folders` / DELETE | 添加 / 移除路径 |
| POST | `/folders/open` | 在系统文件管理器中打开 |
| POST | `/scan` | 预扫描（不写索引） |
| POST | `/memory/build` | 增量构建 `{project, llm, force_files?, rebuild_all?}` |
| GET  | `/memory?project=` | 读 memory.md + memory_prompt.txt |
| PUT  | `/memory` / `/memory/prompt` | 保存 |
| POST | `/memory/augment` | 追加补充记忆（手写 note） |
| POST | `/query` | RAG 查询 `{project, question, mode, llm, mentions?, history?}`，`mentions[].type ∈ legacy_case \| legacy_xmind \| doc \| output` |
| POST | `/debug/env-check` | 诊断后端能否读到该密钥（不回传 key） |

### 实验性（flag 开启时可用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / PUT | `/settings/features` | 读 / 翻转 feature flags |
| GET / PUT / DELETE | *`/knowledge/points`* | KnowledgePoint CRUD |
| POST | *`/knowledge/rebuild`* | 按现有 chunk 全量重抽 KP |
| POST | *`/case-gen/start`* | 创建流水线 |
| GET  | *`/case-gen/list`* | 项目下流水线列表 |
| GET  | *`/case-gen/{project}/{pipeline_id}`* | 读 state + 产物 |
| POST | *`/case-gen/{project}/{pipeline_id}/step/{n}/run`* | 跑第 n 步 |
| PUT  | *`/case-gen/{project}/{pipeline_id}/step/{n}/output`* | 用户编辑产物 |
| POST | *`/case-gen/{project}/{pipeline_id}/rollback`* | 回退到 stepN_pending |
| POST/GET | *`/coverage/{project}/{pipeline_id}/compute`* / *`/coverage/{project}/summary`* | 覆盖率计算与聚合 |
| POST | *`/conflict/{project}/detect`* | 扫描全量 KP 找冲突 |
| GET / POST / DELETE | *`/conflict/{project}/...`* | 读 / 标记解决 / 清理 |
| POST / GET / DELETE | *`/feedback/{project}`* | 提交 / 列表 / 撤回反馈 |
| GET | *`/feedback/{project}/summary`* / *`/examples`* | 统计与 few-shot 候选 |
| GET / POST / DELETE | `/legacy/cases` *`/{file_id}`* `/peek-headers` `/upload` | 历史 Excel 用例的列表 / 预览表头 / 幂等上传 / 单文件读 / 删除 |
| GET / POST / DELETE | `/legacy/xmind` *`/{file_id}`* `/upload` | 历史 XMind 列表 / 上传 / 树状读取 / 删除 |
| GET / POST | `/legacy/column-mapping` `/confirm` | 读 ProjectColumnMappingStore / 确认或编辑某 fingerprint 映射 |
| GET | `/legacy/style` | 读项目级 StyleProfile |
| GET / POST | *`/legacy/inferred`* `/review` | 反哺候选列表（`?status=pending\|accepted\|rejected`）/ accept-reject 单条 |
| POST | *`/legacy/analyze`* | 跑五阶段历史分析（聚类 → 风格抽取 → 反哺，需 `enable_legacy_inference`） |

`llm` 结构：`{ base_url, api_key, model }`。`mode` ∈ `qa | testcase | xmind | chat`。

## Docker 一键启动（备选）

```bash
docker compose up --build
```

前端 `http://localhost:5173`，后端 `http://localhost:8888`。

## 开发 / 测试

```bash
# 后端回归（308+ 用例）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest backend/tests -q

# 前端构建
cd frontend && npm run build
```

环境变量 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 是因为 `allure-pytest` 插件在当前环境有兼容问题——禁用自动加载即可，不影响测试功能。

## 常见问题

### 端口被占用
```
端口 8888 / 5173 被占用：run.py 会自动定位 PID 并 kill，无需手动干预。
若仍异常，运行 python stop.py 或 stop.bat 兜底。
```

### PowerShell 无法运行脚本
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### pip 装 faiss-cpu 失败
`requirements.txt` 里 faiss 已注释；VectorStore 会自动回退到 NumPy 纯内存实现，功能完全等价（大规模下速度差距可观）。

### LLM 调用报错 `Expecting value...`
已在 `backend/core/llm.py` 中做容错处理，会输出具体原因（Key 失效 / Base URL 错 / 模型名错 / 响应非 JSON 等）。

### UI 翻转 Feature Flag 后没生效
本项目 flag 在每次调用时从磁盘 `memory/_global/features.json` 实时读取，翻转即生效，无需重启。如仍异常：
- 确认 `/api/settings/features` PUT 返回 200
- 后端日志若有 `features.json 读取失败`，检查文件是否被并发写坏（原子写已做，正常场景不会发生）

### 开启 `enable_reranker` 后首次请求很慢
`BAAI/bge-reranker-base`（~300MB）首次调用时加载，采用"懒加载 + 一次失败不再重试"模式；启动后端后第一次查询会有 10~30 秒的模型加载延时，后续请求复用进程内实例。

## 扩展性说明

- **新 Agent**：`backend/agents/` 下继承 `AgentBase`，在 `services/` 加方法，在 `api/` 新建 `routes_*.py` 并在 `routes.py` 挂载
- **新 feature flag**：`backend/config.py::Features` 加字段 → `frontend/src/pages/Settings.jsx` 加一条 toggle 描述
- **替换嵌入**：改 `backend/config.py:embedding_model`
- **替换 reranker**：改 `backend/config.py:reranker_model`（任意 `sentence-transformers.CrossEncoder` 兼容模型）
- **替换向量库**：重写 `backend/core/vector_store.py`（保留接口：`add_chunks` / `search` / `stats` / `has_source` / `remove_source` / `all_chunks`）
- **替换 LLM**：`backend/core/llm.py` 走 OpenAI chat-completions 标准，任意兼容端点可直接用

## 自检清单

- [x] 一键启动脚本覆盖 Windows / Linux / macOS（`run.py` + 平台转发脚本）
- [x] 后端 FastAPI `/api/health` 返回 `{"ok": true}`
- [x] 前端 Vite 代理 `/api` → 后端 8888
- [x] 目录递归扫描，文件详情按需加载
- [x] 增量差异检测：未变更文件零重读
- [x] 可查看/编辑 memory.md，保存时同步 prompt
- [x] RAG 问答自动附加 memory_prompt + 混合检索片段
- [x] 多项目完全隔离：docs / memory / vector_store / outputs
- [x] 所有 feature flag 默认关闭，即使全开也不影响基础流程
- [x] `features.json` 翻转即生效，不需要重启后端
- [x] Prompts 强约束，未在 PRIMARY SOURCES 出现的内容一律标记 `uncertain=true` / `(?)`
- [x] faiss 缺失自动回退 NumPy
- [x] 时间戳统一使用 tz-aware UTC（`backend/core/timeutil.py`），无 `datetime.utcnow()` 警告
- [x] 后端测试 308+ / 308+ 通过（含历史资产 21 个新测试：列映射 / few-shot / 团队模板 / 五阶段分析）

## 隐私与安全

### 数据安全
- ✅ 所有文档和记忆数据存储在本地 `memory/` 目录
- ✅ 向量索引存储在本地 `vector_store/` 目录
- ✅ API Key 仅保存在浏览器 localStorage，后端不持久化
- ✅ 支持通过环境变量引用 API Key，避免硬编码
- ✅ `.gitignore` 已配置排除所有个人数据和密钥

### 上传到 GitHub 前
如果你要 fork 或贡献代码，请确保：
1. 运行 `python init_data.py --preview-clean` 查看将要清理的文件
2. 检查是否有硬编码的 API Key 或个人信息
3. 确认 `.gitignore` 生效，敏感文件未被追踪
4. 不要提交 `.env` 文件（使用 `.env.example` 作为模板）
5. 阅读 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) 了解详细步骤

### LLM 调用隐私
- 发送到 LLM 的内容包括：文档片段、memory.md、查询问题
- 建议使用可信的 LLM 提供商
- 可在本地部署开源模型（如 Ollama）实现完全离线

### 新手入门
如果你是第一次使用 CaseMind，请查看 [GETTING_STARTED.md](GETTING_STARTED.md) 快速上手指南。
