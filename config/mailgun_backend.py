"""
Email backend that sends through the Mailgun HTTP API.

Useful where outbound SMTP is blocked. Enable with
EMAIL_BACKEND=config.mailgun_backend.MailgunBackend.
"""

from email.mime.base import MIMEBase

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class MailgunBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = settings.MAILGUN_API_KEY
        self.domain = settings.MAILGUN_DOMAIN
        self.base_url = settings.MAILGUN_BASE_URL.rstrip("/")
        self.timeout = getattr(settings, "EMAIL_TIMEOUT", 15)

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._send(message)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message):
        data = [("from", message.from_email), ("subject", message.subject)]
        data += [("to", address) for address in message.to]
        data += [("cc", address) for address in message.cc]
        data += [("bcc", address) for address in message.bcc]
        if message.reply_to:
            data.append(("h:Reply-To", ", ".join(message.reply_to)))
        for name, value in message.extra_headers.items():
            data.append((f"h:{name}", value))

        if message.content_subtype == "html":
            data.append(("html", message.body))
        else:
            data.append(("text", message.body))
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                data.append(("html", content))

        files = []
        for attachment in message.attachments:
            if isinstance(attachment, MIMEBase):
                filename = attachment.get_filename() or "attachment"
                content = attachment.get_payload(decode=True)
                mimetype = attachment.get_content_type()
            else:
                filename, content, mimetype = attachment
            if isinstance(content, str):
                content = content.encode("utf-8")
            files.append(
                ("attachment", (filename, content, mimetype or "application/octet-stream"))
            )

        response = requests.post(
            f"{self.base_url}/v3/{self.domain}/messages",
            auth=("api", self.api_key),
            data=data,
            files=files or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response
