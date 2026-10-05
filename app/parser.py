import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from lxml import etree

from app.text_utils import html_to_rich, is_undefined_date

SEX_LABELS = {"1": "Masculin", "2": "Féminin"}
COMMUNICATION_KINDS = {"0": "Téléphone", "6": "E-mail"}
EVENT_KINDS = {"1": "Consultation", "3": "Lettre"}
# Fallback French label for Document sections without a Title field.
SECTION_FALLBACK_LABELS = {"1": "Compte rendu", "3": "Demande", "4": "Prescription"}

Section = Tuple[str, str]
Fee = Tuple[str, str, str]


@dataclass
class PatientData:
    last_name: str = ""
    first_name: str = ""
    full_name: str = ""
    sex: str = ""
    birth_date: str = ""
    birth_place: str = ""
    nir: str = ""
    nir_key: str = ""
    created_date: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class Antecedent:
    category: str
    label: str
    cim10: str = ""
    comment: str = ""


@dataclass
class Prescription:
    name: str
    dosage: str = ""


@dataclass
class Consultation:
    date: str
    kind: str
    user: str = ""
    title: str = ""
    sections: list[Section] = field(default_factory=list)
    vitals: list[Section] = field(default_factory=list)
    prescriptions: list[Prescription] = field(default_factory=list)
    fees: list[Fee] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


@dataclass
class PatientRecord:
    patient: PatientData
    antecedents: list[Antecedent] = field(default_factory=list)
    consultations: list[Consultation] = field(default_factory=list)


def parse_patient_xml(xml_bytes: bytes) -> PatientRecord:
    root = etree.fromstring(xml_bytes)
    onglet_titles = _build_onglet_titles(root)
    patient = _parse_patient(root)
    antecedents = _parse_antecedents(root, onglet_titles)
    consultations = _parse_consultations(root)
    return PatientRecord(
        patient=patient,
        antecedents=antecedents,
        consultations=consultations,
    )


def _build_onglet_titles(root: etree._Element) -> dict[str, str]:
    titles: dict[str, str] = {}
    for onglet in root.findall("Onglets/Onglet"):
        ong_id = _text(onglet, "OngID")
        titre = _text(onglet, "Titre")
        if ong_id and titre:
            titles[ong_id] = titre
    return titles


def _parse_patient(root: etree._Element) -> PatientData:
    def t(path: str) -> str:
        return _text(root, path)

    node = root.find("Patient")
    if node is None:
        node = root

    last_name = t("Nom")
    first_name = t("Prenom")
    full_name = t("NomPrenom") or f"{last_name} {first_name}".strip()
    sex = SEX_LABELS.get(t("LabelSexe"), "")

    address_lines: list[str] = []
    phone = ""
    email = ""
    addresses = node.findall("Adresses/Adresse")
    main_address = None
    pays = ""
    for adr in addresses:
        pays = pays or _text(adr, "Pays")
        if _text(adr, "Adresse1") and main_address is None:
            main_address = adr
    if main_address is not None:
        parts = [p for p in (
            _text(main_address, "Adresse1"),
            " ".join(p for p in (_text(main_address, "CodePostal"), _text(main_address, "Ville")) if p),
            pays,
        ) if p]
        address_lines.append(" - ".join(parts))
        address = address_lines[0] if address_lines else ""
    else:
        address = ""

    for comm in node.findall("Communications/Communication"):
        kind = COMMUNICATION_KINDS.get(_text(comm, "LabelType"))
        value = _text(comm, "Text")
        if not kind or not value:
            continue
        if kind == "Téléphone":
            phone = value
        elif kind == "E-mail":
            email = value

    return PatientData(
        last_name=last_name,
        first_name=first_name,
        full_name=full_name,
        sex=sex,
        birth_date=_clean_date(t("DateNaissance")),
        birth_place=t("LieuNaissance"),
        nir=t("Nir"),
        nir_key=t("NirCle"),
        created_date=_clean_date(t("DateCreated")),
        address=address,
        phone=phone,
        email=email,
    )


def _parse_antecedents(
    root: etree._Element, onglet_titles: dict[str, str]
) -> list[Antecedent]:
    antecedents: list[Antecedent] = []
    for node in root.findall("Antecedents/Antecedent"):
        label = _text(node, "Nom")
        if not label:
            continue
        ong_id = _text(node, "OngID")
        category = onglet_titles.get(ong_id, "Antécédents")
        antecedents.append(
            Antecedent(
                category=category,
                label=label,
                cim10=_text(node, "CIM10"),
                comment=_text(node, "Commentaire"),
            )
        )
    return antecedents


def _date_sort_key(value: str) -> tuple[int, datetime]:
    try:
        return (1, datetime.strptime(value, "%d/%m/%Y"))
    except (TypeError, ValueError):
        return (0, datetime.min)


def _parse_consultations(root: etree._Element) -> list[Consultation]:
    consultations: list[Consultation] = []
    for node in root.findall("Evenements/Evenement"):
        date_value = _clean_date(_text(node, "Date"))
        if is_undefined_date(_text(node, "Date")):
            continue
        event_kind_code = _text(node, "LabelType")
        consult = Consultation(
            date=date_value or _clean_date(_text(node, "DateCreated")),
            kind=EVENT_KINDS.get(event_kind_code, "Consultation"),
            user=_text(node, "UserInitial").upper(),
        )

        for doc in node.findall("Documents/Document"):
            _fill_document(consult, doc)

        for recette in node.findall("Recettes/Recette"):
            libelle = _text(recette, "Libelle")
            actes = _text(recette, "Actes")
            montant = _text(recette, "Montant")
            if libelle or actes or montant:
                consult.fees.append((libelle, actes, montant))

        for stream in node.findall("FileStreams/FileStream"):
            name = _text(stream, "Filename") or _text(stream, "Titre") or _text(stream, "LocalPath")
            if name:
                consult.attachments.append(name)

        if any(
            (consult.sections, consult.vitals, consult.prescriptions,
             consult.fees, consult.attachments)
        ):
            consultations.append(consult)

    consultations.sort(key=lambda c: _date_sort_key(c.date), reverse=True)
    return consultations


def _fill_document(consult: Consultation, doc: etree._Element) -> None:
    prescriptions = doc.findall("Prescriptions/Prescription")
    if prescriptions:
        for pres in prescriptions:
            name = _text(pres, "Name")
            if not name:
                continue
            dosage = _text(pres, "PosoText").strip(" |")
            consult.prescriptions.append(Prescription(name=name, dosage=dosage))
        # The structured Prescriptions already carry the readable data;
        # the matching Texte1 would only duplicate it.
        return

    title_default = _text(doc, "Titre")
    doc_type = _text(doc, "LabelType")
    for i in (1, 2, 3):
        raw_title = _text(doc, f"Title{i}")
        raw_text = _text(doc, f"Texte{i}")
        if not raw_text:
            continue
        text = html_to_rich(raw_text)
        if not text:
            continue
        if re.fullmatch(r"\s*V\d+\|\d+\|\s*", text):
            continue
        label = raw_title or (title_default if i == 1 else "")
        if not label:
            label = SECTION_FALLBACK_LABELS.get(doc_type, "")
        consult.sections.append((label, text))

    for suivi in doc.findall("Suivis/Suivi"):
        question = _text(suivi, "Question")
        reponse = _text(suivi, "Reponse")
        if question and reponse:
            consult.vitals.append((question, reponse))


def _text(node: Optional[etree._Element], path: str) -> str:
    if node is None:
        return ""
    child = node.find(path)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _clean_date(value: str) -> str:
    return "" if is_undefined_date(value) else value