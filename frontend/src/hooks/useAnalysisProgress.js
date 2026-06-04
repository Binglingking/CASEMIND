import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

/**
 * 管理五阶段分析的进度轮询、暂停/恢复/取消、localStorage 恢复
 */
export default function useAnalysisProgress(project) {
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(null);
  const progressTimerRef = useRef(null);

  // 组件挂载时检查是否有正在进行的分析
  useEffect(() => {
    if (!project) return;

    const saved = localStorage.getItem(`analysis_progress_${project}`);
    if (saved) {
      try {
        const { analyzing: wasAnalyzing, progress: savedProgress, timestamp } = JSON.parse(saved);
        const twoHoursAgo = Date.now() - 2 * 60 * 60 * 1000;
        if (timestamp > twoHoursAgo && wasAnalyzing) {
          setAnalyzing(true);
          setAnalysisProgress(savedProgress);

          api.legacyAnalysisProgress(project).then(progress => {
            setAnalysisProgress(progress);
            if (['running', 'paused'].includes(progress.status)) {
              startProgressPolling();
            } else {
              setAnalyzing(false);
              setAnalysisProgress(null);
              localStorage.removeItem(`analysis_progress_${project}`);
            }
          }).catch(() => {
            localStorage.removeItem(`analysis_progress_${project}`);
            setAnalyzing(false);
          });
        } else {
          localStorage.removeItem(`analysis_progress_${project}`);
        }
      } catch (e) {
        localStorage.removeItem(`analysis_progress_${project}`);
      }
    }

    return () => stopProgressPolling();
  }, [project]);

  function startProgressPolling() {
    stopProgressPolling();
    progressTimerRef.current = setInterval(async () => {
      try {
        const progress = await api.legacyAnalysisProgress(project);
        setAnalysisProgress(progress);

        if (['running', 'paused'].includes(progress.status)) {
          localStorage.setItem(`analysis_progress_${project}`, JSON.stringify({
            analyzing: true,
            progress,
            timestamp: Date.now(),
          }));
        }

        if (['completed', 'cancelled', 'error'].includes(progress.status)) {
          stopProgressPolling();
          setAnalyzing(false);
          setAnalysisProgress(null);
          localStorage.removeItem(`analysis_progress_${project}`);
        }
      } catch (e) {
        console.error('[useAnalysisProgress] Failed to fetch progress:', e);
      }
    }, 2000);
  }

  function stopProgressPolling() {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }

  async function pauseAnalysis() {
    try { await api.legacyAnalysisPause(project); } catch (e) { throw e; }
  }

  async function resumeAnalysis() {
    try { await api.legacyAnalysisResume(project); } catch (e) { throw e; }
  }

  async function cancelAnalysis() {
    try {
      await api.legacyAnalysisCancel(project);
      stopProgressPolling();
      setAnalyzing(false);
      setAnalysisProgress(null);
      localStorage.removeItem(`analysis_progress_${project}`);
    } catch (e) { throw e; }
  }

  function clearProgress() {
    stopProgressPolling();
    setAnalyzing(false);
    setAnalysisProgress(null);
    localStorage.removeItem(`analysis_progress_${project}`);
  }

  return {
    analyzing,
    setAnalyzing,
    analysisProgress,
    setAnalysisProgress,
    startProgressPolling,
    stopProgressPolling,
    pauseAnalysis,
    resumeAnalysis,
    cancelAnalysis,
    clearProgress,
  };
}
