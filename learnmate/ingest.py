"""Turn subtitles, PDF, PPTX and TXT into 'chunks' that keep their exact page / slide / time / line reference."""
import io
import re
import zipfile

import config
from errors import UserError

DOC_EXT = {".pdf", ".pptx", ".txt", ".md", ".csv", ".docx"}
SUB_EXT = {".srt", ".vtt"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi"}


# ---------- subtitles --------------------------------------------------------
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")


def _secs(m):
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000


def parse_subtitles(text):
    """Works for .srt and .vtt. Returns [{'start','end','text'}]."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").lstrip("\ufeff").strip()):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        i = next((k for k, l in enumerate(lines) if "-->" in l), None)
        if i is None:
            continue
        a, b = lines[i].split("-->", 1)
        ma, mb = _TIME.search(a), _TIME.search(b)
        body = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1:])).strip()
        if ma and mb and body:
            cues.append({"start": _secs(ma), "end": _secs(mb), "text": body})
    cues.sort(key=lambda c: c["start"])
    if not cues:
        raise UserError("bad_transcript", "No timestamped lines found in the transcript.",
                        "Use an .srt or .vtt file with lines like 00:00:01,000 --> 00:00:04,000.")
    return cues


def fetch_youtube_transcript(video_id):
    """Automatically fetch YouTube video subtitles using youtube_transcript_api.
    Returns [{'start', 'end', 'text'}]. Returns empty list if unavailable."""
    if not video_id:
        return []
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        yta = YouTubeTranscriptApi()
        raw_list = None
        # Try fetching English or preferred language first
        try:
            raw_list = yta.fetch(video_id, languages=("en", "en-US", "en-GB")).to_raw_data()
        except Exception:
            # Fall back to listing any available transcripts (auto-generated or manual)
            transcripts = yta.list(video_id)
            for t in transcripts:
                try:
                    raw_list = t.fetch().to_raw_data()
                    if raw_list:
                        break
                except Exception:
                    continue
        if not raw_list:
            return []
        cues = []
        for item in raw_list:
            start = float(item.get("start", 0.0))
            duration = float(item.get("duration", 0.0))
            text = str(item.get("text", "")).strip()
            # Clean bracketed music/noise notations like [Music], [Applause]
            cleaned_text = re.sub(r"^\[.*?\]$", "", text).strip()
            if cleaned_text:
                cues.append({"start": round(start, 2), "end": round(start + max(duration, 0.5), 2), "text": cleaned_text})
        cues.sort(key=lambda c: c["start"])
        return cues
    except Exception:
        return []


def chunk_cues(cues):
    """Group cues into 30-60 second chunks. A video chunk unlocks when it starts."""
    chunks, cur = [], []

    def flush():
        nonlocal cur
        if cur:
            chunks.append({"type": "video", "start": cur[0]["start"], "end": cur[-1]["end"],
                           "unlock": cur[0]["start"], "text": " ".join(c["text"] for c in cur)})
            cur = []

    for c in cues:
        if cur and c["end"] - cur[0]["start"] > config.CHUNK_MAX_S:
            flush()
        cur.append(c)
        if cur[-1]["end"] - cur[0]["start"] >= config.CHUNK_MIN_S:
            flush()
    flush()
    return chunks


# ---------- documents --------------------------------------------------------
def split_text(text, max_chars=900):
    """Split long page text at paragraph / sentence ends. Every piece keeps the SAME page number."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    pieces, cur = [], ""
    for part in re.split(r"(?<=[.!?\n])\s+", text):
        if cur and len(cur) + len(part) > max_chars:
            pieces.append(cur.strip())
            cur = ""
        cur += part + " "
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def chunks_from_pages(kind, pages, doc, unlock_map=None):
    """pages = [(number, text)]. unlock_map (demo course only) = {'3': 90.0}: the video second a page unlocks.
    Pages missing from a given unlock_map are skipped, never guessed."""
    chunks = []
    for num, text in pages:
        unlock = None
        if unlock_map is not None:
            if str(num) not in unlock_map:
                continue
            unlock = float(unlock_map[str(num)])
        label = f"{doc} p.{num}" if kind == "pdf" else f"{doc} slide {num}"
        for piece in split_text(text):
            chunks.append({"type": kind, "doc": doc, "ref": num, "label": label, "unlock": unlock, "text": piece})
    return chunks


def chunks_from_txt(text, doc, max_chars=900):
    chunks, cur, start = [], [], 1
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines, 1):
        cur.append(line)
        if sum(len(l) for l in cur) >= max_chars or i == len(lines):
            body = "\n".join(cur).strip()
            if body:
                chunks.append({"type": "txt", "doc": doc, "ref": start, "unlock": None,
                               "label": f"{doc} lines {start}-{i}", "text": body})
            cur, start = [], i + 1
    return chunks


def read_pdf(data):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise UserError("pdf_unavailable", "PDF support is not installed on the server.", "pip install pymupdf", 500)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise UserError("bad_pdf", "This PDF could not be opened.", "Check that the file is not damaged or password-protected.")
    if doc.page_count > config.MAX_PAGES:
        raise UserError("too_long", f"PDF has more than {config.MAX_PAGES} pages.", "Split the file and upload the parts.")
    return [(i + 1, page.get_text().strip()) for i, page in enumerate(doc)]


def read_pptx(data):
    from pptx import Presentation
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception:
        raise UserError("bad_pptx", "This PowerPoint file could not be opened.", "Save it again as .pptx (not .ppt).")
    if len(prs.slides) > config.MAX_PAGES:
        raise UserError("too_long", f"Deck has more than {config.MAX_PAGES} slides.", "Split the deck.")
    out = []
    for i, slide in enumerate(prs.slides, 1):
        parts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        for sh in slide.shapes:
            if sh.has_table:
                parts += [c.text for row in sh.table.rows for c in row.cells]
        if slide.has_notes_slide:
            parts.append(slide.notes_slide.notes_text_frame.text)
        out.append((i, "\n".join(p for p in parts if p.strip())))
    return out


# ---------- validation + one entry point --------------------------------------
def _ext(filename):
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def extract_document(filename, data):
    """Validate an uploaded document and return (kind, chunks, page_count). Raises UserError with a helpful hint."""
    ext = _ext(filename)
    if ext not in DOC_EXT:
        raise UserError("bad_type", f"'{ext or 'this file'}' is not supported.", "Upload a .pdf, .pptx or .txt file.", 415)
    if not data:
        raise UserError("empty_file", "The file is empty.")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise UserError("too_big", f"File is larger than {config.MAX_UPLOAD_MB} MB.", "Compress or split it.", 413)
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UserError("bad_pdf", "This file is not a real PDF.", "Export it again as PDF.")
        pages = read_pdf(data)
        chunks = chunks_from_pages("pdf", pages, filename)
        kind, count = "pdf", len(pages)
    elif ext == ".pptx":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            ok = "ppt/presentation.xml" in z.namelist()
            size = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile:
            ok, size = False, 0
        if not ok:
            raise UserError("bad_pptx", "This file is not a real .pptx presentation.", "Save it again as .pptx.")
        if size > 100 * 1024 * 1024:
            raise UserError("too_big", "The presentation expands to an unsafe size.", "Compress the images.", 413)
        pages = read_pptx(data)
        chunks = chunks_from_pages("slide", pages, filename)
        kind, count = "slide", len(pages)
    elif ext in (".txt", ".md", ".csv"):
        if b"\x00" in data:
            raise UserError("bad_txt", "This does not look like a text file.", "Upload plain UTF-8 text.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise UserError("bad_txt", "The text file is not UTF-8.", "Save it as UTF-8 and upload again.")
        chunks, kind, count = chunks_from_txt(text, filename), "txt", text.count("\n") + 1
    elif ext == ".docx":
        # Extract text from docx zip xml without extra heavy deps
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            xml_content = z.read("word/document.xml").decode("utf-8")
            text = " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml_content))
            chunks, kind, count = chunks_from_txt(text, filename), "doc", max(1, len(text) // 1500)
        except Exception:
            raise UserError("bad_docx", "Could not read Word document.", "Save it as .docx or .pdf.")
    else:
        raise UserError("bad_type", f"Unsupported file type: {ext}")
    if not chunks:
        raise UserError("no_text", "No readable text was found in this file.")
    if sum(len(c["text"]) for c in chunks) > config.MAX_TEXT_CHARS:
        raise UserError("too_big", "The document has too much text.", "Upload a shorter file.", 413)
    return kind, chunks, count
