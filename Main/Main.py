import argparse
# from Settings import settings
import Settings


def __main__():





def processArgs(parser):
    parser = argparse.ArgumentParser(prog = "Ultimate Audiobooks")
    parser.add_argument("-B", "--batch", default = 10) #batch size
    parser.add_argument("-CL", "--clean", default = False) #overwrite audio file metadata
    parser.add_argument("-CV", "--convert", default = False) #convert to .m4b
    parser.add_argument("-CR", "--create", default = None, choices = ["Infotext", "OPD"]) #create metadata file
    parser.add_argument("-D", "--default", default=False) #Reset saved settings to default
    parser.add_argument("-FO", "--force", False) #force metadata overwrite at the file level
    parser.add_argument("-FM", "--fetch", default=None, choices = ["Audible", "Goodreads", "Both"]) #interactively fetch metadata from the web
    parser.add_argument("-I", "--input", required = True) #input folder
    parser.add_argument("-M", "--move", default = False) #move files to output (copies by default)
    parser.add_argument("-O", "--output", default=None) #output folder. Will default to a named sub of input, set in setter method
    parser.add_argument("-Q", "--quick", default=False) #skip confirmation of settings
    # parser.add_argument("-RN", "--rename", default=None) #rename files
    parser.add_argument("-RF", "--recurseFetch", default=False) #recursively fetch all audio files, presumed to be entire books. Recursives are exclusive.
    parser.add_argument("-RC", "--recurseCombine", default=False) #recursively fetch all audio files, combining files sharing a dir. Recursives are exclusive.
    parser.add_argument("-S", "--save", default=False) #save settings for future excecutions

    Settings.create()
