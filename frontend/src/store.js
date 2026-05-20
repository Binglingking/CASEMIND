// Minimal state via localStorage + a subscriber hook.
import { useEffect, useState } from 'react';

const LS_PROJECT = 'casemind.project';
const LS_LLM = 'casemind.llm';
const LS_CHATS = (project) => `casemind.chats.${project}`;
const LS_ACTIVE_CHAT = (project) => `casemind.chats.${project}.active`;
const LS_LAST = (project) => `casemind.last.${project}`;

export function getProject() {
  return localStorage.getItem(LS_PROJECT) || '';
}
export function setProject(name) {
  localStorage.setItem(LS_PROJECT, name || '');
  window.dispatchEvent(new Event('casemind:project'));
}
export function useProject() {
  const [p, setP] = useState(getProject());
  useEffect(() => {
    const h = () => setP(getProject());
    window.addEventListener('casemind:project', h);
    return () => window.removeEventListener('casemind:project', h);
  }, []);
  return [p, setProject];
}

// 仅保留 OpenRouter。历史数据如果存的是旧 provider（mimo / custom）或扁平格式，
// 读取时会被规范化回 openrouter profile。
const DEFAULT_PROFILES = {
  openrouter: { base_url: 'https://openrouter.ai/api/v1', api_key: '', model: 'openai/gpt-5.5-20260423' },
};

function cloneDefaults() {
  return Object.fromEntries(Object.entries(DEFAULT_PROFILES).map(([k, v]) => [k, { ...v }]));
}

export function getLLMStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_LLM) || 'null');
    if (!raw) return { active: 'openrouter', profiles: cloneDefaults() };
    const profiles = cloneDefaults();
    if (raw.profiles && raw.active) {
      // 新格式：仅合并 openrouter 配置，忽略已移除的 provider
      if (raw.profiles.openrouter) {
        profiles.openrouter = { ...profiles.openrouter, ...raw.profiles.openrouter };
      }
    } else if (raw.base_url || raw.api_key || raw.model) {
      // 旧扁平格式 → 统一迁移到 openrouter profile
      profiles.openrouter = { ...profiles.openrouter, ...raw };
    }
    return { active: 'openrouter', profiles };
  } catch {
    return { active: 'openrouter', profiles: cloneDefaults() };
  }
}

function saveLLMStore(store) {
  localStorage.setItem(LS_LLM, JSON.stringify(store));
  window.dispatchEvent(new Event('casemind:llm'));
}

export function setActiveLLMProvider(provider) {
  const s = getLLMStore();
  if (!DEFAULT_PROFILES[provider]) return; // 未知 provider 直接忽略
  if (!s.profiles[provider]) {
    s.profiles[provider] = { ...DEFAULT_PROFILES[provider] };
  }
  s.active = provider;
  saveLLMStore(s);
}

export function setLLMProfile(provider, cfg) {
  const s = getLLMStore();
  s.profiles[provider] = {
    ...(s.profiles[provider] || DEFAULT_PROFILES[provider] || DEFAULT_PROFILES.openrouter),
    ...cfg,
  };
  saveLLMStore(s);
}

export function useLLMStore() {
  const [s, setS] = useState(() => getLLMStore());
  useEffect(() => {
    const h = () => setS(getLLMStore());
    window.addEventListener('casemind:llm', h);
    return () => window.removeEventListener('casemind:llm', h);
  }, []);
  return [s, { setActive: setActiveLLMProvider, setProfile: setLLMProfile }];
}

// 向后兼容：返回"当前激活 provider 的扁平配置"。Chat / Memory 等组件继续用它。
export function getLLM() {
  const s = getLLMStore();
  return { ...(s.profiles[s.active] || DEFAULT_PROFILES.openrouter) };
}
export function setLLM(cfg) {
  const s = getLLMStore();
  s.profiles[s.active] = { ...(s.profiles[s.active] || {}), ...cfg };
  saveLLMStore(s);
}
export function useLLM() {
  const [v, setV] = useState(getLLM());
  useEffect(() => {
    const h = () => setV(getLLM());
    window.addEventListener('casemind:llm', h);
    return () => window.removeEventListener('casemind:llm', h);
  }, []);
  return [v, setLLM];
}

// --------- chats (per project) ---------

function readJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; }
  catch { return fallback; }
}

export function getChats(project) {
  if (!project) return [];
  return readJSON(LS_CHATS(project), []);
}
export function setChats(project, chats) {
  if (!project) return;
  localStorage.setItem(LS_CHATS(project), JSON.stringify(chats));
  window.dispatchEvent(new Event('casemind:chats'));
}
export function getActiveChatId(project) {
  if (!project) return '';
  return localStorage.getItem(LS_ACTIVE_CHAT(project)) || '';
}
export function setActiveChatId(project, id) {
  if (!project) return;
  localStorage.setItem(LS_ACTIVE_CHAT(project), id || '');
  window.dispatchEvent(new Event('casemind:chats'));
}
export function useChats(project) {
  const [chats, setC] = useState(() => getChats(project));
  const [activeId, setA] = useState(() => getActiveChatId(project));
  useEffect(() => {
    const h = () => { setC(getChats(project)); setA(getActiveChatId(project)); };
    h();
    window.addEventListener('casemind:chats', h);
    window.addEventListener('casemind:project', h);
    return () => {
      window.removeEventListener('casemind:chats', h);
      window.removeEventListener('casemind:project', h);
    };
  }, [project]);
  return [chats, activeId, {
    save: (c) => setChats(project, c),
    setActive: (id) => setActiveChatId(project, id),
  }];
}

export function newChat(mode = 'qa') {
  return {
    id: `c_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    title: '新对话',
    mode,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [], // {role: 'user'|'assistant', content, sources?, thinking?}
  };
}

// --------- last results (per project) ---------

export function getLast(project) {
  if (!project) return null;
  return readJSON(LS_LAST(project), null);
}
export function setLast(project, payload) {
  if (!project) return;
  if (payload === null) localStorage.removeItem(LS_LAST(project));
  else localStorage.setItem(LS_LAST(project), JSON.stringify(payload));
  window.dispatchEvent(new Event('casemind:last'));
}
export function useLast(project) {
  const [v, setV] = useState(() => getLast(project));
  useEffect(() => {
    const h = () => setV(getLast(project));
    h();
    window.addEventListener('casemind:last', h);
    window.addEventListener('casemind:project', h);
    return () => {
      window.removeEventListener('casemind:last', h);
      window.removeEventListener('casemind:project', h);
    };
  }, [project]);
  return [v, (p) => setLast(project, p)];
}
