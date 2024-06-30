# import pyaudio
from pydub import AudioSegment
from itertools import islice
import mutagen
import re
import subprocess

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

        if trackMap[-1]:
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
    

    

def mergeBook(folderPath):  #This assumes chapter files are always mp3
    #TODO log
    files = list(islice(folderPath.glob("*.mp3")))
    tracks = []
    pieces = []
    hasMultipleDisks = False

    for file in files:
        track = mutagen.File(file, easy=True)
        tracks.append(track)
        if track['discnumber'] != 1:
            hasMultipleDisks = True

    try:
        pieces = orderByTrackNumber(tracks, hasMultipleDisks)
    except Exception as e:
        pass

    if len(pieces) == 0:
        pieces = orderByTitle(tracks)


    streams = []
    for p in pieces:  #.mp3, .mp4
        streams.append(AudioSegment.from_file(p))

    #TODO rename master file
    #TODO use Mutagen library to add chapter markers in metadata, for mp4 file. Manually convert to m4b in post.
    # master = AudioSegment.empty()
    # ms = 0
    # chapters = []
    # for stream in streams:
    #     master.append(stream)
    #     ms += len(stream)
    #     chapters.append(ms)

    tempFilepath = folderPath + '\\tempConcatFileList.txt'
    newFilepath = folderPath + '\\output.mp3'   #TODO give more descriptive name
    with open (tempFilepath, 'w') as outFile:
        for s in streams:
            outFile.write(f"file '{s}'\n")

    cmd = ['ffmpeg', 
           '-f', 'concat',
           'safe', '0',
           '-i', tempFilepath,
           '-codec', 'copy',    #copy audio streams instead of re-encoding
           newFilepath #we could convert to mp4 while already doing the operation, but I prefer the cleanliness of seperation of duties
           ]
    
    try:
        subprocess.run(cmd, check=True)

    except subprocess.CalledProcessError as e:
        return #TODO
    
    #TODO return combined file AND chapter info
    return newFilepath
