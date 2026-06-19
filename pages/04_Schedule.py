"""
04_Schedule.py
──────────────
Página 4: Relatórios Automáticos e Agendamento de Email
"""

import streamlit as st
import os
import json
from datetime import date, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from outputs.email_dispatcher import EmailDispatcher
from outputs.pdf_generator import generate_supervisor_brief
from core.scheduler import get_scheduled_jobs, schedule_weekly_report, cancel_job

st.set_page_config(page_title="Relatórios — RISE ICT", page_icon="📧", layout="wide")

st.markdown("## 📧 Relatórios Automáticos e Agendamento")

dispatcher = EmailDispatcher()

# ─── Estado do email ──────────────────────────────────────────────────────────
st.markdown("### Configuração de Email")

if dispatcher.is_configured():
    st.success(f"✅ Email configurado: {dispatcher.user} → {dispatcher.host}:{dispatcher.port}")
else:
    st.error(
        "❌ Email não configurado. Adicione `EMAIL_USER` e `EMAIL_PASSWORD` ao ficheiro `.env`.\n\n"
        "Para Office 365: `EMAIL_HOST=smtp.office365.com` | `EMAIL_PORT=587`"
    )

with st.expander("🔧 Testar Configuração de Email"):
    test_recipient = st.text_input("Enviar email de teste para:", value=os.getenv("EMAIL_USER", ""))
    if st.button("Enviar Email de Teste"):
        if not dispatcher.is_configured():
            st.error("Email não configurado.")
        elif not test_recipient:
            st.warning("Indique um endereço de email de destinatário.")
        else:
            with st.spinner("A enviar email de teste..."):
                ok = dispatcher.send_test_email(test_recipient)
            if ok:
                st.success(f"✅ Email de teste enviado para {test_recipient}")
            else:
                st.error("❌ Falha no email. Verifique EMAIL_HOST, EMAIL_USER, EMAIL_PASSWORD no .env")

st.markdown("---")

# ─── Envio manual de relatórios ───────────────────────────────────────────────
st.markdown("### 📤 Enviar Relatório Agora")

if st.session_state.get("df") is None:
    st.warning("⚠️ Nenhum dado carregado. Carregue um CSV primeiro para gerar relatórios.")
else:
    result = st.session_state.get("orch_result")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📄 Resumo de Supervisor (PDF)")
        sup_emails_raw = st.text_area(
            "Endereços de email dos supervisores (um por linha)",
            value=os.getenv("SUPERVISOR_EMAILS", "").replace(",", "\n"),
            height=100,
        )
        sup_emails = [e.strip() for e in sup_emails_raw.splitlines() if e.strip()]
        sup_province = st.text_input("Província (para o assunto do email)", value="MANICA")
        sup_district  = st.text_input("Distrito (para o assunto do email)", value="")

        if st.button("📨 Enviar Resumo de Supervisor", use_container_width=True):
            if not sup_emails:
                st.warning("Indique pelo menos um email de supervisor.")
            elif not dispatcher.is_configured():
                st.error("Email não configurado.")
            elif result is None:
                st.warning("Execute a Análise IA primeiro para gerar um resumo.")
            else:
                with st.spinner("A gerar PDF e a enviar..."):
                    pdf_bytes = generate_supervisor_brief(
                        flagging_result=result.flagging,
                        allocation_result=result.allocation,
                        province=sup_province,
                        district=sup_district,
                        report_date=date.today(),
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
                    st.success(f"✅ Resumo de supervisor enviado para: {', '.join(sup_emails)}")
                else:
                    st.error("❌ Falha no email. Verifique a configuração.")

    with col2:
        st.markdown("#### 📊 Relatório da Equipa Central (HTML)")
        central_emails_raw = st.text_area(
            "Endereços de email da equipa central (um por linha)",
            value=os.getenv("CENTRAL_TEAM_EMAILS", "").replace(",", "\n"),
            height=100,
        )
        central_emails = [e.strip() for e in central_emails_raw.splitlines() if e.strip()]

        if st.button("📨 Enviar Relatório da Equipa Central", use_container_width=True):
            if not central_emails:
                st.warning("Indique pelo menos um email da equipa central.")
            elif not dispatcher.is_configured():
                st.error("Email não configurado.")
            elif result is None:
                st.warning("Execute a Análise IA primeiro.")
            else:
                narrative = result.flagging.narrative if result.flagging else "Sem análise disponível."
                html_content = f"""
<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>RISE ICT — Relatório Semanal</title>
<style>body{{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px}}
h1{{color:#00539C}}h2{{color:#333}}pre{{background:#f5f5f5;padding:10px;border-radius:4px}}</style>
</head><body>
<h1>RISE ICT — Relatório de Análise Semanal</h1>
<p><strong>Data:</strong> {date.today().strftime('%d %B %Y')}</p>
<hr>
<h2>Sinalização de Desempenho</h2>
<pre>{narrative}</pre>
{'<h2>Análise de Causa Raiz</h2><pre>' + result.root_cause.narrative + '</pre>' if result.root_cause and result.root_cause.narrative else ''}
</body></html>
"""
                with st.spinner("A enviar relatório da equipa central..."):
                    ok = dispatcher.send_central_team_report(
                        recipients=central_emails,
                        html_content=html_content,
                        report_date=date.today(),
                        summary=narrative[:400],
                    )
                if ok:
                    st.success(f"✅ Relatório enviado para: {', '.join(central_emails)}")
                else:
                    st.error("❌ Falha no email.")

    if result is not None:
        st.markdown("---")
        st.markdown("#### ⬇️ Descarregar PDF (sem email)")
        if st.button("Gerar e Descarregar PDF"):
            with st.spinner("A gerar PDF..."):
                pdf_bytes = generate_supervisor_brief(
                    flagging_result=result.flagging,
                    allocation_result=result.allocation,
                    province=sup_province if 'sup_province' in dir() else "",
                    district=sup_district if 'sup_district' in dir() else "",
                    report_date=date.today(),
                )
            st.download_button(
                label="⬇️ Descarregar PDF",
                data=pdf_bytes,
                file_name=f"RISE_ICT_Resumo_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )

st.markdown("---")

# ─── Agendamento semanal ──────────────────────────────────────────────────────
st.markdown("### ⏰ Agendamento Semanal Automático")
st.info(
    "O agendador executa automaticamente a análise completa todas as segundas-feiras às 06h00 "
    "e envia os relatórios à quarta-feira (supervisores de manhã, equipa central à tarde). "
    "A aplicação Streamlit deve estar em execução para o agendador funcionar."
)

schedule_config_path = Path(__file__).parent.parent / "data" / "schedule_config.json"
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
    enabled = st.toggle("Activar relatórios semanais automáticos", value=config.get("enabled", False))
    day_opts = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    day_labels = {"Monday": "Segunda-feira", "Tuesday": "Terça-feira", "Wednesday": "Quarta-feira",
                  "Thursday": "Quinta-feira", "Friday": "Sexta-feira"}
    analysis_day = st.selectbox(
        "Executar análise em",
        day_opts,
        format_func=lambda d: day_labels[d],
        index=day_opts.index(config.get("analysis_day", "Monday")),
    )
    province_filter = st.text_input(
        "Filtro de província (deixar em branco para todas)",
        value=config.get("province_filter", ""),
    )

with col_s2:
    sched_sup_emails = st.text_area(
        "Lista de emails dos supervisores",
        value="\n".join(config.get("supervisor_emails", [])),
        height=80,
    )
    sched_central_emails = st.text_area(
        "Lista de emails da equipa central",
        value="\n".join(config.get("central_emails", [])),
        height=80,
    )

if st.button("💾 Guardar Configuração do Agendamento", type="primary"):
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
    st.success("✅ Configuração do agendamento guardada.")

st.markdown("---")
st.markdown("### 📋 Tarefas Agendadas")

try:
    jobs = get_scheduled_jobs()
    if jobs:
        for job in jobs:
            st.markdown(f"- **{job['id']}**: próxima execução em `{job['next_run']}`")
    else:
        st.info("Sem tarefas agendadas activas. Active o agendamento acima e reinicie a aplicação.")
except Exception:
    st.info("Agendador ainda não está em execução (inicie a aplicação para activar).")
