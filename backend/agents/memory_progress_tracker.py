"""Memory build progress tracker — track and control memory building."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryBuildProgress:
    """Track memory build progress."""

    def __init__(self, project: str):
        self.project = project
        self.status = "idle"  # idle | running | paused | cancelled | completed | error
        self.current_step = 0
        self.total_steps = 6
        self.step_name = ""
        self.processed_files = 0
        self.total_files = 0
        self.llm_calls = 0
        self.extracted_kps = 0
        self.elapsed_seconds = 0.0
        self.message = ""
        self.error: Optional[str] = None
        self._start_time: Optional[float] = None
        self._pause_start: Optional[float] = None
        self._paused_elapsed = 0.0
        self._lock = threading.Lock()
        self._should_pause = False
        self._should_cancel = False

    def start(self, total_files: int):
        with self._lock:
            self.status = "running"
            self._start_time = time.time()
            self._pause_start = None
            self._paused_elapsed = 0.0
            self.total_files = total_files
            self.processed_files = 0
            self.llm_calls = 0
            self.extracted_kps = 0
            self.error = None
            self._should_pause = False
            self._should_cancel = False

    def update_progress(
        self,
        step: Optional[int] = None,
        step_name: Optional[str] = None,
        processed_files: Optional[int] = None,
        total_files: Optional[int] = None,
        llm_calls: Optional[int] = None,
        extracted_kps: Optional[int] = None,
        message: Optional[str] = None,
    ):
        with self._lock:
            if step is not None:
                self.current_step = step
            if step_name is not None:
                self.step_name = step_name
            if processed_files is not None:
                self.processed_files = processed_files
            if total_files is not None:
                self.total_files = total_files
            if llm_calls is not None:
                self.llm_calls = llm_calls
            if extracted_kps is not None:
                self.extracted_kps = extracted_kps
            if message is not None:
                self.message = message
            self._update_elapsed()

    def pause(self):
        """Request pause (will pause at next checkpoint)."""
        with self._lock:
            if self.status == "running":
                self._should_pause = True
                self._pause_start = time.time()
                logger.info(f"[MemoryBuild] Pause requested for {self.project}")

    def resume(self):
        """Resume from paused state."""
        with self._lock:
            if self.status == "paused":
                if self._pause_start is not None:
                    self._paused_elapsed += time.time() - self._pause_start
                    self._pause_start = None
                self.status = "running"
                self._should_pause = False
                logger.info(f"[MemoryBuild] Resumed for {self.project}")

    def cancel(self):
        """Request immediate cancellation."""
        with self._lock:
            if self.status in ("running", "paused"):
                self._should_cancel = True
                self._should_pause = False
                logger.info(f"[MemoryBuild] Cancel requested for {self.project}")

    def check_should_pause(self) -> bool:
        """Check if should pause at next checkpoint."""
        with self._lock:
            return self._should_pause

    def check_should_cancel(self) -> bool:
        """Check if should cancel immediately."""
        with self._lock:
            return self._should_cancel

    def complete(self, error: Optional[str] = None):
        """Mark build as completed or errored."""
        with self._lock:
            self._update_elapsed()
            if error:
                self.status = "error"
                self.error = error
            else:
                self.status = "completed"
            logger.info(f"[MemoryBuild] Completed for {self.project}: status={self.status}")

    def _update_elapsed(self):
        """Update elapsed time."""
        if self._start_time is None:
            return
        if self.status == "paused" and self._pause_start:
            self.elapsed_seconds = self._paused_elapsed
        else:
            current = time.time() - self._start_time - self._paused_elapsed
            if self._pause_start:
                current -= (time.time() - self._pause_start)
            self.elapsed_seconds = current

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        with self._lock:
            self._update_elapsed()
            progress_percent = 0
            if self.total_files > 0:
                progress_percent = round((self.processed_files / self.total_files) * 100, 1)
            elif self.total_steps > 0:
                progress_percent = round((self.current_step / self.total_steps) * 100, 1)

            return {
                "project": self.project,
                "status": self.status,
                "current_step": self.current_step,
                "total_steps": self.total_steps,
                "step_name": self.step_name,
                "processed_files": self.processed_files,
                "total_files": self.total_files,
                "llm_calls": self.llm_calls,
                "extracted_kps": self.extracted_kps,
                "elapsed_seconds": round(self.elapsed_seconds, 1),
                "message": self.message,
                "error": self.error,
                "progress_percent": progress_percent,
            }


class MemoryBuildControllerManager:
    """Manage memory build controllers for multiple projects."""

    def __init__(self):
        self._controllers: dict[str, MemoryBuildProgress] = {}
        self._lock = threading.Lock()

    def get_or_create(self, project: str) -> MemoryBuildProgress:
        with self._lock:
            if project not in self._controllers:
                self._controllers[project] = MemoryBuildProgress(project)
            return self._controllers[project]

    def get(self, project: str) -> Optional[MemoryBuildProgress]:
        with self._lock:
            return self._controllers.get(project)

    def remove(self, project: str):
        with self._lock:
            self._controllers.pop(project, None)


# Global manager instance
controller_manager = MemoryBuildControllerManager()
