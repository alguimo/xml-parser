"""Unpack a WEDA export ZIP into the raw pieces the rest of the app needs."""

from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile


@dataclass
class ExtractedBundle:
    """Result of opening an export ZIP.

    Attributes:
        xml_bytes: Raw bytes of the Patient.xml file.
        attachments: PDF files found in the ZIP, keyed by file name. They are
            only listed in the report, never embedded.
    """

    xml_bytes: bytes
    attachments: dict[str, bytes] = field(default_factory=dict)


def extract_bundle(zip_path: Path) -> ExtractedBundle:
    """Read the export ZIP without unpacking it to disk.

    Finds the Patient.xml (the parser's contract) and collects the sibling PDF
    attachments so the report can mention them as references.

    Raises:
        FileNotFoundError: If no file ending in "Patient.xml" is present.
    """
    with ZipFile(zip_path) as zf:
        xml_names = [n for n in zf.namelist() if n.endswith("Patient.xml")]
        if not xml_names:
            raise FileNotFoundError("Patient.xml not found in ZIP")
        xml_bytes = zf.read(xml_names[0])
        attachments = {
            Path(n).name: zf.read(n)
            for n in zf.namelist()
            if n.lower().endswith(".pdf")
        }
    return ExtractedBundle(xml_bytes=xml_bytes, attachments=attachments)
