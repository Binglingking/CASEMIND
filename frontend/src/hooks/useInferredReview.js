import { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function useInferredReview(project) {
  const [inferred, setInferred] = useState([]);
  const [inferredFilter, setInferredFilter] = useState('pending_review');
  const [inferredErr, setInferredErr] = useState('');
  const [selectedInferred, setSelectedInferred] = useState(new Set());
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [editingInferredId, setEditingInferredId] = useState(null);
  const [editingContent, setEditingContent] = useState('');
  const [expandedSources, setExpandedSources] = useState(new Set());

  const totalPages = Math.ceil(inferred.length / pageSize);

  function getCurrentPageItems() {
    const start = (currentPage - 1) * pageSize;
    return inferred.slice(start, start + pageSize);
  }

  async function refreshInferred() {
    setInferredErr('');
    if (!project) { setInferred([]); return; }
    try {
      const status = inferredFilter === 'all' ? null : inferredFilter;
      const r = await api.legacyListInferred(project, status);
      setInferred(Array.isArray(r) ? r : (r.items || []));
    } catch (e) {
      setInferredErr(String(e.message || e));
      setInferred([]);
    }
  }

  useEffect(() => { refreshInferred(); }, [project, inferredFilter]);

  useEffect(() => { setCurrentPage(1); }, [inferredFilter]);

  async function reviewInferred(item, decision) {
    try {
      await api.legacyReviewInferred(project, item.inferred_id, decision);
      refreshInferred();
      if (selectedInferred.has(item.inferred_id)) {
        const next = new Set(selectedInferred);
        next.delete(item.inferred_id);
        setSelectedInferred(next);
      }
    } catch (e) { setInferredErr(String(e.message || e)); }
  }

  async function batchReviewInferred(decision) {
    if (selectedInferred.size === 0) { setInferredErr('请先选择要审核的候选项'); return; }
    try {
      await api.legacyBatchReviewInferred(project, Array.from(selectedInferred), decision);
      setSelectedInferred(new Set());
      refreshInferred();
    } catch (e) { setInferredErr(String(e.message || e)); }
  }

  async function revokeAutoAccepted(item) {
    try { await api.legacyRevokeInferred(project, item.inferred_id); refreshInferred(); }
    catch (e) { setInferredErr(String(e.message || e)); }
  }

  function startEditInferred(item) {
    setEditingInferredId(item.inferred_id);
    setEditingContent(item.content || '');
  }

  function cancelEditInferred() {
    setEditingInferredId(null);
    setEditingContent('');
  }

  async function saveEditInferred(item) {
    if (!editingContent.trim()) { setInferredErr('内容不能为空'); return; }
    try {
      await api.legacyEditInferred(project, item.inferred_id, editingContent.trim());
      setEditingInferredId(null);
      setEditingContent('');
      refreshInferred();
    } catch (e) { setInferredErr(String(e.message || e)); }
  }

  function toggleSourceExpand(id) {
    const next = new Set(expandedSources);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpandedSources(next);
  }

  function toggleSelectInferred(id) {
    const next = new Set(selectedInferred);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedInferred(next);
  }

  function toggleSelectAll() {
    const pageItems = getCurrentPageItems();
    const allSelected = selectedInferred.size === pageItems.length && pageItems.length > 0;
    const next = new Set(selectedInferred);
    if (allSelected) {
      pageItems.forEach(item => next.delete(item.inferred_id));
    } else {
      pageItems.forEach(item => next.add(item.inferred_id));
    }
    setSelectedInferred(next);
  }

  function goToPage(page) {
    if (page >= 1 && page <= totalPages) setCurrentPage(page);
  }

  return {
    inferred, inferredFilter, setInferredFilter,
    inferredErr, selectedInferred,
    currentPage, pageSize, setPageSize,
    editingInferredId, editingContent, setEditingContent,
    expandedSources, totalPages,
    getCurrentPageItems, refreshInferred,
    reviewInferred, batchReviewInferred, revokeAutoAccepted,
    startEditInferred, cancelEditInferred, saveEditInferred,
    toggleSourceExpand, toggleSelectInferred, toggleSelectAll, goToPage,
  };
}
