import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { useProject } from '../store.js';

function Toast({ msg, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, 2200);
    return () => clearTimeout(t);
  }, []);
  return (
    <div style={{
      position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
      background: 'linear-gradient(135deg, rgba(103,80,164,0.95), rgba(154,124,255,0.95))',
      color: '#fff', padding: '14px 28px', borderRadius: 12, zIndex: 100,
      fontSize: 15, fontWeight: 700,
      boxShadow: '0 8px 32px rgba(103,80,164,0.5)',
      animation: 'switchToastIn 0.35s cubic-bezier(0.16,1,0.3,1)',
      border: '1px solid rgba(207,188,255,0.5)',
      display: 'flex', alignItems: 'center', gap: 8,
    }}>
      <span className="mi" style={{ fontSize: 18 }}>check_circle</span>
      {msg}
    </div>
  );
}

export default function Projects() {
  const [list, setList] = useState([]);
  const [stats, setStats] = useState({});
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [filter, setFilter] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [toast, setToast] = useState('');
  const [current, setCurrent] = useProject();
  const [busyDelete, setBusyDelete] = useState(null);

  async function refresh() {
    setErr('');
    try {
      const r = await api.listProjects();
      const projects = r.projects || [];
      setList(projects);
      const entries = await Promise.all(projects.map(async p => {
        try { return [p.name, await api.stats(p.name)]; }
        catch { return [p.name, null]; }
      }));
      setStats(Object.fromEntries(entries));
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { refresh(); }, []);

  async function createProject() {
    setMsg(''); setErr('');
    if (!name.trim()) { setErr('请输入项目名称'); return; }
    try {
      await api.createProject(name.trim());
      setMsg(`项目 ${name} 已创建`);
      setName('');
      setShowModal(false);
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
  }

  function handleSwitch(pName) {
    if (pName === current) return;
    setCurrent(pName);
    setToast(`已切换到：${pName}`);
  }

  async function handleDelete(e, pName) {
    e.stopPropagation();
    if (!confirm(`确定删除项目「${pName}」？\n\n将同时删除：\n- 记忆数据（memory.md + 文档摘要）\n- 向量索引\n- 输出文件（测试用例 / XMind）\n- 对话记录\n\n此操作不可撤销。`)) return;
    setBusyDelete(pName);
    try {
      await api.deleteProject(pName);
      if (current === pName) setCurrent('');
      setToast(`已删除：${pName}`);
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    setBusyDelete(null);
  }

  const userCreated = useMemo(() => list.filter(p => p.created_at), [list]);
  const autoDiscovered = useMemo(() => list.filter(p => !p.created_at), [list]);

  const filteredUser = useMemo(
    () => userCreated.filter(p => !filter || p.name.toLowerCase().includes(filter.toLowerCase())),
    [userCreated, filter],
  );
  const filteredAuto = useMemo(
    () => autoDiscovered.filter(p => !filter || p.name.toLowerCase().includes(filter.toLowerCase())),
    [autoDiscovered, filter],
  );

  function renderCard(p, isUserCreated) {
    const st = stats[p.name] || {};
    const vec = st?.vector?.num_vectors ?? st?.vector?.num_chunks ?? 0;
    const folders = st?.folders?.length ?? 0;
    const isActive = current === p.name;

    return (
      <div
        key={p.name}
        className={`proj-card ${isActive ? 'active' : ''}`}
        onClick={() => handleSwitch(p.name)}
        style={isActive ? {
          borderColor: 'rgba(207,188,255,0.6)',
          boxShadow: '0 0 24px rgba(103,80,164,0.25)',
        } : {}}
      >
        {isUserCreated && (
          <button
            className="icon-btn"
            onClick={(e) => handleDelete(e, p.name)}
            disabled={busyDelete === p.name}
            title="删除项目"
            style={{
              position: 'absolute', top: 10, right: 10,
              color: busyDelete === p.name ? '#948e9c' : '#ffb4ab',
              zIndex: 2,
            }}
          >
            <span className="mi" style={{ fontSize: 16 }}>
              {busyDelete === p.name ? 'hourglass_empty' : 'delete_outline'}
            </span>
          </button>
        )}
        <div className="proj-icon">
          <span className="mi" style={{ color: isUserCreated ? '#cfbcff' : '#948e9c' }}>
            {isUserCreated ? 'folder_special' : 'folder_open'}
          </span>
        </div>
        {isActive && <span className="tag ok" style={{ position: 'absolute', top: 14, right: isUserCreated ? 42 : 14, zIndex: 1 }}>当前</span>}
        {!isUserCreated && !isActive && (
          <span className="tag" style={{
            position: 'absolute', top: 14, right: 14, zIndex: 1,
            background: 'rgba(148,142,156,0.12)', color: '#948e9c',
          }}>自动发现</span>
        )}
        <div className="proj-name">{p.name}</div>
        <div className="proj-sub">
          {isUserCreated
            ? (folders > 0 ? `${folders} 个已登记目录` : '暂未添加目录')
            : '代码自动扫描发现'}
        </div>
        <div className="proj-stats">
          <span><span className="mi">description</span>{folders}</span>
          <span><span className="mi">memory</span>{vec.toLocaleString()}</span>
        </div>
        <div className="proj-footer">
          <span>{p.created_at ? `创建于 ${p.created_at.slice(0, 10)}` : ''}</span>
          {isActive ? (
            <span className="active-badge" style={{
              background: 'linear-gradient(135deg, rgba(103,80,164,0.6), rgba(207,188,255,0.3))',
              color: '#e0d2ff', padding: '4px 12px', borderRadius: 8,
              fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4,
              border: '1px solid rgba(207,188,255,0.4)',
            }}>
              <span className="mi" style={{ fontSize: 14 }}>check_circle</span>
              使用中
            </span>
          ) : (
            <button
              className="enter-btn-real"
              onClick={(e) => {
                e.stopPropagation();
                handleSwitch(p.name);
              }}
            >
              进入 <span className="mi" style={{ fontSize: 14 }}>chevron_right</span>
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      {toast && <Toast msg={toast} onDone={() => setToast('')} />}

      <div className="page-head">
        <div>
          <div className="page-title">
            项目管理 <span className="badge-pro">PRO</span>
          </div>
          <div className="page-sub">管理项目，区分手动创建与自动发现的数据源。</div>
        </div>
        <button className="primary" onClick={() => setShowModal(true)}>
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>add</span>
          新建项目
        </button>
      </div>

      {current && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(103,80,164,0.2), rgba(207,188,255,0.08))',
          border: '1px solid rgba(207,188,255,0.25)',
          borderRadius: 12, padding: '14px 20px',
          marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span className="mi" style={{ fontSize: 22, color: '#cfbcff' }}>play_circle</span>
          <div>
            <div style={{ fontSize: 12, color: '#b5afbd', fontFamily: '"Space Grotesk", monospace', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              当前活跃项目
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#e0d2ff' }}>{current}</div>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
        <span className="mi" style={{ color: '#948e9c', marginLeft: 6 }}>search</span>
        <input
          type="text"
          placeholder="搜索项目..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{ flex: 1, border: 'none', background: 'transparent', boxShadow: 'none', padding: '6px 4px' }}
        />
        <button className="ghost" onClick={refresh}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>refresh</span>
          刷新
        </button>
      </div>

      {err && <div className="card" style={{ borderColor: 'rgba(255,180,171,0.3)' }}><span className="err">{err}</span></div>}
      {msg && <p className="ok" style={{ marginLeft: 4 }}>{msg}</p>}

      {/* 我的项目 */}
      <div style={{ marginBottom: 32 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          margin: '20px 0 12px 4px',
        }}>
          <span className="mi" style={{ color: '#cfbcff' }}>folder_special</span>
          <span style={{ fontWeight: 600, color: '#e6e0e9' }}>我的项目</span>
          <span className="tag info">{filteredUser.length}</span>
        </div>
        {filteredUser.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 32, color: '#948e9c' }}>
            {filter ? '无匹配项目' : '暂无项目，点击右上角按钮创建第一个项目。'}
          </div>
        ) : (
          <div className="grid-projects">
            {filteredUser.map(p => renderCard(p, true))}
            <div className="proj-card create" onClick={() => setShowModal(true)}>
              <span className="mi">add_circle</span>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>创建新项目</div>
              <div className="muted">导入文档后即开始</div>
            </div>
          </div>
        )}
      </div>

      {/* 自动发现 */}
      {filteredAuto.length > 0 && (
        <div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            margin: '0 0 12px 4px',
          }}>
            <span className="mi" style={{ color: '#948e9c' }}>folder_open</span>
            <span style={{ fontWeight: 600, color: '#948e9c' }}>自动发现</span>
            <span className="tag" style={{ background: 'rgba(148,142,156,0.12)', color: '#948e9c' }}>{filteredAuto.length}</span>
            <span className="muted" style={{ fontSize: 12 }}>— 代码自动扫描 docs 目录，不可删除</span>
          </div>
          <div className="grid-projects" style={{ opacity: 0.7 }}>
            {filteredAuto.map(p => renderCard(p, false))}
          </div>
        </div>
      )}

      {showModal && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(15,13,19,0.7)',
            backdropFilter: 'blur(8px)', display: 'grid', placeItems: 'center', zIndex: 50,
          }}
          onClick={() => setShowModal(false)}
        >
          <div
            className="card"
            style={{ width: 440, margin: 0 }}
            onClick={e => e.stopPropagation()}
          >
            <h2>创建项目</h2>
            <div className="row">
              <input
                type="text" style={{ flex: 1, minWidth: 'auto' }}
                placeholder="项目名称（字母/数字/_/-/中文）"
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') createProject(); }}
                autoFocus
              />
            </div>
            {err && <p className="err" style={{ marginTop: 8 }}>{err}</p>}
            <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
              <button className="ghost" onClick={() => setShowModal(false)}>取消</button>
              <button className="primary" onClick={createProject}>创建</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
