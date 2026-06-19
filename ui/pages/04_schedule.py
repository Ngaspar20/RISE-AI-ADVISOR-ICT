"""
04_schedule.py
──────────────
Page 4: Automated Reports & Email Schedule

Configure weekly automated report delivery.
Send manual reports on-demand.
Test email configuration.
"""

import streamlit as st
import os
import json
from datetime import date, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from outputs.email_dispatcher import EmailDispatcher
from outputs.pdf_generator import generate_supervisor_brief
from core.scheduler import get_scheduled_jobs, schedule_weekly_report, cancel_job

st.set_page_config(page_title="Reports & Schedule — RISE ICT", page_icon="📧", layout="wide")

st.markdown("## 📧 Automated Reports & Email Schedule")

dispatcher = EmailDispatcher()

# ─── Email configuration status ───────────────────────────────────────────────
st.markdown("### Email Configuration")

if dispatcher.is_configured():
    st.success(f"✅ Email configured: {dispatcher.user} → {dispatcher.host}:{dispatcher.port}")
else:
    st.error(
        "❌ Email not configured. Add `EMAIL_USER` and `EMAIL_PASSWORD` to your `.env` file.\n\n"
        "For Office 365: `EMAIL_HOST=smtp.office365.com` | `EMAIL_PORT=587`"
    )

# Test email button
with st.expander("🔧 Test Email Configuration"):
    test_recipient = st.text_input("Send test email to:", value=os.getenv("EMAIL_USER", ""))
    if st.button("Send Test Email"):
        if not dispatcher.is_configured():
            st.error("Email not configured.")
        elif not test_recipient:
            st.warning("Enter a recipient email address.")
        else:
            with st.spinner("Sending test email..."):
                ok = dispatcher.send_test_email(test_recipient)
            if ok:
                st.success(f"✅ Test email sent to {test_recipient}")
            else:
                st.error("❌ Email failed. Check EMAIL_HOST, EMAIL_USER, EMAIL_PASSWORD in .env")

st.markdown("---")

# ─── Manual report delivery ───────────────────────────────────────────────────
st.markdown("### 📤 Send Report Now")

if st.session_state.get("df") is None:
    st.warning("⚠️ No data loaded. Upload a CSV first to generate reports.")
else:
    result = st.session_state.get("orch_result")

    col1, col2 = st.columns(2)

    # Supervisor Brief
    with col1:
        st.markdown("#### 📄 Supervisor Brief (PDF)")
        sup_emails_raw = st.text_area(
            "Supervisor email addresses (one per line)",
            value=os.getenv("SUPERVISOR_EMAILS", "").replace(",", "\n"),
            height=100,
        )
        sup_emails = [e.strip() for e in sup_emails_raw.splitlines() if e.strip()]

        sup_province = st.text_input("Province (for subject line)", value="MANICA")
        sup_district = st.text_input("District (for subject line)", value="")

        if st.button("📨 Send Supervisor Brief", use_container_width=True):
            if not sup_emails:
                st.warning("Enter at least one supervisor email.")
            elif not dispatcher.is_configured():
                st.error("Email not configured.")
            elif result is None:
                st.warning("Run AI Analysis first to generate a brief.")
            else:
                with st.spinner("Generating PDF and sending..."):
                    pdf_bytes = generate_supervisor_brief(
                        flagging_result=result.flagging,
                        allocation_result=result.allocation,
                        province=sup_province,
                        district=sup_district,
                        report_date=date.today(),
                        narrative_summary=result.flagging.narrative[:500] if result.flagging else "",
                    )
                    ok = dispatcher.send_supervisor_brief(
                        recipients=sup_emails,
                        pdf_bytes=pdf_bytes,
                        province=sup_province,
                        district=sup_district,
                        report_date=date.today(),
                        narrative_summary=result.flagging.narrative[:300] if result.flagging else "",
                    )
                if ok:
                    st.success(f"✅ Supervisor brief sent to: {', '.join(sup_emails)}")
                else:
                    st.error("❌ Email failed. Check configuration.")

    # Central Team Report
    with col2:
        st.markdown("#### 📊 Central Team Report (HTML)")
        central_emails_raw = st.text_area(
            "Central team email addresses (one per line)",
            value=os.getenv("CENTRAL_TEAM_EMAILS", "").replace(",", "\n"),
            height=100,
        )
        central_emails = [e.strip() for e in central_emails_raw.splitlines() if e.strip()]

        if st.button("📨 Send Central Team Report", use_container_width=True):
            if not central_emails:
                st.warning("Enter at least one central team email.")
            elif not dispatcher.is_configured():
                st.error("Email not configured.")
            elif result is None:
                st.warning("Run AI Analysis first.")
            else:
                # Build a simple HTML summary
                narrative = result.flagging.narrative if result.flagging else "No analysis available."
                html_content = f"""
<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>RISE ICT Dashboard</title>
<style>body{{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px}}
h1{{color:#00539C}}h2{{color:#333}}pre{{background:#f5f5f5;padding:10px;border-radius:4px}}</style>
</head><body>
<h1>RISE ICT — Weekly Analysis Report</h1>
<p><strong>Date:</strong> {date.today().strftime('%d %B %Y')}</p>
<hr>
<h2>Performance Flagging</h2>
<pre>{narrative}</pre>
{'<h2>Root Cause Analysis</h2><pre>' + result.root_cause.narrative + '</pre>' if result.root_cause and result.root_cause.narrative else ''}
</body></html>
"""
                with st.spinner("Sending central team report..."):
                    ok = dispatcher.send_central_team_report(
                        recipients=central_emails,
                        html_content=html_content,
                        report_date=date.today(),
                        summary=narrative[:400],
                    )
                if ok:
                    st.success(f"✅ Central team report sent to: {', '.join(central_emails)}")
                else:
                    st.error("❌ Email failed.")

    # PDF download fallback
    if result is not None:
        st.markdown("---")
        st.markdown("#### ⬇️ Download PDF (no email required)")
        if st.button("Generate & Download PDF Brief"):
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_supervisor_brief(
                    flagging_result=result.flagging,
                    allocation_result=result.allocation,
                    province=sup_province,
                    district=sup_district,
                    report_date=date.today(),
                )
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name=f"RISE_ICT_Brief_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )

st.markdown("---")

# ─── Weekly schedule configuration ───────────────────────────────────────────
st.markdown("### ⏰ Automated Weekly Schedule")
st.info(
    "The scheduler runs the full analysis pipeline automatically each Monday at 06:00 AM "
    "and sends reports on Wednesday AM (supervisors) and Wednesday PM (central team). "
    "The Streamlit app must be running for the scheduler to execute."
)

# Load current schedule config
schedule_config_path = Path(__file__).parent.parent.parent / "data" / "schedule_config.json"
schedule_config_path.parent.mkdir(exist_ok=True)

default_config = {
    "enabled": False,
    "supervisor_emails": os.getenv("SUPERVISOR_EMAILS", "").split(","),
    "central_emails": os.getenv("CENTRAL_TEAM_EMAILS", "").split(","),
    "province_filter": "",
    "district_filter": "",
    "analysis_day": "Monday",
    "brief_day": "Wednesday",
}

if schedule_config_path.exists():
    with open(schedule_config_path) as f:
        config = json.load(f)
else:
    config = default_config

col_s1, col_s2 = st.columns(2)

with col_s1:
    enabled = st.toggle("Enable weekly automated reports", value=config.get("enabled", False))
    analysis_day = st.selectbox(
        "Run analysis on",
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        index=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(
            config.get("analysis_day", "Monday")
        ),
    )
    province_filter = st.text_input(
        "Province filter (leave blank for all)",
        value=config.get("province_filter", ""),
    )

with col_s2:
    sched_sup_emails = st.text_area(
        "Supervisor email list",
        value="\n".join(config.get("supervisor_emails", [])),
        height=80,
    )
    sched_central_emails = st.text_area(
        "Central team email list",
        value="\n".join(config.get("central_emails", [])),
        height=80,
    )

if st.button("💾 Save Schedule Configuration", type="primary"):
    new_config = {
        "enabled": enabled,
        "supervisor_emails": [e.strip() for e in sched_sup_emails.splitlines() if e.strip()],
        "central_emails": [e.strip() for e in sched_central_emails.splitlines() if e.strip()],
        "province_filter": province_filter,
        "district_filter": "",
        "analysis_day": analysis_day,
        "brief_day": "Wednesday",
    }
    with open(schedule_config_path, "w") as f:
        json.dump(new_config, f, indent=2)
    st.success("✅ Schedule configuration saved.")

st.markdown("---")
st.markdown("### 📋 Scheduled Jobs")

try:
    jobs = get_scheduled_jobs()
    if jobs:
        for job in jobs:
            st.markdown(f"- **{job['id']}**: next run at `{job['next_run']}`")
    else:
        st.info("No scheduled jobs currently active. Enable the schedule above and restart the app.")
except Exception:
    st.info("Scheduler not yet running (start the app to activate).")
