# Convertisseur WEDA — Medical Record XML to PDF

Desktop utility in Python that converts patient-record `.zip` exports from the
French medical software **WEDA** into clean, paginated A4 PDF reports
(`Nom_Prenom_Date.pdf`). All visible text in the interface and in the generated
reports is in French.

It supports both manual drag-and-drop conversions and automatic folder watching
from the Windows notification area, processing exports in memory without
persisting patient data.

## Windows installer

Download the latest installer directly (no Python installation or GitHub sign-in
required):

- **[ConvertisseurWEDA-Setup.exe](https://github.com/alguimo/xml-parser/releases/latest/download/ConvertisseurWEDA-Setup.exe)** — latest [GitHub Release](https://github.com/alguimo/xml-parser/releases)

The installer runs per-user (`%LOCALAPPDATA%\Programs\Convertisseur WEDA`, no
administrator prompt), offers to launch the app automatically at Windows sign-in
hidden in the system tray, and updates itself silently in the background when
new releases are published.

## Features

- **Manual conversion** — drag a WEDA `.zip` onto the window (or select it via
  the file dialog), choose whether `Antécédents` should be included, and
  generate `Nom_Prenom_Date.pdf`.
- **Watched folder mode** — monitors a chosen input folder, waits until new
  `.zip` files stop changing size and modification time before reading them,
  converts valid WEDA exports one by one in arrival order, and moves processed
  archives into `traites/` or `erreurs/` with a timestamp suffix.
- **Two-column clinical report** — parallel A4 layout with a wide left column
  (`Données patient` and `Consultations`, 66%) and a narrow right column
  (`Antécédents` and consolidated `Traitement`, 33%), falling back to full width
  when the side column is empty.
- **System tray & single instance** — runs in the Windows notification area
  (`Ouvrir` / `Quitter`), hides to the tray when closing the main window, and
  uses a named Win32 mutex so opening the shortcut again brings the running
  instance to the front instead of starting a duplicate watcher.
- **Startup toggle** — auto-start at Windows sign-in (`HKCU\...\Run` with
  `--minimized`) can be enabled or disabled either during installation or later
  from `Paramètres`.
- **Silent self-update** — every push to `main` builds a new installer and
  `.sha256` checksum on GitHub Actions and publishes a GitHub Release; installed
  Windows clients check periodically, verify the SHA-256 digest, and update in
  the background once idle.

## Tech stack

Python 3.13, CustomTkinter and `tkinterdnd2` for the desktop GUI, `pystray` and
Pillow for the Windows tray icon, `lxml` and BeautifulSoup4 for XML parsing and
HTML cleanup, ReportLab for PDF layout. Packaged natively on Windows with
PyInstaller and Inno Setup 6 via GitHub Actions.

## Running from source

Requires Python 3.13 with Tcl/Tk 8.6+ (on macOS, use Python from Homebrew or
python.org rather than `/usr/bin/python3`, whose bundled Tk 8.5 breaks
CustomTkinter rendering).

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install customtkinter tkinterdnd2 reportlab beautifulsoup4 lxml pillow packaging
# On Windows, also install tray support:
pip install pystray

python main.py                   # normal window
python main.py --minimized       # start hidden in the system tray
```

Exact pinned versions used for release builds are defined in
`.github/workflows/windows-build.yml`. To build the Windows installer locally on
a Windows machine with PyInstaller and Inno Setup 6 installed:

```powershell
pyinstaller --clean --noconfirm Convertisseur.spec
iscc installer\Convertisseur.iss
```

## Project layout

```
.
├── main.py                              CLI entry point (--minimized, --quit) and instance guard
├── app/
│   ├── gui.py                           CustomTkinter main window, settings modal and event loop
│   ├── conversion_service.py            Shared ZIP -> XML -> PDF pipeline
│   ├── extractor.py                     In-memory reader for WEDA export ZIP bundles
│   ├── parser.py                        lxml parser mapping Patient.xml into dataclasses
│   ├── text_utils.py                    HTML entity decoding, rich-text cleanup and filenames
│   ├── pdf_generator.py                 Two-column A4 ReportLab renderer with custom pagination
│   ├── folder_watcher.py                Stability-checked folder polling and worker queue
│   ├── config_store.py                  Local JSON persistence for folder paths and watch state
│   ├── tray.py                          Windows notification-area icon and French context menu
│   ├── startup.py                       Per-user Windows Run registry key reader/writer
│   ├── single_instance.py               Win32 mutex and named events for show/quit signalling
│   ├── updater.py                       GitHub Releases checker, SHA-256 verifier and silent runner
│   ├── icon.py                          Programmatic multi-size icon generator (PIL / .ico)
│   └── version.py                       Stamped build version and GitHub repository coordinates
├── Convertisseur.spec                   PyInstaller bundle specification (Windows and macOS)
├── installer/
│   └── Convertisseur.iss                Inno Setup 6 script (French UI, auto-start and /AUTOUPDATE)
└── .github/workflows/
    └── windows-build.yml                CI build, SHA-256 generation and GitHub Release publishing
```

## Data & implementation notes

- **Zero patient-data persistence** — `Patient.xml` is extracted from the `.zip`
  archive in memory; sibling PDF attachments referenced in `<FileStreams>` are
  listed by filename in the report and never unpacked to disk or concatenated.
  Local state in `~/.convertisseur_weda.json` stores only folder paths and the
  watch toggle.
- **Atomic PDF writes** — reports are built into a temporary file in the output
  folder and moved to their final name with `os.replace()` only after rendering
  completes, avoiding partial files on abrupt exit.
- **Custom pagination** — feeding a multi-thousand-point row into a two-column
  ReportLab `Table` can make `splitInRow` return an empty top fragment and loop
  indefinitely. `_paginate()` in `app/pdf_generator.py` measures each flowable
  against the frame height and emits one non-splitting table per page.
- **WEDA XML quirks** — handles single- and double-escaped HTML entities
  (`&amp;#233;` -> `é`), strips placeholder `01/01/0001` dates, keeps comma
  decimals intact, and resolves `<Onglets>` category titles while omitting
  context-dependent raw codes.
- **Verified background updates** — `app/updater.py` restricts downloads to
  HTTPS GitHub hosts, validates both the Windows PE header and the published
  `.sha256` checksum before launching Inno Setup, and waits until no ZIP
  conversion is in progress before restarting.
