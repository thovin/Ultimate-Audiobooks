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
import json

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

    try: #authors (multiple supported)
        md.authors = []
        authors_raw = info.get('authors', [])
        if isinstance(authors_raw, list) and len(authors_raw) > 0:
            for author in authors_raw:
                name = None
                if isinstance(author, dict):
                    name = author.get('name') or author.get('display_name')
                elif isinstance(author, str):
                    name = author
                if name:
                    md.authors.append(name)
            if len(md.authors) > 0:
                md.author = md.authors[0]
        else:
            log.debug("No authors found in audible JSON")
    except Exception as e:
        log.debug("Exeption parsing author in audible JSON")

    try: #title
        md.title = info['title']
    except Exception as e:
        log.debug("Exeption parsing title in audible JSON")


    try: #summary
        rawSummary = BeautifulSoup(info['publisher_summary'], 'html.parser')
        md.summary = rawSummary.getText()
    except Exception as e:
        log.debug("Exeption parsing summary in audible JSON")


    try: #subtitle
        md.subtitle = info['subtitle']
    except Exception as e:
        log.debug("Exeption parsing subtitle in audible JSON")


    try: #narrators
        if len(info['narrators']) == 0:
            log.debug("No narrators found")
        else:
            md.narrator = info['narrators'][0]['name']

            for n in info['narrators']:
                md.narrators.append(n['name'])

        md.narrator = info['narrators'][0]['name']

    except Exception as e:
        log.debug("Exeption parsing narrator in audible JSON")


    try: #publisher
        md.publisher = info['publisher_name']
    except Exception as e:
        log.debug("Exeption parsing publisher in audible JSON")


    try: #publish year
        md.publishYear = info['release_date'][:4]
    except Exception as e:
        log.debug("Exeption parsing release year in audible JSON")


    try: #genres (multiple supported)
        genres: list[str] = []
        # Common fields where genres may appear in Audible product JSON
        # 1) thesaurus_subject_keywords: ["Fantasy", "Epic" ...]
        tsk = info.get('thesaurus_subject_keywords')
        if isinstance(tsk, list):
            genres.extend([g for g in tsk if isinstance(g, str) and g])

        # 2) genres: can be ["Fantasy", ...] or [{"name": "Fantasy"}, ...]
        if not genres and 'genres' in info:
            g = info.get('genres')
            if isinstance(g, list):
                for item in g:
                    if isinstance(item, str) and item:
                        genres.append(item)
                    elif isinstance(item, dict):
                        name = item.get('name') or item.get('title') or item.get('display_name')
                        if name:
                            genres.append(name)

        # 3) category_ladders: [[{"name": "Fiction"}, {"name": "Fantasy"}], ...]
        if not genres and 'category_ladders' in info:
            ladders = info.get('category_ladders')
            if isinstance(ladders, list):
                for ladder in ladders:
                    if isinstance(ladder, list):
                        for node in ladder:
                            if isinstance(node, dict):
                                name = node.get('name') or node.get('display_name')
                                if name:
                                    genres.append(name)

        # Deduplicate while preserving order
        seen = set()
        unique_genres = []
        for g in genres:
            if g not in seen:
                seen.add(g)
                unique_genres.append(g)
        md.genres = unique_genres
    except Exception as e:
        log.debug("Exeption parsing genres in audible JSON")


    try: #series
        md.series = info['series'][0]['title']
    except Exception as e:
        log.debug("Exeption parsing series in audible JSON")


    try: #volume num
        md.volumeNumber = info['series'][0]['sequence']
    except Exception as e:
        log.debug("Exeption parsing volume number in audible JSON")

    try: #asin
        md.asin = info['asin']
    except Exception as e:
        log.debug("Exeption parsing ASIN in audible JSON")

    


def parseGoodreadsMd(soup, md):
    log.debug("Parsing goodreads metadata")
    try:
        md.title = soup.find('h1', class_="Text Text__title1").text.strip()
    except Exception as e:
        log.debug("Exeption parsing title from goodreads")

    # Authors (multiple)
    try:
        md.authors = []
        author_spans = soup.find_all('span', class_="ContributorLink__name")
        for span in author_spans:
            name = span.get_text(strip=True)
            if name:
                md.authors.append(name)
        if len(md.authors) > 0:
            md.author = md.authors[0]
        else:
            # Fallback: try older structure
            a_links = soup.select('a.ContributorLink__name, a.authorName')
            for a in a_links:
                name = a.get_text(strip=True)
                if name:
                    md.authors.append(name)
            if len(md.authors) > 0:
                md.author = md.authors[0]
    except Exception as e:
        log.debug("Exeption parsing authors from goodreads")

    try:    #if multiple classes, use wrapper div instead
        md.summary = soup.find('span', class_="Formatted").text.strip()
    except Exception as e:
        log.debug("Exeption parsing summary from goodreads")
    
    # Publisher, Publish Year, ISBN
    try:
        details_section = soup.select_one('[data-testid="bookDetails"]') or soup.find('div', id='bookDataBox')
        details_text = details_section.get_text(" ", strip=True) if details_section else soup.get_text(" ", strip=True)

        # Publish year (First published ... YYYY) or (Published ... YYYY)
        m_year = re.search(r'(?:First\s+published|Published)[^\d]*(\d{4})', details_text, re.IGNORECASE)
        if m_year:
            md.publishYear = m_year.group(1)

        # Publisher (after 'by ')
        m_pub = re.search(r'Published.*?by\s+([^\d,]+)', details_text, re.IGNORECASE)
        if m_pub:
            md.publisher = m_pub.group(1).strip()

        # ISBN (10 or 13, possibly with hyphens)
        m_isbn = re.search(r'ISBN(?:-13)?:?\s*([0-9Xx\-]{10,17})', details_text)
        if m_isbn:
            candidate = m_isbn.group(1).replace('-', '').strip()
            if 10 <= len(candidate) <= 13:
                md.isbn = candidate
    except Exception as e:
        log.debug("Exeption parsing publisher/publish year/ISBN from goodreads")


    # Genres (multiple)
    try:
        genres: list[str] = []
        # New Goodreads layout often lists genres as tag buttons
        # Strategy 1: look for data-testid containers and anchors
        containers = soup.select('[data-testid="genresList"], [data-testid="bookMeta"]')
        for cont in containers:
            for a in cont.find_all('a'):
                text = a.get_text(strip=True)
                if text and len(text) < 60:  # avoid long non-genre texts
                    genres.append(text)
        # Strategy 2: look for tag buttons
        if not genres:
            for a in soup.select('a.Button--tag, a.ActionLink--genre, a[href*="/genres/"]'):
                text = a.get_text(strip=True)
                if text:
                    genres.append(text)
        # Deduplicate while preserving order
        seen = set()
        unique_genres = []
        for g in genres:
            if g not in seen:
                seen.add(g)
                unique_genres.append(g)
        md.genres = unique_genres
    except Exception as e:
        log.debug("Exeption parsing genres from goodreads")


        
    try:
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.series = temp[ : temp.find('#') - 1]
    except Exception as e:
        log.debug("Exeption parsing series from goodreads")


    try:
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.volumeNumber = temp[temp.find('#') + 1: ]
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

    # Robustly open the search URL in the user's default browser, with fallbacks for all major OSes.
    def open_url_cross_platform(url):
        try:
            system = platform.system()
            # On Linux, prefer xdg-open in a fully detached subprocess FIRST to ensure persistence
            if system == "Linux":
                try:
                    log.debug("Linux detected; launching via xdg-open (detached)")
                    subprocess.Popen(
                        ['xdg-open', url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
                except Exception:
                    log.debug("xdg-open failed; attempting Python webbrowser as fallback")
                    try:
                        if webbrowser.open(url, new=2):
                            return
                    except Exception:
                        pass

                log.debug("Default browser open failed; attempting additional platform-specific fallbacks")
                # As a last resort on Linux, try known controllers (still may be tied to parent)
                for browser in ['firefox', 'google-chrome', 'chromium', 'brave-browser']:
                    try:
                        webbrowser.get(browser).open(url, new=2)
                        return
                    except Exception:
                        continue

                log.error("Could not open a web browser. Please open this URL manually: " + url)
                return

            # Non-Linux platforms
            # 1) Honor $BROWSER if set
            browser_env = os.environ.get('BROWSER')
            if browser_env:
                try:
                    log.debug(f"Using BROWSER controller: {browser_env}")
                    webbrowser.get(browser_env).open(url, new=2)
                    return
                except Exception:
                    pass

            # 2) Use Python's default (respects system defaults)
            try:
                if webbrowser.open(url, new=2):
                    log.debug("Opened URL via Python webbrowser default")
                    return
            except Exception:
                pass

            # 3) Minimal platform-specific fallbacks
            log.debug("Default browser open failed; attempting platform-specific fallback")
            
            if system == "Windows":
                try:
                    os.startfile(url)  # type: ignore[attr-defined]
                    return
                except Exception:
                    pass
            elif system == "Darwin":
                try:
                    subprocess.Popen(['open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    return
                except Exception:
                    pass
            log.error("Could not open a web browser. Please open this URL manually: " + url)
        except Exception as e:
            log.error(f"Failed to open browser: {e}. Please open this URL manually: {url}")

    open_url_cross_platform(searchURL)


    tempClipboard = pyperclip.paste()
    log.info("Waiting for URL...")
    while True:
        time.sleep(1)
        currClipboard = pyperclip.paste()

        if currClipboard == tempClipboard:
            continue
        elif currClipboard.upper() == "SKIP":
            log.info("Detected skip, skipping book")
            md.skip = True
            break
        elif "audible.com" in currClipboard:
            log.debug("Audible URL captured: " + currClipboard)
            # Robustly extract ASIN from path or query, ignoring extra query params
            try:
                parsed = urllib.parse.urlparse(currClipboard.strip())
                path_parts = [p for p in parsed.path.split('/') if p]
                asin_match = None
                # Search path segments from the end for a valid ASIN (10-char starting with 'B')
                for part in reversed(path_parts):
                    m = re.match(r'^[0-9A-Z]{10}$', part, re.IGNORECASE)
                    if m:
                        asin_match = m.group(0).upper()
                        break
                # Fallback to query parameter 'asin' if present
                if not asin_match:
                    qs = urllib.parse.parse_qs(parsed.query)
                    candidate = qs.get('asin', [None])[0]
                    if candidate and re.match(r'^[0-9A-Z]{10}$', candidate, re.IGNORECASE):
                        asin_match = candidate.upper()
                if not asin_match:
                    log.error("Unable to extract ASIN from Audible URL. Please copy a book page link and try again, or copy 'skip' to skip this book.")
                    pyperclip.copy("Ultimate Audiobooks")
                    md.failed = False
                    log.info("Waiting for URL...")
                    continue
                md.asin = asin_match
            except Exception:
                log.exception("Error parsing Audible URL")
                pyperclip.copy("Ultimate Audiobooks")
                md.failed = False
                log.info("Waiting for URL...")
                continue

            paramRequest = "?response_groups=contributors,product_attrs,product_desc,product_extended_attrs,series"
            targetUrl = f"https://api.audible.com/1.0/catalog/products/{md.asin}" + paramRequest
            page = GETpage(targetUrl, md)
            if md.failed or not getattr(page, "ok", False):
                log.error("Audible API request failed. Please copy a valid book page link, or copy 'skip' to skip.")
                pyperclip.copy("Ultimate Audiobooks")
                md.failed = False
                log.info("Waiting for URL...")
                continue

            try:
                data = page.json()
                product = data.get('product')
                if not product:
                    raise KeyError("No 'product' in response")
                parseAudibleMd(product, md)

                if not md.title or not md.author:
                    log.error("Audible link did not yield both title and author. Please copy a valid book page link, or copy 'skip' to skip.")
                    pyperclip.copy("Ultimate Audiobooks")
                    md.failed = False
                    log.info("Waiting for URL...")
                    continue
                break
            except (json.JSONDecodeError, KeyError):
                log.error("Error reading Audible API. Perhaps this is a series/podcast or invalid link? Copy a book page link, or 'skip'.")
                pyperclip.copy("Ultimate Audiobooks")
                md.failed = False
                log.info("Waiting for URL...")
                continue



        elif "goodreads.com" in currClipboard:
            log.debug("Goodreads URL captured: " + currClipboard)
            page = GETpage(currClipboard, md)
            soup = BeautifulSoup(page.text, 'html.parser')
            parseGoodreadsMd(soup, md)
            # Safety net: ensure required fields present
            if not md.title or not md.author:
                log.error("Goodreads link did not yield both title and author. Please copy a valid book page link, or copy 'skip' to skip.")
                pyperclip.copy("Ultimate Audiobooks")
                md.failed = False
                log.info("Waiting for URL...")
                continue
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
        # newPath = Path(md.bookPath + "/" + md.title + ".mp4")   #TODO (rename) temp change to title while working on rename
        newPath = Path(md.bookPath + "/" + re.sub(r'[<>"|?’:,*\']', '', md.title) + ".mp4")   #TODO (rename) temp change to title while working on rename
    else:
        # newPath = Path(md.bookPath + "/" + file.stem + ".mp4")   #TODO (rename) temp change to title while working on rename
        newPath = Path(md.bookPath + "/" + re.sub(r'[<>"|?’:,*\']', '', file.stem) + ".mp4")   #TODO (rename) temp change to title while working on rename

    tempPath = newPath
    newPath = getUniquePath(newPath.with_suffix(".m4b").name, newPath.parent)

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
           tempPath]
    
    
    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)

            file.unlink() #if not settings.move, a copy is created which this deletes. Nondestructive.
            return tempPath.rename(newPath)

        except subprocess.CalledProcessError as e:
            log.error(f"Conversion failed! Aborting file...")
            md.failed = True
            return file

    elif type == '.mp4':
        log.debug("Converting MP4 to M4B")
        return file.rename(newPath.with_suffix('.m4b')) #if not settings.move, a copy is created which this moves. Nondestructive.


def cleanMetadata(track, md): #TODO add multiple authors and narrators
    log.info("Cleaning file metadata")
    if isinstance(track, mp3.EasyMP3):
        log.debug("Cleaning easymp3 metadata")

        track.delete()
        track['title'] = md.title
        track['artist'] = md.narrator
        track['album'] = md.series
        track['date'] = md.publishYear
        track['discnumber'] = int(md.volumeNumber)
        # Authors (support multiple if available)
        try:
            # Support custom 'author' EasyID3 key if available
            if hasattr(md, 'authors') and md.authors:
                track['author'] = md.authors
            else:
                track['author'] = md.author
        except Exception:
            # Fallback to composer for author if custom key unsupported
            if hasattr(md, 'authors') and md.authors:
                track['composer'] = md.authors
            else:
                track['composer'] = md.author
        # Genres (support multiple)
        try:
            if hasattr(md, 'genres') and md.genres:
                track['genre'] = md.genres
        except Exception:
            pass
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

        track.delete()
        track['title'] = md.title
        track['narrator'] = md.narrator
        track['date'] = md.publishYear
        track['description'] = md.summary
        # Authors (support multiple)
        if hasattr(md, 'authors') and md.authors:
            track['author'] = md.authors
        else:
            track['author'] = md.author
        # Genres (support multiple)
        if hasattr(md, 'genres') and md.genres:
            track['genre'] = md.genres
        track['publisher'] = md.publisher
        track['isbn'] = md.isbn
        track['asin'] = md.asin
        track['series'] = md.series

        # if md.volumeNumber != "":   #TODO. disnumber seems misleading, even though a lot of people use it this way. Some use a custom key for series-part or series_index.
        #     track['discnumber'] = [md.volumeNumber]

    elif isinstance(track, mp3.MP3):
        log.debug("Cleaning mp3 metadata")

        track.delete()
        track.add(mutagen.TIT2(encoding = 3, text = md.title))
        track.add(mutagen.TPE1(encoding = 3, text = md.narrator))
        track.add(mutagen.TALB(encoding = 3, text = md.series))
        track.add(mutagen.TYER(encoding = 3, text = md.publishYear))
        track.add(mutagen.TPOS(encoding = 3, text = md.volumeNumber))
        # Authors (ID3 TCOM) supports multiple
        if hasattr(md, 'authors') and md.authors:
            track.add(mutagen.TCOM(encoding = 3, text = md.authors))
        else:
            track.add(mutagen.TCOM(encoding = 3, text = md.author))
        # Genres (ID3 TCON) supports multiple values
        if hasattr(md, 'genres') and md.genres:
            track.add(mutagen.TCON(encoding = 3, text = md.genres))
        track.add(mutagen.TPUB(encoding = 3, text = md.publisher))
        track.add(mutagen.TXXX(encoding = 3, desc='description', text = md.summary))
        track.add(mutagen.TXXX(encoding = 3, desc='subtitle', text = md.subtitle))
        track.add(mutagen.TXXX(encoding = 3, desc='isbn', text = md.isbn))
        track.add(mutagen.TXXX(encoding = 3, desc='asin', text = md.asin))
        track.add(mutagen.TXXX(encoding = 3, desc='publisher', text = md.publisher))

    elif isinstance(track, mp4.MP4):
        log.debug("Cleaning mp4/m4b metadata")
        
        track['\xa9nam'] = md.title
        track['\xa9day'] = md.publishYear
        track['trkn'] = [(int(md.volumeNumber), 0)]
        # Authors (MP4) - support multiple values
        if hasattr(md, 'authors') and md.authors:
            track['\xa9aut'] = md.authors
        else:
            track['\xa9aut'] = md.author
        # Genres (MP4)
        if hasattr(md, 'genres') and md.genres:
            track['\xa9gen'] = md.genres
        track['\xa9des'] = md.summary
        track['\xa9nrt'] = md.narrator
        track['----:com.thovin:isbn'] = mutagen.mp4.MP4FreeForm(md.isbn.encode('utf-8'))
        track['----:com.thovin:asin'] = mutagen.mp4.MP4FreeForm(md.asin.encode('utf-8'))
        track['----:com.thovin:series'] = mutagen.mp4.MP4FreeForm(md.series.encode('utf-8'))

    else:
        log.error("Audio file not detected as MP3, MP4, or M4A/B. Unable to clean metadata.")
        return

    log.debug("Metadata cleaned")
    track.save()


def createOpf(md):
    log.info("Creating OPF")
    dcLink = "{http://purl.org/dc/elements/1.1/}"
    package = ET.Element("package", version="3.0", xmlns="http://www.idpf.org/2007/opf", unique_identifier="BookId")
    metadata = ET.SubElement(package, "metadata", nsmap={'dc' : dcLink})

    # Authors: write multiple creators when available; keep first as primary
    if hasattr(md, 'authors') and md.authors:
        for name in md.authors:
            a_el = ET.SubElement(metadata, f"{dcLink}creator", attrib={ET.QName(dcLink, "role"): "aut"})
            a_el.text = name
    else:
        author = ET.SubElement(metadata, f"{dcLink}creator", attrib={ET.QName(dcLink, "role"): "aut"})
        author.text = md.author

    title = ET.SubElement(metadata, f"{dcLink}title")
    title.text = md.title

    summary = ET.SubElement(metadata, f"{dcLink}description")
    summary.text = md.summary

    # Genres as dc:subject entries (multiple allowed)
    if hasattr(md, 'genres') and md.genres:
        for g in md.genres:
            subject = ET.SubElement(metadata, f"{dcLink}subject")
            subject.text = g

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
    #TODO (rename) temp change while working on rename
    type = Path(fileName).suffix
    currPath = Path(outpath) / fileName
    while os.path.exists(currPath):
        currPath = Path(outpath) / Path(str(Path(fileName).stem) + " - " + str(counter) + type)
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

    name = re.sub(r'[<>"|?’:,*\']', '', name)
    # name = re.sub(r'[^\x00-\x7F]+', '', name) #non-ASCII characters, in case they end up being trouble

    newParent = re.sub(r'[<>"|?’,*\']', '', parent) #since this is a dir path, no colons allowed
    Path(newParent).mkdir(parents = True, exist_ok = True)

    newPath = Path(newParent) / name

    if file == newPath:
        log.debug("Sanitize out - no changes")
        return file

    else:
        log.debug("Sanitize out - " + newPath.name)
        return file.rename(newPath)

