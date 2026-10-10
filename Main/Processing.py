import logging
from Settings import getSettings
from pathlib import Path
import mutagen
import mutagen.mp3
from Util import (Metadata, Conversion, fetchMetadata, cleanMetadata, convertToM4B,
                  getAudioFiles, getUniquePath, calculateWorkerCount, createOpf)
from FileMerger import combineAndFindChapters
from BookStatus import skipBook, failBook
import Reporter
import LogSetup
import multiprocessing
import queue
import re
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
        return  #conversion failed; book already marked as failed

    track = mutagen.File(file, easy=True)

    if settings.fetch and settings.clean:
        #the converted file is a new file in both move and copy modes, so always safe to clean
        cleanMetadata(track, md)

    if settings.rename:
        #TODO rename
        #again, only apply to copy
        pass



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


def processConversions():
    Reporter.phaseStarted(f"Converting {len(conversions)} file{'s' if len(conversions) != 1 else ''}",
                          len(conversions))

    numWorkers = settings.workers
    if numWorkers == -1:
        numWorkers = math.floor(calculateWorkerCount())

        if numWorkers > 0:
            log.debug(f"Number of workers not specified, set to {numWorkers} based on system CPU count and available memory")
        else:
            numWorkers = 1
            log.debug("Number of workers not specified and unable to retrieve relevant system information. Defaulting to 1 worker.")

    with multiprocessing.Manager() as manager:
        events = manager.Queue()

        with ProcessPoolExecutor(max_workers=numWorkers) as controller:
            futures = {controller.submit(processConversion, c, settings, events): c
                       for c in conversions}

            pending = set(futures)
            while pending:
                #short timeout so worker progress reaches the front end while conversions run
                done, pending = wait(pending, timeout=0.2)
                _drainEvents(events)

                for future in done:
                    conversion = futures[future]
                    #name the book before reporting: this loop runs in the parent, where the current
                    #book is still whichever one the serial loop finished with
                    Reporter.setCurrentBook(Path(conversion.file))
                    try:
                        future.result()
                        Reporter.bookFinished(Reporter.STATUS_OK, Path(conversion.file).name)
                    except Exception as e:
                        log.error("Error processing conversion: " + str(e))
                        failBook(conversion.file, "Conversion raised an error")

            _drainEvents(events)

    Reporter.phaseFinished("Conversions complete")
    conversions.clear()

def _dryRunSteps(combine=False):
    #Short human phrases for the per-book pipeline implied by the current settings, mirroring
    #processFile's decision flow. Keep in sync with processFile. No disk access.
    steps = []
    if combine:            steps.append("combine chapters")
    if settings.fetch:     steps.append(f"fetch metadata ({settings.fetch})")
    if settings.create:    steps.append(f"create {settings.create} sidecar")
    if settings.convert:   steps.append("convert .m4b")
    if settings.clean:     steps.append("write tags")
    steps.append("move" if settings.move else "copy")
    return steps


def _reportDryRunPlan(books, combine=False, emptyNote="no audio files found in the input folder"):
    #Describe the run rather than performing it. Every front end renders the same plan object.
    #books: list of (label, detail-or-None), detail e.g. "(2 chapters)".
    Reporter.dryRunPlanned(Reporter.DryRunPlan(
        output=settings.output,
        verb="move" if settings.move else "copy",
        modeNote="originals removed from source" if settings.move else "originals left in place",
        perBookDest=bool(settings.fetch),
        steps=_dryRunSteps(combine),
        books=list(books),
        combine=combine,
        emptyNote=emptyNote))


def dryRunCombine(infolder):
    #Folder-level preview of recurse-combine without invoking the ffmpeg merge. Each
    #subfolder that holds audio files is treated as one book (as combineAndFindChapters does).
    books = []
    for folder in sorted(p for p in infolder.rglob('*') if p.is_dir()):
        if len(books) >= settings.batch:
            break
        files = getAudioFiles(folder)
        if files:
            books.append((folder.name, f"({len(files)} chapter{'s' if len(files) != 1 else ''})"))
    _reportDryRunPlan(books, combine=True,
                      emptyNote="no subfolders with audio files found to combine")


def processFile(file, index=0, total=0):
    #the path is the book's identity for the rest of the run; file.name is only what gets displayed
    Reporter.bookStarted(index, total, file.name, bookId=file)
    type = Path(file).suffix.lower()
    md = Metadata()
    md.bookPath = settings.output
    newPath = ""

    try:
        track = mutagen.File(file, easy=True)
    except mutagen.mp3.HeaderNotFoundError:
        failBook(file, "Corrupt or unreadable audio file")
        return

    if track == None:
        failBook(file, "Unable to process file")
        return

    #read once here: the conversion worker needs it for progress and cannot reopen a moved file
    duration = float(getattr(track.info, 'length', -1) or -1)

    if settings.fetch:
        #existing OPF is ignored in single level batch
        md = fetchMetadata(file, track)

        if md is None:
            # Book was skipped or failed during metadata fetch
            return

        #TODO (rename) set md.bookPath according to rename
        cleanAuthor = re.sub(r'[<>"|?’:,*\']', '', md.author)
        cleanTitle = re.sub(r'[<>"|?’:,*\']', '', md.title)
        md.bookPath = settings.output + f"/{cleanAuthor}/{cleanTitle}"


        log.debug(f"Making directory {md.bookPath} if not exists")
        Path(md.bookPath).mkdir(parents = True, exist_ok = True)

        if settings.create:
            createOpf(md)

        if settings.convert:
            log.debug(f"Queueing {file.name} for conversion")
            conversions.append(Conversion(file, type, md, duration))
            return
        else:
            newPath = getUniquePath(Path(cleanTitle).with_suffix(type).name, md.bookPath)

        if settings.clean and settings.move:
            #if copying, we will only clean the copied file
            cleanMetadata(track, md)

    if settings.convert:
        conversions.append(Conversion(file, type, md, duration))
        return

    if settings.rename:
        #TODO rename
        #again, only apply to copy
        pass

    if newPath == "":
        newPath = getUniquePath(file.name, md.bookPath)
    if settings.move:
        Reporter.bookStep(Reporter.STEP_MOVE, file.name, md.bookPath)
        # TODO (rename) temporarily use title while working on rename
        shutil.move(str(file), str(newPath))  #Path.rename fails when input and output are on different drives
    else:
        Reporter.bookStep(Reporter.STEP_COPY, file.name, md.bookPath)
        shutil.copy(file, newPath)

        if settings.fetch and settings.clean:
            cleanMetadata(mutagen.File(newPath, easy=True), md)

    Reporter.bookFinished(Reporter.STATUS_OK, file.name)


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
    combineAndFindChapters(infolder, outFolder, 1, infolder)

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
        _reportDryRunPlan([(f.name, None) for f in files])
        return

    Reporter.phaseStarted("Processing books", len(files))
    _runBatch(files)
    Reporter.phaseFinished("Batch completed. Enjoy your audiobooks!")


def recursivelyFetchBatch():    #Since the only difference is passing true to getAudioFiles, I could probably fold this into another batch
    infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch, True)

    if settings.dryRun:
        _reportDryRunPlan([(f.name, None) for f in files])
        return

    Reporter.phaseStarted("Processing complete books in all subfolders", len(files))
    _runBatch(files)
    Reporter.phaseFinished("Batch completed. Enjoy your audiobooks!")
