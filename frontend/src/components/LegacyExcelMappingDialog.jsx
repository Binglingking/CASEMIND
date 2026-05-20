import React, { useEffect, useMemo, useState } from 'react';

const STANDARD_COLUMNS = [
  '用例目录', '模块', '子项', '用例名称', '前置条件',
  '用例步骤', '预期结果', '用例类型', '用例等级', '创建人',
];

/**
 * LegacyExcelMappingDialog
 *
 * Props:
 *   open: bool
 *   headers: string[]              — 上传 Excel 实际表头
 *   suggested: { [header]: standard } — 自动推断；可空
 *   fingerprint: string
 *   filename: string
 *   onConfirm({ header_to_standard, fingerprint })
 *   onCancel()
 */
export default function LegacyExcelMappingDialog({
  open, headers = [], suggested = {}, fingerprint = '', filename = '',
  onConfirm, onCancel,
}) {
  const [mapping, setMapping] = useState({});

  useEffect(() => {
    if (!open) return;
    const initial = {};
    headers.forEach(h => { initial[h] = suggested[h] || ''; });
    setMapping(initial);
  }, [open, headers, suggested]);

  const stats = useMemo(() => {
    const mapped = STANDARD_COLUMNS.filter(s => Object.values(mapping).includes(s));
    return {
      mappedCount: mapped.length,
      missing: STANDARD_COLUMNS.filter(s => !mapped.includes(s)),
      hitRatio: mapped.length / STANDARD_COLUMNS.length,
    };
  }, [mapping]);

  const duplicates = useMemo(() => {
    const seen = {};
    Object.values(mapping).forEach(v => {
      if (!v) return;
      seen[v] = (seen[v] || 0) + 1;
    });
    return Object.entries(seen).filter(([, n]) => n > 1).map(([k]) => k);
  }, [mapping]);

  if (!open) return null;

  function setHeaderTarget(h, target) {
    setMapping(m => ({ ...m, [h]: target }));
  }

  function confirm() {
    if (duplicates.length > 0) return;
    const cleaned = {};
    Object.entries(mapping).forEach(([h, v]) => {
      cleaned[h] = v || '';
    });
    onConfirm({
      header_to_standard: cleaned,
      unmapped_headers: Object.keys(cleaned).filter(h => !cleaned[h]),
      confirmed: true,
      hit_ratio: stats.hitRatio,
      fingerprint,
    });
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }}>
      <div className="card" style={{ width: 720, maxHeight: '85vh', overflow: 'auto', margin: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span className="mi" style={{ color: '#cfbcff', fontSize: 22 }}>view_column</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 16 }}>确认列映射</div>
            <div className="muted" style={{ fontSize: 12 }}>
              {filename ? `${filename} · ` : ''}首次见到此列结构，请将每个表头映射到团队标准列。确认后会按指纹复用。
            </div>
          </div>
          <span className="tag info mono">{fingerprint?.slice(0, 8) || '-'}</span>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <span className={stats.hitRatio >= 0.9 ? 'tag ok' : 'tag warn'}>
            命中率 {(stats.hitRatio * 100).toFixed(0)}% · {stats.mappedCount}/{STANDARD_COLUMNS.length}
          </span>
          {stats.missing.length > 0 && (
            <span className="tag warn">未映射：{stats.missing.join('、')}</span>
          )}
          {duplicates.length > 0 && (
            <span className="tag err">重复：{duplicates.join('、')}</span>
          )}
        </div>

        <table style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ width: '50%' }}>Excel 表头</th>
              <th>映射到标准列</th>
            </tr>
          </thead>
          <tbody>
            {headers.map(h => (
              <tr key={h}>
                <td style={{ fontFamily: '"Space Grotesk", monospace', color: '#e6e0e9' }}>{h}</td>
                <td>
                  <select
                    value={mapping[h] || ''}
                    onChange={e => setHeaderTarget(h, e.target.value)}
                    style={{ width: '100%' }}
                  >
                    <option value="">— 忽略 —</option>
                    {STANDARD_COLUMNS.map(sc => (
                      <option key={sc} value={sc}>{sc}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="ghost" onClick={onCancel}>取消</button>
          <button
            className="primary"
            disabled={duplicates.length > 0 || stats.mappedCount === 0}
            onClick={confirm}
          >
            <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>check</span>
            确认并解析
          </button>
        </div>
      </div>
    </div>
  );
}
