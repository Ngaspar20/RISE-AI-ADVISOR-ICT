"""
03_Analysis.py
──────────────
Página 3: Hub de Análise IA
Foco: volume de testagem, positividade, positivos encontrados
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator
from core.period_utils import period_label, period_label_long
from core.email_sender import (
    send_report, get_recipients, load_supervisors, is_configured as email_configured
)
from outputs.pdf_generator import generate_supervisor_brief
from tools.claude_client import is_configured as api_configured

st.set_page_config(page_title="Análise IA — RISE ICT", page_icon="🤖", layout="wide")

if st.session_state.get("df") is None:
    st.warning("⚠️ Nenhum dado carregado. Por favor carregue um CSV primeiro.")
    if st.button("→ Ir para Upload"):
        st.switch_page("pages/01_Upload.py")
    st.stop()

df_full   = st.session_state.df
df_period = st.session_state.get("df_period", df_full)   # 2 semanas actuais
df_trend  = st.session_state.get("df_trend",  df_full)   # 4 semanas anteriores (para tendência)
p_start   = st.session_state.get("period_start")
p_end     = st.session_state.get("period_end")

st.markdown("## 🤖 Análise IA — Três Fluxos de Supervisão")

# Banner do período
if p_start and p_end:
    n_p = len(df_period)
    st.info(
        f"📅 **Período analisado:** {period_label(p_start, p_end)}  "
        f"({n_p:,} contactos registados no período)"
    )
    if n_p == 0:
        st.error("❌ Nenhum contacto com data de teste nas últimas 2 semanas. Verifique o CSV.")
        st.stop()

if not api_configured():
    st.warning(
        "⚠️ **Grok API não configurado.** A análise será executada sem geração de narrativa IA. "
        "Adicione `GROK_API_KEY` ao ficheiro `.env` para funcionalidade completa."
    )

st.markdown("### Configurações da Análise")

col1, col2, col3 = st.columns(3)
with col1:
    provinces = ["Todas"] + sorted(df_period["province"].dropna().unique().tolist())
    sel_province = st.selectbox("Província", provinces)

with col2:
    df_prov = df_period if sel_province == "Todas" else df_period[df_period["province"] == sel_province]
    districts = ["Todos"] + sorted(df_prov["district"].dropna().unique().tolist())
    sel_district = st.selectbox("Distrito", districts)

with col3:
    n_supervisors = st.number_input("Supervisores Disponíveis", min_value=1, max_value=10, value=2)

col_w1, col_w2, col_w3 = st.columns(3)
run_flagging   = col_w1.checkbox("✅ Fluxo 1: Sinalização de Desempenho", value=True)
run_allocation = col_w2.checkbox("✅ Fluxo 2: Alocação de Supervisão", value=True)
run_rca        = col_w3.checkbox("✅ Fluxo 3: Análise de Causa Raiz", value=True)

st.markdown("---")

if st.button("🚀 Executar Análise", type="primary", use_container_width=True):
    prov_filter = None if sel_province == "Todas" else sel_province
    dist_filter = None if sel_district == "Todos" else sel_district

    with st.spinner("A executar análise... (pode demorar 30-90 segundos com Grok API)"):
        orch = Orchestrator()
        result = orch.run(
            df_period,          # ← apenas as 2 semanas do período
            province=prov_filter,
            district=dist_filter,
            run_flagging=run_flagging,
            run_allocation=run_allocation,
            run_root_cause=run_rca,
            n_supervisors=int(n_supervisors),
        )
        st.session_state.orch_result = result

    if result.success:
        st.success(f"✅ Análise concluída em {result.elapsed_seconds:.1f}s")
    else:
        st.warning(f"⚠️ Análise concluída com erros: {result.errors}")

result = st.session_state.get("orch_result")

if result is None:
    st.info("Clique em **Executar Análise** para gerar insights de supervisão com IA.")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs([
    "🚦 Fluxo 1: Sinalização",
    "📅 Fluxo 2: Alocação",
    "🔍 Fluxo 3: Causa Raiz",
    "📋 Análise por Conselheiro",
])

# ── Tab 1: Sinalização ─────────────────────────────────────────────────────────
with tab1:
    if result.flagging is None:
        st.info("Fluxo de sinalização não foi executado.")
    elif not result.flagging.success:
        st.error(f"Sinalização falhou: {result.flagging.error}")
    else:
        fr   = result.flagging
        data = fr.data

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Contactos Analisados", f"{data.get('n_contacts', 0):,}")
        col2.metric("Conselheiros", data.get("n_counselors", 0))
        col3.metric("Unidades Sanitárias", data.get("n_facilities", 0))
        n_red = sum(1 for df_f in [data.get("counselor_flags", pd.DataFrame()), data.get("facility_flags", pd.DataFrame())]
                    if not df_f.empty for _, r in df_f.iterrows() if r.get("severity") == "red")
        col4.metric("Sinalizações Críticas 🔴", n_red)

        st.markdown("---")

        # Unidades sinalizadas
        fac_flags = data.get("facility_flags", pd.DataFrame())
        if not fac_flags.empty:
            st.markdown("#### 🔴 Unidades Sanitárias Sinalizadas (Problemas Sistémicos)")
            for _, row in fac_flags.iterrows():
                icon = "🔴" if row.get("severity") == "red" else "🟡"
                positivity = row.get("median_test_positivity", 0)
                dist_pos   = row.get("district_median_test_positivity", 0)
                contacts   = int(row.get("n_contacts_total", 0))
                try:
                    pos_str  = f"{float(positivity):.1f}%"
                    dpos_str = f"{float(dist_pos):.1f}%"
                except Exception:
                    pos_str = dpos_str = "N/A"
                st.markdown(f"""
                <div style='background:#FFF5F5;border-left:4px solid #DC3545;padding:0.7rem;border-radius:4px;margin:0.3rem 0'>
                <b>{icon} {row['facility']}</b> ({row.get('district', '')}) —
                Positividade: <b>{pos_str}</b> (mediana distrito: {dpos_str}) |
                Contactos: {contacts}
                </div>
                """, unsafe_allow_html=True)

        # Conselheiros sinalizados
        coun_flags = data.get("counselor_flags", pd.DataFrame())
        if not coun_flags.empty:
            st.markdown("#### 🟡 Conselheiros Sinalizados")
            for _, row in coun_flags.iterrows():
                icon = "🔴" if row.get("severity") == "red" else "🟡"
                pos  = row.get("test_positivity", 0)
                fpos = row.get("facility_median_test_positivity", 0)
                cons = row.get("consent_rate", 0)
                try:
                    pos_str  = f"{float(pos):.1f}%"
                    fpos_str = f"{float(fpos):.1f}%"
                    cons_str = f"{float(cons):.1f}%"
                except Exception:
                    pos_str = fpos_str = cons_str = "N/A"
                st.markdown(f"""
                <div style='background:#FFFBF0;border-left:4px solid #FFC107;padding:0.7rem;border-radius:4px;margin:0.3rem 0'>
                <b>{icon} {row['counselor']}</b> em {row.get('facility', '')} ({row.get('district', '')}) —
                Positividade: <b>{pos_str}</b> (mediana US: {fpos_str}) |
                Consentimento: {cons_str} |
                Contactos: {int(row.get('n_contacts', 0))}
                </div>
                """, unsafe_allow_html=True)

        # Narrativa IA
        if fr.narrative:
            st.markdown("---")
            st.markdown("#### 🤖 Resumo de Supervisão Gerado por IA")
            st.markdown(fr.narrative)

        # ── PDF + Envio por Email ───────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 📄 Relatório PDF e Envio aos Supervisores")

        prov_label = sel_province if sel_province != "Todas" else ""
        dist_label = sel_district if sel_district != "Todos" else ""

        if st.button("📄 Gerar PDF e Pré-visualizar Envio", key="gen_pdf", type="primary"):
            with st.spinner("A gerar PDF..."):
                try:
                    fac_f  = result.flagging.data.get("facility_flags",  pd.DataFrame())
                    coun_f = result.flagging.data.get("counselor_flags", pd.DataFrame())
                    n_crit = sum(1 for df_x in [fac_f, coun_f] if not df_x.empty
                                 for _, r in df_x.iterrows() if r.get("severity") == "red")
                    n_atenc= sum(1 for df_x in [fac_f, coun_f] if not df_x.empty
                                 for _, r in df_x.iterrows() if r.get("severity") == "yellow")

                    pdf_bytes = generate_supervisor_brief(
                        flagging_result=result.flagging,
                        allocation_result=result.allocation,
                        province=prov_label,
                        district=dist_label,
                        report_date=date.today(),
                        df=df_period,
                        df_prev=df_trend,
                        period_start=p_start,
                        period_end=p_end,
                    )
                    st.session_state["pdf_bytes"]  = pdf_bytes
                    st.session_state["pdf_n_crit"] = n_crit
                    st.session_state["pdf_n_atenc"]= n_atenc
                    st.session_state["pdf_ready"]  = True
                except Exception as e:
                    st.error(f"Erro na geração de PDF: {e}")
                    st.session_state["pdf_ready"] = False

        # ── Painel de Oversight ────────────────────────────────────────────
        if st.session_state.get("pdf_ready"):
            pdf_bytes = st.session_state["pdf_bytes"]
            n_crit    = st.session_state.get("pdf_n_crit", 0)
            n_atenc   = st.session_state.get("pdf_n_atenc", 0)

            st.markdown("---")
            st.markdown("### 🔍 Pré-visualização antes do Envio")

            # Download local sempre disponível
            period_tag = p_end.strftime("%Y%m%d") if p_end else date.today().strftime("%Y%m%d")
            fname = f"RISE_ICT_{prov_label or 'Nacional'}_{period_tag}.pdf"
            st.download_button(
                label="⬇️ Descarregar PDF (para revisão)",
                data=pdf_bytes,
                file_name=fname,
                mime="application/pdf",
            )

            # Destinatários
            supervisors, cc_list = get_recipients(prov_label, dist_label)
            to_emails = [s.email for s in supervisors]

            st.markdown("**Destinatários (Para):**")
            if supervisors:
                for s in supervisors:
                    st.markdown(f"- {s.name} — `{s.email}` ({s.role})")
            else:
                st.warning(
                    "⚠️ Nenhum supervisor encontrado para esta província. "
                    "Verifique `config/supervisors.yaml`."
                )

            if cc_list:
                st.markdown(f"**CC:** {', '.join(cc_list)}")

            # Pré-visualização do assunto e corpo
            period_str = (
                f"{p_start.strftime('%d/%m/%Y')} a {p_end.strftime('%d/%m/%Y')}"
                if p_start and p_end else ""
            )
            subj = f"RISE ICT | Resumo de Supervisão — {prov_label or 'Nacional'} | {period_str}"
            with st.expander("📧 Ver assunto e corpo do email"):
                st.code(subj, language=None)
                st.markdown(f"""
**Corpo:**
Em anexo encontra o resumo de supervisão ICT RISE para **{prov_label or 'todas as províncias'}**, período **{period_str}**.

Destaques:
- 🔴 **{n_crit}** unidade(s)/conselheiro(s) CRÍTICO(S) — visita esta semana
- 🟡 **{n_atenc}** em ATENÇÃO — agendar este mês

Anexo: `{fname}`
""")

            # Estado do email
            if not email_configured():
                st.error(
                    "❌ Email não configurado. Adicione `EMAIL_USER` e `EMAIL_PASSWORD` ao ficheiro `.env`."
                )
            elif not supervisors:
                st.warning("Adicione supervisores ao ficheiro `config/supervisors.yaml` para activar o envio.")
            else:
                st.markdown("---")
                st.markdown("#### ✅ Confirmação de Envio")
                st.info(
                    f"O email com o relatório PDF será enviado para **{len(supervisors)} supervisor(es)** "
                    f"com cópia para **{len(cc_list)} destinatário(s)**. "
                    "Reveja o PDF acima antes de confirmar."
                )

                col_send, col_cancel = st.columns([1, 3])
                with col_send:
                    if st.button("📨 Confirmar e Enviar", type="primary", key="btn_send"):
                        with st.spinner("A enviar email..."):
                            send_result = send_report(
                                pdf_bytes=pdf_bytes,
                                province=prov_label,
                                district=dist_label,
                                period_start=p_start,
                                period_end=p_end,
                                n_critical=n_crit,
                                n_attention=n_atenc,
                            )
                        if send_result.success:
                            st.success(
                                f"✅ {send_result.message}\n\n"
                                f"**Enviado para:** {', '.join(send_result.recipients)}"
                            )
                            if send_result.cc:
                                st.info(f"CC: {', '.join(send_result.cc)}")
                            st.session_state["pdf_ready"] = False
                        else:
                            for err in send