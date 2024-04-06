import argparse
# from Settings import settings
import Settings
from FileManagement import *
import logging as log

'''
DEBUG
INFO
WARNING
ERROR
CRITICAL
'''
#TODO change level before release
log.basicConfig(level=log.DEBUG, format = "%(asctime)s%(levelname)s: %(message)s", datefmt='%H:%M:%S')

def main(args):
    #TODO change level before release
    # log.basicConfig(level=log.DEBUG, format = "%(asctime)s%(levelname)s: %(message)s", datefmt='%H:%M:%S')

    # processArgs()
    Settings.create(args)
    processBooks()




def processBooks():

    if (settings.recurseFetch and settings.recurseCombine) or (settings.recurseFetch and settings.recursePreserve) or (settings.recurseCombine and settings.recursePreserve):
        log.critical("Incompatible processing modes selected. Enable only one processing mode. Exiting...")
        #TODO ERROR
        pass

    elif settings.recurseFetch:
        recursivelyFetchBatch()

    elif settings.recurseCombine:
        recursivelyCombineBatch()

    elif settings.recursePreserve:
        recursivelyPreserveBatch()

    else:
        singleLevelBatch()



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
    parser.add_argument("-FO", "--force", False) #When used with --create, this overwrites existing metadata files
    parser.add_argument("-FM", "--fetch", default=None, choices = ["Audible", "Goodreads", "Both"]) #interactively fetch metadata from the web
    parser.add_argument("-I", "--input", required = True) #input folder
    parser.add_argument("-M", "--move", default = False) #move files to output (copies by default)
    parser.add_argument("-O", "--output", default=None) #output folder. Will default to a named sub of input, set in setter method
    parser.add_argument("-Q", "--quick", default=False) #skip confirmation of settings
    # parser.add_argument("-RN", "--rename", default=None) #rename files
    parser.add_argument("-RF", "--recurseFetch", default=False) #recursively fetch audio files, presumed to be entire books. Recursives are exclusive.
    parser.add_argument("-RC", "--recurseCombine", default=False) #recursively fetch audio files, combining files sharing a dir. Recursives are exclusive.
    parser.add_argument("-RP", "--recursePreserve", default=False) #recursively fetch audio files, preserving chapter files. Recursives are exclusive.
    parser.add_argument("-S", "--save", default=False) #save settings for future excecutions

    args = parser.parse_args()
    log.info("Arguments parsed successfully")

    main(args)