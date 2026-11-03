"""Output naming: turns a --rename template into the folders and filename a book lands at.

Pure functions only (no disk access, no imports from Settings or Util), so every front end and every
processing mode can share them. A template is a relative path under the output folder. "/" separates
folder levels and the last segment is the filename stem; the extension is added by the caller.
Each segment is free text mixing {placeholders}, e.g. "{author}/{series} {volume} - {title}/{title}".
"""
import re
import string
from types import SimpleNamespace

#Characters stripped from every name that reaches the output. The comma ban is intentional.
ILLEGAL_CHARS = re.compile(r'[<>"|?’:,*\']')

#Placeholder values additionally lose path separators and control characters, so a title like "AC/DC"
#can never create an extra folder. Literal text in the template is left alone.
_VALUE_CHARS = re.compile(r'[<>"|?’:,*\'/\\\x00-\x1F]')

PLACEHOLDERS = ("author", "authors", "title", "subtitle", "series", "volume", "narrator", "narrators",
                "publisher", "year", "genre", "asin", "isbn", "filename")

DEFAULT_TEMPLATE_FETCH = "{author}/{title}/{title}"  #the layout books have always had when fetching
DEFAULT_TEMPLATE = "{filename}"                      #flat, original names, when not fetching

MAX_SEGMENT_BYTES = 200  #most filesystems cap a name at 255 bytes; leave room for the extension and " - N"

#stand-in book for previews, so the GUI and dry run can show what a template does without a real fetch
SAMPLE_BOOK = SimpleNamespace(
    author="Barnaby Quillfeather", authors=["Barnaby Quillfeather"], title="How to Befriend a Goose",
    subtitle="A Cautionary Tale", series="The Honk Chronicles", volumeNumber="1",
    narrator="Penelope Honkworth", narrators=["Penelope Honkworth", "Sir Reginald Waddle"],
    publisher="Soggy Bread Press", publishYear="2021", genres=["Comedy"], asin="B000000000", isbn="9780000000000")
SAMPLE_FILENAME = "goose-book-final-v2"


def sanitizeName(text):
    return _VALUE_CHARS.sub('', text)


def effectiveTemplate(settings):
    #the user's template, or the layout that matches how the run behaved before --rename existed
    custom = (settings.rename or "").strip()
    if custom:
        return custom
    return DEFAULT_TEMPLATE_FETCH if settings.fetch else DEFAULT_TEMPLATE


def usesMetadata(template):
    #True when the template needs anything beyond the file's own name, i.e. fetched metadata
    return any(field not in (None, "filename")
               for segment in str(template).split('/') for _, field, _, _ in _parse(segment))


def _parse(segment):
    #list of (literal, fieldName, spec, conversion); raises ValueError on unbalanced braces
    return list(string.Formatter().parse(segment))


def _applySpec(value, spec):
    #Format spec for a value. Numbers pad as numbers ("{volume:02}" -> "01", "1.5" -> "01.5"); anything
    #else is a plain string format. A spec that doesn't fit the value leaves it unchanged.
    if not spec or not value:
        return value
    try:
        if re.fullmatch(r'\d+', value):
            return format(int(value), spec)
        whole, dot, fraction = value.partition('.')
        if dot and whole.isdigit() and fraction.isdigit():
            return format(int(whole), spec) + dot + fraction
        return format(value, spec)
    except ValueError:
        return value


def validateTemplate(template):
    """Raise ValueError, in words a user can act on, if the template can't be used."""
    if template is None or not str(template).strip():
        raise ValueError("The rename template is empty.")
    template = str(template)
    if '\\' in template:
        raise ValueError("Use / to separate folders in the rename template, not \\.")

    segments = template.split('/')
    for index, segment in enumerate(segments):
        isLast = index == len(segments) - 1
        if not segment.strip():
            if index == 0 and len(segments) > 1:
                raise ValueError("The rename template must be relative to the output folder (no leading /).")
            raise ValueError("The rename template has an empty " + ("filename" if isLast else "folder level") + ".")
        if segment.strip() in ('.', '..'):
            raise ValueError(f"'{segment.strip()}' is not allowed in the rename template.")

        try:
            parts = _parse(segment)
        except ValueError:
            raise ValueError(f"Unbalanced braces in the rename template: {segment}") from None

        for literal, field, spec, conversion in parts:
            if field is None:
                continue
            if conversion:
                raise ValueError(f"{{{field}!{conversion}}} is not supported; use {{{field}}}.")
            if field not in PLACEHOLDERS:
                raise ValueError(f"Unknown placeholder {{{field}}} in the rename template. "
                                 f"Available: {', '.join('{' + p + '}' for p in PLACEHOLDERS)}")
            if spec and not _specFits(spec):
                raise ValueError(f"Bad format '{spec}' for {{{field}}} in the rename template.")


def _specFits(spec):
    #valid when it formats a number or a word; a spec that suits neither is a typo
    for sample in ("1", "Dune"):
        try:
            if re.fullmatch(r'\d+', sample):
                format(int(sample), spec)
            else:
                format(sample, spec)
            return True
        except ValueError:
            continue
    return False


def _lookup(md, filename):
    #raw (unsanitized) value for every placeholder; empty string when the book has no such data
    def joined(items):
        return " & ".join(i for i in (items or []) if i)

    return {
        "author": md.author,
        "authors": joined(md.authors),
        "title": md.title or filename,  #without metadata the file's own name is the best title there is
        "subtitle": md.subtitle,
        "series": md.series,
        "volume": md.volumeNumber,
        "narrator": md.narrator,
        "narrators": joined(md.narrators),
        "publisher": md.publisher,
        "year": md.publishYear,
        "genre": md.genres[0] if md.genres else "",
        "asin": md.asin,
        "isbn": md.isbn,
        "filename": filename,
    }


def _renderSegment(segment, values, missing):
    #None when the segment has placeholders and every one of them is empty (the level is dropped).
    #missing collects the names of placeholders that had no value, in the order they were met.
    out = []
    placeholders = 0
    filled = 0
    sawEmpty = False
    for literal, field, spec, _ in _parse(segment):
        out.append(literal)
        if field is None:
            continue
        placeholders += 1
        value = sanitizeName(str(values[field] or "")).strip()
        value = _applySpec(value, spec)
        if value:
            filled += 1
        else:
            sawEmpty = True
            if field not in missing:
                missing.append(field)
        out.append(value)

    if placeholders and not filled:
        return None

    text = "".join(out)
    if sawEmpty:
        text = _tidy(text)
    return _finish(text)


def _tidy(text):
    #Clean up what an empty placeholder leaves behind: "  - Title", "Series - - Title", "Title ()".
    #Only run when something was empty, so a real title that starts with "-" or "#" is never touched.
    text = re.sub(r'\(\s*\)|\[\s*\]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s[-–—]\s(?:[-–—]\s)+', ' - ', text)
    return text.strip(' -–—_#:')


def _finish(text):
    text = text.strip().rstrip('. ').lstrip('.')  #no hidden files, no trailing dots (not valid on every filesystem)
    while len(text.encode('utf-8')) > MAX_SEGMENT_BYTES:
        text = text[:-1]
    return text.rstrip('. ')


def resolve(template, md, filename):
    """Folders and filename stem for a book. Returns (folders, stem, missing): folders is a list of folder names
    under the output folder (possibly empty), stem has no extension, and missing lists the placeholders that had
    no value and so were left out of the name. filename is the book's original name without extension, used for
    {filename} and as the fallback for {title} and for an empty result."""
    values = _lookup(md, filename)
    segments = str(template).split('/')
    missing = []

    folders = []
    for segment in segments[:-1]:
        rendered = _renderSegment(segment, values, missing)
        if rendered:
            folders.append(rendered)

    stem = _renderSegment(segments[-1], values, missing)
    if not stem:
        stem = _finish(sanitizeName(filename).strip()) or "Audiobook"
    return folders, stem, missing


def preview(template, suffix=".m4b"):
    """What the template does to a sample book, as a relative path string. Raises ValueError for a bad template."""
    validateTemplate(template)
    folders, stem, _ = resolve(template, SAMPLE_BOOK, SAMPLE_FILENAME)
    return "/".join(folders + [stem + suffix])
