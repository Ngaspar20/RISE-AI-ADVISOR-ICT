"""
03_analysis.py
──────────────
Page 3: AI Analysis Hub

Run all 3 agent workflows. View narratives, download PDFs, on-demand counselor drills.
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.orchestrator import Orchestrator
from outputs.pdf_generator import generate_supervisor_brief
from tools.claude_client import is_configured as api_configured

st.set_page_config(page_title="AI Analysis — RISE ICT", page_icon="🤖", layout="wide")

# ─── Guard ─────────────────────────────────────────────────────────────────────
if st.session_state.get("df") is None:
    st.warning("⚠️ No data loaded. Please upload a CSV first.")
    if st.button("→ Go to Upload"):
        st.switch_page("ui/pages/01_upload.py")
    st.stop()

df_full = st.session_state.df

st.markdown("## 🤖 AI Analysis — Three Workflows")

if not api_configured():
    st.warning(
        "⚠️ **Claude API not configured.** Analysis will run without AI narrative generation. "
        "Add `ANTHROPIC_API_KEY` to your `.env` file for full functionality."
    )

# ─── Controls ──────────────────────────────────────────────────────────────────
st.markdown("### Analysis Settings")

col1, col2, col3 = st.columns(3)
with col1:
    provinces = ["All"] + sorted(df_full["province"].dropna().unique().tolist())
    sel_province = st.selectbox("Province", provinces)

with col2:
    df_prov = df_full if sel_province == "All" else df_full[df_full["province"] == sel_province]
    districts = ["All"] + sorted(df_prov["district"].dropna().unique().tolist())
    sel_district = st.selectbox("District", districts)

with col3:
    n_supervisors = st.number_input("Available Supervisors", min_value=1, max_value=10, value=2)

col_w1, col_w2, col_w3 = st.columns(3)
run_flagging = col_w1.checkbox("✅ Workflow 1: Performance Flagging", value=True)
run_allocation = col_w2.checkbox("✅ Workflow 2: Supervision Allocation", value=True)
run_rca = col_w3.checkbox("✅ Workflow 3: Root Cause Analysis", value=True)

st.markdown("---")

# ─── Run analysis button ───────────────────────────────────────────────────────
if st.button("🚀 Run Analysis", type="primary", use_container_width=True):
    prov_filter = None if sel_province == "All" else sel_province
    dist_filter = None if sel_district == "All" else sel_district

    with st.spinner("Running analysis... (this may take 30–90 seconds with Claude API)"):
        orch = Orchestrator()
        result = orch.run(
            df_full,
            province=prov_filter,
            district=dist_filter,
            run_flagging=run_flagging,
            run_allocation=run_allocation,
            run_root_cause=run_rca,
            n_supervisors=int(n_supervisors),
        )
        st.session_state.orch_result = result

    if result.success:
        st.success(f"✅ Analysis complete in {result.elapsed_seconds:.1f}s")
    else:
        st.warning(f"⚠️ Analysis completed with errors: {result.errors}")

# ─── Show results ──────────────────────────────────────────────────────────────
result = st.session_state.get("orch_result")

if result is None:
    st.info("Click **Run Analysis** to generate AI-powered supervision insights.")
    st.stop()

# ── Tabs for each workflow ──────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🚦 Workflow 1: Flagging",
    "📅 Workflow 2: Allocation",
    "🔍 Workflow 3: Root Cause",
    "📋 Counselor Drill",
])

# ── Tab 1: Flagging ────────────────────────────────────────────────────────────
with tab1:
    if result.flagging is None:
        st.info("Flagging workflow was not run.")
    elif not result.flagging.success:
        st.error(f"Flagging failed: {result.flagging.error}")
    else:
        fr = result.flagging
        data = fr.data

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Contacts Analysed", f"{data.get('n_contacts', 0):,}")
        col2.metric("Counselors", data.get("n_counselors", 0))
        col3.metric("Facilities", data.get("n_facilities", 0))
        col4.metric("Red Flags", len(data.get("counselor_flags", [])) + len(data.get("facility_flags", [])))

        st.markdown("---")

        # Facility flags
        fac_flags = data.get("facility_flags", pd.DataFrame())
        if not fac_flags.empty:
            st.markdown("#### 🔴 Facility Flags (Systemic Issues)")
            for _, row in fac_flags.iterrows():
                icon = "🔴" if row.get("severity") == "red" else "🟡"
                st.markdown(f"""
                <div style='background:#FFF5F5;border-left:4px solid #DC3545;padding:0.7rem;border-radius:4px;margin:0.3rem 0'>
                <b>{icon} {row['facility']}</b> ({row.get('district', '')}) —
                Linkage: <b>{row.get('median_linkage_rate', 'N/A'):.1f}%</b>
                (district median: {row.get('district_median_linkage_rate', 'N/A'):.1f}%) |
                Contacts: {int(row.get('n_contacts_total', 0))}
                </div>
                """, unsafe_allow_html=True)

        # Counselor flags
        coun_flags = data.get("counselor_flags", pd.DataFrame())
        if not coun_flags.empty:
            st.markdown("#### 🔴 Counselor Flags")
            for _, row in coun_flags.iterrows():
                icon = "🔴" if row.get("severity") == "red" else "🟡"
                st.markdown(f"""
                <div style='background:#FFFBF0;border-left:4px solid #FFC107;padding:0.7rem;border-radius:4px;margin:0.3rem 0'>
                <b>{icon} {row['counselor']}</b> at {row.get('facility', '')} ({row.get('district', '')}) —
                Linkage: <b>{row.get('linkage_rate', 0):.1f}%</b>
                (facility median: {row.get('facility_median_linkage_rate', 0):.1f}%) |
                Consent: {row.get('consent_rate', 0):.1f}% |
                Contacts: {int(row.get('n_contacts', 0))}
                </div>
                """, unsafe_allow_html=True)

        # AI Narrative
        if fr.narrative:
            st.markdown("---")
            st.markdown("#### 🤖 AI-Generated Supervision Brief")
            st.markdown(fr.narrative)

        # PDF Download
        st.markdown("---")
        st.markdown("#### 📄 Download Supervisor Brief (PDF)")
        if st.button("Generate PDF Brief", key="gen_pdf"):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_bytes = generate_supervisor_brief(
                        flagging_result=result.flagging,
                        allocation_result=result.allocation,
                        province=sel_province if sel_province != "All" else "",
                        district=sel_district if sel_district != "All" else "",
                        report_date=date.today(),
                        narrative_summary=fr.narrative[:500],
                    )
                    st.download_button(
                        label="⬇️ Download PDF",
                        data=pdf_bytes,
                        file_name=f"RISE_ICT_Brief_{date.today().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                    )
                except Exception as e:
                    st.error(f"PDF generation failed: {e}")


# ── Tab 2: Allocation ──────────────────────────────────────────────────────────
with tab2:
    if result.allocation is None:
        st.info("Allocation workflow was not run.")
    elif not result.allocation.success:
        st.error(f"Allocation failed: {result.allocation.error}")
    else:
        ar = result.allocation
        triage = ar.data.get("triage", {})

        col1, col2, col3 = st.columns(3)
        col1.metric("🔴 Visit This Week", ar.data.get("n_red", 0))
        col2.metric("🟡 Schedule This Month", ar.data.get("n_yellow", 0))
        col3.metric("🟢 On Track", ar.data.get("n_green", 0))

        # Triage tables
        for severity, label, color in [
            ("red", "🔴 Visit This Week — CRITICAL", "#FFF5F5"),
            ("yellow", "🟡 Schedule This Month — CAUTION", "#FFFBF0"),
            ("green", "🟢 On Track — Quarterly Visit", "#F0FFF4"),
        ]:
            entries = triage.get(severity, [])
            if entries:
                st.markdown(f"#### {label}")
                for e in entries:
                    from tools.compute_metrics import format_pct
                    st.markdown(f"""
                    <div style='background:{color};padding:0.6rem;border-radius:4px;margin:0.2rem 0'>
                    <b>{e['facility']}</b> ({e['district']}) —
                    Linkage: {format_pct(e.get('linkage_rate', float('nan')))} |
                    Flagged counselors: {e.get('n_flagged_counselors', 0)}/{e.get('n_counselors', 0)} |
                    <i>{e.get('suggested_visit_type', '')}</i>
                    </div>
                    """, unsafe_allow_html=True)

        # AI narrative
        if ar.narrative:
            st.markdown("---")
            st.markdown("#### 🤖 AI-Generated Supervision Plan")
            st.markdown(ar.narrative)


# ── Tab 3: Root Cause ──────────────────────────────────────────────────────────
with tab3:
    if result.root_cause is None:
        st.info("Root cause workflow was not run.")
    elif not result.root_cause.success:
        st.error(f"Root cause failed: {result.root_cause.error}")
    else:
        rc = result.root_cause
        pipeline = rc.data.get("pipeline", {})

        # Pipeline waterfall
        if pipeline:
            st.markdown("#### Linkage Pipeline — Where Is the Gap?")
            steps = [
                ("Total Contacts", pipeline.get("n_total", 0)),
                ("Eligible", pipeline.get("n_eligible", 0)),
                ("Consented", pipeline.get("n_consented", 0)),
                ("Tested", pipeline.get("n_tested", 0)),
                ("HIV+", pipeline.get("n_positive", 0)),
                ("Linked", pipeline.get("n_linked", 0)),
            ]
            labels = [s[0] for s in steps]
            values = [s[1] for s in steps]

            import plotly.graph_objects as go
            fig = go.Figure(go.Funnel(
                y=labels, x=values,
                textposition="inside",
                textinfo="value+percent initial",
                marker=dict(color=["#00539C", "#0077CC", "#28A745", "#FFC107", "#FF851B", "#DC3545"]),
            ))
            fig.update_layout(title="ICT Cascade (Linkage Pipeline)", height=350)
            st.plotly_chart(fig, use_container_width=True)

            col1, col2, col3 = st.columns(3)
            from tools.compute_metrics import format_pct
            col1.metric("Consent Rate", format_pct(pipeline.get("consent_rate")))
            col2.metric("Testing Completion", format_pct(pipeline.get("testing_completion")))
            col3.metric("Linkage Rate (HIV+)", format_pct(pipeline.get("linkage_rate")))

        # AI narrative
        if rc.narrative:
            st.markdown("---")
            st.markdown("#### 🤖 AI Root Cause Analysis")
            st.markdown(rc.narrative)


# ── Tab 4: Counselor Drill ────────────────────────────────────────────────────
with tab4:
    st.markdown("### On-Demand Counselor Deep Dive")
    st.markdown("Select a specific counselor for a focused coaching brief.")

    counselors = sorted(df_full["counselor"].dropna().unique().tolist())
    sel_counselor = st.selectbox("Select Counselor", counselors)

    if sel_counselor:
        # Get counselor's facility
        coun_row = df_full[df_full["counselor"] == sel_counselor]
        facility = coun_row["facility"].mode()[0] if len(coun_row) > 0 else ""
        st.caption(f"Facility: {facility} | Contacts: {len(coun_row):,}")

        if st.button("🔍 Run Counselor Analysis", type="primary"):
            with st.spinner(f"Analysing {sel_counselor}..."):
                orch = Orchestrator()
                drill_result = orch.run_counselor_drill(df_full, sel_counselor, facility)
                st.session_state[f"drill_{sel_counselor}"] = drill_result

        drill = st.session_state.get(f"drill_{sel_counselor}")
        if drill and drill.success:
            pipeline = drill.data.get("pipeline", {})
            if pipeline:
                from tools.compute_metrics import format_pct
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Contacts", pipeline.get("n_total", 0))
                col2.metric("Consent Rate", format_pct(pipeline.get("consent_rate")))
                col3.metric("Linkage Rate", format_pct(pipeline.get("linkage_rate")))
                col4.metric("Unlinked HIV+", pipeline.get("n_unlinked", 0))

            if drill.narrative:
                st.markdown("#### 🤖 Coaching Brief")
                st.markdown(drill.narrative)
