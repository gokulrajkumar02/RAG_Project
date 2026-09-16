"""
Labeled test set for the retrieval-debugging exercise (Week 4).

Ground truth is expressed as chunk indices into the fine-grained chunking
of data/sample_contract.pdf (chunk_size=150, chunk_overlap=20 — see
rag_core.load_pdf_chunks). Run eval/dump_chunks.py to reprint that map if
the source PDF ever changes.

Questions are phrased the way a real employee would ask them, not copied
from the contract's own wording — that's deliberate. Copy-paste phrasing
("What is the notice period?") barely stresses semantic search, since it
shares almost every word with the source clause. Paraphrased, colloquial
phrasing ("how much heads-up do I need to give?") is what actually
produces retrieval failures worth studying.

Each question also carries `answer_keywords`: substrings that MUST appear
(case-insensitively, any one is enough) in a correct LLM answer. Used to
auto-detect "right chunk fetched, wrong answer" failures once an LLM
answer is generated from the retrieved context.

`no_answer=True` means the contract does not contain this fact at all —
the correct behavior is retrieval finding nothing relevant and the LLM
saying so. These are excluded from hit-rate@3 (there is no "correct chunk"
to hit) but are included in the inspection view as a hallucination check.
"""

QUESTIONS = [
    {
        "id": "parties",
        "question": "Which company and individual signed this contract?",
        "expected_chunks": [1],
        "answer_keywords": ["TechCorp", "John Smith"],
    },
    {
        "id": "job_role",
        "question": "What position is being filled by this hire?",
        "expected_chunks": [2],
        "answer_keywords": ["Software Engineer"],
    },
    {
        "id": "reports_to",
        "question": "Who is my direct manager?",
        "expected_chunks": [2, 3],
        "answer_keywords": ["Engineering Manager"],
    },
    {
        "id": "effective_date",
        "question": "When does this employment officially begin?",
        "expected_chunks": [4],
        "answer_keywords": ["January 1, 2024", "January 1"],
    },
    {
        "id": "salary",
        "question": "What is my take-home pay every month?",
        "expected_chunks": [6, 7],
        "answer_keywords": ["80,000", "Eighty Thousand"],
    },
    {
        "id": "bonus",
        "question": "Could I get extra pay for good performance?",
        "expected_chunks": [7, 8],
        "answer_keywords": ["bonus"],
    },
    {
        "id": "working_hours",
        "question": "What time am I supposed to be at work, and when can I leave?",
        "expected_chunks": [9],
        "answer_keywords": ["9:00 AM", "9 AM", "Monday to Friday"],
    },
    {
        "id": "overtime",
        "question": "Do I get paid extra for staying late?",
        "expected_chunks": [10, 11],
        "answer_keywords": ["overtime"],
    },
    {
        "id": "annual_leave",
        "question": "How much vacation do I get each year?",
        "expected_chunks": [12],
        "answer_keywords": ["18 days", "18"],
    },
    {
        "id": "sick_leave",
        "question": "What's the deal with sick days?",
        "expected_chunks": [12],
        "answer_keywords": ["10 days", "10"],
    },
    {
        "id": "leave_approval",
        "question": "Can I just take time off whenever I feel like it?",
        "expected_chunks": [13],
        "answer_keywords": ["approved", "in advance"],
    },
    {
        "id": "notice_period",
        "question": "If I want to quit, how much heads-up do I need to give?",
        "expected_chunks": [14],
        "answer_keywords": ["30", "thirty"],
    },
    {
        "id": "pay_in_lieu",
        "question": "Could they just pay me off instead of letting me work my notice?",
        "expected_chunks": [15],
        "answer_keywords": ["in lieu of notice", "lieu of notice"],
    },
    {
        "id": "immediate_termination_fraud",
        "question": "What happens if I get caught stealing from the company?",
        "expected_chunks": [16, 17],
        "answer_keywords": ["theft", "fraud"],
    },
    {
        "id": "confidentiality_dismissal",
        "question": "Could breaking a confidentiality rule get me fired on the spot?",
        "expected_chunks": [18],
        "answer_keywords": ["willful breach of confidentiality", "breach of confidentiality"],
    },
    {
        "id": "confidentiality_after",
        "question": "After I resign, can I still be sued for leaking client info?",
        "expected_chunks": [19, 20, 21],
        "answer_keywords": ["after employment"],
    },
    {
        "id": "confidential_info_scope",
        "question": "What counts as secret information I'm not allowed to share?",
        "expected_chunks": [20, 21],
        "answer_keywords": ["business plans", "client lists", "trade secrets"],
    },
    {
        "id": "noncompete_duration",
        "question": "If I leave, how soon can I go work for a competitor?",
        "expected_chunks": [22],
        "answer_keywords": ["6", "six months"],
    },
    {
        "id": "noncompete_consulting",
        "question": "Am I allowed to freelance for a rival firm right after I resign?",
        "expected_chunks": [22, 23],
        "answer_keywords": ["consult", "competitor"],
    },
    {
        "id": "ip_ownership",
        "question": "Does the company own an app I build on the job?",
        "expected_chunks": [25, 26],
        "answer_keywords": ["sole and exclusive property", "Company"],
    },
    {
        "id": "ip_assignment",
        "question": "If asked, do I have to formally hand over my IP rights?",
        "expected_chunks": [27],
        "answer_keywords": ["assign"],
    },
    {
        "id": "jurisdiction",
        "question": "If we end up in a legal fight, which city's courts handle it?",
        "expected_chunks": [29],
        "answer_keywords": ["Bengaluru", "Karnataka"],
    },
    {
        "id": "maternity_leave",
        "question": "Does this contract mention maternity or paternity leave?",
        "expected_chunks": [],
        "answer_keywords": ["not found"],
        "no_answer": True,
    },
    {
        "id": "probation",
        "question": "Is there a probation period mentioned anywhere?",
        "expected_chunks": [],
        "answer_keywords": ["not found"],
        "no_answer": True,
    },
]
