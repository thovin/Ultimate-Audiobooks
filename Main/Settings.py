import json
import logging


log = logging.getLogger(__name__)

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
            self.output = self.input + "/Ultimate Output"


        if self.save:
            self.save()

        log.INFO("Settings parsed")

    def load():
        return

    def save(): #TODO having the method and parameter with the same name may cause issues
        return
    
settings = None

def create(args):
    log.info("Creating settings")   #Keep pseudo-dupe log?
    global settings
    settings = Settings(args)