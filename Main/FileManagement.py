from Settings import getSettings
from pathlib import Path
from itertools import islice
import mutagen
from Util import *
import xml.etree.ElementTree as ET
import subprocess
import os
import shutil
import logging
import FileMerger

class Conversion:
    def __init__(self, file, track, type, md):
        self.file = file
        self.track = track
        self.type = type
        self.md = md
        

log = logging.getLogger(__name__)
settings = None
conversions = []

def loadSettings():
    global settings
    settings = getSettings()


def combine(folder):
    return  #FileMerger.py #redundant?


def getAudioFiles(folderPath, batch = -1):
    files = []
    files.extend(list((folderPath.glob("*.m4*"))))  #.m4a, .m4b
    files.extend(list(islice(folderPath.glob("*.mp*"), 0)))  #.mp3, .mp4
    files.extend(list(islice(folderPath.glob("*.flac"), 0)))  #flac
    files.extend(list(islice(folderPath.glob("*.wma"), 0)))  #wma
    files.extend(list(islice(folderPath.glob("*.wav"), 0)))  #wav

    if batch == -1 or len(files) < batch:
        return files
    elif len(files) == 0:
        return -1
    else:
        return files[:batch]


def convertToM4B(file, type, md):
    #When copying we create the new file in destination, otherwise the new file will be copied and there will be an extra original
    #When moving we convert in place and allow the move to be handled in EOF processing
    log.info("Converting " + file.name + " to M4B")
    newPath = Path(md.bookPath + "\\" + file.with_suffix('.mp4').name)
    cmd = ['ffmpeg',
           '-i', file,  #input file
           '-codec', 'copy', #copy audio streams instead of re-encoding
           '-vn',   #disable video
           newPath]
    
    
    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)

            if settings.move:
                file.unlink()   #delete original file

            return newPath.rename(newPath.with_suffix('.m4b'))
        except subprocess.CalledProcessError as e:
            log.error(f"Conversion failed! Aborting file...")
            md.failed = True
            return file

    elif type == '.mp4':
        log.debug("Converting MP4 to M4B")

        if settings.move:
            return file.rename(file.with_suffix('.m4b'))
        else:
            return shutil.copy(file, newPath.with_suffix('.m4b'))


def cleanMetadata(track, md):
    log.info("Cleaning file metadata")
    if isinstance(track, mp3.EasyMP3):
        log.debug("Cleaning easymp3 metadata")

        #TODO genres
        track.delete()
        track['title'] = md.title
        track['artist'] = md.narrator
        track['album'] = md.series
        track['date'] = md.publishYear
        track['discnumber'] = md.volumeNumber
        track['author'] = md.author
        track['asin'] = md.asin
        track.ID3.RegisterTXXXKey('description', md.summary)
        track.ID3.RegisterTXXXKey('subtitle', md.subtitle)
        track.ID3.RegisterTXXXKey('isbn', md.isbn)
        track.ID3.RegisterTXXXKey('publisher', md.publisher)

    elif isinstance(track, easymp4.EasyMP4):
        log.debug("Cleaning easymp4 metadata")
        track.RegisterTextKey('narrator', '@nrt')
        track.RegisterTextKey('author', '@aut')
        track.MP4Tags.RegisterFreeformKey('publisher', "----:com.thovin.publisher")
        track.MP4Tags.RegisterFreeformKey('isbn', "----:com.thovin.isbn")
        track.MP4Tags.RegisterFreeformKey('asin', "----:com.thovin.asin")
        track.MP4Tags.RegisterFreeformKey('series', "----:com.thovin.series")

        #TODO genres
        track.delete()
        track['title'] = md.title
        track['narrator'] = md.narrator
        track['date'] = md.publishYear
        track['description'] = md.summary
        track['author'] = md.author
        track['publisher'] = md.publisher
        track['isbn'] = md.isbn
        track['asin'] = md.asin
        track['series'] = md.series

        if md.volumeNumber != "":
            track['discnumber'] = md.volumeNumber

    elif isinstance(track, mp3.MP3):
        log.debug("Cleaning mp3 metadata")

        track.delete()
        track.add(mutagen.TIT2(encoding = 3, text = md.title))
        track.add(mutagen.TPE1(encoding = 3, text = md.narrator))
        track.add(mutagen.TALB(encoding = 3, text = md.series))
        track.add(mutagen.TYER(encoding = 3, text = md.publishYear))
        track.add(mutagen.TPOS(encoding = 3, text = md.volumeNumber))
        track.add(mutagen.TCOM(encoding = 3, text = md.author))
        # track.add(mutagen.TCON(encoding = 3, text = md.md.genres[0]))  #can list multiples by separating with /, //, or ;
        track.add(mutagen.TPUB(encoding = 3, text = md.publisher))
        track.add(mutagen.TXXX(encoding = 3, desc='description', text = md.summary))
        track.add(mutagen.TXXX(encoding = 3, desc='subtitle', text = md.subtitle))
        track.add(mutagen.TXXX(encoding = 3, desc='isbn', text = md.isbn))
        track.add(mutagen.TXXX(encoding = 3, desc='asin', text = md.asin))
        track.add(mutagen.TXXX(encoding = 3, desc='publisher', text = md.publisher))

    elif isinstance(track, mp4.MP4):
        log.debug("Cleaning mp4/m4b metadata")
        
        track['\xa9nam'] = md.title
        # track['\xa9gen'] = md.genres[0]
        track['\xa9day'] = md.publishYear
        track['trkn'] = [(int(md.volumeNumber), 0)]
        track['\xa9aut'] = md.author
        track['\xa9des'] = md.summary
        track['\xa9nrt'] = md.narrator
        track['----:com.thovin:isbn'] = mutagen.mp4.MP4FreeForm(md.isbn.encode('utf-8'))
        track['----:com.thovin:asin'] = mutagen.mp4.MP4FreeForm(md.asin.encode('utf-8'))
        track['----:com.thovin:series'] = mutagen.mp4.MP4FreeForm(md.series.encode('utf-8'))

    else:
        log.error("Audio file not detected as MP3, MP4, or M4A/B. Unable to clean metadata.")
        return

    track.save()




def createOpf(md):
    log.info("Creating OPF")
    dcLink = "{http://purl.org/dc/elements/1.1/}"
    package = ET.Element("package", version="3.0", xmlns="http://www.idpf.org/2007/opf", unique_identifier="BookId")
    metadata = ET.SubElement(package, "metadata", nsmap={'dc' : dcLink})

    author = ET.SubElement(metadata, f"{dcLink}creator", attrib={ET.QName(dcLink, "role"): "aut"})
    author.text = md.author

    #TODO handle multiples (2 authors, etc)
    title = ET.SubElement(metadata, f"{dcLink}title")
    title.text = md.title

    summary = ET.SubElement(metadata, f"{dcLink}description")
    summary.text = md.summary

    # subtitle = ET.SubElement(metadata, f"{dcLink}subtitle")
    # subtitle.text = md.subtitle

    narrator = ET.SubElement(metadata, f"{dcLink}contributor", attrib={ET.QName(dcLink, "role"): "nrt"})
    narrator.text = md.narrator

    publisher = ET.SubElement(metadata, f"{dcLink}publisher")
    publisher.text = md.publisher

    publishYear = ET.SubElement(metadata, f"{dcLink}date")
    publishYear.text = md.publishYear

    isbn = ET.SubElement(metadata, f"{dcLink}identifier", attrib={ET.QName(dcLink, "scheme"): "ISBN"})
    isbn.text = md.isbn

    asin = ET.SubElement(metadata, f"{dcLink}identifier", attrib={ET.QName(dcLink, "scheme"): "ASIN"})
    asin.text = md.asin

    series = ET.SubElement(metadata, f"{dcLink}meta", attrib={"property" : "belongs-to-collection", "id" : "series-id"})
    series.text = md.series

    volumeNumber = ET.SubElement(metadata, f"{dcLink}meta", attrib={"refines" : "#series-id", "property" : "group-position"})
    volumeNumber.text = md.volumeNumber


    tree = ET.ElementTree(package)
    with open (md.bookPath + "/metadata.opf", "wb") as outFile:
        log.debug("Write OPF file")
        tree.write(outFile, xml_declaration=True, encoding="utf-8", method="xml")
            

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
    #TODO check for existing book
    
    if settings.move:
        log.info("Moving " + file.name + " to " + md.bookPath)
        file.rename(md.bookPath)
        # file.rename(md.bookPath + file.name)
        # shutil.move(file, md.bookPath)
    else:
        if settings.fetch:
            cleanMetadata(track, md)

        log.info("Copying " + file.name + " to " + md.bookPath)
        shutil.copy(file, md.bookPath)


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


def combineAndFindChapters(startPath, outPath, counter):
    #filepaths or path objects?
    #outpath is a temp dir, no need for naming
    #if single books are found they are returned, so this works for mixed whole and chapter books 

    subfolders = [path.name for path in Path(startPath).glob('*') if path.is_dir()]
    for folder in subfolders:
        if counter <= settings.batch:
            if settings.move:
                counter = combineAndFindChapters(folder, outPath, counter)
                #TODO PROCESS THE DAMN BOOK
            else:
                pass    #TODO
        else:
            return counter
        


    #TODO this doesn't work when copying
    files = getAudioFiles(startPath)
    if files == -1:
        pass
    elif len(files) == 1:
        counter += 1
        files[0].rename(outPath + f"\\{files[0].name}")
    elif len(files) > 1:
        counter += 1
        FileMerger.mergeBook(startPath, outPath)

    return counter

    '''
    If -M, nuke emptied folder. Ensure there are no unchecked subfolders first!
    Either way, combined files should be put into outpath

    '''


def recursivelyCombineBatch():
    log.info("Begin recursively finding, combining, and processing chapter books")
    infolder = Path(settings.input)

    outFolder = infolder.joinpath("Ultimate temp")
    counter = 1

    while outFolder.is_dir():
        outFolder = infolder.joinpath(f"Ultimate temp{counter}")
        counter += 1

    outFolder.mkdir()
    combineAndFindChapters(Path(settings.input), outFolder, 0)
    
    log.info("Chapter files successfully combined and stored in temp folder. Initiating single level batch process on combined books.")
    singleLevelBatch(outFolder)

    log.debug("Removing temp folder")   #TODO what happens if there are failed/skipped books in here?
    outFolder.unlink()


def recursivelyPreserveBatch():
    log.info("Begin resurively finding and processing chapter books (chapters will be preserved)")
    return