"""
02_dashboard.py
───────────────
Page 2: Interactive Performance Dashboard

Drill-down: District → Facility → Counselor
Charts: Heatmaps, bar charts, trend lines, traffic lights
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.compute_metrics import (
    compute_counselor_metrics, compute_facility_metrics,
    compute_district_metrics, compute_weekly_trends,
    stratify_by_contact_type, stratify_by_age_group,
    flag_counselors, flag_facilities,
    format_pct, traffic_light,
)

st.set_page_config(page_title="Dashboard — RISE ICT", page_icon="📊", layout="wide")

# ─── Guard: require data ───────────────────────────────────────────────────────
if st.session_state.get("df") is None:
    st.warning("⚠️ No data loaded. Please upload a CSV first.")
    if st.button("→ Go to Upload"):
        st.switch_page("ui/pages/01_upload.py")
    st.stop()

df_full = st.session_state.df

# ─── Filters sidebar ──────────────────────────────────────────────────────────
st.sidebar.markdown("### 🔽 Filters")

provinces = ["All"] + sorted(df_full["province"].dropna().unique().tolist())
sel_province = st.sidebar.selectbox("Province", provinces)

df_prov = df_full if sel_province == "All" else df_full[df_full["province"] == sel_province]

districts = ["All"] + sorted(df_prov["district"].dropna().unique().tolist())
sel_district = st.sidebar.selectbox("District", districts)

df_filtered = df_prov if sel_district == "All" else df_prov[df_prov["district"] == sel_district]

st.sidebar.markdown("---")
view_level = st.sidebar.radio("View Level", ["District", "Facility", "Counselor"], index=0)

# ─── Header ───────────────────────────────────────────────────────────────────
scope = " → ".join(filter(lambda x: x != "All", [sel_province, sel_district])) or "All Provinces"
st.markdown(f"## 📊 Performance Dashboard: {scope}")
st.markdown(f"*{len(df_filtered):,} contacts | {df_filtered['counselor'].nunique()} counselors | {df_filtered['facility'].nunique()} facilities*")

# ─── KPI Summary Row ──────────────────────────────────────────────────────────
st.markdown("### Key Metrics")

n_pos = df_filtered["is_positive"].sum()
n_linked = df_filtered[df_filtered["is_positive"]]["is_linked"].sum()
n_consented = df_filtered["consented"].sum()
n_eligible = df_filtered["eligible_bool"].sum()
n_tested = df_filtered["was_tested"].sum()

linkage_pct = n_linked / n_pos * 100 if n_pos > 0 else 0
consent_pct = n_consented / n_eligible * 100 if n_eligible > 0 else 0
positivity_pct = n_pos / n_tested * 100 if n_tested > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔗 Linkage Rate", f"{linkage_pct:.1f}%", help="% of HIV+ contacts linked to care (target ≥85%)")
c2.metric("✅ Consent Rate", f"{consent_pct:.1f}%", help="% of eligible contacts consenting to test (target ≥90%)")
c3.metric("🦠 Test Positivity", f"{positivity_pct:.1f}%", help="% of tested contacts HIV+")
c4.metric("👥 Contacts Tested", f"{int(n_tested):,}")
c5.metric("🔴 HIV+ Unlinked", f"{int(n_pos - n_linked):,}", delta=f"-{int(n_pos-n_linked)} gap", delta_color="inverse")

st.markdown("---")

# ─── District Level View ──────────────────────────────────────────────────────
if view_level == "District":
    dist_df = compute_district_metrics(df_filtered)

    if dist_df.empty:
        st.info("No district metrics available for current selection.")
        st.stop()

    st.markdown("### District Performance Overview")

    metrics_to_show = {
        "district_median_linkage_rate": "Linkage Rate (%)",
        "district_median_consent_rate": "Consent Rate (%)",
        "district_median_test_positivity": "Test Positivity (%)",
        "n_contacts_total": "Total Contacts",
    }

    display_dist = dist_df[["district", "province"] + list(metrics_to_show.keys())].copy()
    display_dist.columns = ["District", "Province"] + list(metrics_to_show.values())

    # Add traffic lights
    display_dist["Linkage 🚦"] = display_dist.apply(
        lambda r: "🔴" if r["Linkage Rate (%)"] < 70
        else "🟡" if r["Linkage Rate (%)"] < 85
        else "🟢", axis=1
    )

    st.dataframe(display_dist.round(1), use_container_width=True, hide_index=True)

    # Bar chart
    if len(dist_df) > 0:
        fig = px.bar(
            dist_df.sort_values("district_median_linkage_rate"),
            x="district",
            y="district_median_linkage_rate",
            color="district_median_linkage_rate",
            color_continuous_scale=["#DC3545", "#FFC107", "#28A745"],
            range_color=[50, 100],
            title="District Median Linkage Rate",
            labels={"district_median_linkage_rate": "Linkage Rate (%)", "district": "District"},
        )
        fig.add_hline(y=85, line_dash="dash", line_color="green", annotation_text="Target 85%")
        fig.add_hline(y=70, line_dash="dot", line_color="red", annotation_text="Alert 70%")
        fig.update_layout(height=350, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# ─── Facility Level View ──────────────────────────────────────────────────────
elif view_level == "Facility":
    fac_flagged = flag_facilities(df_filtered)

    if fac_flagged.empty:
        st.info("No facility metrics available.")
        st.stop()

    st.markdown("### Facility Performance vs District Median")
    st.markdown("*🔴 ≥10% below district median | 🟡 caution | 🟢 on track*")

    # Colour-coded table
    display_fac = fac_flagged[[
        "facility", "district", "n_contacts_total", "n_counselors",
        "median_linkage_rate", "median_consent_rate", "median_test_positivity",
        "severity", "flags"
    ]].copy()
    display_fac.columns = [
        "Facility", "District", "Contacts", "Counselors",
        "Linkage (%)", "Consent (%)", "Positivity (%)",
        "Status", "Flags"
    ]
    display_fac["Status"] = display_fac["Status"].map(
        {"red": "🔴 Critical", "yellow": "🟡 Caution", "green": "🟢 On Track"}
    )
    st.dataframe(display_fac.round(1), use_container_width=True, hide_index=True)

    # Scatter: facility linkage vs district median
    if "district_median_linkage_rate" in fac_flagged.columns:
        fig = px.scatter(
            fac_flagged,
            x="district_median_linkage_rate",
            y="median_linkage_rate",
            color="severity",
            color_discrete_map={"red": "#DC3545", "yellow": "#FFC107", "green": "#28A745"},
            hover_name="facility",
            hover_data={"district": True, "n_contacts_total": True, "severity": False},
            title="Facility vs District Median Linkage Rate",
            labels={
                "district_median_linkage_rate": "District Median Linkage (%)",
                "median_linkage_rate": "Facility Median Linkage (%)",
            },
        )
        # Reference line
        max_val = max(
            fac_flagged["district_median_linkage_rate"].max(),
            fac_flagged["median_linkage_rate"].max(),
        )
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines", line=dict(dash="dash", color="gray"),
            name="Parity line", showlegend=True,
        ))
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

# ─── Counselor Level View ─────────────────────────────────────────────────────
elif view_level == "Counselor":
    coun_flagged = flag_counselors(df_filtered)

    if coun_flagged.empty:
        st.info("No counselor metrics available.")
        st.stop()

    # Facility drill-down filter
    facilities = ["All"] + sorted(coun_flagged["facility"].dropna().unique().tolist())
    sel_facility = st.selectbox("Drill into Facility", facilities)

    if sel_facility != "All":
        display_coun = coun_flagged[coun_flagged["facility"] == sel_facility]
    else:
        display_coun = coun_flagged

    st.markdown(f"### Counselor Performance — {sel_facility if sel_facility != 'All' else 'All Facilities'}")
    st.markdown("*Compared to their facility median. 🔴 = ≥10% below median.*")

    cols_to_show = [
        "counselor", "facility", "district", "n_contacts",
        "linkage_rate", "facility_median_linkage_rate",
        "consent_rate", "facility_median_consent_rate",
        "test_positivity", "severity", "flags"
    ]
    cols_to_show = [c for c in cols_to_show if c in display_coun.columns]
    disp = display_coun[cols_to_show].copy()
    disp["severity"] = disp["severity"].map(
        {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    ).fillna("⚪")
    st.dataframe(disp.round(1), use_container_width=True, hide_index=True)

    # Bar chart: counselor linkage rates within selected facility
    if sel_facility != "All" and len(display_coun) > 0:
        fig = px.bar(
            display_coun.sort_values("linkage_rate"),
            x="counselor", y="linkage_rate",
            color="severity",
            color_discrete_map={"red": "#DC3545", "yellow": "#FFC107", "green": "#28A745"},
            title=f"Counselor Linkage Rates — {sel_facility}",
            labels={"linkage_rate": "Linkage Rate (%)", "counselor": "Counselor"},
        )
        if "facility_median_linkage_rate" in display_coun.columns:
            median_val = display_coun["facility_median_linkage_rate"].iloc[0]
            if not np.isnan(median_val):
                fig.add_hline(y=median_val, line_dash="dash",
                              annotation_text=f"Facility Median {median_val:.1f}%")
        fig.update_layout(height=350, xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

# ─── Weekly Trend ─────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📈 Weekly Trends")

weekly = compute_weekly_trends(df_filtered, level="district" if sel_district == "All" else "facility")

if not weekly.empty and "week" in weekly.columns and "linkage_rate" in weekly.columns:
    group_col = "district" if "district" in weekly.columns and sel_district == "All" else "facility"
    if group_col in weekly.columns:
        fig = px.line(
            weekly,
            x="week", y="linkage_rate",
            color=group_col,
            title="Weekly Linkage Rate Trend",
            labels={"linkage_rate": "Linkage Rate (%)", "week": "Week"},
            markers=True,
        )
        fig.add_hline(y=85, line_dash="dash", line_color="green", annotation_text="Target 85%")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Weekly trend data not available (requires test_date column).")

# ─── Contact type breakdown ───────────────────────────────────────────────────
st.markdown("---")
col_ct, col_age = st.columns(2)

with col_ct:
    st.markdown("### Contact Type Analysis")
    ct_df = stratify_by_contact_type(df_filtered)
    if not ct_df.empty:
        fig = px.bar(
            ct_df.sort_values("n_contacts", ascending=True),
            x="linkage_rate", y="contact_type",
            orientation="h",
            color="linkage_rate",
            color_continuous_scale=["#DC3545", "#FFC107", "#28A745"],
            range_color=[0, 100],
            title="Linkage Rate by Contact Type",
            labels={"linkage_rate": "Linkage Rate (%)", "contact_type": ""},
            text="linkage_rate",
        )
        fig.update_traces(texttemplate="%{text:.1f}%")
        fig.add_vline(x=85, line_dash="dash", line_color="green")
        fig.update_layout(height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

with col_age:
    st.markdown("### Age Group Analysis")
    age_df = stratify_by_age_group(df_filtered)
    if not age_df.empty:
        fig = px.bar(
            age_df,
            x="age_group", y="linkage_rate",
            color="linkage_rate",
            color_continuous_scale=["#DC3545", "#FFC107", "#28A745"],
            range_color=[0, 100],
            title="Linkage Rate by Age Group",
            labels={"linkage_rate": "Linkage Rate (%)", "age_group": "Age Group"},
            text="linkage_rate",
        )
        fig.update_traces(texttemplate="%{text:.1f}%")
        fig.add_hline(y=85, line_dash="dash", line_color="green")
        fig.update_layout(height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
