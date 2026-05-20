# 用例和XMind显示优化报告

## 🎯 优化目标

1. **用例显示**：改为弹窗显示详情，列表保持简略信息
2. **XMind显示**：默认折叠所有分支，添加一键展开/折叠功能，支持手动展开部分节点

---

## ✅ 实现方案

### 1. 用例表格优化

#### 修改前
- 点击文件行后在下方展开显示所有用例
- 每个用例可以点击展开查看详细步骤
- 页面过长，需要大量滚动

#### 修改后
- 点击文件行弹出**模态对话框**显示所有用例
- 用例列表保持简略（序号、名称、模块、阶段、步骤数、等级、类型）
- **支持分页**：每页显示20条用例，避免弹窗过长
- 点击单条用例弹出**二级对话框**显示详细信息
- 支持分行显示步骤和预期，更易阅读

---

### 2. XMind树视图优化

#### 修改前
- 默认展开所有节点
- 没有一键展开/折叠功能
- 用户需要手动逐个折叠

#### 修改后
- **默认全部折叠**：打开文件时只显示根节点
- **一键展开/折叠按钮**：头部工具栏添加两个按钮
  - `unfold_more` - 全部展开
  - `unfold_less` - 全部折叠
- **手动控制**：用户可以点击任意节点展开/折叠
- **高度限制**：树形内容区域设置最大高度，超出可滚动

---

## 📝 技术实现

### 文件1：LegacyCaseTable.jsx

**位置**：`frontend/src/components/LegacyCaseTable.jsx`

**主要改动**：

1. **移除行内展开逻辑**：
   ```jsx
   // 修改前
   const [openId, setOpenId] = useState('');
   
   // 修改后
   const [selectedCase, setSelectedCase] = useState(null);
   const [currentPage, setCurrentPage] = useState(1);
   const pageSize = 20; // 每页显示20条
   ```

2. **添加分页逻辑**：
   ```jsx
   // 计算分页数据
   const totalPages = Math.ceil(cases.length / pageSize);
   const startIndex = (currentPage - 1) * pageSize;
   const endIndex = startIndex + pageSize;
   const currentPageCases = cases.slice(startIndex, endIndex);
   
   // 重置页码（当cases变化时）
   React.useEffect(() => {
     setCurrentPage(1);
   }, [cases]);
   ```

3. **简化表格行**：
   - 移除展开箭头图标
   - 添加序号列（使用全局序号：`startIndex + idx + 1`）
   - 移除case_id显示（移到弹窗中）
   - 添加hover效果

4. **添加分页控件**：
   ```jsx
   {totalPages > 1 && (
     <div style={{ display: 'flex', justifyContent: 'space-between', ... }}>
       <div>第 {currentPage} / {totalPages} 页 · 共 {cases.length} 条</div>
       <div>
         <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))}>
           上一页
         </button>
         <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}>
           下一页
         </button>
       </div>
     </div>
   )}
   ```

5. **添加用例详情弹窗**：
   ```jsx
   {selectedCase && (
     <div style={{ position: 'fixed', inset: 0, ... }}>
       <div className="card" style={{ width: 800, ... }}>
         {/* 头部：标题 + case_id */}
         {/* 元信息网格：模块、阶段、优先级、类型、创建人、来源 */}
         {/* 前置条件 */}
         {/* 步骤/预期（分行显示）*/}
       </div>
     </div>
   )}
   ```

6. **步骤/预期分行显示**：
   ```jsx
   <div style={{ display: 'grid', gridTemplateColumns: '40px 1fr 1fr', ... }}>
     <div className="mono">{s.index}</div>
     <div>
       <div className="muted">操作</div>
       <div>{s.action}</div>
     </div>
     <div>
       <div className="muted">预期</div>
       <div style={{ color: '#7fd9a8' }}>{s.expected}</div>
     </div>
   </div>
   ```

---

### 文件2：LegacyXMindTreeView.jsx

**位置**：`frontend/src/components/LegacyXMindTreeView.jsx`

**主要改动**：

1. **默认全部折叠**：
   ```jsx
   useMemo(() => {
     if (tree) {
       const allNodeIds = new Set();
       (tree.nodes || []).forEach(n => {
         if (!n.is_leaf && n.children_ids?.length > 0) {
           allNodeIds.add(n.node_id);
         }
       });
       setCollapsed(allNodeIds); // 默认全部折叠
     }
   }, [tree]);
   ```

2. **添加一键展开/折叠函数**：
   ```jsx
   function expandAll() {
     setCollapsed(new Set());
   }

   function collapseAll() {
     const allNodeIds = new Set();
     (tree.nodes || []).forEach(n => {
       if (!n.is_leaf && n.children_ids?.length > 0) {
         allNodeIds.add(n.node_id);
       }
     });
     setCollapsed(allNodeIds);
   }
   ```

3. **头部控制栏**：
   ```jsx
   <div style={{ display: 'flex', alignItems: 'center', gap: 8, ... }}>
     <span className="mi">account_tree</span>
     <span style={{ fontWeight: 500, flex: 1 }}>{tree.name}</span>
     <span className="tag info mono">{nodes.length} 节点</span>
     <button onClick={expandAll} title="全部展开">
       <span className="mi">unfold_more</span>
     </button>
     <button onClick={collapseAll} title="全部折叠">
       <span className="mi">unfold_less</span>
     </button>
   </div>
   ```

4. **内容区域高度限制**：
   ```jsx
   <div style={{ maxHeight: 'calc(100vh - 300px)', overflow: 'auto' }}>
     {renderNode(root, 0)}
   </div>
   ```

---

### 文件3：Folders.jsx

**位置**：`frontend/src/pages/Folders.jsx`

**主要改动**：

1. **状态变量调整**：
   ```jsx
   // 修改前
   const [openFid, setOpenFid] = useState('');
   
   // 修改后
   const [selectedFileId, setSelectedFileId] = useState('');
   ```

2. **toggle函数简化**：
   ```jsx
   async function toggle(fid) {
     setSelectedFileId(fid); // 直接设置为选中
     if (!casesByFid[fid]) {
       // 加载用例数据
       const r = await api.legacyGetCaseFile(project, fid);
       setCasesByFid(c => ({ ...c, [fid]: r.cases || [] }));
     }
   }
   ```

3. **文件列表简化**：
   - 移除展开箭头图标
   - 移除行内展开的内容区域
   - 添加hover效果
   - 保持简洁的单行显示

4. **添加用例文件详情弹窗**：
   ```jsx
   {selectedFileId && casesByFid[selectedFileId] && (
     <div style={{ position: 'fixed', inset: 0, ... }} onClick={() => setSelectedFileId('')}>
       <div className="card" style={{ width: '90vw', maxWidth: 1200, ... }}>
         {/* 头部：文件名 + 用例数 + 分析状态 */}
         {/* 解析告警 */}
         {/* LegacyCaseTable组件 */}
       </div>
     </div>
   )}
   ```

---

## 🎨 UI设计要点

### 用例详情弹窗

**布局结构**：
```
┌─────────────────────────────────────┐
│ 📄 用例标题                          │
│    LC_xxx                            │
│                              [关闭]  │
├─────────────────────────────────────┤
│ 模块/子项 | 阶段 | 优先级 | 类型...  │
├─────────────────────────────────────┤
│ 前置条件                             │
│ ┌─────────────────────────────────┐ │
│ │ xxx                             │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ 步骤 / 预期 (N步)                   │
│ ┌───┬──────────┬──────────────────┐ │
│ │ 1 │ 操作xxx  │ 预期xxx          │ │
│ ├───┼──────────┼──────────────────┤ │
│ │ 2 │ 操作xxx  │ 预期xxx          │ │
│ └───┴──────────┴──────────────────┘ │
└─────────────────────────────────────┘
```

**视觉特点**：
- 宽度800px，最大高度85vh
- 元信息使用网格布局，自适应列数
- 步骤和预期并排显示，用绿色突出预期
- 背景色区分不同区域

---

### XMind树视图

**布局结构**：
```
┌─────────────────────────────────────┐
│ 🌳 文件名        649节点 [⬆] [⬇]   │
├─────────────────────────────────────┤
│ > 根节点 · 5                        │
│   > 子节点1 · 3                     │
│   > 子节点2 · 2                     │
│   ...                               │
└─────────────────────────────────────┘
```

**视觉特点**：
- 头部有分隔线，与内容区分
- 按钮使用ghost样式，不抢眼
- 节点hover有高亮效果
- 叶子节点用绿色圆点标识
- 父节点用紫色箭头标识

---

## 💡 用户体验提升

### 用例查看
1. **减少页面长度**：不再在列表中展开所有内容
2. **快速浏览**：简略信息一目了然
3. **按需查看**：点击才看详情，避免信息过载
4. **清晰对比**：步骤和预期并排显示，方便对照

### XMind浏览
1. **初始清爽**：默认折叠，不会一下子展示太多内容
2. **灵活控制**：可以一键展开/折叠，也可以手动控制
3. **局部展开**：只展开感兴趣的分支，其他保持折叠
4. **滚动友好**：高度限制，长树也能轻松浏览

---

## 🚀 测试建议

### 用例测试
1. 上传一个Excel文件
2. 点击文件行，应该弹出对话框
3. 点击单条用例，应该弹出二级对话框
4. 检查步骤和预期是否分行显示
5. 检查关闭按钮是否正常

### XMind测试
1. 上传一个XMind文件
2. 点击文件，应该只显示根节点（全部折叠）
3. 点击"全部展开"按钮，应该展开所有节点
4. 点击"全部折叠"按钮，应该折叠所有节点
5. 手动点击某个节点，应该只展开该分支
6. 检查滚动是否正常

---

## 📊 性能考虑

### 优点
- **懒加载**：用例数据只在点击时才加载
- **虚拟滚动**：虽然没用虚拟列表，但弹窗限制了最大高度
- **状态管理**：已加载的数据缓存到`casesByFid`，避免重复请求

### 潜在优化
- 如果用例数量超过1000条，可以考虑分页或虚拟滚动
- XMind节点过多时，可以考虑懒加载子节点

---

## 📝 相关文件

- [LegacyCaseTable.jsx](file:///D:/CaseMind/frontend/src/components/LegacyCaseTable.jsx) - 用例表格组件
- [LegacyXMindTreeView.jsx](file:///D:/CaseMind/frontend/src/components/LegacyXMindTreeView.jsx) - XMind树视图组件
- [Folders.jsx](file:///D:/CaseMind/frontend/src/pages/Folders.jsx) - 文件夹页面

---

## ✨ 总结

### 已完成
✅ 用例改为弹窗显示详情  
✅ 用例列表保持简略信息  
✅ **支持分页**：每页20条，避免弹窗过长  
✅ 单条用例点击显示详细信息（二级弹窗）  
✅ 步骤和预期分行显示，更易阅读  
✅ XMind默认折叠所有分支  
✅ 添加一键展开/折叠按钮  
✅ 支持手动展开部分节点  
✅ 树形内容区域高度限制，支持滚动  

### 用户体验
- **更清爽**：页面不再过长，信息密度适中
- **更高效**：快速浏览 + 按需查看详情
- **更灵活**：XMind可以自由控制展开范围
- **更美观**：弹窗设计精美，层次分明

**请刷新页面测试新的显示方式！** 🎊
