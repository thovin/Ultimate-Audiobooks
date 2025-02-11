import argparse
import Settings
import Util
import Processing
import logging as log
from pathlib import Path
import sys

'''
DEBUG
INFO
WARNING
ERROR
CRITICAL
'''
#TODO change level before release
log.basicConfig(level=log.DEBUG, format = "[%(asctime)s][%(levelname)s] %(message)s", datefmt='%H:%M:%S')
settings = None

def main(args):
    #Yes, I know this approach isn't super elegant. Feel free to recommend an alternative that isn't more of a pain in the ass like a config file.
    global settings
    settings = Settings.Settings(args)
    Settings.setSettings(settings)
    Util.loadSettings()
    Processing.loadSettings()

    log.debug("Creating output directory if not exists: " + settings.output)
    Path(settings.output).mkdir(parents = True, exist_ok = True)
    processBooks()


def processBooks():
    global settings

    if (settings.recurseFetch and settings.recurseCombine) or (settings.recurseFetch and settings.recursePreserve) or (settings.recurseCombine and settings.recursePreserve):
        log.critical("Incompatible processing modes selected. Enable only one processing mode. Exiting...")
        sys.exit()

    elif settings.recurseFetch:
        Processing.recursivelyFetchBatch()

    elif settings.recurseCombine:
        Processing.recursivelyCombineBatch()

    elif settings.recursePreserve:
        Processing.recursivelyPreserveBatch()

    else:
        Processing.singleLevelBatch()


if __name__ == "__main__":
    log.info("Parsing arguments")
    parser = argparse.ArgumentParser(prog = "Ultimate Audiobooks")
    parser.add_argument("-B", "--batch", type=int, default = 10) #batch size
    parser.add_argument("-CL", "--clean", action = "store_true") #overwrite audio file metadata
    parser.add_argument("-CV", "--convert", action = "store_true") #convert to .m4b
    parser.add_argument("-CR", "--create", default = None, type=str.upper, choices = ["INFOTEXT", "OPF"]) #create metadata file where nonexistant. Where existant, skip unless --force is enabled
    parser.add_argument("-D", "--default", action = "store_true") #Reset saved settings to default
    parser.add_argument("-FO", "--force", action = "store_true") #When used with --create, this overwrites existing metadata files
    parser.add_argument("-FM", "--fetch", type=str.lower, choices = ["audible", "goodreads", "both"]) #interactively fetch metadata from the web
    parser.add_argument("-I", "--input", required = True) #input folder
    parser.add_argument("-L", "--load", action = "store_true")  #load saved settings
    parser.add_argument("-M", "--move", action = "store_true") #move files to output (copies by default)
    parser.add_argument("-O", "--output", default = None) #output folder. Will default to a named sub of input, set in setter method
    parser.add_argument("-Q", "--quick", action = "store_true") #skip confirmation of settings
    parser.add_argument("-RN", "--rename", default = None) #rename files
    parser.add_argument("-RF", "--recurseFetch", action = "store_true") #recursively fetch audio files, presumed to be entire books. Recursives are exclusive.
    parser.add_argument("-RC", "--recurseCombine", action = "store_true") #recursively fetch audio files, combining files sharing a dir. Recursives are exclusive.
    parser.add_argument("-RP", "--recursePreserve", action = "store_true") #recursively fetch audio files, preserving chapter files. Recursives are exclusive.
    parser.add_argument("-S", "--save", action = "store_true") #save settings for future executions
    parser.add_argument("-W", "--workers", type=int, default = -1)  #set number of workers to process conversions

    args = parser.parse_args()
    log.debug("Arguments parsed successfully")

    main(args)