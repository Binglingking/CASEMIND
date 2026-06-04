import React from 'react';

export default function AnalysisProgressPanel({ progress, onPause, onResume, onCancel }) {
  if (!progress) return null;

  return (
    <div className="card" style={{ padding: 16, marginBottom: 12, background: 'rgba(127,217,168,0.05)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mi" style={{ color: '#cfbcff', fontSize: 20 }}>analytics</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{progress.stage_name || '分析中...'}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              {progress.message}
              {progress.status === 'running' && (
                <span style={{ marginLeft: 8, color: '#7fd9a8' }}>{'●'} 后台运行中</span>
              )}
              {progress.status === 'paused' && (
                <span style={{ marginLeft: 8, color: '#ffc107' }}>{'●'} 已暂停</span>
              )}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {progress.status === 'running' && (
            <button className="ghost" onClick={onPause} style={{ fontSize: 12 }}>
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>pause</span>
              暂停
            </button>
          )}
          {progress.status === 'paused' && (
            <button className="ghost" onClick={onResume} style={{ fontSize: 12 }}>
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>play_arrow</span>
              继续
            </button>
          )}
          <button className="danger-ghost" onClick={onCancel} style={{ fontSize: 12 }}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>stop</span>
            取消
          </button>
        </div>
      </div>

      <div style={{ background: '#2a2830', borderRadius: 4, height: 8, overflow: 'hidden', marginBottom: 8 }}>
        <div
          style={{
            width: `${progress.progress_percent || 0}%`,
            height: '100%',
            background: 'linear-gradient(90deg, #7fd9a8, #cfbcff)',
            transition: 'width 0.3s ease',
          }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, fontSize: 12 }}>
        <div>
          <div className="muted">阶段</div>
          <div style={{ fontWeight: 600 }}>{progress.current_stage}/{progress.total_stages}</div>
        </div>
        {progress.total_batches > 0 && (
          <div>
            <div className="muted">批次</div>
            <div style={{ fontWeight: 600 }}>{progress.completed_batches}/{progress.total_batches}</div>
          </div>
        )}
        <div>
          <div className="muted">LLM调用</div>
          <div style={{ fontWeight: 600 }}>{progress.llm_calls}</div>
        </div>
        <div>
          <div className="muted">提取信号</div>
          <div style={{ fontWeight: 600 }}>{progress.extracted_signals}</div>
        </div>
        <div>
          <div className="muted">耗时</div>
          <div style={{ fontWeight: 600 }}>{Math.floor(progress.elapsed_seconds / 60)}分{Math.floor(progress.elapsed_seconds % 60)}秒</div>
        </div>
      </div>
    </div>
  );
}
