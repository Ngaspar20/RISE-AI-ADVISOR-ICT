"""
orchestrator.py
───────────────
Coordinates all three agents into a single analysis run.
Called by the scheduler (automated) and the Streamlit UI (on-demand).

Returns an OrchestratorResult containing outputs from all three agents.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import pandas as pd

from agents.flagging_agent import FlaggingAgent
from agents.allocation_agent import AllocationAgent
from agents.root_cause_agent import RootCauseAgent
from agents.base_agent import AgentResult

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    success: bool
    flagging: Optional[AgentResult] = None
    allocation: Optional[AgentResult] = None
    root_cause: Optional[AgentResult] = None
    elapsed_seconds: float = 0.0
    errors: list = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        results = [self.flagging, self.allocation, self.root_cause]
        return all(r is not None and r.success for r in results)

    def summary(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "all_succeeded": self.all_succeeded,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "flagging_ok": self.flagging.success if self.flagging else False,
            "allocation_ok": self.allocation.success if self.allocation else False,
            "root_cause_ok": self.root_cause.success if self.root_cause else False,
            "errors": self.errors,
        }


class Orchestrator:
    """
    Runs all three analysis workflows in sequence.

    Usage:
        orch = Orchestrator()
        result = orch.run(df, province="MANICA")
    """

    def __init__(self):
        self.flagging_agent = FlaggingAgent()
        self.allocation_agent = AllocationAgent()
        self.root_cause_agent = RootCauseAgent()

    def run(
        self,
        df: pd.DataFrame,
        province: Optional[str] = None,
        district: Optional[str] = None,
        run_flagging: bool = True,
        run_allocation: bool = True,
        run_root_cause: bool = True,
        n_supervisors: int = 2,
    ) -> OrchestratorResult:
        """
        Execute all workflows.

        Parameters
        ----------
        df             : Normalised ICT line-list from data_loader
        province       : Filter to specific province
        district       : Filter to specific district
        run_*          : Toggle individual workflows (for on-demand partial runs)
        n_supervisors  : For allocation planning
        """
        logger.info(
            f"Orchestrator starting | province={province} district={district} | "
            f"n={len(df):,} rows"
        )
        start = time.time()
        result = OrchestratorResult(success=False)

        # ── Workflow 1: Performance Flagging ───────────────────────────────────
        if run_flagging:
            logger.info("Running Workflow 1: Performance Flagging...")
            try:
                result.flagging = self.flagging_agent.run(
                    df, province=province, district=district
                )
                if not result.flagging.success:
                    result.errors.append(f"Flagging: {result.flagging.error}")
            except Exception as e:
                logger.error(f"Flagging agent crashed: {e}", exc_info=True)
                result.errors.append(f"Flagging crashed: {e}")

        # ── Workflow 2: Resource Allocation ────────────────────────────────────
        if run_allocation:
            logger.info("Running Workflow 2: Supervision Allocation...")
            try:
                result.allocation = self.allocation_agent.run(
                    df, province=province, district=district,
                    n_supervisors=n_supervisors,
                )
                if not result.allocation.success:
                    result.errors.append(f"Allocation: {result.allocation.error}")
            except Exception as e:
                logger.error(f"Allocation agent crashed: {e}", exc_info=True)
                result.errors.append(f"Allocation crashed: {e}")

        # ── Workflow 3: Root Cause Analysis ────────────────────────────────────
        if run_root_cause:
            logger.info("Running Workflow 3: Root Cause Analysis...")
            try:
                result.root_cause = self.root_cause_agent.run(
                    df, province=province, district=district
                )
                if not result.root_cause.success:
                    result.errors.append(f"RootCause: {result.root_cause.error}")
            except Exception as e:
                logger.error(f"Root cause agent crashed: {e}", exc_info=True)
                result.errors.append(f"RootCause crashed: {e}")

        result.elapsed_seconds = time.time() - start
        result.success = len(result.errors) == 0

        logger.info(
            f"Orchestrator complete in {result.elapsed_seconds:.1f}s | "
            f"Errors: {len(result.errors)}"
        )
        return result

    def run_counselor_drill(
        self, df: pd.DataFrame, counselor: str, facility: str
    ) -> AgentResult:
        """On-demand deep dive for a specific counselor."""
        logger.info(f"Counselor drill: {counselor} at {facility}")
        return self.root_cause_agent.run(
            df, facility=facility, counselor=counselor
        )
