import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import { useProject } from '../store.js';

const BASE_TABS = [
  { id: 'projects', label: '项目管理', icon: 'dashboard' },
  { id: 'folders',  label: '目录管理', icon: 'folder_open' },
  { id: 'memory',   label: '记忆面板', icon: 'psychology' },
  { id: 'chat',     label: 'AI 对话', icon: 'forum' },
  { id: 'results',  label: 'AI 用例库', icon: 'table_chart' },
];

const CASEGEN_TAB  = { id: 'casegen',   label: '用例流水线', icon: 'account_tree' };
const CONFLICT_TAB = { id: 'conflicts', label: '冲突检测',   icon: 'report_problem' };
const SETTINGS_TAB = { id: 'settings',  label: '设置',       icon: 'settings' };

export default function Sidebar({ tab, setTab }) {
  const [project] = useProject();
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (project) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      return () => clearTimeout(t);
    }
  }, [project]);

  // 根据 features flag 动态决定可选 tab 是否展示
  const [pipelineOn, setPipelineOn] = useState(false);
  const [conflictOn, setConflictOn] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = () => api.getFeatures()
      .then(f => {
        if (cancelled) return;
        setPipelineOn(!!f.enable_case_gen_pipeline);
        setConflictOn(!!f.enable_conflict_detection);
      })
      .catch(() => { /* 后端不可用时保守不显示 */ });
    load();
    window.addEventListener('casemind:features', load);
    return () => {
      cancelled = true;
      window.removeEventListener('casemind:features', load);
    };
  }, []);

  const tabs = [
    ...BASE_TABS,
    ...(pipelineOn ? [CASEGEN_TAB]  : []),
    ...(conflictOn ? [CONFLICT_TAB] : []),
    SETTINGS_TAB,
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-icon">∞</div>
        <div>
          <div className="brand-title">CASEMIND</div>
          <div className="brand-sub">AI 记忆中枢</div>
        </div>
      </div>

      <nav>
        {tabs.map(t => (
          <button
            key={t.id}
            className={tab === t.id ? 'active' : ''}
            onClick={() => setTab(t.id)}
          >
            <span className="mi">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>

      <div className="proj-slot">
        {project && (
          <div style={{
            padding: '12px 14px', marginBottom: 10, fontSize: 11, color: '#948e9c',
            transition: 'all 0.4s cubic-bezier(0.16,1,0.3,1)',
            background: flash ? 'rgba(154,124,255,0.25)' : 'transparent',
            borderRadius: 10,
            border: flash ? '1px solid rgba(207,188,255,0.4)' : '1px solid transparent',
            boxShadow: flash ? '0 0 20px rgba(207,188,255,0.2)' : 'none',
          }}>
            <div style={{
              fontFamily: '"Space Grotesk", monospace', letterSpacing: '0.14em',
              textTransform: 'uppercase', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span className="mi" style={{
                fontSize: 12, color: flash ? '#cfbcff' : '#948e9c',
                transition: 'color 0.4s',
              }}>radio_button_checked</span>
              当前项目
            </div>
            <div style={{
              color: flash ? '#e0d2ff' : '#e6e0e9', fontSize: 14, fontWeight: 700,
              transition: 'color 0.4s',
            }}>{project}</div>
          </div>
        )}
        <div className="user-card">
          <div className="avatar">C</div>
          <div style={{ minWidth: 0 }}>
            <div className="name">CaseMind</div>
            <div className="role">LOCAL</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
