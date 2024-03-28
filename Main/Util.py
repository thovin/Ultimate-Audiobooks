from Settings import settings
from pathlib import Path
from itertools import islice
import mutagen
from mutagen import id3, easyid3, mp3, mp4
import webbrowser
import pyperclip
import time
import requests
from bs4 import BeautifulSoup

class Metadata{
    author = ""
    authors = []
    title = ""
    summary = ""
    subtitle = ""
    narrator = ""
    narrators = []
    publisher = ""
    publishYear = ""
    genres = []
    isbn = ""
    asin = ""
    series = ""
    seriesMulti = []
    volumeNumber = ""   #TODO rename?
    skip = False
    failed = False
    inFolder = None
    inFile = None
}

def GETpage(url, md):
    #md is passed by reference, so no need to return
    timer = 2
    while True:
        try:
            page = requests.get(url)
        except Exception as e:
            if timer == 2:
                #loading
                time.sleep(timer)
                timer *= 1.5
            elif timer >= 10:
                md.failed = True
                break

    if md.failed:
        return page
    
    if page.status_code != requests.codes.ok:
        md.failed = True
        return page
    
    try:
        page.raise_for_status()
        return page
    except Exception as e:
        md.failed = True
        return page
    

def parseAudibleMd(info, md):
    try:
        authors = info['authors']
        if len(authors) == 1:
            md.author = authors[0]
        elif len(authors) > 1:
            md.authors = authors
        else:
            #TODO ERROR
            pass
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.title = info['title']
    except Exception as e:
        #TODO ERROR
        pass

    try:
        rawSummary = BeautifulSoup(info['publisher_summary'], 'html.parser')    #TODO is this parser somthing I'm supposed to have or part of the soup?
        md.summary = rawSummary.getText()
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.subtitle = info['subtitle']
    except Exception as e:
        #TODO ERROR
        pass

    try:
        narrators = info['narrotors']   #I know it's misspelled, it came this way. It's either a bug or a british thing.
        if len(narrators) == 1:
            md.narrator = narrators[0]['name']
        elif len(narrators) > 1:
            temp = []
            for n in narrators:
                temp.append(n['name'])

            md.narrators = temp
        else:
            #TODO ERROR
            pass
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.publisher = info['publisher_name']
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.publishYear = 0000   #TODO he uses regex to parse, find my solution
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.genres = []  #TODO he commented this out, couldn't get it to work?
    except Exception as e:
        #TODO ERROR
        pass

    try:
        series = info['series']
        if len(series) == 1:
            md.series = series[0]
        elif len(series) > 1:
            md.seriesMulti = series
        else:
            #TODO exception
            pass
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.volumeNumber = info['series'][0]['sequence']
    except Exception as e:
        #TODO ERROR
        pass


def parseGoodreadsMd(soup, md):

    try:
        md.title = soup.find('h1', class="Text Text__title1").text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:
        md.author = soup.find('span', class="ContributorLink__name").text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO author multi
        md. = soup.find('a', ).text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #if multiple classes, use wrapper div instead
        md.summary = soup.find('span', class="Formatted").text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO
        md.publisher = soup.find().text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO
        md.publishYear = soup.find().text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO
        md.genres = soup.find().text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO
        md.series = soup.find().text.strip()
    except Exception as e:
        #TODO ERROR
        pass

    try:    #TODO
        md.volumeNumber = soup.find().text.strip()
    except Exception as e:
        #TODO ERROR
        pass




            



def fetchMetadata(file, track) -> Metadata:
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

    if settings.fetch == "Audible":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:audible.com/pd/ {searchText}", new = 2)
    elif settings.fetch == "Goodreads":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=site:goodreads.com {searchText}", new=2)
    elif settings.fetch == "Both":
        webbrowser.open(f"https://duckduckgo.com/?t=ffab&q=audible.com/pd/ goodreads.com {searchText}", new=2)
    else:
        #TODO ERROR
        pass

    oldClipboard = pyperclip.paste()
    if ["goodreads.com", "audible.com"] in oldClipboard:    #TODO right strings?
        pyperclip.copy("Ultimate Audiobooks")

    while True:
        time.sleep(1)
        currClipboard = pyperclip.paste()

        if currClipboard == oldClipboard:
            continue
        elif currClipboard.upper() == "SKIP":
            md.skip = True
            #TODO skip logic
            break
        elif "audible.com" in currClipboard:    #TODO does this work?
            page = GETpage(currClipboard, md)
            info = page.json()['product']
            parseAudibleMd(info, md)

        elif "goodreads.com" in currClipboard:  #TODO does this work?
            page = GETpage(currClipboard, md)
            soup = BeautifulSoup(page.text, 'html.parser')
            parseGoodreadsMd(soup, md)





def getTitle(track):
    # TODO correct syntax?

    if isinstance(track, EasyID3):
        if track['title'] != "":
            return track['title']
        elif track['album'] != "":
            return track['album']
        else:
            return False
    elif isinstance(track, MP4):
        if track.tag['\xa9nam'] != "":
            return track.tags['\xa9nam']
        elif track.tags['\xa9alb'] != "":
            return track.tags['\xa9alb']
        else:
            return ""