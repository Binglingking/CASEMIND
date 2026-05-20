import React, { useState } from 'react';

/**
 * 历史用例表格 — 点击行弹出详情对话框，支持分页。
 * Props:
 *   cases: LegacyCase[] (model_dump 后的字典)
 */
export default function LegacyCaseTable({ cases = [] }) {
  const [selectedCase, setSelectedCase] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 20; // 每页显示20条

  // 计算分页数据
  const totalPages = Math.ceil(cases.length / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const currentPageCases = cases.slice(startIndex, endIndex);

  // 重置页码（当cases变化时）
  React.useEffect(() => {
    setCurrentPage(1);
  }, [cases]);

  if (!cases.length) {
    return <div className="muted" style={{ padding: 24, textAlign: 'center' }}>该文件下暂无解析后的用例</div>;
  }

  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th>用例名称</th>
              <th>模块/子项</th>
              <th>阶段</th>
              <th>步骤数</th>
              <th>等级</th>
              <th>类型</th>
            </tr>
          </thead>
          <tbody>
            {currentPageCases.map((c, idx) => (
              <tr
                key={c.case_id}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedCase(c)}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(207,188,255,0.06)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td className="mono" style={{ color: '#948e9c' }}>{startIndex + idx + 1}</td>
                <td>
                  <div style={{ fontWeight: 500 }}>{c.title || '(未命名)'}</div>
                </td>
                <td style={{ color: '#d8d3de', fontSize: 12 }}>{c.module || '-'} / {c.sub_item || '-'}</td>
                <td>{c.stage ? <span className="tag info">{c.stage}</span> : <span className="muted">-</span>}</td>
                <td>{c.steps?.length ?? 0}</td>
                <td>{c.priority ? <span className="tag warn">{c.priority}</span> : '-'}</td>
                <td>{c.case_type || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 分页控件 */}
      {totalPages > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 0', marginTop: 12,
          borderTop: '1px solid #2b292f',
        }}>
          <div className="muted" style={{ fontSize: 12 }}>
            第 {currentPage} / {totalPages} 页 · 共 {cases.length} 条
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="ghost"
              disabled={currentPage === 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              style={{
                padding: '4px 12px', fontSize: 12,
                opacity: currentPage === 1 ? 0.5 : 1,
                cursor: currentPage === 1 ? 'not-allowed' : 'pointer',
              }}
            >
              <span className="mi" style={{ fontSize: 16, verticalAlign: -3 }}>chevron_left</span>
              上一页
            </button>
            <button
              className="ghost"
              disabled={currentPage === totalPages}
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              style={{
                padding: '4px 12px', fontSize: 12,
                opacity: currentPage === totalPages ? 0.5 : 1,
                cursor: currentPage === totalPages ? 'not-allowed' : 'pointer',
              }}
            >
              下一页
              <span className="mi" style={{ fontSize: 16, verticalAlign: -3 }}>chevron_right</span>
            </button>
          </div>
        </div>
      )}

      {/* 用例详情弹窗 */}
      {selectedCase && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 100,
          }}
          onClick={() => setSelectedCase(null)}
        >
          <div
            className="card"
            style={{
              width: 800, maxHeight: '85vh', overflow: 'auto',
              margin: 0, padding: 24,
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* 头部 */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 20 }}>
              <span className="mi" style={{ fontSize: 24, color: '#7fd9a8' }}>description</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 4 }}>
                  {selectedCase.title || '(未命名)'}
                </div>
                <div className="muted mono" style={{ fontSize: 12 }}>
                  {selectedCase.case_id}
                </div>
              </div>
              <button className="ghost" onClick={() => setSelectedCase(null)}>
                <span className="mi">close</span>
              </button>
            </div>

            {/* 元信息 */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: 12, marginBottom: 20, padding: 16,
              background: 'rgba(15,13,19,0.3)', borderRadius: 8,
            }}>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>模块/子项</div>
                <div style={{ fontSize: 13 }}>{selectedCase.module || '-'} / {selectedCase.sub_item || '-'}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>阶段</div>
                <div>{selectedCase.stage ? <span className="tag info">{selectedCase.stage}</span> : '-'}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>优先级</div>
                <div>{selectedCase.priority ? <span className="tag warn">{selectedCase.priority}</span> : '-'}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>类型</div>
                <div style={{ fontSize: 13 }}>{selectedCase.case_type || '-'}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>创建人</div>
                <div style={{ fontSize: 13 }}>{selectedCase.creator || '-'}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>来源</div>
                <div className="mono" style={{ fontSize: 12 }}>
                  {selectedCase.source_file} · 行 {selectedCase.source_row}
                </div>
              </div>
            </div>

            {/* 前置条件 */}
            {selectedCase.preconditions && (
              <div style={{ marginBottom: 20 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 8, fontWeight: 500 }}>前置条件</div>
                <div style={{
                  padding: 12, background: 'rgba(207,188,255,0.05)',
                  borderRadius: 6, fontSize: 13, lineHeight: 1.6,
                }}>
                  {selectedCase.preconditions}
                </div>
              </div>
            )}

            {/* 步骤/预期 */}
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 8, fontWeight: 500 }}>
                步骤 / 预期 ({(selectedCase.steps || []).length} 步)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {(selectedCase.steps || []).map(s => (
                  <div
                    key={s.index}
                    style={{
                      display: 'grid', gridTemplateColumns: '40px 1fr 1fr',
                      gap: 12, padding: 12,
                      background: 'rgba(15,13,19,0.3)', borderRadius: 6,
                      alignItems: 'start',
                    }}
                  >
                    <div className="mono" style={{ color: '#cfbcff', fontWeight: 600 }}>
                      {s.index}
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>操作</div>
                      <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                        {s.action || <span className="muted">—</span>}
                      </div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>预期</div>
                      <div style={{ fontSize: 13, lineHeight: 1.5, color: '#7fd9a8' }}>
                        {s.expected || <span className="muted">—</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
