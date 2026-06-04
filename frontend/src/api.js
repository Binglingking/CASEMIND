const API_BASE = '/api';

import { getProjectKey } from './store.js';

// API Key 简单编码（Base64），防止明文抓包
const encodeApiKey = (key) => {
  if (!key) return key;
  try {
    return btoa(unescape(encodeURIComponent(key)));
  } catch (e) {
    return key;
  }
};

// 递归处理请求体中的 api_key 字段
const protectApiKey = (obj) => {
  if (!obj || typeof obj !== 'object') return obj;
  const copy = Array.isArray(obj) ? [] : {};
  for (const [k, v] of Object.entries(obj)) {
    if (k === 'api_key' && typeof v === 'string' && v.trim()) {
      copy[k] = encodeApiKey(v);
    } else if (typeof v === 'object' && v !== null) {
      copy[k] = protectApiKey(v);
    } else {
      copy[k] = v;
    }
  }
  return copy;
};

async function req(path, opts = {}, project = null) {
  // 自动附加项目密钥到请求头
  if (project) {
    const key = getProjectKey(project);
    if (key) {
      opts.headers = opts.headers || {};
      opts.headers['X-CaseMind-Project'] = encodeURIComponent(project);
      opts.headers['X-CaseMind-Key'] = encodeURIComponent(key);
    }
  }

  // 对 POST/PUT 请求体中的 api_key 进行编码
  if ((opts.method === 'POST' || opts.method === 'PUT') && opts.body && opts.headers?.['Content-Type'] === 'application/json') {
    try {
      const parsed = JSON.parse(opts.body);
      opts.body = JSON.stringify(protectApiKey(parsed));
    } catch (e) {
      // ignore
    }
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = data?.detail || data?.raw || res.statusText;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

async function blobReq(path, opts = {}, project = null) {
  if (project) {
    const key = getProjectKey(project);
    if (key) {
      opts.headers = opts.headers || {};
      opts.headers['X-CaseMind-Project'] = encodeURIComponent(project);
      opts.headers['X-CaseMind-Key'] = encodeURIComponent(key);
    }
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) {
    const text = await res.text();
    let msg = res.statusText || 'Download failed';
    try {
      const d = JSON.parse(text);
      msg = d.detail || d.message || msg;
    } catch {
      msg = text || msg;
    }
    throw new Error(msg);
  }
  return res.blob();
}

function saveBlob(blob, filename) {
  if (!blob || blob.size === 0) throw new Error('下载的文件为空');
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const q = (obj) => new URLSearchParams(obj).toString();

export const api = {
  // projects
  listProjects: () => req('/projects'),
  createProject: (name, owner = null, password = null) => req('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, owner, password }),
  }),
  stats: (name) => req(`/projects/${encodeURIComponent(name)}/stats`),
  deleteProject: (name) => req('/projects', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }),
  unlockProject: (name, password) => req(`/projects/${encodeURIComponent(name)}/unlock`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  }),
  setProjectPassword: (name, owner, password) => req(`/projects/${encodeURIComponent(name)}/set-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, password }),
  }),
  changeProjectPassword: (name, old_password, new_password) => req(`/projects/${encodeURIComponent(name)}/change-password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_password, new_password }),
  }),

  // folders
  listFolders: (project) => req(`/folders?${q({ project })}`, {}, project),
  listFolderFiles: (project, path) => req(`/folders/files?${q({ project, path })}`, {}, project),
  addFolder: (project, path) => req('/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }, project),
  removeFolder: (project, path) => req('/folders', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }, project),
  openFile: (project, path) => req('/folders/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }, project),
  uploadFiles: (project, files) => {
    const fd = new FormData();
    fd.append('project', project);
    for (const f of files) fd.append('files', f);
    return req('/folders/upload', { method: 'POST', body: fd }, project);
  },

  // scan / build
  scan: (project) => req('/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project }),
  }, project),
  buildMemory: (project, llm, { force_files = null, rebuild_all = false, incremental = true } = {}) =>
    req('/memory/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, llm, force_files, rebuild_all, incremental }),
    }, project),

  // memory
  getMemory: (project) => req(`/memory?${q({ project })}`, {}, project),
  saveMemory: (project, memory_md, regenerate_prompt = true) => req('/memory', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, memory_md, regenerate_prompt }),
  }, project),
  savePrompt: (project, prompt_text) => req('/memory/prompt', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, prompt_text }),
  }, project),

  // query
  query: (project, question, mode, llm, top_k = null, history = null, mentions = null, images = null) => req('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, question, mode, top_k, llm, history, mentions, images }),
  }, project),

  // query stream (SSE)
  queryStream: (project, question, mode, llm, top_k, history, mentions, images, callbacks) => {
    // callbacks: { onThinking, onAnswer, onDone, onError }
    const controller = new AbortController();

    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/query/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project, question, mode, top_k, llm, history, mentions, images }),
          signal: controller.signal,
        });

        if (!resp.ok) {
          const text = await resp.text();
          callbacks.onError?.(new Error(text));
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // 按事件边界（双换行）分割
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';

          for (const eventBlock of events) {
            if (!eventBlock.trim()) continue;
            const lines = eventBlock.split('\n');
            let eventType = '';
            let dataLines = [];

            for (const line of lines) {
              if (line.startsWith('event: ')) {
                eventType = line.slice(7).trim();
              } else if (line.startsWith('data: ')) {
                dataLines.push(line.slice(6));
              }
            }

            const data = dataLines.join('\n');
            if (!eventType) continue;

            if (eventType === 'thinking') {
              callbacks.onThinking?.(data);
            } else if (eventType === 'answer') {
              callbacks.onAnswer?.(data);
            } else if (eventType === 'done') {
              try {
                callbacks.onDone?.(JSON.parse(data));
              } catch {
                callbacks.onDone?.({});
              }
              return;
            } else if (eventType === 'error') {
              callbacks.onError?.(new Error(data));
              return;
            }
          }
        }
      } catch (e) {
        if (e.name !== 'AbortError') {
          callbacks.onError?.(e);
        }
      }
    })();

    return controller;
  },

  // image upload
  uploadImages: (project, files) => {
    const fd = new FormData();
    fd.append('project', project);
    for (const f of files) fd.append('images', f);
    return req('/upload', { method: 'POST', body: fd }, project);
  },

  // requirement analysis report PDF
  generateReqAnalysisReport: (project, analysisData) => req('/query/req-analysis/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, analysis_json: JSON.stringify(analysisData) }),
  }, project),

  // augment memory with user-supplied info
  augmentMemory: (project, info, llm, note = '') => req('/memory/augment', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, info, note, llm }),
  }, project),

  // memory versions
  listVersions: (project) => req(`/memory/versions?${q({ project })}`, {}, project),
  getVersion: (project, versionId) =>
    req(`/memory/versions/${encodeURIComponent(versionId)}?${q({ project })}`, {}, project),
  restoreVersion: (project, versionId) =>
    req(`/memory/versions/${encodeURIComponent(versionId)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project }),
    }, project),

  // build history
  listBuilds: (project) => req(`/memory/builds?${q({ project })}`, {}, project),
  getBuild: (project, buildId) =>
    req(`/memory/builds/${encodeURIComponent(buildId)}?${q({ project })}`, {}, project),
  restoreFromBuild: (project, buildId) =>
    req(`/memory/builds/${encodeURIComponent(buildId)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project }),
    }, project),

  // ---- legacy assets (历史用例 / 历史 XMind / 反哺候选) ----
  legacyListCases: (project) => req(`/legacy/cases?${q({ project })}`, {}, project),
  legacyPeekHeaders: (project, file) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    return req('/legacy/cases/peek-headers', { method: 'POST', body: fd }, project);
  },
  legacyUploadCase: (project, file, confirmed_mapping = null) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    if (confirmed_mapping) fd.append('confirmed_mapping', JSON.stringify(confirmed_mapping));
    return req('/legacy/cases/upload', { method: 'POST', body: fd }, project);
  },
  legacyGetCaseFile: (project, fileId) =>
    req(`/legacy/cases/${encodeURIComponent(fileId)}?${q({ project })}`, {}, project),
  legacyDeleteCase: (project, fileId) =>
    req(`/legacy/cases/${encodeURIComponent(fileId)}?${q({ project })}`, { method: 'DELETE' }, project),

  legacyListXMind: (project) => req(`/legacy/xmind?${q({ project })}`, {}, project),
  legacyUploadXMind: (project, file) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    return req('/legacy/xmind/upload', { method: 'POST', body: fd }, project);
  },
  legacyGetXMind: (project, fileId) =>
    req(`/legacy/xmind/${encodeURIComponent(fileId)}?${q({ project })}`, {}, project),
  legacyDeleteXMind: (project, fileId) =>
    req(`/legacy/xmind/${encodeURIComponent(fileId)}?${q({ project })}`, { method: 'DELETE' }, project),

  legacyGetColumnMapping: (project) => req(`/legacy/column-mapping?${q({ project })}`, {}, project),
  legacyConfirmColumnMapping: (project, fingerprint, mapping) =>
    req('/legacy/column-mapping/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, fingerprint, mapping }),
    }, project),

  legacyGetStyle: (project) => req(`/legacy/style?${q({ project })}`, {}, project),

  legacyListInferred: (project, status = null) => {
    const params = { project };
    if (status) params.status = status;
    return req(`/legacy/inferred?${q(params)}`, {}, project);
  },
  legacyReviewInferred: (project, inferred_id, decision, reviewer = '') =>
    req('/legacy/inferred/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, inferred_id, decision, reviewer }),
    }, project),
  legacyBatchReviewInferred: (project, inferred_ids, decision, reviewer = '') =>
    req('/legacy/inferred/batch-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, inferred_ids, decision, reviewer }),
    }, project),
  legacyRevokeInferred: (project, inferred_id) =>
    req('/legacy/inferred/revoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, inferred_id, decision: 'revoke' }),
    }, project),
  legacyEditInferred: (project, inferred_id, content, editor = '') => {
    const form = new FormData();
    form.append('project', project);
    form.append('inferred_id', inferred_id);
    form.append('content', content);
    form.append('editor', editor);
    return req('/legacy/inferred/edit', { method: 'POST', body: form }, project);
  },

  legacyAnalyze: (project, llm, { skip_extract = false } = {}) =>
    req('/legacy/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, llm, skip_extract }),
    }, project),

  // 分析进度控制
  legacyAnalysisProgress: (project) =>
    req(`/legacy/analyze/progress?${q({ project })}`, {}, project),
  legacyAnalysisPause: (project) =>
    req(`/legacy/analyze/pause?${q({ project })}`, { method: 'POST' }, project),
  legacyAnalysisResume: (project) =>
    req(`/legacy/analyze/resume?${q({ project })}`, { method: 'POST' }, project),
  legacyAnalysisCancel: (project) =>
    req(`/legacy/analyze/cancel?${q({ project })}`, { method: 'POST' }, project),

  // memory build progress control
  getMemoryBuildProgress: (project) =>
    req(`/memory/build/progress?${q({ project })}`, {}, project),
  pauseMemoryBuild: (project) =>
    req(`/memory/build/pause?${q({ project })}`, { method: 'POST' }, project),
  resumeMemoryBuild: (project) =>
    req(`/memory/build/resume?${q({ project })}`, { method: 'POST' }, project),
  cancelMemoryBuild: (project) =>
    req(`/memory/build/cancel?${q({ project })}`, { method: 'POST' }, project),

  // ---- chats persistence ----
  loadChats: (project) => req(`/chats/${encodeURIComponent(project)}`, {}, project),
  saveChats: (project, chats, active_id = '') => req(`/chats/${encodeURIComponent(project)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, chats, active_id }),
  }, project),

  // diagnostics
  checkEnv: (api_key) => req('/debug/env-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key }),
  }),

  // ---- feature flags -----------------------------------------------------
  getFeatures: () => req('/settings/features'),
  updateFeatures: (partial) => req('/settings/features', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  }),

  // ---- 飞书集成（项目级） -------------------------------------------------
  feishuGetConfig: (project) =>
    req(`/feishu/config?${q({ project })}`, {}, project),
  feishuSaveConfig: (project, partial) =>
    req(`/feishu/config?${q({ project })}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial),
    }, project),
  feishuTest: (project) =>
    req(`/feishu/test?${q({ project })}`, { method: 'POST' }, project),
  feishuImportLegacy: (project, url, confirmed_mapping = null) =>
    req('/feishu/legacy/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, url, confirmed_mapping }),
    }, project),
  feishuExportCases: (project, cases, title = null) =>
    req('/feishu/docs/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, cases, title }),
    }, project),

  // ---- case-gen pipeline -------------------------------------------------
  cgStart: (project, question, llm, { mentions = null, filters = null } = {}) =>
    req('/case-gen/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, question, llm, mentions, filters }),
    }, project),
  cgList: (project) => req(`/case-gen/list?${q({ project })}`, {}, project),
  cgGet: (project, pipelineId) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}`, {}, project),
  cgRunStep: (project, pipelineId, n, llm) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/step/${n}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm }),
    }, project),
  cgUserEdit: (project, pipelineId, n, payload) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/step/${n}/output`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload }),
    }, project),
  cgRollback: (project, pipelineId, step_n) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_n }),
    }, project),

  // ---- conflict detection ------------------------------------------------
  cfDetect: (project, llm, { sim_low = 0.75, sim_high = 0.99, modules = null } = {}) =>
    req(`/conflict/${encodeURIComponent(project)}/detect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm, sim_low, sim_high, modules }),
    }, project),
  cfList: (project) => req(`/conflict/${encodeURIComponent(project)}`, {}, project),
  cfResolve: (project, conflictId, resolution, note = '') =>
    req(`/conflict/${encodeURIComponent(project)}/${encodeURIComponent(conflictId)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution, note }),
    }, project),
  cfDelete: (project, conflictId) =>
    req(`/conflict/${encodeURIComponent(project)}/${encodeURIComponent(conflictId)}`, { method: 'DELETE' }, project),
  cfClear: (project) =>
    req(`/conflict/${encodeURIComponent(project)}`, { method: 'DELETE' }, project),

  // ---- feedback loop -----------------------------------------------------
  fbSubmit: (project, body) =>
    req(`/feedback/${encodeURIComponent(project)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, project),
  fbList: (project, { kind = null, target_id = null } = {}) => {
    const params = {};
    if (kind) params.kind = kind;
    if (target_id) params.target_id = target_id;
    const qs = Object.keys(params).length ? `?${q(params)}` : '';
    return req(`/feedback/${encodeURIComponent(project)}${qs}`, {}, project);
  },
  fbSummary: (project) =>
    req(`/feedback/${encodeURIComponent(project)}/summary`, {}, project),
  fbExamples: (project, { module = null, limit = 3 } = {}) => {
    const params = { limit };
    if (module) params.module = module;
    return req(`/feedback/${encodeURIComponent(project)}/examples?${q(params)}`, {}, project);
  },
  fbDelete: (project, feedbackId) =>
    req(`/feedback/${encodeURIComponent(project)}/${encodeURIComponent(feedbackId)}`, { method: 'DELETE' }, project),
  fbClear: (project) =>
    req(`/feedback/${encodeURIComponent(project)}`, { method: 'DELETE' }, project),

  // ---- coverage ----------------------------------------------------------
  covCompute: (project, pipelineId, { sim_threshold = 0.75, enable_semantic = true } = {}) =>
    req(`/coverage/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/compute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sim_threshold, enable_semantic }),
    }, project),
  covGet: (project, pipelineId) =>
    req(`/coverage/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}`, {}, project),
  covSummary: (project) => req(`/coverage/${encodeURIComponent(project)}/summary`, {}, project),

  // outputs
  listOutputs: (project, kind = null) => {
    const params = { project };
    if (kind) params.kind = kind;
    return req(`/outputs?${q(params)}`, {}, project);
  },
  getOutputContent: (project, kind, filename) =>
    req(`/outputs/content?${q({ project, kind, filename })}`, {}, project),
  downloadOutput: async (project, kind, filename, downloadName = null) => {
    const blob = await blobReq(`/outputs/download?${q({ project, kind, filename })}`, {}, project);
    saveBlob(blob, downloadName || filename);
  },
  exportOutputExcel: async (project, kind, filename) => {
    const blob = await blobReq('/outputs/export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, kind, filename }),
    }, project);
    saveBlob(blob, filename.replace(/\.[^.]+$/, '.xlsx'));
  },
  renameOutput: (project, kind, old_name, new_name) => req('/outputs/rename', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, kind, old_name, new_name }),
  }, project),
  deleteOutput: (project, kind, filename) => req('/outputs', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, kind, filename }),
  }, project),

  // ---- batch generation (split → confirm → run → download) ----------------
  batchSplit: (project, question, kind, llm, { mentions = null, images = null, target_cases_per_unit = 50 } = {}) =>
    req('/batch/split', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, question, kind, llm, mentions, images, target_cases_per_unit }),
    }, project),
  batchStart: (project, question, kind, units, llm, { mentions = null, images = null, max_parallel = 1 } = {}) =>
    req('/batch/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, question, kind, units, llm, mentions, images, max_parallel }),
    }, project),
  batchList: (project, kind = null) => {
    const params = { project };
    if (kind) params.kind = kind;
    return req(`/batch/list?${q(params)}`, {}, project);
  },
  batchGet: (project, batchId) =>
    req(`/batch/${encodeURIComponent(batchId)}?${q({ project })}`, {}, project),
  batchDelete: (project, batchId) =>
    req(`/batch/${encodeURIComponent(batchId)}?${q({ project })}`, { method: 'DELETE' }, project),
  batchGetUnit: (project, batchId, unitId) =>
    req(`/batch/${encodeURIComponent(batchId)}/unit/${encodeURIComponent(unitId)}?${q({ project })}`, {}, project),
  batchDownload: async (project, batchId, fmt = 'merged', filename = null) => {
    const blob = await blobReq(
      `/batch/${encodeURIComponent(batchId)}/download?${q({ project, fmt })}`,
      {}, project,
    );
    const name = filename || `${batchId}.${fmt === 'zip' ? 'zip' : 'bin'}`;
    saveBlob(blob, name);
  },

  // batch run (SSE)
  batchRunStream: (project, batchId, llm, { target_cases_per_unit = 50, only_pending = true } = {}, callbacks) => {
    // callbacks: { onEvent(evt), onDone(evt), onError(err) }
    const controller = new AbortController();

    // protect api_key in nested llm before sending
    const body = JSON.stringify(protectApiKey({
      project, batch_id: batchId, llm, target_cases_per_unit, only_pending,
    }));

    const headers = { 'Content-Type': 'application/json' };
    const key = getProjectKey(project);
    if (key) {
      headers['X-CaseMind-Project'] = encodeURIComponent(project);
      headers['X-CaseMind-Key'] = encodeURIComponent(key);
    }

    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/batch/run`, {
          method: 'POST', headers, body, signal: controller.signal,
        });
        if (!resp.ok) {
          const text = await resp.text();
          callbacks.onError?.(new Error(text || resp.statusText));
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';
          for (const eventBlock of events) {
            if (!eventBlock.trim()) continue;
            const lines = eventBlock.split('\n');
            let eventType = '';
            const dataLines = [];
            for (const line of lines) {
              if (line.startsWith('event: ')) eventType = line.slice(7).trim();
              else if (line.startsWith('data: ')) dataLines.push(line.slice(6));
            }
            const data = dataLines.join('\n');
            if (!eventType) continue;
            let parsed = {};
            try { parsed = data ? JSON.parse(data) : {}; } catch { parsed = { raw: data }; }
            if (eventType === 'error') {
              callbacks.onError?.(new Error(parsed.message || data));
              return;
            }
            callbacks.onEvent?.({ event: eventType, ...parsed });
            if (eventType === 'batch_done') {
              callbacks.onDone?.({ event: eventType, ...parsed });
              return;
            }
          }
        }
      } catch (e) {
        if (e.name !== 'AbortError') callbacks.onError?.(e);
      }
    })();

    return controller;
  },
};
