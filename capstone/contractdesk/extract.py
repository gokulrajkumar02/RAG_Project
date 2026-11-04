"""
Document -> text. Digital PDFs: pypdf's text layer. Scanned PDFs (no text layer): really OCR the page images
with RapidOCR (PP-OCR models on onnxruntime). Nothing is simulated: the scanned pages are pixels, the OCR is a
real engine, and ocr_metrics() scores its output against the text the generator drew.

How a scan is detected: a page whose text layer has fewer than MIN_TEXT_CHARS characters but which carries an
image. The manifest does not say which documents are scans.

OCR output is cached by the SHA-256 of the page image, so re-running ingestion after a parser change does not
repeat minutes of OCR.
"""

import hashlib
import io
import json
import os
import re
import statistics
import time
from concurrent.futures import ProcessPoolExecutor

from . import paths

MIN_TEXT_CHARS = 40
FURNITURE = re.compile(r"^\s*Page\s*\d+(\s*of\s*\d+)?\s*$", re.I)
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        # One onnxruntime thread per engine: extraction runs one engine per worker process, and letting every
        # engine spawn a thread per core made 8 workers thrash (measured: ~0.35 pages/s for the pool).
        _ENGINE = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    return _ENGINE


def engine_version():
    try:
        from importlib.metadata import version
        return f"rapidocr-onnxruntime {version('rapidocr-onnxruntime')} / onnxruntime {version('onnxruntime')}"
    except Exception:
        return "rapidocr-onnxruntime (version unknown)"


def boxes_to_lines(result):
    """RapidOCR [(box, text, score), ...] -> (text lines top-to-bottom, mean score, n boxes)."""
    if not result:
        return [], 0.0, 0
    items = []
    for box, text, score in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append(dict(cy=sum(ys) / 4, h=max(ys) - min(ys), x=min(xs), text=text, score=float(score)))
    items.sort(key=lambda i: i["cy"])
    tol = 0.6 * statistics.median(i["h"] for i in items)
    lines, cur = [], [items[0]]
    for it in items[1:]:
        if abs(it["cy"] - statistics.fmean(c["cy"] for c in cur)) <= tol:
            cur.append(it)
        else:
            lines.append(cur)
            cur = [it]
    lines.append(cur)
    out = [" ".join(i["text"] for i in sorted(l, key=lambda i: i["x"])) for l in lines]
    return out, statistics.fmean(i["score"] for i in items), len(items)


def ocr_image(pil_image):
    import numpy as np
    arr = np.asarray(pil_image.convert("RGB"))
    result, _t = _engine()(arr)
    return boxes_to_lines(result)


def _page_images(page):
    out = []
    for im in page.images:
        out.append(im.image)
    return out


def extract_pdf(pdf_path):
    """-> dict(pages=[{n, text, source, mean_conf, boxes, seconds}], source, seconds)."""
    from pypdf import PdfReader

    t0 = time.time()
    reader = PdfReader(pdf_path)
    pages = []
    for n, page in enumerate(reader.pages, 1):
        layer = (page.extract_text() or "").strip()
        if len(layer) >= MIN_TEXT_CHARS:
            pages.append(dict(n=n, text=layer, source="text-layer", mean_conf=None, boxes=None, seconds=0.0))
            continue
        images = _page_images(page)
        if not images:
            pages.append(dict(n=n, text=layer, source="empty", mean_conf=None, boxes=None, seconds=0.0))
            continue
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        key = hashlib.sha256(buf.getvalue()).hexdigest()
        cache = os.path.join(paths.OCR_CACHE, key + ".json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                rec = json.load(f)
        else:
            t1 = time.time()
            lines, conf, nbox = ocr_image(images[0])
            rec = dict(lines=lines, mean_conf=conf, boxes=nbox, seconds=round(time.time() - t1, 2))
            os.makedirs(paths.OCR_CACHE, exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(rec, f)
        lines = [ln for ln in rec["lines"] if not FURNITURE.match(ln)]
        pages.append(dict(n=n, text="\n".join(lines), source="ocr", mean_conf=round(rec["mean_conf"], 4),
                          boxes=rec["boxes"], seconds=rec["seconds"]))
    sources = {p["source"] for p in pages}
    return dict(pages=pages, source="ocr" if "ocr" in sources else "text-layer",
                seconds=round(time.time() - t0, 2))


def pdf_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def _work(item):
    doc_id, rel = item
    path = os.path.join(paths.CORPUS, *rel.split("/"))
    rec = extract_pdf(path)
    rec["pdf_sha"] = pdf_sha(path)      # an extraction is only valid for the exact PDF it was made from
    return doc_id, rec


def _is_current(doc_id, rel):
    out = os.path.join(paths.EXTRACTED, *doc_id.split("/")) + ".json"
    if not os.path.exists(out):
        return False
    try:
        with open(out, encoding="utf-8") as f:
            return json.load(f).get("pdf_sha") == pdf_sha(os.path.join(paths.CORPUS, *rel.split("/")))
    except (OSError, ValueError):
        return False


def extract_all(manifest, workers=None, progress=print):
    """Extract every document in the manifest into corpus/extracted/<doc_id>.json (parallel; OCR is the slow part)."""
    items = [(d["doc_id"], d["pdf"]) for d in manifest["documents"].values()]
    todo = [it for it in items if not _is_current(*it)]
    workers = workers or max(1, min(4, (os.cpu_count() or 2) - 1))   # 8 workers ran this machine out of commit memory
    if progress:
        progress(f"extracting {len(todo)}/{len(items)} documents with {workers} worker(s) "
                 f"(scanned pages go through OCR, ~3 s each) ...")
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for doc_id, rec in pool.map(_work, todo):
            out = os.path.join(paths.EXTRACTED, *doc_id.split("/")) + ".json"
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            done += 1
            if progress and done % 20 == 0:
                progress(f"  extracted {done}/{len(todo)}")


def load_extracted(doc_id):
    with open(os.path.join(paths.EXTRACTED, *doc_id.split("/")) + ".json", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------------------------------------
# measuring extraction error (used by the eval harness and reports; needs truth.json)
# ----------------------------------------------------------------------------------------------------------
def levenshtein(a, b):
    """Exact edit distance, vectorised (O(len(a) * len(b)) cell updates, one numpy pass per row)."""
    import numpy as np
    if not a:
        return len(b)
    if not b:
        return len(a)
    bb = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    idx = np.arange(len(b) + 1)
    prev = idx.copy()
    for i, ch in enumerate(a, 1):
        cost = (bb != ord(ch)).astype(np.int64)
        base = np.empty(len(b) + 1, dtype=np.int64)
        base[0] = i
        base[1:] = np.minimum(prev[1:] + 1, prev[:-1] + cost)
        prev = np.minimum.accumulate(base - idx) + idx
    return int(prev[-1])


def _squash(s):
    return re.sub(r"\s+", "", s)


def ocr_metrics(truth_text, extracted_text, critical_tokens):
    """Character error rate (whitespace ignored), whitespace-loss rate, word error rate, critical-token recall."""
    a, b = _squash(truth_text), _squash(extracted_text)
    cer = levenshtein(a, b) / max(1, len(a))
    t_words, e_words = truth_text.split(), extracted_text.split()
    space_ratio = (len(e_words) / max(1, len(t_words)))
    flat = _squash(extracted_text)
    found = sum(1 for tok in critical_tokens if _squash(tok) in flat)
    return dict(cer=cer, words_truth=len(t_words), words_out=len(e_words), word_ratio=space_ratio,
                critical_total=len(critical_tokens), critical_found=found,
                critical_missing=[tok for tok in critical_tokens if _squash(tok) not in flat][:12])
