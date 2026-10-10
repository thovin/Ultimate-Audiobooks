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
import LogSetup
import BookStatus
import Util

log = logging.getLogger(__name__)

PAD = 14
FETCH_OPTIONS = ["Off", "Audible", "Goodreads", "Both"]
FETCH_INPUT_MODES = ["Clipboard (copy link)", "Paste box"]
CREATE_OPTIONS = ["Off", "OPF"]  #INFOTEXT not yet implemented
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
#The drawer defaults to DEBUG because logging is diagnostics only now - the run itself narrates
#itself through Reporter events into the activity view, so at INFO the drawer is nearly empty and
#reads as broken. This is a view preference (gui_state.json), not the CLI's --logLevel.
DEFAULT_DRAWER_LEVEL = "DEBUG"
MODES = ["Single level", "Recurse fetch", "Recurse combine"]  #Recurse preserve not yet implemented
UI_SCALES = ["90%", "100%", "110%", "125%", "150%"]
DEFAULT_UI_SCALE = "110%"
#log pane text size, adjustable independently of UI scale (ctrl +/-/0 or ctrl+wheel over the log)
LOG_FONT_SIZES = ["10", "11", "12", "13", "14", "16", "18", "20", "24"]
DEFAULT_LOG_FONT_SIZE = 13
MIN_LOG_FONT_SIZE = 8
MAX_LOG_FONT_SIZE = 32
DEFAULT_GEOMETRY = "1440x860"
LOG_DRAWER_HEIGHT = 260
MIN_LOG_DRAWER_HEIGHT = 120
ACTIVITY_PEEK = 44  #the drawer overlays the activity list but stops just below its first line

#Background of the main area, and of the PanedWindow sash behind it. This has to be a real colour
#rather than "transparent": the main area hangs off a plain tk.PanedWindow, and CustomTkinter cannot
#read a background colour through a non-CTk parent - it falls back to the default frame grey, which
#draws a visible lighter rectangle behind every transparent child (buttons especially).
MAIN_BG = ("#d4d4d4", "#1a1a1a")

#(light, dark) pairs, so CustomTkinter swaps them with the appearance mode and rows need no retheming
ROW_COLORS = {
    "active":  ("gray10", "gray95"),
    "normal":  ("gray20", "gray85"),
    "muted":   ("gray45", "gray60"),
    "warning": ("#9a6700", "#e3b341"),
    "error":   ("#c62828", "#ff6b6b"),
    "success": ("#1b7f3b", "#4ade80"),
}

#The dark-blue theme gives every button the same light text colour in both appearance modes, because
#it assumes buttons are filled with the accent colour. Outline buttons need a colour that actually
#follows the mode, or they are unreadable in light mode.
OUTLINE_TEXT = ("gray10", "gray90")

#The log bar's buttons are deliberately filled rather than outlined. A button with
#fg_color="transparent" has no background of its own: CustomTkinter paints the text label with a
#*guess* at what is behind it, walked up the master chain. The log bar is three transparent frames
#deep and hangs off a plain tk.PanedWindow, so any disagreement between that guess and the pixels
#actually on screen shows up as a faint rectangle hugging the button's text. A real fill removes the
#guess entirely - the label sits on the button's own colour.
QUIET_FILL = ("#c4c4c4", "#2d2d2d")
QUIET_HOVER = ("#b4b4b4", "#3c3c3c")

#Cards (run header, dry run plan, final summary) are outlined rather than filled, so they read as
#annotations about the run instead of as another book in the list.
CARD_BORDER = ("gray70", "gray32")

#A dry run must be impossible to mistake for a real one, so it gets a banner pinned above the
#scrolling list rather than a card that the activity can push out of view.
DRY_RUN_FILL = ("#fde68a", "#6b3f08")
DRY_RUN_TEXT = ("#6b3f08", "#fde68a")

#how a finished book presents itself: glyph, and which palette entry its detail line uses
STATUS_STYLE = {
    Reporter.STATUS_OK:      ("✅", "Done", "normal"),
    Reporter.STATUS_SKIPPED: ("⏭️", "Skipped", "warning"),
    Reporter.STATUS_FAILED:  ("❌", "Failed", "error"),
}

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
    formatted: str  #what the drawer shows, e.g. "[14:02:11][INFO] Processing foo.mp3"
    level: str      #record.levelname, used to colour the line


class QueueHandler(logging.Handler):
    #worker threads log freely; the GUI thread drains the queue (tkinter widgets are not thread-safe)
    def __init__(self, logQueue):
        super().__init__()
        self.logQueue = logQueue

    def emit(self, record):
        try:
            self.logQueue.put(LogEntry(formatted=self.format(record), level=record.levelname))
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
        #the worker thread is the one Reporter attributes events to, so this is the waiting book
        self.app.fetchRequests.put((searchText, searchURL, file.name, reason, Reporter._currentBookId))
        return self.responses.get()


def hide(widget):
    """Unmap a widget so it stays unmapped when the UI scale changes.

    CustomTkinter remembers each widget's last grid() call and replays it on every rescale, and only
    grid_forget clears that memory - grid_remove does not. So a widget hidden with grid_remove (the
    fetch panel, the log drawer, the dry run banner) comes back the moment the scale is changed.
    Showing it again is still a plain widget.grid(), which Tk restores from its own saved options."""
    widget._last_geometry_manager_call = None
    widget.grid_remove()


def wrapToWidth(container, labels, padding):
    """Keep labels wrapping to their container instead of being clipped by it.

    Output paths and failure reasons are long and the sidebar sash is draggable, so a fixed
    wraplength would be wrong at most window sizes."""
    def onResize(event):
        #event.width is in real pixels but CTkLabel scales wraplength itself, so un-scale it here or
        #the text wraps wider than the container whenever the UI scale is above 100%
        for label in labels:
            label.configure(wraplength=max(200, label._reverse_widget_scaling(event.width - padding)))
    container.bind("<Configure>", onResize)


class BookRow(ctk.CTkFrame):
    """One book, updated in place.

    A row is the unit the activity view is built from. Conversions run in parallel across worker
    processes, so several rows are genuinely live at once and each owns its own progress - which is
    the thing an append-only transcript could never show."""

    def __init__(self, parent, label, index=0, total=0):
        super().__init__(parent, fg_color=("gray92", "gray17"), corner_radius=8)
        self.grid_columnconfigure(1, weight=1)

        self.label = label
        self.detail = "Queued"
        self.started = False  #announced but not yet acted on - queued for conversion, typically
        self.finished = False
        self.planned = False  #a dry-run row: nothing is happening to it, so it isn't "in flight"
        self.status = None
        self.fraction = 0.0

        self.glyphLabel = ctk.CTkLabel(self, text="⏳", width=30, font=ctk.CTkFont(size=16))
        self.glyphLabel.grid(row=0, column=0, rowspan=2, padx=(10, 2), pady=8)

        self.titleLabel = ctk.CTkLabel(self, text=label, anchor="w", justify="left",
                                       font=ctk.CTkFont(size=13, weight="bold"),
                                       text_color=ROW_COLORS["active"])
        self.titleLabel.grid(row=0, column=1, sticky="ew", pady=(8, 0))

        self.countLabel = ctk.CTkLabel(self, text=self._countText(index, total), anchor="e",
                                       font=ctk.CTkFont(size=12), text_color=ROW_COLORS["muted"])
        self.countLabel.grid(row=0, column=2, sticky="e", padx=(8, 12), pady=(8, 0))

        self.detailLabel = ctk.CTkLabel(self, text=self.detail, anchor="w", justify="left",
                                        font=ctk.CTkFont(size=12), text_color=ROW_COLORS["muted"])
        self.detailLabel.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=(0, 8))

        #created on the first StepProgress: most steps finish too fast to measure, and an empty bar
        #sitting at zero reads as a stall
        self.progressBar = None

        #the glyph and count columns are fixed, so the text columns get whatever is left
        wrapToWidth(self, (self.titleLabel, self.detailLabel), 120)

    @staticmethod
    def _countText(index, total):
        if index and total and total > 0:
            return f"{index} / {total}"
        return str(index) if index else ""

    def setCount(self, index, total):
        self.countLabel.configure(text=self._countText(index, total))

    def _setDetail(self, text, colorKey):
        self.detail = text
        self.detailLabel.configure(text=text, text_color=ROW_COLORS[colorKey])

    def setStep(self, step, detail=None):
        self.started = True
        self.glyphLabel.configure(text=Reporter.stepGlyph(step))
        self._setDetail(Reporter.stepLabel(step) + (f" — {detail}" if detail else ""), "active")

    def setProgress(self, step, fraction):
        self.started = True
        self.fraction = max(0.0, min(1.0, fraction))
        if self.progressBar is None:
            self.progressBar = ctk.CTkProgressBar(self, height=6)
            self.progressBar.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=(0, 10))
        self.progressBar.set(self.fraction)
        self.glyphLabel.configure(text=Reporter.stepGlyph(step))
        self._setDetail(f"{Reporter.stepLabel(step)}  {int(self.fraction * 100)}%", "active")

    def finish(self, status, reason=None):
        self.finished = True
        self.status = status
        self.fraction = 1.0
        glyph, word, colorKey = STATUS_STYLE.get(status, STATUS_STYLE[Reporter.STATUS_OK])
        self.glyphLabel.configure(text=glyph)
        if self.progressBar is not None:
            #a finished row has nothing left to measure, and dropping the bar keeps the list compact
            self.progressBar.destroy()
            self.progressBar = None
        self._setDetail(word + (f" — {reason}" if reason else ""), colorKey)
        self.titleLabel.configure(text_color=ROW_COLORS["normal"])

    def setPlanned(self, detail=None):
        #dry run: the same row, describing what would happen rather than what is happening
        self.planned = True
        self.glyphLabel.configure(text="•")
        self.titleLabel.configure(text_color=ROW_COLORS["normal"])
        self._setDetail(detail or "", "muted")

    def setWarning(self, text):
        self.glyphLabel.configure(text="⚠️")
        self._setDetail(text, "warning")

    def setWaiting(self):
        #blocked on the user: outlined and amber so it stands out from rows the app is working on
        self.started = True
        self.glyphLabel.configure(text="🔗")
        self.configure(border_width=2, border_color=ROW_COLORS["warning"])
        self._setDetail("Waiting for a book link — see the fetch panel", "warning")

    def clearWaiting(self):
        self.configure(border_width=0)
        self.glyphLabel.configure(text=Reporter.stepGlyph(Reporter.STEP_FETCH))
        self._setDetail(Reporter.stepLabel(Reporter.STEP_FETCH), "active")

    def statusText(self):
        return f"{self.label} — {self.detail}"


class ActivityView(ctk.CTkScrollableFrame):
    """The main surface: a run header, a live row per book, and a closing summary.

    Rows are keyed on Reporter bookId rather than on the displayed label, because the two are not
    the same - a book announced as "dune.mp3" reports its tagging step as "Dune"."""

    MAX_ROWS = 200  #hundreds of CTk frames get sluggish, and batch size is user-settable

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._prunedLabel = None
        self._scrollPending = False
        self.totalBooks = 0
        self.finishedCount = 0
        self._rows = {}
        self._widgets = []
        self._pruned = {}
        self._nextGridRow = 0
        self._idleLabel = None
        self.reset()

    # ---------- structure ----------

    def reset(self):
        for widget in self._widgets:
            widget.destroy()
        for row in self._rows.values():
            row.destroy()
        if self._prunedLabel is not None:
            self._prunedLabel.destroy()
            self._prunedLabel = None

        self._rows = {}
        self._widgets = []
        self._pruned = {}
        self._follow = True
        self._nextGridRow = 0  #grid row 0 is reserved for the pruned-rows notice
        self.totalBooks = 0
        self.finishedCount = 0
        self._showIdleHint()

    def _showIdleHint(self):
        self._idleLabel = ctk.CTkLabel(self, text="Choose an input folder and press Start Processing.",
                                       anchor="w", font=ctk.CTkFont(size=13),
                                       text_color=ROW_COLORS["muted"])
        self._idleLabel.grid(row=1, column=0, sticky="ew", padx=6, pady=10)
        self._widgets.append(self._idleLabel)

    def _clearIdleHint(self):
        if self._idleLabel is not None:
            self._idleLabel.destroy()
            self._widgets.remove(self._idleLabel)
            self._idleLabel = None

    def _place(self, widget, pady=(0, 8)):
        self._clearIdleHint()  #the hint occupies the first grid row, so it has to go before anything else
        self._nextGridRow += 1
        widget.grid(row=self._nextGridRow, column=0, sticky="ew", padx=4, pady=pady)
        self._autoscroll()

    def _card(self, title, lines, titleColor="active", accent=None):
        #outlined, not filled: a card is a statement about the run, and must not be mistaken for a
        #book row the way the old filled summary was
        card = ctk.CTkFrame(self, fg_color="transparent", corner_radius=8, border_width=2,
                            border_color=ROW_COLORS[accent] if accent else CARD_BORDER)
        card.grid_columnconfigure(0, weight=1)
        wrapped = []
        titleLabel = ctk.CTkLabel(card, text=title, anchor="w", justify="left",
                                  font=ctk.CTkFont(size=14, weight="bold"), text_color=ROW_COLORS[titleColor])
        titleLabel.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(10, 2 if lines else 10))
        wrapped.append(titleLabel)
        for number, (text, colorKey) in enumerate(lines, 1):
            line = ctk.CTkLabel(card, text=text, anchor="w", justify="left", font=ctk.CTkFont(size=12),
                                text_color=ROW_COLORS[colorKey])
            line.grid(row=number, column=0, sticky="ew", padx=PAD,
                      pady=(0, 10 if number == len(lines) else 2))
            wrapped.append(line)
        wrapToWidth(card, wrapped, 2 * PAD)
        self._widgets.append(card)
        self._place(card)
        return card

    def _autoscroll(self):
        #follow the newest row, but only when the view is already at the bottom: yanking the scroll
        #away while someone is reading an earlier failure is worse than not following at all
        if not self._follow:
            return
        try:
            if self._parent_canvas.yview()[1] < 0.995:
                return
        except Exception:
            return
        if not self._scrollPending:
            self._scrollPending = True
            self.after(50, self._scrollToEnd)

    def _scrollToEnd(self):
        self._scrollPending = False
        try:
            self._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    # ---------- rows ----------

    def row(self, bookId, label=None, index=0, total=0):
        """The row for this book, created if it doesn't exist yet.

        Creating on demand means an unexpected step still lands somewhere visible instead of being
        dropped on the floor."""
        key = bookId or label or "?"
        existing = self._rows.get(key)
        if existing is not None:
            return existing

        self._prune()
        row = BookRow(self, label or key, index, total)
        self._rows[key] = row
        self._place(row, pady=(0, 6))
        return row

    def _prune(self):
        if len(self._rows) < self.MAX_ROWS:
            return
        for key, row in list(self._rows.items()):
            if len(self._rows) < self.MAX_ROWS:
                break
            if not row.finished:
                continue  #never prune a book that is still in flight
            self._pruned[row.status] = self._pruned.get(row.status, 0) + 1
            row.destroy()
            del self._rows[key]
        self._showPruned()

    def _showPruned(self):
        total = sum(self._pruned.values())
        if not total:
            return
        text = (f"…  {total} earlier book{'s' if total != 1 else ''} hidden  "
                f"({self._pruned.get(Reporter.STATUS_OK, 0)} done, "
                f"{self._pruned.get(Reporter.STATUS_SKIPPED, 0)} skipped, "
                f"{self._pruned.get(Reporter.STATUS_FAILED, 0)} failed)")
        if self._prunedLabel is None:
            self._prunedLabel = ctk.CTkLabel(self, anchor="w", font=ctk.CTkFont(size=12),
                                             text_color=ROW_COLORS["muted"])
            self._prunedLabel.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 6))
        self._prunedLabel.configure(text=text)

    def inFlight(self):
        """Rows still to finish - including ones only queued so far, so the bar accounts for them."""
        return [row for row in self._rows.values() if not row.finished and not row.planned]

    def working(self):
        """Rows something is actually happening to right now, for the status line."""
        return [row for row in self.inFlight() if row.started]

    def overallFraction(self):
        """Completion across the batch, or None when the batch size isn't known.

        Counts the in-flight books' own progress, so three parallel conversions move the bar
        smoothly instead of it jumping a whole book at a time."""
        if self.totalBooks <= 0:
            return None
        partial = sum(row.fraction for row in self.inFlight())
        return min(1.0, (self.finishedCount + partial) / self.totalBooks)

    # ---------- events ----------

    def runStarted(self, event):
        if event.settingsSummary.get("dryRun"):
            #the pinned banner already says this is a dry run, and the mode name ("Combining chapter
            #folders...") would read as if work had started
            return
        #the sidebar already shows the settings; the full record goes to the log file. A card always
        #needs a body line: its padding assumes one, and a title-only card renders cramped
        if event.totalBooks > 0:
            noun = "book" if event.totalBooks == 1 else "books"
            body = f"{event.totalBooks} {noun} queued"
        else:
            body = "Starting…"
        self._card(f"▶  {event.mode}", [(body, "muted")])

    def phaseStarted(self, event):
        if event.total > 0:
            self.totalBooks = event.total
            self.finishedCount = 0
        if self.inFlight():
            #The conversion phase begins after the per-book loop has already drawn every row, so a
            #heading here would sit underneath the rows it describes. Those rows say "Converting to
            #M4B" themselves; the status line carries the phase.
            return
        label = ctk.CTkLabel(self, text=event.name, anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=ROW_COLORS["muted"])
        self._widgets.append(label)
        self._place(label, pady=(10, 4))

    def phaseFinished(self, event):
        label = ctk.CTkLabel(self, text="✔  " + event.name, anchor="w", font=ctk.CTkFont(size=12),
                             text_color=ROW_COLORS["muted"])
        self._widgets.append(label)
        self._place(label, pady=(4, 4))

    def bookStarted(self, event):
        if event.total > 0:
            self.totalBooks = max(self.totalBooks, event.total)
        self.row(event.bookId, event.label, event.index, event.total).setCount(event.index, event.total)

    def bookStep(self, event):
        self.row(event.bookId, event.label).setStep(event.step, event.detail)

    def stepProgress(self, event):
        if event.total <= 0:
            return
        self.row(event.bookId, event.label).setProgress(event.step, event.done / event.total)

    def bookFinished(self, event):
        row = self.row(event.bookId, event.label)
        if not row.finished:
            self.finishedCount += 1
        row.finish(event.status, event.reason)

    def fetchFailed(self, event):
        #the fetch panel shows this too; the row keeps it visible once the panel is gone
        row = self._rows.get(event.bookId)
        if row is not None:
            row.setWarning(event.reason)

    def setWaiting(self, bookId, waiting):
        row = self._rows.get(bookId)
        if row is None or row.finished:
            return
        row.setWaiting() if waiting else row.clearWaiting()

    def dryRunPlanned(self, plan):
        #a plan is read top-down, not followed like a live run; scaled up it no longer fits, and
        #autoscroll would push the summary card off the top before anyone saw it
        self._follow = False
        lines = [(f"📂  Output: {plan.output}", "normal")]
        if plan.perBookDest:
            lines.append(("Each book lands in Author/Title from the fetched metadata", "muted"))
        lines.append((f"{'🚚' if plan.verb == 'move' else '📋'}  Mode: {plan.verb} — {plan.modeNote}", "normal"))
        lines.append((f"🔧  Each book: {' → '.join(plan.steps)}", "normal"))
        if not plan.books:
            lines.append((f"⚠️  Nothing to do — {plan.emptyNote}.", "warning"))
        self._card("Run settings", lines, titleColor="warning", accent="warning")

        if not plan.books:
            return
        noun = "book" if len(plan.books) == 1 else "books"
        verb, pastVerb = ("assemble", "assembled") if plan.combine else ("process", "processed")
        heading = ctk.CTkLabel(self, text=f"{len(plan.books)} {noun} to {verb}", anchor="w",
                               font=ctk.CTkFont(size=13, weight="bold"), text_color=ROW_COLORS["muted"])
        self._widgets.append(heading)
        self._place(heading, pady=(10, 4))

        for number, (label, detail) in enumerate(plan.books, 1):
            #the same widget as a live book, so there is only ever one way a book is drawn
            self.row(f"plan:{number}:{label}", label, number, len(plan.books)).setPlanned(
                detail or f"will be {pastVerb}")

    def runFinished(self, event):
        if event.dryRun:
            self._card("🧪  Dry run finished", [], titleColor="warning", accent="warning")
            return

        if not event.skips and not event.fails:
            self._card("✅  Finished", [("All books processed cleanly.", "muted")],
                       titleColor="success", accent="success")
            return

        lines = [(f"⏭️  {item}", "warning") for item in event.skips]
        lines += [(f"❌  {item}", "error") for item in event.fails]
        accent = "error" if event.fails else "warning"
        self._card(f"🏁  Finished — {len(event.skips)} skipped, {len(event.fails)} failed", lines,
                   titleColor=accent, accent=accent)


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

        #run events from the core pipeline; the activity view and the progress bar render these
        self.eventQueue = queue.Queue()
        Reporter.setReporter(GuiReporter(self.eventQueue))
        self._indeterminate = False
        self._sawRunFinished = False

        #worker-thread failures that deserve a dialog; shown from _pollLogs, since tkinter calls
        #(including after()) are only safe from the main thread
        self.errorQueue = queue.Queue()

        self.fetchRequests = queue.Queue()
        self.urlProvider = GuiUrlProvider(self)
        Util.setUrlProvider(self.urlProvider)
        self.currentSearchURL = None
        self._waitingBookId = None
        self._clipboardBaseline = ""
        self._clipboardTick = 0

        #resizable split between sidebar and activity area (drag the sash)
        self.paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bd=0,
                                    relief="flat", bg=self._panedColor())
        self.paned.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(self.paned, corner_radius=0)
        self._buildSidebar(sidebar)
        self.paned.add(sidebar, minsize=460, width=self.guiState.get("sidebarWidth", 560), stretch="never")

        mainArea = ctk.CTkFrame(self.paned, fg_color=MAIN_BG, corner_radius=0)
        self._buildMainArea(mainArea)
        self.paned.add(mainArea, minsize=450, stretch="always")

        self._applyGuiState()
        self._bindFontShortcuts()
        self.protocol("WM_DELETE_WINDOW", self._onClose)
        self.after(100, self._pollLogs)

    def _applyGuiState(self):
        self.appearanceMenu.set(self.guiState.get("appearance", "Dark"))
        self.uiScaleMenu.set(self.guiState.get("uiScale", DEFAULT_UI_SCALE))
        self._setLogFontSize(self._logFontSize)
        fetchInput = self.guiState.get("fetchInput", FETCH_INPUT_MODES[0])
        self.fetchInputMenu.set(fetchInput if fetchInput in FETCH_INPUT_MODES else FETCH_INPUT_MODES[0])
        self._updateFetchHint()
        drawerLevel = self.guiState.get("logLevel", DEFAULT_DRAWER_LEVEL)
        self.logLevelMenu.set(drawerLevel if drawerLevel in LOG_LEVELS else DEFAULT_DRAWER_LEVEL)
        self._setLogLevel(self.logLevelMenu.get())
        if self.guiState.get("autoLoadSettings"):
            self.autoLoadSwitch.select()
            self._loadSettings(silent=True)
        try:
            self._setLogDrawerHeight(int(self.guiState.get("logDrawerHeight", LOG_DRAWER_HEIGHT)))
        except (TypeError, ValueError):
            pass
        if self.guiState.get("logDrawerOpen"):
            self._toggleLogDrawer()

    def _onClose(self):
        state = {
            "geometry": self.geometry(),
            "sidebarWidth": self.paned.sash_coord(0)[0],
            "appearance": self.appearanceMenu.get(),
            "uiScale": self.uiScaleMenu.get(),
            "logFontSize": self._logFontSize,
            "logLevel": self.logLevelMenu.get(),
            "fetchInput": self.fetchInputMenu.get(),
            "autoLoadSettings": bool(self.autoLoadSwitch.get()),
            "logDrawerHeight": self._logDrawerHeight,
            "logDrawerOpen": self.logDrawerOpen,
        }
        try:
            with open(GUI_STATE_FILE, 'w') as outFile:
                json.dump(state, outFile)
        except OSError:
            pass
        self.destroy()

    def _panedColor(self):
        return MAIN_BG[1] if ctk.get_appearance_mode() == "Dark" else MAIN_BG[0]

    def _setAppearance(self, mode):
        ctk.set_appearance_mode(mode)
        self.paned.configure(bg=self._panedColor())
        self._configureLogTags(self.logBox)

    def _setUiScale(self, value):
        ctk.set_widget_scaling(int(value.rstrip('%')) / 100)

    def _setLogFontSize(self, value):
        #dropdown, ctrl +/-/0, or ctrl+wheel over the log drawer
        size = clampLogFontSize(value)
        self._logFontSize = size
        self.logFont.configure(size=size)
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
        #the drawer shows what the level dropdown asks for; the log file always gets DEBUG
        self.logHandler = QueueHandler(self.logQueue)
        self.logHandler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s",
                                                       datefmt="%H:%M:%S"))
        self.logHandler.setLevel(getattr(logging, DEFAULT_DRAWER_LEVEL, logging.DEBUG))
        LogSetup.setupLogging(extraHandler=self.logHandler)

    _LOG_TAG_COLORS = {
        "debug":    ("gray50", "gray50"),
        "info":     ("gray20", "gray85"),
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
                      fg_color="transparent", border_width=1, text_color=OUTLINE_TEXT).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(buttons, text="Load Settings", height=32, command=self._loadSettings,
                      fg_color="transparent", border_width=1, text_color=OUTLINE_TEXT).grid(row=0, column=1, sticky="ew", padx=(5, 0))
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
                                           lambda p: ctk.CTkEntry(p, width=170, height=32, font=font13),
                                           lastInCard=True)
        self.batchEntry.insert(0, "10")

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

        self.autoLoadSwitch = ctk.CTkSwitch(card, text="Auto-load settings on launch", font=font13)
        self.autoLoadSwitch.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 12))

    def _buildMainArea(self, container):
        main = ctk.CTkFrame(container, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(main, text="Activity", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("gray30", "gray70")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        #pinned above the scrolling list: a dry run has to stay obvious no matter how far the
        #activity has scrolled, because mistaking one for a real run is an expensive misunderstanding
        self.dryRunBanner = ctk.CTkFrame(main, fg_color=DRY_RUN_FILL, corner_radius=8)
        self.dryRunBanner.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.dryRunBanner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.dryRunBanner,
                     text="🧪   DRY RUN — no changes made",
                     anchor="center", font=ctk.CTkFont(size=15, weight="bold"), text_color=DRY_RUN_TEXT
                     ).grid(row=0, column=0, sticky="ew", padx=PAD, pady=10)
        hide(self.dryRunBanner)

        self._buildFetchPanel(main)

        self.activity = ActivityView(main)
        self.activity.grid(row=3, column=0, sticky="nsew")

        self._buildLogDrawer(main)

        statusRow = ctk.CTkFrame(main, fg_color="transparent")
        statusRow.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        statusRow.grid_columnconfigure(0, weight=1)
        self.statusLabel = ctk.CTkLabel(statusRow, text="Ready", anchor="w", font=ctk.CTkFont(size=13))
        self.statusLabel.grid(row=0, column=0, sticky="w")
        #determinate by default: book counts come from the events, so real progress is known
        self.progressBar = ctk.CTkProgressBar(statusRow, width=200, mode="determinate")
        self.progressBar.grid(row=0, column=1, sticky="e")
        self.progressBar.set(0)

    def _buildLogDrawer(self, main):
        #Diagnostics live here, out of the way. The activity view above is what a run looks like;
        #this is for when something went wrong and the file isn't convenient to open.
        bar = self.logBar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        bar.grid_columnconfigure(1, weight=1)

        self.logToggleButton = ctk.CTkButton(bar, text="Show log  ▾", width=140, height=30,
                                             font=ctk.CTkFont(size=12), fg_color=QUIET_FILL,
                                             hover_color=QUIET_HOVER, text_color=OUTLINE_TEXT,
                                             command=self._toggleLogDrawer)
        self.logToggleButton.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bar, text="Open log folder", width=140, height=30, font=ctk.CTkFont(size=12),
                      fg_color=QUIET_FILL, hover_color=QUIET_HOVER, text_color=OUTLINE_TEXT,
                      command=self._openLogFolder).grid(row=0, column=2, sticky="e")

        self.logDrawer = ctk.CTkFrame(main, height=LOG_DRAWER_HEIGHT)
        self.logDrawer.grid_columnconfigure(0, weight=1)
        self.logDrawer.grid_rowconfigure(2, weight=1)
        self.logDrawer.grid_propagate(False)
        self._logDrawerHeight = LOG_DRAWER_HEIGHT
        self.logDrawerOpen = False

        #drag hangle along the top edge: dragging up makes the drawer taller
        self.logGrip = ctk.CTkFrame(self.logDrawer, height=14, fg_color=QUIET_FILL, corner_radius=6,
                                    cursor="sb_v_double_arrow")
        self.logGrip.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(6, 0))
        ctk.CTkLabel(self.logGrip, text="· · ·", height=10, font=ctk.CTkFont(size=10),
                     text_color=ROW_COLORS["muted"], cursor="sb_v_double_arrow").place(relx=0.5, rely=0.5, anchor="center")
        for widget in (self.logGrip, *self.logGrip.winfo_children()):
            widget.bind("<ButtonPress-1>", self._gripPress)
            widget.bind("<B1-Motion>", self._gripDrag)

        controls = ctk.CTkFrame(self.logDrawer, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(6, 6))
        controls.grid_columnconfigure(4, weight=1)
        ctk.CTkLabel(controls, text="Level:", font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.logLevelMenu = ctk.CTkOptionMenu(controls, values=LOG_LEVELS, width=130, height=28,
                                              font=ctk.CTkFont(size=12), command=self._setLogLevel)
        self.logLevelMenu.set(DEFAULT_DRAWER_LEVEL)
        self.logLevelMenu.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ctk.CTkLabel(controls, text="Font size:", font=ctk.CTkFont(size=12)).grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.logFontMenu = ctk.CTkOptionMenu(controls, values=LOG_FONT_SIZES, width=80, height=28,
                                             font=ctk.CTkFont(size=12), command=self._setLogFontSize)
        self.logFontMenu.set(str(self._logFontSize))
        self.logFontMenu.grid(row=0, column=3, sticky="w", padx=(8, 0))
        #Only worth saying while the drawer is open - it explains the Level dropdown sitting next to
        #it, and the bar above has no room for a line nobody reads when the log is put away.
        ctk.CTkLabel(controls,
                     text=f"Full DEBUG detail is always written to {LogSetup.LOG_FILE.name}, whatever this is set to.",
                     anchor="w", font=ctk.CTkFont(size=12), text_color=ROW_COLORS["muted"]
                     ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ctk.CTkLabel(controls, text="Ctrl +/- or ctrl+scroll over the log also works", anchor="w",
                     font=ctk.CTkFont(size=12), text_color=ROW_COLORS["muted"]
                     ).grid(row=2, column=0, columnspan=5, sticky="w")

        self.logFont = ctk.CTkFont(family="monospace", size=self._logFontSize)
        self.logBox = ctk.CTkTextbox(self.logDrawer, font=self.logFont, wrap="word")
        self.logBox.grid(row=2, column=0, sticky="nsew", padx=PAD, pady=(0, PAD))
        self.logBox.configure(state="disabled")
        self._configureLogTags(self.logBox)
        for sequence in ("<Control-Button-4>", "<Control-Button-5>", "<Control-MouseWheel>"):
            self.logBox._textbox.bind(sequence, self._onLogFontScroll)

        #the drawer floats over the activity list rather than taking grid space, so it can grow over
        #it; its bottom edge follows the log bar
        main.bind("<Configure>", lambda event: self._placeLogDrawer())

    def _gripPress(self, event):
        self._gripStart = (event.y_root, self._logDrawerHeight)

    def _gripDrag(self, event):
        startY, startHeight = self._gripStart
        self._setLogDrawerHeight(startHeight + (startY - event.y_root))

    def _placeLogDrawer(self):
        if not self.logDrawerOpen:
            return
        self.update_idletasks()
        bottom = self.logBar.winfo_y() - 4
        #CTk refuses width/height in place(); the size has to go through configure
        self.logDrawer.configure(height=self._logDrawerHeight)
        self.logDrawer.place(x=0, y=self.logDrawer._reverse_widget_scaling(bottom), anchor="sw",
                             relwidth=1)
        self.logDrawer.lift()

    def _setLogDrawerHeight(self, height):
        height = int(max(MIN_LOG_DRAWER_HEIGHT, height))
        try:
            top = self.activity.winfo_y() + ACTIVITY_PEEK * self.logDrawer._get_widget_scaling()
            limit = self.logDrawer._reverse_widget_scaling(self.logBar.winfo_y() - 4 - top)
            if self.logBar.winfo_y() > 50:  #before the first layout everything reports 0
                height = int(min(height, max(MIN_LOG_DRAWER_HEIGHT, limit)))
        except Exception:
            pass
        if height == self._logDrawerHeight:
            return
        self._logDrawerHeight = height
        self._placeLogDrawer()

    def _toggleLogDrawer(self):
        if self.logDrawerOpen:
            self.logDrawerOpen = False
            self.logDrawer.place_forget()
            self.logToggleButton.configure(text="Show log  ▾")
        else:
            self.logDrawerOpen = True
            self._placeLogDrawer()
            self.logToggleButton.configure(text="Hide log  ▴")

    def _openLogFolder(self):
        if not LogSetup.openLogFolder():
            messagebox.showinfo("Log folder", "Could not open a file manager.\n\n"
                                              f"The log is at:\n{LogSetup.LOG_FILE}")

    def _setLogLevel(self, value):
        #only the drawer is filtered; the log file stays at DEBUG so a bug report always has detail
        self.logHandler.setLevel(getattr(logging, value, logging.INFO))

    def _buildFetchPanel(self, main):
        self.fetchPanel = ctk.CTkFrame(main, border_width=2)
        self.fetchPanel.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.fetchPanel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.fetchPanel, text="Metadata Fetch", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=PAD, pady=(10, 0))
        self.fetchBookLabel = ctk.CTkLabel(self.fetchPanel, text="", anchor="w", wraplength=700,
                                           justify="left", font=ctk.CTkFont(size=13))
        self.fetchBookLabel.grid(row=1, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(2, 4))

        #why the last link was rejected, shown where the user is actually looking
        self.fetchReasonLabel = ctk.CTkLabel(self.fetchPanel, text="", anchor="w", wraplength=700,
                                             justify="left", font=ctk.CTkFont(size=13),
                                             text_color=ROW_COLORS["error"])
        self.fetchReasonLabel.grid(row=4, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(0, 10))
        hide(self.fetchReasonLabel)

        ctk.CTkButton(self.fetchPanel, text="Open Search", width=110, height=32, command=self._openSearch,
                      fg_color="transparent", border_width=1, text_color=OUTLINE_TEXT).grid(row=2, column=0, padx=(PAD, 8), pady=(4, 12))

        #paste-box mode widgets
        self.urlEntry = ctk.CTkEntry(self.fetchPanel, height=32,
                                     placeholder_text="Paste the Audible/Goodreads book page link here")
        self.urlEntry.grid(row=2, column=1, sticky="ew", pady=(4, 12))
        self.urlEntry.bind("<Return>", lambda event: self._submitUrl())

        #clipboard mode replaces the paste box with an instruction
        self.clipModeLabel = ctk.CTkLabel(self.fetchPanel, font=ctk.CTkFont(size=13), anchor="w",
                                          text="Copy the book page link in your browser - it will be picked up automatically.")
        self.clipModeLabel.grid(row=2, column=1, sticky="ew", pady=(4, 12))
        hide(self.clipModeLabel)

        buttonRow = ctk.CTkFrame(self.fetchPanel, fg_color="transparent")
        buttonRow.grid(row=2, column=2, padx=(8, PAD), pady=(4, 12))
        self.submitButton = ctk.CTkButton(buttonRow, text="Submit", width=80, height=32, command=self._submitUrl)
        self.submitButton.grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(buttonRow, text="Skip Book", width=80, height=32, command=self._skipFetch,
                      fg_color="transparent", border_width=1, text_color=OUTLINE_TEXT).grid(row=0, column=1)

        hide(self.fetchPanel)  #hidden until a fetch is waiting

    # ---------- fetch panel ----------

    def _clipboardModeActive(self):
        return self.fetchInputMenu.get() == FETCH_INPUT_MODES[0]

    def _updateFetchHint(self):
        if self._clipboardModeActive():
            self.fetchHint.configure(text="For each book, a browser search opens automatically.\nCopy the book page link in your browser to continue.")
        else:
            self.fetchHint.configure(text="For each book, a panel will appear above the activity list.\nOpen the search, then paste the book page link to continue.")

    def showFetchPanel(self, searchText, searchURL, fileName, reason=None, bookId=None):
        self._waitingBookId = bookId
        self.activity.setWaiting(bookId, True)
        self.currentSearchURL = searchURL
        self.fetchBookLabel.configure(text=f"File: {fileName}\nSearch: {searchText}")
        self.urlEntry.delete(0, "end")

        if reason:
            self.fetchReasonLabel.configure(text="⚠️  " + reason)
            self.fetchReasonLabel.grid()
        else:
            hide(self.fetchReasonLabel)

        if self._clipboardModeActive():
            hide(self.urlEntry)
            hide(self.submitButton)
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
            hide(self.clipModeLabel)
            self.urlEntry.grid()
            self.submitButton.grid()
            self.urlEntry.focus_set()
            self.statusLabel.configure(text="Waiting for a book link (paste it into the panel)...")

        self.fetchPanel.grid()

    def _hideFetchPanel(self):
        hide(self.fetchPanel)
        self.activity.setWaiting(self._waitingBookId, False)
        self._updateStatus()

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

    def _resetViews(self):
        self.logBox.configure(state="normal")
        self.logBox.delete("1.0", "end")
        self.logBox.configure(state="disabled")
        self.activity.reset()
        self._sawRunFinished = False

    def _appendLog(self, entry):
        #the drawer is the diagnostic view: every record the level allows, verbatim
        self.logBox.configure(state="normal")
        self.logBox.insert("end", entry.formatted + "\n", tags=(entry.level.lower(),))
        self.logBox.see("end")
        self.logBox.configure(state="disabled")

    # ---------- rendering run events ----------

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

    def _updateProgress(self):
        fraction = self.activity.overallFraction()
        if fraction is None:
            self._setIndeterminate()
        else:
            self._setProgress(fraction)

    def _updateStatus(self):
        #one line summarising the whole run, which has to cope with several books at once
        if self.fetchPanel.winfo_ismapped():
            return  #the panel owns the status line while it is waiting for the user
        active = self.activity.working()
        total = self.activity.totalBooks
        done = self.activity.finishedCount
        tally = f"  ·  {done}/{total} done" if total > 0 else ""

        if len(active) == 1:
            self.statusLabel.configure(text=active[0].statusText() + tally)
        elif active:
            self.statusLabel.configure(text=f"{len(active)} books in progress{tally}")
        elif total > 0:
            self.statusLabel.configure(text=f"{done}/{total} done")

    _EVENT_RENDERERS = {}  #built below the class body, mapping event type -> method name

    def _handleEvent(self, event):
        #The single place run events become widgets. Reporter.py is the list of what can arrive;
        #adding a field there cannot silently stop rendering the way a reworded log line used to.
        name = self._EVENT_RENDERERS.get(type(event))
        if name is None:
            return
        getattr(self, name)(event)

    def _onRunStarted(self, event):
        self.activity.runStarted(event)

    def _onPhaseStarted(self, event):
        self.activity.phaseStarted(event)
        self._updateProgress()
        self.statusLabel.configure(text=event.name)

    def _onPhaseFinished(self, event):
        self.activity.phaseFinished(event)

    def _onBookStarted(self, event):
        self.activity.bookStarted(event)
        self._updateProgress()
        self._updateStatus()

    def _onBookStep(self, event):
        self.activity.bookStep(event)
        self._updateStatus()

    def _onStepProgress(self, event):
        self.activity.stepProgress(event)
        self._updateProgress()
        self._updateStatus()

    def _onBookFinished(self, event):
        self.activity.bookFinished(event)
        self._updateProgress()
        self._updateStatus()

    def _onFetchFailed(self, event):
        self.activity.fetchFailed(event)

    def _onDryRunPlanned(self, event):
        self.activity.dryRunPlanned(event.plan)

    def _onRunFinished(self, event):
        self._sawRunFinished = True
        self.activity.runFinished(event)

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
            hide(self.fetchPanel)
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
            #no logLevel: that is the console's verbosity, and the GUI has no console. The drawer's
            #level is a view preference kept in gui_state.json, so fiddling with it here cannot
            #quietly change how a later CLI run behaves.
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
        #raise the banner before anything starts, so it is up for the whole run rather than arriving
        #with the plan event
        if self._dryRunActive:
            self.dryRunBanner.grid()
        else:
            hide(self.dryRunBanner)
        self._resetViews()
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


#one entry per event in Reporter.py; a missing entry here is why "Batch completed" once vanished
App._EVENT_RENDERERS = {
    Reporter.RunStarted:    "_onRunStarted",
    Reporter.PhaseStarted:  "_onPhaseStarted",
    Reporter.PhaseFinished: "_onPhaseFinished",
    Reporter.BookStarted:   "_onBookStarted",
    Reporter.BookStep:      "_onBookStep",
    Reporter.StepProgress:  "_onStepProgress",
    Reporter.BookFinished:  "_onBookFinished",
    Reporter.FetchFailed:   "_onFetchFailed",
    Reporter.DryRunPlanned: "_onDryRunPlanned",
    Reporter.RunFinished:   "_onRunFinished",
}


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
