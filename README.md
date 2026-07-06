# Ultimate Audiobooks

This WIP program is intended to simplify processing audiobook files: fetch metadata, tag files, convert to `.m4b`, merge chapter files, generate sidecar files, and organize everything into a clean library structure ready for apps like Audiobookshelf.

⚠️ **Warning:** Always back up your audiobook files before use. The tool defaults to copying files instead of moving them, but data safety is not guaranteed.

If **fetch** is passed, books are organized into `<output>/<author>/<title>/`. Otherwise they go directly into `<output>`. This will be customizable in the future (`--rename`).

---

## Features

- Copy or move audiobooks into structured folders (`Author/Title`)
- Fetch metadata from **Audible** and/or **Goodreads** (interactive browser + clipboard workflow)
- Clean and overwrite file tags with fetched metadata
- Convert audio files to `.m4b` (via ffmpeg, parallelized across CPU cores)
- Merge multi-chapter folders into single files with chapter markers
- Generate `.opf` metadata sidecar files for library apps like Audiobookshelf
- Batch processing with configurable size
- Problem books are tracked and reported; in move mode they are set aside in `Ultimate Audiobook skips`/`Ultimate Audiobook fails` folders next to the input folder
- Save, reload, and reset settings for repeated use

**Supported input formats:** `.mp3`, `.mp4`, `.m4a`, `.m4b`, `.flac`

---

## Requirements

- **Python 3.13**
- **System dependencies**
  - [ffmpeg](https://ffmpeg.org/) (for conversion and chapter merging)
  - Linux: clipboard utility such as `xclip` or `xsel` (for fetch support)
- **Python libraries** — install with:
  ```
  pip install -r requirements.txt
  ```
  (primary packages: `mutagen`, `requests`, `beautifulsoup4`, `pyperclip`, `psutil`, `pydub`)

---

## Arguments

### Input/Output
- `-I, --input <path>`
  **Required.** Path to input folder containing audiobook files.
- `-O, --output <path>`
  Destination folder. Defaults to a folder named `Ultimate Output` **next to** the input folder (`<input's parent>/Ultimate Output`).
- `-M, --move`
  Move files instead of copying (default is copy). In copy mode, skipped/failed books are left in place; in move mode they are moved to the skips/fails folders.

### Metadata
- `-FM, --fetch [audible|goodreads|both]`
  Interactive metadata fetch. A browser search opens for each book; copy the correct Audible/Goodreads book page link to your clipboard to continue, or copy the word `skip` to skip the book.
- `-CL, --clean`
  Overwrite file tags with fetched metadata (use together with `--fetch`).
- `-CR, --create [INFOTEXT|OPF]`
  Generate metadata sidecar files. (**INFOTEXT is not yet implemented — an OPF is currently created for either choice**)
- `-FO, --force`
  Overwrite existing sidecar files (**not yet implemented**).

### File Conversion
- `-CV, --convert`
  Convert all non-M4B files to `.m4b` (requires ffmpeg). MP3 and FLAC are converted; MP4/M4A are remuxed. Conversions run in parallel.
- `-W, --workers <int>`
  Number of parallel conversion workers. Defaults to an automatic value based on CPU cores and available memory.

### Recursive Processing Mode (choose one — enforced)
Note: Combine and Preserve processing modes can be used on libraries of mixed whole book files and chapter files **as long as** every book has its own folder.
- `-RF, --recurseFetch`
  Process all files in input and subfolders as separate books.
- `-RC, --recurseCombine`
  Combine chapter files within subfolders into complete books with chapter markers. Chapters are ordered by track/disc number tags, with filename-number fallback. **Currently requires `--move`.**
- `-RP, --recursePreserve`
  Treat subfolder files as chapters without combining (**not yet implemented**).

### Execution Control
- `-B, --batch <int>`
  Max number of books per run. Default = 10.
- `-Q, --quick`
  Skip settings confirmation (for scripting).
- `-LL, --logLevel [DEBUG|INFO|WARNING|ERROR|CRITICAL]`
  Set logging verbosity. Default = INFO.
- `-RN, --rename`
  Rename files using a template (**not yet implemented**).

### Saved Settings
Settings are stored in `settings.json` next to `Main.py`, so they work no matter which directory you launch from.
- `-S, --save`
  Save this run's settings (after defaults are resolved) for future use.
- `-L, --load`
  Load saved settings. Any option you explicitly pass on the command line overrides the saved value. Loading never happens automatically — `-L` is always required.
- `-D, --default`
  Reset saved settings by deleting `settings.json`, then continue the run with pure command-line values. Cannot be combined with `--load`. Combine with `--save` to reset and save fresh settings in one run.

---

# How to run

Clone this project, install requirements, then run `Main/Main.py` with args (examples below) — or launch the GUI.

```
pip install -r requirements.txt
python Main/Main.py --input /path/to/audiobooks [OPTIONS]
```

## GUI

A desktop GUI (CustomTkinter) covers the same features as the CLI with a live activity log:

```
python Main/GUI.py
```

- All options from the CLI are available as form controls; Start kicks off a run with live log output
- Metadata fetch uses an in-app panel per book. **Recommended workflow: simply copy the book page link in your browser** — the GUI detects it and continues automatically, no extra clicks. A paste box, Open Search button, and Skip button are also available in the panel. (The CLI keeps the pure clipboard workflow.)
- Interface settings (in the sidebar): Dark/Light/System appearance and a UI scale control (90%–150%, default 110%) to size the whole interface to your screen
- Save/Load Settings buttons share the same `settings.json` as the CLI's `-S`/`-L`
- Linux note: tkinter requires the system Tk package (`sudo pacman -S tk` on Arch, `sudo apt install python3-tk` on Debian/Ubuntu)

---

# Example calls

The most basic use. All audio files in the root **input** folder will be processed as individual books and copied to `c:\some\input\Ultimate Output` (a sibling of the input folder). Files in subdirectories will be ignored.

`Main.py --input c:\some\input\folder`

&nbsp;

This will **fetch** metadata interactively, **clean** the file tags, **create** an OPF metadata file, and **move** the books to `c:\some\input\Ultimate Output\<author>\<title>`. This is done for all books in the input folder and any subfolders until completion or the **batch** size is reached.

`Main.py --clean --create opf --fetch both --move --recurseFetch --input c:\some\input\folder`

&nbsp;

This will set the **batch** size to be virtually infinite, recursively combine and process all chapter files, and **output** them to `c:\some\output\folder`. It also **saves** the settings used on this execution for later reuse.

`Main.py --batch 99999 --save --move --recurseCombine --input c:\some\input\folder --output c:\some\output\folder`

&nbsp;

This will **load** the previously saved settings, overriding **input**, **move**, and **quick** with the values given here. Everything else (batch size, output, recursive mode, etc.) comes from the save file.

`Main.py --load --quick --move --input c:\some\input\folder`
