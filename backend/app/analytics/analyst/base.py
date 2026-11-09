"""Base abstract class for all NEXUS Adaptive Analyst Skills."""

from abc import ABC, abstractmethod
import time
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.analytics.analyst.models import (
    ExecutionContext,
    SkillDomain,
    SkillExecutionResult,
    SkillMetadata,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseAnalystSkill(ABC):
    """Abstract base class that all specialist analytical skills implement."""

    def __init__(self, metadata: SkillMetadata) -> None:
        self.metadata = metadata

    @property
    def skill_id(self) -> str:
        return self.metadata.skill_id

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def domain(self) -> SkillDomain:
        return self.metadata.domain

    @property
    def enabled(self) -> bool:
        return self.metadata.enabled

    def set_enabled(self, status: bool) -> None:
        self.metadata.enabled = status

    def run(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        """Safe execution harness measuring latency, handling errors, and validating boundaries."""
        if not self.enabled:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="SKIPPED",
                findings=[f"Skill '{self.name}' is currently disabled in registry."],
                confidence_score=0.0,
            )

        start_time = time.perf_counter()
        try:
            result = self._execute(db, context)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            result.execution_time_ms = round(elapsed_ms, 2)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Skill execution failed for {self.skill_id}: {exc}", exc_info=True)
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="FAILED",
                error_message=str(exc),
                findings=[f"Analysis failed: {str(exc)}"],
                confidence_score=0.0,
                execution_time_ms=round(elapsed_ms, 2),
            )

    def execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        """Alias for run() to support both execute and run invocations."""
        return self.run(db, context)

    @abstractmethod
    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        """Specialist analytical logic implemented by concrete skills."""
        pass
