"""Shared conversion pipeline: ZIP in, PDF out.

This is the single place that ties the three real steps together, so both the
manual button and the folder watcher reuse the exact same logic.
"""

from datetime import datetime
from pathlib import Path

from app.extractor import extract_bundle
from app.parser import parse_patient_xml
from app.pdf_generator import generate_pdf


def convert_zip(
    zip_path: Path,
    output_dir: Path,
    include_antecedents: bool,
    now: datetime,
) -> Path:
    """Convert one WEDA export ZIP into a patient report PDF.

    Pipeline: extract the bundle from the ZIP, parse the Patient.xml into a
    structured record, then render that record as a PDF.

    Args:
        zip_path: Path to the WEDA export ZIP.
        output_dir: Folder where the generated PDF is written.
        include_antecedents: Whether medical history should appear in the PDF.
        now: Timestamp used for the file name (passed in so callers stay testable).

    Returns:
        The path to the generated PDF.

    Raises:
        FileNotFoundError: If the ZIP does not contain a Patient.xml.
    """
    bundle = extract_bundle(zip_path)
    record = parse_patient_xml(bundle.xml_bytes)
    return generate_pdf(
        record,
        output_dir,
        include_antecedents=include_antecedents,
        today=now.date(),
    )
