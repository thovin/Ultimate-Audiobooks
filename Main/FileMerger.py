from itertools import islice
import mutagen
import re
import subprocess
import logging
import tempfile
from pathlib import Path
import os

log = logging.getLogger(__name__)

def findTitleNum(title, whichNum) -> int:
    title = title.upper()
    try:
        return int(re.findall(r'\d+', title)[whichNum])  #find all numbers, return specified
    except IndexError:
        if any(word in title for word in ["intro".upper(), "prologue".upper()]):
            return 1
        if any(word in title for word in ["outro".upper(), "epilogue".upper(), "credits".upper()]):
            return 999
        else:
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
    number = 0

    while True:
        trackMap = {}
        for track in tracks:
            trackMap[findTitleNum(Path(track.filename).stem, number)] = track
        ordered = sorted(trackMap.keys())

        # if trackMap[-1]:
        if -1 in trackMap:
            #TODO skip this book
            break   #no more numbers, no order beginning in 1
        elif ordered[0] != 1 or len(ordered) < 2: #check for 1, 1, 1, ...
            number += 1
            continue
        else:
            tracksOut = []
            for key in ordered:
                tracksOut.append(trackMap[key])
            return tracksOut
    

def mergeBook(folderPath, outPath = False, move = False):
    log.debug("Begin merging chapters in " + folderPath.name)
    files = list(folderPath.glob("*.mp*"))
    tracks = []
    pieces = []
    hasMultipleDisks = False

    if len(files) < 1:
        files = list(folderPath.glob("*.m4*"))

    log.debug(str(len(files)) + " chapters detected")

    #TODO when --rename is working, apply here
    #TODO special characters completely break this
    #TODO suppress ffmpeg output?
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

    #TODO use Mutagen library to add chapter markers in metadata, for mp4 file. Manually convert to m4b in post.

    if outPath:
        newFilepath = outPath / (folderPath.name + " - " + files[0].name)
    else:
        newFilepath = folderPath / (folderPath.name + " - " + files[0].name)



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

        if move:
            with open(tempFilepath, 'r') as t:
                for line in t:
                    os.remove(line[5:].strip().strip('\''))

    except subprocess.CalledProcessError as e:
        return #TODO
    
    os.remove(tempFilepath)

    
    #TODO return combined file AND chapter info
    return newFilepath
