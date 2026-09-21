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

Two fields added in Week 6 (eval/run_evals.py) tie this set to the Week 5
error analysis instead of duplicating it:

- `problem_type`: which named group from error_analysis/error_taxonomy.md
  this question belongs to (`split_clause_refusal`, `never_retrieved_false_notfound`,
  `wrong_item_selected`, `never_retrieved_lucky_pass`, `no_answer_control`,
  or `baseline_pass` for the 17 that already passed). Lets run_evals.py
  report a before/after score per problem type, not just one overall number.
- `human_verdict`: the PASS/FAIL this question got in
  error_analysis/open_coding_notes.md, from a human reading the actual
  retrieved chunks + generated answer. Ground truth for
  eval/validate_judge.py — never touched by the judge itself.
"""

QUESTIONS = [
    {
        "id": "parties",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "Which company and individual signed this contract?",
        "expected_chunks": [1],
        "answer_keywords": ["TechCorp", "John Smith"],
    },
    {
        "id": "job_role",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "What position is being filled by this hire?",
        "expected_chunks": [2],
        "answer_keywords": ["Software Engineer"],
    },
    {
        "id": "reports_to",
        "problem_type": "split_clause_refusal",
        "human_verdict": "FAIL",
        "question": "Who is my direct manager?",
        "expected_chunks": [2, 3],
        "answer_keywords": ["Engineering Manager"],
    },
    {
        "id": "effective_date",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "When does this employment officially begin?",
        "expected_chunks": [4],
        "answer_keywords": ["January 1, 2024", "January 1"],
    },
    {
        "id": "salary",
        "problem_type": "split_clause_refusal",
        "human_verdict": "FAIL",
        "question": "What is my take-home pay every month?",
        "expected_chunks": [6, 7],
        "answer_keywords": ["80,000", "Eighty Thousand"],
    },
    {
        "id": "bonus",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "Could I get extra pay for good performance?",
        "expected_chunks": [7, 8],
        "answer_keywords": ["bonus"],
    },
    {
        "id": "working_hours",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "What time am I supposed to be at work, and when can I leave?",
        "expected_chunks": [9],
        "answer_keywords": ["9:00 AM", "9 AM", "Monday to Friday"],
    },
    {
        "id": "overtime",
        "problem_type": "never_retrieved_false_notfound",
        "human_verdict": "FAIL",
        "question": "Do I get paid extra for staying late?",
        "expected_chunks": [10, 11],
        "answer_keywords": ["overtime"],
    },
    {
        "id": "annual_leave",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "How much vacation do I get each year?",
        "expected_chunks": [12],
        "answer_keywords": ["18 days", "18"],
    },
    {
        "id": "sick_leave",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "What's the deal with sick days?",
        "expected_chunks": [12],
        "answer_keywords": ["10 days", "10"],
    },
    {
        "id": "leave_approval",
        "problem_type": "never_retrieved_lucky_pass",
        "human_verdict": "FAIL",
        "question": "Can I just take time off whenever I feel like it?",
        "expected_chunks": [13],
        "answer_keywords": ["approved", "in advance"],
    },
    {
        "id": "notice_period",
        "problem_type": "never_retrieved_false_notfound",
        "human_verdict": "FAIL",
        "question": "If I want to quit, how much heads-up do I need to give?",
        "expected_chunks": [14],
        "answer_keywords": ["30", "thirty"],
    },
    {
        "id": "pay_in_lieu",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "Could they just pay me off instead of letting me work my notice?",
        "expected_chunks": [15],
        "answer_keywords": ["in lieu of notice", "lieu of notice"],
    },
    {
        "id": "immediate_termination_fraud",
        "problem_type": "wrong_item_selected",
        "human_verdict": "FAIL",
        "question": "What happens if I get caught stealing from the company?",
        "expected_chunks": [16, 17],
        "answer_keywords": ["theft", "fraud"],
    },
    {
        "id": "confidentiality_dismissal",
        "problem_type": "split_clause_refusal",
        "human_verdict": "FAIL",
        "question": "Could breaking a confidentiality rule get me fired on the spot?",
        "expected_chunks": [18],
        "answer_keywords": ["willful breach of confidentiality", "breach of confidentiality"],
    },
    {
        "id": "confidentiality_after",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "After I resign, can I still be sued for leaking client info?",
        "expected_chunks": [19, 20, 21],
        "answer_keywords": ["after employment"],
    },
    {
        "id": "confidential_info_scope",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "What counts as secret information I'm not allowed to share?",
        "expected_chunks": [20, 21],
        "answer_keywords": ["business plans", "client lists", "trade secrets"],
    },
    {
        "id": "noncompete_duration",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "If I leave, how soon can I go work for a competitor?",
        "expected_chunks": [22],
        "answer_keywords": ["6", "six months"],
    },
    {
        "id": "noncompete_consulting",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "Am I allowed to freelance for a rival firm right after I resign?",
        "expected_chunks": [22, 23],
        "answer_keywords": ["consult", "competitor"],
    },
    {
        "id": "ip_ownership",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "Does the company own an app I build on the job?",
        "expected_chunks": [25, 26],
        "answer_keywords": ["sole and exclusive property", "Company"],
    },
    {
        "id": "ip_assignment",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "If asked, do I have to formally hand over my IP rights?",
        "expected_chunks": [27],
        "answer_keywords": ["assign"],
    },
    {
        "id": "jurisdiction",
        "problem_type": "baseline_pass",
        "human_verdict": "PASS",
        "question": "If we end up in a legal fight, which city's courts handle it?",
        "expected_chunks": [29],
        "answer_keywords": ["Bengaluru", "Karnataka"],
    },
    {
        "id": "maternity_leave",
        "problem_type": "no_answer_control",
        "human_verdict": "PASS",
        "question": "Does this contract mention maternity or paternity leave?",
        "expected_chunks": [],
        "answer_keywords": ["not found"],
        "no_answer": True,
    },
    {
        "id": "probation",
        "problem_type": "no_answer_control",
        "human_verdict": "PASS",
        "question": "Is there a probation period mentioned anywhere?",
        "expected_chunks": [],
        "answer_keywords": ["not found"],
        "no_answer": True,
    },
]
