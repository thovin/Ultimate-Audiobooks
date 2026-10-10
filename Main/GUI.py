"""Ultimate Audiobooks GUI. Run with: python GUI.py (no arguments needed)."""
import json
import logging
import queue
import threading
from argparse import Namespace
from pathlib import Path
from typing import NamedTuple
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pyperclip

import Main
import Settings
import Reporter
import BookStatus
import Util

log = logging.getLogger(__name__)

PAD = 14
FETCH_OPTIONS = ["Off", "Audible", "Goodreads", "Both"]
FETCH_INPUT_MODES = ["Clipboard (copy link)", "Paste box"]
CREATE_OPTIONS = ["Off", "OPF"]  #INFOTEXT not yet implemented
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MODES = ["Single level", "Recurse fetch", "Recurse combine"]  #Recurse preserve not yet implemented
UI_SCALES = ["90%", "100%", "110%", "125%", "150%"]
DEFAULT_UI_SCALE = "110%"
#log pane text size, adjustable independently of UI scale (ctrl +/-/0 or ctrl+wheel over the log)
LOG_FONT_SIZES = ["10", "11", "12", "13", "14", "16", "18", "20", "24"]
DEFAULT_LOG_FONT_SIZE = 13
MIN_LOG_FONT_SIZE = 8
MAX_LOG_FONT_SIZE = 32
DEFAULT_GEOMETRY = "1440x860"

#window size/position and interface preferences, remembered between sessions (separate from
#settings.json, which holds processing options shared with the CLI)
GUI_STATE_FILE = Path(__file__).resolve().parent / 'gui_state.json'


def clampLogFontSize(value):
    try:
        size = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LOG_FONT_SIZE
    return max(MIN_LOG_FONT_SIZE, min(MAX_LOG_FONT_SIZE, size))


def loadGuiState():
    try:
        with open(GUI_STATE_FILE, 'r') as inFile:
            return json.load(inFile)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


class LogEntry(NamedTuple):
    formatted: str  #what the raw view shows, e.g. "[14:02:11][INFO] Processing foo.mp3"
    level: str       #record.levelname
    logger: str      #record.name
    message: str     #record.getMessage() - no timestamp/level prefix, for the pretty classifier


class QueueHandler(logging.Handler):
    #worker threads log freely; the GUI thread drains the queue (tkinter widgets are not thread-safe)
    def __init__(self, logQueue):
        super().__init__()
        self.logQueue = logQueue

    def emit(self, record):
        try:
            self.logQueue.put(LogEntry(
                formatted=self.format(record),
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            ))
        except Exception:
            pass


class GuiReporter(Reporter.Reporter):
    """Hands run events to the GUI thread.

    handle() is called from the worker thread (and from Processing's relay of conversion-worker
    events), so it only enqueues - every widget touch happens in _pollLogs on the main thread."""

    def __init__(self, eventQueue):
        self.eventQueue = eventQueue

    def handle(self, event):
        self.eventQueue.put(event)

    def confirmSettings(self, values):
        return True  #pressing Start is the confirmation


class GuiUrlProvider:
    """Feeds book URLs to Util.fetchMetadata from the GUI's fetch panel instead of the clipboard.

    Called from the worker thread; blocks until the user supplies a URL or skips.
    Requests go through a queue because tkinter widgets may only be touched from the main thread."""

    def __init__(self, app):
        self.app = app
        self.responses = queue.Queue()

    def __call__(self, searchText, searchURL, file, reason=None):
        #reason explains why the previous link was rejected, so the panel can re-prompt with it
        self.app.fetchRequests.put((searchText, searchURL, file.name, reason))
        return self.responses.get()


class App(ctk.CTk):
    def __init__(self, guiState=None):
        super().__init__()
        self.guiState = guiState if guiState is not None else {}
        self.title("Ultimate Audiobooks")
        self.geometry(self.guiState.get("geometry", DEFAULT_GEOMETRY))
        self.minsize(1050, 650)

        self.workerThread = None
        self._dryRunActive = False  #dry run state of the run in progress (the switch may be toggled meanwhile)
        self._logFontSize = clampLogFontSize(self.guiState.get("logFontSize", DEFAULT_LOG_FONT_SIZE))
        self.logQueue = queue.Queue()
        self._setupLogging()

        #run events from the core pipeline; the pretty pane and the progress bar render these
        self.eventQueue = queue.Queue()
        Reporter.setReporter(GuiReporter(self.eventQueue))
        self._bookTotal = 0
        self._bookIndex = 0
        self._currentBook = None
        self._indeterminate = False
        self._sawRunFinished = False

        #worker-thread failures that deserve a dialog; shown from _pollLogs, since tkinter calls
        #(including after()) are only safe from the main thread
        self.errorQueue = queue.Queue()

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
        self.paned.add(sidebar, minsize=460, width=self.guiState.get("sidebarWidth", 560), stretch="never")

        mainArea = ctk.CTkFrame(self.paned, fg_color="transparent")
        self._buildMainArea(mainArea)
        self.paned.add(mainArea, minsize=450, stretch="always")

        self._applyGuiState()
        self._bindFontShortcuts()
        self.protocol("WM_DELETE_WINDOW", self._onClose)
        self.after(100, self._pollLogs)

    def _applyGuiState(self):
        self.appearanceMenu.set(self.guiState.get("appearance", "Dark"))
        self.uiScaleMenu.set(self.guiState.get("uiScale", DEFAULT_UI_SCALE))
        self._setLogFontSize(self._logFontSize)  #applies the saved size to both panes
        fetchInput = self.guiState.get("fetchInput", FETCH_INPUT_MODES[0])
        self.fetchInputMenu.set(fetchInput if fetchInput in FETCH_INPUT_MODES else FETCH_INPUT_MODES[0])
        self._updateFetchHint()
        if self.guiState.get("autoLoadSettings"):
            self.autoLoadSwitch.select()
            self._loadSettings(silent=True)
        if self.guiState.get("prettyLog", True):
            self.prettyLogSwitch.select()
        else:
            self.prettyLogSwitch.deselect()
        self._onPrettyLogToggle()

    def _onClose(self):
        state = {
            "geometry": self.geometry(),
            "sidebarWidth": self.paned.sash_coord(0)[0],
            "appearance": self.appearanceMenu.get(),
            "uiScale": self.uiScaleMenu.get(),
            "logFontSize": self._logFontSize,
            "fetchInput": self.fetchInputMenu.get(),
            "autoLoadSettings": bool(self.autoLoadSwitch.get()),
            "prettyLog": bool(self.prettyLogSwitch.get()),
        }
        try:
            with open(GUI_STATE_FILE, 'w') as outFile:
                json.dump(state, outFile)
        except OSError:
            pass
        self.destroy()

    def _panedColor(self):
        return "#1a1a1a" if ctk.get_appearance_mode() == "Dark" else "#d4d4d4"

    def _setAppearance(self, mode):
        ctk.set_appearance_mode(mode)
        self.paned.configure(bg=self._panedColor())
        self._configureLogTags(self.logBox)
        self._configureLogTags(self.prettyBox)

    def _setUiScale(self, value):
        ctk.set_widget_scaling(int(value.rstrip('%')) / 100)

    def _applyPrettyHeaderFont(self):
        #CTkTextbox.tag_config forbids a "font" kwarg (scaling conflict) - set it on the raw
        #tkinter.Text directly. Headers sit one point above the body text.
        self.prettyBox._textbox.tag_config("book_header",
                                           font=("TkDefaultFont", self._logFontSize + 1, "bold"),
                                           foreground=self.prettyBox._apply_appearance_mode(("gray10", "gray95")))

    def _setLogFontSize(self, value):
        #one knob for both log views (dropdown, ctrl +/-/0, or ctrl+wheel over the log)
        size = clampLogFontSize(value)
        self._logFontSize = size
        self.logFont.configure(size=size)
        self.prettyFont.configure(size=size)
        self._applyPrettyHeaderFont()
        if self.logFontMenu.get() != str(size):
            self.logFontMenu.set(str(size))  #keep the dropdown honest after a shortcut

    def _stepLogFontSize(self, step):
        self._setLogFontSize(self._logFontSize + step)

    def _onLogFontScroll(self, event):
        #ctrl+wheel: Button-4/5 on X11, signed delta elsewhere
        self._stepLogFontSize(1 if event.num == 4 or getattr(event, "delta", 0) > 0 else -1)
        return "break"  #don't scroll the view as well

    def _bindFontShortcuts(self):
        for sequence in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.bind(sequence, lambda event: self._stepLogFontSize(1))
        for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.bind(sequence, lambda event: self._stepLogFontSize(-1))
        self.bind("<Control-0>", lambda event: self._setLogFontSize(DEFAULT_LOG_FONT_SIZE))

    def _setupLogging(self):
        handler = QueueHandler(self.logQueue)
        handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    _LOG_TAG_COLORS = {
        "debug":    ("gray50", "gray50"),
        "info":     ("gray20", "gray85"),
        "pretty_info": ("gray20", "gray85"),
        "muted":    ("gray45", "gray60"),
        "warning":  ("#9a6700", "#e3b341"),
        "error":    ("#c62828", "#ff6b6b"),
        "critical": ("#ffffff", "#ffffff"),
    }

    def _configureLogTags(self, box):
        for tag, colors in self._LOG_TAG_COLORS.items():
            resolved = box._apply_appearance_mode(colors)
            if tag == "critical":
                box.tag_config(tag, foreground=resolved,
                               background=box._apply_appearance_mode(("#b00020", "#8b0000")))
            else:
                box.tag_config(tag, foreground=resolved)

    def _refreshLogView(self):
        if self.prettyLogSwitch.get():
            self.logBox.grid_remove()
            self.prettyBox.grid()
        else:
            self.prettyBox.grid_remove()
            self.logBox.grid()

    def _onPrettyLogToggle(self):
        self._refreshLogView()
        self.logLevelMenu.configure(state="disabled" if self.prettyLogSwitch.get() else "normal")

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

    def _labeledRow(self, card, row, labelText, makeWidget, lastInCard=False):
        #makeWidget receives the row frame as parent, so widgets are parented normally
        #(gridding a widget into a frame that is not its parent breaks dropdown menus)
        rowFrame = ctk.CTkFrame(card, fg_color="transparent")
        rowFrame.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(0, 12 if lastInCard else 8))
        rowFrame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(rowFrame, text=labelText, font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="w")
        widget = makeWidget(rowFrame)
        widget.grid(row=0, column=1, sticky="e")
        return widget

    def _buildForm(self, form):
        font13 = ctk.CTkFont(size=13)

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

        self.moveSwitch = ctk.CTkSwitch(card, text="Move files (default: copy)", font=font13)
        self.moveSwitch.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.dryRunSwitch = ctk.CTkSwitch(card, text="Dry run (list actions, write nothing)", font=font13)
        self.dryRunSwitch.grid(row=4, column=0, sticky="w", padx=PAD, pady=(0, 12))

        # --- Processing mode ---
        card = self._sectionCard(form, 1, "PROCESSING MODE")
        self.modeSelector = ctk.CTkSegmentedButton(card, values=MODES, height=32, font=font13)
        self.modeSelector.set(MODES[0])
        self.modeSelector.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0, 12))

        # --- Metadata ---
        card = self._sectionCard(form, 2, "METADATA")

        self.fetchMenu = self._labeledRow(card, 1, "Fetch from web:",
                                          lambda p: ctk.CTkOptionMenu(p, values=FETCH_OPTIONS, width=170,
                                                                      height=32, font=font13))
        self.fetchInputMenu = self._labeledRow(card, 2, "Fetch input:",
                                               lambda p: ctk.CTkOptionMenu(p, values=FETCH_INPUT_MODES, width=170,
                                                                           height=32, font=font13,
                                                                           command=lambda v: self._updateFetchHint()))

        self.fetchHint = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=12),
                                      text_color="gray55", justify="left")
        self.fetchHint.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 8))
        self._updateFetchHint()

        self.cleanSwitch = ctk.CTkSwitch(card, text="Clean file tags with fetched metadata", font=font13)
        self.cleanSwitch.grid(row=4, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.createMenu = self._labeledRow(card, 5, "Sidecar file:",
                                           lambda p: ctk.CTkOptionMenu(p, values=CREATE_OPTIONS, width=170,
                                                                       height=32, font=font13),
                                           lastInCard=True)

        # --- Conversion ---
        card = self._sectionCard(form, 3, "CONVERSION")
        self.convertSwitch = ctk.CTkSwitch(card, text="Convert to .m4b (requires ffmpeg)", font=font13)
        self.convertSwitch.grid(row=1, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.workersEntry = self._labeledRow(card, 2, "Workers:",
                                             lambda p: ctk.CTkEntry(p, width=170, height=32,
                                                                    placeholder_text="Auto", font=font13),
                                             lastInCard=True)

        # --- Execution ---
        card = self._sectionCard(form, 4, "EXECUTION")

        self.batchEntry = self._labeledRow(card, 1, "Batch size:",
                                           lambda p: ctk.CTkEntry(p, width=170, height=32, font=font13))
        self.batchEntry.insert(0, "10")

        self.logLevelMenu = self._labeledRow(card, 2, "Log level:",
                                             lambda p: ctk.CTkOptionMenu(p, values=LOG_LEVELS, width=170,
                                                                         height=32, font=font13),
                                             lastInCard=True)
        self.logLevelMenu.set("INFO")

        # --- Interface ---
        card = self._sectionCard(form, 5, "INTERFACE")

        self.appearanceMenu = self._labeledRow(card, 1, "Appearance:",
                                               lambda p: ctk.CTkOptionMenu(p, values=["Dark", "Light", "System"],
                                                                           width=170, height=32, font=font13,
                                                                           command=self._setAppearance))
        self.uiScaleMenu = self._labeledRow(card, 2, "UI scale:",
                                            lambda p: ctk.CTkOptionMenu(p, values=UI_SCALES, width=170,
                                                                        height=32, font=font13,
                                                                        command=self._setUiScale))
        self.uiScaleMenu.set(DEFAULT_UI_SCALE)
        self.logFontMenu = self._labeledRow(card, 3, "Log font size:",
                                            lambda p: ctk.CTkOptionMenu(p, values=LOG_FONT_SIZES, width=170,
                                                                        height=32, font=font13,
                                                                        command=self._setLogFontSize))
        self.logFontMenu.set(str(self._logFontSize))
        ctk.CTkLabel(card, text="Ctrl +/- or ctrl+scroll over the log also works",
                     font=ctk.CTkFont(size=12), text_color=("gray45", "gray60")
                     ).grid(row=4, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.autoLoadSwitch = ctk.CTkSwitch(card, text="Auto-load settings on launch", font=font13)
        self.autoLoadSwitch.grid(row=5, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self.prettyLogSwitch = ctk.CTkSwitch(card, text="Pretty output", font=font13,
                                             command=self._onPrettyLogToggle)
        self.prettyLogSwitch.grid(row=6, column=0, sticky="w", padx=PAD, pady=(0, 12))
        self.prettyLogSwitch.select()  #default on

    def _buildMainArea(self, container):
        main = ctk.CTkFrame(container, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(main, text="Activity Log", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("gray30", "gray70")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._buildFetchPanel(main)

        #kept as objects so _setLogFontSize can resize the panes live
        self.logFont = ctk.CTkFont(family="monospace", size=self._logFontSize)
        self.prettyFont = ctk.CTkFont(size=self._logFontSize)

        self.logBox = ctk.CTkTextbox(main, font=self.logFont, wrap="word")
        self.logBox.grid(row=2, column=0, sticky="nsew")
        self.logBox.configure(state="disabled")
        self._configureLogTags(self.logBox)

        self.prettyBox = ctk.CTkTextbox(main, font=self.prettyFont, wrap="word")
        self.prettyBox.grid(row=2, column=0, sticky="nsew")
        self.prettyBox.configure(state="disabled")
        self._configureLogTags(self.prettyBox)
        self._applyPrettyHeaderFont()

        for box in (self.logBox, self.prettyBox):
            for sequence in ("<Control-Button-4>", "<Control-Button-5>", "<Control-MouseWheel>"):
                box._textbox.bind(sequence, self._onLogFontScroll)

        statusRow = ctk.CTkFrame(main, fg_color="transparent")
        statusRow.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        statusRow.grid_columnconfigure(0, weight=1)
        self.statusLabel = ctk.CTkLabel(statusRow, text="Ready", anchor="w", font=ctk.CTkFont(size=13))
        self.statusLabel.grid(row=0, column=0, sticky="w")
        #determinate by default: book counts come from BookStarted events, so real progress is known
        self.progressBar = ctk.CTkProgressBar(statusRow, width=200, mode="determinate")
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

        #why the last link was rejected, shown where the user is actually looking
        self.fetchReasonLabel = ctk.CTkLabel(self.fetchPanel, text="", anchor="w", wraplength=700,
                                             justify="left", font=ctk.CTkFont(size=13),
                                             text_color=("#c62828", "#ff6b6b"))
        self.fetchReasonLabel.grid(row=4, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(0, 10))
        self.fetchReasonLabel.grid_remove()

        ctk.CTkButton(self.fetchPanel, text="Open Search", width=110, height=32, command=self._openSearch,
                      fg_color="transparent", border_width=1).grid(row=2, column=0, padx=(PAD, 8), pady=(4, 12))

        #paste-box mode widgets
        self.urlEntry = ctk.CTkEntry(self.fetchPanel, height=32,
                                     placeholder_text="Paste the Audible/Goodreads book page link here")
        self.urlEntry.grid(row=2, column=1, sticky="ew", pady=(4, 12))
        self.urlEntry.bind("<Return>", lambda event: self._submitUrl())

        #clipboard mode replaces the paste box with an instruction
        self.clipModeLabel = ctk.CTkLabel(self.fetchPanel, font=ctk.CTkFont(size=13), anchor="w",
                                          text="Copy the book page link in your browser - it will be picked up automatically.")
        self.clipModeLabel.grid(row=2, column=1, sticky="ew", pady=(4, 12))
        self.clipModeLabel.grid_remove()

        buttonRow = ctk.CTkFrame(self.fetchPanel, fg_color="transparent")
        buttonRow.grid(row=2, column=2, padx=(8, PAD), pady=(4, 12))
        self.submitButton = ctk.CTkButton(buttonRow, text="Submit", width=80, height=32, command=self._submitUrl)
        self.submitButton.grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(buttonRow, text="Skip Book", width=80, height=32, command=self._skipFetch,
                      fg_color="transparent", border_width=1).grid(row=0, column=1)

        self.fetchPanel.grid_remove()  #hidden until a fetch is waiting

    # ---------- fetch panel ----------

    def _clipboardModeActive(self):
        return self.fetchInputMenu.get() == FETCH_INPUT_MODES[0]

    def _updateFetchHint(self):
        if self._clipboardModeActive():
            self.fetchHint.configure(text="For each book, a browser search opens automatically.\nCopy the book page link in your browser to continue.")
        else:
            self.fetchHint.configure(text="For each book, a panel will appear above the log.\nOpen the search, then paste the book page link to continue.")

    def showFetchPanel(self, searchText, searchURL, fileName, reason=None):
        self.currentSearchURL = searchURL
        self.fetchBookLabel.configure(text=f"File: {fileName}\nSearch: {searchText}")
        self.urlEntry.delete(0, "end")

        if reason:
            self.fetchReasonLabel.configure(text="⚠️  " + reason)
            self.fetchReasonLabel.grid()
        else:
            self.fetchReasonLabel.grid_remove()

        if self._clipboardModeActive():
            self.urlEntry.grid_remove()
            self.submitButton.grid_remove()
            self.clipModeLabel.grid()
            #baseline the clipboard so only NEW copies count; reset it if it already holds a book link
            try:
                self._clipboardBaseline = pyperclip.paste()
                if any(s in self._clipboardBaseline for s in ("audible.com", "goodreads.com")):
                    pyperclip.copy("Ultimate Audiobooks")
                    self._clipboardBaseline = "Ultimate Audiobooks"
            except Exception:
                self._clipboardBaseline = ""
            #hands-free flow: launch the browser search automatically, like the CLI does
            Util.open_url_cross_platform(searchURL)
            self.statusLabel.configure(text="Waiting for a book link (copy it in your browser)...")
        else:
            self.clipModeLabel.grid_remove()
            self.urlEntry.grid()
            self.submitButton.grid()
            self.urlEntry.focus_set()
            self.statusLabel.configure(text="Waiting for a book link (paste it into the panel)...")

        self.fetchPanel.grid()

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
        #clipboard mode: a newly copied book link (or 'skip') submits itself
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

    def _clearLogs(self):
        for box in (self.logBox, self.prettyBox):
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.configure(state="disabled")
        self._bookTotal = 0
        self._bookIndex = 0
        self._currentBook = None
        self._sawRunFinished = False

    def _appendLog(self, entry):
        #the raw pane is the diagnostic view: every log record, verbatim
        self.logBox.configure(state="normal")
        self.logBox.insert("end", entry.formatted + "\n", tags=(entry.level.lower(),))
        self.logBox.see("end")
        self.logBox.configure(state="disabled")

    # ---------- pretty pane: rendering run events ----------

    def _prettyLine(self, text, tag="pretty_info", blankBefore=False):
        box = self.prettyBox
        box.configure(state="normal")
        if blankBefore:
            box.insert("end", "\n")
        box.insert("end", text + "\n", tags=(tag,))
        box.see("end")
        box.configure(state="disabled")

    def _setProgress(self, fraction):
        if self._indeterminate:
            self.progressBar.stop()
            self.progressBar.configure(mode="determinate")
            self._indeterminate = False
        self.progressBar.set(max(0.0, min(1.0, fraction)))

    def _setIndeterminate(self):
        #used for phases whose size isn't known up front, such as the chapter merge
        if not self._indeterminate:
            self.progressBar.configure(mode="indeterminate")
            self.progressBar.start()
            self._indeterminate = True

    def _describeSettings(self, values):
        parts = [str(values.get("output")), "move" if values.get("move") else "copy"]
        if values.get("fetch"):
            parts.append("fetch " + str(values["fetch"]))
        if values.get("create"):
            parts.append(str(values["create"]) + " sidecar")
        if values.get("convert"):
            parts.append("convert m4b")
        if values.get("clean"):
            parts.append("write tags")
        if values.get("dryRun"):
            parts.append("dry run")
        return " · ".join(parts)

    def _qualify(self, label):
        #Steps belonging to the book we just announced need no label. Conversions run in parallel
        #after the per-book loop, so those do - without it the lines are unattributable.
        return "" if (not label or label == self._currentBook) else f" {label}"

    def _handleEvent(self, event):
        #The single place run events become widgets. Reporter.py is the list of what can arrive;
        #adding a field there cannot silently stop rendering the way a reworded log line used to.
        if isinstance(event, Reporter.RunStarted):
            self._bookTotal, self._bookIndex = 0, 0
            self._currentBook = None
            self._prettyLine(f"▶ {event.mode}", "book_header")
            if event.settingsSummary:
                self._prettyLine("   " + self._describeSettings(event.settingsSummary), "muted")

        elif isinstance(event, Reporter.PhaseStarted):
            self._bookTotal, self._bookIndex = event.total, 0
            self._currentBook = None  #a new phase means the per-book narration no longer applies
            self._prettyLine(f"▸ {event.name}", "muted", blankBefore=True)
            if event.total > 0:
                self._setProgress(0)
            else:
                self._setIndeterminate()

        elif isinstance(event, Reporter.PhaseFinished):
            self._currentBook = None
            self._prettyLine(f"✔ {event.name}", "muted")

        elif isinstance(event, Reporter.BookStarted):
            self._bookIndex = event.index
            self._currentBook = event.label
            if event.total > 0:
                self._bookTotal = event.total
                self._prettyLine(f"📖 [{event.index}/{event.total}] {event.label}",
                                 "book_header", blankBefore=True)
                self._setProgress((event.index - 1) / event.total)
            else:
                self._prettyLine(f"📖 {event.label}", "book_header", blankBefore=True)
            self.statusLabel.configure(text="Processing " + event.label)

        elif isinstance(event, Reporter.BookStep):
            detail = f" — {event.detail}" if event.detail else ""
            self._prettyLine(f"  {Reporter.stepGlyph(event.step)} "
                             f"{Reporter.stepLabel(event.step)}{self._qualify(event.label)}{detail}",
                             "pretty_info")

        elif isinstance(event, Reporter.StepProgress):
            self._renderStepProgress(event)

        elif isinstance(event, Reporter.BookFinished):
            self._renderBookFinished(event)

        elif isinstance(event, Reporter.FetchFailed):
            #also shown in the fetch panel when it reappears; keep a trace in the transcript
            self._prettyLine(f"  ⚠️  {event.reason}", "warning")

        elif isinstance(event, Reporter.DryRunPlanned):
            self._appendPrettyDryRun(event.plan)

        elif isinstance(event, Reporter.RunFinished):
            self._sawRunFinished = True
            self._appendPrettySummary(event)

    def _renderStepProgress(self, event):
        if event.total <= 0:
            return
        percent = min(100, int(event.done / event.total * 100))
        label = f"{Reporter.stepLabel(event.step)}: {percent}%"

        if self._bookTotal > 0 and self._bookIndex > 0:
            #fold the step's progress into this book's slice of the overall bar
            base = (self._bookIndex - 1) / self._bookTotal
            self._setProgress(base + (percent / 100) / self._bookTotal)
            label = f"[{self._bookIndex}/{self._bookTotal}] {label}"

        self.statusLabel.configure(text=label)

    def _renderBookFinished(self, event):
        reason = f" — {event.reason}" if event.reason else ""
        if event.status == Reporter.STATUS_FAILED:
            self._prettyLine(f"  ❌ Failed: {event.label}{reason}", "error")
        elif event.status == Reporter.STATUS_SKIPPED:
            self._prettyLine(f"  ⏭️  Skipped: {event.label}{reason}", "warning")
        else:
            self._prettyLine(f"  ✅ Done{self._qualify(event.label)}", "pretty_info")

        if self._bookTotal > 0 and self._bookIndex > 0:
            self._setProgress(self._bookIndex / self._bookTotal)

    def _appendPrettyDryRun(self, plan):
        #A dry run produces one plan rather than a stream of per-book activity, so pretty mode
        #renders it as a block: what would happen, then the books it would happen to.
        box = self.prettyBox
        box.configure(state="normal")
        box.insert("end", "\n")
        box.insert("end", "🧪 Dry run\n", tags=("book_header",))
        box.insert("end", f"  📂 Output: {plan.output}\n", tags=("pretty_info",))
        if plan.perBookDest:
            box.insert("end", "      each book lands in Author/Title from the fetched metadata\n", tags=("muted",))
        box.insert("end", f"  {'🚚' if plan.verb == 'move' else '📋'} Mode: {plan.verb} — {plan.modeNote}\n",
                   tags=("pretty_info",))
        box.insert("end", f"  🔧 Each book: {' → '.join(plan.steps)}\n", tags=("pretty_info",))

        if not plan.books:
            box.insert("end", f"  ⚠️  Nothing to do — {plan.emptyNote}.\n", tags=("warning",))
        else:
            noun = "book" if len(plan.books) == 1 else "books"
            box.insert("end", f"\n  📚 {len(plan.books)} {noun} to {'assemble' if plan.combine else 'process'}:\n",
                       tags=("pretty_info",))
            width = len(str(len(plan.books)))
            for number, (label, detail) in enumerate(plan.books, 1):
                box.insert("end", f"     {number:>{width}}. {label}", tags=("pretty_info",))
                if detail:
                    box.insert("end", f"  {detail}", tags=("muted",))
                box.insert("end", "\n")

        box.see("end")
        box.configure(state="disabled")

    def _appendPrettySummary(self, event):
        if event.dryRun:
            #skip/fail counts are meaningless here: a dry run never gets as far as processing a book
            self._prettyLine("🧪 Dry run finished — nothing was written. "
                             "Switch Dry run off to carry out this plan.", "pretty_info",
                             blankBefore=True)
            return

        if not event.skips and not event.fails:
            self._prettyLine("✅ Finished — all books processed cleanly.", "pretty_info",
                             blankBefore=True)
            return

        tag = "error" if event.fails else "warning"
        self._prettyLine(f"🏁 Finished — {len(event.skips)} skipped, {len(event.fails)} failed.",
                         tag, blankBefore=True)
        for item in event.skips:
            self._prettyLine(f"  ⏭️  {item}", "warning")
        for item in event.fails:
            self._prettyLine(f"  ❌ {item}", "error")

    def _pollLogs(self):
        try:
            while True:
                self._appendLog(self.logQueue.get_nowait())
        except queue.Empty:
            pass

        try:
            while True:
                self._handleEvent(self.eventQueue.get_nowait())
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
            if self.fetchPanel.winfo_ismapped() and self._clipboardModeActive():
                self._watchClipboard()

        if self.workerThread and not self.workerThread.is_alive():
            self.workerThread = None
            self.startButton.configure(state="normal")
            try:
                while True:
                    title, message = self.errorQueue.get_nowait()
                    messagebox.showerror(title, message)
            except queue.Empty:
                pass
            self._hideFetchPanel()
            if self._indeterminate:
                self.progressBar.stop()
                self.progressBar.configure(mode="determinate")
                self._indeterminate = False
            if self._sawRunFinished:
                self.progressBar.set(1)
                self.statusLabel.configure(text="Finished - dry run, nothing was written"
                                           if self._dryRunActive else "Finished")
            else:
                #no RunFinished means the run never got going (bad settings) or it crashed
                self.progressBar.set(0)
                self.statusLabel.configure(text="Run did not complete - see the log")

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
            "dryRun": bool(self.dryRunSwitch.get()),
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
        values.pop("dryRun", None)  #dry run is a per-run toggle, never persisted (matches CLI)
        try:
            values["batch"] = int(values["batch"])
            values["workers"] = int(values["workers"])
        except ValueError:
            pass  #save as-is; validated properly at run time
        with open(Settings.SETTINGS_FILE, 'w') as outFile:
            json.dump(values, outFile)
        log.info("Settings saved to " + str(Settings.SETTINGS_FILE))

    def _loadSettings(self, silent=False):
        try:
            with open(Settings.SETTINGS_FILE, 'r') as inFile:
                saved = json.load(inFile)
        except FileNotFoundError:
            if not silent:
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
        #Form fields on top of the CLI's own defaults, so flags the GUI doesn't expose can't go
        #missing and can't drift out of step with Settings.buildParser.
        values = Settings.defaults()
        values.update(self._formValues())

        if not values["input"]:
            messagebox.showerror("Missing input", "Please choose an input folder.")
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

        #everything else (missing folders, special characters, recurse-combine needing move) is
        #Settings.validate's job, and is reported from _runWorker
        return Namespace(**values)

    def _startRun(self):
        if self.workerThread:
            return
        args = self._collectArgs()
        if args is None:
            return

        self._dryRunActive = bool(args.dryRun)
        numericLevel = getattr(logging, args.logLevel, logging.INFO)
        if self.prettyLogSwitch.get():
            numericLevel = min(numericLevel, logging.INFO)
        logging.getLogger().setLevel(numericLevel)
        self._clearLogs()
        self.startButton.configure(state="disabled")
        self.statusLabel.configure(text="Starting...")
        self._setProgress(0)

        self.workerThread = threading.Thread(target=self._runWorker, args=(args,), daemon=True)
        self.workerThread.start()

    def _runWorker(self, args):
        try:
            #reset state left over from a previous run in this same process
            BookStatus.clearSkips()
            BookStatus.clearFails()

            Main.main(args)
        except Settings.ConfigError as ce:
            #raised before anything is touched, so there is nothing to clean up - just explain it
            log.error(str(ce))
            self.errorQueue.put(("Cannot start run", str(ce)))
        except Exception as e:
            log.exception("Unexpected error during run")
            self.errorQueue.put(("Run failed", f"{type(e).__name__}: {e}\n\nSee the log for details."))


if __name__ == "__main__":
    guiState = loadGuiState()
    ctk.set_appearance_mode(guiState.get("appearance", "Dark"))
    ctk.set_default_color_theme("dark-blue")
    scale = guiState.get("uiScale", DEFAULT_UI_SCALE)
    try:
        ctk.set_widget_scaling(int(str(scale).rstrip('%')) / 100)
    except ValueError:
        ctk.set_widget_scaling(int(DEFAULT_UI_SCALE.rstrip('%')) / 100)
    App(guiState).mainloop()
