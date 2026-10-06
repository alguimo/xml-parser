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
    bundle = extract_bundle(zip_path)
    record = parse_patient_xml(bundle.xml_bytes)
    return generate_pdf(
        record,
        output_dir,
        include_antecedents=include_antecedents,
        today=now.date(),
    )
