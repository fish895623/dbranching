"""Progress reporting system for snapshot operations."""

import asyncio
import logging
import time
from collections import deque
from typing import Optional, Callable, Deque, Tuple
from datetime import datetime, timedelta

from .models import ProgressReport, OperationPhase

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Advanced progress tracker with ETA calculation and speed monitoring."""
    
    def __init__(
        self,
        total_work: int,
        callback: Optional[Callable[[ProgressReport], None]] = None,
        history_size: int = 10,
        min_update_interval: float = 0.5
    ):
        """
        Initialize progress tracker.
        
        Args:
            total_work: Total amount of work to be done
            callback: Optional callback function for progress updates
            history_size: Number of historical data points for speed calculation
            min_update_interval: Minimum interval between progress updates (seconds)
        """
        self.total_work = total_work
        self.current_work = 0
        self.callback = callback
        
        # Progress tracking
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.min_update_interval = min_update_interval
        
        # Speed calculation with rolling average
        self.history_size = history_size
        self.progress_history: Deque[Tuple[float, int]] = deque(maxlen=history_size)
        
        # Current state
        self.current_phase = OperationPhase.INITIALIZING
        self.current_message = ""
        self.current_stage = ""
        
        # Cancellation support
        self._cancelled = False
        self._lock = asyncio.Lock()
    
    async def update(
        self,
        current: int,
        message: str = "",
        stage: str = "",
        force_update: bool = False
    ) -> None:
        """
        Update progress and optionally trigger callback.
        
        Args:
            current: Current progress value
            message: Optional progress message
            stage: Current stage description
            force_update: Force update even if min interval hasn't passed
        """
        async with self._lock:
            if self._cancelled:
                return
            
            current_time = time.time()
            
            # Check if we should update based on time interval
            time_since_update = current_time - self.last_update_time
            should_update = (
                force_update or 
                time_since_update >= self.min_update_interval or
                current >= self.total_work
            )
            
            if not should_update and current > self.current_work:
                # Always update internal state even if not triggering callback
                self.current_work = current
                return
            
            # Update internal state
            old_work = self.current_work
            self.current_work = min(current, self.total_work)
            self.current_message = message
            self.current_stage = stage
            self.last_update_time = current_time
            
            # Add to history for speed calculation
            if current > old_work:
                self.progress_history.append((current_time, self.current_work))
            
            # Calculate progress metrics
            percentage = (self.current_work / self.total_work * 100) if self.total_work > 0 else 0
            eta_seconds = self._calculate_eta()
            speed_mbps = self._calculate_speed()
            
            # Create progress report
            report = ProgressReport(
                phase=self.current_phase,
                current=self.current_work,
                total=self.total_work,
                percentage=percentage,
                message=message,
                stage=stage,
                eta_seconds=eta_seconds,
                speed_mbps=speed_mbps
            )
            
            # Trigger callback if provided
            if self.callback:
                try:
                    if asyncio.iscoroutinefunction(self.callback):
                        await self.callback(report)
                    else:
                        self.callback(report)
                except Exception as e:
                    logger.warning(f"Progress callback failed: {e}")
    
    async def set_phase(self, phase: OperationPhase, message: str = "") -> None:
        """
        Set current operation phase.
        
        Args:
            phase: New operation phase
            message: Optional phase description message
        """
        async with self._lock:
            self.current_phase = phase
            if message:
                self.current_message = message
            
            # Force update when phase changes
            await self.update(self.current_work, message, force_update=True)
    
    async def add_work(self, additional_work: int) -> None:
        """
        Add additional work to total (useful for dynamic operations).
        
        Args:
            additional_work: Amount of additional work to add
        """
        async with self._lock:
            self.total_work += additional_work
            logger.debug(f"Added {additional_work} work units, total now {self.total_work}")
    
    async def complete_phase(self, message: str = "") -> None:
        """Mark current phase as completed and update progress."""
        await self.update(self.current_work, message or f"{self.current_phase.value} completed", force_update=True)
    
    async def cancel(self) -> None:
        """Cancel progress tracking."""
        async with self._lock:
            self._cancelled = True
            logger.debug("Progress tracking cancelled")
    
    async def is_cancelled(self) -> bool:
        """Check if progress tracking was cancelled."""
        async with self._lock:
            return self._cancelled
    
    def _calculate_eta(self) -> Optional[float]:
        """Calculate estimated time to completion based on progress history."""
        if len(self.progress_history) < 2:
            return None
        
        current_time = time.time()
        elapsed_time = current_time - self.start_time
        
        # Use recent progress for ETA calculation
        if len(self.progress_history) >= 2:
            recent_time, recent_work = self.progress_history[-1]
            older_time, older_work = self.progress_history[max(0, len(self.progress_history) - 5)]
            
            time_diff = recent_time - older_time
            work_diff = recent_work - older_work
            
            if time_diff > 0 and work_diff > 0:
                work_rate = work_diff / time_diff
                remaining_work = self.total_work - self.current_work
                
                if work_rate > 0:
                    eta = remaining_work / work_rate
                    return max(0, eta)
        
        # Fallback: use overall average rate
        if elapsed_time > 0 and self.current_work > 0:
            overall_rate = self.current_work / elapsed_time
            remaining_work = self.total_work - self.current_work
            
            if overall_rate > 0:
                eta = remaining_work / overall_rate
                return max(0, eta)
        
        return None
    
    def _calculate_speed(self) -> Optional[float]:
        """Calculate current speed in MB/s based on progress history."""
        if len(self.progress_history) < 2:
            return None
        
        # Use recent measurements for speed calculation
        recent_measurements = list(self.progress_history)[-min(5, len(self.progress_history)):]
        
        if len(recent_measurements) >= 2:
            time_span = recent_measurements[-1][0] - recent_measurements[0][0]
            work_span = recent_measurements[-1][1] - recent_measurements[0][1]
            
            if time_span > 0:
                # Convert bytes per second to MB/s
                bytes_per_second = work_span / time_span
                mbps = bytes_per_second / (1024 * 1024)
                return max(0, mbps)
        
        return None
    
    def get_summary(self) -> dict:
        """Get summary of progress tracking."""
        current_time = time.time()
        elapsed_time = current_time - self.start_time
        percentage = (self.current_work / self.total_work * 100) if self.total_work > 0 else 0
        
        return {
            "phase": self.current_phase.value,
            "progress": f"{self.current_work}/{self.total_work}",
            "percentage": f"{percentage:.1f}%",
            "elapsed_seconds": elapsed_time,
            "eta_seconds": self._calculate_eta(),
            "speed_mbps": self._calculate_speed(),
            "cancelled": self._cancelled,
            "message": self.current_message,
            "stage": self.current_stage,
        }


class MultiPhaseProgressTracker:
    """Progress tracker for multi-phase operations with weighted phases."""
    
    def __init__(
        self,
        phase_weights: dict[OperationPhase, float],
        callback: Optional[Callable[[ProgressReport], None]] = None
    ):
        """
        Initialize multi-phase progress tracker.
        
        Args:
            phase_weights: Mapping of phases to their relative weights (0-1)
            callback: Optional callback function for progress updates
        """
        self.phase_weights = phase_weights
        self.callback = callback
        
        # Normalize weights to sum to 1.0
        total_weight = sum(phase_weights.values())
        if total_weight > 0:
            self.phase_weights = {
                phase: weight / total_weight 
                for phase, weight in phase_weights.items()
            }
        
        # Current state
        self.current_phase = OperationPhase.INITIALIZING
        self.phase_trackers: dict[OperationPhase, ProgressTracker] = {}
        self.completed_phases: set[OperationPhase] = set()
        
        # Overall tracking
        self.start_time = time.time()
        self._lock = asyncio.Lock()
    
    async def start_phase(
        self,
        phase: OperationPhase,
        total_work: int,
        message: str = ""
    ) -> ProgressTracker:
        """
        Start a new phase and return its progress tracker.
        
        Args:
            phase: Phase to start
            total_work: Total work units for this phase
            message: Optional phase description
            
        Returns:
            ProgressTracker for the phase
        """
        async with self._lock:
            self.current_phase = phase
            
            # Create phase-specific progress tracker
            phase_tracker = ProgressTracker(
                total_work=total_work,
                callback=self._create_phase_callback(phase)
            )
            
            self.phase_trackers[phase] = phase_tracker
            
            # Set initial phase
            await phase_tracker.set_phase(phase, message)
            
            logger.debug(f"Started phase {phase.value} with {total_work} work units")
            return phase_tracker
    
    async def complete_phase(self, phase: OperationPhase, message: str = "") -> None:
        """
        Mark phase as completed.
        
        Args:
            phase: Phase to complete
            message: Optional completion message
        """
        async with self._lock:
            if phase in self.phase_trackers:
                await self.phase_trackers[phase].complete_phase(message)
                self.completed_phases.add(phase)
                
                # Update overall progress
                await self._update_overall_progress()
                
                logger.debug(f"Completed phase {phase.value}")
    
    def _create_phase_callback(self, phase: OperationPhase) -> Callable[[ProgressReport], None]:
        """Create callback function for phase-specific progress updates."""
        async def phase_callback(report: ProgressReport):
            # Update overall progress when phase progress changes
            await self._update_overall_progress()
            
        return phase_callback
    
    async def _update_overall_progress(self) -> None:
        """Update overall progress based on phase progress."""
        if not self.callback:
            return
            
        # Calculate overall progress as weighted sum of phase progress
        overall_progress = 0.0
        overall_message_parts = []
        
        for phase, weight in self.phase_weights.items():
            if phase in self.completed_phases:
                overall_progress += weight
            elif phase in self.phase_trackers:
                tracker = self.phase_trackers[phase]
                phase_percentage = (tracker.current_work / tracker.total_work) if tracker.total_work > 0 else 0
                overall_progress += weight * phase_percentage
                
                if tracker.current_message:
                    overall_message_parts.append(f"{phase.value}: {tracker.current_message}")
        
        # Calculate overall ETA based on current phase ETA and remaining phases
        overall_eta = None
        if self.current_phase in self.phase_trackers:
            current_tracker = self.phase_trackers[self.current_phase]
            phase_eta = current_tracker._calculate_eta()
            
            if phase_eta is not None:
                # Rough estimate: add time for remaining phases based on current phase rate
                remaining_weight = sum(
                    weight for phase, weight in self.phase_weights.items()
                    if phase not in self.completed_phases and phase != self.current_phase
                )
                
                current_weight = self.phase_weights.get(self.current_phase, 0)
                if current_weight > 0:
                    estimated_total_eta = phase_eta + (phase_eta * remaining_weight / current_weight)
                    overall_eta = max(0, estimated_total_eta)
        
        # Create overall progress report
        report = ProgressReport(
            phase=self.current_phase,
            current=int(overall_progress * 100),
            total=100,
            percentage=overall_progress * 100,
            message=" | ".join(overall_message_parts),
            stage=f"Phase {len(self.completed_phases) + 1}/{len(self.phase_weights)}",
            eta_seconds=overall_eta,
            speed_mbps=None  # Speed is phase-specific
        )
        
        # Trigger callback
        try:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(report)
            else:
                self.callback(report)
        except Exception as e:
            logger.warning(f"Overall progress callback failed: {e}")
    
    async def cancel_all(self) -> None:
        """Cancel all phase trackers."""
        for tracker in self.phase_trackers.values():
            await tracker.cancel()
    
    def get_overall_summary(self) -> dict:
        """Get overall operation summary."""
        current_time = time.time()
        elapsed_time = current_time - self.start_time
        
        phase_summaries = {}
        for phase, tracker in self.phase_trackers.items():
            phase_summaries[phase.value] = tracker.get_summary()
        
        return {
            "current_phase": self.current_phase.value,
            "completed_phases": [p.value for p in self.completed_phases],
            "total_elapsed_seconds": elapsed_time,
            "phase_summaries": phase_summaries,
            "overall_progress": len(self.completed_phases) / len(self.phase_weights) * 100,
        }