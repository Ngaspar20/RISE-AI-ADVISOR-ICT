# RISE AI Technical Advisor Platform

AI-powered supervision intelligence for the JHPIEGO RISE Index Case Testing (ICT) programme in Mozambique (Zambézia & Manica provinces).

## What it does

- **Performance Flagging** — Two-level hierarchical benchmarking: counselor vs. facility median, facility vs. district median. Flags anyone ≥10% below their reference group.
- **Supervision Allocation** — Triages facilities into Red/Yellow/Green and generates a weekly visit schedule prioritised by severity.
- **Root Cause Analysis** — Breaks down the linkage cascade (eligible → consented → tested → HIV+ → linked) to pinpoint where gaps occur.
- **Automated Reports** — Weekly PDF supervisor briefs and email delivery via Office 365.

## Quick start (local)

```bash
git clone <repo>
cd rise_ai_advisor
pip install -r requirements.txt
cp .env.example .env          # add your keys
streamlit run app.py
```

## Streamlit Community Cloud deployment

1. Push repo to GitHub (`.env` and `secrets.toml` are gitignored).
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → select repo, branch `main`, file `rise_ai_advisor/app.py`.
3. In **Advanced settings → Secrets**, paste the contents of `.streamlit/secrets.toml` with real values:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
EMAIL_HOST        = "smtp.office365.com"
EMAIL_PORT        = "587"
EMAIL_USER        = "you@jhpiego.org"
EMAIL_PASSWORD    = "your_password"
EMAIL_FROM        = "you@jhpiego.org"
SUPERVISOR_EMAILS = "supervisor1@jhpiego.org,supervisor2@jhpiego.org"
CENTRAL_TEAM_EMAILS = "ngaspar10@gmail.com"
CLAUDE_MODEL      = "claude-3-5-sonnet-20241022"
```

4. Click **Deploy**.

> **Note**: APScheduler runs in-process. On Streamlit Cloud the scheduler only runs while a browser session is active. For fully unattended weekly delivery, set up a GitHub Action or cron job that POSTs to the Streamlit app's `/run_analysis` endpoint, or use an external task runner.

## Environment variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (optional — app runs in fallback mode without it) |
| `EMAIL_HOST` | SMTP host (default: smtp.office365.com) |
| `EMAIL_PORT` | SMTP port (default: 587) |
| `EMAIL_USER` | Sender email address |
| `EMAIL_PASSWORD` | Sender password / app password |
| `EMAIL_FROM` | From address (usually same as USER) |
| `SUPERVISOR_EMAILS` | Comma-separated supervisor email list |
| `CENTRAL_TEAM_EMAILS` | Comma-separated central team email list |
| `CLAUDE_MODEL` | Claude model ID (default: claude-3-5-sonnet-20241022) |

## Data format

Upload the DHIS2 ICT line-list CSV exported from the national DHIS2 instance. Expected encoding: latin-1 (CP1252). The loader also accepts UTF-8 with BOM.

Required columns (Portuguese DHIS2 names):

| Internal name | CSV column |
|---|---|
| province | Provincia |
| district | Distrito |
| facility | US |
| counselor | HIV - Conselheiro (a) |
| test_result | HIV - Resultado do teste |
| contact_consent | HIV - Contacto consente referencia/testagem |
| eligible | HIV - Elegível a testagem |
| linkage | HIV - Ligação a unidade sanitária |

All column mappings are editable in `config.yaml`.

## Performance thresholds

Editable in `config.yaml → thresholds`:

| Metric | Target | Flag threshold |
|---|---|---|
| Linkage rate | ≥ 85% | ≥ 10% below facility/district median |
| Consent rate | ≥ 90% | ≥ 10% below facility/district median |
| Testing completion | ≥ 95% | ≥ 10% below facility/district median |
| Turnaround days | ≤ 3 days | — |

## Project structure

```
rise_ai_advisor/
├── app.py                  # Streamlit entry point
├── config.yaml             # All thresholds, column maps, schedule settings
├── requirements.txt
├── .env.example
├── .streamlit/
│   ├── config.toml         # JHPIEGO theme
│   └── secrets.toml        # (gitignored) — add real values here
├── core/
│   ├── data_loader.py      # CSV ingestion + derived columns
│   ├── data_quality.py     # 7-check quality gate
│   └── orchestrator.py     # Agent coordinator
├── agents/
│   ├── base_agent.py
│   ├── flagging_agent.py   # Workflow 1: Performance Flagging
│   ├── allocation_agent.py # Workflow 2: Supervision Allocation
│   └── root_cause_agent.py # Workflow 3: Root Cause Analysis
├── tools/
│   ├── compute_metrics.py  # Two-level benchmarking engine
│   └── claude_client.py    # Anthropic API wrapper
├── outputs/
│   ├── pdf_generator.py    # Supervisor brief PDF
│   └── email_dispatcher.py # Office 365 SMTP delivery
├── core/
│   └── scheduler.py        # APScheduler weekly jobs
└── ui/pages/
    ├── 01_upload.py        # Data upload + quality report
    ├── 02_dashboard.py     # 3-level drill-down dashboard
    ├── 03_analysis.py      # AI analysis hub (4 tabs)
    └── 04_schedule.py      # Email config + scheduler
```

## Licence

Internal JHPIEGO RISE tool. Not for public distribution.
