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
    return  #FileMerger.py


def convertToM4B(file, type, md):
    log.info("converting " + file.name + " to M4B")
    cmd = ['ffmpeg',
           '-i', file,  #input file
           '-codec', 'copy', #codec, audio
           '-vn',   #disable video
           '-f', 'mp4', #force output format
           '-y', #yes, overwrite existing file (due to same name)
           file.with_suffix('.m4b')]    #output file
    
    
    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)
            newFile = file.with_suffix('.m4b')
            file.unlink()   #delete original file
            return newFile
        except subprocess.CalledProcessError as e:
            log.error(f"Conversion failed! Aborting file...")
            md.failed = True
            return file

    elif type == '.mp4':
        log.debug("Converting MP4 to M4B")
        newName = file.with_suffix('.m4b')
        file.rename(newName)

def cleanMetadata(track, md):
    log.info("Cleaning file metadata")
    if isinstance(track, mp3.EasyMP3):
        log.debug("cleaning easymp3 metadata")

        #TODO genres
        track.delete()
        track['title'] = md.title
        track['artist'] = md.narrator
        track['album'] = md.series
        track['date'] = md.publishYear
        track['discNumber'] = md.volumeNumber
        track['author'] = md.author
        track['asin'] = md.asin
        track.ID3.RegisterTXXXKey('description', md.summary)
        track.ID3.RegisterTXXXKey('subtitle', md.subtitle)
        track.ID3.RegisterTXXXKey('isbn', md.isbn)
        track.ID3.RegisterTXXXKey('publisher', md.publisher)

    elif isinstance(track, easymp4.EasyMP4):
        log.debug("cleaning easymp4 metadata")
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
        track['discNumber'] = md.volumeNumber
        track['author'] = md.author
        track['publisher'] = md.publisher
        track['isbn'] = md.isbn
        track['asin'] = md.asin
        track['series'] = md.series

    elif isinstance(track, mp3.MP3):
        log.debug("cleaning mp3 metadata")

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
        log.debug("cleaning mp4/m4b metadata")
        
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


def singleLevelBatch():
    log.info("Begin single level batch processing")
    infolder = Path(settings.input)
    files = list(islice(infolder.glob("*.m4*"), settings.batch))    #.m4a, .m4b

    if len(files) < settings.batch:
        for file in list(islice(infolder.glob("*.mp*"), settings.batch - len(files))):  #.mp3, .mp4
            files.append(file)

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.flac"), settings.batch - len(files))))

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.wma"), settings.batch - len(files))))

    for file in files:
        processFile(file)
        if len(conversions) > 0:
            processConversions()

    log.info("Batch completed. Enjoy your audiobooks!") #TODO extra end processing for failed books and such?
            

def processConversions():
    #TODO explore converting in parallel?
    log.info("Processing conversions")
    for c in conversions:
        file = c.file
        type = c.type
        track = c.track
        md = c.md

        convertToM4B(file, type, md)
        track = mutagen.File(file, easy=True)

        if settings.fetch and settings.clean and settings.move:
            #if copying, we will only clean the copied file
            cleanMetadata(track, md)
        
        processFileEnding(file, track, md)

        

def processFile(file):
    log.info(f"Processing {file.name}")
    track = mutagen.File(file, easy=True)
    type = Path(file).suffix.lower()
    md = Metadata   #need parends after metadata for constructor call?


    if settings.fetch:
        #existing OPF is ignored in single level batch
        md = fetchMetadata(file, track)
        #TODO set md.bookPath according to rename
        md.bookPath = settings.output + f"\{md.author}\{md.title}"
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

    processFileEnding(file, track, md)

def processFileEnding(file, track, md):
    if settings.rename:
        #TODO
        #again, only apply to copy
        pass

    #TODO fails and skips - skips up top?
    #TODO check for existing book
    log.debug(f"Making directory {md.bookPath} if not exists")
    if settings.move:
        log.info("Moving " + file.name + " to " + md.bookPath)
        # file.rename(md.bookPath + file.name)
        shutil.move(file, md.bookPath)
    else:
        if settings.fetch:
            cleanMetadata(track, md)

        log.info("Copying " + file.name + " to " + md.bookPath)
        shutil.copy(file, md.bookPath)

def recursivelyFetchBatch():
    return


def recursivelyCombineBatch():   #TODO single recurse func checking flags?
    return


def recursivelyPreserveBatch():
    return