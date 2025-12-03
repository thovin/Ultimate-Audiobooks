This WIP program is intended to simplify processing audiobook files.

⚠️ **Warning:** Always back up your audiobook files before use. The tool defaults to copying files instead of moving them, but data safety is not guaranteed.

If **fetch** is passed, books will be moved to &lt;outpath&gt;/&lt;author&gt;/&lt;title&gt;. Otherwise they will be moved to &lt;outpath&gt;. This will be customizable in the future.

---

## Features

- Copy or move audiobooks into structured folders (`Author/Title`)
- Fetch metadata from **Audible** and/or **Goodreads**
- Clean and overwrite file metadata
- Convert audio files to `.m4b` (via ffmpeg)
- Generate metadata sidecar files (`.opf`, `infotext`) for library apps like Audiobookshelf
- Combine or preserve multi-chapter audiobooks
- Batch processing
- Save and reload settings for repeated use

---

## Requirements

- **System dependencies**
  - [ffmpeg](https://ffmpeg.org/) (for audio conversion)
  - Linux: clipboard utility such as `xclip` or `xsel` (for fetch support)

- **Python libraries**
  - `pydub`
  - `mutagen`
  - `requests`
  - `beautifulsoup4`
  - `pyperclip`
  - `psutil`

---


## Arguments

### Input/Output
- `-I, --input <path>`  
  **Required.** Path to input folder containing audiobook files.  
- `-O, --output <path>`  
  Destination folder. Defaults to `<input>/Ultimate Output`.  
- `-M, --move`  
  Move files instead of copying (default is copy).

### Metadata
- `-FM, --fetch [audible|goodreads|both]`  
  Interactive metadata fetch. Opens browser search, paste the correct link to continue.  
- `-CL, --clean`  
  Overwrite metadata with fetched info.  
- `-CR, --create [INFOTEXT|OPF]`  
  Generate metadata sidecar files.  
- `-FO, --force`  
  Overwrite existing sidecar files (**not yet implemented**).  

### File Conversion
- `-CV, --convert`  
  Convert all non-M4B files to `.m4b` (requires ffmpeg).

### Recursive Processing Mode (choose one)
Note: Combine and Preserve processing modes can be used on libraries of mixed whole book files and chapter files **as long as** every book has its own folder
- `-RF, --recurseFetch`  
  Process all files in input and subfolders as separate books.  
- `-RC, --recurseCombine`  
  Combine chapter files within subfolders into complete books.  
- `-RP, --recursePreserve`  
  Treat subfolder files as chapters without combining (**not yet implemented**).

### Execution Control
- `-B, --batch <int>`  
  Max number of books per run. Default = 10.  
- `-Q, --quick`  
  Skip settings confirmation (for scripting).  
- `-LL, --loglevel [DEBUG|INFO|WARNING|ERROR|CRITICAL]`  
  Set logging verbosity. Default = INFO. Useful for debugging or reducing console output.  
- `-S, --save` / `-L, --load` / `-D, --default`  
  Save, load, or reset settings (**not yet implemented**).  
- `-RN, --rename`  
  Rename files using a template (**not yet implemented**).

&nbsp;

---

# How to run

Clone this project, set working directory to Main in term, run Main.py with args. Examples below.

---

# Example calls

The most basic use. All audio files in the root **input** folder will be processed as individual books and copied to "c:\\some\\input\\folder\\Ultimate Output". Files in subdirectories will be ignored.

`Main.py --input c:\some\input\folder`

&nbsp;

With the root folder "c:\\some\\input\\folder", this will **fetch** metadata interactively, **clean** the file metadata, **create** an infotext metadata file, and **move** the books to "c:\\some\\input\\folder\\Ultimate Output\\&lt;author&gt;\\&lt;title&gt;". This will be done to all books in the input folder and any subfolders until completion or the **batch** size has been reached.

`Main.py --clean --create infotext --fetch both --move --recurseFetch --input c:\some\input\folder`

&nbsp;

With the root folder "c:\\some\\input\\folder", this will set the **batch** size to be virtually infinite, recursively combine and process all chapter files, and **output** them to "c:\\some\\output\\folder". It will also save the settings used on this execution. (**Save functionality is not yet implemented)

`Main.py --batch 99999 --save --recurseCombine --input c:\some\input\folder --output c:\some\output\folder`

&nbsp;

With the root folder "c:\\some\\input\\folder", this will **load** saved settings and skip confirmation of settings. It will also override saved settings for **move**, **input**, and **quick.** (**Save/Load functionality is not yet implemented)

`Main.py --load --quick --move --input c:\some\input\folder`






