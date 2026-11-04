"""
The Week 3-4 retrieval pipeline (FAISS over MiniLM embeddings, then a cross-encoder rerank), made multi-document.

rag_core.ContractIndex is reused UNCHANGED as the base class: its embedding model, FAISS store, lazy cross-encoder
and `reranker` property are what runs here. What it lacks, and this subclass adds, is what a 60-contract corpus
needs and a single PDF never did:

  * search_scoped(): a metadata filter, so a question about one counterparty can only ever be answered from that
    counterparty's documents. FAISS (flat, exact) is asked for EVERY candidate and the filter applied after, so
    the filter cannot hide the right clause behind a different customer's near-identical one.
  * save()/load(): the index is built once by `run.py build`; the two MCP server processes load it from disk
    instead of re-embedding ~4,000 clauses at start-up.

Chunks are whole clauses (Week 11's answer-v3 lesson: serve clauses whole and labelled; 150-character chunks cut
mid-sentence and lose the clause number a citation needs). Clause = chunk, so Week 6's neighbour-stitch is not
needed and is not used.
"""

import json
import os
import time

from rag_core import ContractIndex

from . import paths

RERANK_POOL = 14


class CorpusIndex(ContractIndex):
    def __init__(self, chunks, vector_store=None):
        if vector_store is None:
            super().__init__(chunks)              # embeds + builds FAISS exactly as Weeks 3-4 did
        else:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            self.chunks = chunks
            self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            self.vector_store = vector_store
            self._reranker = None

    def save(self, directory=None):
        directory = directory or paths.INDEX_DIR
        os.makedirs(directory, exist_ok=True)
        self.vector_store.save_local(directory)

    @classmethod
    def load(cls, directory=None):
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS

        directory = directory or paths.INDEX_DIR
        emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        # our own file, written by save() above: loading it unpickles the docstore
        vs = FAISS.load_local(directory, emb, allow_dangerous_deserialization=True)
        chunks = [vs.docstore.search(vs.index_to_docstore_id[i]) for i in range(vs.index.ntotal)]
        return cls(chunks, vs)

    def warm(self):
        _ = self.reranker
        self.search_scoped("warm-up", lambda md: True, k=1)

    def search_scoped(self, query, keep, k=4, pool=RERANK_POOL, span=None):
        """Top-k chunks whose metadata satisfy keep(md), best first: FAISS over all chunks, filter, cross-encode.
        `span(name, **attrs)` (optional) is a context-manager factory used to time the three stages.
        -> [(Document, rerank_score)]"""
        from contextlib import nullcontext
        span = span or (lambda name, **a: nullcontext())
        with span("retrieval.embed_query", model="all-MiniLM-L6-v2"):
            qvec = self.embeddings.embed_query(query)
        with span("retrieval.vector_search", k=pool, scope="metadata filter"):
            cands = self.vector_store.similarity_search_by_vector(qvec, k=pool, filter=keep, fetch_k=len(self.chunks))
        if not cands:
            return []
        with span("retrieval.rerank", pairs=len(cands)):
            scores = self.reranker.predict([(query, d.page_content) for d in cands])
        ranked = sorted(zip(cands, scores), key=lambda p: p[1], reverse=True)[:k]
        return [(d, float(s)) for d, s in ranked]
