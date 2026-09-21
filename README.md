# ⚖️ Legal Contract RAG Assistant

> Week 3 Assignment — Retrieval-Augmented Generation (RAG)

A beginner-friendly RAG system that lets you upload a legal contract PDF
and ask questions about it. The AI answers **only from the contract** —
no guessing or hallucinating.

---

## 🔍 What This Project Does

```
Upload PDF ──► Extract Text ──► Split Chunks ──► Embed ──► FAISS
                                                              │
        Question ──► Search FAISS (top 10) ──► Rerank (top 3) ──► LLM ──► Answer + Source
```

### Example

Upload `sample_contract.pdf` then ask:

> "What is the notice period?"

The system finds the relevant clause and answers:

> "The notice period is 30 days."

It also shows **which part of the contract** was used to generate the answer.

---

## 🛠️ Tech Stack

| Component       | Technology                              |
|-----------------|------------------------------------------|
| UI              | Streamlit                                |
| LLM             | Groq (`openai/gpt-oss-20b`, free tier)   |
| Embeddings      | HuggingFace `all-MiniLM-L6-v2` (local)   |
| Vector Database | FAISS (local)                            |
| Reranker        | Cross-encoder `ms-marco-MiniLM-L-6-v2`   |
| PDF Loader      | PyPDF via LangChain                      |
| RAG Framework   | LangChain                                |

---

## 📁 Project Files

```
legal-contract-rag/
├── app.py                 ← Streamlit UI (upload, ask, show sources)
├── rag_core.py             ← Shared chunking / retrieval / generation logic
├── requirements.txt       ← Python packages to install
├── .env.example           ← Template for your API key
├── create_sample_pdf.py   ← Script to generate a test PDF contract
├── README.md              ← This file
├── data/
│   └── sample_contract.txt  ← Sample contract (reference text)
├── eval/                  ← Week 4 & 6 — retrieval debugging & evals
│   ├── questions.py         ← Labeled test set (chunks + keywords + Week 5 problem_type/human_verdict)
│   ├── retrieval_eval.py    ← Week 4: baseline vs. reranked retrieval, hit-rate@3
│   ├── results.md            ← Week 4: generated report
│   ├── judge.py              ← Week 6: LLM-as-judge (binary PASS/FAIL, groundedness)
│   ├── validate_judge.py     ← Week 6: judge vs. human-verdict agreement check
│   ├── judge_validation.md   ← Week 6: generated report
│   ├── run_evals.py          ← Week 6: one-command eval — validates judge, then
│   │                            before/after score per problem type (neighbor-stitch fix)
│   └── eval_report.md        ← Week 6: generated report
└── error_analysis/       ← Week 5 — error analysis (reading traces, ranked taxonomy)
    ├── collect_traces.py    ← Runs the real app pipeline + Groq LLM, saves full traces
    ├── traces.md             ← 24 real question → context → answer traces, read by hand
    ├── open_coding_notes.md  ← Honest per-trace failure notes, written before grouping
    └── error_taxonomy.md     ← Named, ranked problem groups + chosen fix target
```

---

## 🚀 How to Run

### Step 1 — Check Python Version

```bash
python --version
```
You need **Python 3.9 or above**.

---

### Step 2 — Create a Virtual Environment (recommended)

```bash
# Create the environment
python -m venv venv

# Activate it:
# Windows:
venv\Scripts\activate

# Mac / Linux:
source venv/bin/activate
```

---

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

This installs Streamlit, LangChain, FAISS, sentence-transformers, and everything else.

---

### Step 4 — Add Your Groq API Key (free)

**Option A** — Create a `.env` file:
```bash
# Copy the example file
cp .env.example .env

# Open .env and replace the placeholder with your real key:
GROQ_API_KEY=gsk-your-actual-key-here
```

**Option B** — Just type it in the app's sidebar when it opens.

> Get a free key at: https://console.groq.com

Embeddings and reranking run **locally** and don't need this key at all —
it's only used for the final answer-generation call.

---

### Step 5 — Create the Sample PDF (for testing)

```bash
python create_sample_pdf.py
```

This creates `data/sample_contract.pdf` — a sample employment contract
you can use to test the app.

---

### Step 6 — Run the App

```bash
streamlit run app.py
```

The app opens automatically at: **http://localhost:8501**

---

## 🧪 How to Use the App

1. **Enter your API key** in the left sidebar
2. **Upload** `data/sample_contract.pdf` (or any other contract PDF)
3. Click **"Process"** — the contract is loaded into FAISS (takes a few seconds)
4. Click a **quick question button** or type your own question
5. Click **"Get Answer"** — see the answer + the exact contract clause it came from

---

## 💬 Questions to Test With

| Question | What to Expect |
|----------|---------------|
| What is the notice period? | 30 days |
| What is the employee's salary? | Rs. 80,000/month |
| What are the working hours? | Mon–Fri, 9 AM–6 PM |
| How many leave days? | 18 annual + 10 sick + 3 personal |
| Is there a confidentiality clause? | Yes |
| What are the termination conditions? | Gross misconduct, fraud... |
| Is there a non-compete clause? | Yes, 6 months |
| Does the company provide a housing allowance? | **Not found in contract** ✅ |

The last one is important — a good RAG system says "not found" instead of making up an answer.

---

## 🧠 RAG Concepts Demonstrated

| Step | What Happens | Why It Matters |
|------|-------------|---------------|
| PDF Loading | Text extracted from PDF pages | Makes document readable by code |
| Chunking (150 chars) | Contract split into small, per-clause pieces | Fine enough that retrieval has to genuinely pick the right clause |
| Embeddings | Each chunk → vector of numbers | Enables semantic (meaning-based) search |
| FAISS | Stores and indexes all vectors | Super fast nearest-neighbour search |
| Retrieval (top 10) | 10 chunks most similar to question | Casts a wide net before narrowing down |
| Reranking (cross-encoder) | Re-scores those 10 chunks against the question, keeps top 3 | Catches cases where embedding similarity alone picks the wrong clause |
| Generation | LLM reads the top 3 chunks → writes answer | Grounds the answer in real contract data |

See [`eval/`](eval/) for the Week 4 retrieval-debugging exercise: labeled
failure cases, a before/after hit-rate@3 measurement of the reranking
step above, and an inspection view showing question → fetched chunks →
answer side by side.

See [`error_analysis/`](error_analysis/) for the Week 5 error-analysis
exercise: 24 real end-to-end traces read by hand, honest failure notes
written before any category existed, grouped into a named, ranked
taxonomy, with one chosen fix target and a written prediction.

See [`eval/`](eval/) for the Week 6 evals exercise: the Week 5 fix
prediction (stitch each retrieved chunk's neighbor into the context —
now live in `rag_core.ContractIndex.expand_with_neighbors` and `app.py`)
implemented and measured with a one-command harness (`eval/run_evals.py`)
— free rule checks, an LLM judge validated against the Week 5 human
labels before being trusted, and a before/after pass rate per problem
type.

---

## ⚠️ Notes

- The Groq API is free, but never commit your `.env` file to GitHub — keep your API key private
- The app resets if you refresh the page — re-upload the contract to continue

---

## 🐛 Common Errors

| Error | Fix |
|-------|-----|
| `AuthenticationError` | Check your Groq API key |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| `PDFSyntaxError` | Try a different or simpler PDF |
| App is slow on first question | Normal — embedding/reranker models download once, then run locally |
