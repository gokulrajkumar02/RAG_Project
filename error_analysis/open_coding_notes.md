# Open Coding Notes — Legal Contract RAG (Track F)

Read all 24 traces in `traces.md` end to end, in order, before grouping anything
into categories. One line per trace: PASS, or one honest sentence on what went
wrong. Judgment is based on reading the actual retrieved chunks and the actual
generated answer — not just the automated keyword/chunk-index check from
`eval/questions.py` (that check is noted for reference but a few answers that
technically contain no matching keyword are still fine, and a couple that
technically "hit" the expected chunk still produced a wrong answer).

| id | verdict | note |
|---|---|---|
| parties | PASS | Right chunk, correct, concise answer. |
| job_role | PASS | Right chunk, correct answer. |
| reports_to | **FAIL** | Chunk 2 (has "...shall report to the") never retrieved — only chunk 3 ("Engineering Manager and perform duties...") was, so the model saw the job title with no verb attaching it to "report to," and answered "not found" instead of inferring the obvious link. |
| effective_date | PASS | Right chunk, correct answer. |
| salary | **FAIL** | Chunks 6 and 7 — the exact ones with "Rs. 80,000 (Eighty Thousand" / "Rupees)" — were both retrieved, but the model still answered "not found," apparently because the figure is split across the chunk boundary. |
| bonus | PASS | Right chunk, correct, appropriately hedges "at the sole discretion of the Company." |
| working_hours | PASS | Right chunk, correct answer. |
| overtime | **FAIL** | Chunk 11 (the actual "Overtime is compensated as per Company policy" line) was never retrieved; chunk 10 alone doesn't confirm extra pay, so the "not found" answer is a reasonable read of what it got — the real problem is upstream, in retrieval. |
| annual_leave | PASS | Right chunk, correct answer. |
| sick_leave | PASS | Right chunk, correct answer. |
| leave_approval | **FAIL** | Chunk 13 (the actual "must be applied for in advance and approved" clause) was never retrieved; the model still landed on a directionally correct "No," but only by inference from the leave-days list, not from the real rule — it got lucky, it isn't grounded. |
| notice_period | **FAIL** | Chunk 14 (has "30 (thirty) days written notice") never makes it into the candidate pool at all for this phrasing, so the answer is a flat, wrong "not found" on an ordinary quit-notice question. |
| pay_in_lieu | PASS | Right chunk, correct answer. |
| immediate_termination_fraud | **FAIL** | Chunk 17 was retrieved and literally contains the bullet "Theft, fraud, or dishonesty," but the model answered with a different bullet from the same list ("Gross misconduct or negligence") — confidently wrong, not a refusal. |
| confidentiality_dismissal | **FAIL** | Chunk 18 was retrieved and literally contains "Willful breach of confidentiality," but the causal header ("may terminate immediately for:") is in chunk 16, which wasn't retrieved — without it the model can't confirm the breach→firing link and answers "not found" even though the named clause is right there. |
| confidentiality_after | PASS | Right chunks, correct answer, properly cites "during and after employment." |
| confidential_info_scope | PASS | Right chunks, correct, complete bullet-list answer. |
| noncompete_duration | PASS | Right chunk, correct answer. |
| noncompete_consulting | PASS | Right chunks, correct, grounded in both the termination and non-compete clauses. |
| ip_ownership | PASS | Right chunks, correct answer. |
| ip_assignment | PASS | Right chunk, correct answer. |
| jurisdiction | PASS | Right chunk, correct answer. |
| maternity_leave (no-answer control) | PASS | Correctly refuses — no hallucination. |
| probation (no-answer control) | PASS | Correctly refuses — no hallucination. |

**Tally: 17/24 pass, 7/24 fail.**
