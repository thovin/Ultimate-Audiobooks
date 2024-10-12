import json
import logging
from pathlib import Path
import sys

log = logging.getLogger(__name__)

settings = None

class Settings:
    def __init__(self, args):
        if self.load:  
            try:
                self.load()
            except FileNotFoundError:
                log.debug("No saved settings found! Skipping load.")

        log.info("Parsing settings")
        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if self.save:   
            self.save()

        if not self.output:
            outPath = str(Path(self.input).parent / "Ultimate Output")
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)

        if not self.quick:
            self.confirm()

        

        log.debug("Settings parsed")

    def load(self):
        log.debug("Loading settings")
        with open ('settings.json', 'r') as inFile:
            settingsMap = json.load(inFile)

        setSettings(Settings(**settingsMap))


    def save(self): 
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