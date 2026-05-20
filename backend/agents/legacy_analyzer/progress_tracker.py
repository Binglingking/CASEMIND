"""分析进度跟踪器 - 支持暂停、继续、取消。"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field


class AnalysisStatus(Enum):
    """分析状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ProgressInfo:
    """进度信息"""
    status: AnalysisStatus = AnalysisStatus.IDLE
    current_stage: int = 0  # 0-5，当前阶段
    total_stages: int = 5
    stage_name: str = ""
    
    # Stage 2 专用（LLM调用）
    total_batches: int = 0
    completed_batches: int = 0
    current_batch: int = 0
    batch_type: str = ""  # "case" or "xmind"
    
    # 统计信息
    llm_calls: int = 0
    extracted_signals: int = 0
    elapsed_seconds: float = 0.0
    
    # 消息
    message: str = ""
    error: Optional[str] = None
    
    # 时间戳
    started_at: Optional[float] = None
    paused_at: Optional[float] = None
    resumed_at: Optional[float] = None
    completed_at: Optional[float] = None


class AnalysisController:
    """分析控制器 - 管理单个项目的分析进程"""
    
    def __init__(self, project: str):
        self.project = project
        self.progress = ProgressInfo()
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始为运行状态
        self._cancel_flag = False
    
    def start(self):
        """开始分析"""
        with self._lock:
            self.progress.status = AnalysisStatus.RUNNING
            self.progress.started_at = time.time()
            self.progress.completed_at = None
            self.progress.error = None
            self._cancel_flag = False
            self._pause_event.set()
    
    def pause(self):
        """暂停分析"""
        with self._lock:
            if self.progress.status == AnalysisStatus.RUNNING:
                self.progress.status = AnalysisStatus.PAUSED
                self.progress.paused_at = time.time()
                self._pause_event.clear()
                self.progress.message = "已暂停"
    
    def resume(self):
        """继续分析"""
        with self._lock:
            if self.progress.status == AnalysisStatus.PAUSED:
                self.progress.status = AnalysisStatus.RUNNING
                self.progress.resumed_at = time.time()
                self._pause_event.set()
                self.progress.message = "已继续"
    
    def cancel(self):
        """取消分析"""
        with self._lock:
            self._cancel_flag = True
            self.progress.status = AnalysisStatus.CANCELLED
            self.progress.completed_at = time.time()
            self._pause_event.set()  # 释放等待，让线程退出
            self.progress.message = "已取消"
    
    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancel_flag
    
    def wait_if_paused(self):
        """如果暂停则等待，用于在批次间检查"""
        self._pause_event.wait()
    
    def update_progress(
        self,
        stage: Optional[int] = None,
        stage_name: Optional[str] = None,
        total_batches: Optional[int] = None,
        completed_batches: Optional[int] = None,
        current_batch: Optional[int] = None,
        batch_type: Optional[str] = None,
        llm_calls: Optional[int] = None,
        extracted_signals: Optional[int] = None,
        message: Optional[str] = None,
    ):
        """更新进度"""
        with self._lock:
            if stage is not None:
                self.progress.current_stage = stage
            if stage_name is not None:
                self.progress.stage_name = stage_name
            if total_batches is not None:
                self.progress.total_batches = total_batches
            if completed_batches is not None:
                self.progress.completed_batches = completed_batches
            if current_batch is not None:
                self.progress.current_batch = current_batch
            if batch_type is not None:
                self.progress.batch_type = batch_type
            if llm_calls is not None:
                self.progress.llm_calls = llm_calls
            if extracted_signals is not None:
                self.progress.extracted_signals = extracted_signals
            if message is not None:
                self.progress.message = message
            
            # 更新耗时
            if self.progress.started_at:
                self.progress.elapsed_seconds = time.time() - self.progress.started_at
    
    def complete(self, error: Optional[str] = None):
        """完成分析"""
        with self._lock:
            self.progress.completed_at = time.time()
            if error:
                self.progress.status = AnalysisStatus.ERROR
                self.progress.error = error
            else:
                self.progress.status = AnalysisStatus.COMPLETED
                self.progress.message = "分析完成"
    
    def get_progress(self) -> dict:
        """获取进度信息（字典格式，用于JSON序列化）"""
        with self._lock:
            return {
                "project": self.project,
                "status": self.progress.status.value,
                "current_stage": self.progress.current_stage,
                "total_stages": self.progress.total_stages,
                "stage_name": self.progress.stage_name,
                "total_batches": self.progress.total_batches,
                "completed_batches": self.progress.completed_batches,
                "current_batch": self.progress.current_batch,
                "batch_type": self.progress.batch_type,
                "llm_calls": self.progress.llm_calls,
                "extracted_signals": self.progress.extracted_signals,
                "elapsed_seconds": round(self.progress.elapsed_seconds, 1),
                "message": self.progress.message,
                "error": self.progress.error,
                "progress_percent": self._calculate_percent(),
            }
    
    def _calculate_percent(self) -> float:
        """计算总体进度百分比"""
        if self.progress.total_stages == 0:
            return 0.0
        
        # 基础进度：按阶段计算
        base_percent = (self.progress.current_stage / self.progress.total_stages) * 100
        
        # 如果在Stage 2，添加批次进度
        if self.progress.current_stage == 2 and self.progress.total_batches > 0:
            batch_percent = (self.progress.completed_batches / self.progress.total_batches) * 20  # Stage 2占20%
            base_percent += batch_percent
        
        return min(round(base_percent, 1), 100.0)


# 全局控制器管理器
class ControllerManager:
    """管理所有项目的分析控制器"""
    
    def __init__(self):
        self._controllers: dict[str, AnalysisController] = {}
        self._lock = threading.Lock()
    
    def get_or_create(self, project: str) -> AnalysisController:
        """获取或创建控制器"""
        with self._lock:
            if project not in self._controllers:
                self._controllers[project] = AnalysisController(project)
            return self._controllers[project]
    
    def get(self, project: str) -> Optional[AnalysisController]:
        """获取控制器"""
        with self._lock:
            return self._controllers.get(project)
    
    def remove(self, project: str):
        """移除控制器"""
        with self._lock:
            self._controllers.pop(project, None)


# 全局实例
controller_manager = ControllerManager()
