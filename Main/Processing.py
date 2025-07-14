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
        #TODO
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
            log.info("Number of works not specified and unable to retrieve relevant system information. Defaulting to 1 worker.")

    with ProcessPoolExecutor(max_workers=numWorkers) as controller:
        futures = [controller.submit(processConversion, c, settings) for c in conversions]

        wait(futures)

        for future in futures:
            try:
                future.result()
            except Exception as e:
                log.error(e)    #TODO proper message


def processFile(file):
    log.info(f"Processing {file.name}")
    track = mutagen.File(file, easy=True)
    type = Path(file).suffix.lower()
    md = Metadata()
    md.bookPath = settings.output


    if settings.fetch:
        #existing OPF is ignored in single level batch
        md = fetchMetadata(file, track)

        if md.skip or md.failed:
            skips.append(file)

        #TODO set md.bookPath according to rename
        md.bookPath = settings.output + f"/{md.author}/{md.title}"
        log.debug(f"Making directory {md.bookPath} if not exists")
        Path(md.bookPath).mkdir(parents = True, exist_ok = True)

        if settings.create:
            createOpf(md)

        if settings.convert and type != '.m4b':
            log.debug(f"Queueing {file.name} for conversion")
            conversions.append(Conversion(file, track, type, md))
            return

        if settings.clean and settings.move:
            #if copying, we will only clean the copied file
            cleanMetadata(track, md)

    if settings.convert and type != '.m4b':
        conversions.append(Conversion(file, track, type, md)) 
        return

    if settings.rename:
        #TODO
        #again, only apply to copy
        pass
    
    if settings.move:
        log.info("Moving " + file.name + " to " + md.bookPath)
        # file.rename(getUniquePath(file, md.bookPath))
        # TODO temporarily use title while working on rename
        # file.rename(getUniquePath(md.title, md.bookPath))
        file.rename(getUniquePath(file.name, md.bookPath))
        # file.rename(md.bookPath + file.name)
        # shutil.move(file, md.bookPath)
    else:
        if settings.fetch:
            cleanMetadata(track, md)

        log.info("Copying " + file.name + " to " + md.bookPath)
        shutil.copy(file, getUniquePath(file, md.bookPath))

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

    log.debug("Removing temp folder")   #TODO what happens if there are failed/skipped books in here? It errors, dir not empty.
    outFolder.rmdir()


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

    if len(skips) > 0:
        log.info("Books skipped or failed:")
        for file in skips:
            log.info(file.name)

    log.info("Batch completed. Enjoy your audiobooks!") #TODO extra end processing for failed books and such?


def recursivelyFetchBatch():    #Since the only difference is passing true to getAudioFiles, I could probably fold this into another batch
    log.info("Begin processing complete books in all subdirectories (recursively fetch batch)")
    infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch, True)

    for file in files:
        processFile(file)
        
    if len(conversions) > 0:
        processConversions()

    log.info("Batch completed. Enjoy your audiobooks!") #TODO extra end processing for failed books and such?

 
    return