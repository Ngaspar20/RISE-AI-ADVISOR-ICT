"""
01_upload.py
────────────
Page 1: Data Upload + Quality Check

User uploads the ICT line-list CSV. System runs quality checks and
stores the clean DataFrame in session state.
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.data_loader import load_csv_from_bytes
from core.data_quality import run_quality_checks

st.set_page_config(page_title="Upload Data — RISE ICT", page_icon="📤", layout="wide")

st.markdown("## 📤 Upload ICT Line-List Data")
st.markdown("Upload the weekly DHIS2 export CSV. The system will validate it and flag any quality issues.")

# ─── File uploader ─────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "Choose CSV file (DHIS2 export)",
    type=["csv"],
    help="Upload the 'Base de Dados Principal' CSV exported from DHIS2.",
)

if uploaded_file is not None:
    with st.spinner(f"Loading and validating {uploaded_file.name}..."):
        try:
            file_bytes = uploaded_file.read()
            df = load_csv_from_bytes(file_bytes, filename=uploaded_file.name)
            quality_report = run_quality_checks(df)

            # Store in session state
            st.session_state.df = df
            st.session_state.quality_report = quality_report
            st.session_state.last_upload_filename = uploaded_file.name

        except ValueError as e:
            st.error(f"❌ Failed to load file: {e}")
            st.stop()
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            st.stop()

    # ── Success summary ────────────────────────────────────────────────────────
    st.success(f"✅ **{uploaded_file.name}** loaded successfully!")

    # KPI row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Contacts", f"{len(df):,}")
    col2.metric("Counselors", df["counselor"].nunique())
    col3.metric("Facilities", df["facility"].nunique())
    col4.metric("Districts", df["district"].nunique())
    col5.metric("Data Quality Score", f"{quality_report.score:.0f}/100")

    st.markdown("---")

    # ── Quality Report ─────────────────────────────────────────────────────────
    st.markdown("### 🔍 Data Quality Report")

    if quality_report.passed:
        st.success(f"✅ Quality check PASSED (score: {quality_report.score:.1f}/100)")
    else:
        st.error(f"❌ Quality check FAILED (score: {quality_report.score:.1f}/100) — critical issues found. Review before analysis.")

    # Issues table
    if quality_report.issues:
        for issue in quality_report.issues:
            if issue.severity == "critical":
                container = st.error
                icon = "🔴"
            elif issue.severity == "warning":
                container = st.warning
                icon = "🟡"
            else:
                container = st.info
                icon = "🔵"

            with st.expander(f"{icon} [{issue.severity.upper()}] {issue.check} — {issue.affected_rows:,} records ({issue.affected_pct:.1f}%)"):
                st.write(issue.description)
                if issue.examples:
                    st.write("**Examples:**", ", ".join(str(e) for e in issue.examples))
    else:
        st.success("No quality issues detected.")

    st.markdown("---")

    # ── Data preview ───────────────────────────────────────────────────────────
    st.markdown("### 👀 Data Preview")

    province_filter = st.selectbox(
        "Filter preview by Province",
        ["All"] + sorted(df["province"].dropna().unique().tolist()),
    )

    preview_df = df if province_filter == "All" else df[df["province"] == province_filter]

    display_cols = [
        "province", "district", "facility", "counselor",
        "contact_type", "contact_age", "contact_sex",
        "consented", "was_tested", "is_positive", "is_linked",
        "linkage", "test_result",
    ]
    display_cols = [c for c in display_cols if c in preview_df.columns]

    st.dataframe(
        preview_df[display_cols].head(100),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Showing first 100 of {len(preview_df):,} records for selected province.")

    # ── Navigate to analysis ───────────────────────────────────────────────────
    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📊 Go to Dashboard →", use_container_width=True):
            st.switch_page("ui/pages/02_dashboard.py")
    with col_b:
        if st.button("🤖 Run AI Analysis →", use_container_width=True, type="primary"):
            st.switch_page("ui/pages/03_analysis.py")

elif st.session_state.df is not None:
    st.info(
        f"✅ Data already loaded: **{st.session_state.last_upload_filename}** "
        f"({len(st.session_state.df):,} records). Upload a new file to replace it."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📊 Go to Dashboard →", use_container_width=True):
            st.switch_page("ui/pages/02_dashboard.py")
    with col_b:
        if st.button("🤖 Run AI Analysis →", use_container_width=True, type="primary"):
            st.switch_page("ui/pages/03_analysis.py")
else:
    st.info("👆 Please upload a CSV file to begin.")
    st.markdown("""
    **Expected format:** DHIS2 ICT line-list export (CSV, latin-1 encoding)

    **Required columns include:**
    - Provincia, Distrito, US (facility)
    - HIV - Conselheiro (a) (counselor name)
    - HIV - Resultado do teste (test result)
    - HIV - Ligação a unidade sanitária (linkage)
    - HIV - Contacto consente referencia/testagem (consent)
    - HIV - Data de Testagem (test date)
    """)
