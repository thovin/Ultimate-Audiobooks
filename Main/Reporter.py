"""Structured run events, and the console renderer for them.

The core pipeline reports what it is doing through this module instead of printing. Each front end
installs its own reporter: Main installs ConsoleReporter, GUI installs GuiReporter. logging is still
used throughout for diagnostics (log.debug) and for genuine errors, but it is no longer how the
program talks to the user - so neither front end has to parse the other's output to find out what
happened.

Events are plain NamedTuples of simple values, which keeps them picklable: conversion workers run in
ProcessPoolExecutor children and report back through QueueReporter over a multiprocessing queue.
"""
import logging
import sys
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)


#per-book pipeline steps, in roughly the order processFile runs them
STEP_MERGE = "merge"
STEP_FETCH = "fetch"
STEP_SIDECAR = "sidecar"
STEP_CONVERT = "convert"
STEP_TAG = "tag"
STEP_MOVE = "move"
STEP_COPY = "copy"

#how a book ended
STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

#what each step is called when narrated to the user, and the glyph pretty renderers use
STEP_LABELS = {
    STEP_MERGE:   ("Combining chapters", "🧩"),
    STEP_FETCH:   ("Looking up metadata", "🔍"),
    STEP_SIDECAR: ("Creating info file", "📄"),
    STEP_CONVERT: ("Converting to M4B", "🔄"),
    STEP_TAG:     ("Writing tags", "🏷️"),
    STEP_MOVE:    ("Moving to library", "🚚"),
    STEP_COPY:    ("Copying to library", "📋"),
}


def stepLabel(step):
    return STEP_LABELS.get(step, (step.capitalize(), "•"))[0]


def stepGlyph(step):
    return STEP_LABELS.get(step, (step.capitalize(), "•"))[1]


# ---------- events ----------

class RunStarted(NamedTuple):
    mode: str                 #human name of the processing mode
    totalBooks: int           #-1 when not known up front
    settingsSummary: dict     #resolved settings, so GUI mode has a record of what ran


class PhaseStarted(NamedTuple):
    name: str
    total: int                #-1 when not known up front


class PhaseFinished(NamedTuple):
    name: str


class BookStarted(NamedTuple):
    index: int                #1-based position in the batch
    total: int
    label: str


class BookStep(NamedTuple):
    step: str                 #one of the STEP_* constants
    label: str                #the book this belongs to
    detail: Optional[str]


class StepProgress(NamedTuple):
    step: str
    label: str
    done: float               #same unit as total, usually seconds of audio
    total: float              #-1 when the total is unknown


class BookFinished(NamedTuple):
    status: str               #one of the STATUS_* constants
    label: str
    reason: Optional[str]


class FetchFailed(NamedTuple):
    #why the link the user supplied was rejected, so the front end can re-prompt with the reason
    reason: str
    label: str


class DryRunPlan(NamedTuple):
    #What a run would do, described rather than performed. Every front end renders this same
    #structure, so the terminal plan and the GUI plan can never drift apart.
    output: str
    verb: str          #"move" or "copy"
    modeNote: str      #what happens to the originals
    perBookDest: bool  #True when fetch decides the per-book Author/Title subfolder
    steps: list        #per-book pipeline phrases, in order
    books: list        #(label, detail-or-None) pairs
    combine: bool      #chapter folders being assembled rather than files processed
    emptyNote: str     #why there is nothing to do, when books is empty


class DryRunPlanned(NamedTuple):
    plan: DryRunPlan


class RunFinished(NamedTuple):
    skips: list                #relative path strings
    fails: list                #relative path strings
    dryRun: bool


# ---------- reporter registry ----------

class Reporter:
    """Base reporter. Handles every event by ignoring it, so subclasses only override what they show."""

    def handle(self, event):
        pass

    def confirmSettings(self, values):
        #Interactive, not an event: return False to abort the run before anything is touched.
        return True


_reporter = None


def setReporter(reporter):
    global _reporter
    _reporter = reporter


def getReporter():
    return _reporter


def _emit(event):
    if _reporter is None:
        return
    try:
        _reporter.handle(event)
    except Exception:
        #a broken renderer must never take the run down with it
        log.debug("Reporter failed to handle %s", type(event).__name__, exc_info=True)


def replay(event):
    """Feed an already-built event to the installed reporter.

    Used to relay events that were produced in another process (see QueueReporter)."""
    _emit(event)


def confirmSettings(values):
    if _reporter is None:
        return True
    return _reporter.confirmSettings(values)


#terse emit helpers, so call sites stay as short as the log.info they replace
def runStarted(mode, totalBooks=-1, settingsSummary=None):
    _emit(RunStarted(mode, totalBooks, settingsSummary or {}))


def phaseStarted(name, total=-1):
    _emit(PhaseStarted(name, total))


def phaseFinished(name):
    _emit(PhaseFinished(name))


def bookStarted(index, total, label):
    _emit(BookStarted(index, total, label))


def bookStep(step, label, detail=None):
    _emit(BookStep(step, label, detail))


def stepProgress(step, label, done, total=-1):
    _emit(StepProgress(step, label, done, total))


def bookFinished(status, label, reason=None):
    _emit(BookFinished(status, label, reason))


def fetchFailed(reason, label=""):
    _emit(FetchFailed(reason, label))


def dryRunPlanned(plan):
    _emit(DryRunPlanned(plan))


def runFinished(skips, fails, dryRun=False):
    _emit(RunFinished(list(skips), list(fails), dryRun))


class QueueReporter(Reporter):
    """Forwards events to another process over a multiprocessing queue.

    Conversion workers start from a fresh interpreter under the forkserver start method, so they
    inherit neither the installed reporter nor any logging configuration. Each worker installs one of
    these; processConversions drains the queue in the parent and replays the events into the real
    reporter."""

    def __init__(self, queue):
        self.queue = queue

    def handle(self, event):
        try:
            self.queue.put(event)
        except Exception:
            pass  #the parent may have gone away; losing a progress tick is not worth failing a conversion


# ---------- console rendering ----------

def dryRunPlanText(plan):
    #Text form of the plan for the terminal: the shared pipeline printed once, then a numbered
    #per-book list.
    dest = plan.output + ("  (per-book Author/Title depends on fetch)" if plan.perBookDest else "")
    lines = ["[DRY RUN] Planned run — nothing will be written",
             f"  Output:    {dest}",
             f"  Mode:      {plan.verb} ({plan.modeNote})",
             f"  Each book: {' → '.join(plan.steps)}",
             ""]
    if not plan.books:
        lines.append(f"  Nothing to do — {plan.emptyNote}")
        return lines

    noun = "book" if len(plan.books) == 1 else "books"
    lines.append(f"  {len(plan.books)} {noun} to {'assemble' if plan.combine else 'process'}:")
    width = len(str(len(plan.books)))
    for number, (label, detail) in enumerate(plan.books, 1):
        lines.append(f"    {number:>{width}}. {label}" + (f"  {detail}" if detail else ""))
    return lines


class ConsoleReporter(Reporter):
    """Renders events as terminal output. Owns every piece of CLI formatting in the program."""

    def __init__(self):
        self._progressActive = False
        self._lastPercent = {}
        self._currentBook = None

    def handle(self, event):
        handler = self._HANDLERS.get(type(event))
        if handler:
            handler(self, event)

    # --- progress line ---

    def _interactive(self):
        try:
            return sys.stdout.isatty()
        except Exception:
            return False

    def _clearProgress(self):
        if self._progressActive:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self._progressActive = False

    def _qualify(self, label):
        #Steps belonging to the book we just announced need no label. Conversions run in parallel
        #after the per-book loop, so those do - without it the lines are unattributable.
        return "" if (not label or label == self._currentBook) else f" {label}"

    def _onStepProgress(self, event):
        if event.total <= 0:
            return
        percent = min(100, int(event.done / event.total * 100))

        if not self._interactive():
            #piped or redirected output: one line per 25% so logs stay readable
            key = (event.step, event.label)
            if percent // 25 > self._lastPercent.get(key, -1) // 25:
                self._lastPercent[key] = percent
                log.info(f"  {stepLabel(event.step)}{self._qualify(event.label)}: {percent}%")
            return

        filled = percent * 24 // 100
        bar = "█" * filled + "░" * (24 - filled)
        sys.stdout.write(f"\r\033[K  {stepLabel(event.step)}{self._qualify(event.label)} "
                         f"[{bar}] {percent:3d}%")
        sys.stdout.flush()
        self._progressActive = True

    # --- everything else ---

    def _onRunStarted(self, event):
        #The phase headlines that follow say the same thing more precisely, so this stays at debug
        #rather than opening every run with two near-identical lines. Richer front ends use the
        #mode and the settings summary as a run header.
        self._clearProgress()
        log.debug("Run started: %s %s", event.mode, event.settingsSummary)

    def _onPhaseStarted(self, event):
        self._clearProgress()
        self._currentBook = None  #a new phase means the per-book narration no longer applies
        log.info(event.name)

    def _onPhaseFinished(self, event):
        self._clearProgress()
        self._currentBook = None
        log.info(event.name)

    def _onBookStarted(self, event):
        self._clearProgress()
        self._currentBook = event.label
        if event.total > 0:
            log.info(f"[{event.index}/{event.total}] {event.label}")
        else:
            log.info(f"Processing {event.label}")

    def _onBookStep(self, event):
        self._clearProgress()
        detail = f" - {event.detail}" if event.detail else ""
        log.info(f"  {stepLabel(event.step)}{self._qualify(event.label)}{detail}")

    def _onBookFinished(self, event):
        self._clearProgress()
        reason = f" - {event.reason}" if event.reason else ""
        if event.status == STATUS_FAILED:
            log.error(f"  Failed: {event.label}{reason}")
        elif event.status == STATUS_SKIPPED:
            log.warning(f"  Skipped: {event.label}{reason}")

    def _onFetchFailed(self, event):
        self._clearProgress()
        log.error(event.reason)

    def _onDryRunPlanned(self, event):
        self._clearProgress()
        log.info("\n".join(dryRunPlanText(event.plan)))

    def _onRunFinished(self, event):
        self._clearProgress()
        if event.dryRun:
            log.info("Dry run finished. Nothing was written.")
            return

        if not event.skips and not event.fails:
            log.info("No books were skipped or failed.")
            return

        log.info("=" * 60)
        log.info("SKIP/FAIL SUMMARY")
        log.info("=" * 60)

        if event.skips:
            log.info(f"\nSkipped books ({len(event.skips)}):")
            for item in event.skips:
                log.info(f"  - {item}")

        if event.fails:
            log.info(f"\nFailed books ({len(event.fails)}):")
            for item in event.fails:
                log.info(f"  - {item}")

        log.info("=" * 60)

    _HANDLERS = {
        RunStarted:    _onRunStarted,
        PhaseStarted:  _onPhaseStarted,
        PhaseFinished: _onPhaseFinished,
        BookStarted:   _onBookStarted,
        BookStep:      _onBookStep,
        StepProgress:  _onStepProgress,
        BookFinished:  _onBookFinished,
        FetchFailed:   _onFetchFailed,
        DryRunPlanned: _onDryRunPlanned,
        RunFinished:   _onRunFinished,
    }

    # --- interactive ---

    def confirmSettings(self, values):
        for key, value in values.items():
            print(f"{key}: {value}")

        while True:
            userInput = input("Continue program execution? (y/n): ").lower()
            if userInput == 'y':
                return True
            elif userInput == 'n':
                print("Confirmed, exiting...")
                return False
