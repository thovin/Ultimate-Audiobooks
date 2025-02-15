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
import FileMerger
import os
import psutil
import platform
import urllib.parse

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

    if isinstance(track, mp3.EasyMP3):
        if track['title'] != "":    #TODO keyerror processing foundryside. I think it doesn't actually have a title, which I didn't know was possible. Apparently filename doesn't default to title.
            return track['title'][0]
        elif track['album'] != "":
            return track['album'][0]
        else:
            return False
    elif isinstance(track, easymp4.EasyMP4):
        try:
            if track['title'] != "":
                return track['title'][0]
        except KeyError:
            pass

        try:
            if track['album'] != "":
                return track['album'][0]
            else:
                return ""
        except KeyError:
            return ""
    elif isinstance(track, mp3.MP3):
        if track['TIT2'] != "":
            return track['TIT2']
            # return track['TIT2'][0]
        elif track['TALB'] != "":
            return track['TALB']
            # return track['TALB'][0]
        else:
            return False
    elif isinstance(track, mp4.MP4):
        if track['\xa9nam'] != "":
            return track['\xa9nam']
            # return track['\xa9nam'][0]
        elif track['\xa9alb'] != "":
            return track['\xa9alb']
            # return track['\xa9alb'][0]
        else:
            return False

    else:
        log.error("Track is not detected as MP3, MP4, or M4A/B. Unable to get title")
        return ""


def getAuthor(track):
    log.debug("Extracting author from track")

    if isinstance(track, mp3.EasyMP3):
        try:
            if track['artist'] != "":
                return track['artist'][0]
        except KeyError:
            pass
        try:
            if track['composer'] != "":
                return track['composer'][0]
        except KeyError:
            pass
        try:
            if track['albumartist'] != "":
                return track['albumartist'][0]
        except KeyError:
            pass
        try:
            if track['lyricist'] != "":
                return track['lyricist'][0]
        except KeyError:
            return ""

    elif isinstance(track, easymp4.EasyMP4):
        try:
            if track['artist'] != "":
                return track['artist'][0]
        except KeyError:
            pass
        try:
            if track['composer'] != "":
                return track['composer'][0]
        except KeyError:
            pass
        try:
            if track['albumartist'] != "":
                return track['albumartist'][0]
        except KeyError:
            return ""

    elif isinstance(track, mp3.MP3): #will this throw errors like the easymp3 solution?
        if track['TPE1'] != "":
                return track['TPE1']
                # return track['TPE1'][0]
        if track['TCOM'] != "":
                return track['TCOM']
                # return track['TCOM'][0]
        if track['TPE2'] != "":
                return track['TPE2']
                # return track['TPE2'][0]
        if track['TEXT'] != "":
                return track['TEXT']
                # return track['TEXT'][0]

    elif isinstance(track, mp4.MP4): #will this throw errors like the easymp4 solution?
        if track['\xa9ART'] != "":
                return track['\xa9ART']
                # return track['\xa9ART'][0]
        if track['soco'] != "":
                return track['soco'][0]
                # return track['soco']
        if track['aART'] != "":
                return track['aART']
                # return track['aART'][0]

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
        # webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:audible.com/pd/ {searchText}", new = 2)
    elif settings.fetch == "goodreads":
        searchURL = f"https://duckduckgo.com/?t=ffab&q=site:goodreads.com {searchText}"
        # webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:goodreads.com {searchText}", new=2)
    elif settings.fetch == "both":
        searchURL = f"https://duckduckgo.com/?t=ffab&q=audible.com/pd/ goodreads.com {searchText}"
        # webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=audible.com/pd/ goodreads.com {searchText}", new=2)

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

        if currClipboard == tempClipboard:
            continue
        elif currClipboard.upper() == "SKIP":
            log.info("Detected skip, skipping book")
            md.skip = True
            #TODO skip logic
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


def loadSettings():
    global settings
    settings = getSettings()


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
    newPath = Path(md.bookPath + "/" + file.with_suffix('.mp4').name)   #TODO forward slashes ok on windows?
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
            return file.rename(newPath.with_suffix('.m4b'))
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
    if files == -1 or startPath == root:    #ignore files in the root folder
        pass
    elif len(files) == 1:
        counter += 1
        files[0].rename(outPath / f"{files[0].name}")
    elif len(files) > 1:
        counter += 1
        FileMerger.mergeBook(startPath, outPath)

    return counter

    '''
    If -M, nuke emptied folder. Ensure there are no unchecked subfolders first!
    Either way, combined files should be put into outpath

    '''

def getUniquePath(book, outpath):
    counter = 1
    ogPath = outpath + "/" + book.name  #forward slash ok on windows?
    currPath = ogPath
    while os.path.exists(currPath):
        currPath = ogPath + " - " + str(counter)
        counter += 1

    return currPath


def calculateWorkerCount():
    log.debug("Finding worker count")
    numCores = os.cpu_count()
    availableMemory = psutil.virtual_memory().available / (1024 ** 3)   #converts to Gb

    return numCores / 2 if numCores / 2 < availableMemory - 2 else availableMemory - 2