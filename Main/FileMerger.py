# import pyaudio
from pydub import AudioSegment

# //TODO get list of files

streams = []
for file in files:
    streams.append(AudioSegment.from_file(FILENAME, format=SUFFIX))

master = streams[0]
streams.pop(0)
for stream in streams:
    master.append(stream)