import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import {
  useLLM, useProject, useChats, newChat, useLast,
} from '../store.js';

function splitThinking(text) {
  if (!text) return { thinking: '', answer: '' };
  const re = /<think(?:ing)?>([\s\S]*?)<\/think(?:ing)?>/gi;
  let thinking = '';
  const answer = text.replace(re, (_, g1) => { thinking += (thinking ? '\n\n' : '') + g1.trim(); return ''; }).trim();
  return { thinking, answer };
}

function smartTitle(userText, aiText = '') {
  const src = (userText || '').trim();
  if (!src) return '新对话';
  // strip leading greetings / fillers
  const stripped = src
    .replace(/^(请|帮我|麻烦|你好|hi|hello)[，,、:：\s]*/i, '')
    .replace(/[?？！!。.\n\r]+$/, '')
    .trim() || src;
  // first meaningful segment
  const seg = stripped.split(/[。.!！?？\n；;]/)[0] || stripped;
  const title = seg.slice(0, 18).trim();
  return title || src.slice(0, 18);
}

function CitationBlock({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;
  return (
    <div className="citations">
      <button className="ghost" onClick={() => setOpen(v => !v)} style={{ padding: '4px 10px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 13, verticalAlign: -2, marginRight: 4 }}>
          {open ? 'expand_less' : 'expand_more'}
        </span>
        引用 {sources.length} 条
      </button>
      {open && (
        <ul>
          {sources.map((s, i) => (
            <li key={i}>
              <code className="mono">[{s.source} #{s.index}]</code>
              <span className="muted"> · score={Number(s.score).toFixed(3)}</span>
              {s.text && <div className="cite-text">{s.text}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ThinkingBlock({ text }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="thinking">
      <button className="ghost" onClick={() => setOpen(v => !v)} style={{ padding: '4px 10px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 13, verticalAlign: -2, marginRight: 4, color: '#e7c365' }}>bolt</span>
        深度思考过程
      </button>
      {open && <pre className="thinking-body">{text}</pre>}
    </div>
  );
}

function groupChats(chats) {
  const now = Date.now();
  const DAY = 24 * 3600 * 1000;
  const today = [], week = [], older = [];
  chats.forEach(c => {
    const age = now - (c.updatedAt || 0);
    if (age < DAY) today.push(c);
    else if (age < 7 * DAY) week.push(c);
    else older.push(c);
  });
  return { today, week, older };
}

export default function Chat() {
  const [project] = useProject();
  const [llm] = useLLM();
  const [chats, activeId, chatsApi] = useChats(project);
  const [, setLast] = useLast(project);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const [error, setError] = useState(null);

  // @-mention multitiling data: legacy cases + legacy xmind + requirement docs + output items
  const [legacyCases, setLegacyCases] = useState([]);
  const [legacyXMind, setLegacyXMind] = useState([]);
  const [docFiles, setDocFiles] = useState([]);
  const [outputItems, setOutputItems] = useState([]);
  const [mentionState, setMentionState] = useState(null); // { query, start } | null

  useEffect(() => {
    if (!project) {
      setLegacyCases([]);
      setLegacyXMind([]);
      setDocFiles([]);
      setOutputItems([]);
      return;
    }
    api.legacyListCases(project)
      .then(r => setLegacyCases(r.files || []))
      .catch(e => {
        console.error('Failed to load legacy cases:', e);
        setLegacyCases([]);
      });
    api.legacyListXMind(project)
      .then(r => setLegacyXMind(r.files || []))
      .catch(e => {
        console.error('Failed to load legacy xmind:', e);
        setLegacyXMind([]);
      });
    api.listFolders(project)
      .then(r => {
        const folders = r.folders || [];
        return Promise.all(
          folders.map(f => api.listFolderFiles(project, f.path).catch(() => ({ files: [] })))
        );
      })
      .then(results => {
        const allFiles = results.flatMap(r => r.files || []);
        setDocFiles(allFiles);
      })
      .catch(e => {
        console.error('Failed to load doc files:', e);
        setDocFiles([]);
      });
    api.listOutputs(project)
      .then(r => setOutputItems(r.outputs || []))
      .catch(e => {
        console.error('Failed to load outputs:', e);
        setOutputItems([]);
      });
  }, [project]);

  const mentionCandidates = useMemo(() => {
    if (!mentionState) return [];
    const q = (mentionState.query || '').toLowerCase();

    const filterAndSlice = (items, labelKey, nameKey, sizeKey) => {
      const pool = items.map(item => ({
        label: String(item[labelKey] || ''),
        name: String(item[nameKey] || ''),
        ext: item.ext || (item.kind === 'xmind' ? '.md' : '.json'),
        size: item[sizeKey],
      }));
      if (!q) return pool.slice(0, 4);
      return pool.filter(r => r.label.toLowerCase().includes(q)).slice(0, 4);
    };

    // Legacy cases / xmind use file `name` (without extension) as @label.
    const stripExt = s => String(s || '').replace(/\.[^.]+$/, '');
    const lcPool = legacyCases.map(it => ({
      label: stripExt(it.name), name: it.name, ext: it.ext || '.xlsx',
      size: it.size, file_id: it.file_id,
    }));
    const xmPool = legacyXMind.map(it => ({
      label: stripExt(it.name), name: it.name, ext: it.ext || '.xmind',
      size: it.size, file_id: it.file_id,
    }));
    const lcFiltered = (q ? lcPool.filter(r => r.label.toLowerCase().includes(q)) : lcPool).slice(0, 4)
      .map(r => ({ ...r, category: 'legacy_case', catLabel: '历史用例' }));
    const xmFiltered = (q ? xmPool.filter(r => r.label.toLowerCase().includes(q)) : xmPool).slice(0, 4)
      .map(r => ({ ...r, category: 'legacy_xmind', catLabel: '历史 XMind' }));
    const reqDocs = filterAndSlice(docFiles, 'name', 'abs_path', 'size').map(r => ({ ...r, category: 'doc', catLabel: '需求文档' }));
    const tcOutputs = filterAndSlice(
      outputItems.filter(o => o.kind === 'testcase'), 'name', 'name', 'size'
    ).map(r => ({ ...r, category: 'out_tc', catLabel: '输出-测试用例' }));
    const xmOutputs = filterAndSlice(
      outputItems.filter(o => o.kind === 'xmind'), 'name', 'name', 'size'
    ).map(r => ({ ...r, category: 'out_xm', catLabel: '输出-XMind' }));

    return [...lcFiltered, ...xmFiltered, ...reqDocs, ...tcOutputs, ...xmOutputs];
  }, [legacyCases, legacyXMind, docFiles, outputItems, mentionState]);

  function handleInputChange(e) {
    const v = e.target.value;
    setInput(v);
    const cursor = e.target.selectionStart ?? v.length;
    // find last '@' before cursor (any position, not just after whitespace)
    let at = -1;
    for (let i = cursor - 1; i >= 0; i--) {
      const ch = v[i];
      if (ch === '@') {
        at = i;
        break;
      }
      // stop if we hit whitespace (the @ is part of a previous word)
      if (/\s/.test(ch)) break;
    }
    if (at >= 0) {
      const q = v.slice(at + 1, cursor);
      // only show suggestions if the text after @ doesn't contain spaces or another @
      if (/^[^\s@]*$/.test(q)) {
        setMentionState({ query: q, start: at });
        return;
      }
    }
    setMentionState(null);
  }

  function insertMention(label) {
    if (!mentionState || !textareaRef.current) return;
    const v = input;
    const end = (textareaRef.current.selectionStart ?? v.length);
    const before = v.slice(0, mentionState.start);
    const after = v.slice(end);
    const next = `${before}@${label} ${after}`;
    setInput(next);
    setMentionState(null);
    setTimeout(() => {
      if (textareaRef.current) {
        const pos = before.length + label.length + 2;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(pos, pos);
      }
    }, 0);
  }

  function extractMentions(text) {
    if (!text) return [];
    const stripExt = s => String(s || '').replace(/\.[^.]+$/, '');
    const lcLabels = new Map(legacyCases.map(it => [
      stripExt(it.name).toLowerCase(),
      { type: 'legacy_case', file_id: it.file_id, name: it.name },
    ]));
    const xmLabels = new Map(legacyXMind.map(it => [
      stripExt(it.name).toLowerCase(),
      { type: 'legacy_xmind', file_id: it.file_id, name: it.name },
    ]));
    const docLabels = new Map(docFiles.map(f => {
      const base = f.name.replace(/\.[^.]+$/, '');
      return [base.toLowerCase(), { type: 'doc', path: f.abs_path, name: f.name }];
    }));
    const outputLabels = new Map(outputItems.map(o => {
      const base = o.name.replace(/\.[^.]+$/, '');
      return [base.toLowerCase(), { type: 'output', kind: o.kind, filename: o.name }];
    }));

    const allLabels = new Map([...lcLabels, ...xmLabels, ...docLabels, ...outputLabels]);
    const found = [];
    const seen = new Set();

    const re = /(?:^|\s)@([^\s@]+)/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const tok = m[1].toLowerCase();
      if (seen.has(tok)) continue;
      if (allLabels.has(tok)) {
        seen.add(tok);
        found.push(allLabels.get(tok));
        continue;
      }
      const cand = [...allLabels.keys()].filter(k => k.startsWith(tok));
      if (cand.length === 1) {
        seen.add(cand[0]);
        found.push(allLabels.get(cand[0]));
      }
    }
    return found;
  }

  const active = useMemo(
    () => {
      try {
        if (!activeId) return null;
        return chats.find(c => c.id === activeId) || null;
      } catch (e) {
        console.error('Error finding active chat:', e);
        setError('加载对话时出错：' + e.message);
        return null;
      }
    },
    [chats, activeId],
  );
  const mode = active?.mode || 'qa';

  useEffect(() => {
    if (project && chats.length === 0) {
      const c = newChat('qa');
      chatsApi.save([c]);
      chatsApi.setActive(c.id);
    } else if (project && !active && chats.length > 0) {
      chatsApi.setActive(chats[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, chats.length]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [active?.messages?.length, busy]);

  function createNew() {
    const c = newChat(mode);
    chatsApi.save([c, ...chats]);
    chatsApi.setActive(c.id);
  }

  function removeChat(id) {
    if (!confirm('删除此对话？')) return;
    const next = chats.filter(c => c.id !== id);
    chatsApi.save(next);
    if (id === activeId) chatsApi.setActive(next[0]?.id || '');
  }

  function renameChat(id) {
    const target = chats.find(c => c.id === id);
    if (!target) return;
    const name = prompt('重命名对话', target.title || '新对话');
    if (name == null) return;
    chatsApi.save(chats.map(c => c.id === id ? { ...c, title: name.trim() || c.title } : c));
  }

  function setMode(m) {
    if (active && active.messages.length === 0 && active.mode === m) return;
    const existing = chats
      .filter(c => c.mode === m)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    if (existing.length > 0) {
      chatsApi.setActive(existing[0].id);
    } else {
      const c = newChat(m);
      chatsApi.save([c, ...chats]);
      chatsApi.setActive(c.id);
    }
  }

  async function send() {
    if (!project) { alert('请先选择项目'); return; }
    if (!active) { createNew(); return; }
    if (!input.trim()) return;
    if (!llm.api_key) { alert('请先在「设置」填写 API Key'); return; }
    const q = input.trim();
    setInput('');

    const history = active.messages.map(m => ({ role: m.role, content: m.content }));
    const msgUser = { role: 'user', content: q };
    const isFirstMsg = active.messages.length === 0;

    // 1) persist user message immediately, then work off the snapshot
    //    (avoid reading stale `chats` via closure in the later updateActive call)
    const chatsAfterUser = chats.map(c => c.id === active.id ? ({
      ...c,
      messages: [...c.messages, msgUser],
      title: isFirstMsg ? smartTitle(q) : c.title,
      updatedAt: Date.now(),
    }) : c);
    chatsApi.save(chatsAfterUser);
    setBusy(true);

    const mentions = extractMentions(q);
    let msgAI;
    try {
      let r, displayText = '', thinking = '', sources = [];
      if (mode === 'augment') {
        r = await api.augmentMemory(project, q, llm, '');
        displayText =
          `已将补充信息融合进系统记忆。\n` +
          `• 字符数：${r.info_chars}\n` +
          `• memory.md：${r.memory_md_path}\n\n` +
          `可在「记忆面板」查看合并后的索引。`;
      } else {
        r = await api.query(project, q, mode, llm, null, history, mentions);
        sources = r.sources || [];
        if (r.mode === 'qa' || r.mode === 'chat') {
          const sp = splitThinking(r.answer || '');
          thinking = sp.thinking;
          displayText = sp.answer;
        } else if (r.mode === 'testcase') {
          displayText = `已生成 ${r.data?.cases?.length || 0} 条测试用例。\n保存：${r.output_file}\n可在「AI 用例库」查看。`;
          setLast({ kind: 'testcase', payload: r, savedAt: Date.now() });
        } else if (r.mode === 'xmind') {
          displayText = `已生成 XMind。\n保存：${r.output_file}\n可在「AI 用例库」查看。`;
          setLast({ kind: 'xmind', payload: r, savedAt: Date.now() });
        }
      }
      msgAI = { role: 'assistant', content: displayText, sources, thinking };
    } catch (e) {
      msgAI = { role: 'assistant', content: '错误：' + (e.message || e) };
    }

    // 2) append AI message onto the *post-user* snapshot, not the stale closure
    const chatsAfterAI = chatsAfterUser.map(c => c.id === active.id ? ({
      ...c,
      messages: [...c.messages, msgAI],
      title: isFirstMsg && msgAI.role === 'assistant' && !msgAI.content.startsWith('错误：')
        ? smartTitle(q, msgAI.content) : c.title,
      updatedAt: Date.now(),
    }) : c);
    chatsApi.save(chatsAfterAI);
    setBusy(false);
  }

  const { today, week, older } = groupChats(chats);

  const renderGroup = (label, items) => items.length > 0 && (
    <>
      <div className="chat-group-label">{label}</div>
      {items.map(c => (
        <div
          key={c.id}
          className={`chat-item ${c.id === activeId ? 'active' : ''}`}
          onClick={() => chatsApi.setActive(c.id)}
        >
          <div className="chat-item-title">{c.title || '新对话'}</div>
          <div className="chat-item-meta">
            {c.mode === 'qa' ? '问答'
              : c.mode === 'chat' ? '普通问答'
              : c.mode === 'testcase' ? '生成测试用例'
              : c.mode === 'xmind' ? '生成 XMind'
              : c.mode === 'augment' ? '信息补充'
              : c.mode}
            <span className="muted"> · {c.messages.length} 条</span>
          </div>
          <div className="chat-item-actions">
            <button className="icon-btn" onClick={(e) => { e.stopPropagation(); renameChat(c.id); }} title="重命名">
              <span className="mi" style={{ fontSize: 14 }}>edit</span>
            </button>
            <button className="icon-btn" onClick={(e) => { e.stopPropagation(); removeChat(c.id); }} title="删除">
              <span className="mi" style={{ fontSize: 14 }}>close</span>
            </button>
          </div>
        </div>
      ))}
    </>
  );

  return (
    <div className="chat-layout">
      {error && (
        <div className="card" style={{ borderColor: '#cf6679', background: 'rgba(207,102,121,0.1)', marginBottom: 16 }}>
          <p style={{ color: '#cf6679', margin: 0 }}>
            <span className="mi" style={{ verticalAlign: -2, marginRight: 6 }}>error</span>
            {error}
          </p>
          <button className="ghost" onClick={() => setError(null)} style={{ marginTop: 8 }}>关闭</button>
        </div>
      )}
      <aside className="chat-list">
        <div className="chat-list-title">
          <span>会话记录</span>
          <button className="icon-btn" onClick={createNew} title="新对话">
            <span className="mi">edit_square</span>
          </button>
        </div>
        {chats.length === 0 && <p className="muted">还没有对话</p>}
        {renderGroup('今天', today)}
        {renderGroup('本周', week)}
        {renderGroup('更早', older)}
      </aside>

      <div>
        <div className="page-head" style={{ marginBottom: 16 }}>
          <div>
            <div className="page-title" style={{ fontSize: 24 }}>
              AI 对话
              <span className="badge-pro" style={{ marginLeft: 8 }}>{project || '未选择项目'}</span>
            </div>
            <div className="page-sub">自动附带当前项目记忆 + 向量检索 + 本会话历史。</div>
          </div>
          <div className="mode-tabs">
            <button className={mode === 'qa' ? 'active' : ''} onClick={() => setMode('qa')}>问答</button>
            <button className={mode === 'chat' ? 'active' : ''} onClick={() => setMode('chat')}>普通问答</button>
            <button className={mode === 'testcase' ? 'active' : ''} onClick={() => setMode('testcase')}>生成测试用例</button>
            <button className={mode === 'xmind' ? 'active' : ''} onClick={() => setMode('xmind')}>生成 XMind</button>
            <button className={mode === 'augment' ? 'active' : ''} onClick={() => setMode('augment')}>信息补充</button>
          </div>
        </div>

        <div
          ref={scrollRef}
          className="card"
          style={{
            display: 'flex', flexDirection: 'column', gap: 16,
            maxHeight: 'calc(100vh - 340px)', overflow: 'auto',
            padding: 24,
          }}
        >
          {(!active || active.messages.length === 0) && (
            <p className="muted" style={{ textAlign: 'center', padding: '40px 0' }}>
              输入你的问题，例如：&quot;登录模块有哪些测试用例？&quot;
            </p>
          )}
          {active?.messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role === 'assistant' ? 'ai' : 'user'}`}>
              {m.role === 'assistant' && <ThinkingBlock text={m.thinking} />}
              <div>{m.content}</div>
              {m.role === 'assistant' && <CitationBlock sources={m.sources} />}
            </div>
          ))}
          {busy && (
            <div className="bubble ai" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className="mi" style={{ color: '#cfbcff', animation: 'pulse 1.4s infinite' }}>auto_awesome</span>
              <span className="muted">{mode === 'chat' ? '正在生成回答…' : '正在检索并生成回答…'}</span>
            </div>
          )}
        </div>

        <div className="card" style={{ marginTop: 16, position: 'relative' }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onSelect={handleInputChange}
            placeholder={
              mode === 'augment'
                ? '粘贴你希望补充进项目记忆的内容（新需求说明、业务规则、字段定义、术语澄清、决策记录…），Enter 发送。系统会把它融入 memory.md 索引。'
                : mode === 'chat'
                ? '随便聊点什么，Enter 发送，Shift+Enter 换行。此模式不检索项目文档。'
                : '描述你需要生成的内容，Enter 发送，Shift+Enter 换行。输入 @ 可引用文件。'
            }
            onKeyDown={e => {
              if (mentionState && mentionCandidates.length > 0) {
                if (e.key === 'Escape') { setMentionState(null); e.preventDefault(); return; }
                if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
                  e.preventDefault();
                  insertMention(mentionCandidates[0].label);
                  return;
                }
              }
              if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                send();
              }
            }}
          />
          {mentionState && mentionCandidates.length > 0 && (
            <div style={{
              position: 'absolute', left: 20, bottom: 'calc(100% - 8px)',
              background: 'rgba(29,27,32,0.95)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(207,188,255,0.3)',
              borderRadius: 12,
              padding: 6,
              minWidth: 300,
              maxHeight: 360,
              overflow: 'auto',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              zIndex: 20,
            }}>
              <div className="muted mono" style={{ padding: '4px 10px', fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                引用文件 · 按 Tab/Enter 选中
              </div>
              {(() => {
                const categories = ['历史用例', '历史 XMind', '需求文档', '输出-测试用例', '输出-XMind'];
                let globalIdx = 0;
                return categories.map(cat => {
                  const items = mentionCandidates.filter(mc => mc.catLabel === cat);
                  if (items.length === 0) return null;
                  return (
                    <div key={cat}>
                      <div className="muted" style={{ padding: '6px 10px 2px', fontSize: 10, letterSpacing: '0.1em' }}>
                        {cat}
                      </div>
                      {items.map(c => {
                        const idx = globalIdx++;
                        const icon = c.category === 'legacy_case' ? 'table_chart'
                          : c.category === 'legacy_xmind' ? 'account_tree'
                          : c.category === 'doc' ? 'description'
                          : c.category === 'out_tc' ? 'fact_check' : 'account_tree';
                        const iconColor = c.category === 'legacy_case' ? '#7fd9a8'
                          : c.category === 'legacy_xmind' ? '#e7c365'
                          : c.category === 'doc' ? '#85c1e9'
                          : c.category === 'out_tc' ? '#cfbcff' : '#e7c365';
                        return (
                          <div
                            key={`${c.category}:${c.name}`}
                            onClick={() => insertMention(c.label)}
                            style={{
                              padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
                              background: idx === 0 ? 'rgba(103,80,164,0.25)' : 'transparent',
                              display: 'flex', alignItems: 'center', gap: 8,
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'rgba(103,80,164,0.25)'}
                            onMouseLeave={e => e.currentTarget.style.background = idx === 0 ? 'rgba(103,80,164,0.25)' : 'transparent'}
                          >
                            <span className="mi" style={{ fontSize: 16, color: iconColor }}>{icon}</span>
                            <span style={{ fontSize: 13, color: '#e6e0e9' }}>@{c.label}</span>
                            <span className="mono muted" style={{ fontSize: 11, marginLeft: 'auto' }}>{c.ext}</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                });
              })()}
            </div>
          )}
          <div className="row" style={{ marginTop: 10, justifyContent: 'space-between' }}>
            <span className="muted">
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>model_training</span>
              {llm.model || '未配置模型'}
            </span>
            <button className="primary" onClick={send} disabled={busy}>
              <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>send</span>
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
