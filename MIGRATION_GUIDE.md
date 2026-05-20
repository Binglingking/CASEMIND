# 数据迁移指南

如果你已经有 CaseMind 的个人数据，想要：
1. 继续本地使用
2. 同时贡献代码到 GitHub

请按照以下步骤操作。

## 🎯 目标

- ✅ 保留所有个人数据在本地
- ✅ 只提交代码到 GitHub
- ✅ 不影响本地正常使用

## 📋 操作步骤

### 第 1 步：更新 .gitignore

确保你的 `.gitignore` 文件已更新（项目已包含最新的 `.gitignore`）。

### 第 2 步：检查 Git 状态

```bash
git status
```

查看哪些文件会被提交。**不应该**包含：
- ❌ `memory/*/` 下的任何个人数据
- ❌ `vector_store/*` 下的索引文件
- ❌ `docs/*/` 下的业务文档
- ❌ `outputs/*` 下的生成结果
- ❌ `.env` 文件

### 第 3 步：移除已追踪的敏感文件（如果有）

如果发现敏感文件已被 Git 追踪：

```bash
# 从 Git 追踪中移除（但保留本地文件）
git rm --cached -r memory/*/
git rm --cached vector_store/*
git rm --cached docs/AI用例
git rm --cached docs/国内GM平台
git rm --cached docs/投放管理平台
git rm --cached outputs/*
git rm --cached .env
git rm --cached *.jsonl
git rm --cached rate_limit_report*.json
git rm --cached test_report*.json

# 提交更改
git add .gitignore
git commit -m "chore: 更新 .gitignore 排除个人数据"
```

### 第 4 步：验证

```bash
# 再次检查
git status

# 应该只看到代码文件，没有个人数据
git ls-files | Select-String -Pattern "memory|vector_store|docs/.*\.(docx|xlsx|pdf)"
# 应该没有输出
```

### 第 5 步：正常继续使用

你的本地数据完全不受影响，可以继续使用 CaseMind：
- ✅ 所有项目数据保留
- ✅ 向量索引保留
- ✅ 历史文档保留
- ✅ 生成的用例保留

只是这些数据不会被提交到 Git。

## 🔄 在其他机器上使用

如果你想在另一台电脑上使用：

### 方案 A：同步代码 + 独立数据（推荐）

1. 在新机器上克隆代码
   ```bash
   git clone https://github.com/yourusername/CaseMind.git
   cd CaseMind
   ```

2. 初始化
   ```bash
   python init_data.py --demo
   ```

3. 启动并创建新项目
   ```bash
   start.bat  # 或 ./start.sh
   ```

4. 添加新机器上的文档，重新构建记忆

### 方案 B：完整数据迁移

如果你想把所有数据迁移到新机器：

1. 打包个人数据
   ```powershell
   # Windows (PowerShell)
   Compress-Archive -Path memory,vector_store,outputs -DestinationPath casemind-data.zip
   ```
   
   ```bash
   # Linux/Mac
   tar -czf casemind-data.tar.gz memory vector_store outputs
   ```

2. 在新机器上：
   - 克隆代码
   - 解压数据包到项目根目录
   - 启动应用

## ⚠️ 注意事项

1. **不要提交 `.env` 文件**
   - 如果已经创建了 `.env`，确保它在 `.gitignore` 中
   - 使用 `.env.example` 作为模板

2. **定期清理生成文件**
   ```bash
   # 预览将要清理的文件
   python init_data.py --preview-clean
   
   # 实际清理（谨慎使用！）
   python init_data.py --clean
   ```

3. **备份重要数据**
   - 定期备份 `memory/` 和 `vector_store/` 目录
   - 可以使用云存储或外部硬盘

## 🔒 隐私保护

上传到 GitHub 前，请确认：

- [ ] 没有硬编码的 API Key
- [ ] 没有提交个人文档内容
- [ ] 没有提交业务数据
- [ ] `.gitignore` 正确配置
- [ ] 运行 `git status` 确认无敏感文件

## 💡 最佳实践

1. **代码与数据分离**
   - 代码放在 Git 仓库
   - 数据保存在本地或私有存储

2. **使用环境变量**
   - API Key 等敏感信息通过环境变量配置
   - 提供 `.env.example` 作为模板

3. **文档脱敏**
   - 如需分享示例，创建脱敏后的测试文档
   - 放在 `examples/` 目录并提交

4. **定期审查**
   - 每次提交前检查 `git status`
   - 使用 `git diff --cached` 查看将要提交的内容

## 📞 需要帮助？

如有问题，请：
1. 查看 [GETTING_STARTED.md](GETTING_STARTED.md)
2. 查阅 [README.md](README.md)
3. 提交 GitHub Issue
