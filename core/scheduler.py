"""
scheduler.py
────────────
APScheduler-based weekly automation.

Runs the full analysis pipeline on a configured schedule and sends
emails automatically. Designed to be started when the Streamlit app
launches and to run in the background.

Usage in app.py (add at bottom):
    from core.scheduler import start_scheduler
    start_scheduler()
"""

import logging
import json
import os
from pathlib import Path
from datetime import datetime, date
from typing import List, Optional

logger = logging.getLogger(__name__)

# APScheduler imports — graceful fallback if not installed
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed. Scheduling disabled. Run: pip install APScheduler")

# ─── Global scheduler instance ────────────────────────────────────────────────
_scheduler: Optional["BackgroundScheduler"] = None

SCHEDULE_CONFIG_PATH = Path(__file__).parent.parent / "data" / "schedule_config.json"
DATA_DIR = Path(__file__).parent.parent / "data"


def start_scheduler():
    """
    Start the background scheduler if enabled in config.
    Call once at app startup.
    """
    global _scheduler

    if not SCHEDULER_AVAILABLE:
        return

    if _scheduler and _scheduler.running:
        return  # Already running

    _scheduler = BackgroundScheduler(timezone="Africa/Maputo")

    # Load config
    config = _load_config()
    if not config.get("enabled", False):
        logger.info("Scheduler disabled in config. Not starting.")
        return

    # Schedule weekly analysis (default: Monday 06:00)
    day_map = {
        "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed",
        "Thursday": "thu", "Friday": "fri",
    }
    analysis_day = day_map.get(config.get("analysis_day", "Monday"), "mon")

    _scheduler.add_job(
        func=_run_weekly_analysis,
        trigger=CronTrigger(day_of_week=analysis_day, hour=6, minute=0),
        id="weekly_analysis",
        name="Weekly ICT Analysis",
        replace_existing=True,
    )

    # Schedule supervisor brief delivery (Wednesday 08:00)
    _scheduler.add_job(
        func=_send_supervisor_briefs,
        trigger=CronTrigger(day_of_week="wed", hour=8, minute=0),
        id="supervisor_briefs",
        name="Supervisor Brief Delivery",
        replace_existing=True,
    )

    # Schedule central team report (Wednesday 13:00)
    _scheduler.add_job(
        func=_send_central_reports,
        trigger=CronTrigger(day_of_week="wed", hour=13, minute=0),
        id="central_reports",
        name="Central Team Report Delivery",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"Scheduler started. Jobs: {[j.id for j in _scheduler.get_jobs()]}"
    )


def stop_scheduler():
    """Gracefully stop the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


def get_scheduled_jobs() -> List[dict]:
    """Return list of scheduled jobs with next run times."""
    if not _scheduler or not _scheduler.running:
        return []
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "Not scheduled",
        }
        for job in _scheduler.get_jobs()
    ]


def schedule_weekly_report(job_id: str, cron_expression: str):
    """Add or update a scheduled job (advanced use)."""
    if not _scheduler:
        raise RuntimeError("Scheduler not running.")
    pass  # Extend as needed


def cancel_job(job_id: str) -> bool:
    """Cancel a scheduled job by ID."""
    if not _scheduler:
        return False
    try:
        _scheduler.remove_job(job_id)
        return True
    except Exception:
        return False


# ─── Scheduled task functions ─────────────────────────────────────────────────

def _run_weekly_analysis():
    """
    Run the full analysis pipeline. Called by scheduler.
    Stores result in a file for the brief-sending jobs to pick up.
    """
    logger.info("Scheduled weekly analysis starting...")
    config = _load_config()

    # Find the most recent CSV in uploads/
    upload_dir = DATA_DIR / "uploads"
    csvs = sorted(upload_dir.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not csvs:
        logger.warning("No CSV found in uploads/. Skipping scheduled analysis.")
        return

    latest_csv = csvs[0]
    logger.info(f"Using: {latest_csv.name}")

    try:
        from core.data_loader import load_csv
        from core.orchestrator import Orchestrator

        df = load_csv(latest_csv)
        orch = Orchestrator()
        result = orch.run(
            df,
            province=config.get("province_filter") or None,
            district=config.get("district_filter") or None,
        )

        # Persist result narratives for email jobs
        result_cache = DATA_DIR / "processed" / "last_analysis_result.json"
        result_cache.parent.mkdir(exist_ok=True)
        cache_data = {
            "run_at": datetime.now().isoformat(),
            "csv_file": latest_csv.name,
            "flagging_narrative": result.flagging.narrative if result.flagging else "",
            "allocation_narrative": result.allocation.narrative if result.allocation else "",
            "root_cause_narrative": result.root_cause.narrative if result.root_cause else "",
            "success": result.success,
            "errors": result.errors,
        }
        with open(result_cache, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Weekly analysis complete. Success: {result.success}")

    except Exception as e:
        logger.error(f"Scheduled analysis failed: {e}", exc_info=True)


def _send_supervisor_briefs():
    """Send supervisor PDF briefs. Called Wednesday 08:00."""
    logger.info("Sending supervisor briefs...")
    config = _load_config()
    recipients = config.get("supervisor_emails", [])
    recipients = [r for r in recipients if r]

    if not recipients:
        logger.warning("No supervisor emails configured. Skipping.")
        return

    result_cache = DATA_DIR / "processed" / "last_analysis_result.json"
    if not result_cache.exists():
        logger.warning("No cached analysis result. Run analysis first.")
        return

    with open(result_cache, encoding="utf-8") as f:
        cached = json.load(f)

    try:
        from outputs.email_dispatcher import EmailDispatcher
        dispatcher = EmailDispatcher()

        if not dispatcher.is_configured():
            logger.warning("Email not configured. Skipping supervisor brief delivery.")
            return

        # Build minimal PDF without full agent objects
        # For scheduled runs we send the narrative as plain text
        province = config.get("province_filter", "")
        district = config.get("district_filter", "")
        narrative = cached.get("flagging_narrative", "No analysis available.")

        body = f"""Caro(a) Supervisor(a),

Segue o resumo da supervisão ICT desta semana.

{narrative[:1500]}

---
Sistema de Supervisão ICT — RISE Programme / JHPIEGO
Análise gerada em: {cached.get('run_at', 'N/A')}
"""
        scope = " - ".join(filter(None, [province, district])) or "RISE ICT"
        ok = dispatcher._send(
            recipients=recipients,
            subject=f"[RISE ICT] Resumo de Supervisão — {scope} — {date.today().strftime('%d/%m/%Y')}",
            body=body,
        )
        logger.info(f"Supervisor brief sent: {ok}")

    except Exception as e:
        logger.error(f"Supervisor brief delivery failed: {e}", exc_info=True)


def _send_central_reports():
    """Send central team HTML report. Called Wednesday 13:00."""
    logger.info("Sending central team reports...")
    config = _load_config()
    recipients = config.get("central_emails", [])
    recipients = [r for r in recipients if r]

    if not recipients:
        logger.warning("No central team emails configured.")
        return

    result_cache = DATA_DIR / "processed" / "last_analysis_result.json"
    if not result_cache.exists():
        logger.warning("No cached analysis. Skipping central report.")
        return

    with open(result_cache, encoding="utf-8") as f:
        cached = json.load(f)

    try:
        from outputs.email_dispatcher import EmailDispatcher
        dispatcher = EmailDispatcher()

        if not dispatcher.is_configured():
            return

        html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<style>body{{font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px}}
h1{{color:#00539C}}.section{{background:#f5f5f5;padding:15px;border-radius:6px;margin:15px 0}}</style>
</head><body>
<h1>RISE ICT — Weekly Analysis Report</h1>
<p>Generated: {cached.get('run_at', 'N/A')} | Source: {cached.get('csv_file', 'N/A')}</p>
<div class='section'><h2>Performance Flagging</h2><pre>{cached.get('flagging_narrative','')}</pre></div>
<div class='section'><h2>Supervision Allocation</h2><pre>{cached.get('allocation_narrative','')}</pre></div>
<div class='section'><h2>Root Cause Analysis</h2><pre>{cached.get('root_cause_narrative','')}</pre></div>
</body></html>"""

        ok = dispatcher.send_central_team_report(
            recipients=recipients,
            html_content=html,
            report_date=date.today(),
            summary=cached.get("flagging_narrative", "")[:400],
        )
        logger.info(f"Central team report sent: {ok}")

    except Exception as e:
        logger.error(f"Central report delivery failed: {e}", exc_info=True)


# ─── Config helper ────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if SCHEDULE_CONFIG_PATH.exists():
        with open(SCHEDULE_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False}
