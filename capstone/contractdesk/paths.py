"""Where everything lives. Nothing else in the package hardcodes a path."""

import os

from . import CAPSTONE_DIR, REPO_ROOT

CORPUS = os.path.join(CAPSTONE_DIR, "corpus")          # generated; gitignored; rebuilt by `run.py build`
PDF_DIR = os.path.join(CORPUS, "pdf")
TRUTH = os.path.join(CORPUS, "truth.json")             # the generator's ground truth. ONLY eval code may read it.
MANIFEST = os.path.join(CORPUS, "manifest.json")       # the document inventory ("legal ops" upload metadata)
EXTRACTED = os.path.join(CORPUS, "extracted")          # per-document extraction (pypdf text or OCR) + stats
OCR_CACHE = os.path.join(CORPUS, "ocr_cache")
REGISTRY = os.path.join(CORPUS, "registry.json")       # what the system parsed out of the extracted text
INDEX_DIR = os.path.join(CORPUS, "index")              # FAISS index over clause chunks
LOGS = os.path.join(CAPSTONE_DIR, "logs")
DELIVERABLES = os.path.join(CAPSTONE_DIR, "deliverables")
EVAL_DIR = os.path.join(CAPSTONE_DIR, "eval")
REGRESSION_DIR = os.path.join(EVAL_DIR, "regression")
CONFIG = os.path.join(CAPSTONE_DIR, "config.json")
MCP_CONFIG = os.path.join(CAPSTONE_DIR, "mcp_servers.json")

SUPPLIER = "TechCorp Pvt. Ltd."          # Weeks 3-11's company: the seller whose legal team uses this tool


def pdf_path(doc_id):
    return os.path.join(PDF_DIR, *doc_id.split("/")) + ".pdf"
