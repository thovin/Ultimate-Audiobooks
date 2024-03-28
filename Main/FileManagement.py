from Settings import settings
from pathlib import Path
from itertools import islice
import mutagen
from mutagen import id3, easyid3, mp3, mp4
from Util import *
import xml.etree.ElementTree as ET


def singleLevelBatch():
    infolder = Path(settings.input)
    files = list(islice(infolder.glob("*.m4*"), settings.batch))    #.m4a, .m4b

    if len(files) < settings.batch:
        files.append(list(islice(infolder.glob("*.mp*"), settings.batch - len(files)))) #.mp3, .mp4

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.flac"), settings.batch - len(files))))

    # if len(files) < settings.batch:
    #     files.append(list(islice(infolder.glob("*.wma"), settings.batch - len(files))))

    for file in files:
        track = mutagen.File(file, easy=True)
        if settings.fetch:
            #existing OPF is ignored in single level batch
            md = fetchMetadata(file, track)
            if settings.create:
                opf = createOpf(md)

            if settings.clean:
                #TODO overwrite file md
                pass

        if settings.convert and :#TODO file not m4b
            file = convertToM4B(file)

        if settings.rename:
            #TODO
            pass

        if settings.move:
            #TODO
            pass
        else:
            #TODO same but copy. In case of conversion, delete original?
            





def recursivelyFetchBatch():


def recursivelyCombineBatch():   #TODO single recurse func checking flags?



def recursivelyPreserveBatch():



def combine(folder):



def convertToM4B(file):
    #delete original file?


def cleanMetadata(file, md):



def createOpf(md):
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
        tree.write(outFile, xml_declaration=True, encoding="utf-8", method="xml")


