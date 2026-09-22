# Week 7 Agent Race Report — Track F (Legal Contracts)

One command (`python agent/race.py`): races the hand-built retry/reformulate agent (`contract_agent.py`) against the existing fixed pipeline (`fixed_workflow.py` — the same search_reranked + expand_with_neighbors + generate_answer app.py runs live) on the same 24 questions, scored with the Week 6 rule check + validated LLM judge.

## Overall

| metric | fixed | agent |
|---|---|---|
| pass rate | 14/24 (58.3%) | 15/24 (62.5%) |
| avg seconds/question | 1.29 | 13.52 |
| total seconds | 31.0 | 324.4 |
| avg LLM calls/question | 1.00 | 2.92 |
| total LLM calls | 24 | 70 |

## Score by problem type

| problem_type | fixed | agent |
|---|---|---|
| baseline_pass | 11/15 | 10/15 |
| never_retrieved_false_notfound | 0/2 | 2/2 |
| never_retrieved_lucky_pass | 0/1 | 0/1 |
| no_answer_control | 2/2 | 1/2 |
| split_clause_refusal | 1/3 | 1/3 |
| wrong_item_selected | 0/1 | 1/1 |

## Per-question detail

| id | problem_type | fixed | agent | fixed_s | agent_s | fixed_calls | agent_calls | agent tool calls |
|---|---|---|---|---|---|---|---|---|
| parties | baseline_pass | PASS | PASS | 2.46 | 3.88 | 1 | 3 | 1 |
| job_role | baseline_pass | PASS | PASS | 1.05 | 2.51 | 1 | 2 | 1 |
| reports_to | split_clause_refusal | PASS | PASS | 1.15 | 3.98 | 1 | 3 | 1 |
| effective_date | baseline_pass | FAIL | PASS | 1.30 | 2.58 | 1 | 2 | 1 |
| salary | split_clause_refusal | FAIL | FAIL | 1.15 | 31.39 | 1 | 6 | 1 |
| bonus | baseline_pass | PASS | PASS | 1.17 | 10.75 | 1 | 2 | 1 |
| working_hours | baseline_pass | FAIL | FAIL | 1.18 | 10.29 | 1 | 2 | 1 |
| overtime | never_retrieved_false_notfound | FAIL | PASS | 1.49 | 10.76 | 1 | 2 | 1 |
| annual_leave | baseline_pass | PASS | PASS | 0.90 | 11.36 | 1 | 2 | 1 |
| sick_leave | baseline_pass | FAIL | FAIL | 1.18 | 12.23 | 1 | 2 | 1 |
| leave_approval | never_retrieved_lucky_pass | FAIL | FAIL | 1.42 | 8.66 | 1 | 2 | 1 |
| notice_period | never_retrieved_false_notfound | FAIL | PASS | 1.21 | 13.37 | 1 | 2 | 1 |
| pay_in_lieu | baseline_pass | PASS | PASS | 1.16 | 8.69 | 1 | 2 | 1 |
| immediate_termination_fraud | wrong_item_selected | FAIL | PASS | 1.18 | 15.45 | 1 | 3 | 1 |
| confidentiality_dismissal | split_clause_refusal | FAIL | FAIL | 2.58 | 11.55 | 1 | 2 | 1 |
| confidentiality_after | baseline_pass | FAIL | PASS | 1.30 | 10.76 | 1 | 2 | 1 |
| confidential_info_scope | baseline_pass | PASS | PASS | 1.15 | 37.30 | 1 | 6 | 3 |
| noncompete_duration | baseline_pass | PASS | FAIL | 1.25 | 15.19 | 1 | 3 | 1 |
| noncompete_consulting | baseline_pass | PASS | FAIL | 1.29 | 10.77 | 1 | 2 | 1 |
| ip_ownership | baseline_pass | PASS | PASS | 0.88 | 9.42 | 1 | 2 | 1 |
| ip_assignment | baseline_pass | PASS | FAIL | 1.16 | 29.35 | 1 | 6 | 1 |
| jurisdiction | baseline_pass | PASS | PASS | 1.13 | 11.03 | 1 | 3 | 1 |
| maternity_leave | no_answer_control | PASS | FAIL | 1.10 | 20.89 | 1 | 4 | 3 |
| probation | no_answer_control | PASS | PASS | 1.11 | 22.26 | 1 | 5 | 3 |
