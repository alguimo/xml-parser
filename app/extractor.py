from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile


@dataclass
class ExtractedBundle:
    xml_bytes: bytes
    attachments: dict[str, bytes] = field(default_factory=dict)


def extract_bundle(zip_path: Path) -> ExtractedBundle:
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
