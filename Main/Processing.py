import logging
from Settings import getSettings
from pathlib import Path
from Util import *
import os



log = logging.getLogger(__name__)
settings = None
conversions = []

def loadSettings():
    global settings
    settings = getSettings()

def processConversions():
    #TODO explore converting in parallel?
    log.info("Processing conversions")
    for c in conversions:
        file = c.file
        type = c.type
        track = c.track
        md = c.md

        file = convertToM4B(file, type, md)
        track = mutagen.File(file, easy=True)

        if settings.fetch and settings.clean and settings.move:
            #if copying, we will only clean the copied file
            cleanMetadata(track, md)
        
        if settings.rename:
            #TODO
            #again, only apply to copy
            pass


def processFile(file):
    log.info(f"Processing {file.name}")
    track = mutagen.File(file, easy=True)
    type = Path(file).suffix.lower()
    md = Metadata   #need parends after metadata for constructor call?
    md.bookPath = settings.output


    if settings.fetch:
        #existing OPF is ignored in single level batch
        md = fetchMetadata(file, track)

        #TODO set md.bookPath according to rename
        md.bookPath = settings.output + f"\{md.author}\{md.title}"
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

    #TODO fails and skips - skips up top?
    
    if settings.move:
        log.info("Moving " + file.name + " to " + md.bookPath)
        file.rename(getUniquePath(file, md.bookPath))
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
    counter = 1

    while outFolder.is_dir():
        outFolder = infolder.joinpath(f"Ultimate temp{counter}")    #TODO any reason not to just nuke the old one?
        counter += 1

    outFolder.mkdir()
    combineAndFindChapters(infolder, outFolder, 0)  #TODO ultimate temp is scanned like an input folder
    
    log.info("Chapter files successfully combined and stored in temp folder. Initiating single level batch process on combined books.")
    singleLevelBatch(outFolder)

    log.debug("Removing temp folder")   #TODO what happens if there are failed/skipped books in here?
    outFolder.unlink()


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

    log.info("Batch completed. Enjoy your audiobooks!") #TODO extra end processing for failed books and such?


def recursivelyFetchBatch():
    log.info("Begin processing complete books in all subdirectories (recursively fetch batch)")
    infolder = Path(settings.input)
    files = getAudioFiles(infolder, settings.batch)

    for file in files:
        processFile(file)
        
    if len(conversions) > 0:
        processConversions()

    log.info("Batch completed. Enjoy your audiobooks!") #TODO extra end processing for failed books and such?

 
    return