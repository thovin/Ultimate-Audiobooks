import logging
from Settings import getSettings
from pathlib import Path
import mutagen
import mutagen.mp3
from Util import (Metadata, Conversion, fetchMetadata, cleanMetadata, convertToM4B,
                  getAudioFiles, getUniquePath, calculateWorkerCount, createOpf,
                  canReadTags, canWriteTags, readTags, mergeMetadata, claimedPaths, ALWAYS_TRANSCODE_TYPES)
from FileMerger import combineAndFindChapters, pendingMerges, runMergeJob, failMerge, finishMerge
from BookStatus import skipBook, failBook, getOriginalPath
import Naming
import Reporter
import LogSetup
import multiprocessing
import queue
import shutil
from concurrent.futures import ProcessPoolExecutor, wait
import math



log = logging.getLogger(__name__)
settings = None
conversions = []


def loadSettings():
    global settings
    settings = getSettings()
    conversions.clear()  #a fresh run must not inherit the previous run's queue (GUI reuses the process)
    claimedPaths.clear()

def processConversion(c, settings, events=None): #This is run through ProcessPoolExecutor, which limits access to globals
    #Workers start from a fresh interpreter under the forkserver start method, so they inherit no
    #reporter. Install one that ships events back to the parent over the shared queue.
    if events is not None:
        Reporter.setReporter(Reporter.QueueReporter(events))
        LogSetup.setupWorkerLogging(events)  #otherwise this child's diagnostics go nowhere

    #this child handles exactly one book, so naming it once attributes every event it emits - which
    #is what lets the GUI keep several conversions on screen at once without mixing them up
    Reporter.setCurrentBook(Path(c.file))

    file = c.file
    type = c.type
    md = c.md

    file = convertToM4B(file, type, md, settings, c.duration)
    if file is None:
        return None  #conversion failed; book already marked as failed

    track = mutagen.File(file, easy=True)

    if settings.fetch and settings.clean:
        #the converted file is a new file in both move and copy modes, so always safe to clean
        cleanMetadata(track, md)

    return str(file)  #where the book ended up, so the parent can report it


def _drainEvents(events):
    #Replay worker events into this process's reporter, so conversions narrate themselves in
    #whichever front end is running. The same queue carries the workers' log records (see
    #LogSetup.setupWorkerLogging), which belong to logging rather than to the reporter.
    while True:
        try:
            item = events.get_nowait()
        except queue.Empty:
            return
        except Exception:
            return  #manager queue torn down

        if isinstance(item, logging.LogRecord):
            logging.getLogger(item.name).handle(item)
        else:
            Reporter.replay(item)


def processMerge(job, settings, events=None):  #run through ProcessPoolExecutor, like processConversion
    if events is not None:
        Reporter.setReporter(Reporter.QueueReporter(events))
        LogSetup.setupWorkerLogging(events)

    Reporter.setCurrentBook(Path(job.folderPath))
    return runMergeJob(job)


def _workerCount():
    numWorkers = settings.workers
    if numWorkers == -1:
        numWorkers = math.floor(calculateWorkerCount())

        if numWorkers > 0:
            log.debug(f"Number of workers not specified, set to {numWorkers} based on system CPU count and available memory")
        else:
            numWorkers = 1
            log.debug("Number of workers not specified and unable to retrieve relevant system information. Defaulting to 1 worker.")
    return numWorkers


def _runInPool(worker, jobs, bookOf, onResult, onError):
    """Run worker(job, settings, events) for every job in a process pool, replaying the workers' events
    into this process's reporter. onResult/onError run here in the parent, with the current book set."""
    with multiprocessing.Manager() as manager:
        events = manager.Queue()

        with ProcessPoolExecutor(max_workers=_workerCount()) as controller:
            futures = {controller.submit(worker, j, settings, events): j for j in jobs}

            pending = set(futures)
            while pending:
                #short timeout so worker progress reaches the front end while jobs run
                done, pending = wait(pending, timeout=0.2)
                _drainEvents(events)

                for future in done:
                    job = futures[future]
                    #name the book before reporting: this loop runs in the parent, where the current
                    #book is still whichever one the serial loop finished with
                    Reporter.setCurrentBook(bookOf(job))
                    try:
                        result = future.result()
                    except Exception as e:
                        onError(job, e)
                    else:
                        onResult(job, result)

            _drainEvents(events)


def processConversions():
    Reporter.phaseStarted(f"Converting {len(conversions)} file{'s' if len(conversions) != 1 else ''}",
                          len(conversions))

    def onResult(conversion, finalPath):
        if finalPath is None:
            return  #the worker already reported the failure; don't overwrite it with a success
        Reporter.bookFinished(Reporter.STATUS_OK, Path(conversion.file).name,
                              placement=_placement(finalPath, conversion.md))

    def onError(conversion, e):
        log.error("Error processing conversion: " + str(e))
        failBook(conversion.file, "Conversion raised an error")

    _runInPool(processConversion, list(conversions), lambda c: Path(c.file), onResult, onError)

    Reporter.phaseFinished("Conversions complete")
    conversions.clear()


def processMerges():
    #transcoding merges (FLAC chapters) were queued by FileMerger; each is a full AAC encode
    if not pendingMerges:
        return

    Reporter.phaseStarted(f"Merging {len(pendingMerges)} book{'s' if len(pendingMerges) != 1 else ''}",
                          len(pendingMerges))

    def onResult(job, ok):
        if ok:
            finishMerge(job)
            Reporter.bookFinished(Reporter.STATUS_OK, job.folderPath.name)
        else:
            failMerge(job)

    def onError(job, e):
        log.error("Error merging chapters: " + str(e))
        failMerge(job)

    _runInPool(processMerge, list(pendingMerges), lambda j: Path(j.folderPath), onResult, onError)

    Reporter.phaseFinished("Merges complete")
    pendingMerges.clear()

def _dryRunSteps(combine=False):
    #Short human phrases for the per-book pipeline implied by the current settings, mirroring
    #processFile's decision flow. Keep in sync with processFile. No disk access.
    steps = []
    if combine:            steps.append("combine chapters")
    if settings.fetch:     steps.append(f"fetch metadata ({settings.fetch})")
    if settings.create:    steps.append(f"create {settings.create} sidecar")
    if settings.convert:   steps.append("convert .m4b")
    if settings.rename:    steps.append("rename")
    if settings.clean:     steps.append("write tags")
    steps.append("move" if settings.move else "copy")
    return steps


def _destinationKnown(combine=False):
    #A destination depends on the file's name, its own tags and the template, all readable without
    #writing anything, so it can be worked out exactly. It can't be when it needs fetched metadata (a
    #dry run deliberately doesn't fetch), or the tags of a merged file that doesn't exist yet.
    if not Naming.usesMetadata(Naming.effectiveTemplate(settings)):
        return True
    return not settings.fetch and not combine


def _tagsOf(file):
    #the book's own tags for a dry run; a folder (combine) or unreadable file has none
    try:
        return readTags(mutagen.File(file, easy=True)) if Path(file).is_file() else Metadata()
    except Exception:
        return Metadata()


def _plannedDestination(file, suffix, source=None):
    #"-> path under the output folder" for the dry run, from the same _destination the real run uses
    #returns (text, placeholders that would be left out of the name)
    md = _tagsOf(file)
    missing = Naming.missingRequired(Naming.parseRequired(settings.require), md)
    if missing:
        return "→ would be skipped: not found: " + ", ".join(missing), ()
    path = _destination(file, md, suffix, source)
    return "→ " + path.relative_to(settings.output).as_posix(), tuple(md.renameMissing)


def _planBooks(files):
    #(label, detail) for each file, with the destination as the detail when it can be known
    known = _destinationKnown()
    books = []
    for f in files:
        detail, missing = _plannedDestination(f, ".m4b" if settings.convert else f.suffix.lower()) if known else (None, ())
        books.append(Reporter.PlannedBook(f.name, detail, missing))
    claimedPaths.clear()  #the preview reserved names to show collisions; none of that should outlive it
    return books


def _reportDryRunPlan(books, combine=False, emptyNote="no audio files found in the input folder"):
    #Describe the run rather than performing it. Every front end renders the same plan object.
    #books: list of (label, detail-or-None), detail e.g. "(2 chapters) → Lib/Book.mp3".
    example = Naming.preview(Naming.effectiveTemplate(settings), ".m4b" if settings.convert else ".mp3")
    if not _destinationKnown(combine):
        example += "  (sample book; real names come from each book's metadata)"
    Reporter.dryRunPlanned(Reporter.DryRunPlan(
        output=settings.output,
        verb="move" if settings.move else "copy",
        modeNote="originals removed from source" if settings.move else "originals left in place",
        layout=Naming.effectiveTemplate(settings),
        layoutExample=example,
        steps=_dryRunSteps(combine),
        books=list(books),
        combine=combine,
        emptyNote=emptyNote,
        required=", ".join(Naming.parseRequired(settings.require))))


def dryRunCombine(infolder):
    #Folder-level preview of recurse-combine without invoking the ffmpeg merge. Each
    #subfolder that holds audio files is treated as one book (as combineAndFindChapters does).
    books = []
    known = _destinationKnown(combine=True)
    for folder in sorted(p for p in infolder.rglob('*') if p.is_dir()):
        if len(books) >= settings.batch:
            break
        files = getAudioFiles(folder)
        if files:
            detail = f"({len(files)} chapter{'s' if len(files) != 1 else ''})"
            missing = ()
            if known:
                #several chapters merge into one file; same suffix rule as FileMerger.mergeBook
                first = files[0].suffix.lower()
                suffix = ".m4b" if settings.convert or (len(files) > 1 and first in ALWAYS_TRANSCODE_TYPES) else first
                text, missing = _plannedDestination(folder, suffix, source=folder.name)
                detail += " " + text
            books.append(Reporter.PlannedBook(folder.name, detail, missing))
    claimedPaths.clear()
    _reportDryRunPlan(books, combine=True,
                      emptyNote="no subfolders with audio files found to combine")


def _destination(file, md, suffix, source=None):
    #Where a book lands, unique among the files already there and the books already placed this run.
    #The one place the --rename template meets the file system, shared by the real run and the dry run
    #so a preview cannot drift from what happens. source overrides {filename} (default: derived from file).
    folders, stem, md.renameMissing = Naming.resolve(Naming.effectiveTemplate(settings), md, source or _sourceName(file))
    folder = Path(settings.output).joinpath(*folders)
    return getUniquePath(stem + suffix, folder, claim=True)


def _placement(finalPath, md):
    #what a finished book reports about where it went: its path under the output folder, and which
    #template placeholders had nothing to fill them
    try:
        relative = Path(finalPath).relative_to(settings.output).as_posix()
    except ValueError:
        relative = Path(finalPath).name
    return Reporter.Placement(relative, tuple(md.renameMissing))


def _sourceName(file):
    #What {filename} means for this book: its own name, or for a combined book the chapter folder
    #it was assembled from (the merged file in the temp folder has an assembled name nobody chose)
    original = getOriginalPath(file)
    return original.name if original.is_dir() else original.stem


def processFile(file, index=0, total=0):
    #the path is the book's identity for the rest of the run; file.name is only what gets displayed
    Reporter.bookStarted(index, total, file.name, bookId=file)
    type = Path(file).suffix.lower()

    try:
        track = mutagen.File(file, easy=True)
    except mutagen.mp3.HeaderNotFoundError:
        failBook(file, "Corrupt or unreadable audio file")
        return

    if track == None:
        failBook(file, "Unable to process file")
        return

    #what the file's own tags say; a fetch below overrides whatever it finds
    md = readTags(track)

    #read once here: the conversion worker needs it for progress and cannot reopen a moved file
    duration = float(getattr(track.info, 'length', -1) or -1)

    #say so up front when this file type rules out something the user asked for, instead of trying
    #it and reporting an error. Only the requests that will really be affected are mentioned.
    if settings.fetch:
        if not canReadTags(track):
            Reporter.bookNote(f"{type} files have no readable tags; searching by file name instead", file.name)
        #a converted book is tagged after it becomes an M4B, so only an unconverted file is affected
        if settings.clean and not settings.convert and not canWriteTags(track):
            Reporter.bookNote(f"Tags can't be written to {type} files; leaving them untagged", file.name)

    if settings.fetch:
        #existing OPF is ignored in single level batch
        fetched = fetchMetadata(file, track)

        if fetched is None:
            # Book was skipped or failed during metadata fetch
            return
        md = mergeMetadata(md, fetched)

    #--require: a book missing a required field is skipped rather than filed under a name that omits it.
    #Checked before the destination is claimed, so nothing is created or reserved for a skipped book.
    missing = Naming.missingRequired(Naming.parseRequired(settings.require), md)
    if missing:
        skipBook(file, "Not found: " + ", ".join(missing) + " (required)")
        return

    #The --rename template (or the default layout) decides where the book lands, with or without
    #fetched metadata. The final name is settled here, in the parent, so books that map to the same
    #name get distinct paths even while their conversions are still queued.
    newPath = _destination(file, md, ".m4b" if settings.convert else type)
    md.bookPath = str(newPath.parent)
    md.fileStem = newPath.stem

    log.debug(f"Making directory {md.bookPath} if not exists")
    Path(md.bookPath).mkdir(parents = True, exist_ok = True)

    if settings.fetch and settings.create:
        createOpf(md)

    if settings.convert:
        log.debug(f"Queueing {file.name} for conversion")
        conversions.append(Conversion(file, type, md, duration))
        return

    if settings.fetch and settings.clean and settings.move:
        #if copying, we will only clean the copied file
        cleanMetadata(track, md)

    if settings.move:
        Reporter.bookStep(Reporter.STEP_MOVE, file.name, md.bookPath)
        shutil.move(str(file), str(newPath))  #Path.rename fails when input and output are on different drives
    else:
        Reporter.bookStep(Reporter.STEP_COPY, file.name, md.bookPath)
        shutil.copy(file, newPath)

        if settings.fetch and settings.clean:
            cleanMetadata(mutagen.File(newPath, easy=True), md)

    Reporter.bookFinished(Reporter.STATUS_OK, file.name, placement=_placement(newPath, md))


def recursivelyCombineBatch():
    infolder = Path(settings.input)

    if settings.dryRun:
        dryRunCombine(infolder)
        return

    Reporter.phaseStarted("Combining chapter folders into books")
    outFolder = infolder.joinpath("Ultimate temp")

    if outFolder.is_dir():
        # outFolder.rmdir() #only works on empty dirs
        shutil.rmtree(outFolder)

    outFolder.mkdir()
    pendingMerges.clear()
    combineAndFindChapters(infolder, outFolder, 1, infolder)
    processMerges()

    Reporter.phaseFinished("Chapter files combined into the temp folder")
    singleLevelBatch(outFolder)

    log.debug("Removing temp folder")
    if not any(outFolder.iterdir()):
        outFolder.rmdir()
    else:
        log.error("Error: temp directory not empty. Unable to delete.")



def recursivelyPreserveBatch():
    Reporter.phaseStarted("Recurse preserve is not implemented yet")
    return


def _runBatch(files):
    for index, file in enumerate(files, 1):
        processFile(file, index, len(files))

    if len(conversions) > 0:
        processConversions()


def singleLevelBatch(infolder = None):
    if infolder == None:
        infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch)

    if settings.dryRun:
        _reportDryRunPlan(_planBooks(files))
        return

    Reporter.phaseStarted("Processing books", len(files))
    _runBatch(files)
    Reporter.phaseFinished("Batch completed. Enjoy your audiobooks!")


def recursivelyFetchBatch():    #Since the only difference is passing true to getAudioFiles, I could probably fold this into another batch
    infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch, True)

    if settings.dryRun:
        _reportDryRunPlan(_planBooks(files))
        return

    Reporter.phaseStarted("Processing complete books in all subfolders", len(files))
    _runBatch(files)
    Reporter.phaseFinished("Batch completed. Enjoy your audiobooks!")
