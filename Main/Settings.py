import argparse
import json
import logging
from pathlib import Path
import re
import os

import Reporter

log = logging.getLogger(__name__)

#anchored next to the script so save/load work regardless of launch directory
SETTINGS_FILE = Path(__file__).resolve().parent / 'settings.json'

settings = None


class ConfigError(Exception):
    """Settings that cannot produce a valid run. Each front end decides how to present it."""


class UserAborted(ConfigError):
    """The user declined the run at the confirmation step. Not an error, just a stop."""


def buildParser():
    #Single source of truth for the CLI contract. The GUI reads defaults() from this parser rather
    #than hardcoding its own copies, so adding a flag here cannot leave the GUI out of step.
    parser = argparse.ArgumentParser(prog = "Ultimate Audiobooks")
    parser.add_argument("-B", "--batch", type=int, default = 10) #batch size
    parser.add_argument("-CL", "--clean", action = "store_true") #overwrite audio file metadata
    parser.add_argument("-CV", "--convert", action = "store_true") #convert to .m4b
    parser.add_argument("-CR", "--create", default = None, type=str.upper, choices = ["INFOTEXT", "OPF"]) #create metadata file where nonexistant. Where existant, skip unless --force is enabled
    savedSettings = parser.add_mutually_exclusive_group()
    savedSettings.add_argument("-D", "--default", action = "store_true") #Reset saved settings to default (deletes settings.json)
    parser.add_argument("-FO", "--force", action = "store_true") #When used with --create, this overwrites existing metadata files
    parser.add_argument("-FM", "--fetch", type=str.lower, choices = ["audible", "goodreads", "both"]) #interactively fetch metadata from the web
    parser.add_argument("-I", "--input", required = True) #input folder
    savedSettings.add_argument("-L", "--load", action = "store_true")  #load saved settings. Exclusive with --default
    parser.add_argument("-LL", "--logLevel", type=str.upper, default = "INFO", choices = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help = "Set logging level") #log level
    parser.add_argument("-M", "--move", action = "store_true") #move files to output (copies by default)
    parser.add_argument("-DR", "--dryRun", action = "store_true") #list what would be done without copying, moving, converting, or tagging anything (fetch skipped)
    parser.add_argument("-O", "--output", default = None) #output folder. Will default to a named sub of input, set in setter method
    parser.add_argument("-Q", "--quick", action = "store_true") #skip confirmation of settings
    parser.add_argument("-RN", "--rename", default = None) #rename files
    recursiveModes = parser.add_mutually_exclusive_group()
    recursiveModes.add_argument("-RF", "--recurseFetch", action = "store_true") #recursively fetch audio files, presumed to be entire books. Recursives are exclusive.
    recursiveModes.add_argument("-RC", "--recurseCombine", action = "store_true") #recursively fetch audio files, combining files sharing a dir. Recursives are exclusive.
    recursiveModes.add_argument("-RP", "--recursePreserve", action = "store_true") #recursively fetch audio files, preserving chapter files. Recursives are exclusive.
    parser.add_argument("-S", "--save", action = "store_true") #save settings for future executions
    parser.add_argument("-W", "--workers", type=int, default = -1)  #set number of workers to process conversions
    return parser


def defaults():
    #Every option with its default value, for front ends that build args without argparse.
    return {action.dest: action.default for action in buildParser()._actions if action.dest != 'help'}


def modeName(s):
    #Human name of the processing mode, for the run header.
    if s.recurseFetch:
        return "Processing complete books in all subfolders"
    if s.recurseCombine:
        return "Combining chapter folders into books"
    if s.recursePreserve:
        return "Processing subfolders with chapters preserved"
    return "Processing books in the input folder"


class Settings:
    def __init__(self, args):
        #--load is applied in Main.py before this constructor runs, so args already reflect saved settings
        for arg, value in vars(args).items():
            setattr(self, arg, value)

        if not self.output:
            outPath = str(Path(self.input).parent / "Ultimate Output")
            self.output = outPath
            log.debug("Output path defaulting to: " + outPath)

        #save after defaults are resolved so the save file holds real values, not None
        if self.save:
            self.createSaveFile()

        self.validate()

        if not self.quick and not Reporter.confirmSettings(dict(self.__dict__)):
            raise UserAborted("User declined the settings confirmation.")

        log.debug("Settings parsed")

    def createSaveFile(self):
        log.debug("Saving settings")
        settingsMap = self.__dict__
        settingsJSON = json.dumps(settingsMap)

        with open (SETTINGS_FILE, 'w') as outFile:
            outFile.write(settingsJSON)

    def validate(self):
        #Every rule that makes a run impossible, in one place, so the CLI and the GUI cannot
        #disagree about what is allowed. Raises ConfigError; callers present it however suits them.
        if not self.input:
            raise ConfigError("No input folder given.")
        if not Path(self.input).is_dir():
            raise ConfigError("The input folder does not exist:\n" + str(self.input))

        if self.recurseCombine and not self.move:
            raise ConfigError("Recurse combine currently requires move mode: "
                              "copy mode would strand original files in the temp folder.")

        self.checkFolders()

    def checkFolders(self): #TODO this is really only a problem when using ffmpeg, I think. Cut this check and/or only check when going to use it and only check in those functions?
        specials = re.compile(r'[<,>"|\'?’*\x00-\x1F]') #since this is a dir path, no colons allowed

        for label, path in (("input", self.input), ("output", self.output)):
            for folder in str(path).split(os.sep):
                if specials.search(folder):
                    raise ConfigError(f"Special character in {label} directory: {folder}\n"
                                      "Special characters can cause unexpected behavior and are not allowed.")


def setSettings(s):
    global settings
    settings = s

def getSettings():
    return settings
