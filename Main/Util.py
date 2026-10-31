from Settings import getSettings
from pathlib import Path
import mutagen
from mutagen import easymp4, mp3, mp4, flac, oggopus, oggvorbis, asf
import webbrowser
import time
import requests
from bs4 import BeautifulSoup
import logging
import pyperclip
import subprocess
import shutil
from xml.sax.saxutils import escape
import os
import psutil
import platform
import urllib.parse
import re
import json
from BookStatus import skipBook, failBook
import Reporter

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
    def __init__(self, file, type, md, duration=-1):
        self.file = file
        self.type = type
        self.md = md
        self.duration = duration  #seconds of audio, so the worker can report conversion progress


#FLAC, Ogg Vorbis and Opus all keep Vorbis comments, so they share one set of tag branches below
VORBIS_TYPES = (flac.FLAC, oggvorbis.OggVorbis, oggopus.OggOpus)

#What the script can do with a file's tags, decided by what mutagen opened it as. WAV has no tags to
#speak of, and WMA (ASF) is readable but not worth writing. Callers check these before reading or
#writing, and tell the user why when they skip, rather than attempting it and logging an error.
def canReadTags(track):
    return isinstance(track, (mp3.EasyMP3, easymp4.EasyMP4, asf.ASF) + VORBIS_TYPES)


def canWriteTags(track):
    return isinstance(track, (mp3.EasyMP3, easymp4.EasyMP4) + VORBIS_TYPES)


def _asfFirst(track, *keys):
    #ASF keeps its own key names (Title, Author, ...) and wraps values in attribute objects
    for key in keys:
        values = track.get(key)
        if values:
            text = str(values[0]).strip()
            if text:
                return text
    return ""


def getTitle(track):
    log.debug("Extracting title from track")

    if isinstance(track, asf.ASF):
        return _asfFirst(track, 'Title', 'WM/AlbumTitle')

    if not canReadTags(track):
        log.debug("This file type carries no readable tags. Returning empty string")
        return ""

    if isinstance(track, mp3.EasyMP3) or isinstance(track, easymp4.EasyMP4):
        if 'title' in track and track['title'] != "":
            return track['title'][0]
        elif 'album' in track and track['album'] != "":
            return track['album'][0]
        else:
            log.debug("No title found. Returning empty string")
            return ""
    else:
        #Vorbis comments (FLAC, Ogg Vorbis, Opus)
        if 'title' in track and track['title']:
            return track['title'][0]
        elif 'album' in track and track['album']:
            return track['album'][0]
        else:
            log.debug("No title found. Returning empty string")
            return ""


def getAuthor(track):
    log.debug("Extracting author from track")

    if isinstance(track, asf.ASF):
        return _asfFirst(track, 'Author', 'WM/AlbumArtist', 'WM/Composer')

    if not canReadTags(track):
        log.debug("This file type carries no readable tags. Returning empty string")
        return ""

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
    else:
        #Vorbis comments (FLAC, Ogg Vorbis, Opus)
        if 'artist' in track and track['artist']:
            return track['artist'][0]
        elif 'composer' in track and track['composer']:
            return track['composer'][0]
        elif 'albumartist' in track and track['albumartist']:
            return track['albumartist'][0]
        else:
            log.debug("No author found. Returning empty string")
            return ""
    
    

def GETpage(url):
    log.debug("GET page: " + url)
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
#(searchText, searchURL, file, reason) -> URL string or "SKIP", where reason explains why the
#previous link was rejected (None on the first attempt). The GUI installs its own; the CLI defaults
#to watching the clipboard (ClipboardUrlProvider).
urlProvider = None

def setUrlProvider(provider):
    global urlProvider
    urlProvider = provider


class ClipboardUrlProvider:
    def __call__(self, searchText, searchURL, file, reason=None):
        #reset the clipboard if it already holds a book link, so re-copying the same link registers as a change
        last = pyperclip.paste()
        if any(sub in last for sub in ("goodreads.com", "audible.com")):
            pyperclip.copy("Ultimate Audiobooks")
            last = "Ultimate Audiobooks"

        #re-open the search on a retry too: a stale browser tab with no explanation is the worst
        #place to leave the user, and it matches what the GUI panel does
        open_url_cross_platform(searchURL)

        if reason:
            print(reason)
        print("Waiting for URL (copy the book page link, or copy the word 'skip')...")
        while True:
            time.sleep(1)
            curr = pyperclip.paste()
            if curr == last:
                continue
            if curr.strip().upper() == "SKIP" or "audible.com" in curr or "goodreads.com" in curr:
                return curr
            #any other clipboard activity is ignored, same as the original behavior


def fetchMetadata(file, track) -> Metadata:
    Reporter.bookStep(Reporter.STEP_FETCH, file.name)
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

    def reject(message):
        #Report why the link was no good and hand the same message back to the provider, so the
        #next prompt can explain itself instead of leaving the reason in a scrolling log.
        Reporter.fetchFailed(message, file.name)
        return message

    reason = None

    while True:
        candidate = provider(searchText, searchURL, file, reason)
        reason = None

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
                    reason = reject("That looks like a series, author, or podcast page - not a book page. Please provide a specific book's page link, or skip this book.")
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
                    reason = reject("Unable to extract ASIN from Audible URL. Please provide a book page link, or skip this book.")
                    continue
                md.asin = asin_match
            except Exception:
                log.debug("Error parsing Audible URL", exc_info=True)
                reason = reject("Could not read that Audible URL. Please provide a book page link, or skip this book.")
                continue

            paramRequest = "?response_groups=contributors,product_attrs,product_desc,product_extended_attrs,series"
            targetUrl = f"https://api.audible.com/1.0/catalog/products/{md.asin}" + paramRequest
            page = GETpage(targetUrl)
            if page is None or not getattr(page, "ok", False):
                reason = reject("Audible API request failed. Please provide a valid book page link, or skip this book.")
                continue

            try:
                data = page.json()
                product = data.get('product')
                if not product:
                    raise KeyError("No 'product' in response")
                parseAudibleMd(product, md)

                if not md.title or not md.author:
                    reason = reject("Audible link did not yield both title and author. Please provide a valid book page link, or skip this book.")
                    continue
                break
            except (json.JSONDecodeError, KeyError):
                reason = reject("Error reading Audible API. Perhaps this is a series/podcast or invalid link? Provide a book page link, or skip this book.")
                continue



        elif "goodreads.com" in candidate:
            log.debug("Goodreads URL captured: " + candidate)
            page = GETpage(candidate)
            if page is None:
                reason = reject("Goodreads page request failed. Please provide a valid book page link, or skip this book.")
                continue
            soup = BeautifulSoup(page.text, 'html.parser')
            parseGoodreadsMd(soup, md)
            # Safety net: ensure required fields present
            if not md.title or not md.author:
                reason = reject("Goodreads link did not yield both title and author. Please provide a valid book page link, or skip this book.")
                continue
            break

        else:
            reason = reject("Link not recognized as an Audible or Goodreads book page. Try again, or skip this book.")
            continue

    return md



#Formats that are always re-encoded to AAC. MP3 is handled on its own branch in convertToM4B and the
#MP4 family is probed first, since an MP4 container may already hold AAC/ALAC and need no encoding.
ALWAYS_TRANSCODE_TYPES = {'.flac', '.opus', '.ogg', '.oga', '.wav', '.wma'}
AUDIO_EXTENSIONS = {'.m4a', '.m4b', '.mp3', '.mp4'} | ALWAYS_TRANSCODE_TYPES

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


def getDuration(file):
    #Seconds of audio, or -1 when it can't be read. Used as the denominator for conversion progress.
    try:
        track = mutagen.File(file)
        return float(track.info.length) if track is not None else -1
    except Exception:
        log.debug("Could not read duration of " + str(file), exc_info=True)
        return -1


#ffmpeg's -progress stream is plain key=value lines
_PROGRESS_LINE = re.compile(r'^([a-z_]+)=(.*)$')

#appended to every ffmpeg command: machine-readable progress on stdout, no CR status line
FFMPEG_PROGRESS_ARGS = ['-progress', 'pipe:1', '-nostats']


def runFfmpeg(cmd, step, label, totalSeconds=-1):
    """Run ffmpeg, turning its -progress output into StepProgress events. Returns True on success.

    cmd must contain FFMPEG_PROGRESS_ARGS. stderr is folded into stdout so ffmpeg's own messages
    cannot fill a second pipe and deadlock the read loop; lines that are not key=value progress
    pairs are collected and logged as warnings once the process exits."""
    messages = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError:
        log.error("ffmpeg not found. Install ffmpeg and make sure it is on PATH.")
        return False

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        match = _PROGRESS_LINE.match(line)
        if not match:
            messages.append(line)
            continue
        if totalSeconds <= 0:
            continue

        key, value = match.group(1), match.group(2)
        if key == 'out_time_us':
            try:
                done = int(value) / 1_000_000
            except ValueError:
                continue  #ffmpeg reports N/A before the first frame is written
            Reporter.stepProgress(step, label, min(done, totalSeconds), totalSeconds)
        elif key == 'progress' and value == 'end':
            Reporter.stepProgress(step, label, totalSeconds, totalSeconds)

    proc.stdout.close()
    proc.wait()

    for message in messages:
        log.warning("ffmpeg: " + message)

    return proc.returncode == 0


def convertToM4B(file, type, md, settings, duration=-1): #This is run parallel through ProcessPoolExecutor, which limits access to globals
    #When copying we create the new file in destination, otherwise the new file will be copied and there will be an extra original
    #When moving we convert in place and allow the move to be handled in EOF processing
    #Returns the converted file's path, or None on failure
    file = Path(file)  # Ensure file is a Path object (may be string after ProcessPoolExecutor pickling)
    originalFile = file
    label = file.name
    Reporter.bookStep(Reporter.STEP_CONVERT, label)

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
           '-hide_banner',  #suppress version/build info header
           '-loglevel', 'warning',
           *FFMPEG_PROGRESS_ARGS,
           str(tempPath)]  #convert Path to string for subprocess


    def conversionFailed():
        nonlocal file
        if not settings.move:
            #remove the working copy; the untouched original is what should be reported/moved
            file.unlink(missing_ok=True)
            file = originalFile
        failBook(file, "Conversion failed")
        return None

    if duration <= 0:
        duration = getDuration(file)

    if type == '.mp3':
        log.debug("Converting MP3 to M4B")
        if not runFfmpeg(cmd, Reporter.STEP_CONVERT, label, duration):
            return conversionFailed()

        file.unlink() #if not settings.move, a copy is created which this deletes. Nondestructive.
        return tempPath.rename(newPath)

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
                   *FFMPEG_PROGRESS_ARGS,
                   str(tempPath)]
        if not runFfmpeg(cmd_mp4, Reporter.STEP_CONVERT, label, duration):
            return conversionFailed()

        file.unlink()
        return tempPath.rename(newPath)

    elif type in ALWAYS_TRANSCODE_TYPES:
        log.debug(f"Converting {type} to M4B")
        cmd_other = ['ffmpeg',
                     '-nostdin',  #never prompt on stdin (a prompt would deadlock ProcessPoolExecutor workers)
                     '-y',        #overwrite leftover temp output from a previous crashed run
                     '-i', str(file),
                     '-c:a', 'aac',  #transcode to AAC (none of these codecs can be stream-copied into an MP4 container)
                     '-q:a', '3',  #VBR quality ~128-160kbps
                     '-vn',  #disable video
                     '-hide_banner',  #suppress version/build info header
                     '-loglevel', 'error',
                     *FFMPEG_PROGRESS_ARGS,
                     str(tempPath)]
        if not runFfmpeg(cmd_other, Reporter.STEP_CONVERT, label, duration):
            return conversionFailed()

        file.unlink()
        return tempPath.rename(newPath)

    else:
        log.error(f"Unsupported type {type} for conversion of {file.name}")
        return conversionFailed()


def cleanMetadata(track, md):
    if not canWriteTags(track):
        #callers announce this to the user (see tagNotes); nothing to attempt, so nothing to report here
        log.debug("File type has no writable tags. Skipping tag step")
        return
    Reporter.bookStep(Reporter.STEP_TAG, md.title or Path(track.filename).name)
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

    elif isinstance(track, VORBIS_TYPES):
        log.debug("Cleaning Vorbis comment metadata")
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

    log.debug("Metadata cleaned")
    track.save()

def buildOpf(md):
    #Audiobookshelf's OPF reader (server/utils/parsers/parseOpfMetadata.js) is the compatibility target, and it is
    #picky: dc:* elements for title/subtitle/creator/publisher/date/identifier/description/subject, role and scheme
    #read through the first xmlns: prefix it finds (defaulting to opf), narrators as dc:creator opf:role="nrt", and
    #series only as calibre:series / calibre:series_index metas. Anything else is silently ignored, so the XML is
    #assembled by hand: ElementTree reorders and renames namespace prefixes, which breaks that prefix detection.
    def clean(value):
        return "" if value is None else str(value).strip()

    def element(tag, value, attrs=""):
        value = clean(value)
        return f"    <{tag}{attrs}>{escape(value)}</{tag}>" if value else None

    def meta(name, value):
        value = clean(value)
        return f'    <meta name="{name}" content="{escape(value, {chr(34): "&quot;"})}"/>' if value else None

    authors = [clean(a) for a in md.authors] if md.authors else [clean(md.author)]
    narrators = [clean(n) for n in md.narrators] if md.narrators else [clean(md.narrator)]
    #the package must name one of its identifiers, so prefer the ASIN (what Audiobookshelf matches on) over the ISBN
    idAttr = ' id="BookId"'
    asinAttr, isbnAttr = (idAttr, "") if clean(md.asin) else ("", idAttr)

    lines = [
        element("dc:title", md.title),
        element("dc:subtitle", md.subtitle),
        *[element("dc:creator", a, ' opf:role="aut"') for a in authors],
        *[element("dc:creator", n, ' opf:role="nrt"') for n in narrators],
        element("dc:publisher", md.publisher),
        element("dc:date", md.publishYear),
        element("dc:description", md.summary),
        *[element("dc:subject", g) for g in (md.genres or [])],
        element("dc:identifier", md.asin, f'{asinAttr} opf:scheme="ASIN"'),
        element("dc:identifier", md.isbn, f'{isbnAttr} opf:scheme="ISBN"'),
        meta("calibre:series", md.series),
        meta("calibre:series_index", md.volumeNumber) if clean(md.series) else None,
    ]
    body = "\n".join(line for line in lines if line)
    uniqueId = ' unique-identifier="BookId"' if clean(md.asin) or clean(md.isbn) else ""

    #xmlns:opf is declared first on purpose: the reader takes the first xmlns: prefix it finds as the one for role/scheme
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" xmlns:opf="http://www.idpf.org/2007/opf" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"{uniqueId}>\n'
        '  <metadata>\n'
        f'{body}\n'
        '  </metadata>\n'
        '</package>\n'
    )


def createOpf(md):
    opfPath = Path(md.bookPath) / "metadata.opf"
    if opfPath.exists() and not settings.force:
        log.debug(f"{opfPath} already exists; skipping (use --force to overwrite)")
        return

    Reporter.bookStep(Reporter.STEP_SIDECAR, md.title)
    log.debug("Write OPF file")
    opfPath.write_text(buildOpf(md), encoding="utf-8")


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

    #ffmpeg's native AAC encoder is single-threaded, so one job saturates about one core; leave a core
    #free for the parent process and the desktop. An audio transcode needs well under 0.25 GB.
    return min(numCores - 1, availableMemory / 0.25)

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

