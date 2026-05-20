import React, { useMemo, useState } from 'react';

/**
 * 历史 XMind 树形视图 — 默认折叠所有分支，支持一键展开/折叠。
 * Props:
 *   tree: LegacyXMindTree (model_dump)
 */
export default function LegacyXMindTreeView({ tree }) {
  const [collapsed, setCollapsed] = useState(new Set());

  const byId = useMemo(() => {
    const m = {};
    (tree?.nodes || []).forEach(n => { m[n.node_id] = n; });
    return m;
  }, [tree]);

  // 当tree变化时，重置为全部折叠
  useMemo(() => {
    if (tree) {
      // 收集所有有子节点的节点ID
      const allNodeIds = new Set();
      (tree.nodes || []).forEach(n => {
        if (!n.is_leaf && n.children_ids?.length > 0) {
          allNodeIds.add(n.node_id);
        }
      });
      setCollapsed(allNodeIds); // 默认全部折叠
    }
  }, [tree]);

  if (!tree) {
    return <div className="muted" style={{ padding: 24, textAlign: 'center' }}>请选择一份 XMind 文件</div>;
  }

  const root = byId[tree.root_id];
  if (!root) {
    return <div className="err" style={{ padding: 12 }}>根节点不存在：{tree.root_id}</div>;
  }

  function toggle(id) {
    setCollapsed(c => {
      const next = new Set(c);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // 一键全部展开
  function expandAll() {
    setCollapsed(new Set());
  }

  // 一键全部折叠
  function collapseAll() {
    const allNodeIds = new Set();
    (tree.nodes || []).forEach(n => {
      if (!n.is_leaf && n.children_ids?.length > 0) {
        allNodeIds.add(n.node_id);
      }
    });
    setCollapsed(allNodeIds);
  }

  function renderNode(node, depth) {
    if (!node) return null;
    const hasChild = !node.is_leaf && node.children_ids?.length > 0;
    const isCollapsed = collapsed.has(node.node_id);
    return (
      <div key={node.node_id}>
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 8px', paddingLeft: 8 + depth * 18,
            cursor: hasChild ? 'pointer' : 'default',
            borderRadius: 6,
          }}
          onClick={() => hasChild && toggle(node.node_id)}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(207,188,255,0.06)'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          {hasChild ? (
            <span className="mi" style={{ fontSize: 16, color: '#cfbcff' }}>
              {isCollapsed ? 'chevron_right' : 'expand_more'}
            </span>
          ) : (
            <span className="mi" style={{ fontSize: 14, color: '#7fd9a8' }}>radio_button_unchecked</span>
          )}
          <span style={{ fontSize: 13, color: '#e6e0e9' }}>{node.title || '(未命名)'}</span>
          {hasChild && (
            <span className="muted mono" style={{ fontSize: 11 }}>
              · {node.children_ids.length}
            </span>
          )}
        </div>
        {hasChild && !isCollapsed && (
          <div>
            {node.children_ids.map(cid => renderNode(byId[cid], depth + 1))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 8, margin: 0 }}>
      {/* 头部控制栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 12, padding: '8px 8px',
        borderBottom: '1px solid #2b292f',
      }}>
        <span className="mi" style={{ color: '#e7c365' }}>account_tree</span>
        <span style={{ fontWeight: 500, flex: 1 }}>{tree.name}</span>
        <span className="tag info mono">{(tree.nodes || []).length} 节点</span>
        <button
          className="ghost"
          style={{ padding: '4px 8px', fontSize: 12 }}
          onClick={expandAll}
          title="全部展开"
        >
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3 }}>unfold_more</span>
        </button>
        <button
          className="ghost"
          style={{ padding: '4px 8px', fontSize: 12 }}
          onClick={collapseAll}
          title="全部折叠"
        >
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3 }}>unfold_less</span>
        </button>
      </div>

      {/* 树形内容 */}
      <div style={{ maxHeight: 'calc(100vh - 300px)', overflow: 'auto' }}>
        {renderNode(root, 0)}
      </div>
    </div>
  );
}
