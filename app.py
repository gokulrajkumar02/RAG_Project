
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

for key in ["vector_store", "contract_name"]:
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
2. ✂️  Split into 500-char chunks
3. 🔢 Embed chunks → vectors (local)
4. 🗃️  Store vectors in FAISS

**Phase 2 — Q&A (Ask)**
5. ❓ Embed your question (local)
6. 🔍 Find similar chunks in FAISS
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
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS

  
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    loader = PyPDFLoader(tmp_path)
    documents = loader.load()
    os.unlink(tmp_path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    chunks = splitter.split_documents(documents)


    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2"
    )

  
    vector_store = FAISS.from_documents(chunks, embeddings)

    return vector_store, len(chunks)


st.header("📄 Step 1 — Upload Contract")
uploaded = st.file_uploader("Choose a PDF file", type=["pdf"])

if uploaded:
    col1, col2 = st.columns([4, 1])
    col1.info(f"📄 **{uploaded.name}**")
    process_btn = col2.button("⚙️ Process", type="primary")

    if process_btn:
        with st.spinner("⏳ Processing contract... (first run may take a minute to download the embedding model)"):
            try:
                vs, num_chunks = process_contract(uploaded)
                st.session_state.vector_store  = vs
                st.session_state.contract_name = uploaded.name
                st.success(
                    f"✅ Done! Contract split into **{num_chunks} chunks** and stored in FAISS."
                )
            except Exception as e:
                st.error(f"❌ Error while processing: {e}")

def get_answer(question, vector_store, api_key):
    """
    Retrieval + Generation Pipeline:
    Question → Embed (local) → FAISS Search → Groq LLM → Answer
    """
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

   
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    source_docs = retriever.invoke(question)

    context = "\n\n---\n\n".join(doc.page_content for doc in source_docs)

   
    prompt = ChatPromptTemplate.from_template("""You are a legal contract assistant.
Answer the question using ONLY the contract context provided below.
If the answer is not in the context, respond with:
"This information was not found in the contract."
Be clear and concise.

Contract Context:
{context}

Question: {question}

Answer:""")

    llm = ChatGroq(
        groq_api_key=api_key,
        model_name="openai/gpt-oss-20b",
        temperature=0
    )

    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": context, "question": question})

    return answer, source_docs


if st.session_state.vector_store:
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
                    st.session_state.vector_store,
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