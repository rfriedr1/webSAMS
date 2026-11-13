"""Render and send the sample-receipt confirmation e-mail.

Deliberately split into `render_confirmation` (pure, no I/O) and
`send_email` (does the SMTP call). The wizard renders first and shows
the result to the operator; **nothing is sent until they click Send.**
An import is not blocked by mail problems — the records are already
committed by the time this runs.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

#: Laboratory number prefix used in customer correspondence.
LAB_NUMBER_PREFIX = "MAMS-"


class EmailError(RuntimeError):
    """Raised when an e-mail cannot be rendered or delivered."""


_ADDRESS_SEPARATORS = re.compile(r"[,;\s]+")
_PLAIN_ADDRESS = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")


def split_addresses(value: Any) -> list[str]:
    """A list of addresses from text or a list, in order, without repeats.

    Accepts commas, semicolons, spaces and line breaks as separators —
    Outlook users type semicolons, and the Setup field used to say
    "commas only". Repeats (ignoring case) are dropped.
    """
    if value is None:
        return []
    parts = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for address in _ADDRESS_SEPARATORS.split(str(part or "")):
            address = address.strip()
            if address and address.lower() not in seen:
                seen.add(address.lower())
                result.append(address)
    return result


def invalid_addresses(addresses: list[str]) -> list[str]:
    """The entries that are not a plain `name@domain.tld` address."""
    return [a for a in addresses if not _PLAIN_ADDRESS.match(a)]


@dataclass
class RenderedEmail:
    to_address: str
    subject: str
    body: str
    from_address: str = ""
    from_name: str = ""
    reply_to: str = ""
    cc: str = ""
    bcc: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "to_address": self.to_address,
            "subject": self.subject,
            "body": self.body,
            "from_address": self.from_address,
            "from_name": self.from_name,
            "reply_to": self.reply_to,
            "cc": split_addresses(self.cc),
            "bcc": split_addresses(self.bcc),
        }

    def recipients(self) -> list[str]:
        """Every address the message goes to: To, then Cc, then Bcc."""
        return split_addresses([self.to_address, self.cc, self.bcc])


def format_sample_list(sample_nrs: list[int], labels: list[str] | None = None) -> str:
    """One line per sample: lab number, then the submitter's own label.

    Customers identify samples by their own naming, so pairing the two
    is what makes the mail useful to them.
    """
    labels = labels or []
    lines: list[str] = []
    for index, sample_nr in enumerate(sample_nrs):
        label = labels[index] if index < len(labels) else ""
        number = f"{LAB_NUMBER_PREFIX}{sample_nr}"
        lines.append(f"  {number}    {label}".rstrip())
    return "\n".join(lines)


def render_confirmation(
    template: dict[str, str],
    *,
    context: dict[str, Any],
) -> tuple[str, str]:
    """Substitute placeholders into a template's subject and body.

    Uses `str.replace` rather than `str.format` on purpose: templates are
    operator-authored free text and will contain stray braces (German
    quotes, JSON snippets pasted in). `format` would raise KeyError on
    those; this degrades gracefully and leaves unknown placeholders
    visible so the operator can spot the typo in the preview.
    """
    subject = str(template.get("subject", ""))
    body = str(template.get("body", ""))
    for key, value in context.items():
        token = "{" + key + "}"
        subject = subject.replace(token, str(value))
        body = body.replace(token, str(value))
    return subject, body


def build_confirmation(
    *,
    template: dict[str, str],
    settings: dict[str, Any],
    submitter: Any,
    project_nr: int,
    project_name: str,
    sample_nrs: list[int],
    sample_labels: list[str] | None = None,
) -> RenderedEmail:
    """Render the confirmation e-mail for a completed import."""
    first = (getattr(submitter, "first_name", "") or "").strip()
    last = (getattr(submitter, "last_name", "") or "").strip()
    display = f"{first} {last}".strip() or "Sir or Madam"

    context = {
        "submitter_name": display,
        "submitter_first_name": first,
        "submitter_last_name": last,
        "salutation": (getattr(submitter, "salutation", "") or "").strip(),
        "project_nr": project_nr,
        "project_name": project_name,
        "sample_count": len(sample_nrs),
        "sample_list": format_sample_list(sample_nrs, sample_labels),
        "lab_name": settings.get("from_name", "") or "",
    }
    subject, body = render_confirmation(template, context=context)

    return RenderedEmail(
        to_address=(getattr(submitter, "email", "") or "").strip(),
        subject=subject,
        body=body,
        from_address=str(settings.get("from_address", "") or ""),
        from_name=str(settings.get("from_name", "") or ""),
        reply_to=str(settings.get("reply_to", "") or ""),
        cc=", ".join(split_addresses(settings.get("cc"))),
        bcc=", ".join(split_addresses(settings.get("bcc"))),
    )


def send_email(message: RenderedEmail, settings: dict[str, Any]) -> None:
    """Deliver one message over SMTP.

    Raises `EmailError` with an operator-readable explanation on any
    failure — the caller reports it in the UI without rolling anything
    back, because the import itself has already been committed.
    """
    host = str(settings.get("smtp_host") or "").strip()
    if not host:
        raise EmailError("No SMTP server is configured. Set one up in Setup → E-mail.")
    if not message.to_address:
        raise EmailError("The submitter has no e-mail address, so nothing can be sent.")
    if not message.from_address:
        raise EmailError("No sender address is configured. Set one up in Setup → E-mail.")
    for label, value in (("To", message.to_address), ("Cc", message.cc), ("Bcc", message.bcc)):
        bad = invalid_addresses(split_addresses(value))
        if bad:
            raise EmailError(
                f"{label}: {', '.join(bad)} is not an e-mail address. Correct it and send again."
            )

    try:
        port = int(settings.get("smtp_port") or 587)
    except (TypeError, ValueError):
        port = 587
    security = str(settings.get("smtp_security") or "starttls").lower()
    user = str(settings.get("smtp_user") or "").strip()
    password = str(settings.get("smtp_password") or "")

    email = EmailMessage()
    email["Subject"] = message.subject
    email["From"] = (
        f"{message.from_name} <{message.from_address}>"
        if message.from_name
        else message.from_address
    )
    email["To"] = ", ".join(split_addresses(message.to_address))
    if message.reply_to:
        email["Reply-To"] = message.reply_to
    # Bcc gets no header: its addresses go only into the SMTP envelope
    # (`recipients()`), so the customer never sees them.
    cc = split_addresses(message.cc)
    if cc:
        email["Cc"] = ", ".join(cc)
    email.set_content(message.body)

    try:
        if security == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(email, to_addrs=message.recipients())
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                if user:
                    smtp.login(user, password)
                smtp.send_message(email, to_addrs=message.recipients())
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(
            "The mail server rejected the username or password. Check Setup → E-mail."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        refused = ", ".join(sorted(exc.recipients)) or message.to_address
        raise EmailError(f"The mail server refused the address {refused}.") from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise EmailError(f"Could not reach the mail server: {exc}") from exc


__all__ = [
    "LAB_NUMBER_PREFIX",
    "EmailError",
    "RenderedEmail",
    "build_confirmation",
    "format_sample_list",
    "invalid_addresses",
    "render_confirmation",
    "send_email",
    "split_addresses",
]
