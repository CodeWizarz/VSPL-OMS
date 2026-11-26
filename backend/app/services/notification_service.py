import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging

logger = logging.getLogger("notification_service")


class NotificationService:
    @staticmethod
    def send_f1_excess_alert(
        wo: any,
        stage: str,
        planned_qty: int,
        produced_qty: int,
        excess_qty: int,
        heat_number: str = None,
        operator_name: str = None,
        reason: str = None
    ) -> bool:
        """Sends an in-system and email alert when F1 records excess production."""
        wo_number = getattr(wo, "wo_number", "Unknown WO")
        order = getattr(wo, "order", None)
        part = getattr(order, "part", None) if order else None
        part_name = getattr(part, "name", "N/A") if part else "N/A"
        part_number = getattr(part, "part_number", "N/A") if part else "N/A"
        customer = getattr(order, "customer", None) if order else None
        customer_name = getattr(customer, "name", "N/A") if customer else "N/A"
        
        subject = f"[VSPL SMES Alert] F1 Excess Production Logged — {wo_number} (+{excess_qty} pcs)"
        
        body_text = f"""
VSPL Smart Manufacturing Execution System (SMES) — Production Alert
===================================================================

An excess casting / production entry was recorded at stage {stage}:

• Work Order:       {wo_number}
• Customer:         {customer_name}
• Part Name/Number: {part_name} ({part_number})
• Heat Number:      {heat_number or 'Not Assigned'}
• Operator / Cell:  {operator_name or 'Floor Operator'}
• Original Target:  {planned_qty} pcs
• Actual Cast/Made: {produced_qty} pcs
• Excess Quantity:  +{excess_qty} pcs
• Reason / Notes:   {reason or 'Foundry excess mould poured'}
• Timestamp:        {datetime.now().strftime('%d %b %Y, %H:%M:%S IST')}

The Work Order route and downstream stages have been automatically adjusted
to track all {produced_qty} pieces through subsequent manufacturing stages.

-------------------------------------------------------------------
Automated alert from VSPL SMES Engine v3.3 (https://oms.vijayspheroidals.in)
"""

        # SMTP configuration
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "data.analyst@vijayspheroidals.in")
        smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))
        
        # Recipient list: defaults to data.analyst@vijayspheroidals.in plus ALERT_EMAIL_RECIPIENTS
        recipients = [smtp_user]
        extra_recipients = os.environ.get("ALERT_EMAIL_RECIPIENTS", "")
        if extra_recipients:
            for r in extra_recipients.split(","):
                clean = r.strip()
                if clean and clean not in recipients:
                    recipients.append(clean)

        logger.info(f"F1 EXCESS ALERT: WO {wo_number}, Excess: +{excess_qty} pcs. Notifying: {recipients}")
        print(f"[F1_EXCESS_ALERT] {subject}\n{body_text}")

        if not smtp_pass:
            logger.warning("SMTP_PASSWORD not set; email alert logged to console and audit trail.")
            return True

        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info("Email alert delivered successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to deliver SMTP email alert: {e}")
            return False


def _digest_text(digest: dict) -> tuple:
    c = digest["counts"]
    subject = f"[VSPL SMES] Plan delays {digest['date']}: {c['delayed']} delayed, {c['at_risk']} at risk"
    lines = [
        "VSPL Smart Manufacturing Execution System (SMES) - Planning digest",
        "=" * 66,
        f"Date: {digest['date']}   Delayed: {c['delayed']}   At risk: {c['at_risk']}   No plan: {c['no_plan']}",
        "",
    ]
    for title, key in (("DELAYED", "delayed"), ("AT RISK", "at_risk")):
        rows = digest[key]
        lines.append(f"{title} ({len(rows)})")
        if not rows:
            lines.append("  none")
        for r in rows:
            lines.append(
                f"  {r['wo_number']}  setup {r.get('setup_number') or 'none'}  {r.get('part_number') or ''}  "
                f"commitment {r.get('commitment_date') or 'n/a'}  {r['plan_text']}"
            )
        lines.append("")
    lines.append("Automated message from VSPL SMES (https://oms.vijayspheroidals.in)")
    return subject, "\n".join(lines)


def send_plan_delay_digest(digest: dict, recipients: list) -> dict:
    """Email the planning digest. Without SMTP_PASSWORD on the server nothing is emailed; the list is
    only written to the server log. Returns {email_sent, recipients}."""
    subject, body = _digest_text(digest)
    smtp_user = os.environ.get("SMTP_USER", "data.analyst@vijayspheroidals.in")
    smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))
    to = list(dict.fromkeys([r for r in recipients if r]))
    for extra in os.environ.get("ALERT_EMAIL_RECIPIENTS", "").split(","):
        if extra.strip() and extra.strip() not in to:
            to.append(extra.strip())
    logger.info(f"PLAN DIGEST: {digest['counts']}; recipients: {to}")
    print(f"[PLAN_DIGEST] {subject}\n{body}")
    if not smtp_pass or not to:
        return {"email_sent": False, "recipients": to}
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return {"email_sent": True, "recipients": to}
    except Exception as e:
        logger.error(f"Failed to deliver the planning digest: {e}")
        return {"email_sent": False, "recipients": to}


NotificationService.send_plan_delay_digest = staticmethod(send_plan_delay_digest)
