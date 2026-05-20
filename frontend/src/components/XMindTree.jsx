import React, { useMemo, useState, useCallback } from 'react';

// Parse markdown with # / ## / ### / - list indentation into a tree.
function parseMarkdown(md) {
  const root = { name: 'Root', children: [], path: 'root' };
  const stack = [{ level: 0, node: root }];
  const lines = (md || '').split(/\r?\n/);
  let seq = 0;
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) continue;
    let level = 0, name = '';
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      level = h[1].length;
      name = h[2].trim();
    } else {
      const b = line.match(/^(\s*)[-*]\s+(.*)$/);
      if (!b) continue;
      const indent = b[1].replace(/\t/g, '  ').length;
      level = 6 + Math.floor(indent / 2) + 1;
      name = b[2].trim();
    }
    if (!name) continue;
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
    const parent = stack[stack.length - 1]?.node || root;
    const path = `${parent.path}/${seq++}`;
    const node = { name, children: [], path };
    parent.children.push(node);
    stack.push({ level, node });
  }
  return root.children.length === 1 ? root.children[0] : root;
}

function collectPaths(node, out = []) {
  if (node.children && node.children.length > 0) {
    out.push(node.path);
    node.children.forEach(c => collectPaths(c, out));
  }
  return out;
}

function Node({ node, depth, expanded, toggle }) {
  const hasChildren = node.children && node.children.length > 0;
  const open = expanded.has(node.path);
  return (
    <li>
      <span
        className="node"
        style={{ cursor: hasChildren ? 'pointer' : 'default', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        onClick={() => hasChildren && toggle(node.path)}
      >
        {hasChildren ? (
          <span className="mi" style={{ fontSize: 14, color: '#cfbcff', transition: 'transform 160ms ease', transform: open ? 'rotate(0deg)' : 'rotate(-90deg)' }}>
            expand_more
          </span>
        ) : (
          <span className="mi" style={{ fontSize: 8, color: '#6b6772', marginRight: 2 }}>circle</span>
        )}
        <span style={{
          fontWeight: depth <= 1 ? 600 : 500,
          color: depth === 0 ? '#e6e0e9' : depth === 1 ? '#e0d2ff' : '#d8d3de',
        }}>{node.name}</span>
        {hasChildren && <span className="muted mono" style={{ fontSize: 11, marginLeft: 4 }}>({node.children.length})</span>}
      </span>
      {hasChildren && open && (
        <ul>{node.children.map(c => (
          <Node key={c.path} node={c} depth={depth + 1} expanded={expanded} toggle={toggle} />
        ))}</ul>
      )}
    </li>
  );
}

export default function XMindTree({ markdown }) {
  const tree = useMemo(() => parseMarkdown(markdown || ''), [markdown]);
  const allPaths = useMemo(() => collectPaths(tree), [tree]);
  const [expanded, setExpanded] = useState(() => new Set(allPaths));

  // re-seed expanded when tree changes (different markdown)
  React.useEffect(() => {
    setExpanded(new Set(allPaths));
  }, [markdown]);

  const toggle = useCallback((path) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }, []);

  const expandAll = () => setExpanded(new Set(allPaths));
  const collapseAll = () => setExpanded(new Set());

  if (!markdown) return <p className="muted">暂无 XMind。先在 AI 对话页选择 "XMind" 模式生成。</p>;

  return (
    <div>
      <div className="row" style={{ marginBottom: 10, justifyContent: 'flex-end' }}>
        <button className="ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={expandAll}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>unfold_more</span>
          全部展开
        </button>
        <button className="ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={collapseAll}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>unfold_less</span>
          全部收起
        </button>
      </div>
      <div className="tree">
        <ul><Node node={tree} depth={0} expanded={expanded} toggle={toggle} /></ul>
      </div>
      <details style={{ marginTop: 16 }}>
        <summary style={{ cursor: 'pointer', color: '#b5afbd', fontSize: 13 }}>原始 Markdown（可复制导入 XMind）</summary>
        <pre className="code" style={{ marginTop: 8 }}>{markdown}</pre>
      </details>
    </div>
  );
}
