"""Ultimate Audiobooks GUI. Run with: python GUI.py (no arguments needed)."""
import json
import logging
import queue
import threading
from argparse import Namespace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pyperclip

import Main
import Settings
import Processing
import BookStatus
import Util

log = logging.getLogger(__name__)

PAD = 14
FETCH_OPTIONS = ["Off", "Audible", "Goodreads", "Both"]
CREATE_OPTIONS = ["Off", "OPF"]  #INFOTEXT not yet implemented
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MODES = ["Single level", "Recurse fetch", "Recurse combine"]  #Recurse preserve not yet implemented
UI_SCALES = ["90%", "100%", "110%", "125%", "150%"]
DEFAULT_UI_SCALE = "110%"


class QueueHandler(logging.Handler):
    #worker threads log freely; the GUI thread drains the queue (tkinter widgets are not thread-safe)
    def __init__(self, logQueue):
        super().__init__()
        self.logQueue = logQueue

    def emit(self, record):
        try:
            self.logQueue.put(self.format(record))
        except Exception:
            pass


class GuiUrlProvider:
    """Feeds book URLs to Util.fetchMetadata from the GUI's fetch panel instead of the clipboard.

    Called from the worker thread; blocks until the user submits a URL, copies one
    (clipboard watching), or skips. Requests go through a queue because tkinter widgets
    may only be touched from the main thread."""

    def __init__(self, app):
        self.app = app
        self.responses = queue.Queue()

    def __call__(self, searchText, searchURL, file):
        self.app.fetchRequests.put((searchText, searchURL, file.name))
        return self.responses.get()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ultimate Audiobooks")
        self.geometry("1280x800")
        self.minsize(1050, 650)

        self.workerThread = None
        self.logQueue = queue.Queue()
        self._setupLogging()

        self.fetchRequests = queue.Queue()
        self.urlProvider = GuiUrlProvider(self)
        Util.setUrlProvider(self.urlProvider)
        self.currentSearchURL = None
        self._clipboardBaseline = ""
        self._clipboardTick = 0

        #resizable split between sidebar and log area (drag the sash)
        self.paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bd=0,
                                    relief="flat", bg=self._panedColor())
        self.paned.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(self.paned, corner_radius=0)
        self._buildSidebar(sidebar)
        self.paned.add(sidebar, minsize=460, width=560, stretch="never")

        mainArea = ctk.CTkFrame(self.paned, fg_color="transparent")
        self._buildMainArea(mainArea)
        self.paned.add(mainArea, minsize=450, stretch="always")

        self.after(100, self._pollLogs)

    def _panedColor(self):
        return "#1a1a1a" if ctk.get_appearance_mode() == "Dark" else "#d4d4d4"

    def _setAppearance(self, mode):
        ctk.set_appearance_mode(mode)
        self.paned.configure(bg=self._panedColor())

    def _setUiScale(self, value):
        ctk.set_widget_scaling(int(value.rstrip('%')) / 100)

    def _setupLogging(self):
        handler = QueueHandler(self.logQueue)
        handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    # ---------- layout ----------

    def _buildSidebar(self, sidebar):
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Ultimate Audiobooks",
                     font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, sticky="w")

        form = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        form.grid(row=1, column=0, sticky="nsew", padx=(PAD // 2, 0), pady=(4, PAD // 2))
        form.grid_columnconfigure(0, weight=1)
        self._buildForm(form)

        buttons = ctk.CTkFrame(sidebar, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0, PAD))
        buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Save Settings", height=32, command=self._saveSettings,
                      fg_color="transparent", border_width=1).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(buttons, text="Load Settings", height=32, command=self._loadSettings,
                      fg_color="transparent", border_width=1).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.startButton = ctk.CTkButton(buttons, text="Start Processing", height=46,
                                         font=ctk.CTkFont(size=16, weight="bold"), command=self._startRun)
        self.startButton.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _sectionCard(self, form, row, title):
        card = ctk.CTkFrame(form)
        card.grid(row=row, column=0, sticky="ew", padx=(4, 8), pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("gray30", "gray70")).grid(row=0, column=0, sticky="w", padx=PAD, pady=(10, 6))
        return card

    def _menuRow(self, card, row, labelText, menu):
        rowFrame = ctk.CTkFrame(card, fg_color="transparent")
        rowFrame.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(0, 8))
        rowFrame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(rowFrame, text=labelText, font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="w")
        menu.grid(row=0, column=1, sticky="e", in_=rowFrame)
        return rowFrame

    def _buildForm(self, form):
        # --- Folders ---
        card = self._sectionCard(form, 0, "FOLDERS")

        inputRow = ctk.CTkFrame(card, fg_color="transparent")
        inputRow.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0, 8))
        inputRow.grid_columnconfigure(0, weight=1)
        self.inputEntry = ctk.CTkEntry(inputRow, height=32, placeholder_text="Input folder (required)")
        self.inputEntry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(inputRow, text="Browse", width=76, height=32,
                      command=lambda: self._browseInto(self.inputEntry)).grid(row=0, column=1, padx=(8, 0))

        outputRow = ctk.CTkFrame(card, fg_color="transparent")
        outputRow.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0, 8))
        outputRow.grid_columnconfigure(0, weight=1)
        self.outputEntry = ctk.CTkEntry(outputRow, height=32, placeholder_text="Output folder (optional)")
        self.outputEntry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(outputRow, text="Browse", width=76, height=32,
                      command=lambda: self._browseInto(self.outputEntry)).grid(row=0, column=1, padx=(8, 0))

        self.moveSwitch = ctk.CTkSwitch(card, text="Move files (default: copy)", font=ctk.CTkFont(size=13))
        self.moveSwitch.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 12))

        # --- Processing mode ---
        card = self._sectionCard(form, 1, "PROCESSING MODE")
        self.modeSelector = ctk.CTkSegmentedButton(card, values=MODES, height=32, font=ctk.CTkFont(size=13))
        self.modeSelector.set(MODES[0])
        self.modeSelector.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0, 12))

        # --- Metadata ---
        card = self._sectionCard(form, 2, "METADATA")

        self.fetchMenu = ctk.CTkOptionMenu(card, values=FETCH_OPTIONS, width=140, height=32,
                                           font=ctk.CTkFont(size=13))
        self._menuRow(card, 1, "Fetch from web:", self.fetchMenu)

        self.fetchHint = ctk.CTkLabel(card, text="For each book, a panel will appear above the log.\nCopy the book page link, paste it, or skip.",
                                      font=ctk.CTkFont(size=12), text_color="gray55", justify="left")
        self.fetchHint.grid(row=2, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.cleanSwitch = ctk.CTkSwitch(card, text="Clean file tags with fetched metadata", font=ctk.CTkFont(size=13))
        self.cleanSwitch.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.createMenu = ctk.CTkOptionMenu(card, values=CREATE_OPTIONS, width=140, height=32,
                                            font=ctk.CTkFont(size=13))
        rowFrame = self._menuRow(card, 4, "Sidecar file:", self.createMenu)
        rowFrame.grid_configure(pady=(0, 12))

        # --- Conversion ---
        card = self._sectionCard(form, 3, "CONVERSION")
        self.convertSwitch = ctk.CTkSwitch(card, text="Convert to .m4b (requires ffmpeg)", font=ctk.CTkFont(size=13))
        self.convertSwitch.grid(row=1, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.workersEntry = ctk.CTkEntry(card, width=140, height=32, placeholder_text="Auto",
                                         font=ctk.CTkFont(size=13))
        rowFrame = self._menuRow(card, 2, "Workers:", self.workersEntry)
        rowFrame.grid_configure(pady=(0, 12))

        # --- Execution ---
        card = self._sectionCard(form, 4, "EXECUTION")

        self.batchEntry = ctk.CTkEntry(card, width=140, height=32, font=ctk.CTkFont(size=13))
        self.batchEntry.insert(0, "10")
        self._menuRow(card, 1, "Batch size:", self.batchEntry)

        self.logLevelMenu = ctk.CTkOptionMenu(card, values=LOG_LEVELS, width=140, height=32,
                                              font=ctk.CTkFont(size=13))
        self.logLevelMenu.set("INFO")
        rowFrame = self._menuRow(card, 2, "Log level:", self.logLevelMenu)
        rowFrame.grid_configure(pady=(0, 12))

        # --- Interface ---
        card = self._sectionCard(form, 5, "INTERFACE")

        self.appearanceMenu = ctk.CTkOptionMenu(card, values=["Dark", "Light", "System"], width=140, height=32,
                                                font=ctk.CTkFont(size=13), command=self._setAppearance)
        self._menuRow(card, 1, "Appearance:", self.appearanceMenu)

        self.uiScaleMenu = ctk.CTkOptionMenu(card, values=UI_SCALES, width=140, height=32,
                                             font=ctk.CTkFont(size=13), command=self._setUiScale)
        self.uiScaleMenu.set(DEFAULT_UI_SCALE)
        rowFrame = self._menuRow(card, 2, "UI scale:", self.uiScaleMenu)
        rowFrame.grid_configure(pady=(0, 12))

    def _buildMainArea(self, container):
        main = ctk.CTkFrame(container, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(main, text="Activity Log", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("gray30", "gray70")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._buildFetchPanel(main)

        self.logBox = ctk.CTkTextbox(main, font=ctk.CTkFont(family="monospace", size=13), wrap="word")
        self.logBox.grid(row=2, column=0, sticky="nsew")
        self.logBox.configure(state="disabled")

        statusRow = ctk.CTkFrame(main, fg_color="transparent")
        statusRow.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        statusRow.grid_columnconfigure(0, weight=1)
        self.statusLabel = ctk.CTkLabel(statusRow, text="Ready", anchor="w", font=ctk.CTkFont(size=13))
        self.statusLabel.grid(row=0, column=0, sticky="w")
        self.progressBar = ctk.CTkProgressBar(statusRow, width=200, mode="indeterminate")
        self.progressBar.grid(row=0, column=1, sticky="e")
        self.progressBar.set(0)

    def _buildFetchPanel(self, main):
        self.fetchPanel = ctk.CTkFrame(main, border_width=2)
        self.fetchPanel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.fetchPanel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.fetchPanel, text="Metadata Fetch", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=PAD, pady=(10, 0))
        self.fetchBookLabel = ctk.CTkLabel(self.fetchPanel, text="", anchor="w", wraplength=700,
                                           justify="left", font=ctk.CTkFont(size=13))
        self.fetchBookLabel.grid(row=1, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(2, 4))

        ctk.CTkButton(self.fetchPanel, text="Open Search", width=110, height=32, command=self._openSearch,
                      fg_color="transparent", border_width=1).grid(row=2, column=0, padx=(PAD, 8), pady=(4, 12))
        self.urlEntry = ctk.CTkEntry(self.fetchPanel, height=32,
                                     placeholder_text="Copy the Audible/Goodreads book link, or paste it here")
        self.urlEntry.grid(row=2, column=1, sticky="ew", pady=(4, 12))
        self.urlEntry.bind("<Return>", lambda event: self._submitUrl())
        submitRow = ctk.CTkFrame(self.fetchPanel, fg_color="transparent")
        submitRow.grid(row=2, column=2, padx=(8, PAD), pady=(4, 12))
        ctk.CTkButton(submitRow, text="Submit", width=80, height=32, command=self._submitUrl).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(submitRow, text="Skip Book", width=80, height=32, command=self._skipFetch,
                      fg_color="transparent", border_width=1).grid(row=0, column=1)

        self.fetchPanel.grid_remove()  #hidden until a fetch is waiting

    # ---------- fetch panel ----------

    def showFetchPanel(self, searchText, searchURL, fileName):
        self.currentSearchURL = searchURL
        self.fetchBookLabel.configure(text=f"File: {fileName}\nSearch: {searchText}")
        self.urlEntry.delete(0, "end")

        #baseline the clipboard so only NEW copies auto-submit; reset it if it already holds a book link
        try:
            self._clipboardBaseline = pyperclip.paste()
            if any(s in self._clipboardBaseline for s in ("audible.com", "goodreads.com")):
                pyperclip.copy("Ultimate Audiobooks")
                self._clipboardBaseline = "Ultimate Audiobooks"
        except Exception:
            self._clipboardBaseline = ""

        self.fetchPanel.grid()
        self.urlEntry.focus_set()
        self.statusLabel.configure(text="Waiting for a book link (copy or paste it)...")

    def _hideFetchPanel(self):
        self.fetchPanel.grid_remove()
        self.statusLabel.configure(text="Running...")

    def _openSearch(self):
        if self.currentSearchURL:
            Util.open_url_cross_platform(self.currentSearchURL)

    def _submitUrl(self):
        url = self.urlEntry.get().strip()
        if not url:
            return
        self._hideFetchPanel()
        self.urlProvider.responses.put(url)

    def _skipFetch(self):
        self._hideFetchPanel()
        self.urlProvider.responses.put("SKIP")

    def _watchClipboard(self):
        #hands-free alternative to the paste box: a newly copied book link (or 'skip') submits itself
        try:
            current = pyperclip.paste()
        except Exception:
            return
        if current == self._clipboardBaseline:
            return
        if current.strip().upper() == "SKIP" or "audible.com" in current or "goodreads.com" in current:
            self._clipboardBaseline = current
            self._hideFetchPanel()
            self.urlProvider.responses.put(current)

    # ---------- helpers ----------

    def _browseInto(self, entry):
        folder = filedialog.askdirectory()
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def _appendLog(self, text):
        self.logBox.configure(state="normal")
        self.logBox.insert("end", text + "\n")
        self.logBox.see("end")
        self.logBox.configure(state="disabled")

    def _pollLogs(self):
        try:
            while True:
                self._appendLog(self.logQueue.get_nowait())
        except queue.Empty:
            pass

        try:
            while True:
                self.showFetchPanel(*self.fetchRequests.get_nowait())
        except queue.Empty:
            pass

        #watch the clipboard while the fetch panel is up (every 5th tick ~ 0.5s; xclip calls aren't free)
        self._clipboardTick += 1
        if self._clipboardTick >= 5:
            self._clipboardTick = 0
            if self.fetchPanel.winfo_ismapped():
                self._watchClipboard()

        if self.workerThread and not self.workerThread.is_alive():
            self.workerThread = None
            self.startButton.configure(state="normal")
            self.progressBar.stop()
            self.progressBar.set(0)
            self.statusLabel.configure(text="Finished - see log for results")

        self.after(100, self._pollLogs)

    # ---------- settings persistence (shares settings.json with the CLI) ----------

    def _formValues(self):
        mode = self.modeSelector.get()
        fetch = self.fetchMenu.get().lower()
        create = self.createMenu.get()
        workers = self.workersEntry.get().strip()
        return {
            "input": self.inputEntry.get().strip(),
            "output": self.outputEntry.get().strip() or None,
            "move": bool(self.moveSwitch.get()),
            "recurseFetch": mode == "Recurse fetch",
            "recurseCombine": mode == "Recurse combine",
            "recursePreserve": False,
            "fetch": None if fetch == "off" else fetch,
            "clean": bool(self.cleanSwitch.get()),
            "create": None if create == "Off" else create.upper(),
            "convert": bool(self.convertSwitch.get()),
            "batch": self.batchEntry.get().strip(),
            "workers": -1 if workers.lower() in ("", "auto") else workers,
            "logLevel": self.logLevelMenu.get(),
        }

    def _saveSettings(self):
        values = self._formValues()
        try:
            values["batch"] = int(values["batch"])
            values["workers"] = int(values["workers"])
        except ValueError:
            pass  #save as-is; validated properly at run time
        with open(Settings.SETTINGS_FILE, 'w') as outFile:
            json.dump(values, outFile)
        log.info("Settings saved to " + str(Settings.SETTINGS_FILE))

    def _loadSettings(self):
        try:
            with open(Settings.SETTINGS_FILE, 'r') as inFile:
                saved = json.load(inFile)
        except FileNotFoundError:
            messagebox.showinfo("Load Settings", "No saved settings found.")
            return

        def setEntry(entry, value):
            entry.delete(0, "end")
            if value not in (None, ""):
                entry.insert(0, str(value))

        setEntry(self.inputEntry, saved.get("input"))
        setEntry(self.outputEntry, saved.get("output"))
        setEntry(self.batchEntry, saved.get("batch", 10))
        workers = saved.get("workers", -1)
        setEntry(self.workersEntry, "Auto" if workers in (-1, "-1", None) else workers)

        self.moveSwitch.select() if saved.get("move") else self.moveSwitch.deselect()
        self.cleanSwitch.select() if saved.get("clean") else self.cleanSwitch.deselect()
        self.convertSwitch.select() if saved.get("convert") else self.convertSwitch.deselect()

        if saved.get("recurseFetch"):
            self.modeSelector.set("Recurse fetch")
        elif saved.get("recurseCombine"):
            self.modeSelector.set("Recurse combine")
        else:
            self.modeSelector.set("Single level")

        fetch = saved.get("fetch")
        self.fetchMenu.set(fetch.capitalize() if fetch in ("audible", "goodreads", "both") else "Off")
        self.createMenu.set("OPF" if saved.get("create") else "Off")
        level = saved.get("logLevel", "INFO")
        self.logLevelMenu.set(level if level in LOG_LEVELS else "INFO")
        log.info("Settings loaded from " + str(Settings.SETTINGS_FILE))

    # ---------- running ----------

    def _collectArgs(self):
        values = self._formValues()

        if not values["input"]:
            messagebox.showerror("Missing input", "Please choose an input folder.")
            return None
        if not Path(values["input"]).is_dir():
            messagebox.showerror("Invalid input", "The input folder does not exist:\n" + values["input"])
            return None
        if values["recurseCombine"] and not values["move"]:
            messagebox.showerror("Incompatible settings",
                                 "Recurse combine currently requires 'Move files'.\nCopy mode would strand originals in the temp folder.")
            return None
        try:
            values["batch"] = int(values["batch"])
        except ValueError:
            messagebox.showerror("Invalid batch size", "Batch size must be a whole number.")
            return None
        try:
            values["workers"] = int(values["workers"])
        except ValueError:
            messagebox.showerror("Invalid workers", "Workers must be a whole number or 'Auto'.")
            return None

        #flags the CLI has that the GUI handles itself or doesn't expose
        values.update({"quick": True, "save": False, "load": False, "default": False,
                       "force": False, "rename": None})
        return Namespace(**values)

    def _startRun(self):
        if self.workerThread:
            return
        args = self._collectArgs()
        if args is None:
            return

        logging.getLogger().setLevel(getattr(logging, args.logLevel, logging.INFO))
        self.startButton.configure(state="disabled")
        self.statusLabel.configure(text="Running...")
        self.progressBar.start()

        self.workerThread = threading.Thread(target=self._runWorker, args=(args,), daemon=True)
        self.workerThread.start()

    def _runWorker(self, args):
        try:
            #reset state left over from a previous run in this same process
            BookStatus.clearSkips()
            BookStatus.clearFails()
            Processing.conversions.clear()

            Main.main(args)
        except SystemExit:
            log.error("Run aborted - see messages above.")
        except Exception:
            log.exception("Unexpected error during run")


if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("dark-blue")
    ctk.set_widget_scaling(int(DEFAULT_UI_SCALE.rstrip('%')) / 100)
    App().mainloop()
