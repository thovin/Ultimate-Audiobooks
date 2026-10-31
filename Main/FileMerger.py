from Settings import getSettings
import mutagen
import re
import logging
import tempfile
from pathlib import Path
import os
import shutil
from Util import sanitizeFile, getAudioFiles, getUniquePath, runFfmpeg, FFMPEG_PROGRESS_ARGS, ALWAYS_TRANSCODE_TYPES
from BookStatus import skipBook, failBook, setOriginalPath
import Reporter

log = logging.getLogger(__name__)
settings = None

def loadSettings():
    global settings
    settings = getSettings()

def findTitleNum(title, whichNum) -> int:
    title = title.upper()
    try:
        return int(re.findall(r'\d+', title)[whichNum])  #find all numbers, return specified
    except IndexError:
        if any(word in title for word in ["intro".upper(), "prologue".upper()]):
            log.debug("Intro or prologue detected. Setting as first element in trackmap.")
            return 0
        if any(word in title for word in ["outro".upper(), "epilogue".upper(), "credits".upper()]):
            log.debug("Outro, epilogue, or credits detected. Setting as last element in trackmap.")
            return 999
        else:
            log.debug("Failed to find keyword or number in title on numberPosition " + str(whichNum))
            return -1   #no more numbers in title


def orderByTrackNumber(tracks, hasMultipleDisks):
    log.debug("Attempting to order files by track number...")
    chapters = [None] * (len(tracks) + 1)


    if hasMultipleDisks:
        tracksDone = 0
        disk = 1
        while tracksDone < len(tracks):
            if disk > len(tracks):
                #disc numbering has gaps or is inconsistent; nothing left to place
                log.debug("Unable to resolve disc numbering. Aborting track number sort.")
                return []
            offset = tracksDone
            for track in tracks:
                try:
                    diskNumber = int(track['discnumber'][0].split('/')[0])
                    trackNumber = int(track['tracknumber'][0].split('/')[0])
                except (KeyError, ValueError, IndexError):
                    log.debug("Missing or malformed disc/track number. Aborting track number sort.")
                    return []

                if diskNumber == disk:
                    index = trackNumber + offset
                    if index < 0 or index >= len(chapters) or chapters[index] is not None:
                        log.debug("Invalid or overlapping track numbers detected. Aborting track number sort.")
                        return []
                    chapters[index] = track
                    tracksDone += 1
            disk += 1
    else:
        for track in tracks:
            trackNumber = int(track['tracknumber'][0].split('/')[0])
            if trackNumber < 0 or trackNumber >= len(chapters):
                log.debug("Track number out of range. Aborting track number sort.")
                return []
            if chapters[trackNumber] == None:
                chapters[trackNumber] = track
            else:
                log.debug("Overlapping track numbers detected. Aborting track number sort.")
                return []

    if chapters[0] == None:
        chapters = chapters[1:]

    if chapters[-1] == None:
        chapters = chapters[:-1]

    if any(chapter is None for chapter in chapters):
        #gaps mean numbering didn't line up (e.g. discs not numbered from 1)
        log.debug("Gaps in track numbering detected. Aborting track number sort.")
        return []

    return chapters


def orderByTitle(tracks, folderPath=None):
    log.debug("Attempting to order files by name...")
    whichNum = 0

    #TODO fails to detect janky disk number formatting in lean mean thirteen
    while True:
        trackMap = {}
        for track in tracks:
            key = findTitleNum(Path(track.filename).stem, whichNum)
            if key in trackMap and key != -1:
                log.debug("Duplicate track numbers detected at position " + str(whichNum))
                trackMap = {999:"error"}
                break
            else:
                trackMap[key] = track
        ordered = sorted(trackMap.keys())

        if -1 in trackMap:
            log.debug("Failed to order files by name")
            return []   #no more numbers, no order beginning in 1
        elif ordered[0] != 0 and ordered[0] != 1:
            whichNum += 1
            continue
        else:
            tracksOut = []
            for key in ordered:
                tracksOut.append(trackMap[key])
            return tracksOut
    

class MergeJob:
    #pickled to ProcessPoolExecutor workers, so hold only simple values
    def __init__(self, folderPath, cmd, totalSeconds, newFilepath, concatPath, chapPath, outPath, move, chapters):
        self.folderPath = folderPath
        self.cmd = cmd
        self.totalSeconds = totalSeconds  #runtime of the assembled book, for progress
        self.newFilepath = newFilepath
        self.concatPath = concatPath
        self.chapPath = chapPath
        self.outPath = outPath
        self.move = move
        self.chapters = chapters


#merges that must transcode (FLAC) are queued here and run in parallel by Processing.processMerges,
#since each is a full AAC encode. Stream-copy merges are fast and run inline.
pendingMerges = []


def runMergeJob(job):
    """The ffmpeg half of a merge. Safe to run in a worker: touches no book-status state. Returns True on success."""
    Reporter.bookStep(Reporter.STEP_MERGE, job.folderPath.name,
                      f"{job.chapters} chapter{'s' if job.chapters != 1 else ''}")
    log.debug("Begin combining")
    return runFfmpeg(job.cmd, Reporter.STEP_MERGE, job.folderPath.name, job.totalSeconds)


def failMerge(job):
    failBook(job.folderPath, "ffmpeg error during chapter merge")


def finishMerge(job):
    """The parent-side bookkeeping after a successful merge."""
    # Register original path for merged file in temp folder
    if job.outPath:
        setOriginalPath(job.newFilepath, job.folderPath)

    if job.move:
        with open(job.concatPath, 'r') as t:
            for line in t:
                os.remove(line[5:].strip().strip('\''))

    os.remove(job.concatPath)
    os.remove(job.chapPath)


def mergeBook(folderPath, outPath = False, move = False):
    log.debug("Begin merging chapters in " + folderPath.name)
    #the first group with any files wins, so a folder is only ever merged as one kind of audio
    files = []
    for suffixes in (('.mp3', '.mp4'), ('.m4a', '.m4b'), ('.flac',), ('.opus',), ('.ogg', '.oga'), ('.wav',), ('.wma',)):
        files = [f for f in folderPath.glob('*') if f.suffix.lower() in suffixes]
        if files:
            break

    if len(files) < 1:
        log.warning("No audio files found in " + folderPath.name + ". Nothing to merge.")
        return None

    needsTranscode = files[0].suffix.lower() in ALWAYS_TRANSCODE_TYPES
    # Chapters in these formats are merged directly to M4B/AAC: stream-copy via concat doesn't
    # update FLAC's internal sample numbers, causing non-monotonic DTS, and none of them can sit in
    # an MP4 container as-is anyway. Transcoding in one pass avoids a broken intermediate file and a
    # redundant decode/encode cycle.
    outSuffix = '.m4b' if needsTranscode else files[0].suffix
    codec_args = ['-c:a', 'aac', '-q:a', '3'] if needsTranscode else ['-codec', 'copy']

    newName = folderPath.name + " - " + files[0].stem + outSuffix
    newFilepath = getUniquePath(newName, outPath if outPath else folderPath)

    log.debug(str(len(files)) + " chapters detected")
    #TODO (rename) when --rename is working, apply here
    #TODO improve processing for multiple disks not in metadata

    for i in range(len(files)):
        if settings.move:
            files[i] = sanitizeFile(files[i])
        else:
            path, name = os.path.split(files[i])
            copyFile = shutil.copy(files[i], os.path.join(path, f"COPY{name}"))
            files[i] = sanitizeFile(copyFile)

    pieces = orderFiles(files, folderPath)

    if len(pieces) == 0:
        return

    # TODO When sanitizing chapter files, worth trying to keep the original name in chapter metadata?
    tempConcatFilePath, tempChapFilePath = createTempFiles(pieces, folderPath)

    cmd = ['ffmpeg',
        '-nostdin',  #never prompt on stdin (a prompt would hang the run)
        '-f', 'concat',
        '-safe', '0',
        '-i', tempConcatFilePath,
        '-i', tempChapFilePath, "-map_metadata", "1",
        *codec_args,
        '-vn',   #disable video
        '-hide_banner',  #suppress version/build info header
        '-loglevel', 'error',
        *FFMPEG_PROGRESS_ARGS,
        newFilepath
        ]

        #TODO manually parse out ffmpeg warnings like "Error reading comment frame, skipped", "Incorrect BOM value", "Application provided invalid, non monotonically increasing dts to muxer in <stream 0: 182540921472 >= 182539260288>"

    #total runtime of the assembled book, so the merge can report real progress rather than
    #sitting silent through what is usually the longest part of a run
    totalSeconds = sum(getattr(p.info, 'length', 0) or 0 for p in pieces)

    job = MergeJob(folderPath, cmd, totalSeconds, newFilepath, tempConcatFilePath, tempChapFilePath,
                   outPath, move, len(files))

    if needsTranscode:
        #a full transcode: defer so every such book can encode at once
        pendingMerges.append(job)
        return None

    if not runMergeJob(job):
        failMerge(job)
        return None

    finishMerge(job)
    return newFilepath

def orderFiles(files, folderPath=None):
    pieces = []
    tracks = []
    hasMultipleDisks = False

    for file in files:
        try:
            track = mutagen.File(file, easy=True)
        except mutagen.mp3.HeaderNotFoundError:
            failBook(folderPath, "Corrupt or unreadable audio file")
            return []

        tracks.append(track)

        try:
            #easy tags are strings, possibly "disc/total" format
            if int(track['discnumber'][0].split('/')[0]) > 1:
                hasMultipleDisks = True
        except (KeyError, ValueError, IndexError):
            pass

    try:
        pieces = orderByTrackNumber(tracks, hasMultipleDisks)
    except Exception as e:
        log.debug("Failed to order files by track number")
        pass

    if len(pieces) == 0:
        pieces = orderByTitle(tracks, folderPath)

    if len(pieces) == 0:
        if folderPath:
            failBook(folderPath, "Failed to order files")
    else:
        log.debug("Pieces ordered")

    return pieces

def createTempFiles(pieces, folderPath):
    log.debug("Write files to tempConcatFileList")
    tempConcatFilepath = ""
    tempChapFilepath = ""
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', dir=folderPath) as tempConcatFile, \
    tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', dir=folderPath) as tempChapFile:
        #TODO skip books when this errors instead of crashing whole script? Especially on the for p loop. //This should be solved by checking for empty pieces list. Keep an eye on it.
        runningTime = 0
        chapCount = 1
        tempChapFile.write(";FFMETADATA1\n")

        for p in pieces: #p = mutagen easyMP*
            tempConcatFile.write(f"file '{p.filename}'\n")

            tempChapFile.write("[CHAPTER]\n")
            tempChapFile.write("TIMEBASE=1/1000\n")
            tempChapFile.write(f"START={runningTime}\n")
            runningTime += p.info.length * 1000
            tempChapFile.write(f"END={runningTime}\n")
            tempChapFile.write(f"title=Chapter {chapCount}\n\n")
            chapCount += 1

        tempConcatFilepath = tempConcatFile.name
        tempChapFilepath = tempChapFile.name



    return tempConcatFilepath, tempChapFilepath


def combineAndFindChapters(startPath, outPath, counter, root):
    #filepaths or path objects?
    #outpath is a temp dir, no need for naming
    #if single books are found they are returned, so this works for mixed whole and chapter books 

    subfolders = [path for path in startPath.glob('*') if path.is_dir()]
    if outPath in subfolders:
        subfolders.remove(outPath)    #prevents Ultimate temp from being processed
    for folder in subfolders:
        if counter <= settings.batch:
            if settings.move:
                counter = combineAndFindChapters(folder, outPath, counter, root)
            else:
                pass    #TODO
        else:
            return counter
        


    #TODO this doesn't work when copying
    #TODO delete chapter files and/or folder after processing. Make sure you don't accidently kill subs.
    files = getAudioFiles(startPath)
    if not files or startPath == root:    #ignore files in the root folder
        pass
    elif len(files) == 1:
        originalFile = files[0]
        #counter is 1-based coming in, so it is this book's number; total is unknown because the
        #batch setting is a ceiling, not a count, and the walk hasn't finished
        Reporter.bookStarted(counter, -1, startPath.name, bookId=startPath)
        counter += 1
        newFile = outPath / f"{files[0].name}"
        files[0].rename(newFile)
        # Register original path for files moved to temp folder
        setOriginalPath(newFile, originalFile)
        Reporter.bookFinished(Reporter.STATUS_OK, startPath.name, "already a single file")
    elif len(files) > 1:
        Reporter.bookStarted(counter, -1, startPath.name, bookId=startPath)
        counter += 1
        #failures are reported by mergeBook itself (via failBook), so only the success needs closing.
        #Deferred (transcoding) merges return None and are closed out by Processing.processMerges.
        if mergeBook(startPath, outPath, settings.move):
            Reporter.bookFinished(Reporter.STATUS_OK, startPath.name)

    return counter

    '''
    If -M, nuke emptied folder. Ensure there are no unchecked subfolders first!
    Either way, combined files should be put into outpath

    '''