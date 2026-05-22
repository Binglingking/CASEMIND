# CaseMind — AI 驱动的需求理解与测试用例生成平台

CaseMind 是一个智能化的需求分析与测试用例生成平台，通过 AI 技术将产品需求文档自动转化为结构化记忆、知识库和高质量测试用例。

**核心价值**：
- 📚 **智能文档理解**：自动解析 Markdown/Word/PDF 等格式的需求文档，构建系统级知识记忆
- 🧠 **增量式学习**：基于差异检测的增量更新机制，只处理变更内容，大幅降低 API 成本
- 🔍 **混合检索增强**：BM25 + 向量检索 + Cross-Encoder 精排，提供精准的 RAG 问答能力
- ✨ **自动化用例生成**：从需求到测试用例的全流程自动化，支持 XMind 思维导图导出
- 🎯 **历史资产复用**：上传团队历史 Excel/XMind 用例，AI 自动学习风格并作为参考
- ⚡ **冲突与覆盖率分析**：自动检测需求矛盾点，评估测试用例覆盖度

> 🔒 **隐私保护**：所有文档、记忆和向量索引均存储在本地，不会上传到任何服务器。LLM 调用仅发送必要的上下文到配置的 API 端点。

## 🚀 快速开始

### 前置要求

- **Python**: 3.11 或更高版本
- **Node.js**: 18 或更高版本
- **网络**: 首次使用需要联网下载嵌入模型（约 100MB）

### 一键启动（推荐）

```bash
# Windows (双击运行)
start.bat

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\start.ps1

# Linux / macOS
chmod +x start.sh
./start.sh

# 跨平台统一入口
python run.py                # 启动后端 + 前端
python run.py --no-browser   # 不自动打开浏览器
python stop.py               # 停止服务
```

启动脚本会自动完成：
1. ✅ 检测 Python 和 Node.js 环境
2. ✅ 创建虚拟环境并安装依赖
3. ✅ 启动后端服务（端口 8888）
4. ✅ 启动前端服务（端口 5173）
5. ✅ 自动打开浏览器访问 `http://127.0.0.1:5173`

> 💡 **首次启动提示**：后端会下载中文嵌入模型 `BAAI/bge-small-zh-v1.5`（约 100MB），请耐心等待。开启重排序功能后会额外下载 `BAAI/bge-reranker-base`（约 300MB）。

## ✨ 核心功能

### 📚 智能文档管理
- **多格式支持**：Markdown、Word (.docx)、PDF、纯文本等常见格式
- **增量更新**：基于文件大小、修改时间和 SHA256 哈希的智能差异检测，未变更文件零重读
- **多项目隔离**：每个项目拥有独立的记忆库、向量索引和输出目录
- **实时进度控制**：构建 AI 记忆时显示实时进度，支持暂停/继续/取消操作

### 🧠 AI 记忆系统
- **自动摘要**：逐文档提取关键信息，生成结构化摘要
- **知识抽取**：将非结构化文档转化为 KnowledgePoint 知识库（实验性功能）
- **记忆编辑**：可直接在界面编辑 memory.md，保存后自动同步提示词
- **反哺审核**：从历史用例中挖掘隐性规则，经人工审核后融入知识库

### 🔍 RAG 问答引擎
- **混合检索**：BM25 关键词匹配 + FAISS 向量相似度检索 + RRF 融合排序
- **Cross-Encoder 精排**：可选的重排序模型提升检索精度（实验性功能）
- **多模式对话**：
  - 💬 **问答模式**：基于文档内容回答问题
  - 📝 **测试用例**：直接生成结构化 JSON 格式用例
  - 🗺️ **XMind 模式**：生成思维导图层级结构
  - 🤖 **聊天模式**：纯对话，不注入项目上下文
- **@文件引用**：在对话中通过 `@文件名` 引用历史用例、XMind 或文档

### ✨ 自动化用例生成
- **四步流水线**（实验性功能）：
  1. **Slicer**：将需求切分为 FeaturePoint 列表，自检覆盖率
  2. **Generator**：按功能点并行生成用例，支持 few-shot 示例注入
  3. **Merger**：跨功能点去重，补充集成测试用例
  4. **Validator**：字段完整性、知识点 ID、块 ID 合法性校验
- **反馈闭环**：对生成的用例点赞/点踩，优质用例作为下次生成的参考示例
- **风格学习**：上传团队历史 Excel/XMind 用例，AI 自动学习编写风格

### 🎯 质量保障工具
- **冲突检测**：扫描全量知识点，识别跨文档的矛盾点并提供解决方案建议
- **覆盖率分析**：三层命中评估（显式匹配 / 同块匹配 / 语义匹配）+ 加权评分
- **五阶段历史分析**：
  1. 标准化历史用例格式
  2. LLM 抽取隐性规则信号
  3. 提取团队风格画像（步骤数、动词偏好、标题风格）
  4. 聚类相似用例
  5. 生成反哺候选知识点

### 📊 历史资产复用
- **Excel 用例导入**：支持团队标准 10 列模板，自动推断列映射关系
- **XMind 解析**：解析 `.xmind` 和 Markdown 格式的思维导图
- **幂等存储**：相同文件多次上传不会重复存储
- **智能引用**：生成用例时自动匹配同模块/子项的历史用例作为 few-shot 示例

### ⚙️ 实验性功能（Feature Flags）

以下高级功能默认关闭，可在「设置 → 实验性功能」中一键开启，无需重启服务：

| 功能 | 说明 | 适用场景 |
|------|------|----------|
| **知识抽取** | 将文档片段升级为结构化 KnowledgePoint | 构建可复用的知识库 |
| **混合检索** | BM25 + 向量 + RRF 融合，jieba 中文分词 | 提高检索准确率 |
| **Cross-Encoder 精排** | 使用 `BAAI/bge-reranker-base` 重排序（首次下载 ~300MB） | 高精度检索场景 |
| **用例流水线** | 4 步高级用例生成（Slicer → Generator → Merger → Validator） | 复杂需求的系统化用例生成 |
| **覆盖率报告** | 三层命中率评估 + 加权评分 + 模块聚合 | 评估测试用例质量 |
| **冲突检测** | 跨文档知识点冲突检测（向量相似度 + LLM 裁判） | 发现需求矛盾点 |
| **反馈闭环** | 用例点赞/点踩，优质用例作为 few-shot 注入 | 持续优化生成质量 |
| **历史风格参考** | 同模块历史用例作为 few-shot + 团队风格画像约束 | 保持团队用例风格一致 |
| **历史反哺审核** | 五阶段分析产生的候选知识点进入审核队列 | 从历史用例挖掘隐性规则 |
| **自动接受高置信反哺** | 高置信度候选直接合入知识库（⚠️ 高风险） | 加速知识库构建 |

全局配置保存在 `memory/_global/features.json`，运行时实时读取。

### 手动启动（开发者模式）

```bash
# 终端 1：启动后端
cd backend
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8888

# 终端 2：启动前端
cd frontend
npm install
npm run dev
```

### Docker 部署

```bash
docker compose up --build
```

前端访问 `http://localhost:5173`，后端 API `http://localhost:8888`。

## 📖 使用指南

### 基本工作流程

#### 1️⃣ 创建项目
进入「项目管理」页面，点击「新建项目」并命名（例如：`投放管理平台`）。

#### 2️⃣ 添加需求文档
- 进入「目录管理」→「本地文件夹」Tab
- 点击「添加文件夹」，选择包含需求文档的目录
- 支持多个文件夹，系统会递归扫描所有支持的格式（`.md`, `.docx`, `.pdf`, `.txt` 等）
- 展开文件夹可查看每个文件的名称、大小和修改时间

#### 3️⃣ 构建 AI 记忆
- 进入「记忆面板」
- 点击「构建 AI 记忆」按钮
- **首次构建**：全量扫描 → 逐文档摘要 → 合成 memory.md → 生成 memory_prompt.txt
- **增量更新**：只处理新增/修改/删除的文件，未变更文件零重读（大幅节省 API 费用）
- 构建过程中可实时查看进度，支持暂停/继续/取消操作
- 构建完成后可在页面上直接编辑 `memory.md`，保存时提示词自动同步

#### 4️⃣ AI 交互
进入「AI 交互」页面，选择模式并开始对话：

- **💬 问答模式**：基于文档内容回答问题
  ```
  示例问题：
  - 用户登录有哪些安全要求？
  - 支付流程的关键步骤是什么？
  - 系统中有哪些角色权限？
  ```

- **📝 测试用例模式**：自动生成结构化 JSON 格式用例
  ```
  示例输入：
  "为登录功能生成测试用例"
  ```

- **🗺️ XMind 模式**：生成思维导图层级结构（可导入 XMind 软件）
  ```
  示例输入：
  "生成用户模块的功能脑图"
  ```

- **🤖 聊天模式**：纯对话，不注入任何项目上下文

- **@文件引用**：在输入框中通过 `@文件名` 引用历史用例、XMind 或文档
  ```
  示例：
  "帮我分析 @1.12.0全量用例 中的登录模块"
  "对比 @需求文档A 和 @需求文档B 的差异"
  ```

#### 5️⃣ 查看与导出结果
- 生成的用例和 XMind 会自动保存在「AI用例库」页面
- 支持在线预览和下载
- 用例以标准 JSON 格式存储，可直接导入测试管理系统

### 进阶工作流

#### 🔧 配置 LLM

进入「设置」页面配置大模型参数：

- **Base URL**: `https://openrouter.ai/api/v1` （或其他兼容 OpenAI API 的服务）
- **API Key**: 你的 API Key（存储在浏览器 localStorage，后端不持久化）
  - 支持环境变量引用：`${env:NAME}` 或 `$NAME`
  - 可点击「检查后端能否读到该密钥」进行诊断
- **模型**: 例如 `anthropic/claude-3.5-sonnet`、`openai/gpt-4`、`deepseek/deepseek-chat` 等

> 💡 **提示**：也可以使用本地部署的 Ollama（`http://localhost:11434/v1`） 实现完全离线运行。

#### 📊 上传历史用例（可选）

如果你有团队的 Excel 测试用例或 XMind 脑图：

1. 进入「目录管理」→「历史用例」Tab
2. 上传 Excel 文件（支持团队标准 10 列模板）
3. 系统自动推断列映射关系，可在「列映射管理」中确认或调整
4. 同样方式上传历史 XMind 文件（`.xmind` 或 `.md` 格式）
5. 在生成用例时使用 `@文件名` 引用，AI 会自动学习团队风格

#### ⚙️ 启用实验性功能

1. 进入「设置」→「实验性功能」
2. 开启你需要的功能（详见上方「实验性功能」表格）
3. 无需重启服务，立即生效

#### 🔄 增量更新最佳实践

当你修改或添加了新文档：

1. 再次点击「构建 AI 记忆」
2. 确保勾选「增量分析」（默认已勾选）
3. 系统只会处理变更的文件，大幅降低 API 费用

**费用对比示例**（假设 364 条用例 + 649 个 XMind 节点）：
- 首次完整分析：$5.70
- 添加 10 个新用例（增量）：**$0.16**（节省 97%）
- 无变化重复运行：**$0.00**（节省 100%）

详细文档：[增量分析功能说明](docs/增量分析功能说明.md)

## 📁 项目结构

```
CaseMind/
├── backend/                    # FastAPI 后端服务
│   ├── main.py                # 应用入口
│   ├── config.py              # 配置管理（功能开关、路径等）
│   ├── agents/                # AI Agent 核心逻辑
│   │   ├── memory_agent.py    # 文档索引与记忆构建
│   │   ├── query_agent.py     # RAG 问答引擎
│   │   ├── knowledge_extractor.py  # 知识抽取
│   │   ├── conflict_detector.py    # 冲突检测
│   │   └── case_gen/          # 用例生成流水线
│   ├── core/                  # 核心基础设施
│   │   ├── vector_store.py    # FAISS/NumPy 向量存储
│   │   ├── bm25_index.py      # BM25 关键词索引
│   │   ├── hybrid_retriever.py# 混合检索器
│   │   ├── reranker.py        # Cross-Encoder 重排序
│   │   ├── kp_store.py        # 知识点存储
│   │   ├── legacy/            # 历史资产解析（Excel/XMind）
│   │   └── llm.py             # LLM API 调用封装
│   ├── services/              # 业务服务层
│   │   ├── memory_service.py  # 记忆管理服务
│   │   ├── query_service.py   # 查询服务
│   │   ├── case_gen_service.py# 用例生成服务
│   │   ├── legacy_service.py  # 历史用例服务
│   │   └── coverage_service.py# 覆盖率分析
│   ├── api/                   # API 路由
│   │   ├── routes.py          # 主路由
│   │   ├── routes_knowledge.py# 知识点 API
│   │   ├── routes_case_gen.py # 用例生成 API
│   │   ├── routes_legacy.py   # 历史资产 API
│   │   └── ...
│   ├── schemas/               # Pydantic 数据模型
│   └── tests/                 # 单元测试（308+ 用例）
│
├── frontend/                   # React + Vite 前端应用
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Projects.jsx   # 项目管理
│   │   │   ├── Folders.jsx    # 目录管理 + 历史用例
│   │   │   ├── Memory.jsx     # 记忆面板 + 反哺审核
│   │   │   ├── Chat.jsx       # AI 交互界面
│   │   │   ├── CaseGen.jsx    # 用例生成流水线
│   │   │   ├── Conflicts.jsx  # 冲突检测
│   │   │   └── Settings.jsx   # 设置页面
│   │   └── components/        # 可复用组件
│   └── package.json
│
├── desktop/                    # Electron 桌面应用（可选）
│   ├── main.js
│   └── package.json
│
├── memory/                     # 项目数据存储（本地）
│   ├── _global/
│   │   └── features.json      # 全局功能开关
│   └── <project>/             # 按项目隔离
│       ├── folders.json       # 登记的文件夹路径
│       ├── file_index.json    # 文件差异检测状态
│       ├── memory.md          # AI 合成的系统记忆
│       ├── memory_prompt.txt  # 可复用提示词
│       ├── knowledge_points.jsonl  # 结构化知识库
│       └── legacy/            # 历史资产
│           ├── cases/         # Excel 用例解析结果
│           ├── xmind/         # XMind 树结构
│           └── inferred/      # 反哺候选队列
│
├── vector_store/               # 向量索引存储（本地）
│   ├── <project>.faiss        # FAISS 向量索引
│   ├── <project>.npy          # NumPy 备用索引
│   └── <project>.bm25.*.pkl   # BM25 索引
│
├── outputs/                    # 生成结果输出
│   ├── testcases/<project>/   # 生成的测试用例
│   └── xmind/<project>/       # 生成的 XMind 文件
│
├── prompts/                    # Prompt 模板
│   ├── memory.txt             # 记忆构建提示
│   ├── query.txt              # 问答提示
│   ├── testcase.txt           # 用例生成提示
│   └── ...
│
├── docs/                       # 详细文档
├── run.py / stop.py           # 跨平台启动/停止脚本
├── start.bat / start.sh       # 平台特定启动脚本
├── docker-compose.yml         # Docker 部署配置
└── README.md                  # 本文件
```

## 🛠️ 技术栈

### 后端
- **框架**: FastAPI (Python 3.11+)
- **向量数据库**: FAISS / NumPy（自动回退）
- **嵌入模型**: BAAI/bge-small-zh-v1.5（中文优化）
- **重排序**: BAAI/bge-reranker-base（可选）
- **关键词检索**: jieba + rank_bm25
- **LLM 调用**: OpenAI 兼容 API（支持 OpenRouter、Ollama 等）
- **测试框架**: pytest（308+ 单元测试）

### 前端
- **框架**: React 18
- **构建工具**: Vite
- **UI 库**: 原生 CSS + 自定义组件
- **状态管理**: React Hooks + localStorage
- **HTTP 客户端**: Fetch API

### 桌面端（可选）
- **框架**: Electron
- **打包**: electron-builder

### 部署
- **容器化**: Docker + Docker Compose
- **反向代理**: Nginx（生产环境推荐）

## ❓ 常见问题

### 端口被占用
**问题**：启动时提示端口 8888 或 5173 被占用。

**解决**：
```bash
# run.py 会自动定位并终止占用端口的进程
python stop.py  # 手动停止服务
```

### PowerShell 无法运行脚本
**问题**：Windows 上运行 `start.ps1` 时报错。

**解决**：
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### faiss-cpu 安装失败
**问题**：`pip install` 时 faiss 编译失败。

**解决**：`requirements.txt` 中 faiss 已注释，VectorStore 会自动回退到 NumPy 纯内存实现，功能完全等价（大规模数据下速度差距可观）。

### LLM 调用报错
**问题**：出现 `Expecting value...` 或连接错误。

**解决**：
1. 检查 Base URL 是否正确（注意末尾不要加 `/`）
2. 确认 API Key 有效且未过期
3. 验证模型名称正确
4. 点击「设置」页面的「检查后端能否读到该密钥」进行诊断

### 首次启动很慢
**问题**：第一次运行时下载模型耗时较长。

**说明**：
- 嵌入模型 `BAAI/bge-small-zh-v1.5` 约 100MB
- 开启重排序后 `BAAI/bge-reranker-base` 约 300MB
- 下载完成后后续启动会很快

### 进度浮窗不显示
**问题**：构建 AI 记忆或五阶段分析时看不到进度条。

**解决**：
1. 确认后端服务正常运行
2. 检查浏览器控制台是否有错误
3. 刷新页面重试
4. 查看 [全局进度浮窗测试指南](docs/全局进度浮窗和@文件功能优化测试指南.md)

### @文件功能不工作
**问题**：输入 `@` 后没有弹出文件选择列表。

**解决**：
1. 确认项目中已有历史用例或 XMind 文件
2. `@` 后面不要加空格，直接输入文件名
3. 检查浏览器控制台是否有错误

### 如何备份数据
**解决**：备份整个 `memory/` 和 `vector_store/` 目录即可。

```bash
# Windows PowerShell
Compress-Archive -Path memory,vector_store -DestinationPath casemind-backup.zip

# Linux/Mac
tar -czf casemind-backup.tar.gz memory vector_store
```

### 可以离线使用吗
**回答**：
- ✅ 嵌入模型下载后可以离线运行
- ✅ 向量检索和本地存储完全离线
- ⚠️ LLM 调用仍需网络（除非使用本地部署的 Ollama）

更多问题请查看 [GETTING_STARTED.md](GETTING_STARTED.md) 新手入门指南。

## 🔧 开发指南

### 添加新功能

#### 新增 Agent
1. 在 `backend/agents/` 下创建新模块，继承 `AgentBase`
2. 在 `backend/services/` 中添加服务方法
3. 在 `backend/api/` 中创建 `routes_*.py` 并在 `routes.py` 中挂载

#### 新增 Feature Flag
1. 在 `backend/config.py::Features` 类中添加字段
2. 在 `frontend/src/pages/Settings.jsx` 中添加 toggle 开关和描述
3. 在相关代码中检查 `features.enable_xxx` 状态

#### 替换嵌入模型
修改 `backend/config.py` 中的 `embedding_model` 配置项。

#### 替换 LLM 提供商
`backend/core/llm.py` 使用 OpenAI 兼容的 chat-completions API，任意兼容端点可直接使用。

### 运行测试

```bash
# 后端单元测试（308+ 用例）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest backend/tests -q

# 前端构建
cd frontend && npm run build
```

> **注意**：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于禁用 allure-pytest 插件自动加载，避免兼容性问题，不影响测试功能。

### 代码规范
- Python: 遵循 PEP 8，使用 type hints
- JavaScript: 使用函数式组件 + Hooks
- 注释：关键逻辑必须添加中文注释

## 🤝 贡献指南

欢迎为 CaseMind 做出贡献！

### 提交 Issue
- 🐛 **Bug 报告**：详细描述问题、复现步骤、预期行为
- 💡 **功能建议**：说明使用场景和期望效果
- ❓ **使用问题**：先查阅文档，确认是否已有解答

### 提交 PR
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request

### 开发前准备
```bash
# 克隆仓库
git clone https://github.com/yourusername/CaseMind.git
cd CaseMind

# 初始化演示数据
python init_data.py --demo

# 启动开发环境
python run.py
```

详细的数据迁移和隐私保护指南请查看 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)。

## 🔒 隐私与安全

### 数据保护
- ✅ **本地存储**：所有文档、记忆和向量索引均存储在本地 `memory/` 和 `vector_store/` 目录
- ✅ **API Key 安全**：仅保存在浏览器 localStorage，后端不持久化
- ✅ **环境变量支持**：通过 `.env` 文件配置敏感信息，避免硬编码
- ✅ **Git 忽略**：`.gitignore` 已配置排除所有个人数据和密钥

### LLM 调用隐私
- 发送到 LLM 的内容包括：文档片段、memory.md、查询问题
- 建议使用可信的 LLM 提供商（如 OpenRouter、OpenAI）
- 可在本地部署开源模型（如 Ollama）实现完全离线运行

### 上传到 GitHub 前
如果你要 fork 或贡献代码，请确保：
1. 运行 `python init_data.py --preview-clean` 查看将要清理的文件
2. 检查是否有硬编码的 API Key 或个人信息
3. 确认 `.gitignore` 生效，敏感文件未被追踪
4. 不要提交 `.env` 文件（使用 `.env.example` 作为模板）
5. 阅读 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) 了解详细步骤

---

## 📚 更多资源

### 新手入门
- [GETTING_STARTED.md](GETTING_STARTED.md) - 5 分钟快速上手指南
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - 数据迁移与隐私保护指南

### 功能文档
- [增量分析功能说明](docs/增量分析功能说明.md) - 大幅降低 API 费用的智能更新机制
- [全局进度浮窗和@文件功能优化测试指南](docs/全局进度浮窗和@文件功能优化测试指南.md)
- [Memory构建进度控制功能实现方案](docs/Memory构建进度控制功能实现方案.md)

### 技术文档
- [平台框架全面分析报告](docs/平台框架全面分析报告.md) - 系统架构深度解析
- [五阶段分析费用优化方案](docs/五阶段分析费用优化方案.md)
- [API费用优化实施总结](docs/API费用优化实施总结.md)

### 开发文档
- 后端测试：`backend/tests/` 目录包含 308+ 单元测试
- API 文档：启动后访问 `http://localhost:8888/docs` 查看 Swagger UI

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

感谢以下开源项目的支持：
- [FastAPI](https://fastapi.tiangolo.com/) - 高性能 Python Web 框架
- [React](https://react.dev/) - 用户界面库
- [FAISS](https://faiss.ai/) - 向量相似度搜索库
- [BAAI bge](https://huggingface.co/BAAI) - 中文嵌入和重排序模型
- [OpenRouter](https://openrouter.ai/) - 统一的大模型 API 网关

---

**⭐ 如果 CaseMind 对你有帮助，欢迎给项目一个 Star！**
