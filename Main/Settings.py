import json
import logging
from pathlib import Path
import sys

log = logging.getLogger(__name__)

settings = None

class Settings:
    def __init__(self, args):
        log.info("Parsing settings")
        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if self.save:   #save before loading so we don't have to deal with making the two exclusive
            self.save()

        if self.load:
            self.load()

        if not self.output:
            outPath = str(Path(self.input).parent / "Ultimate Output")
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)

        if not self.quick:
            self.confirm()

        

        log.info("Settings parsed")

    def load():
        log.debug("Loading settings")
        with open ('settings.json', 'r') as inFile:
            settingsMap = json.load(inFile)

        setSettings(Settings(**settingsMap))


    def save(): 
        log.debug("Saving settings")
        settingsMap = settings.__dict__
        settingsJSON = json.dumps(settingsMap)

        with open ('settings.json', 'w') as outFile:
            outFile.write(settingsJSON)

    def confirm():
        log.debug("Confirming settings")
        for key, value in settings.__dict__.items():
            print(f"{key}: {value}")

        while True:
            input = input("Continue program execution? (y/n): ").lower

            if input == 'y':
                break
            elif input == 'n':
                print("Confirmed, exiting...")
                log.info("User has selected no when confirming settings. Exiting...")
                sys.exit()

        
        
    
def setSettings(s):
    global settings
    settings = s

def getSettings():
    return settings