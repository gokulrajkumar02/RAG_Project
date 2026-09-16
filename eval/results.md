# Retrieval Debugging Report — Legal Contract RAG

Corpus: `data/sample_contract.pdf`, 32 chunks (chunk_size=150, chunk_overlap=20)

- **hit-rate@3 BEFORE (semantic-only FAISS, k=3)**: 90.91%

- **hit-rate@3 AFTER (FAISS top-10 -> cross-encoder rerank to top 3)**: 90.91%


## Inspection view (question / fetched / labeled failure)

| id | question | expected chunks | baseline chunks | baseline hit | reranked chunks | reranked hit | label |
|---|---|---|---|---|---|---|---|
| parties | Which company and individual signed this contract? | [1] | [5, 0, 30] | False | [1, 30, 0] | True | FIXED by reranking |
| job_role | What position is being filled by this hire? | [2] | [31, 2, 8] | True | [2, 1, 26] | True | HIT (both) |
| reports_to | Who is my direct manager? | [2, 3] | [3, 31, 23] | True | [3, 23, 31] | True | HIT (both) |
| effective_date | When does this employment officially begin? | [4] | [4, 1, 22] | True | [1, 4, 22] | True | HIT (both) |
| salary | What is my take-home pay every month? | [6, 7] | [7, 6, 8] | True | [6, 7, 22] | True | HIT (both) |
| bonus | Could I get extra pay for good performance? | [7, 8] | [8, 22, 10] | True | [8, 6, 7] | True | HIT (both) |
| working_hours | What time am I supposed to be at work, and when can I leave? | [9] | [9, 10, 13] | True | [9, 13, 10] | True | HIT (both) |
| overtime | Do I get paid extra for staying late? | [10, 11] | [8, 10, 15] | True | [7, 15, 10] | True | HIT (both) |
| annual_leave | How much vacation do I get each year? | [12] | [12, 8, 7] | True | [12, 6, 11] | True | HIT (both) |
| sick_leave | What's the deal with sick days? | [12] | [12, 10, 9] | True | [12, 14, 7] | True | HIT (both) |
| leave_approval | Can I just take time off whenever I feel like it? | [13] | [10, 13, 12] | True | [10, 12, 9] | False | REGRESSED by reranking |
| notice_period | If I want to quit, how much heads-up do I need to give? | [14] | [8, 23, 4] | False | [10, 12, 6] | False | RETRIEVAL FAILURE (wrong chunk fetched, both) |
| pay_in_lieu | Could they just pay me off instead of letting me work my notice? | [15] | [15, 13, 16] | True | [15, 16, 14] | True | HIT (both) |
| immediate_termination_fraud | What happens if I get caught stealing from the company? | [16, 17] | [21, 17, 16] | True | [17, 18, 26] | True | HIT (both) |
| confidentiality_dismissal | Could breaking a confidentiality rule get me fired on the spot? | [18] | [20, 18, 19] | True | [18, 19, 20] | True | HIT (both) |
| confidentiality_after | After I resign, can I still be sued for leaking client info? | [19, 20, 21] | [21, 20, 18] | True | [21, 20, 19] | True | HIT (both) |
| confidential_info_scope | What counts as secret information I'm not allowed to share? | [20, 21] | [21, 20, 19] | True | [19, 20, 21] | True | HIT (both) |
| noncompete_duration | If I leave, how soon can I go work for a competitor? | [22] | [22, 10, 8] | True | [22, 12, 13] | True | HIT (both) |
| noncompete_consulting | Am I allowed to freelance for a rival firm right after I resign? | [22, 23] | [26, 23, 22] | True | [15, 23, 22] | True | HIT (both) |
| ip_ownership | Does the company own an app I build on the job? | [25, 26] | [25, 26, 24] | True | [26, 25, 1] | True | HIT (both) |
| ip_assignment | If asked, do I have to formally hand over my IP rights? | [27] | [27, 28, 26] | True | [27, 16, 24] | True | HIT (both) |
| jurisdiction | If we end up in a legal fight, which city's courts handle it? | [29] | [29, 28, 16] | True | [29, 28, 23] | True | HIT (both) |

## No-answer control questions

- **maternity_leave**: "Does this contract mention maternity or paternity leave?" → top reranked chunks = [16, 13, 23]
- **probation**: "Is there a probation period mentioned anywhere?" → top reranked chunks = [22, 14, 20]
