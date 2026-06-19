"""
email_dispatcher.py
───────────────────
Sends automated reports via Outlook / Office 365 SMTP.

Handles:
  - Supervisor brief (PDF attachment)
  - Central team HTML report (inline or attachment)
  - Escalation alerts
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from datetime import date

logger = logging.getLogger(__name__)


class EmailDispatcher:
    """
    Sends emails via Office 365 SMTP.

    Configuration via environment variables:
      EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD, EMAIL_FROM
    """

    def __init__(self):
        self.host = os.getenv("EMAIL_HOST", "smtp.office365.com")
        self.port = int(os.getenv("EMAIL_PORT", 587))
        self.user = os.getenv("EMAIL_USER", "")
        self.password = os.getenv("EMAIL_PASSWORD", "")
        self.from_addr = os.getenv("EMAIL_FROM", self.user)

    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def send_supervisor_brief(
        self,
        recipients: List[str],
        pdf_bytes: bytes,
        province: str,
        district: str,
        report_date: Optional[date] = None,
        narrative_summary: str = "",
    ) -> bool:
        """
        Send weekly supervisor brief PDF to provincial supervisors.

        Parameters
        ----------
        recipients      : List of supervisor email addresses
        pdf_bytes       : PDF file contents from pdf_generator
        province        : Province name for subject line
        district        : District name for subject line
        report_date     : Report date (defaults to today)
        narrative_summary : Plain text summary for email body
        """
        report_date = report_date or date.today()
        scope = f"{province} — {district}" if district else province

        subject = (
            f"[RISE ICT] Relatório de Supervisão — {scope} — "
            f"{report_date.strftime('%d/%m/%Y')}"
        )

        body = f"""Caro(a) Supervisor(a),

Segue em anexo o relatório semanal de supervisão ICT para {scope}.

{narrative_summary[:500] if narrative_summary else ''}

Por favor reveja as prioridades desta semana e confirme as visitas de supervisão planeadas.

Atenciosamente,
Sistema de Supervisão ICT — RISE Programme / JHPIEGO

---
Este é um relatório automático gerado pelo sistema de supervisão ICT.
Para questões técnicas, contacte: {self.from_addr}
"""

        filename = f"RISE_ICT_Supervisao_{scope.replace(' ', '_')}_{report_date.strftime('%Y%m%d')}.pdf"

        return self._send(
            recipients=recipients,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=filename,
            attachment_mimetype="application/pdf",
        )

    def send_central_team_report(
        self,
        recipients: List[str],
        html_content: str,
        report_date: Optional[date] = None,
        summary: str = "",
    ) -> bool:
        """
        Send HTML dashboard/report to central JHPIEGO team.
        """
        report_date = report_date or date.today()
        subject = f"[RISE ICT] Dashboard — Análise Central — {report_date.strftime('%d/%m/%Y')}"

        body_text = f"""Equipa Central,

O dashboard ICT desta semana está disponível em anexo.

Resumo:
{summary[:800] if summary else ''}

---
Sistema de Supervisão ICT — RISE Programme / JHPIEGO
"""
        filename = f"RISE_ICT_Dashboard_{report_date.strftime('%Y%m%d')}.html"

        return self._send(
            recipients=recipients,
            subject=subject,
            body=body_text,
            attachment_bytes=html_content.encode("utf-8"),
            attachment_filename=filename,
            attachment_mimetype="text/html",
        )

    def send_escalation_alert(
        self,
        recipients: List[str],
        alert_type: str,
        message: str,
        facility: str = "",
        counselor: str = "",
    ) -> bool:
        """
        Send an immediate escalation alert (linkage drop, data quality failure, etc.)
        """
        subject = f"[RISE ICT] ⚠️ ALERTA — {alert_type} — {facility or 'Programa'}"

        body = f"""⚠️ ALERTA DE SUPERVISÃO ICT

Tipo: {alert_type}
Unidade: {facility or 'N/A'}
Conselheiro(a): {counselor or 'N/A'}

{message}

Por favor tome acção imediata.

---
Sistema de Supervisão ICT — RISE Programme / JHPIEGO
"""
        return self._send(recipients=recipients, subject=subject, body=body)

    def send_test_email(self, recipient: str) -> bool:
        """Send a test email to verify SMTP configuration."""
        return self._send(
            recipients=[recipient],
            subject="[RISE ICT] Teste de Configuração de Email",
            body="Se recebeu este email, a configuração SMTP está correcta. / If you received this email, SMTP is configured correctly.",
        )

    # ─── Internal ──────────────────────────────────────────────────────────────

    def _send(
        self,
        recipients: List[str],
        subject: str,
        body: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_mimetype: str = "application/octet-stream",
    ) -> bool:
        if not self.is_configured():
            logger.warning("Email not configured. Set EMAIL_USER and EMAIL_PASSWORD in .env")
            return False

        if not recipients:
            logger.warning("No recipients specified.")
            return False

        msg = MIMEMultipart()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachment_bytes and attachment_filename:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_filename}"',
            )
            # Set proper MIME type
            if attachment_mimetype == "application/pdf":
                part.set_type("application/pdf")
            elif attachment_mimetype == "text/html":
                part.set_type("text/html")
            msg.attach(part)

        try:
            logger.info(f"Sending email to {recipients} | Subject: {subject}")
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.from_addr, recipients, msg.as_string())
            logger.info(f"Email sent successfully to {len(recipients)} recipient(s)")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check EMAIL_USER and EMAIL_PASSWORD.")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected email error: {e}", exc_info=True)
            return False
