import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.parser import Antecedent, PatientData, PatientRecord, Prescription
from app.text_utils import output_filename

TOP_MARGIN = 15 * mm
BOTTOM_MARGIN = 15 * mm
RIGHT_MARGIN = 15 * mm
LEFT_MARGIN = 15 * mm
CONTENT_WIDTH = A4[0] - LEFT_MARGIN - RIGHT_MARGIN
CONTENT_HEIGHT = A4[1] - TOP_MARGIN - BOTTOM_MARGIN

SIDE_RATIO = 0.66
COLUMN_PADDING = 4 * mm
SIDE_RULE = True
PAGE_SAFETY = 4  # pt kept free so a hand-paginated page never overflows
MAIN_WIDTH = (CONTENT_WIDTH - 2 * COLUMN_PADDING) * SIDE_RATIO
SIDE_WIDTH = (CONTENT_WIDTH - 2 * COLUMN_PADDING) * (1 - SIDE_RATIO)
ENTRY_SEPARATOR = " — "
ENTRY_INDENT = 3 * mm

ACCENT = "#1f3b63"
ACCENT_MID = "#2f4f7f"
ACCENT_LIGHT = "#eef2f8"
GRID = "#c8d2e0"
SUBTLE = colors.HexColor("#6b7280")

GENERATOR_LABEL = "Convertisseur WEDA"
BLOCK_PATIENT = "Données patient"
BLOCK_ANTECEDENTS = "Antécédents"
BLOCK_TREATMENT = "Traitement (ordonances)"
BLOCK_CONSULTATIONS = "Consultations"

LABELS = {
    "full_name": "Nom complet",
    "sex": "Sexe",
    "birth_date": "Date de naissance",
    "birth_place": "Lieu de naissance",
    "nir": "NIR",
    "nir_key": "Clé NIR",
    "created_date": "Date de création du dossier",
    "address": "Adresse",
    "phone": "Téléphone",
    "email": "E-mail",
}
VITAL_HEADERS = ("Mesure", "Valeur")
FEES_HEADERS = ("Libellé", "Acte", "Montant")
NO_ANTECEDENTS = "Aucun antécédent renseigné."
NO_PRESCRIPTIONS = "Aucune prescription enregistrée."
NO_CONSULTATIONS = "Aucune consultation enregistrée."
ATTACHMENTS_TITLE = "Documents liés:"
FEE_SUFFIX = "€"
# French plural heading used only for the secondary kinds of block "Consultations".
GROUP_LABELS = {"Lettre": "Courriers"}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title2",
        parent=base["Title"],
        fontSize=16,
        leading=19,
        spaceAfter=2,
        alignment=TA_LEFT,
    )
    section = ParagraphStyle(
        "Section",
        parent=base["Heading2"],
        fontSize=12,
        leading=15,
        spaceBefore=14,
        spaceAfter=6,
        textColor=colors.HexColor(ACCENT),
    )
    sub = ParagraphStyle(
        "Sub",
        parent=base["Heading3"],
        fontSize=10.5,
        leading=13,
        spaceBefore=8,
        spaceAfter=3,
        textColor=colors.HexColor(ACCENT_MID),
    )
    group = ParagraphStyle(
        "Group",
        parent=base["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        spaceBefore=6,
        spaceAfter=1,
        textColor=colors.HexColor(ACCENT_MID),
    )
    entry_bold = ParagraphStyle(
        "EntryBold",
        parent=base["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10.5,
        spaceBefore=4,
        spaceAfter=0,
    )
    entry_text = ParagraphStyle(
        "EntryText",
        parent=base["BodyText"],
        fontSize=8,
        leading=10,
        leftIndent=ENTRY_INDENT,
        spaceAfter=0,
        textColor=SUBTLE,
    )
    body = ParagraphStyle(
        "Body9",
        parent=base["BodyText"],
        fontSize=9,
        leading=12,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "Small9", parent=base["BodyText"], fontSize=8, leading=10, textColor=colors.grey
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=base["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor(ACCENT),
    )
    return {
        "title": title,
        "section": section,
        "sub": sub,
        "group": group,
        "entry_bold": entry_bold,
        "entry_text": entry_text,
        "body": body,
        "small": small,
        "table_header": table_header,
    }


def _table(
    data: list[list], headers: list[str], styles: dict, widths=None
) -> Table:
    rows = [[Paragraph(f"<b>{h}</b>", styles["table_header"]) for h in headers]]
    rows += [[Paragraph(str(c), styles["small"]) for c in row] for row in data]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT_LIGHT)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _patient_blocks(p: PatientData, styles: dict) -> list[Paragraph]:
    rows = []
    for key, label in LABELS.items():
        value = getattr(p, key, "")
        if value:
            rows.append([Paragraph(f"<b>{label}</b>", styles["body"]), Paragraph(value, styles["body"])])
    if not rows:
        return []
    table = Table(rows, colWidths=[MAIN_WIDTH * 0.42, MAIN_WIDTH * 0.58])
    return [table]


def _antecedent_entry(ant: Antecedent, styles: dict) -> list:
    heading = ant.label
    if ant.cim10:
        heading += f'{ENTRY_SEPARATOR}<font color="{ACCENT_MID}">{ant.cim10}</font>'
    if ant.comment:
        heading += " :"
    blocks = [Paragraph(heading, styles["entry_bold"])]
    if ant.comment:
        blocks.append(Paragraph(ant.comment, styles["entry_text"]))
    return blocks


def _prescription_entry(rx: Prescription, styles: dict) -> list:
    blocks = [Paragraph(rx.name, styles["entry_bold"])]
    if rx.dosage:
        blocks.append(Paragraph(rx.dosage, styles["entry_text"]))
    return blocks


def _antecedent_blocks(antecedents: list[Antecedent], styles: dict) -> list:
    if not antecedents:
        return [Paragraph(NO_ANTECEDENTS, styles["body"])]

    blocks: list = []
    categories: list[tuple[str, list[Antecedent]]] = []
    order: dict[str, int] = {}
    for ant in antecedents:
        idx = order.setdefault(ant.category, len(order))
        if len(categories) <= idx:
            categories.append((ant.category, []))
        categories[idx][1].append(ant)

    for category, items in categories:
        blocks.append(Paragraph(category.upper(), styles["group"]))
        for ant in items:
            blocks.extend(_antecedent_entry(ant, styles))
    return blocks


def _treatment_blocks(record: PatientRecord, styles: dict) -> list:
    consult_with_rx = [c for c in record.consultations if c.prescriptions]
    if not consult_with_rx:
        return [Paragraph(NO_PRESCRIPTIONS, styles["body"])]
    blocks: list = []
    for consult in consult_with_rx:
        blocks.append(Paragraph(consult.date, styles["group"]))
        for rx in consult.prescriptions:
            blocks.extend(_prescription_entry(rx, styles))
    return blocks


def _consultation_blocks(record: PatientRecord, styles: dict) -> list:
    consultations = record.consultations
    if not consultations:
        return [Paragraph(NO_CONSULTATIONS, styles["body"])]

    kinds = list(dict.fromkeys(c.kind for c in consultations))
    priority = {"Consultation": 0, "Lettre": 1}
    kinds = sorted(
        kinds, key=lambda k: (priority.get(k, 99), kinds.index(k))
    )
    show_groups = len(kinds) > 1
    blocks: list = []
    for kind in kinds:
        entries = [c for c in consultations if c.kind == kind]
        if not entries:
            continue
        if show_groups and kind != kinds[0]:
            blocks.append(Paragraph(GROUP_LABELS.get(kind, kind), styles["sub"]))
        for c in entries:
            heading = f"{c.date} — {c.kind}"
            if c.user:
                heading += f" ({c.user})"
            blocks.append(Paragraph(heading, styles["sub"]))

            for section_title, text in c.sections:
                if section_title:
                    blocks.append(Paragraph(section_title, styles["body"]))
                for line in text.split("\n"):
                    blocks.append(Paragraph(line, styles["body"]))

            if c.vitals:
                blocks.append(
                    _table(
                        c.vitals,
                        VITAL_HEADERS,
                        styles,
                        widths=[MAIN_WIDTH * 0.28, MAIN_WIDTH * 0.72],
                    )
                )

            if c.fees:
                rows = [[lib, acte, f"{montant} {FEE_SUFFIX}"] for lib, acte, montant in c.fees]
                blocks.append(
                    _table(
                        rows,
                        FEES_HEADERS,
                        styles,
                        widths=[MAIN_WIDTH * 0.44, MAIN_WIDTH * 0.28, MAIN_WIDTH * 0.28],
                    )
                )

            if c.attachments:
                blocks.append(Spacer(1, 2))
                blocks.append(Paragraph(ATTACHMENTS_TITLE, styles["body"]))
                for name in c.attachments:
                    blocks.append(Paragraph(f"• {name}", styles["small"]))

            blocks.append(Spacer(1, 6))
    return blocks


def _footer(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - RIGHT_MARGIN, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _paginate(flowables: list, width: float, avail_height: float) -> list[list]:
    limit = max(avail_height - PAGE_SAFETY, 1)
    pages: list[list] = []
    current: list = []
    used = 0.0
    queue = list(flowables)
    while queue:
        flow = queue.pop(0)
        _, height = flow.wrap(width, limit)
        space = flow.getSpaceBefore() + flow.getSpaceAfter()
        if current and used + height + space > limit:
            pages.append(current)
            current, used = [], 0.0
        if height > limit:
            room = limit - used
            parts = flow.split(width, room) or flow.split(width, limit)
            if parts and len(parts) > 1:
                queue = list(parts[1:]) + queue
                current.append(parts[0])
                pages.append(current)
                current, used = [], 0.0
                continue
        current.append(flow)
        used += height + space
    if current:
        pages.append(current)
    return pages or [[]]


def _column_page(main: list, side: list) -> Table:
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), COLUMN_PADDING),
        ("LEFTPADDING", (1, 0), (1, -1), COLUMN_PADDING),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if SIDE_RULE:
        style.append(("LINEBEFORE", (1, 0), (1, -1), 0.4, colors.HexColor(GRID)))
    return Table(
        [[main, side]],
        colWidths=[MAIN_WIDTH + COLUMN_PADDING, SIDE_WIDTH + COLUMN_PADDING],
        style=TableStyle(style),
        splitByRow=0,
        splitInRow=0,
    )


def _two_column_layout(main: list, side: list, avail_height: float) -> list:
    if not side:
        return main
    main_pages = _paginate(main, MAIN_WIDTH, avail_height)
    side_pages = _paginate(side, SIDE_WIDTH, avail_height)
    story: list = []
    for index in range(max(len(main_pages), len(side_pages))):
        if index:
            story.append(PageBreak())
        main_cell = main_pages[index] if index < len(main_pages) else []
        side_cell = side_pages[index] if index < len(side_pages) else []
        story.append(_column_page(main_cell, side_cell))
    return story


def generate_pdf(
    record: PatientRecord,
    output_dir: Path,
    include_antecedents: bool = True,
    today: Optional[date] = None,
) -> Path:
    styles = _styles()
    p = record.patient
    today = today or date.today()
    filename = output_filename(p.last_name or "Patient", p.first_name or "", today)
    if not p.last_name and not p.first_name:
        filename = f"patient_{today:%d%m%Y}.pdf"
    output_path = output_dir / filename

    output_dir.mkdir(parents=True, exist_ok=True)
    # Build next to the final file so os.replace stays atomic and same-filesystem.
    fd, tmp_name = tempfile.mkstemp(
        dir=output_dir, prefix=f".{filename}.", suffix=".tmp"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        doc = BaseDocTemplate(
            str(tmp_path),
            pagesize=A4,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title=f"Rapport patient — {p.full_name or p.last_name}",
            author=GENERATOR_LABEL,
        )
        frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            CONTENT_HEIGHT,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        doc.addPageTemplates(
            [PageTemplate(id="body", frames=[frame], onPage=_footer)]
        )

        patient_blocks = _patient_blocks(p, styles)

        main: list = [
            Paragraph(p.full_name or p.last_name, styles["title"]),
            Spacer(1, 6),
        ]
        if patient_blocks:
            main.append(Paragraph(BLOCK_PATIENT, styles["section"]))
            main.extend(patient_blocks)

        side: list = []
        if include_antecedents and record.antecedents:
            side.append(Paragraph(BLOCK_ANTECEDENTS, styles["section"]))
            side.extend(_antecedent_blocks(record.antecedents, styles))

        treatment = [Paragraph(BLOCK_TREATMENT, styles["section"])]
        treatment.extend(_treatment_blocks(record, styles))
        has_prescriptions = any(c.prescriptions for c in record.consultations)
        if side or has_prescriptions:
            side.extend(treatment)
        else:
            main.extend(treatment)

        main.append(Paragraph(BLOCK_CONSULTATIONS, styles["section"]))
        main.extend(_consultation_blocks(record, styles))

        doc.build(_two_column_layout(main, side, CONTENT_HEIGHT))
        os.replace(tmp_path, output_path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return output_path
