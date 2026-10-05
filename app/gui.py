from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from typing import Optional

from app.extractor import extract_bundle
from app.parser import parse_patient_xml
from app.pdf_generator import generate_pdf

APP_TITLE = "Convertisseur ZIP en PDF"
DROP_HINT = "Déposez un fichier ZIP ici"
ZIP_HINT = "Export WEDA"
CHECKBOX_LABEL = "Inclure les antécédents"
SETTINGS_LABEL = "Paramètres"
CONVERT_LABEL = "Convertir"
OUTPUT_FOLDER_LABEL = "Dossier de destination"
DND_UNAVAILABLE = "drag & drop indisponible"
DND_PICK = "Ou cliquez pour choisir le fichier"
CHOOSE_ZIP_TITLE = "Choisir le fichier ZIP (export WEDA)"
CHOOSE_FOLDER_TITLE = "Choisir le dossier de destination"
CONVERT_OK = "PDF généré:\n"
CONVERT_KO = "Conversion impossible:\n"
NO_ZIP = "Aucun fichier ZIP sélectionné"


class SettingsModal(ctk.CTkToplevel):
    def __init__(self, master: "App") -> None:
        super().__init__(master)
        self.title(SETTINGS_LABEL)
        self.resizable(False, False)

        ctk.CTkLabel(self, text=OUTPUT_FOLDER_LABEL).pack(padx=24, pady=(20, 5))
        self.folder_label = ctk.CTkLabel(self, text=str(master.output_dir))
        self.folder_label.pack(padx=24)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=16)
        ctk.CTkButton(row, text="Choisir…", command=lambda: self._pick(master)).pack(side="left", padx=6)
        ctk.CTkButton(row, text="OK", command=self.destroy).pack(side="left", padx=6)

    def _pick(self, master: "App") -> None:
        chosen = filedialog.askdirectory(initialdir=str(master.output_dir))
        if chosen:
            master.output_dir = Path(chosen)
            self.folder_label.configure(text=chosen)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("520x340")
        self.output_dir = Path.home() / "Desktop"
        self.zip_path: Optional[str] = None

        self.drop_zone = ctk.CTkButton(
            self,
            text=f"{DROP_HINT}\n{ZIP_HINT}",
            height=150,
            corner_radius=10,
            fg_color="transparent",
            border_width=2,
            border_color="#3a7ebf",
            hover_color="#2f6aac",
            command=self.pick_zip,
        )
        self.drop_zone.pack(padx=30, pady=24, fill="x")

        self.include_antecedents = ctk.CTkCheckBox(self, text=CHECKBOX_LABEL)
        self.include_antecedents.select()
        self.include_antecedents.pack(pady=4)

        self.status = ctk.CTkLabel(self, text="", text_color="grey")
        self.status.pack(pady=2)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=12)
        ctk.CTkButton(
            button_row, text=SETTINGS_LABEL, command=self.open_settings
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            button_row, text=CONVERT_LABEL, command=self.convert
        ).pack(side="left", padx=5)

        self._setup_drag_and_drop()

    def _setup_drag_and_drop(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            TkinterDnD._require(self)  # noqa: SLF001
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self.on_drop)
        except Exception:
            self.drop_zone.configure(
                text=f"{DROP_HINT}\n{DND_PICK}\n({DND_UNAVAILABLE})"
            )

    def pick_zip(self) -> None:
        chosen = filedialog.askopenfilename(title=CHOOSE_ZIP_TITLE, filetypes=[("ZIP", "*.zip")])
        if chosen:
            self.set_zip(chosen)

    def on_drop(self, event) -> None:  # noqa: ANN001
        first = event.data.split()[0].strip("{}")
        if first.lower().endswith(".zip"):
            self.set_zip(first)
        else:
            self.status.configure(text="Fichier ZIP attendu", text_color="#c0392b")

    def set_zip(self, path: str) -> None:
        self.zip_path = path
        self.drop_zone.configure(text=f"{Path(path).name}")
        self.status.configure(text=path, text_color="grey")

    def open_settings(self) -> None:
        SettingsModal(self)

    def convert(self) -> None:
        if not self.zip_path:
            self.status.configure(text=NO_ZIP, text_color="#c0392b")
            return
        try:
            bundle = extract_bundle(Path(self.zip_path))
            record = parse_patient_xml(bundle.xml_bytes)
            output = generate_pdf(
                record,
                self.output_dir,
                include_antecedents=bool(self.include_antecedents.get()),
            )
            self.status.configure(text=str(output), text_color="#27ae60")
            messagebox.showinfo(APP_TITLE, f"{CONVERT_OK}{output}")
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text="Erreur", text_color="#c0392b")
            messagebox.showerror(APP_TITLE, f"{CONVERT_KO}{exc}")


def run() -> None:
    ctk.set_appearance_mode("system")
    app = App()
    app.mainloop()