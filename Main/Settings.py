import json
import logging
from pathlib import Path
import sys

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

        
        
    
def setSettings(s):
    global settings
    settings = s

def getSettings():
    return settings