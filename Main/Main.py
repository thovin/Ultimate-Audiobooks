import argparse
import Settings
import FileManagement
import Util
import logging as log
from pathlib import Path
import shutil

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
    #TODO change level before release

    # processArgs()
    #Yes, I know this approach isn't super elegant. Feel free to recommend an alternative that isn't more of a pain in the ass like a config file.
    global settings
    settings = Settings.Settings(args)
    Settings.setSettings(settings)
    FileManagement.loadSettings()
    Util.loadSettings()

    log.debug("Creating output directory if not exists: " + settings.output)
    Path(settings.output).mkdir(parents = True, exist_ok = True)
    processBooks()




def processBooks():
    global settings

    if (settings.recurseFetch and settings.recurseCombine) or (settings.recurseFetch and settings.recursePreserve) or (settings.recurseCombine and settings.recursePreserve):
        log.critical("Incompatible processing modes selected. Enable only one processing mode. Exiting...")
        #TODO ERROR
        pass

    elif settings.recurseFetch:
        FileManagement.recursivelyFetchBatch()

    elif settings.recurseCombine:
        FileManagement.recursivelyCombineBatch()

    elif settings.recursePreserve:
        FileManagement.recursivelyPreserveBatch()

    else:
        FileManagement.singleLevelBatch()



# def processArgs(parser):
#     log.info("Parsing arguments")
#     parser = argparse.ArgumentParser(prog = "Ultimate Audiobooks")
#     parser.add_argument("-B", "--batch", default = 10) #batch size
#     parser.add_argument("-CL", "--clean", default = False) #overwrite audio file metadata
#     parser.add_argument("-CV", "--convert", default = False) #convert to .m4b
#     parser.add_argument("-CR", "--create", default = None, choices = ["Infotext", "OPD"]) #create metadata file where nonexistant. Where existant, skip unless --force is enabled
#     parser.add_argument("-D", "--default", default=False) #Reset saved settings to default
#     parser.add_argument("-FO", "--force", False) #When used with --create, this overwrites existing metadata files
#     parser.add_argument("-FM", "--fetch", default=None, choices = ["Audible", "Goodreads", "Both"]) #interactively fetch metadata from the web
#     parser.add_argument("-I", "--input", required = True) #input folder
#     parser.add_argument("-M", "--move", default = False) #move files to output (copies by default)
#     parser.add_argument("-O", "--output", default=None) #output folder. Will default to a named sub of input, set in setter method
#     parser.add_argument("-Q", "--quick", default=False) #skip confirmation of settings
#     # parser.add_argument("-RN", "--rename", default=None) #rename files
#     parser.add_argument("-RF", "--recurseFetch", default=False) #recursively fetch audio files, presumed to be entire books. Recursives are exclusive.
#     parser.add_argument("-RC", "--recurseCombine", default=False) #recursively fetch audio files, combining files sharing a dir. Recursives are exclusive.
#     parser.add_argument("-RP", "--recursePreserve", default=False) #recursively fetch audio files, preserving chapter files. Recursives are exclusive.
#     parser.add_argument("-S", "--save", default=False) #save settings for future excecutions

#     args = parser.parse_args()
#     log.info("Arguments parsed successfully")
#     Settings.create(args)
        




if __name__ == "__main__":
    log.info("Parsing arguments")
    parser = argparse.ArgumentParser(prog = "Ultimate Audiobooks")
    parser.add_argument("-B", "--batch", default = 10) #batch size
    parser.add_argument("-CL", "--clean", default = False) #overwrite audio file metadata
    parser.add_argument("-CV", "--convert", default = False) #convert to .m4b
    parser.add_argument("-CR", "--create", default = None, choices = ["Infotext", "OPD"]) #create metadata file where nonexistant. Where existant, skip unless --force is enabled
    parser.add_argument("-D", "--default", default=False) #Reset saved settings to default
    parser.add_argument("-FO", "--force", default = False) #When used with --create, this overwrites existing metadata files
    parser.add_argument("-FM", "--fetch", default = None, choices = ["Audible", "Goodreads", "Both"]) #interactively fetch metadata from the web
    parser.add_argument("-I", "--input", required = True) #input folder
    parser.add_argument("-M", "--move", default = False) #move files to output (copies by default)
    parser.add_argument("-O", "--output", default = None) #output folder. Will default to a named sub of input, set in setter method
    parser.add_argument("-Q", "--quick", default = False) #skip confirmation of settings
    parser.add_argument("-RN", "--rename", default = None) #rename files #TODO
    parser.add_argument("-RF", "--recurseFetch", default = False) #recursively fetch audio files, presumed to be entire books. Recursives are exclusive.
    parser.add_argument("-RC", "--recurseCombine", default = False) #recursively fetch audio files, combining files sharing a dir. Recursives are exclusive.
    parser.add_argument("-RP", "--recursePreserve", default = False) #recursively fetch audio files, preserving chapter files. Recursives are exclusive.
    parser.add_argument("-S", "--save", default = False) #save settings for future excecutions

    args = parser.parse_args()
    log.debug("Arguments parsed successfully")

    main(args)