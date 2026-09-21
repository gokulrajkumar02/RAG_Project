
import os
import tempfile
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Legal Contract Assistant",
    page_icon="⚖️",
    layout="centered"
)

st.title("⚖️ Legal Contract Assistant")
st.caption("Upload a legal contract PDF — ask questions — get answers with source citations.")

for key in ["index", "contract_name"]:
    if key not in st.session_state:
        st.session_state[key] = None

with st.sidebar:
    st.subheader("🔑 Groq API Key (FREE)")
    api_key = st.text_input(
        "Paste your Groq key here:",
        type="password",
        value=os.getenv("GROQ_API_KEY", ""),
        help="Get a FREE key at https://console.groq.com"
    )
    st.markdown("👆 Free — no credit card needed!")

    st.markdown("---")
    st.subheader("📖 How RAG Works")
    st.markdown("""
**Phase 1 — Ingestion (Upload)**
1. 📄 Load PDF → extract text
2. ✂️  Split into 150-char chunks
3. 🔢 Embed chunks → vectors (local)
4. 🗃️  Store vectors in FAISS

**Phase 2 — Q&A (Ask)**
5. ❓ Embed your question (local)
6. 🔍 FAISS finds top 10 candidates → cross-encoder reranks to the best 3
7. 🤖 Groq LLM reads chunks → Answer
    """)

    st.markdown("---")
    st.info("💡 Embeddings run **locally** on your machine — completely free!")

    if st.session_state.contract_name:
        st.markdown("---")
        st.success(f"✅ Loaded:\n{st.session_state.contract_name}")

def process_contract(uploaded_file):
    """
    Ingestion Pipeline:
    PDF → Text Extraction → Chunking → HuggingFace Embeddings → FAISS
    NOTE: Embeddings run locally — no API key needed for this step!
    """
    from rag_core import load_pdf_chunks, ContractIndex

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    chunks = load_pdf_chunks(tmp_path)
    os.unlink(tmp_path)

    index = ContractIndex(chunks)

    return index, len(chunks)


st.header("📄 Step 1 — Upload Contract")
uploaded = st.file_uploader("Choose a PDF file", type=["pdf"])

if uploaded:
    col1, col2 = st.columns([4, 1])
    col1.info(f"📄 **{uploaded.name}**")
    process_btn = col2.button("⚙️ Process", type="primary")

    if process_btn:
        with st.spinner("⏳ Processing contract... (first run may take a minute to download the embedding model)"):
            try:
                index, num_chunks = process_contract(uploaded)
                st.session_state.index = index
                st.session_state.contract_name = uploaded.name
                st.success(
                    f"✅ Done! Contract split into **{num_chunks} chunks** and indexed in FAISS."
                )
            except Exception as e:
                st.error(f"❌ Error while processing: {e}")

def get_answer(question, index, api_key):
    """
    Retrieval + Generation Pipeline:
    Question → FAISS Search (top 10) → Cross-Encoder Rerank (top 3) →
    stitch in each chunk's neighbor → Groq LLM → Answer

    The neighbor stitch (Week 6 fix, see rag_core.ContractIndex.expand_with_neighbors)
    only changes what context the LLM reads — the cited "Source" chunks
    shown below are still exactly the top-3 reranked chunks.
    """
    from rag_core import generate_answer

    source_docs = index.search_reranked(question, k=3, pool=10)
    context_docs = index.expand_with_neighbors(source_docs)
    answer = generate_answer(question, context_docs, api_key)

    return answer, source_docs


if st.session_state.index:
    st.markdown("---")
    st.header("❓ Step 2 — Ask a Question")
    st.markdown(f"*Contract loaded: **{st.session_state.contract_name}***")

   
    st.markdown("**Quick questions:**")
    quick_qs = [
        "What is the notice period?",
        "Is there a confidentiality clause?",
        "What are the termination conditions?",
    ]
    cols = st.columns(3)
    for i, q in enumerate(quick_qs):
        if cols[i].button(q, key=f"quick_{i}"):
            st.session_state["preset_q"] = q

    question = st.text_input(
        "Or type your own question:",
        value=st.session_state.get("preset_q", ""),
        placeholder="e.g. How many days of leave are provided?"
    )

    ask_btn = st.button("🔍 Get Answer", type="primary")

    if ask_btn and question:
        if not api_key:
            st.error("❌ Please enter your Groq API Key in the sidebar.")
            st.stop()

        with st.spinner("🔍 Searching contract and generating answer..."):
            try:
                answer, sources = get_answer(
                    question,
                    st.session_state.index,
                    api_key
                )

                st.markdown("---")
                st.subheader("💬 Answer")
                st.success(answer)

                st.subheader("📌 Source Clauses (from the contract)")
                st.caption("These are the contract sections the AI used to generate the answer.")
                for i, doc in enumerate(sources, 1):
                    page_num = doc.metadata.get("page", 0) + 1
                    with st.expander(f"📜 Source {i}  —  Page {page_num}"):
                        st.code(doc.page_content, language="")

            except Exception as e:
                st.error(f"❌ Error: {e}")

else:
    if not uploaded:
        st.markdown("---")
        st.info("👆 Start by uploading a contract PDF above.")