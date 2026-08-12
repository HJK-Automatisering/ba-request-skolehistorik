"""Rendering af skabelonerne i templates/.

- report.html  → PDF via WeasyPrint
- mail_body.txt → mailens brødtekst

Begge er almindelige Jinja2-skabeloner og kan redigeres uden at røre koden.
"""

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from .db import Enrollment, Request

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def format_date_id(date_id: int | None) -> str:
    """Konverter et date_id i YYYYMMDD-format til dd.mm.yyyy.

    NULL og sentinel-værdier (0 / 99991231, dvs. "stadig indskrevet")
    vises som tom streng.
    """
    if not date_id:
        return ""
    s = str(date_id)
    if len(s) != 8 or s.startswith("9999"):
        return ""
    try:
        return datetime.strptime(s, "%Y%m%d").strftime("%d.%m.%Y")
    except ValueError:
        return ""


_env.filters["date_id"] = format_date_id


def render_pdf(request: Request, enrollments: list[Enrollment]) -> bytes:
    html = _env.get_template("report.html").render(
        request=request,
        enrollments=enrollments,
        generated_at=datetime.now().strftime("%d.%m.%Y kl. %H:%M"),
    )
    return HTML(string=html).write_pdf()


def render_mail_body(request: Request, enrollments: list[Enrollment]) -> str:
    """Mailens brødtekst. Skabelonen ligger i templates/mail_body.txt."""
    text = _env.get_template("mail_body.txt").render(
        request=request,
        bestilt=request.timestamp.strftime("%d.%m.%Y kl. %H:%M"),
        antal_indskrivninger=len(enrollments),
    )
    return text.strip() + "\n"
