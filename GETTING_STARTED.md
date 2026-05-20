# CaseMind 新手入门指南

欢迎使用 CaseMind！本指南将帮助你快速上手。

## 📋 前置要求

- **Python**: 3.11 或更高版本
- **Node.js**: 18 或更高版本
- **网络**: 首次使用需要联网下载模型（约 100MB）

## 🚀 5 分钟快速开始

### 第 1 步：克隆仓库

```bash
git clone https://github.com/yourusername/CaseMind.git
cd CaseMind
```

### 第 2 步：初始化数据

```bash
# 创建必要的目录结构和演示项目
python init_data.py --demo
```

### 第 3 步：启动应用

**Windows:**
```bash
start.bat
```

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

应用会自动：
- 安装 Python 依赖
- 安装 Node.js 依赖
- 启动后端服务（端口 8888）
- 启动前端服务（端口 5173）
- 打开浏览器

### 第 4 步：配置 LLM

1. 在打开的页面中，点击右上角「设置」
2. 填写以下信息：
   - **Base URL**: `https://openrouter.ai/api/v1`
   - **API Key**: 你的 OpenRouter API Key（从 https://openrouter.ai 获取）
   - **模型**: 例如 `anthropic/claude-3.5-sonnet`
3. 点击「保存」

> 💡 **提示**: 也可以使用其他兼容 OpenAI API 的服务，如 Ollama（本地部署）、OpenAI 官方等

### 第 5 步：创建你的第一个项目

1. 点击左侧菜单「项目管理」
2. 点击「新建项目」
3. 输入项目名称，例如：`我的第一个项目`
4. 点击创建

### 第 6 步：添加需求文档

1. 点击左侧菜单「目录管理」
2. 确保当前项目是你刚创建的项目
3. 点击「添加文件夹」
4. 选择包含需求文档的文件夹

**支持的文档格式：**
- Markdown (`.md`)
- Word (`.docx`)
- PDF (`.pdf`)
- 纯文本 (`.txt`)
- 其他文本格式

**文档准备建议：**
- 将相关的需求文档放在同一个文件夹
- 使用清晰的命名，如 `01_用户模块需求.md`
- 保持文档结构清晰，有明确的标题层级

### 第 7 步：构建 AI 记忆

1. 点击左侧菜单「记忆面板」
2. 点击「构建 AI 记忆」按钮
3. 等待分析完成（根据文档数量，可能需要几分钟）

**构建过程：**
1. 扫描文档 → 2. 逐文档摘要 → 3. 合成系统记忆 → 4. 生成提示词

### 第 8 步：开始使用 AI

点击左侧菜单「AI 交互」，选择模式：

#### 🤔 问答模式
基于文档内容回答问题
```
示例问题：
- 用户登录有哪些安全要求？
- 支付流程的关键步骤是什么？
- 系统中有哪些角色？
```

#### 📝 测试用例模式
自动生成结构化测试用例
```
示例输入：
"为登录功能生成测试用例"
```

#### 🗺️ XMind 模式
生成思维导图（可导入 XMind 软件）
```
示例输入：
"生成用户模块的功能脑图"
```

#### 💬 聊天模式
自由对话，不注入项目上下文

## 📚 进阶功能

### 启用实验性功能

1. 进入「设置」→「实验性功能」
2. 开启你需要的功能：
   - **知识抽取**: 自动提取结构化知识点
   - **混合检索**: BM25 + 向量检索，提高准确性
   - **用例流水线**: 4 步高级用例生成
   - **覆盖率报告**: 分析测试用例覆盖度
   - **冲突检测**: 发现需求中的矛盾
   - **反馈闭环**: 通过点赞优化生成质量

### 使用历史用例

如果你有团队的 Excel 测试用例或 XMind 脑图：

1. 进入「目录管理」→「历史用例」Tab
2. 上传 Excel 文件（10 列标准格式）
3. 确认列映射关系
4. 在生成用例时使用 `@文件名` 引用

### 增量更新

当你修改或添加了新文档：

1. 再次点击「构建 AI 记忆」
2. 系统只会处理变更的文件
3. 未变更的文件不会重新分析

## ❓ 常见问题

### Q: 首次启动很慢？
A: 首次使用会下载嵌入模型（约 100MB），请耐心等待。后续启动会很快。

### Q: 如何更换 LLM 提供商？
A: 在「设置」中修改 Base URL：
- OpenRouter: `https://openrouter.ai/api/v1`
- OpenAI: `https://api.openai.com/v1`
- Ollama (本地): `http://localhost:11434/v1`

### Q: 文档太多怎么办？
A: 
- 可以分批添加文件夹
- 大型文档（>100页）建议拆分
- 启用「混合检索」提高大项目的检索效果

### Q: 如何备份我的数据？
A: 备份整个 `memory/` 和 `vector_store/` 目录即可。

### Q: 可以离线使用吗？
A: 
- 嵌入模型下载后可以离线使用
- LLM 调用仍需网络（除非使用本地部署的 Ollama）

### Q: 生成的测试用例不准确？
A: 
- 检查文档是否清晰完整
- 尝试调整问题描述
- 开启「反馈闭环」，对好用例点赞
- 启用「历史用例参考」，让 AI 学习团队风格

## 🛠️ 故障排查

### 端口被占用
```bash
# 停止服务
python stop.py

# 或手动杀死进程
# Windows: taskkill /F /PID <进程号>
# Linux/Mac: kill <进程号>
```

### 依赖安装失败
```bash
# 手动安装后端依赖
cd backend
pip install -r requirements.txt

# 手动安装前端依赖
cd frontend
npm install
```

### 模型下载失败
检查网络连接，或手动下载模型：
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
```

## 📖 更多资源

- [完整文档](README.md)
- [API 参考](README.md#api-列表)
- [开发指南](CONTRIBUTING.md)
- [GitHub Issues](https://github.com/yourusername/CaseMind/issues)

## 🎉 开始探索

现在你已经掌握了基础知识，开始探索 CaseMind 的强大功能吧！

如有问题，欢迎提交 Issue 或参与讨论。
