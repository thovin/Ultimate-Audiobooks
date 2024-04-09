from Settings import getSettings
from pathlib import Path
from itertools import islice
import mutagen
#from mutagen import id3, easyid3, mp3, mp4
from Util import *
import xml.etree.ElementTree as ET
import subprocess
import os
import shutil
import logging

log = logging.getLogger(__name__)
settings = None

def loadSettings():
    global settings
    settings = getSettings()


def combine(folder):
    return


def convertToM4B(file, type):
    log.info("converting " + file + " to M4B")
    cmd = ['ffmpeg',
           '-i', file,  #input file
           '-codec:a', 'aac', #codec, audio
           '-b:a', '64k', #bitrate, audio
           '-vn',   #disable video
           '-f', 'mp4', #force output format
           file.name]    #output file. do I have to cast to Path first?
    
    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)
            newFile = file.with_suffix('.m4b')
            file.unlink()   #delete original file
            file = newFile
        except subprocess.CalledProcessError as e:
            pass    #ERROR

    elif type == '.mp4':
        log.debug("Converting MP4 to M4B")
        newName = file.with_suffix('.m4b')
        file.rename(newName)



def cleanMetadata(file, type, md):  #TODO rework to take advantage of mutagen's easyMP3/4 tagging #TODO in easyid3/4 all tags are stored as lists
    log.info("Cleaning file metadata")
    if type == '.mp3':
        log.debug("cleaning mp3 metadata")
        data = mutagen.ID3(file)    #can put in try-except if needed

        data.delete()
        data.add(mutagen.TIT2(encoding = 3, text = md.title))
        data.add(mutagen.TPE1(encoding = 3, text = md.narrator))
        data.add(mutagen.TALB(encoding = 3, text = md.series))
        data.add(mutagen.TYER(encoding = 3, text = md.publishYear))
        data.add(mutagen.TPOS(encoding = 3, text = md.volumeNumber))
        data.add(mutagen.TCOM(encoding = 3, text = md.author))
        # data.add(mutagen.TCON(encoding = 3, text = md.md.genres[0]))  #can list multiples by separating with /, //, or ;
        data.add(mutagen.TPUB(encoding = 3, text = md.publisher))
        data.add(mutagen.TXXX(encoding = 3, desc='description', text = md.summary))
        data.add(mutagen.TXXX(encoding = 3, desc='subtitle', text = md.subtitle))
        data.add(mutagen.TXXX(encoding = 3, desc='isbn', text = md.isbn))
        data.add(mutagen.TXXX(encoding = 3, desc='asin', text = md.asin))
        data.add(mutagen.TXXX(encoding = 3, desc='publisher', text = md.publisher))


        # track["TIT2"] = mutagen.TIT2(encoding = 3, text = md.title)
        # track["TPE1"] = mutagen.TPE1(encoding = 3, text = md.narrator)
        # track["TALB"] = mutagen.TALB(encoding = 3, text = md.series)
        # track["TYER"] = mutagen.TYER(encoding = 3, text = md.publishYear)
        # track["TPOS"] = mutagen.TPOS(encoding = 3, text = md.volumeNumber)
        # track["TCOM"] = mutagen.TCOM(encoding = 3, text = md.author)
        # # track["TCON"] = mutagen.TCON(encoding = 3, text = md.genres[0])
        # track["TPUB"] = mutagen.TPUB(encoding = 3, text = md.publisher)
        # trackhow

    elif type == '.mp4' or type == '.m4b':  #TODO are the custom fields the best way to do it?
        log.debug("cleaning mp4/M4B metadata")
        track = mutagen.MP4(file)

        track['\xa9nam'] = md.title
        # track['\xa9gen'] = md.genres[0]
        track['\xa9day'] = md.publishYear
        track['trkn'] = md.volumeNumber
        track['\xa9aut'] = md.author
        track['\xa9des'] = md.summary
        track['\xa9nrt'] = md.narrator
        track['----:com.thovin.isbn'] = md.isbn
        track['----:com.thovin.asin'] = md.asin
        track['----:com.thovin.series'] = md.series

    else:   #ERROR
        return

    log.debug("Saving audio track with new metadata")
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
    with open ("metadata.opf", "wb") as outFile:
        log.debug("Write OPF file")
        tree.write(outFile, xml_declaration=True, encoding="utf-8", method="xml")


def singleLevelBatch():
    log.info("Begin single level batch processing")
    infolder = Path(settings.input).parent
    files = list(islice(infolder.glob("*.m4*"), settings.batch))    #.m4a, .m4b

    if len(files) < settings.batch:
        for file in list(islice(infolder.glob("*.mp*"), settings.batch - len(files))):
            files.append(file)
        # files.append() #.mp3, .mp4

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.flac"), settings.batch - len(files))))

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.wma"), settings.batch - len(files))))

    for file in files:
        track = mutagen.File(file, easy=True)
        type = Path(file).suffix.lower()

        if settings.fetch:
            #existing OPF is ignored in single level batch
            md = fetchMetadata(file, track)
            if settings.create:
                opf = createOpf(md)

            if settings.clean and not settings.convert:
                cleanMetadata(file, type, md)

        if settings.convert and type != '.m4b':
            file = convertToM4B(file, type)

        if settings.rename:
            #TODO
            pass

#TODO move opf
        if settings.move:
            log.info("Moving " + file.name + " to " + settings.output)
            # file.rename(settings.output + file.name)
            shutil.move(file, settings.output)
        else:
            log.info("Copying " + file.name + " to " + settings.output)
            shutil.copy(file, settings.output)

    log.info["Batch completed. Enjoy your audiobooks!"] #TODO extra end processing for failed books and such?
            

def recursivelyFetchBatch():
    return


def recursivelyCombineBatch():   #TODO single recurse func checking flags?
    return


def recursivelyPreserveBatch():
    return