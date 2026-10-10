import json
import Settings
import Reporter
import LogSetup
import Util
import Processing
import FileMerger
import BookStatus
import logging as log
from pathlib import Path
import sys

'''
DEBUG
INFO
WARNING
ERROR
CRITICAL
'''
settings = None

# Hold until keypress at end so user can see logs when running interactively
def _wait_for_keypress(prompt: str = "Press any key to exit...") -> None:
    try:
        # Prefer single key without Enter where possible
        import sys as _sys
        if not _sys.stdin.isatty():
            # Non-interactive context; do not block
            return

        try:
            # Windows
            import msvcrt  # type: ignore
            print(prompt)
            msvcrt.getch()
            return
        except Exception:
            pass

        try:
            # Unix-like
            import termios  # type: ignore
            import tty  # type: ignore
            import sys as _sys2
            print(prompt)
            fd = _sys2.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                _sys2.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return
        except Exception:
            pass

        # Fallback to Enter
        input(prompt.replace("any key", "Enter"))
    except Exception:
        # Last-resort: don't block if anything unexpected happens
        return
def applySavedSettings(args, parser):
    #Saved values fill in for any option not explicitly given on the command line.
    try:
        with open(Settings.SETTINGS_FILE, 'r') as inFile:
            saved = json.load(inFile)
    except FileNotFoundError:
        log.warning("No saved settings found (settings.json). Skipping load.")
        return

    specified = set()
    for token in sys.argv[1:]:
        option = token.split('=', 1)[0]
        action = parser._option_string_actions.get(option)
        if action:
            specified.add(action.dest)

    for key, value in saved.items():
        if key in ('save', 'load', 'default', 'dryRun') or key in specified or not hasattr(args, key):
            continue
        setattr(args, key, value)

    log.info("Loaded saved settings from settings.json")


#options worth recording at the top of a run; the bookkeeping flags are left out
_SUMMARY_KEYS = ("input", "output", "move", "dryRun", "fetch", "clean", "create", "convert",
                 "batch", "workers", "recurseFetch", "recurseCombine", "recursePreserve")


def settingsSummary(s):
    return {key: getattr(s, key) for key in _SUMMARY_KEYS if hasattr(s, key)}


def main(args):
    #Yes, I know this approach isn't super elegant. Feel free to recommend an alternative that isn't more of a pain in the ass like a config file.
    global settings
    settings = Settings.Settings(args)
    Settings.setSettings(settings)
    Util.loadSettings()
    Processing.loadSettings()
    FileMerger.loadSettings()
    BookStatus.loadSettings()

    Reporter.runStarted(Settings.modeName(settings), -1, settingsSummary(settings))

    if not settings.dryRun:
        log.debug("Creating output directory if not exists: " + settings.output)
        Path(settings.output).mkdir(parents = True, exist_ok = True)
    processBooks()


def processBooks():
    global settings

    #recursive modes are enforced as mutually exclusive by argparse, and validated in Settings
    if settings.recurseFetch:
        Processing.recursivelyFetchBatch()

    elif settings.recurseCombine:
        Processing.recursivelyCombineBatch()

    elif settings.recursePreserve:
        Processing.recursivelyPreserveBatch()

    else:
        Processing.singleLevelBatch()

    # Final summary (in case any were missed or for overall view)
    BookStatus.reportSummary(settings.dryRun)


if __name__ == "__main__":
    # Parse arguments first to get log level
    parser = Settings.buildParser()
    args = parser.parse_args()

    # Configure logging based on args: the chosen level on the console, always DEBUG in the log file
    numeric_level = getattr(log, args.logLevel, log.INFO)
    LogSetup.setupLogging(consoleLevel=numeric_level)

    log.debug("Arguments parsed successfully")

    #the console front end renders every run event as terminal output
    Reporter.setReporter(Reporter.ConsoleReporter())

    if args.default:
        try:
            Settings.SETTINGS_FILE.unlink()
            log.info("Saved settings reset to defaults (settings.json deleted)")
        except FileNotFoundError:
            log.info("No saved settings to reset")

    if args.load:
        applySavedSettings(args, parser)

    final_message = ""
    exit_code = 0
    unexpected_error = False
    try:
        main(args)
        final_message = "Processing complete."
    except Settings.UserAborted as ua:
        log.info(str(ua))
        final_message = "Exited."
    except Settings.ConfigError as ce:
        log.critical(str(ce))
        final_message = "Exited."
        exit_code = 1
    except SystemExit as se:
        # Allow graceful pause on explicit exits
        final_message = "Exited."
        exit_code = se.code if isinstance(se.code, int) else 0
    except Exception as e:
        log.exception("Unhandled exception during execution")
        final_message = "An unexpected error occurred."
        unexpected_error = True
        exit_code = 1
    finally:
        # Present final message as info only on non-error paths
        if final_message and not unexpected_error:
            log.info(final_message)
        # Only pause for interactive terminals
        try:
            if sys.stdin.isatty():
                _wait_for_keypress("Press any key to close...")
        except Exception:
            # As a fallback, attempt a simple input-based pause
            try:
                input("Press Enter to close...")
            except Exception:
                pass
        # Preserve exit semantics after pause
        if exit_code:
            sys.exit(exit_code)
