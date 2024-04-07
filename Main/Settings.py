import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

settings = None

class Settings:
    def __init__(self, args):
        log.info("Parsing settings")
        #Moved to main.processArgs
        # setattr(self, "batch", args.batch) 
        # setattr(self, "convert", args.convert) 
        # setattr(self, "create", args.create) 
        # # setattr(self, "default", args.default)
        # setattr(self, "force", args.force) 
        # setattr(self, "fetch", args.fetch) 
        # setattr(self, "input", args.input) 
        # setattr(self, "move", args.move) 
        # # setattr(self, "preview", args.preview) 
        # setattr(self, "output", args.output) 
        # setattr(self, "rename", None) 
        # setattr(self, "recurseFetch", False) 
        # setattr(self, "recurseCombine", False) 
        # # setattr(self, "save", False) 

        #TODO load. make sure load and args in don't overwrite. if -D, skip load.

        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if not self.output: #TODO fix
            outPath = str(Path(self.input).parent / "Ultimate Output")
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)


        if self.save:
            self.save()

        log.info("Settings parsed")

    def load():
        return

    def save(): #TODO having the method and parameter with the same name may cause issues
        return
    
def setSettings(s):
    global settings
    settings = s

def getSettings():
    return settings