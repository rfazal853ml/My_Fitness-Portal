import smtplib
from email.message import EmailMessage
from typing import Optional

from config import get_settings

settings = get_settings()


class EmailService:
    @staticmethod
    def send_password_reset_otp(to_email: str, otp: str, user_name: Optional[str] = None) -> None:
        if not settings.smtp_host or not settings.smtp_sender_email:
            raise RuntimeError("SMTP host and sender email must be configured.")

        if not settings.smtp_username or not settings.smtp_password:
            raise RuntimeError("SMTP username or password is not configured.")

        subject = "Your password reset OTP"
        name = user_name or "User"
        body = (
            f"Hello {name},\n\n"
            "You requested a password reset. Use the OTP below to continue:\n\n"
            f"{otp}\n\n"
            "This code is valid for 10 minutes. If you did not request this, please ignore this email.\n\n"
            "Thank you,\n"
            f"{settings.app_name} Team"
        )

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_sender_email
        message["To"] = to_email
        message.set_content(body)

        if settings.smtp_use_ssl:
            smtp_class = smtplib.SMTP_SSL
        else:
            smtp_class = smtplib.SMTP

        server = smtp_class(settings.smtp_host, settings.smtp_port, timeout=20)
        try:
            server.ehlo()
            if not settings.smtp_use_ssl and settings.smtp_use_tls:
                server.starttls()
                server.ehlo()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        finally:
            try:
                server.quit()
            except Exception:
                pass
