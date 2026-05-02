"""Server-rendered PDF for the vehicle service-history export.

Wraps reportlab so the router stays small and the PDF format lives in
one place. The output is a tabular layout matching the mobile app's
list view: kind, noted_at, title, mileage, cost, location, note.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.vehicles.models import VehicleServiceLog


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value is not None else ""


def _fmt_int(value: int | None, suffix: str = "") -> str:
    if value is None:
        return ""
    return f"{value:,}{suffix}"


def render_service_history_pdf(
    *,
    plate: str,
    make: str | None,
    model: str | None,
    logs: Iterable[VehicleServiceLog],
) -> bytes:
    """Return a PDF byte payload for `logs`. Empty list still renders an empty doc."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Service history — {plate}",
    )
    styles = getSampleStyleSheet()
    story: list[object] = []

    title_text = f"Service history — {plate}"
    if make or model:
        title_text += f" ({make or ''} {model or ''})".rstrip()
    story.append(Paragraph(title_text, styles["Title"]))
    story.append(Spacer(1, 0.3 * cm))

    headers = ["Date", "Kind", "Title", "Mileage", "Cost (MNT)", "Location", "Note"]
    rows: list[list[str]] = [headers]
    for log in logs:
        rows.append(
            [
                _fmt_dt(log.noted_at),
                log.kind.value,
                log.title or "",
                _fmt_int(log.mileage_km, " km"),
                _fmt_int(log.cost_mnt),
                log.location or "",
                log.note or "",
            ]
        )

    if len(rows) == 1:
        story.append(Paragraph("(No service entries yet.)", styles["BodyText"]))
    else:
        table = Table(rows, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(table)

    doc.build(story)
    return buffer.getvalue()
