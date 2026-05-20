import React from 'react';

export default function TestCaseTable({ cases }) {
  if (!cases || cases.length === 0) {
    return <p className="muted">暂无测试用例。先在 AI 对话页选择 "测试用例" 模式生成。</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>目录</th>
          <th>模块</th>
          <th>子项</th>
          <th>用例名称</th>
          <th>前置条件</th>
          <th>步骤</th>
          <th>预期结果</th>
          <th>来源</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c, i) => (
          <tr key={i}>
            <td>{i + 1}</td>
            <td>{c.catalog || ''}</td>
            <td>{c.module || ''}</td>
            <td>{c.sub_item || ''}</td>
            <td>
              {c.name || ''}
              {c.uncertain ? <span className="tag warn" style={{ marginLeft: 6 }}>⚠ 推测</span> : null}
            </td>
            <td>{c.preconditions || ''}</td>
            <td>
              <ol style={{ margin: 0, paddingLeft: 18 }}>
                {(c.steps || []).map((s, j) => <li key={j}>{s}</li>)}
              </ol>
            </td>
            <td>{c.expected || ''}</td>
            <td>{(c.source_refs || []).join('; ')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
