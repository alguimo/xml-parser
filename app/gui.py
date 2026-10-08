"""CustomTkinter GUI: pick a ZIP, convert it, and optionally watch a folder.

`run()` is the entry point called by `main.py`. The GUI only collects paths and
settings; the real conversion is delegated to `conversion_service.convert_zip`
(directly for the button, or through `folder_watcher` for automatic mode).
"""

from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from typing import Optional

from app.config_store import AppConfig, load_config, save_config
from app.conversion_service import convert_zip
from app.folder_watcher import (
    EVENT_ERROR,
    EVENT_IGNORED,
    EVENT_INACCESSIBLE,
    EVENT_SUCCESS,
    POLL_INTERVAL_MS,
    FolderWatcher,
    WatcherEvent,
    scan_zip_entries,
)

APP_TITLE = "Convertisseur ZIP en PDF"
DROP_HINT = "Déposez un fichier ZIP ici"
ZIP_HINT = "Export WEDA"
CHECKBOX_LABEL = "Inclure les antécédents"
SETTINGS_LABEL = "Paramètres"
CONVERT_LABEL = "Convertir"
OUTPUT_FOLDER_LABEL = "Dossier de destination"
WATCHED_FOLDER_LABEL = "Dossier surveillé"
WATCH_TOGGLE_LABEL = "Conversion automatique"
CHOOSE_LABEL = "Choisir…"
CHOOSE_ZIP_TITLE = "Choisir le fichier ZIP (export WEDA)"
CHOOSE_FOLDER_TITLE = "Choisir le dossier de destination"
CHOOSE_WATCHED_TITLE = "Choisir le dossier à surveiller"
WATCHED_NONE = "Aucun dossier sélectionné"
WATCH_DIR_REQUIRED = "Veuillez choisir un dossier à surveiller valide."
OUTPUT_DIR_REQUIRED = "Veuillez choisir un dossier de destination valide."
CONVERT_OK = "PDF généré:\n"
CONVERT_KO = "Conversion impossible:\n"
NO_ZIP = "Aucun fichier ZIP sélectionné"
WATCH_STATE_ON = "Vigilance activée"
WATCH_STATE_OFF = "Vigilance désactivée"
WATCH_SUCCESS = "Conversion automatique réussie:\n"
WATCH_ERROR = "Échec de la conversion automatique:\n"
WATCH_IGNORED = "ZIP ignoré (pas d'export WEDA):\n"
WATCH_INACCESSIBLE = "Dossier inaccessible. Nouvelle tentative…"
DND_UNAVAILABLE = "drag & drop indisponible"
DND_PICK = "Ou cliquez pour choisir le fichier"


class SettingsModal(ctk.CTkToplevel):
    """Modal window to choose the watched/output folders and toggle auto mode."""

    def __init__(self, master: "App") -> None:
        super().__init__(master)
        self.title(SETTINGS_LABEL)
        self.transient(master)
        self.master_app = master

        ctk.CTkLabel(self, text=WATCHED_FOLDER_LABEL).pack(padx=24, pady=(20, 5))
        self.watched_label = ctk.CTkLabel(
            self, text=str(master.watched_dir) if master.watched_dir else WATCHED_NONE
        )
        self.watched_label.pack(padx=24)
        watched_row = ctk.CTkFrame(self, fg_color="transparent")
        watched_row.pack(pady=8)
        ctk.CTkButton(
            watched_row, text=CHOOSE_LABEL, command=self._pick_watched
        ).pack(side="left", padx=6)

        ctk.CTkLabel(self, text=OUTPUT_FOLDER_LABEL).pack(padx=24, pady=(12, 5))
        self.folder_label = ctk.CTkLabel(self, text=str(master.output_dir))
        self.folder_label.pack(padx=24)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=8)
        ctk.CTkButton(
            row, text=CHOOSE_LABEL, command=self._pick_output
        ).pack(side="left", padx=6)

        self.watch_toggle = ctk.CTkCheckBox(
            self, text=WATCH_TOGGLE_LABEL, command=self._toggle_watch
        )
        if master.watch_enabled:
            self.watch_toggle.select()
        self.watch_toggle.pack(pady=(14, 6))

        ctk.CTkButton(self, text="OK", command=self.destroy).pack(pady=(6, 20))

        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")
        self.resizable(True, True)

    def _pick_watched(self) -> None:
        """Ask for the folder to watch, then save and restart the watcher."""
        initial = str(self.master_app.watched_dir or Path.home())
        chosen = filedialog.askdirectory(
            title=CHOOSE_WATCHED_TITLE, initialdir=initial
        )
        if chosen:
            self.master_app.watched_dir = Path(chosen)
            self.watched_label.configure(text=chosen)
            self.master_app.persist_config()
            self.master_app.restart_watch()

    def _pick_output(self) -> None:
        """Ask for the PDF destination folder, then save and restart watcher."""
        chosen = filedialog.askdirectory(
            title=CHOOSE_FOLDER_TITLE, initialdir=str(self.master_app.output_dir)
        )
        if chosen:
            self.master_app.output_dir = Path(chosen)
            self.folder_label.configure(text=chosen)
            self.master_app.persist_config()
            self.master_app.restart_watch()

    def _toggle_watch(self) -> None:
        """Turn automatic mode on/off, prompting for missing folders first."""
        if not self.watch_toggle.get():
            self.master_app.disable_watch()
            return
        # Cannot enable without a valid input and output folder: warn and ask.
        if not self.master_app.watched_dir_valid():
            messagebox.showwarning(APP_TITLE, WATCH_DIR_REQUIRED)
            self.watch_toggle.deselect()
            self._pick_watched()
            return
        if not self.master_app.output_dir_valid():
            messagebox.showwarning(APP_TITLE, OUTPUT_DIR_REQUIRED)
            self.watch_toggle.deselect()
            self._pick_output()
            return
        self.master_app.enable_watch()


class App(ctk.CTk):
    """Main window: drop zone, options, status labels and action buttons."""

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        # Load remembered settings; default the output folder to the Desktop.
        config = load_config()
        self.output_dir = config.output_dir or (Path.home() / "Desktop")
        self.watched_dir: Optional[Path] = config.watched_dir
        self.watch_enabled: bool = config.watch_enabled
        self.zip_path: Optional[str] = None
        self.watcher: Optional[FolderWatcher] = None
        self._tick_job: Optional[str] = None

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

        self.include_antecedents = ctk.CTkCheckBox(
            self, text=CHECKBOX_LABEL, command=self.on_include_antecedents_change
        )
        self.include_antecedents.select()
        self.include_antecedents.pack(pady=4)

        self.status = ctk.CTkLabel(self, text="", text_color="grey")
        self.status.pack(pady=2)

        self.watch_state = ctk.CTkLabel(
            self, text=WATCH_STATE_OFF, text_color="grey"
        )
        self.watch_state.pack(pady=2)
        self.watch_status = ctk.CTkLabel(
            self, text="", text_color="grey", wraplength=460, justify="left"
        )
        self.watch_status.pack(pady=2)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=12)
        ctk.CTkButton(
            button_row, text=SETTINGS_LABEL, command=self.open_settings
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            button_row, text=CONVERT_LABEL, command=self.convert
        ).pack(side="left", padx=5)

        self._setup_drag_and_drop()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.watch_enabled:
            self.start_watch()

        self.update_idletasks()
        width = max(520, self.winfo_reqwidth())
        height = min(self.winfo_reqheight(), self.winfo_screenheight() - 120)
        self.geometry(f"{width}x{height}")
        self.minsize(520, 300)
        self.resizable(True, True)

    def _setup_drag_and_drop(self) -> None:
        """Enable drag & drop if tkinterdnd2 works; otherwise show a hint."""
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
        """Open a file dialog to choose the ZIP (used when clicking the zone)."""
        chosen = filedialog.askopenfilename(title=CHOOSE_ZIP_TITLE, filetypes=[("ZIP", "*.zip")])
        if chosen:
            self.set_zip(chosen)

    def on_drop(self, event) -> None:  # noqa: ANN001
        """Handle a drag & drop; accept only ZIP files."""
        first = event.data.split()[0].strip("{}")
        if first.lower().endswith(".zip"):
            self.set_zip(first)
        else:
            self.status.configure(text="Fichier ZIP attendu", text_color="#c0392b")

    def set_zip(self, path: str) -> None:
        """Remember the chosen ZIP and show its name."""
        self.zip_path = path
        self.drop_zone.configure(text=f"{Path(path).name}")
        self.status.configure(text=path, text_color="grey")

    def open_settings(self) -> None:
        """Open the settings modal window."""
        SettingsModal(self)

    def persist_config(self) -> None:
        """Save the current folders and watch flag to disk."""
        save_config(
            AppConfig(
                watched_dir=self.watched_dir,
                output_dir=self.output_dir,
                watch_enabled=self.watch_enabled,
            )
        )

    def watched_dir_valid(self) -> bool:
        """True if a watched folder is set and still exists."""
        return self.watched_dir is not None and self.watched_dir.is_dir()

    def output_dir_valid(self) -> bool:
        """True if an output folder is set and still exists."""
        return self.output_dir is not None and self.output_dir.is_dir()

    def start_watch(self) -> None:
        """(Re)create the folder watcher and start the polling cycle.

        Existing ZIPs are captured as a "backlog" and skipped, so only files
        dropped after this point are converted.
        """
        self._stop_watch()
        self._set_watch_indicator()
        if self.watched_dir is None:
            messagebox.showwarning(APP_TITLE, WATCH_DIR_REQUIRED)
            return
        try:
            backlog = set(scan_zip_entries(self.watched_dir))
        except OSError:
            backlog = set()
        self.watcher = FolderWatcher(
            self.watched_dir,
            self.output_dir,
            bool(self.include_antecedents.get()),
        )
        self.watcher.start(backlog)
        # Poll the watcher on the Tk event loop (single-threaded access to UI).
        self._tick_job = self.after(POLL_INTERVAL_MS, self.tick)

    def restart_watch(self) -> None:
        """Restart the watcher only if automatic mode is currently enabled."""
        if self.watch_enabled:
            self.start_watch()

    def enable_watch(self) -> None:
        """Turn automatic mode on, save it and start watching."""
        self.watch_enabled = True
        self.persist_config()
        self.start_watch()

    def disable_watch(self) -> None:
        """Turn automatic mode off, save it and stop watching."""
        self.watch_enabled = False
        self.persist_config()
        self._stop_watch()

    def _stop_watch(self) -> None:
        """Cancel the polling timer and stop the worker thread."""
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self._set_watch_indicator()

    def _set_watch_indicator(self) -> None:
        """Update the green/grey label that shows whether watching is on."""
        if self.watch_enabled:
            self.watch_state.configure(text=WATCH_STATE_ON, text_color="#27ae60")
        else:
            self.watch_state.configure(text=WATCH_STATE_OFF, text_color="grey")

    def tick(self) -> None:
        """One polling cycle: scan the folder and show any resulting events."""
        self._tick_job = None
        if self.watcher is None:
            return
        try:
            self.watcher.poll()
            for event in self.watcher.drain_events():
                self._handle_event(event)
        finally:
            # Keep the cycle alive even if one tick fails; the error still surfaces.
            if self.watcher is not None:
                self._tick_job = self.after(POLL_INTERVAL_MS, self.tick)

    def _handle_event(self, event: WatcherEvent) -> None:
        """Translate a watcher event into a coloured status message."""
        if event.kind == EVENT_SUCCESS:
            text = f"{WATCH_SUCCESS}{event.pdf or event.path}"
            color = "#27ae60"
        elif event.kind == EVENT_ERROR:
            text = f"{WATCH_ERROR}{event.path}\n{event.message}"
            color = "#c0392b"
        elif event.kind == EVENT_IGNORED:
            text = f"{WATCH_IGNORED}{event.path}"
            color = "#b9770e"
        elif event.kind == EVENT_INACCESSIBLE:
            text = WATCH_INACCESSIBLE
            color = "#c0392b"
        else:
            return
        self.watch_status.configure(text=text, text_color=color)

    def on_include_antecedents_change(self) -> None:
        """Forward the checkbox change to the running watcher, if any."""
        if self.watcher is not None:
            self.watcher.set_include_antecedents(
                bool(self.include_antecedents.get())
            )

    def on_close(self) -> None:
        """Stop background work before closing the window."""
        self._stop_watch()
        self.destroy()

    def convert(self) -> None:
        """Convert the selected ZIP now (manual button) and report the result."""
        if not self.zip_path:
            self.status.configure(text=NO_ZIP, text_color="#c0392b")
            return
        try:
            output = convert_zip(
                Path(self.zip_path),
                self.output_dir,
                bool(self.include_antecedents.get()),
                datetime.now(),
            )
            self.status.configure(text=str(output), text_color="#27ae60")
            messagebox.showinfo(APP_TITLE, f"{CONVERT_OK}{output}")
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text="Erreur", text_color="#c0392b")
            messagebox.showerror(APP_TITLE, f"{CONVERT_KO}{exc}")


def run() -> None:
    """Configure the theme, create the main window and start the Tk loop."""
    ctk.set_appearance_mode("system")
    app = App()
    app.mainloop()