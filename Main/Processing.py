import logging
from Settings import getSettings
from pathlib import Path
from Util import *
from FileMerger import combineAndFindChapters
import os
from concurrent.futures import ProcessPoolExecutor, wait
import math



log = logging.getLogger(__name__)
settings = None
conversions = []
skips = []
fails = []

def loadSettings():
    global settings
    settings = getSettings()

def processConversion(c, settings): #This is run through ProcessPoolExecutor, which limits access to globals
    file = c.file
    type = c.type
    track = c.track
    md = c.md

    file = convertToM4B(file, type, md, settings)
    track = mutagen.File(file, easy=True)

    if settings.fetch and settings.clean and settings.move:
        #if copying, we will only clean the copied file
        cleanMetadata(track, md)
    
    if settings.rename:
        #TODO rename
        #again, only apply to copy
        pass



def processConversions():
    log.info("Processing conversions")

    numWorkers = settings.workers
    if numWorkers == -1:
        numWorkers = math.floor(calculateWorkerCount())

        if numWorkers > 0:
            log.info(f"Number of workers not specified, set to {numWorkers} based on system CPU count and available memory")
        else:
            numWorkers = 1
            log.info("Number of workers not specified and unable to retrieve relevant system information. Defaulting to 1 worker.")

    with ProcessPoolExecutor(max_workers=numWorkers) as controller:
        futures = [controller.submit(processConversion, c, settings) for c in conversions]

        wait(futures)

        for future in futures:
            try:
                future.result()
            except Exception as e:
                log.error("Error processing conversion: " + str(e))

#TODO print log info place in batch
def processFile(file):
    log.info(f"Processing {file.name}")
    type = Path(file).suffix.lower()
    md = Metadata()
    md.bookPath = settings.output
    newPath = ""

    try:
        track = mutagen.File(file, easy=True)
    except mutagen.mp3.HeaderNotFoundError:
        log.error("File \"" + str(file) + "\" corrupt or otherwise unreadable as audio. Marking as failed...")
        md.failed = True
        fails.append(file)
        return

    if track == None:
        log.error("File unable to be processed. Check for corruption. Marking as failed...")
        md.failed = True
        fails.append(file)
        return


    if settings.fetch:
        #existing OPF is ignored in single level batch
        md = fetchMetadata(file, track)

        if md.skip:
            skips.append(file)
            return
        elif md.failed:
            fails.append(file)
            return

        #TODO (rename) set md.bookPath according to rename
        cleanAuthor = re.sub(r'[<>"|?’:,*\']', '', md.author)
        cleanTitle = re.sub(r'[<>"|?’:,*\']', '', md.title)
        md.bookPath = settings.output + f"/{cleanAuthor}/{cleanTitle}"
        

        log.debug(f"Making directory {md.bookPath} if not exists")
        Path(md.bookPath).mkdir(parents = True, exist_ok = True)

        if settings.create:
            createOpf(md)

        if settings.convert and type != '.m4b':
            log.debug(f"Queueing {file.name} for conversion")
            conversions.append(Conversion(file, track, type, md))
            return
        else:
            newPath = Path(md.bookPath) / Path(cleanTitle).with_suffix(type)

        if settings.clean and settings.move:
            #if copying, we will only clean the copied file
            cleanMetadata(track, md)

    if settings.convert and type != '.m4b':
        conversions.append(Conversion(file, track, type, md)) 
        return

    if settings.rename:
        #TODO rename
        #again, only apply to copy
        pass
    
    if md.skip:
        skips.append(file)
        return
    elif md.failed:
        fails.append(file)
        return
    
    if newPath == "":
        newPath = getUniquePath(file.name, md.bookPath)
    if settings.move:
        log.info("Moving " + file.name + " to " + md.bookPath)
        # TODO (rename) temporarily use title while working on rename
        file.rename(newPath)
    else:
        log.info("Copying " + file.name + " to " + md.bookPath)
        shutil.copy(file, newPath)

        if settings.fetch:
            cleanMetadata(mutagen.File(newPath, easy=True), md)

        

def recursivelyCombineBatch():
    log.info("Begin recursively finding, combining, and processing chapter books")
    infolder = Path(settings.input)

    outFolder = infolder.joinpath("Ultimate temp")

    if outFolder.is_dir():
        # outFolder.rmdir() #only works on empty dirs
        shutil.rmtree(outFolder)

    outFolder.mkdir()
    combineAndFindChapters(infolder, outFolder, 1, infolder)
    
    log.info("Chapter files successfully combined and stored in temp folder. Initiating single level batch process on combined books.")
    singleLevelBatch(outFolder)

    log.debug("Removing temp folder")
    if not any(outFolder.iterdir()):
        outFolder.rmdir()
    else:
        log.error("Error: temp directory not empty. Unable to delete.")



def recursivelyPreserveBatch():
    log.info("Begin resurively finding and processing chapter books (chapters will be preserved)")
    return


def singleLevelBatch(infolder = None):
    log.info("Begin single level batch processing")
    if infolder == None:
        infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch)

    for file in files:
        processFile(file)
        
    if len(conversions) > 0:
        processConversions()

    moveSkipsFails()

    log.info("Batch completed. Enjoy your audiobooks!")


def recursivelyFetchBatch():    #Since the only difference is passing true to getAudioFiles, I could probably fold this into another batch
    log.info("Begin processing complete books in all subdirectories (recursively fetch batch)")
    infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch, True)

    for file in files:
        processFile(file)
        
    if len(conversions) > 0:
        processConversions()

    moveSkipsFails()

    log.info("Batch completed. Enjoy your audiobooks!")

 
    return

def moveSkipsFails():
    infolder = Path(settings.input)
    if len(skips) > 0:
        log.info(str(len(skips)) + " skips. Moving to skip directory...")
        skipDir = infolder.parent.joinpath("Ultimate Audiobook skips")
        skipDir.mkdir()

        for file in skips:
            file.rename(skipDir / file.name)
    if len(fails) > 0:
        log.info(str(len(fails)) + " fails. Moving to fail directory...") #TODO what will happen with chapter books that failed in merge?
        failDir = infolder.parent.joinpath("Ultimate Audiobook fails")
        failDir.mkdir()

        for file in fails:
            file.rename(failDir / file.name)

def skipBook(file):
    skips.append(file)

def failBook(file):
    fails.append(file)