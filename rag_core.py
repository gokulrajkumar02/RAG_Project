"""
Shared retrieval + generation logic for the Legal Contract Assistant.

Used by both app.py (the Streamlit UI) and eval/retrieval_eval.py (the
offline retrieval evaluation harness), so the app and the eval always run
the exact same pipeline.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 150
CHUNK_OVERLAP = 20
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def load_pdf_chunks(pdf_path, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
    from langchain_community.document_loaders import PyPDFLoader

    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(documents)


class ContractIndex:
    """
    Semantic (FAISS) search over contract chunks, with an optional
    cross-encoder reranking pass.

    At k=3 over ~30 short, template-heavy clause chunks (lots of shared
    boilerplate: "Company", "Employee", "Agreement"), plain embedding
    similarity sometimes ranks a generically-similar clause above the one
    that actually answers the question. A cross-encoder reads the question
    and each candidate chunk together (instead of comparing two
    independently-embedded vectors), so it catches that closer relevance
    signal — but it can only promote a chunk that made it into the initial
    semantic candidate pool; it can't fix a chunk that never got retrieved.
    """

    def __init__(self, chunks):
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS

        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_idx"] = i

        self.chunks = chunks
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.vector_store = FAISS.from_documents(chunks, self.embeddings)
        self._reranker = None

    @property
    def reranker(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(RERANKER_MODEL)
        return self._reranker

    def search_semantic(self, query, k=3):
        return self.vector_store.similarity_search(query, k=k)

    def search_reranked(self, query, k=3, pool=10):
        candidates = self.vector_store.similarity_search(query, k=pool)
        pairs = [(query, doc.page_content) for doc in candidates]
        scores = self.reranker.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        return [doc for doc, _score in ranked[:k]]


ANSWER_PROMPT = """You are a legal contract assistant.
Answer the question using ONLY the contract context provided below.
If the answer is not in the context, respond with:
"This information was not found in the contract."
Be clear and concise.

Contract Context:
{context}

Question: {question}

Answer:"""


def generate_answer(question, context_docs, api_key, model_name="openai/gpt-oss-20b"):
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    context = "\n\n---\n\n".join(doc.page_content for doc in context_docs)
    prompt = ChatPromptTemplate.from_template(ANSWER_PROMPT)
    llm = ChatGroq(groq_api_key=api_key, model_name=model_name, temperature=0)
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"context": context, "question": question})
