import React from 'react';

function formatTimeStr(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function InferredReviewPanel({
  inferred, inferredFilter, setInferredFilter,
  inferredErr, selectedInferred,
  currentPage, pageSize, setPageSize,
  editingInferredId, editingContent, setEditingContent,
  expandedSources, totalPages,
  getCurrentPageItems, refreshInferred,
  reviewInferred, batchReviewInferred, revokeAutoAccepted,
  startEditInferred, cancelEditInferred, saveEditInferred,
  toggleSourceExpand, toggleSelectInferred, toggleSelectAll, goToPage,
}) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="mi" style={{ color: '#cfbcff' }}>auto_awesome</span>
            历史反哺候选
          </h3>
          <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>
            来自历史用例 / XMind 反推的隐性规则。高置信度（≥0.9）自动通过入库，低置信度需人工审核。
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {['pending', 'auto_accepted', 'accepted', 'rejected', 'all'].map(s => (
            <button
              key={s}
              className={inferredFilter === s ? 'primary' : 'ghost'}
              style={{ padding: '4px 10px', fontSize: 12 }}
              onClick={() => setInferredFilter(s)}
            >
              {{ pending: '待审', auto_accepted: 'AI自动通过', accepted: '已通过', rejected: '已拒绝', all: '全部' }[s]}
            </button>
          ))}
          <button className="ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={refreshInferred}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>refresh</span>
            刷新
          </button>
        </div>
      </div>
      {inferredErr && <div className="err" style={{ marginBottom: 8 }}>{inferredErr}</div>}

      {inferred.length > 0 && inferredFilter === 'pending' && (
        <div className="row" style={{ gap: 8, marginBottom: 12, alignItems: 'center' }}>
          <button className="ghost" style={{ padding: '4px 12px', fontSize: 12 }} onClick={toggleSelectAll}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>
              {selectedInferred.size === getCurrentPageItems().length && getCurrentPageItems().length > 0 ? 'check_box' : 'check_box_outline_blank'}
            </span>
            {selectedInferred.size === getCurrentPageItems().length && getCurrentPageItems().length > 0 ? '取消全选' : '全选当前页'}
          </button>
          {selectedInferred.size > 0 && (
            <>
              <span style={{ fontSize: 12, color: '#948e9c' }}>已选择 {selectedInferred.size} 项</span>
              <button className="primary" style={{ padding: '4px 12px', fontSize: 12 }} onClick={() => batchReviewInferred('accept')}>
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>check</span>
                批量通过
              </button>
              <button className="ghost" style={{ padding: '4px 12px', fontSize: 12, color: '#ffb4ab' }} onClick={() => batchReviewInferred('reject')}>
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>close</span>
                批量拒绝
              </button>
            </>
          )}
        </div>
      )}

      {inferred.length === 0 ? (
        <div className="muted" style={{ padding: 28, textAlign: 'center' }}>
          暂无{ { pending: '待审', auto_accepted: 'AI自动通过', accepted: '已通过', rejected: '已拒绝', all: '' }[inferredFilter] }候选。先到「文件夹 / 历史用例」运行五阶段分析。
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {getCurrentPageItems().map(it => (
            <div key={it.inferred_id} style={{
              border: `1px solid ${it.review_status === 'auto_accepted' ? 'rgba(127,217,168,0.35)' : '#2b292f'}`,
              borderRadius: 8, padding: 12,
              background: it.review_status === 'auto_accepted' ? 'rgba(127,217,168,0.06)' : 'rgba(15,13,19,0.3)',
            }}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  {it.review_status === 'pending' && (
                    <input type="checkbox" checked={selectedInferred.has(it.inferred_id)} onChange={() => toggleSelectInferred(it.inferred_id)} style={{ marginRight: 4 }} />
                  )}
                  <span className="tag info mono">{it.type}</span>
                  <span className="tag mono">{it.module || '(无模块)'}</span>
                  <span className="tag" style={{ color: it.confidence >= 0.9 ? '#7fd9a8' : it.confidence >= 0.6 ? '#e7c365' : '#ffb4ab', background: it.auto_accepted ? 'rgba(127,217,168,0.15)' : undefined }}>
                    conf {(it.confidence ?? 0).toFixed(2)}
                  </span>
                  {it.review_status === 'auto_accepted' && <span className="tag" style={{ background: 'rgba(127,217,168,0.18)', color: '#7fd9a8' }}><span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 2 }}>auto_awesome</span>AI自动通过</span>}
                  {it.review_status === 'accepted' && <span className="tag ok">已通过</span>}
                  {it.review_status === 'rejected' && <span className="tag err">已拒绝</span>}
                  {it.review_status === 'pending' && <span className="tag warn">待审</span>}
                  {it.aggregated_from?.length > 1 && (
                    <span className="tag" style={{ background: 'rgba(207,188,255,0.12)', color: '#cfbcff', cursor: 'pointer' }} onClick={() => toggleSourceExpand(it.inferred_id)}>
                      <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 2 }}>{expandedSources.has(it.inferred_id) ? 'unfold_less' : 'unfold_more'}</span>
                      {it.aggregated_from.length} 源聚合
                    </span>
                  )}
                </div>
                <div className="muted mono" style={{ fontSize: 11 }}>{it.inferred_id}</div>
              </div>

              {editingInferredId === it.inferred_id ? (
                <div style={{ marginBottom: 8 }}>
                  <textarea
                    style={{ width: '100%', minHeight: 80, fontSize: 13, fontFamily: 'inherit', background: '#2b292f', color: '#e6e0e9', border: '1px solid #494551', borderRadius: 6, padding: 8 }}
                    value={editingContent}
                    onChange={e => setEditingContent(e.target.value)}
                  />
                  <div className="row" style={{ gap: 6, marginTop: 6, justifyContent: 'flex-end' }}>
                    <button className="ghost" style={{ padding: '3px 10px', fontSize: 12 }} onClick={cancelEditInferred}>取消</button>
                    <button className="primary" style={{ padding: '3px 10px', fontSize: 12 }} onClick={() => saveEditInferred(it)}>保存</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: 13, color: '#e6e0e9', marginBottom: 6 }}>{it.content}</div>
              )}

              {it.aliases?.length > 0 && (
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>别名：{it.aliases.join(' / ')}</div>
              )}
              {it.reasoning && (
                <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.6, marginBottom: 6 }}>
                  <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 4 }}>psychology</span>
                  推理：{it.reasoning}
                </div>
              )}
              {it.source_summary && (
                <div style={{ fontSize: 11.5, lineHeight: 1.6, marginBottom: 6, color: '#cfbcff', background: 'rgba(207,188,255,0.06)', padding: '6px 10px', borderRadius: 6 }}>
                  <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 4 }}>summarize</span>
                  AI 总结依据：{it.source_summary}
                </div>
              )}

              {expandedSources.has(it.inferred_id) && it.aggregated_from?.length > 0 && (
                <div style={{ fontSize: 11, color: '#948e9c', marginBottom: 6, background: 'rgba(207,188,255,0.04)', padding: '6px 10px', borderRadius: 6 }}>
                  <div style={{ color: '#cfbcff', marginBottom: 4, fontWeight: 500 }}>聚合自以下 {it.aggregated_from.length} 个来源：</div>
                  {it.aggregated_from.map((src, idx) => (
                    <div key={idx} className="mono" style={{ marginBottom: 2, paddingLeft: 8 }}>
                      {src.kind === 'case' ? '📋' : '🧠'} {src.file}
                      {src.case_id && <> · {src.case_id}{src.case_row ? ` (行${src.case_row})` : ''}</>}
                      {src.node_path?.length > 0 && <> · {src.node_path.join(' › ')}</>}
                    </div>
                  ))}
                </div>
              )}

              <div className="muted mono" style={{ fontSize: 11 }}>
                源：{it.source?.kind === 'case' ? '用例' : 'XMind'} · {it.source?.file}
                {it.source?.case_id && <> · {it.source.case_id} (行 {it.source.case_row})</>}
                {it.source?.node_path?.length > 0 && <> · {it.source.node_path.join(' › ')}</>}
              </div>

              <div className="row" style={{ gap: 6, marginTop: 10, justifyContent: 'flex-end' }}>
                {it.review_status === 'pending' && (
                  <>
                    <button className="ghost" style={{ padding: '4px 12px', fontSize: 12, color: '#ffb4ab' }} onClick={() => reviewInferred(it, 'reject')}>
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>close</span>
                      拒绝
                    </button>
                    <button className="primary" style={{ padding: '4px 12px', fontSize: 12 }} onClick={() => reviewInferred(it, 'accept')}>
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>check</span>
                      通过
                    </button>
                  </>
                )}
                {it.review_status === 'auto_accepted' && (
                  <>
                    <button className="ghost" style={{ padding: '4px 12px', fontSize: 12, color: '#e7c365' }} onClick={() => revokeAutoAccepted(it)} title="撤销自动通过，恢复为待审核状态">
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>undo</span>
                      撤销
                    </button>
                    <button className="ghost" style={{ padding: '4px 12px', fontSize: 12 }} onClick={() => startEditInferred(it)}>
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>edit</span>
                      修改
                    </button>
                  </>
                )}
                {it.review_status === 'accepted' && editingInferredId !== it.inferred_id && (
                  <button className="ghost" style={{ padding: '4px 12px', fontSize: 12 }} onClick={() => startEditInferred(it)}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>edit</span>
                    二次修改
                  </button>
                )}
              </div>

              {it.reviewed_at && (
                <div className="muted mono" style={{ fontSize: 10, marginTop: 6 }}>
                  审核于 {formatTimeStr(it.reviewed_at)}{it.reviewed_by ? ` · ${it.reviewed_by}` : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {inferred.length > 0 && (
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 16, paddingTop: 12, borderTop: '1px solid #2b292f' }}>
          <div className="muted" style={{ fontSize: 12 }}>
            显示 {((currentPage - 1) * pageSize) + 1}-{Math.min(currentPage * pageSize, inferred.length)} 条，共 {inferred.length} 条
          </div>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); goToPage(1); }}
              style={{ background: '#2b292f', color: '#e6e0e9', border: '1px solid #494551', borderRadius: 4, padding: '4px 8px', fontSize: 12 }}>
              <option value={5}>5条/页</option>
              <option value={10}>10条/页</option>
              <option value={20}>20条/页</option>
              <option value={50}>50条/页</option>
            </select>
            <button className="ghost" style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1}>
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2 }}>chevron_left</span>
            </button>
            <span style={{ fontSize: 12, minWidth: 60, textAlign: 'center' }}>{currentPage} / {totalPages || 1}</span>
            <button className="ghost" style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => goToPage(currentPage + 1)} disabled={currentPage >= totalPages}>
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2 }}>chevron_right</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
