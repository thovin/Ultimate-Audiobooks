# from pydub import AudioSegment
from itertools import islice
import mutagen
import re
import subprocess
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

def findTitleNum(title, whichNum) -> int:
    try:
        return int(re.findall(r'\d+', title)[whichNum])  #find all numbers, return specified
    except IndexError:
        #TODO account for intro, prologue, etc
        return -1   #no more numbers in title


def orderByTrackNumber(tracks, hasMultipleDisks):
    chapters = []

    if hasMultipleDisks:
        tracksDone = 0
        disk = 1
        while tracksDone < len(tracks):
            # offset = len(chapters)
            offset = tracksDone
            for track in tracks:
                if track['disknumber'] == disk:
                    chapters[track['tracknumber'] + offset] = track
                    tracksDone += 1
            disk += 1
    else:
        for track in tracks:
            chapters[track['tracknumber']] = track

    return chapters


def orderByTitle(tracks):
    number = 1

    while True:
        trackMap = {}
        for track in tracks:
            trackMap[findTitleNum(track.filename, number)] = track

        ordered = sorted(trackMap.keys())

        # if trackMap[-1]:
        if -1 in trackMap:
            #TODO skip this book
            break   #no more numbers, no order beginning in 1
        elif ordered[0] != 1 or ordered[1] != 2: #check first two in case we get 1, 1, 1, ...
            number += 1
            continue
        else:
            tracksOut = []
            for key in ordered:
                tracksOut.append(trackMap[key])
            return tracksOut
    

def mergeBook(folderPath, outPath = False):  #This assumes chapter files are always mp3
    #TODO log
    log.debug("Begin merging chapters in " + folderPath.name)
    files = list(folderPath.glob("*.mp3"))
    tracks = []
    pieces = []
    hasMultipleDisks = False

    #TODO this assumes all files are also tracks, BROKEN
    for file in files:
        track = mutagen.File(file, easy=True)
        tracks.append(track)

        try:
            if track['discnumber'] != 1:
                hasMultipleDisks = True
        except KeyError:
            pass

    try:
        pieces = orderByTrackNumber(tracks, hasMultipleDisks)
    except Exception as e:
        pass

    if len(pieces) == 0:
        pieces = orderByTitle(tracks)

    log.debug("Pieces ordered")

    #TODO rename master file
    #TODO use Mutagen library to add chapter markers in metadata, for mp4 file. Manually convert to m4b in post.
    # master = AudioSegment.empty()
    # ms = 0
    # chapters = []
    # for stream in streams:
    #     master.append(stream)
    #     ms += len(stream)
    #     chapters.append(ms)

    if outPath:
        # newFilepath = outPath / 'output.mp3'   
        # newFilepath = outPath / folderPath.name   
        newFilepath = outPath / (folderPath.name + " - " + files[0].name)   #TODO stick with parent folder name or find a more surefire way to get the title?
    else:
        # newFilepath = folderPath / 'output.mp3'   
        # newFilepath = folderPath / folderPath.name   #TODO fix name
        newFilepath = folderPath / (folderPath.name + " - " + files[0].name)   #TODO decide name



    log.debug("Write files to tempConcatFileList")
    tempFilepath = ""
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', dir=folderPath) as tempFile:
        for p in pieces:
            tempFile.write(f"file '{p.filename}'\n")

        tempFilepath = tempFile.name
        

    cmd = ['ffmpeg', 
        '-f', 'concat',
        '-safe', '0',
        '-i', tempFilepath,
        '-codec', 'copy',    #copy audio streams instead of re-encoding
        '-vn',   #disable video
        newFilepath #we could convert to mp4 while already doing the operation, but I prefer the cleanliness of seperation of duties
        ]
    
    log.debug("Begin combining")
    try:
        subprocess.run(cmd, check=True)

    except subprocess.CalledProcessError as e:
        return #TODO
    
    Path(tempFilepath).unlink()

    
    #TODO return combined file AND chapter info
    return newFilepath
