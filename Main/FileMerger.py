# import pyaudio
from pydub import AudioSegment

def mergeBook(folderPath):
    # //TODO get list of files

    streams = []
    for file in files:
        streams.append(AudioSegment.from_file(file))
        # streams.append(AudioSegment.from_file(file, format=SUFFIX))

    #TODO figure out how to extract title and chapter number from filename
    #TODO rename master file
    #TODO use Mutagen library to add chapter markers in metadata, for mp4 file. Manually convert to m4b in post.
    #TODO how to figure out how many chapters per segment? Or don't bother?
    #TODO for mp3, check if track numbers are included for ordering purposes. Do not assume existant.
    
    master = streams[0]
    streams.pop(0)
    for stream in streams:
        master.append(stream)

    #TODO convert here or separate?
    #TODO does this actually return a completed file, or just an audiosegment that needs exporting?
    return master

def convertToM4B(inFile):
