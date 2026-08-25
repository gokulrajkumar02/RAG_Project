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
                          Question ──► Embed ──► Search FAISS ──► LLM ──► Answer + Source
```

### Example

Upload `sample_contract.pdf` then ask:

> "What is the notice period?"

The system finds the relevant clause and answers:

> "The notice period is 30 days."

It also shows **which part of the contract** was used to generate the answer.

---

## 🛠️ Tech Stack

| Component       | Technology               |
|-----------------|--------------------------|
| UI              | Streamlit                |
| LLM             | OpenAI GPT-3.5-Turbo     |
| Embeddings      | OpenAI Embeddings        |
| Vector Database | FAISS (local)            |
| PDF Loader      | PyPDF via LangChain      |
| RAG Framework   | LangChain                |

---

## 📁 Project Files

```
legal-contract-rag/
├── app.py                 ← Main Streamlit app (the whole RAG system)
├── requirements.txt       ← Python packages to install
├── .env.example           ← Template for your API key
├── create_sample_pdf.py   ← Script to generate a test PDF contract
├── README.md              ← This file
└── data/
    └── sample_contract.txt  ← Sample contract (reference text)
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

This installs Streamlit, LangChain, FAISS, OpenAI, and everything else.

---

### Step 4 — Add Your OpenAI API Key

**Option A** — Create a `.env` file:
```bash
# Copy the example file
cp .env.example .env

# Open .env and replace the placeholder with your real key:
OPENAI_API_KEY=sk-your-actual-key-here
```

**Option B** — Just type it in the app's sidebar when it opens.

> Get a key at: https://platform.openai.com/api-keys

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
| Chunking (500 chars) | Contract split into small pieces | LLM token limits; retrieval works better on small chunks |
| Embeddings | Each chunk → vector of numbers | Enables semantic (meaning-based) search |
| FAISS | Stores and indexes all vectors | Super fast nearest-neighbour search |
| Retrieval (k=3) | 3 chunks most similar to question | Gives LLM relevant context, not the whole doc |
| Generation | LLM reads chunks → writes answer | Grounds the answer in real contract data |

---

## ⚠️ Notes

- The OpenAI API costs a tiny amount per question (usually less than $0.01)
- Never commit your `.env` file to GitHub — keep your API key private
- The app resets if you refresh the page — re-upload the contract to continue

---

## 🐛 Common Errors

| Error | Fix |
|-------|-----|
| `AuthenticationError` | Check your OpenAI API key |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| `PDFSyntaxError` | Try a different or simpler PDF |
| App is slow on first question | Normal — embeddings take a moment |
