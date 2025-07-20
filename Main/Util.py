from Settings import getSettings
from pathlib import Path
from itertools import islice
import mutagen
from mutagen import easymp4, mp3, mp4
import webbrowser
import time
import requests
from bs4 import BeautifulSoup
import logging
import pyperclip
import subprocess
import shutil
import xml.etree.ElementTree as ET
import os
import psutil
import platform
import urllib.parse
import re

log = logging.getLogger(__name__)
settings = None
conversions = []

def loadSettings():
    global settings
    settings = getSettings()

class Metadata:
    def __init__(self):
        self.author = ""
        self.authors = []
        self.title = ""
        self.summary = ""
        self.subtitle = ""
        self.narrator = ""
        self.narrators = []
        self.publisher = ""
        self.publishYear = ""
        self.genres = []
        self.isbn = ""
        self.asin = ""
        self.series = ""
        self.seriesMulti = []
        self.volumeNumber = ""
        self.bookPath = ""
        self.skip = False
        self.failed = False

class Conversion:
    def __init__(self, file, track, type, md):
        self.file = file
        self.track = track
        self.type = type
        self.md = md


def getTitle(track):
    log.debug("Extracting title from track")

    if isinstance(track, mp3.EasyMP3) or isinstance(track, easymp4.EasyMP4):
        if 'title' in track and track['title'] != "":
            return track['title'][0]
        elif 'album' in track and track['album'] != "":
            return track['album'][0]
        else:
            log.debug("No title found. Returning empty string")
            return ""
    elif isinstance(track, mp3.MP3):
        if 'TIT2' in track and track['TIT2'] != "":
            return track['TIT2']
        elif 'TALB' in track and track['TALB'] != "":
            return track['TALB']
        else:
            log.debug("No title found. Returning empty string")
            return ""
    elif isinstance(track, mp4.MP4):
        if '\xa9nam' in track and track['\xa9nam'] != "":
            return track['\xa9nam']
        elif '\xa9alb' in track and track['\xa9alb'] != "":
            return track['\xa9alb']
        else:
            log.debug("No title found. Returning empty string")
            return ""

    else:
        log.error("Track is not detected as MP3, MP4, or M4A/B. Unable to get title")
        return ""


def getAuthor(track):
    log.debug("Extracting author from track")

    if isinstance(track, mp3.EasyMP3) or isinstance(track, easymp4.EasyMP4):
        if 'artist' in track and track['artist'] != '':
            return track['artist'][0]
        elif 'composer' in track and track['composer'] != "":
            return track['composer'][0]
        elif 'albumartist' in track and track['albumartist'] != "":
            return track['albumartist'][0]
        elif 'lyricist' in track and track['lyricist'] != "":
            return track['lyricist'][0]
        else:
            log.debug("No author found. Returning empty string")
            return ""
    elif isinstance(track, mp3.MP3):
        if 'TPE1' in track and track['TPE1'] != "":
            return track['TPE1']
        elif 'TCOM' in track and track['TCOM'] != "":
            return track['TCOM']
        elif 'TPE2' in track and track['TPE2'] != "":
            return track['TPE2']
        elif 'TEXT' in track and track['TEXT'] != "":
            return track['TEXT']
        else:
            log.debug("No author found. Returning empty string")
            return ""
    elif isinstance(track, mp4.MP4):
        if '\xa9ART' in track and track['\xa9ART'] != "":
            return track['\xa9ART']
        elif 'soco' in track and track['soco'] != "":
            return track['soco']
        elif 'aART' in track and track['aART'] != "":
            return track['aART']
        else:
            log.debug("No author found. Returning empty string")
            return ""
    else:
        log.error("Track is not detected as MP3, MP4, or M4A/B. Unable to get author")
        return ""
    
    

def GETpage(url, md):
    log.info("GET page: " + url)
    timer = 2
    while True:
        try:
            page = requests.get(url)
            break
        except Exception as e:
            if timer == 2:
                #loading
                time.sleep(timer)
                timer *= 1.5
            elif timer >= 10:
                md.failed = True
                break

    if md.failed:
        log.error("metadata shows failed, aborting GET")
        return page
    
    if page.status_code != requests.codes.ok:
        log.error("Status code not OK, aborting GET")
        md.failed = True
        return page
    
    try:
        page.raise_for_status()
        return page
    except Exception as e:
        log.error("Raise for status failed, aborting GET")
        md.failed = True
        return page
    

def parseAudibleMd(info, md):
    log.debug("Parsing audible metadata")
    try:
        # authors = info['authors'] #TODO multiple authors work
        # if len(authors) == 2:   #2 because the first element is ASIN
        #     md.author = authors[0]['name']
        # elif len(authors) > 2:  #Does this work?
        #     temp = []
        #     for a in authors:
        #         temp.append(n['name'])

        #     md.authors = temp
        # else:
        #     log.debug("No authors found in audible JSON")
        #     pass

        md.author = info['authors'][0]['name']
    except Exception as e:
        log.debug("Exeption parsing author in audible JSON")

    try:
        md.title = info['title']
    except Exception as e:
        log.debug("Exeption parsing title in audible JSON")


    try:
        rawSummary = BeautifulSoup(info['publisher_summary'], 'html.parser')
        md.summary = rawSummary.getText()
    except Exception as e:
        log.debug("Exeption parsing summary in audible JSON")


    try:
        md.subtitle = info['subtitle']
    except Exception as e:
        log.debug("Exeption parsing subtitle in audible JSON")


    try:
        # narrators = info['narrators'] #TODO multiple narrators
        # if len(narrators) == 2:
        #     md.narrator = narrators[0]['name']
        # elif len(narrators) > 2:
        #     temp = []
        #     for n in narrators:
        #         temp.append(n['name'])

        #     md.narrators = temp
        # else:
        #     log.debug("No narrator found in audible JSON")

        md.narrator = info['narrators'][0]['name']

    except Exception as e:
        log.debug("Exeption parsing narrator in audible JSON")


    try:
        md.publisher = info['publisher_name']
    except Exception as e:
        log.debug("Exeption parsing publisher in audible JSON")


    try:
        md.publishYear = info['release_date'][:4]
    except Exception as e:
        log.debug("Exeption parsing release year in audible JSON")


    try:
        md.genres = []  #TODO he commented this out, couldn't get it to work?
    except Exception as e:
        log.debug("Exeption parsing genres in audible JSON")


    try:
        # series = info['series']
        # if len(series) == 1:
        #     md.series = series[0]
        # elif len(series) > 1:
        #     md.seriesMulti = series
        # else:
        #     #TODO exception
        #     pass

        # md.series = info('publication_name')    #TODO test this with several books to make sure I've understood what it is

        md.series = info['series'][0]['title']
    except Exception as e:
        log.debug("Exeption parsing series in audible JSON")


    try:
        md.volumeNumber = info['series'][0]['sequence']
    except Exception as e:
        log.debug("Exeption parsing volume number in audible JSON")


def parseGoodreadsMd(soup, md):
    log.debug("Parsing goodreads metadata")
    try:
        md.title = soup.find('h1', class_="Text Text__title1").text.strip()
    except Exception as e:
        log.debug("Exeption parsing title from goodreads")


    try:
        md.author = soup.find('span', class_="ContributorLink__name").text.strip()
    except Exception as e:
        log.debug("Exeption parsing author from goodreads")


    try:    #TODO author multi
        # md. = soup.find('a', ).text.strip()
        pass
    except Exception as e:
        #TODO ERROR
        pass

    try:    #if multiple classes, use wrapper div instead
        md.summary = soup.find('span', class_="Formatted").text.strip()
    except Exception as e:
        log.debug("Exeption parsing summary from goodreads")


    # try:
    #     # temp = soup.find('div', class_="TruncatedContent__text TruncatedContent__text--small").text.strip()
    #     # byIndex = temp.find(" by ")
    #     # md.publisher = temp[byIndex + 4 :]

    #     temp = soup.find("dt", text="Published").find_sibling("div", attrs={"data-testid" : 'contentContainer'})
    #     pass
    # except Exception as e:
    #     log.debug("Exeption parsing publisher from goodreads")


    # try:
    #     temp = soup.find('div', class_="TruncatedContent__text TruncatedContent__text--small").text.strip()
    #     byIndex = temp.find(" by ")
    #     md.publishYear = temp[byIndex - 4 : byIndex]
    # except Exception as e:
    #     log.debug("Exeption parsing release year from goodreads")


    # try:    #TODO
    #     md.genres = soup.find().text.strip()
    # except Exception as e:
    #     log.debug("Exeption parsing genre from goodreads")


    # try:
    #     temp = soup.find('h3', class_="Text Text__title3 Text__italic Text__regular Text__subdued").text.strip()
    #     md.series = temp[ : temp.find('#')]
    # except Exception as e:
    #     log.debug("Exeption parsing series from goodreads")
        
    try:
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.series = temp[ : temp.find('#') - 1]
    except Exception as e:
        log.debug("Exeption parsing series from goodreads")


    # try:    #TODO
    #     temp = soup.find('h3', class_="Text Text__title3 Text__italic Text__regular Text__subdued").text.strip()
    #     md.volumeNumber = temp[ : temp.find('#')]
    # except Exception as e:
    #     log.debug("Exeption parsing volume number from goodreads")

    try:    #TODO
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.volumeNumber = temp[temp.find('#') + 1: ]
        pass
    except Exception as e:
        log.debug("Exeption parsing volume number from goodreads")


def fetchMetadata(file, track) -> Metadata:
    log.info("Fetching metadata")
    md = Metadata()
    md.title = getTitle(track)
    md.author = getAuthor(track)

    if md.title != "" and md.author != "":
        searchText = md.title + " - " + md.author
    elif md.title != "":
        searchText = md.title
    elif md.author != "":
        searchText = md.author
    else:
        searchText = file.name

    oldClipboard = pyperclip.paste()
    if any(sub in oldClipboard for sub in ["goodreads.com", "audible.com"]):
        pyperclip.copy("Ultimate Audiobooks")

    searchURL = ""
    #It's not possible for fetch to be anything other than these, as the argparser would throw an error
    if settings.fetch == "audible":
        searchURL = f"https://duckduckgo.com/?t=ffab&q=site:audible.com/pd/ {searchText}"
    elif settings.fetch == "goodreads":
        searchURL = f"https://duckduckgo.com/?t=ffab&q=site:goodreads.com {searchText}"
    elif settings.fetch == "both":
        searchURL = f"https://duckduckgo.com/?t=ffab&q=audible.com/pd/ goodreads.com {searchText}"

    #some linux OSs don't play nice with webbrowser.open (cries in KDE Neon)
    if platform.system() == "Windows" or platform.system() == "Darwin":
        webbrowser.open(searchURL, new = 2)
    else:
        webbrowser.get('firefox').open(searchURL, new = 2)


        #TODO see if you can get one of these to work, for the nice distros
        # openedTab = webbrowser.open(searchURL, new = 2)
        # if not openedTab:
        #     webbrowser.get('firefox').open(searchURL, new = 2)

        # try:
        #     webbrowser.open(searchURL, new = 2)
        # except:
        #     # subprocess.run(['xdg-open', searchURL], check=True)
        #     webbrowser.get('firefox').open(searchURL, new = 2)


    tempClipboard = pyperclip.paste()
    log.info("Waiting for URL")
    while True:
        time.sleep(1)
        currClipboard = pyperclip.paste()

        # TODO catch exceptions for bad http responses (404, etc) and skip. also, try to tweak audible podcast links?
        if currClipboard == tempClipboard:
            continue
        elif currClipboard.upper() == "SKIP":
            log.info("Detected skip, skipping book")
            md.skip = True
            break
        elif "audible.com" in currClipboard:
            log.debug("Audible URL captured: " + currClipboard)
            asin = currClipboard[currClipboard.find("Audiobook/") + len("Audiobook/"):]
            md.asin = asin
            paramRequest = "?response_groups=contributors,product_attrs,product_desc,product_extended_attrs,series"
            targetUrl = f"https://api.audible.com/1.0/catalog/products/{md.asin}" + paramRequest
            page = GETpage(targetUrl, md)
            info = page.json()['product']
            parseAudibleMd(info, md)
            break

        elif "goodreads.com" in currClipboard:
            log.debug("Goodreads URL captured: " + currClipboard)
            page = GETpage(currClipboard, md)
            soup = BeautifulSoup(page.text, 'html.parser')
            parseGoodreadsMd(soup, md)
            break

    return md



def getAudioFiles(folderPath, batch = -1, recurse = False):
    files = []

    if recurse:
        files.extend(list(folderPath.rglob("*.m4*")))  #.m4a, .m4b
        files.extend(list(folderPath.rglob("*.mp*")))  #.mp3, .mp4
        files.extend(list(folderPath.rglob("*.flac")))  #flac
        files.extend(list(folderPath.rglob("*.wma")))  #wma
        files.extend(list(folderPath.rglob("*.wav")))  #wav
    else:
        files.extend(list(folderPath.glob("*.m4*")))  #.m4a, .m4b
        files.extend(list(folderPath.glob("*.mp*")))  #.mp3, .mp4
        files.extend(list(folderPath.glob("*.flac")))  #flac
        files.extend(list(folderPath.glob("*.wma")))  #wma
        files.extend(list(folderPath.glob("*.wav")))  #wav

    if batch == -1 or len(files) < batch:
        return files
    elif len(files) == 0:
        return -1
    else:
        return files[:batch]


def convertToM4B(file, type, md, settings): #This is run parallel through ProcessPoolExecutor, which limits access to globals
    #When copying we create the new file in destination, otherwise the new file will be copied and there will be an extra original
    #When moving we convert in place and allow the move to be handled in EOF processing
    log.info("Converting " + file.name + " to M4B")

    #apparently ffmpeg can't process special characters on input, but has no problem outputting them? So setting newPath with specials here works just fine.
    if md.title:
        newPath = Path(md.bookPath + "/" + md.title + ".mp4")   #TODO temp change to title while working on rename
    else:
        newPath = Path(md.bookPath + "/" + file.stem + ".mp4")   #TODO temp change to title while working on rename

    #TODO get unique path won't serve here because the file extension is going to change?
    newPath = getUniquePath(file.name, newPath.parent)

    if settings.move:
        file = sanitizeFile(file)
    else:
        folder, filename = os.path.split(file)
        copyFile = shutil.copy(file, os.path.join(folder, f"COPY{filename}"))
        file = sanitizeFile(copyFile)

    cmd = ['ffmpeg',
           '-i', file,  #input file
           '-codec', 'copy', #copy audio streams instead of re-encoding
           '-vn',   #disable video
           # '-hide_banner', #suppress verbose progress output. Changes to the log level may make this redundant.
           # '-loglevel', 'error',
           '-loglevel', 'warning',
           '-stats',    #adds back the progress bar loglevel hides
           newPath]
    
    
    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)

            file.unlink() #if not settings.move, a copy is created which this deletes. Nondestructive.
            return newPath.rename(newPath.with_suffix('.m4b'))

        except subprocess.CalledProcessError as e:
            log.error(f"Conversion failed! Aborting file...")
            md.failed = True
            return file

    elif type == '.mp4':
        log.debug("Converting MP4 to M4B")
        return file.rename(newPath.with_suffix('.m4b')) #if not settings.move, a copy is created which this moves. Nondestructive.


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
        track['discnumber'] = int(md.volumeNumber)
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
            track['discnumber'] = [md.volumeNumber]

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
            



def getUniquePath(fileName, outpath):
    counter = 1
    #TODO temp change while working on rename
    # ogPath = outpath + "/" + book.name
    # ogPath = outpath + "/" + fileName
    # ogPath = outpath / fileName
    # currPath = ogPath
    currPath = Path(outpath) / fileName
    while os.path.exists(currPath):
        currPath = currPath + " - " + str(counter)  #TODO Pretty sure this addition is broken
        counter += 1

    return currPath


def calculateWorkerCount():
    log.debug("Finding worker count")
    numCores = os.cpu_count()
    availableMemory = psutil.virtual_memory().available / (1024 ** 3)   #converts to Gb

    return numCores / 2 if numCores / 2 < availableMemory - 2 else availableMemory - 2

def sanitizeFile(file):
    log.debug("Sanitize in - " + file.name)
    file = Path(file)
    name = file.name
    parent = str(file.parent)

    #The users dirs are checked at init, so it should be safe to affect any with a special char at this point
    subs = {
        "&": "and"
    }

    for og, new in subs.items():
        name = name.replace(og, new)

    name = re.sub(r'[<>"|?’*\']', '', name)
    # name = re.sub(r'[^\x00-\x7F]+', '', name) #non-ASCII characters, in case they end up being trouble

    newParent = re.sub(r'[<>"|?’*\']', '', parent)
    Path(newParent).mkdir(parents = True, exist_ok = True)

    newPath = Path(newParent) / name

    if file == newPath:
        log.debug("Sanitize out - no changes")
        return file

    else:
        log.debug("Sanitize out - " + newPath.name)
        return file.rename(newPath)

