import json
import logging
from pathlib import Path
import sys
import re
import os

log = logging.getLogger(__name__)

settings = None

class Settings:
    def __init__(self, args):
        '''
        if self.load:  #TODO either move below args parsing or manually extract load from args. This way doesn't work.
            try:
                self.loadSaveFile()
            except FileNotFoundError:
                log.debug("No saved settings found! Skipping load.")
        '''
                
        log.info("Parsing settings")
        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if self.save:   
            self.createSaveFile()

        if not self.output:
            outPath = str(Path(self.input).parent / "Ultimate Output")  #TODO would it be more convenient to default to the input parent or input? Using the input definitly creates opportunity for infinite loops.
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)

        if not self.quick:
            self.confirm()

        self.checkFolders()

        log.debug("Settings parsed")

    def loadSaveFile(self):
        log.debug("Loading settings")
        with open ('settings.json', 'r') as inFile:
            settingsMap = json.load(inFile)

        setSettings(Settings(**settingsMap))


    def createSaveFile(self): 
        log.debug("Saving settings")
        settingsMap = self.__dict__
        settingsJSON = json.dumps(settingsMap)

        with open ('settings.json', 'w') as outFile:
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