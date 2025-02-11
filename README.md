This WIP program is intended to simplify processing audiobook files. <ins>I strongly suggest creating a copy of any important files before running this program on them.</ins> Default functionality is set to copy, which theoretically should protect original files even in case of an error. However, I can not guarantee the safety of original files while still in development.

If **fetch** is passed, books will be moved to &lt;outpath&gt;/&lt;author&gt;/&lt;title&gt;. Otherwise they will be moved to &lt;outpath&gt;. This will be customizable in the future.

Dependancies:
- ffmpeg
- python libraries:
    - pydub
    - mutagen
    - requests
    - bs4
    - pyperclip
    - psutil

Linux based systems will additionally need a copy/paste mechanism, such as xclip or xselect.

&nbsp;

# Arguments:

- Batch size (-B, --batch) // arguments: **int** &lt;batchsize&gt;, default = 10
    - Set the amount of books to be processed
    - NOTE: to the best of the program's ability, count will be based on books processed and not audio files. This means that a 40 chapter book would only count as 1 towards the count of books processed. How this is determined is based on the processing method chosen.
- Clean metadata (-CL, --clean) // arguments: N/A, default = false, **dependencies: Fetch**
    - Overwrite file metadata with new info. <ins>Results may vary if clean metadata is not **fetched**!</ins>
    - NOTE: if copying (**move** is not passed) only the metadata on the new copy will be cleaned
- Convert to M4B (-CV, --convert) // arguments: N/A, default = false, **dependencies: ffmpeg**
    - Convert all non-M4B files to M4B. <ins>**Requires ffmpeg installed on the system!**</ins>
    - NOTE: if copying (**move** is not passed) a new M4B file will instead be created
- Create metadata files (-CR, --create) // arguments: \["INFOTEXT", "OPF"\], default = N/A, **dependencies: Fetch**
    - Creates an infotext or OPF file in destination folder. This can be useful for libraries that use these files for metadata, such as audiobookshelf.
- Default (-D, --default) // arguments: N/A, default = false
    - Erases saved settings, setting any arguments not called on this execution to their default values.
    - **NOTE: save/load/default settings features subject to change**
    - **NOTE: this feature has not yet been added**
- Force (-FO, --force) // arguments: N/A, default = false, **dependencies: Create**
    - This will overwrite any existing metadata files when **Creating** new ones
    - **NOTE: this feature has not yet been added**
- Fetch metadata (-FM, --fetch) // arguments: \["audible", "goodreads", "both"\], default = N/A
    - This will allow you to interactively fetch metadata for each book. A new tab will be opened in a browser searching for the book on the site(s) selected. <ins>You must copy the link of the correct book to continue.</ins> If there is no correct option, copy "skip" to skip the current book.
    - **NOTE: skip behavior is only partially implemented. Results may vary.**
- Input folder (-I, --input) // arguments: **string** &lt;inputFolderPath&gt;, **REQUIRED**
    - Set the input folder. <ins>This is required for execution!</ins>
- Load settings (-L, --load) // arguments: N/A, default = false
    - Load saved settings, if existing. <ins>Any arguments included in this command will override those saved, but will not be saved.</ins>
    - NOTE: if **save** and **load** are both called, the order of operations will be as follows: settings are loaded > passed arguments override > settings are saved
    - NOTE: if **quick** was saved, settings confirmation may be inadvertently skipped!
    - **NOTE: even if required arguments are saved, they must still be supplied when calling the program. This may be changed in the future**
    - **NOTE: save/load/default settings features subject to change**
- Move (-M, --move) // arguments: N/A, default = copy
    - Move input books to destination. If this flag is not passed, books will be copied by default
    - NOTE: future executions of this program will still process any books copied. If you wish to avoid this, you must move or delete any books that have been processed
- Output folder (-O, --output) // arguments: **string** &lt;outputFolderPath&gt;, default = <**input**\>/"Ultimate Output"
    - Set the output folder. If this is not passed, output will default to a newly created subfolder of the **input** folder.
- Quick (-Q, --quick) // arguments: N/A, default = false
    - Skip confirmation of settings. Recommended for scripts and automations calling this program.
- Rename (-RN, --rename) // arguments: **WIP**, default = **WIP**
    - Rename book files according to the input template
    - **NOTE: This feature has not been implemented**
    - NOTE: even if this flag is not passed, numbers will still appended to filenames as needed to prevent overwriting existing book files in the destination
- Recursively fetch books (-RF, --recurseFetch) // arguments = N/A, default = false, EXCLUSIVE
    - Recursively traverse input folder and all subfolders, processing all audio files as books.
    - NOTE: recursive fetch, combine, and preserve are <ins>exclusive.</ins> Only one may be selected! If none are selected only books in the root directory will be processed; all subdirectories will be ignored.
- Recursively combine chapter books (-RC, --recurseCombine) // arguments = N/A, default = false, EXCLUSIVE
    - Recursively traverse subfolders of input, combining all audio files in a given directory. Combination algorithm will sort books based on track number in metadata if available, and numerical values in the filename if not.
    - NOTE: input folder itself is ignored in this operation
    - NOTE: if **convert** is not passed, the filetype of the combined book will be that of the chapters
    - NOTE: solitary files will be processed without any combination operation, allowing this to work on a mixed library of whole and chapter books in separate directories. However, **whole books found in the same directory will be combined.**
    - NOTE: recursive fetch, combine, and preserve are <ins>exclusive.</ins> Only one may be selected! If none are selected only books in the root directory will be processed; all subdirectories will be ignored.
    - **NOTE: This feature is** **partially implemented. Results may vary!**
- Recursively preserve chapter books (-RP, --recursePreserve) // arguments = N/A, default = false, EXCLUSIVE
    - Recursively traverse subfolders of input, processing all files in a directory as if they are the chapters of a book. This will NOT combine the files.
    - NOTE: recursive fetch, combine, and preserve are <ins>exclusive.</ins> Only one may be selected! If none are selected only books in the root directory will be processed; all subdirectories will be ignored.
    - <ins>NOTE: because the chapters are not combined, it is strongly recommended to use **fetch!**</ins> If **fetch** is not called, all chapter files will end up lumped together in the output folder. This behavior will likely be corrected in future through use of **rename**.
    - **NOTE: this feature has not been implemented**
- Save settings (-S, --save) // arguments = N/A, default = false
    - Save this execution's settings for future use
    - NOTE: If **save** and **load** are both called, the order of operations will be as follows: settings are loaded > passed arguments override > settings are saved

&nbsp;

&nbsp;

&nbsp;

# Example calls

The command should be entered with your working directory set to Main

&nbsp;

`Main.py --input c:\some\input\folder`

The most basic use. All files in the root **input** folder will be processed as individual books and copied to "c:\\some\\input\\folder\\Ultimate Output"

&nbsp;

`Main.py --clean --create infotext --fetch both --move --recurseFetch --input c:\some\input\folder`

With the root folder "c:\\some\\input\\folder", this will **fetch** metadata interactively, **clean** the file metadata, **create** an infotext metadata file, and **move** the books to "c:\\some\\input\\folder\\Ultimate Output\\&lt;author&gt;\\&lt;title&gt;". This will be done to all books in the input folder and any subfolders until completion or the **batch size** has been reached.

&nbsp;

`Main.py --batch 99999 --save --recurseCombine --input c:\some\input\folder --output c:\some\output\folder`

With the root folder "c:\\some\\input\\folder", this will set the **batch size** to be virtually infinite, recursively combine and process all chapter files, and **output** them to "c:\\some\\output\\folder". It will also save the settings used on this execution.

&nbsp;

`Main.py --load --quick --move --input c:\some\input\folder`

With the root folder "c:\\some\\input\\folder", this will **load** saved settings and skip confirmation of settings. It will also override saved settings for **move**, **input**, and **quick.**
