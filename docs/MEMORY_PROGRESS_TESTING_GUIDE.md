# 🧪 Memory构建进度控制 - 测试指南

## ✅ 已完成的修改

### 后端文件
1. ✅ `backend/agents/memory_progress_tracker.py` - 创建进度跟踪器
2. ✅ `backend/api/routes.py` - 添加4个API端点
3. ✅ `backend/agents/memory_agent.py` - 集成进度跟踪到build()方法

### 前端文件
1. ✅ `frontend/src/api.js` - 添加4个API调用方法
2. ✅ `frontend/src/pages/Memory.jsx` - 添加进度UI和控制逻辑

## 🚀 启动测试

### 第1步：重启后端服务

```bash
# 停止当前运行的服务（如果正在运行）
# 然后重新启动
python run.py
```

或者如果使用Docker：
```bash
docker-compose restart backend
```

### 第2步：刷新前端页面

在浏览器中刷新页面（Ctrl+F5 或 Cmd+Shift+R 强制刷新）

### 第3步：测试基本功能

#### 测试1：启动构建并查看进度

1. 进入"记忆面板"页面
2. 选择一个有文档的项目
3. 点击"构建 AI 记忆"按钮
4. **预期结果**：
   - ✅ 显示进度卡片
   - ✅ 进度条开始更新
   - ✅ 显示当前步骤（如"扫描文件夹"、"处理新增/变更文件"等）
   - ✅ 文件数量实时更新
   - ✅ LLM调用次数增加
   - ✅ 耗时计时器运行

#### 测试2：暂停功能

1. 在构建进行中时，点击"暂停"按钮
2. **预期结果**：
   - ✅ 显示"暂停请求已发送"消息
   - ✅ 当前文件处理完成后暂停
   - ✅ 进度卡片显示"已暂停"标签
   - ✅ "暂停"按钮变为"继续"按钮
   - ✅ 进度条停止更新

3. 点击"继续"按钮
4. **预期结果**：
   - ✅ 显示"继续构建"消息
   - ✅ 从暂停处继续处理
   - ✅ 进度条继续更新

#### 测试3：取消功能

1. 在构建进行中时，点击"取消"按钮
2. **预期结果**：
   - ✅ 弹出确认对话框："确定要取消构建吗？..."
   - ✅ 点击确认后显示"取消请求已发送"
   - ✅ 进度卡片消失
   - ✅ 构建按钮恢复可用状态
   - ✅ 已有的memory.md和prompt保留（如果之前有）

3. 检查memory.md内容
4. **预期结果**：
   - ✅ 如果之前有memory，内容仍然保留
   - ✅ 可以在"版本历史"中看到之前的版本

#### 测试4：完成状态

1. 让构建自然完成（不暂停/取消）
2. **预期结果**：
   - ✅ 进度卡片自动消失
   - ✅ 显示完成消息："构建完成！耗时 X:XX"
   - ✅ 显示统计信息（新增、更新、跳过、删除的文件数）
   - ✅ memory.md和prompt已更新
   - ✅ 版本历史中有新版本记录

#### 测试5：错误处理

1. 故意配置一个不存在的路径
2. 或者断开网络连接
3. **预期结果**：
   - ✅ 显示错误消息
   - ✅ 进度卡片显示错误状态
   - ✅ 可以重试构建

#### 测试6：刷新页面

1. 在构建进行中时，刷新浏览器页面
2. **预期结果**：
   - ✅ 如果后端仍在构建，进度应该能恢复显示
   - ✅ 或者至少不会报错

#### 测试7：防止重复点击

1. 点击"构建 AI 记忆"按钮
2. **预期结果**：
   - ✅ 按钮变为禁用状态（opacity: 0.7, cursor: not-allowed）
   - ✅ 无法再次点击
   - ✅ 只有在构建完成后才能再次点击

## 📊 验证API端点

可以使用curl或Postman测试API：

### 获取进度
```bash
curl http://localhost:8000/api/memory/build/progress?project=投放管理平台
```

**预期响应**：
```json
{
  "project": "投放管理平台",
  "status": "running",
  "current_step": 3,
  "total_steps": 6,
  "step_name": "处理新增/变更文件",
  "processed_files": 45,
  "total_files": 120,
  "llm_calls": 48,
  "extracted_kps": 156,
  "elapsed_seconds": 125.3,
  "message": "正在处理第 45/120 个文件...",
  "error": null,
  "progress_percent": 37.5
}
```

### 暂停构建
```bash
curl -X POST http://localhost:8000/api/memory/build/pause?project=投放管理平台
```

**预期响应**：
```json
{"ok": true, "message": "Pause requested"}
```

### 继续构建
```bash
curl -X POST http://localhost:8000/api/memory/build/resume?project=投放管理平台
```

**预期响应**：
```json
{"ok": true, "message": "Resumed"}
```

### 取消构建
```bash
curl -X POST http://localhost:8000/api/memory/build/cancel?project=投放管理平台
```

**预期响应**：
```json
{"ok": true, "message": "Cancel requested"}
```

## 🔍 调试技巧

### 查看后端日志

在后端终端中，你应该能看到类似这样的日志：

```
[MemoryBuild] Pause requested for 投放管理平台
[MemoryBuild] Resumed for 投放管理平台
[MemoryBuild] Cancel requested for 投放管理平台
[MemoryBuild] Completed for 投放管理平台: status=completed
```

### 查看前端控制台

打开浏览器开发者工具（F12），在Console中查看：
- API调用是否成功
- 是否有JavaScript错误
- 进度数据是否正确接收

### 检查Network请求

在Network标签中：
- 查看 `/api/memory/build/progress` 请求是否每2秒发送一次
- 查看响应数据是否正确
- 查看暂停/继续/取消请求是否成功

## ⚠️ 常见问题排查

### 问题1：进度不更新

**可能原因**：
- 后端没有正确调用 `controller.update_progress()`
- API端点返回的数据格式不正确

**解决方法**：
1. 检查后端日志是否有错误
2. 在浏览器Console中查看API响应
3. 确认 `memory_agent.py` 中的进度更新调用

### 问题2：暂停不起作用

**可能原因**：
- 没有在处理循环中检查 `controller.check_should_pause()`
- 暂停标志没有被正确设置

**解决方法**：
1. 确认 `memory_agent.py` 中有while循环检查暂停
2. 检查API调用是否成功
3. 查看后端日志

### 问题3：取消后memory丢失

**可能原因**：
- 这是不应该发生的，检查是否有其他代码删除了文件

**解决方法**：
1. 检查 `memory_agent.py` 的取消处理逻辑
2. 确认取消时没有调用清理代码
3. 查看文件系统确认文件仍然存在

### 问题4：进度卡片不显示

**可能原因**：
- 前端状态没有正确更新
- 条件渲染有问题

**解决方法**：
1. 在React DevTools中检查 `buildProgress` 状态
2. 确认 `busy` 和 `buildProgress` 都不为null
3. 检查浏览器Console是否有错误

## 📝 测试清单

使用此清单确保所有功能都正常工作：

- [ ] 启动构建后显示进度卡片
- [ ] 进度条实时更新
- [ ] 当前步骤正确显示
- [ ] 文件数量正确统计
- [ ] LLM调用次数正确统计
- [ ] 知识点数量正确统计（如果启用）
- [ ] 耗时计时器正常运行
- [ ] 暂停功能正常工作
- [ ] 继续功能正常工作
- [ ] 取消功能正常工作
- [ ] 取消后已有memory保留
- [ ] 构建完成后显示完成消息
- [ ] 构建完成后刷新页面数据
- [ ] 错误情况正确处理
- [ ] 刷新页面后进度能恢复（可选）
- [ ] 构建按钮在busy时禁用
- [ ] 防止重复点击

## 🎉 成功标志

如果以上测试都通过，恭喜你！Memory构建进度控制功能已经成功实现。

你现在可以：
- ✅ 清晰看到构建的实时进度
- ✅ 随时暂停和继续长时间运行的构建
- ✅ 安全取消而不担心丢失已有记忆
- ✅ 更好地控制API费用
- ✅ 提升整体使用体验

## 📞 需要帮助？

如果遇到任何问题：
1. 查看后端日志
2. 检查浏览器Console
3. 参考设计文档
4. 联系开发团队
