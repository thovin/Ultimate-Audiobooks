from Settings import getSettings
from pathlib import Path
import mutagen
from mutagen import easymp4, mp3, mp4, flac
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
from BookStatus import skipBook, failBook

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

class Conversion:
    #instances are pickled to ProcessPoolExecutor workers, so hold only simple values (no mutagen objects)
    def __init__(self, file, type, md):
        self.file = file
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
    elif isinstance(track, flac.FLAC):
        if 'title' in track and track['title']:
            return track['title'][0]
        elif 'album' in track and track['album']:
            return track['album'][0]
        else:
            log.debug("No title found. Returning empty string")
            return ""

    else:
        log.error("Track is not detected as MP3, MP4, M4A/B, or FLAC. Unable to get title")
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
    elif isinstance(track, flac.FLAC):
        if 'artist' in track and track['artist']:
            return track['artist'][0]
        elif 'composer' in track and track['composer']:
            return track['composer'][0]
        elif 'albumartist' in track and track['albumartist']:
            return track['albumartist'][0]
        else:
            log.debug("No author found. Returning empty string")
            return ""

    else:
        log.error("Track is not detected as MP3, MP4, M4A/B, or FLAC. Unable to get author")
        return ""
    
    

def GETpage(url):
    log.info("GET page: " + url)
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0'}
    timer = 2
    while True:
        try:
            page = requests.get(url, headers=headers, timeout=15)
            break
        except requests.RequestException as e:
            if timer >= 10:
                log.error("GET request failed repeatedly, aborting: " + str(e))
                return None
            log.debug(f"GET failed ({e}), retrying in {timer}s")
            time.sleep(timer)
            timer *= 1.5

    if page.status_code != requests.codes.ok:
        log.error("Status code not OK, aborting GET")
        return None

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
        log.debug("Exception parsing author in audible JSON")

    try: #title
        md.title = info['title']
    except Exception as e:
        log.debug("Exception parsing title in audible JSON")


    try: #summary
        rawSummary = BeautifulSoup(info['publisher_summary'], 'html.parser')
        md.summary = rawSummary.getText()
    except Exception as e:
        log.debug("Exception parsing summary in audible JSON")


    try: #subtitle
        md.subtitle = info['subtitle']
    except Exception as e:
        log.debug("Exception parsing subtitle in audible JSON")


    try: #narrators
        if len(info['narrators']) == 0:
            log.debug("No narrators found")
        else:
            md.narrator = info['narrators'][0]['name']

            for n in info['narrators']:
                md.narrators.append(n['name'])

    except Exception as e:
        log.debug("Exception parsing narrator in audible JSON")


    try: #publisher
        md.publisher = info['publisher_name']
    except Exception as e:
        log.debug("Exception parsing publisher in audible JSON")


    try: #publish year
        md.publishYear = info['release_date'][:4]
    except Exception as e:
        log.debug("Exception parsing release year in audible JSON")


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
        log.debug("Exception parsing genres in audible JSON")


    try: #series
        md.series = info['series'][0]['title']
    except Exception as e:
        log.debug("Exception parsing series in audible JSON")


    try: #volume num
        md.volumeNumber = info['series'][0]['sequence']
    except Exception as e:
        log.debug("Exception parsing volume number in audible JSON")

    try: #asin
        md.asin = info['asin']
    except Exception as e:
        log.debug("Exception parsing ASIN in audible JSON")

    


def parseGoodreadsMd(soup, md):
    log.debug("Parsing goodreads metadata")
    try:
        md.title = soup.find('h1', class_="Text Text__title1").text.strip()
    except Exception as e:
        log.debug("Exception parsing title from goodreads")

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
        log.debug("Exception parsing authors from goodreads")

    try:    #if multiple classes, use wrapper div instead
        md.summary = soup.find('span', class_="Formatted").text.strip()
    except Exception as e:
        log.debug("Exception parsing summary from goodreads")
    
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
        log.debug("Exception parsing publisher/publish year/ISBN from goodreads")


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
        log.debug("Exception parsing genres from goodreads")


        
    try:
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.series = temp[ : temp.find('#') - 1]
    except Exception as e:
        log.debug("Exception parsing series from goodreads")


    try:
        temp = soup.find("div", class_="BookPageTitleSection__title").find_next().text
        md.volumeNumber = temp[temp.find('#') + 1: ]
    except Exception as e:
        log.debug("Exception parsing volume number from goodreads")


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


#Optional override for how book URLs are obtained during fetch. A provider is a callable
#(searchText, searchURL, file) -> URL string or "SKIP". The GUI installs its own; the CLI
#defaults to watching the clipboard (ClipboardUrlProvider).
urlProvider = None

def setUrlProvider(provider):
    global urlProvider
    urlProvider = provider


class ClipboardUrlProvider:
    def __init__(self):
        self.searchOpened = False

    def __call__(self, searchText, searchURL, file):
        #reset the clipboard if it already holds a book link, so re-copying the same link registers as a change
        last = pyperclip.paste()
        if any(sub in last for sub in ("goodreads.com", "audible.com")):
            pyperclip.copy("Ultimate Audiobooks")
            last = "Ultimate Audiobooks"

        if not self.searchOpened:
            open_url_cross_platform(searchURL)
            self.searchOpened = True

        log.info("Waiting for URL (copy the book page link, or copy the word 'skip')...")
        while True:
            time.sleep(1)
            curr = pyperclip.paste()
            if curr == last:
                continue
            if curr.strip().upper() == "SKIP" or "audible.com" in curr or "goodreads.com" in curr:
                return curr
            #any other clipboard activity is ignored, same as the original behavior


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
        searchText = file.stem

    # Construct search query with parentheses around site restrictions
    if settings.fetch == "audible":
        searchQuery = f"audible.com/pd/ {searchText}"
    elif settings.fetch == "goodreads":
        searchQuery = f"goodreads.com {searchText}"
    elif settings.fetch == "both":
        searchQuery = f"(audible.com/pd/ OR goodreads.com) {searchText}"

    # URL-encode the query
    encodedQuery = urllib.parse.quote(searchQuery)

    # Use a generic search URL that browsers may route to their default search engine
    # Many browsers intercept search URLs and use their configured default search engine
    # If the browser doesn't intercept, it will still perform the search on Google
    searchURL = f"https://www.google.com/search?q={encodedQuery}"

    provider = urlProvider if urlProvider is not None else ClipboardUrlProvider()

    while True:
        candidate = provider(searchText, searchURL, file)

        if candidate is None or candidate.strip().upper() == "SKIP":
            skipBook(file, "User skipped during metadata fetch")
            return None

        candidate = candidate.strip()

        if "audible.com" in candidate:
            log.debug("Audible URL captured: " + candidate)
            # Robustly extract ASIN from path or query, ignoring extra query params
            try:
                parsed = urllib.parse.urlparse(candidate)

                # Series/author/podcast pages carry an ASIN too, and the API now returns parseable
                # JSON for them (with a title and author), so they must be rejected by URL shape.
                pathLower = parsed.path.lower()
                if any(seg in pathLower for seg in ("/series/", "/author/", "/podcast/")):
                    log.error("That looks like a series, author, or podcast page - not a book page. Please provide a specific book's page link, or skip this book.")
                    continue

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
                    qsAsin = qs.get('asin', [None])[0]
                    if qsAsin and re.match(r'^[0-9A-Z]{10}$', qsAsin, re.IGNORECASE):
                        asin_match = qsAsin.upper()
                if not asin_match:
                    log.error("Unable to extract ASIN from Audible URL. Please provide a book page link, or skip this book.")
                    continue
                md.asin = asin_match
            except Exception:
                log.exception("Error parsing Audible URL")
                continue

            paramRequest = "?response_groups=contributors,product_attrs,product_desc,product_extended_attrs,series"
            targetUrl = f"https://api.audible.com/1.0/catalog/products/{md.asin}" + paramRequest
            page = GETpage(targetUrl)
            if page is None or not getattr(page, "ok", False):
                log.error("Audible API request failed. Please provide a valid book page link, or skip this book.")
                continue

            try:
                data = page.json()
                product = data.get('product')
                if not product:
                    raise KeyError("No 'product' in response")
                parseAudibleMd(product, md)

                if not md.title or not md.author:
                    log.error("Audible link did not yield both title and author. Please provide a valid book page link, or skip this book.")
                    continue
                break
            except (json.JSONDecodeError, KeyError): #TODO this randomly started letting me copy the link for he who fights with monsters series. Did they change their API to send valid JSON for series? If so, maybe check the URL for /series instead of /p or whatever they use?
                log.error("Error reading Audible API. Perhaps this is a series/podcast or invalid link? Provide a book page link, or skip this book.")
                continue



        elif "goodreads.com" in candidate:
            log.debug("Goodreads URL captured: " + candidate)
            page = GETpage(candidate)
            if page is None:
                log.error("Goodreads page request failed. Please provide a valid book page link, or skip this book.")
                continue
            soup = BeautifulSoup(page.text, 'html.parser')
            parseGoodreadsMd(soup, md)
            # Safety net: ensure required fields present
            if not md.title or not md.author:
                log.error("Goodreads link did not yield both title and author. Please provide a valid book page link, or skip this book.")
                continue
            break

        else:
            log.error("Link not recognized as an Audible or Goodreads book page. Try again, or skip this book.")
            continue

    return md



AUDIO_EXTENSIONS = {'.m4a', '.m4b', '.mp3', '.mp4', '.flac'}  #TODO consider .wma, .wav support

def getAudioFiles(folderPath, batch = -1, recurse = False):
    globber = folderPath.rglob if recurse else folderPath.glob
    files = [f for f in globber('*') if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]

    if batch == -1 or len(files) < batch:
        return files
    else:
        return files[:batch]


def getAudioCodec(file):
    #Returns the lowercased audio codec name (e.g. 'aac', 'mp3'), or None if ffprobe fails / no audio stream found
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(file)],
            capture_output=True, text=True, check=True)
        codec = result.stdout.strip().lower()
        return codec if codec else None
    except subprocess.CalledProcessError:
        return None


def convertToM4B(file, type, md, settings): #This is run parallel through ProcessPoolExecutor, which limits access to globals
    #When copying we create the new file in destination, otherwise the new file will be copied and there will be an extra original
    #When moving we convert in place and allow the move to be handled in EOF processing
    #Returns the converted file's path, or None on failure
    file = Path(file)  # Ensure file is a Path object (may be string after ProcessPoolExecutor pickling)
    originalFile = file
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
        folder, filename = os.path.split(str(file))
        copyFile = shutil.copy(str(file), os.path.join(folder, f"COPY{filename}"))
        file = sanitizeFile(copyFile)

    cmd = ['ffmpeg',
           '-nostdin',  #never prompt on stdin (a prompt would deadlock ProcessPoolExecutor workers)
           '-y',        #overwrite leftover temp output from a previous crashed run
           '-i', str(file),  #input file (convert Path to string for subprocess)
           '-c:a', 'aac', '-q:a', '3', #transcode to AAC (MP3-in-MP4 is nonstandard; Apple's AVFoundation won't decode it)
           '-vn',   #disable video
           # '-hide_banner', #suppress verbose progress output. Changes to the log level may make this redundant.
           # '-loglevel', 'error',
           '-loglevel', 'warning',
           '-stats',    #adds back the progress bar loglevel hides
           str(tempPath)]  #convert Path to string for subprocess


    def conversionFailed():
        nonlocal file
        if not settings.move:
            #remove the working copy; the untouched original is what should be reported/moved
            file.unlink(missing_ok=True)
            file = originalFile
        failBook(file, "Conversion failed")
        return None

    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        try:
            subprocess.run(cmd, check=True)

            file.unlink() #if not settings.move, a copy is created which this deletes. Nondestructive.
            return tempPath.rename(newPath)

        except subprocess.CalledProcessError as e:
            return conversionFailed()

    elif type == '.mp4' or type == '.m4a' or type == '.m4b':
        codec = getAudioCodec(file)
        if codec in ('aac', 'alac'):
            log.debug("Moving MP4/M4A/M4B audio into M4B container")
            #already an MP4 container with Apple-compatible audio; a rename is all that's needed. shutil.move handles cross-device paths.
            return Path(shutil.move(str(file), str(newPath))) #if not settings.move, a copy is created which this moves. Nondestructive.

        log.debug(f"Transcoding non-AAC/ALAC audio ({codec}) to AAC for M4B compatibility")
        cmd_mp4 = ['ffmpeg',
                   '-nostdin',  #never prompt on stdin (a prompt would deadlock ProcessPoolExecutor workers)
                   '-y',        #overwrite leftover temp output from a previous crashed run
                   '-i', str(file),
                   '-c:a', 'aac', '-q:a', '3', #transcode to AAC (source codec isn't Apple-compatible in an MP4 container)
                   '-vn',   #disable video
                   '-hide_banner',
                   '-loglevel', 'error',
                   '-stats',
                   str(tempPath)]
        try:
            subprocess.run(cmd_mp4, check=True)
            file.unlink()
            return tempPath.rename(newPath)
        except subprocess.CalledProcessError as e:
            return conversionFailed()

    elif type == '.flac':
        log.debug("Converting FLAC to M4B")
        cmd_flac = ['ffmpeg',
                    '-nostdin',  #never prompt on stdin (a prompt would deadlock ProcessPoolExecutor workers)
                    '-y',        #overwrite leftover temp output from a previous crashed run
                    '-i', str(file),
                    '-c:a', 'aac',  #transcode to AAC (FLAC can't be stream-copied into MP4 container)
                    '-q:a', '3',  #VBR quality ~128-160kbps
                    '-vn',  #disable video
                    '-hide_banner',  #suppress version/build info header
                    '-loglevel', 'error',
                    '-stats',  #adds back the progress bar loglevel hides
                    str(tempPath)]
        try:
            subprocess.run(cmd_flac, check=True)
            file.unlink()
            return tempPath.rename(newPath)
        except subprocess.CalledProcessError as e:
            return conversionFailed()

    else:
        log.error(f"Unsupported type {type} for conversion of {file.name}")
        return conversionFailed()


def cleanMetadata(track, md):
    log.info("Cleaning file metadata")
    if isinstance(track, mp3.EasyMP3):
        log.debug("Cleaning easymp3 metadata")

        # RegisterTXXXKey maps an easy key name to a TXXX frame description (it does not write values).
        # Register the custom keys once, then assign values through the easy interface below.
        track.ID3.RegisterTXXXKey('description', 'description')
        track.ID3.RegisterTXXXKey('subtitle', 'subtitle')
        track.ID3.RegisterTXXXKey('isbn', 'isbn')
        track.ID3.RegisterTXXXKey('publisher', 'publisher')
        track.ID3.RegisterTXXXKey('series_index', 'series_index')
        track.ID3.RegisterTXXXKey('author', 'author')

        track.delete()
        track['title'] = md.title
        # Narrators (support multiple if available)
        if hasattr(md, 'narrators') and md.narrators:
            track['artist'] = md.narrators
        else:
            track['artist'] = md.narrator
        track['album'] = md.series
        track['date'] = md.publishYear
        # Series index (volume number in series) - use custom TXXX tag
        # Note: discnumber is reserved for actual multi-disc audiobooks (used by FileMerger for chapter ordering)
        if md.volumeNumber:
            track['series_index'] = md.volumeNumber
        # Authors (support multiple if available)
        if hasattr(md, 'authors') and md.authors:
            track['author'] = md.authors
            track['composer'] = md.authors
        else:
            track['author'] = md.author
            track['composer'] = md.author
        # Genres (support multiple)
        if hasattr(md, 'genres') and md.genres:
            track['genre'] = md.genres
        track['asin'] = md.asin
        track['description'] = md.summary
        track['subtitle'] = md.subtitle
        track['isbn'] = md.isbn
        track['publisher'] = md.publisher

    elif isinstance(track, easymp4.EasyMP4):
        log.debug("Cleaning easymp4 metadata")
        #MP4 atom names use the copyright sign prefix (\xa9), not '@'
        track.RegisterTextKey('narrator', '\xa9nrt')
        track.RegisterTextKey('author', '\xa9aut')
        # track.MP4Tags.RegisterFreeformKey('publisher', "----:com.thovin.publisher")
        track.MP4Tags.RegisterFreeformKey('publisher', "publisher", 'com.UltimateAudiobooks')
        # track.MP4Tags.RegisterFreeformKey('isbn', "----:com.thovin.isbn")
        track.MP4Tags.RegisterFreeformKey('isbn', "isbn", 'com.UltimateAudiobooks')
        # track.MP4Tags.RegisterFreeformKey('asin', "----:com.thovin.asin")
        track.MP4Tags.RegisterFreeformKey('asin', "asin", 'com.UltimateAudiobooks')
        # track.MP4Tags.RegisterFreeformKey('series', "----:com.thovin.series")
        track.MP4Tags.RegisterFreeformKey('series', "series", 'com.UltimateAudiobooks')
        # track.MP4Tags.RegisterFreeformKey('series_index', "----:com.thovin.series_index")
        track.MP4Tags.RegisterFreeformKey('series_index', "series_index", "com.UltimateAudiobooks")

        track.delete()
        track['title'] = md.title
        # Narrators (support multiple if available)
        if hasattr(md, 'narrators') and md.narrators:
            track['narrator'] = md.narrators
        else:
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
        # Series index (volume number in series) - use custom freeform key
        # Note: discnumber is reserved for actual multi-disc audiobooks (used by FileMerger for chapter ordering)
        if md.volumeNumber:
            track['series_index'] = md.volumeNumber

    elif isinstance(track, flac.FLAC):
        log.debug("Cleaning FLAC metadata")
        if track.tags:
            track.tags.clear()
        else:
            track.add_tags()
        if md.title:
            track['title'] = [md.title]
        if hasattr(md, 'narrators') and md.narrators:
            narrs = md.narrators if isinstance(md.narrators, list) else [md.narrators]
            track['artist'] = narrs
            track['narrator'] = narrs
        elif md.narrator:
            track['artist'] = [md.narrator]
            track['narrator'] = [md.narrator]
        if md.series:
            track['album'] = [md.series]
            track['grouping'] = [md.series]
        if md.publishYear:
            track['date'] = [md.publishYear]
        if hasattr(md, 'authors') and md.authors:
            authors = md.authors if isinstance(md.authors, list) else [md.authors]
            track['composer'] = authors
            track['author'] = authors
        elif md.author:
            track['composer'] = [md.author]
            track['author'] = [md.author]
        if hasattr(md, 'genres') and md.genres:
            track['genre'] = md.genres if isinstance(md.genres, list) else [md.genres]
        if md.summary:
            track['description'] = [md.summary]
            track['comment'] = [md.summary]
        if md.publisher:
            track['publisher'] = [md.publisher]
        if md.isbn:
            track['isbn'] = [md.isbn]
        if md.asin:
            track['asin'] = [md.asin]
        if md.volumeNumber:
            track['series_index'] = [str(md.volumeNumber)]

    else:
        log.error("Audio file not detected as MP3, MP4, M4A/B, or FLAC. Unable to clean metadata.")
        return

    log.debug("Metadata cleaned")
    track.save()

#TODO Either the template or some part of writing into the opf results in some bad fields
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
    file = Path(file)  # Ensure file is a Path object (may be string after ProcessPoolExecutor pickling)
    log.debug("Sanitize in - " + file.name)
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

