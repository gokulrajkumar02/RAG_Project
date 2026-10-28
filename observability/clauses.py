"""
Clause map for a contract index: which clause every line of every chunk belongs to.

Chunks are cut every ~150 characters, not at clause boundaries, so a chunk regularly ENDS with the
heading of the NEXT clause (chunk ids from data/sample_contract.pdf):

    chunk 15: "...pay salary in lieu of\\nnotice and ask the Employee to leave immediately.\\n7. TERMINATION"
    chunk 18: "- Serious or repeated breach of Company policies\\n  - Willful breach of confidentiality\\n8. CONFIDENTIALITY"

The text of chunk 15 is clause 6 and the text of chunk 18 is clause 7, but the only clause heading
printed in either chunk is the next clause's. Walking the chunks in document order and switching clause
at every heading line gives each line the clause it really belongs to.

Used for: scoring citations in the eval suite, logging which clauses a request's context covered, and
(from prompt answer-v3) labelling the retrieved context by clause.
"""

import re

HEADING = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Z0-9 &/\-]*[A-Z])\s*$")
UNNUMBERED_HEADINGS = ("SIGNATURES",)
FURNITURE = re.compile(r"^\s*(Page \d+|.* - Confidential|Employment Agreement - .*)\s*$")
PREAMBLE = ("preamble", "PREAMBLE")


def parse_heading(line):
    """(clause_id, TITLE) for a heading line, else None. Numbered clauses use their number as id."""
    m = HEADING.match(line)
    if m:
        return m.group(1), m.group(2).strip()
    stripped = line.strip()
    if stripped in UNNUMBERED_HEADINGS:
        return stripped.lower(), stripped
    return None


def line_kind(line):
    if parse_heading(line):
        return "heading"
    if not line.strip() or FURNITURE.match(line):
        return "furniture"
    return "body"


def clause_sort_key(clause_id):
    return (0, int(clause_id), "") if clause_id.isdigit() else (1, 0, clause_id)


class ClauseMap:
    def __init__(self, chunks):
        self.titles = {PREAMBLE[0]: PREAMBLE[1]}
        self.segments = []          # per chunk: [{"clause", "lines", "kinds"}], in text order
        current = PREAMBLE
        for chunk in chunks:
            segs = []
            for line in chunk.page_content.split("\n"):
                head = parse_heading(line)
                if head:
                    current = head
                    self.titles[head[0]] = head[1]
                if not segs or segs[-1]["clause"] != current[0]:
                    segs.append({"clause": current[0], "lines": [], "kinds": []})
                segs[-1]["lines"].append(line)
                segs[-1]["kinds"].append(line_kind(line))
            self.segments.append(segs)

    # ---- per chunk -------------------------------------------------------------------------------
    def chunk_segments(self, idx):
        """[(clause_id, text, has_body)] for one chunk, in text order."""
        return [(s["clause"], "\n".join(s["lines"]), "body" in s["kinds"]) for s in self.segments[idx]]

    def body_clauses(self, idx):
        """Clauses whose TEXT (not just a heading) is in this chunk."""
        out = []
        for clause, _text, has_body in self.chunk_segments(idx):
            if has_body and clause not in out:
                out.append(clause)
        return out

    def clauses_for(self, chunk_ids):
        found = {c for i in chunk_ids for c in self.body_clauses(i)}
        return sorted(found, key=clause_sort_key)

    def chunks_with_body(self, clause_id):
        return [i for i in range(len(self.segments)) if clause_id in self.body_clauses(i)]

    def expand_to_clauses(self, chunk_ids, max_chunks_per_clause=8):
        """Every clause whose text is in `chunk_ids`, served whole: (chunk ids grouped by clause in order of
        first appearance, clause order). The cap keeps one long clause from flooding the prompt."""
        order = []
        for i in chunk_ids:
            for c in self.body_clauses(i):
                if c not in order:
                    order.append(c)
        ids = []
        for c in order:
            for i in self.chunks_with_body(c)[:max_chunks_per_clause]:
                if i not in ids:
                    ids.append(i)
        return ids, order

    def clause_text(self, clause_id, chunk_ids):
        """The clause's own lines from those chunks: no page furniture, no other clause's trailing heading."""
        lines = []
        for i in chunk_ids:
            for s in self.segments[i]:
                if s["clause"] == clause_id and "body" in s["kinds"]:
                    lines += [ln for ln, kind in zip(s["lines"], s["kinds"]) if kind != "furniture"]
        return "\n".join(lines)

    def foreign_trailing_headings(self):
        """Chunks that END with the heading of a clause whose text is not in the chunk:
        [(chunk_idx, body_clause, trailing_heading_clause)]."""
        out = []
        for i, segs in enumerate(self.segments):
            last = segs[-1]
            body = self.body_clauses(i)
            if "body" not in last["kinds"] and "heading" in last["kinds"] and body and last["clause"] not in body:
                out.append((i, body[0], last["clause"]))
        return out

    # ---- naming ----------------------------------------------------------------------------------
    def title(self, clause_id):
        return self.titles.get(clause_id, clause_id.upper())

    def label(self, clause_id):
        if clause_id.isdigit():
            return f"Clause {clause_id} - {self.title(clause_id)}"
        return self.title(clause_id).title()

    def numbered(self):
        return sorted((c for c in self.titles if c.isdigit()), key=int)
