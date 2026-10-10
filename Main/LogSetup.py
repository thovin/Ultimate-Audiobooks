"""Logging configuration for both front ends.

Named LogSetup rather than Logging on purpose: a module called Logging.py would shadow the stdlib
`logging` on a case-insensitive filesystem.

The shape here is deliberate. The root logger runs at DEBUG and the *handlers* carry the levels, so
the log file always captures full detail no matter what the user has the console or the GUI's log
drawer set to. That matters because logging is diagnostics only - the program talks to the user
through Reporter events - so the log is read after something has already gone wrong, when turning
the verbosity up and reproducing is not an option.
"""
import logging
import logging.handlers
import os
import platform
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

#beside settings.json and gui_state.json, so everything this tool writes about itself is in one place
LOG_DIR = Path(__file__).resolve().parent / 'logs'
LOG_FILE = LOG_DIR / 'ultimate-audiobooks.log'

MAX_BYTES = 2_000_000
BACKUP_COUNT = 5

#the file gets more than the console does: a bare message is fine when you are watching a run, but
#useless when reading back a log a week later
FILE_FORMAT = "%(asctime)s %(levelname)-8s %(processName)-14s %(name)s:%(lineno)d  %(message)s"
CONSOLE_FORMAT = "[%(asctime)s][%(levelname)s] %(message)s"
CONSOLE_DATEFMT = '%H:%M:%S'

_fileHandler = None


def fileHandler():
    """The shared rotating file handler, created on first use. None if the log file isn't writable."""
    global _fileHandler
    if _fileHandler is not None:
        return _fileHandler

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
    except OSError as e:
        #a read-only install directory must not stop the program running
        print(f"Could not open log file {LOG_FILE}: {e}", file=sys.stderr)
        return None

    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(FILE_FORMAT))
    _fileHandler = handler
    return _fileHandler


def setupLogging(extraHandler=None, consoleLevel=None):
    """Install the log file, plus either a console handler or the GUI's queue handler.

    Idempotent: the GUI calls this once per process and must not stack a second file handler across
    repeated runs. Pass consoleLevel to log to stderr (the CLI), or extraHandler for the GUI."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  #handlers filter; the file wants everything

    handler = fileHandler()
    if handler is not None and handler not in root.handlers:
        root.addHandler(handler)

    if consoleLevel is not None:
        console = logging.StreamHandler()
        console.setLevel(consoleLevel)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATEFMT))
        root.addHandler(console)

    if extraHandler is not None and extraHandler not in root.handlers:
        root.addHandler(extraHandler)


def setupWorkerLogging(queue):
    """Point a conversion worker's logging at the parent over the event queue.

    Pool children start from a fresh interpreter under the forkserver start method, so they inherit
    no logging configuration and anything they log - including the ffmpeg warnings runFfmpeg
    collects - is discarded. The stdlib QueueHandler prepares records to be picklable, so they can
    ride the same queue the events already use; Processing._drainEvents hands them back to logging in
    the parent."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(logging.handlers.QueueHandler(queue))


def openLogFolder():
    """Show the log folder in the system file manager. Returns False if it couldn't be opened."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    target = str(LOG_DIR)
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(target)  #type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(['open', target], start_new_session=True)
        else:
            subprocess.Popen(['xdg-open', target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        return True
    except Exception:
        log.debug("Could not open the log folder", exc_info=True)
        return False
