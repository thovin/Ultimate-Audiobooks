import logging
from pathlib import Path
from Settings import getSettings
import shutil

log = logging.getLogger(__name__)
settings = None

# Track all skipped and failed books
_skips = []
_fails = []

# Map current paths to original paths (for items moved to temp folders)
_originalPaths = {}

def loadSettings():
    global settings
    settings = getSettings()

def setOriginalPath(currentPath, originalPath):
    """
    Register the original path for an item that may be moved (e.g., to temp folder).
    
    Args:
        currentPath: Current path of the item (may be in temp folder)
        originalPath: Original path of the item (before moving to temp)
    """
    # Resolve to absolute paths for consistent lookups
    current = Path(currentPath).resolve()
    original = Path(originalPath).resolve()
    _originalPaths[current] = original

def _getRelativePath(item):
    """
    Get the relative path from the master input directory to the item.
    Uses original path if the item was moved to a temp folder.
    Returns the item name if it's not under the input directory.
    """
    if settings is None:
        loadSettings()
    
    item = Path(item).resolve()
    
    # Check if we have an original path for this item (e.g., moved to temp)
    if item in _originalPaths:
        item = _originalPaths[item]
    
    try:
        # Get relative path from master input directory
        masterInput = Path(settings.input).resolve()
        relPath = item.relative_to(masterInput)
        # Convert to string with forward slashes for readability
        return str(relPath).replace('\\', '/')
    except ValueError:
        # Item is not under master input directory, just return the name
        return item.name

def _getSkipDir():
    """Get the skip directory path (does not create it)."""
    if settings is None:
        loadSettings()
    infolder = Path(settings.input)
    return infolder.parent.joinpath("Ultimate Audiobook skips")

def _getFailDir():
    """Get the fail directory path (does not create it)."""
    if settings is None:
        loadSettings()
    infolder = Path(settings.input)
    return infolder.parent.joinpath("Ultimate Audiobook fails")

def _moveItem(item, destDir, itemType="book"):
    """
    Move a file or folder to destination directory.
    Creates the destination directory if it doesn't exist.
    
    Args:
        item: Path object (file or folder) to move
        destDir: Destination directory Path
        itemType: String for logging ("book", "file", "folder")
    """
    item = Path(item)
    if not item.exists():
        log.warning(f"{itemType.capitalize()} no longer exists, cannot move: {item.name}")
        return False
    
    # Create destination directory only when needed
    destDir.mkdir(exist_ok=True)
    dest = destDir / item.name
    
    # Handle name conflicts
    counter = 1
    original_dest = dest
    while dest.exists():
        if item.is_dir():
            dest = destDir / f"{item.name} - {counter}"
        else:
            stem = item.stem
            suffix = item.suffix
            dest = destDir / f"{stem} - {counter}{suffix}"
        counter += 1
    
    try:
        if item.is_dir():
            shutil.move(str(item), str(dest))
            log.info(f"Moved {itemType} folder: {item.name} -> {dest.name}")
        else:
            item.rename(dest)
            log.info(f"Moved {itemType} file: {item.name} -> {dest.name}")
        return True
    except Exception as e:
        log.error(f"Error moving {itemType} {item.name}: {e}")
        return False

def skipBook(item, reason=None):
    """
    Mark a book (file or folder) as skipped and move it immediately.
    
    Args:
        item: Path object (file or folder) to mark as skipped
        reason: Optional reason string for logging
    """
    item = Path(item)
    
    # Avoid duplicates
    if item in _skips:
        log.debug(f"Book already in skip list: {item.name}")
        return
    
    _skips.append(item)
    
    reason_msg = f" - {reason}" if reason else ""
    relPath = _getRelativePath(item)
    log.info(f"Skipping book: \"{relPath}\"{reason_msg}")
    
    # Move immediately (directory will be created in _moveItem if needed)
    skipDir = _getSkipDir()
    _moveItem(item, skipDir, "book")

def failBook(item, reason=None):
    """
    Mark a book (file or folder) as failed and move it immediately.
    
    Args:
        item: Path object (file or folder) to mark as failed
        reason: Optional reason string for logging
    """
    item = Path(item)
    
    # Avoid duplicates
    if item in _fails:
        log.debug(f"Book already in fail list: {item.name}")
        return
    
    _fails.append(item)
    
    reason_msg = f" - {reason}" if reason else ""
    relPath = _getRelativePath(item)
    log.error(f"Failed book: \"{relPath}\"{reason_msg}")
    
    # Move immediately (directory will be created in _moveItem if needed)
    failDir = _getFailDir()
    _moveItem(item, failDir, "book")

def getSkips():
    """Get a copy of the skip list."""
    return _skips.copy()

def getFails():
    """Get a copy of the fail list."""
    return _fails.copy()

def getSkipCount():
    """Get the number of skipped books."""
    return len(_skips)

def getFailCount():
    """Get the number of failed books."""
    return len(_fails)

def clearSkips():
    """Clear the skip list (for testing/reset)."""
    _skips.clear()

def clearFails():
    """Clear the fail list (for testing/reset)."""
    _fails.clear()

def printSummary():
    """Print a summary of all skipped and failed books at the end."""
    if len(_skips) == 0 and len(_fails) == 0:
        log.info("No books were skipped or failed.")
        return
    
    log.info("=" * 60)
    log.info("SKIP/FAIL SUMMARY")
    log.info("=" * 60)
    
    if len(_skips) > 0:
        log.info(f"\nSkipped books ({len(_skips)}):")
        for item in _skips:
            relPath = _getRelativePath(item)
            log.info(f"  - {relPath}")
    
    if len(_fails) > 0:
        log.info(f"\nFailed books ({len(_fails)}):")
        for item in _fails:
            relPath = _getRelativePath(item)
            log.info(f"  - {relPath}")
    
    log.info("=" * 60)
