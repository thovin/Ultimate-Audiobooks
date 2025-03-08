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
    hasMultipleDisks = False

    if len(files) < 1:
        files = list(folderPath.glob("*.m4*"))

    if outPath:
        newFilepath = outPath / (folderPath.name + " - " + files[0].name)
    else:
        newFilepath = folderPath / (folderPath.name + " - " + files[0].name)

    log.debug(str(len(files)) + " chapters detected")

    #TODO when --rename is working, apply here
    #TODO special characters completely break this
    #TODO suppress ffmpeg output?
    #TODO process merges at end like conversions?
    #TODO improve processing for multiple disks not in metadata

    pieces = orderFiles(files)
    tempConcatFilePath, tempChapFilePath = createTempFiles(pieces, folderPath)

    cmd = ['ffmpeg', 
        '-f', 'concat',
        '-safe', '0',
        '-i', tempConcatFilePath,
        '-i', tempChapFilePath, "-map_metadata", "1",
        '-codec', 'copy',    #copy audio streams instead of re-encoding
        '-vn',   #disable video
        newFilepath #we could convert to mp4 while already doing the operation, but I prefer the cleanliness of seperation of duties
        ]
    
    log.debug("Begin combining")
    try:
        subprocess.run(cmd, check=True)

        if move:
            with open(tempConcatFilePath, 'r') as t:
                for line in t:
                    os.remove(line[5:].strip().strip('\''))

    except subprocess.CalledProcessError as e:
        return #TODO
    
    os.remove(tempConcatFilePath)
    os.remove(tempChapFilePath)

    return newFilepath

def orderFiles(files):
    pieces = []
    tracks = []

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
    return pieces

def createTempFiles(pieces, folderPath):
    log.debug("Write files to tempConcatFileList")
    tempConcatFilepath = ""
    tempChapFilepath = ""
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', dir=folderPath) as tempConcatFile, \
    tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', dir=folderPath) as tempChapFile:
        #TODO skip books when this errors instead of crashing whole script?
        runningTime = 0
        chapCount = 1
        tempChapFile.write(";FFMETADATA1\n")

        for p in pieces: #p = mutagen easyMP*
            tempConcatFile.write(f"file '{p.filename}'\n")

            tempChapFile.write("[CHAPTER]\n")
            tempChapFile.write("TIMEBASE=1/1000\n")
            tempChapFile.write(f"START={runningTime}\n")
            runningTime += p.info.length * 1000
            tempChapFile.write(f"END={runningTime}\n")
            tempChapFile.write(f"title=Chapter {chapCount}\n\n")
            chapCount += 1

        tempConcatFilepath = tempConcatFile.name
        tempChapFilepath = tempChapFile.name



    return tempConcatFilepath, tempChapFilepath