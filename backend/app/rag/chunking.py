"""Turn documents into text and text into overlapping chunks."""
import io
import re
from typing import List

MAX_PDF_PAGES = 500
_SENT = re.compile(r"(?<=[.!?])\s+")


class ExtractError(Exception):
    pass


def extract_text(fmt: str, data: bytes) -> str:
    if fmt in ("txt", "md"):
        return data.decode("utf-8", errors="replace")
    if fmt == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ExtractError("PDF support needs the 'pypdf' package on the server")
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractError("This PDF is password-protected")
            pages = [(p.extract_text() or "") for p in reader.pages[:MAX_PDF_PAGES]]
        except ExtractError:
            raise
        except Exception as e:
            raise ExtractError(f"Could not read this PDF: {type(e).__name__}")
        text = "\n\n".join(pages).strip()
        if not text:
            raise ExtractError("No text found in this PDF (scanned images need OCR, which is not supported yet)")
        return text
    raise ExtractError(f"Unsupported document type '{fmt}'")


def _units(text: str, size: int) -> List[str]:
    """Paragraphs → sentences → hard splits, so no unit exceeds `size`."""
    out: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            out.append(para)
            continue
        for s in _SENT.split(para):
            s = s.strip()
            while len(s) > size:
                out.append(s[:size])
                s = s[size:]
            if s:
                out.append(s)
    return out


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> List[str]:
    if size < 100:
        raise ValueError("Chunk size must be at least 100 characters")
    if not 0 <= overlap < size // 2:
        raise ValueError("Overlap must be at least 0 and less than half the chunk size")
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for u in _units(text, size):
        add = len(u) + (2 if cur else 0)
        if cur and cur_len + add > size:
            chunks.append("\n\n".join(cur))
            keep: List[str] = []
            n = 0
            for prev in reversed(cur):                      # carry a tail of whole units as overlap
                if n + len(prev) > overlap:
                    break
                keep.insert(0, prev)
                n += len(prev) + 2
            cur, cur_len = keep, sum(len(x) for x in keep) + 2 * max(len(keep) - 1, 0)
            add = len(u) + (2 if cur else 0)
        cur.append(u)
        cur_len += add
    if cur:
        tail = "\n\n".join(cur)
        if not chunks or tail != chunks[-1]:
            chunks.append(tail)
    return chunks
