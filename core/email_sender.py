"""
email_sender.py
───────────────
Envio de relatórios PDF por email via Outlook / Office 365 SMTP.

Fluxo:
  1. Carregar lista de supervisores de config/supervisors.yaml
  2. Filtrar destinatários pela província/distrito do relatório
  3. Compor email com PDF em anexo
  4. Enviar via smtp.office365.com (STARTTLS, porta 587)
  5. Devolver resultado (sucesso/erro por destinatário)

Credenciais lidas de variáveis de ambiente (.env):
  EMAIL_USER     — endereço de envio (ex: nuno.gaspar@jhpiego.org)
  EMAIL_PASSWORD — senha ou app password do Outlook
  EMAIL_FROM     — nome/endereço no campo From (pode ser igual a EMAIL_USER)
"""

import os
import smtplib
import logging
import yaml
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text    import MIMEText
from email.mime.base    import MIMEBase
from email              import encoders
from pathlib            import Path
from typing             import List, Optional
from dataclasses        import dataclass, field

logger = logging.getLogger(__name__)

# ── Configuração SMTP Office 365 ─────────────────────────────────────────────
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

# ── Caminhos ──────────────────────────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "supervisors.yaml"


# ── Tipos de dados ─────────────────────────────────────────────────────────────
@dataclass
class Supervisor:
    name:      str
    email:     str
    role:      str
    provinces: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)


@dataclass
class SendResult:
    success:    bool
    recipients: List[str]
    cc:         List[str]
    errors:     List[str] = field(default_factory=list)
    message:    str = ""


# ── Carregar configuração ─────────────────────────────────────────────────────
def load_supervisors() -> tuple[List[Supervisor], List[str], dict]:
    """
    Lê config/supervisors.yaml e devolve:
      (lista_supervisores, cc_sempre, email_settings)
    """
    if not _CONFIG_PATH.exists():
        logger.warning(f"supervisors.yaml não encontrado em {_CONFIG_PATH}")
        return [], [], {}

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    supervisors = [
        Supervisor(
            name=s.get("name", ""),
            email=s.get("email", ""),
            role=s.get("role", ""),
            provinces=[p.upper() for p in s.get("provinces", [])],
            districts=s.get("districts", []),
        )
        for s in cfg.get("supervisors", [])
    ]
    cc_always = cfg.get("cc_always", [])
    settings  = cfg.get("email_settings", {})
    return supervisors, cc_always, settings


def get_recipients(province: str = "", district: str = "") -> tuple[List[Supervisor], List[str]]:
    """
    Filtra os supervisores relevantes para a província/distrito do relatório.
    Devolve (supervisores_to, cc_emails).
    """
    supervisors, cc_always, _ = load_supervisors()
    prov_upper = province.upper().strip()
    dist_upper = district.upper().strip()

    matched = []
    for sup in supervisors:
        if not sup.email:
            continue
        # Sem filtro de província = recebe tudo
        if not sup.provinces:
            matched.append(sup)
            continue
        # Filtro por província
        if prov_upper and prov_upper not in sup.provinces:
            continue
        # Filtro por distrito (se definido no supervisor)
        if sup.districts and dist_upper and dist_upper not in [d.upper() for d in sup.districts]:
            continue
        matched.append(sup)

    return matched, cc_always


def is_configured() -> bool:
    """Verifica se as credenciais de email estão definidas."""
    return bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASSWORD"))


# ── Composição do email ──────────────────────────────────────────────────────
def _build_subject(province: str, period_start: Optional[date], period_end: Optional[date]) -> str:
    supervisors, _, settings = load_supervisors()
    template = settings.get(
        "subject_template",
        "RISE ICT | Resumo de Supervisao — {province} | {period}"
    )
    period_str = (
        f"{period_start.strftime('%d/%m')} a {period_end.strftime('%d/%m/%Y')}"
        if period_start and period_end
        else date.today().strftime("%d/%m/%Y")
    )
    return template.format(province=province or "Todas", period=period_str)


def _build_body(
    province: str,
    period_start: Optional[date],
    period_end: Optional[date],
    n_critical: int,
    n_attention: int,
    sender_name: str,
) -> str:
    period_str = (
        f"{period_start.strftime('%d/%m/%Y')} a {period_end.strftime('%d/%m/%Y')}"
        if period_start and period_end
        else "período recente"
    )
    return f"""\
Exmo(a) Supervisor(a),

Em anexo encontra o resumo de supervisão ICT RISE para a província de {province or "todas as províncias"}, referente ao período de {period_str}.

Destaques do relatório:
  • {n_critical} unidade(s)/conselheiro(s) CRÍTICO(S) — requerem visita esta semana
  • {n_attention} em ATENÇÃO — agendar visita este mês

O relatório inclui:
  1. Resumo geral de desempenho por distrito (HIV+ encontrados, positividade, testagem)
  2. Prioridades contextualizadas — com explicação do porquê, volume de testagem, positivos esperados vs encontrados, e tendência
  3. Plano de visitas semanal com justificação

Por favor reveja o relatório e tome as acções indicadas no plano de visitas.

Qualquer dúvida, não hesite em contactar.

Com cumprimentos,
{sender_name}
RISE ICT — Advisor Técnico IA | JHPIEGO Moçambique

─────────────────────────────────────────
Este email foi gerado automaticamente pelo Sistema de Supervisão IA RISE ICT.
"""


# ── Envio ─────────────────────────────────────────────────────────────────────
def send_report(
    pdf_bytes: bytes,
    province: str = "",
    district: str = "",
    period_start: Optional[date] = None,
    period_end:   Optional[date] = None,
    n_critical: int = 0,
    n_attention: int = 0,
    override_recipients: Optional[List[str]] = None,  # para testes
) -> SendResult:
    """
    Envia o PDF de supervisão por email aos supervisores relevantes.

    Parâmetros
    ----------
    pdf_bytes           : conteúdo do PDF em bytes
    province            : nome da província (para filtrar destinatários)
    district            : nome do distrito (opcional)
    period_start/end    : datas do período de análise
    n_critical/attention: número de sinalizações (para o corpo do email)
    override_recipients : lista de emails para sobrepor a configuração (testes)

    Devolve
    -------
    SendResult com sucesso/erro por destinatário
    """
    user     = os.getenv("EMAIL_USER", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    sender   = os.getenv("EMAIL_FROM", user)

    if not user or not password:
        return SendResult(
            success=False, recipients=[], cc=[],
            errors=["EMAIL_USER ou EMAIL_PASSWORD não configurados no ficheiro .env"],
        )

    # Destinatários
    if override_recipients:
        to_emails = override_recipients
        cc_emails = []
    else:
        supervisors, cc_emails = get_recipients(province, district)
        to_emails = [s.email for s in supervisors if s.email]

    if not to_emails:
        return SendResult(
            success=False, recipients=[], cc=cc_emails,
            errors=["Nenhum supervisor configurado para esta província. Verifique config/supervisors.yaml"],
        )

    subject = _build_subject(province, period_start, period_end)
    body    = _build_body(
        province=province,
        period_start=period_start,
        period_end=period_end,
        n_critical=n_critical,
        n_attention=n_attention,
        sender_name=sender.split("@")[0].replace(".", " ").title(),
    )

    # Nome do ficheiro PDF
    period_tag = (
        period_end.strftime("%Y%m%d") if period_end else date.today().strftime("%Y%m%d")
    )
    filename = f"RISE_ICT_{province or 'Nacional'}_{period_tag}.pdf"

    errors = []
    try:
        msg = MIMEMultipart()
        msg["From"]    = sender
        msg["To"]      = ", ".join(to_emails)
        if cc_emails:
            msg["Cc"]  = ", ".join(cc_emails)
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Anexar PDF
        part = MIMEBase("application", "octet-stream")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

        all_recipients = to_emails + cc_emails

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(sender, all_recipients, msg.as_string())

        logger.info(f"Email enviado para {to_emails} (cc: {cc_emails})")
        return SendResult(
            success=True,
            recipients=to_emails,
            cc=cc_emails,
            message=f"Email enviado com sucesso para {len(to_emails)} destinatário(s).",
        )

    except smtplib.SMTPAuthenticationError:
        err = "Erro de autenticação SMTP. Verifique EMAIL_USER e EMAIL_PASSWORD no .env."
        logger.error(err)
        return SendResult(success=False, recipients=to_emails, cc=cc_emails, errors=[err])

    except smtplib.SMTPException as e:
        err = f"Erro SMTP: {e}"
        logger.error(err)
        return SendResult(success=False, recipients=to_emails, cc=cc_emails, errors=[err])

    except Exception as e:
        err = f"Erro inesperado ao enviar email: {e}"
        logger.error(err)
        return SendResult(success=False, recipients=to_emails, cc=cc_emails, errors=[err])
