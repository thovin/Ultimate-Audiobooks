from Settings import getSettings
from pathlib import Path
from itertools import islice
import mutagen
from mutagen import id3, easyid3, easymp4, mp3, mp4
import webbrowser
import time
import requests
from bs4 import BeautifulSoup
import logging
import pyperclip

log = logging.getLogger(__name__)
settings = None

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


def getTitle(track):
    log.debug("Extracting title from track")
    # TODO correct syntax?
    #TODO what happens if they're not easy?

    if isinstance(track, mp3.EasyMP3):
        if track['title'] != "":
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
    else:
        #TODO can I extract from regular mp3/4?
        log.error("track is not easyMP3 or 4, unable to get title")
        return ""


def getAuthor(track):
    log.debug("Extracting author from track")
    # TODO correct syntax?
    #TODO what happens if they're not easy?

    if isinstance(track, mp3.EasyMP3):
        try:
            if track['artist'] != "":
                return track['artist'][0]
        except KeyError:
            pass
        try:
            if track['writer'] != "":
                return track['writer'][0]
        except KeyError:
            pass
        try:
            if track['composer'] != "":
                return track['composer'][0]
        except KeyError:
            pass
        try:
            if track['albumartist'] != "":
                return track['album artist'][0]
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
            if track['writer'] != "":
                return track['writer'][0]
        except KeyError:
            pass
        try:
            if track['composer'] != "":
                return track['composer'][0]
        except KeyError:
            pass
        try:
            if track['albumartist'] != "":
                return track['album artist'][0]
        except KeyError:
            return ""

    else:
        log.error("track is not easyMP3 or 4, unable to get author")
        return ""
    
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
    md.author = getAuthor(track) #TODO 

    if md.title != "" and md.author != "":
        searchText = md.title + " - " + md.author
    elif md.title != "":
        searchText = md.title
    elif md.author != "":
        searchText = md.author
    else:
        searchText = file.name

    oldClipboard = pyperclip.paste()
    # if ["goodreads.com", "audible.com"] in oldClipboard:    #TODO right strings?
    if any(sub in oldClipboard for sub in ["goodreads.com", "audible.com"]):
        pyperclip.copy("Ultimate Audiobooks")

    if settings.fetch == "audible":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:audible.com/pd/ {searchText}", new = 2)
    elif settings.fetch == "goodreads":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:goodreads.com {searchText}", new=2)
    elif settings.fetch == "both":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=audible.com/pd/ goodreads.com {searchText}", new=2)
    else:
        log.error("Invalid fetch argument detected")    #TODO how do I handle this fail? Just skip the book? but it woudl apply to all books. so exit program?

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





