import json
import logging
from pathlib import Path
import sys
import re
import os

log = logging.getLogger(__name__)

#anchored next to the script so save/load work regardless of launch directory
SETTINGS_FILE = Path(__file__).resolve().parent / 'settings.json'

settings = None

class Settings:
    def __init__(self, args):
        #--load is applied in Main.py before this constructor runs, so args already reflect saved settings
        log.info("Parsing settings")
        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if not self.output:
            outPath = str(Path(self.input).parent / "Ultimate Output")
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)

        #save after defaults are resolved so the save file holds real values, not None
        if self.save:
            self.createSaveFile()

        if not self.quick:
            self.confirm()

        self.checkFolders()

        log.debug("Settings parsed")

    def createSaveFile(self):
        log.debug("Saving settings")
        settingsMap = self.__dict__
        settingsJSON = json.dumps(settingsMap)

        with open (SETTINGS_FILE, 'w') as outFile:
            outFile.write(settingsJSON)

    def confirm(self):
        log.debug("Confirming settings")
        for key, value in self.__dict__.items():
            print(f"{key}: {value}")

        while True:
            userInput = input("Continue program execution? (y/n): ").lower()

            if userInput == 'y':
                break
            elif userInput == 'n':
                print("Confirmed, exiting...")
                log.info("User has selected no when confirming settings. Exiting...")
                sys.exit()

    def checkFolders(self): #TODO this is really only a problem when using ffmpeg, I think. Cut this check and/or only check when going to use it and only check in those functions?
        specials = re.compile(r'[<,>"|\'?’*\x00-\x1F]') #since this is a dir path, no colons allowed
        inDirs = self.input.split(os.sep)
        outDirs = self.output.split(os.sep)

        for folder in inDirs:
            if specials.search(folder):
                log.error("ERROR: special character detected in directory: " + str(folder) + \
                    ". Special characters can cause unexpected behavior and are not allowed. Aborting...")
                sys.exit(1)
        for folder in outDirs:
            if specials.search(folder):
                log.error("ERROR: special character detected in directory: " + str(folder) + \
                    ". Special characters can cause unexpected behavior and are not allowed. Aborting...")
                sys.exit(1)
        
        
    
def setSettings(s):
    global settings
    settings = s

def getSettings():
    return settings