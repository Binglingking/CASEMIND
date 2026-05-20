import { useState, useEffect } from 'react';
import * as api from '../api';

/**
 * 全局进度浮窗组件
 * 显示五阶段分析或AI记忆构建的实时进度
 * 无论切换到哪个页面都会持续显示
 */
export default function GlobalProgress({ project }) {
  const [progress, setProgress] = useState(null);
  const [progressType, setProgressType] = useState(null); // 'legacy' 或 'memory'
  const [pollingInterval, setPollingInterval] = useState(null);

  // 如果没有项目，不显示
  if (!project) {
    return null;
  }

  // 检查是否有正在进行的任务
  useEffect(() => {
    if (!project) {
      console.log('[GlobalProgress] No project selected');
      return;
    }

    console.log('[GlobalProgress] Checking progress for project:', project);
    let mounted = true;

    const checkProgress = async () => {
      try {
        // 先检查五阶段分析进度
        console.log('[GlobalProgress] Checking legacy analysis progress...');
        const legacyProgress = await api.legacyAnalysisProgress(project);
        console.log('[GlobalProgress] Legacy progress:', legacyProgress);
        
        if (!mounted) return;
        
        if (['running', 'paused'].includes(legacyProgress.status)) {
          console.log('[GlobalProgress] Found running legacy analysis');
          setProgress(legacyProgress);
          setProgressType('legacy');
          startPolling('legacy');
          return;
        }

        // 再检查AI记忆构建进度
        console.log('[GlobalProgress] Checking memory build progress...');
        try {
          const memoryProgress = await api.getMemoryBuildProgress(project);
          console.log('[GlobalProgress] Memory progress:', memoryProgress);
          
          if (!mounted) return;
          
          if (['running', 'paused'].includes(memoryProgress.status)) {
            console.log('[GlobalProgress] Found running memory build');
            setProgress(memoryProgress);
            setProgressType('memory');
            startPolling('memory');
          } else {
            console.log('[GlobalProgress] No running tasks found');
          }
        } catch (err) {
          console.warn('[GlobalProgress] Memory progress check failed:', err.message);
        }
      } catch (err) {
        console.warn('[GlobalProgress] Legacy progress check failed:', err.message);
      }
    };

    checkProgress();

    return () => {
      mounted = false;
      stopPolling();
    };
  }, [project]);

  // 启动轮询
  function startPolling(type) {
    stopPolling();
    
    const interval = setInterval(async () => {
      try {
        let newProgress;
        if (type === 'legacy') {
          newProgress = await api.legacyAnalysisProgress(project);
        } else {
          newProgress = await api.getMemoryBuildProgress(project);
        }

        setProgress(newProgress);

        // 如果任务完成/取消/错误，停止轮询
        if (['completed', 'cancelled', 'error'].includes(newProgress.status)) {
          stopPolling();
          setTimeout(() => {
            setProgress(null);
            setProgressType(null);
          }, 3000); // 3秒后自动隐藏
        }
      } catch (e) {
        console.error('[GlobalProgress] Polling error:', e);
      }
    }, 2000);

    setPollingInterval(interval);
  }

  // 停止轮询
  function stopPolling() {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      setPollingInterval(null);
    }
  }

  // 暂停任务
  async function handlePause() {
    try {
      if (progressType === 'legacy') {
        await api.legacyAnalysisPause(project);
      } else {
        await api.pauseMemoryBuild(project);
      }
    } catch (e) {
      console.error('[GlobalProgress] Pause error:', e);
    }
  }

  // 继续任务
  async function handleResume() {
    try {
      if (progressType === 'legacy') {
        await api.legacyAnalysisResume(project);
      } else {
        await api.resumeMemoryBuild(project);
      }
    } catch (e) {
      console.error('[GlobalProgress] Resume error:', e);
    }
  }

  // 取消任务
  async function handleCancel() {
    if (!confirm('确定要取消当前任务吗？')) return;
    
    try {
      if (progressType === 'legacy') {
        await api.legacyAnalysisCancel(project);
      } else {
        await api.cancelMemoryBuild(project);
      }
      
      stopPolling();
      setProgress(null);
      setProgressType(null);
    } catch (e) {
      console.error('[GlobalProgress] Cancel error:', e);
    }
  }

  // 格式化时间
  function formatSeconds(seconds) {
    if (!seconds && seconds !== 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  // 如果没有进度，不显示
  if (!progress || !project) return null;

  const isLegacy = progressType === 'legacy';
  const title = isLegacy ? '五阶段分析' : '构建 AI 记忆';
  const icon = isLegacy ? 'analytics' : 'build';

  return (
    <div style={{
      position: 'fixed',
      top: 80,
      right: 20,
      width: 420,
      zIndex: 1000,
      background: 'rgba(29, 27, 32, 0.98)',
      backdropFilter: 'blur(12px)',
      border: '1px solid rgba(207, 188, 255, 0.3)',
      borderRadius: 12,
      padding: 16,
      boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
      animation: 'slideInRight 0.3s ease-out',
    }}>
      {/* 标题栏 */}
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        marginBottom: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mi" style={{ 
            color: '#cfbcff', 
            fontSize: 20,
            animation: progress.status === 'running' ? 'pulse 1.4s infinite' : 'none',
          }}>
            {icon}
          </span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: '#e6e0e9' }}>
              {title}
            </div>
            <div style={{ fontSize: 11, color: '#948e9c' }}>
              {progress.message || '处理中...'}
              {progress.status === 'running' && (
                <span style={{ marginLeft: 8, color: '#7fd9a8' }}>● 运行中</span>
              )}
              {progress.status === 'paused' && (
                <span style={{ marginLeft: 8, color: '#ffc107' }}>● 已暂停</span>
              )}
            </div>
          </div>
        </div>
        
        {/* 控制按钮 */}
        <div style={{ display: 'flex', gap: 6 }}>
          {progress.status === 'running' && (
            <button 
              className="ghost" 
              onClick={handlePause}
              style={{ padding: '4px 8px', fontSize: 11 }}
              title="暂停"
            >
              <span className="mi" style={{ fontSize: 14 }}>pause</span>
            </button>
          )}
          {progress.status === 'paused' && (
            <button 
              className="primary" 
              onClick={handleResume}
              style={{ padding: '4px 8px', fontSize: 11 }}
              title="继续"
            >
              <span className="mi" style={{ fontSize: 14 }}>play_arrow</span>
            </button>
          )}
          <button 
            className="danger-ghost" 
            onClick={handleCancel}
            style={{ padding: '4px 8px', fontSize: 11 }}
            title="取消"
          >
            <span className="mi" style={{ fontSize: 14 }}>close</span>
          </button>
        </div>
      </div>

      {/* 进度条 */}
      <div style={{ 
        background: '#2a2830', 
        borderRadius: 4, 
        height: 6, 
        overflow: 'hidden', 
        marginBottom: 12,
      }}>
        <div 
          style={{ 
            width: `${progress.progress_percent || 0}%`, 
            height: '100%',
            background: progress.status === 'paused'
              ? 'linear-gradient(90deg, #e7c365, #f0d87a)'
              : 'linear-gradient(90deg, #7fd9a8, #cfbcff)',
            transition: 'width 0.3s ease',
          }}
        />
      </div>

      {/* 详细信息 */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(3, 1fr)', 
        gap: 10, 
        fontSize: 11,
      }}>
        {isLegacy ? (
          <>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>阶段</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {progress.current_stage}/{progress.total_stages}
              </div>
            </div>
            {progress.total_batches > 0 && (
              <div>
                <div style={{ color: '#948e9c', marginBottom: 2 }}>批次</div>
                <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                  {progress.completed_batches}/{progress.total_batches}
                </div>
              </div>
            )}
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>LLM调用</div>
              <div style={{ fontWeight: 600, color: '#cfbcff' }}>
                {progress.llm_calls}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>提取信号</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {progress.extracted_signals}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>耗时</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {formatSeconds(progress.elapsed_seconds)}
              </div>
            </div>
          </>
        ) : (
          <>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>步骤</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {progress.current_step}/{progress.total_steps}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>文件</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {progress.processed_files}/{progress.total_files}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>LLM调用</div>
              <div style={{ fontWeight: 600, color: '#cfbcff' }}>
                {progress.llm_calls}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>知识点</div>
              <div style={{ fontWeight: 600, color: '#7fd9a8' }}>
                {progress.extracted_kps}
              </div>
            </div>
            <div>
              <div style={{ color: '#948e9c', marginBottom: 2 }}>耗时</div>
              <div style={{ fontWeight: 600, color: '#e6e0e9' }}>
                {formatSeconds(progress.elapsed_seconds)}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
