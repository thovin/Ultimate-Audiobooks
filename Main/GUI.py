"""Ultimate Audiobooks GUI. Run with: python GUI.py (no arguments needed)."""
import json
import logging
import queue
import threading
from argparse import Namespace
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import Main
import Settings
import Processing
import BookStatus

log = logging.getLogger(__name__)

PAD = 10
FETCH_OPTIONS = ["Off", "Audible", "Goodreads", "Both"]
CREATE_OPTIONS = ["Off", "OPF"]  #INFOTEXT not yet implemented
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MODES = ["Single level", "Recurse fetch", "Recurse combine"]  #Recurse preserve not yet implemented


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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ultimate Audiobooks")
        self.geometry("1150x700")
        self.minsize(950, 600)

        self.workerThread = None
        self.logQueue = queue.Queue()
        self._setupLogging()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._buildSidebar()
        self._buildMainArea()

        self.after(100, self._pollLogs)

    def _setupLogging(self):
        handler = QueueHandler(self.logQueue)
        handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    # ---------- layout ----------

    def _buildSidebar(self):
        sidebar = ctk.CTkFrame(self, width=400, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Ultimate Audiobooks", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w")
        self.appearanceMenu = ctk.CTkOptionMenu(header, values=["Dark", "Light", "System"], width=100,
                                                command=ctk.set_appearance_mode)
        self.appearanceMenu.grid(row=0, column=1, sticky="e")

        form = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        form.grid(row=1, column=0, sticky="nsew", padx=(PAD // 2, 0), pady=PAD)
        form.grid_columnconfigure(0, weight=1)
        self._buildForm(form)

        buttons = ctk.CTkFrame(sidebar, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0, PAD))
        buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Save Settings", command=self._saveSettings,
                      fg_color="transparent", border_width=1).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(buttons, text="Load Settings", command=self._loadSettings,
                      fg_color="transparent", border_width=1).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.startButton = ctk.CTkButton(buttons, text="Start Processing", height=40,
                                         font=ctk.CTkFont(size=15, weight="bold"), command=self._startRun)
        self.startButton.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _sectionLabel(self, parent, row, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=("gray25", "gray75")).grid(row=row, column=0, sticky="w", padx=PAD, pady=(PAD, 2))

    def _buildForm(self, form):
        row = 0

        self._sectionLabel(form, row, "FOLDERS"); row += 1

        inputRow = ctk.CTkFrame(form, fg_color="transparent")
        inputRow.grid(row=row, column=0, sticky="ew", padx=PAD); row += 1
        inputRow.grid_columnconfigure(0, weight=1)
        self.inputEntry = ctk.CTkEntry(inputRow, placeholder_text="Input folder (required)")
        self.inputEntry.grid(row=0, column=0, sticky="ew", pady=2)
        ctk.CTkButton(inputRow, text="Browse", width=70,
                      command=lambda: self._browseInto(self.inputEntry)).grid(row=0, column=1, padx=(6, 0))

        outputRow = ctk.CTkFrame(form, fg_color="transparent")
        outputRow.grid(row=row, column=0, sticky="ew", padx=PAD); row += 1
        outputRow.grid_columnconfigure(0, weight=1)
        self.outputEntry = ctk.CTkEntry(outputRow, placeholder_text="Output folder (optional)")
        self.outputEntry.grid(row=0, column=0, sticky="ew", pady=2)
        ctk.CTkButton(outputRow, text="Browse", width=70,
                      command=lambda: self._browseInto(self.outputEntry)).grid(row=0, column=1, padx=(6, 0))

        self.moveSwitch = ctk.CTkSwitch(form, text="Move files (default: copy)")
        self.moveSwitch.grid(row=row, column=0, sticky="w", padx=PAD, pady=4); row += 1

        self._sectionLabel(form, row, "PROCESSING MODE"); row += 1
        self.modeSelector = ctk.CTkSegmentedButton(form, values=MODES)
        self.modeSelector.set(MODES[0])
        self.modeSelector.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1

        self._sectionLabel(form, row, "METADATA"); row += 1

        fetchRow = ctk.CTkFrame(form, fg_color="transparent")
        fetchRow.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1
        fetchRow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(fetchRow, text="Fetch from web:").grid(row=0, column=0, sticky="w")
        self.fetchMenu = ctk.CTkOptionMenu(fetchRow, values=FETCH_OPTIONS, width=130)
        self.fetchMenu.grid(row=0, column=1, sticky="e")

        self.fetchHint = ctk.CTkLabel(form, text="Fetch uses your clipboard: when the browser search opens,\ncopy the correct book page link (or copy the word 'skip').",
                                      font=ctk.CTkFont(size=11), text_color="gray55", justify="left")
        self.fetchHint.grid(row=row, column=0, sticky="w", padx=PAD); row += 1

        self.cleanSwitch = ctk.CTkSwitch(form, text="Clean file tags with fetched metadata")
        self.cleanSwitch.grid(row=row, column=0, sticky="w", padx=PAD, pady=4); row += 1

        createRow = ctk.CTkFrame(form, fg_color="transparent")
        createRow.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1
        createRow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(createRow, text="Sidecar file:").grid(row=0, column=0, sticky="w")
        self.createMenu = ctk.CTkOptionMenu(createRow, values=CREATE_OPTIONS, width=130)
        self.createMenu.grid(row=0, column=1, sticky="e")

        self._sectionLabel(form, row, "CONVERSION"); row += 1
        self.convertSwitch = ctk.CTkSwitch(form, text="Convert to .m4b (requires ffmpeg)")
        self.convertSwitch.grid(row=row, column=0, sticky="w", padx=PAD, pady=4); row += 1

        workersRow = ctk.CTkFrame(form, fg_color="transparent")
        workersRow.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1
        workersRow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(workersRow, text="Workers:").grid(row=0, column=0, sticky="w")
        self.workersEntry = ctk.CTkEntry(workersRow, width=130, placeholder_text="Auto")
        self.workersEntry.grid(row=0, column=1, sticky="e")

        self._sectionLabel(form, row, "EXECUTION"); row += 1

        batchRow = ctk.CTkFrame(form, fg_color="transparent")
        batchRow.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1
        batchRow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(batchRow, text="Batch size:").grid(row=0, column=0, sticky="w")
        self.batchEntry = ctk.CTkEntry(batchRow, width=130)
        self.batchEntry.insert(0, "10")
        self.batchEntry.grid(row=0, column=1, sticky="e")

        levelRow = ctk.CTkFrame(form, fg_color="transparent")
        levelRow.grid(row=row, column=0, sticky="ew", padx=PAD, pady=2); row += 1
        levelRow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(levelRow, text="Log level:").grid(row=0, column=0, sticky="w")
        self.logLevelMenu = ctk.CTkOptionMenu(levelRow, values=LOG_LEVELS, width=130)
        self.logLevelMenu.set("INFO")
        self.logLevelMenu.grid(row=0, column=1, sticky="e")

    def _buildMainArea(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=PAD, pady=PAD)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(main, text="Activity Log", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=("gray25", "gray75")).grid(row=0, column=0, sticky="w", pady=(0, 2))

        self.logBox = ctk.CTkTextbox(main, font=ctk.CTkFont(family="monospace", size=12), wrap="word")
        self.logBox.grid(row=1, column=0, sticky="nsew")
        self.logBox.configure(state="disabled")

        statusRow = ctk.CTkFrame(main, fg_color="transparent")
        statusRow.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        statusRow.grid_columnconfigure(0, weight=1)
        self.statusLabel = ctk.CTkLabel(statusRow, text="Ready", anchor="w")
        self.statusLabel.grid(row=0, column=0, sticky="w")
        self.progressBar = ctk.CTkProgressBar(statusRow, width=200, mode="indeterminate")
        self.progressBar.grid(row=0, column=1, sticky="e")
        self.progressBar.set(0)

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
    App().mainloop()
