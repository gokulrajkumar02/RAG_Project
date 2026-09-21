# Week 6 Eval Report — Track F (Legal Contracts)

One command (`python eval/run_evals.py`): validates the judge, runs all 24 questions before/after the neighbor-stitch fix (`ContractIndex.expand_with_neighbors`, `rag_core.py`), scores each with free rule checks + the validated LLM judge, and reports before/after per Week 5 problem type.

## Judge validation

Agreement with human grading (`error_analysis/open_coding_notes.md`): **20/24 = 83.3%** (trust threshold: 80%). Full breakdown: [`judge_validation.md`](judge_validation.md).

## Score by problem type

| problem_type | before | after |
|---|---|---|
| baseline_pass | 13/15 (87%) | 11/15 (73%) |
| never_retrieved_false_notfound | 0/2 (0%) | 0/2 (0%) |
| never_retrieved_lucky_pass | 0/1 (0%) | 0/1 (0%) |
| no_answer_control | 2/2 (100%) | 2/2 (100%) |
| split_clause_refusal | 0/3 (0%) | 1/3 (33%) |
| wrong_item_selected | 0/1 (0%) | 0/1 (0%) |

**OVERALL — before: 15/24 = 62.5%, after: 14/24 = 58.3%**

## Per-question detail

| id | problem_type | before | after | before answer | after answer | judge reason (after) |
|---|---|---|---|---|---|---|
| parties | baseline_pass | PASS | PASS | TechCorp Pvt. Ltd. and John Smith. | TechCorp Pvt. Ltd. and John Smith. | The answer correctly names the company and individual as stated in the contract. |
| job_role | baseline_pass | PASS | PASS | Software Engineer. | Software Engineer. | The reference text explicitly states the employee is hired as a Software Engineer, which directly answers the question. |
| reports_to | split_clause_refusal | FAIL | PASS | This information was not found in the contract. | Engineering Manager | The contract explicitly states the employee reports to the Engineering Manager, directly answering the question. |
| effective_date | baseline_pass | FAIL | FAIL | The employment officially begins on January 1, 2024. | The employment officially begins on January 1, 2024. | The answer directly matches the effective date stated in the contract. |
| salary | split_clause_refusal | FAIL | FAIL | This information was not found in the contract. | This information was not found in the contract. | The contract states a monthly gross salary of Rs. 80,000, so the information is present; the assistant incorrectly claimed it was not found. |
| bonus | baseline_pass | PASS | PASS | Yes. The contract allows for an annual performance bonus, but it is awarded at the sole discretion of the Company. | Yes. The contract provides for an annual performance bonus that is awarded at the sole discretion of the Company. | The answer correctly states the contract provides an annual performance bonus, which is supported by the reference text. |
| working_hours | baseline_pass | FAIL | FAIL | You should be at work at **9:00 AM** and can leave at **6:00 PM**. | You are expected to start work at **9:00 AM** and finish at **6:00 PM** (Monday to Friday). The schedule includes a one‑hour lunch break, but the start and end times remain 9:00 AM to 6:00 PM. | The assistant added a claim about a one‑hour lunch break, which is not supported by the provided contract text. |
| overtime | never_retrieved_false_notfound | FAIL | FAIL | This information was not found in the contract. | This information was not found in the contract. | The contract explicitly states that overtime is compensated as per Company policy, so the assistant's claim that the information was not found is incorrect. |
| annual_leave | baseline_pass | PASS | PASS | You are entitled to **18 days of annual (vacation) leave per year**. | You are entitled to **18 days of annual (vacation) leave per year**. | The answer directly states the 18 days of annual (vacation) leave, which matches the reference contract text. |
| sick_leave | baseline_pass | PASS | FAIL | The contract provides for **10 days of Sick Leave**. | The contract provides that the employee is entitled to **10 paid sick days per year**. These days must be applied for in advance and approved by the employee’s manager. | Adds unsupported conditions about application and manager approval |
| leave_approval | never_retrieved_lucky_pass | FAIL | FAIL | No. The contract specifies only 18 days of Annual Leave, 10 days of Sick Leave, 3 days of Personal Leave, and public holidays. Time off must be taken under those categories and in accordance with the company’s procedures. | This information was not found in the contract. | The contract explicitly states that leave must be applied for in advance and approved by the manager, directly answering the question. The assistant incorrectly claimed the information was not found. |
| notice_period | never_retrieved_false_notfound | FAIL | FAIL | This information was not found in the contract. | This information was not found in the contract. | The contract explicitly states a 30‑day written notice period, but the assistant claimed the information was not found, which is incorrect and ungrounded. |
| pay_in_lieu | baseline_pass | PASS | PASS | Yes. The contract states that the Company reserves the right to pay salary in lieu of notice and ask the Employee to leave immediately. | Yes. The contract states that the Company reserves the right to pay salary in lieu of notice and ask the Employee to leave immediately. | The answer directly quotes the contract clause allowing payment in lieu of notice. |
| immediate_termination_fraud | wrong_item_selected | FAIL | FAIL | It is classified as gross misconduct or negligence. | The company may terminate your agreement immediately and without notice if you are found to have stolen from the company. | The answer directly reflects the contract clause stating termination for theft. |
| confidentiality_dismissal | split_clause_refusal | FAIL | FAIL | This information was not found in the contract. | Yes. A willful breach of confidentiality is listed as a serious or repeated breach of company policies, which can lead to immediate termination. | The answer asserts that a willful breach leads to immediate termination, but the reference only states it is a serious breach; it does not explicitly mention termination. |
| confidentiality_after | baseline_pass | PASS | PASS | Yes. The confidentiality clause applies “during and after employment,” so you can still be sued for leaking client information after resigning. | Yes. The confidentiality obligations apply both during and after employment, so you can still be sued for leaking client information after resigning. | The answer directly reflects the contract clause stating confidentiality obligations continue after employment and that unauthorized disclosure may lead to legal action. |
| confidential_info_scope | baseline_pass | PASS | PASS | Secret information you cannot share includes:

- Business plans  
- Client lists  
- Financial data  
- Technical documentation  
- Trade secrets  

These are covered under the confidentiality clause and must remain private during and after your employment. | Secret information you cannot share includes:

- Business plans  
- Client lists  
- Financial data  
- Technical documentation  
- Trade secrets  

(Any other confidential information is also protected.) | The listed items match the contract's examples and the 'includes but is not limited to' clause supports the broader statement. |
| noncompete_duration | baseline_pass | PASS | PASS | You may not work for a competitor for 6 (six) months after leaving. | You may not work for a competitor for 6 (six) months after your employment ends. After that period, you may seek employment with a competitor. | The answer correctly states the 6‑month post‑employment restriction, which is directly supported by the non‑compete clause. |
| noncompete_consulting | baseline_pass | PASS | FAIL | No. The contract’s non‑compete clause bars you from working for or consulting with a rival firm for six months after termination, so you cannot freelance for a rival immediately after resigning. | No. The contract’s non‑compete clause (Section 7 and Section 9) prohibits the Employee from directly or indirectly working for or consulting with a rival firm for a period of six months following termination. | The answer incorrectly references Section 7, which is not present in the provided contract text; only Section 9 is supported. |
| ip_ownership | baseline_pass | PASS | PASS | Yes. The agreement states that all inventions, software, designs, and other work created by the Employee in the course of employment are the sole and exclusive property of the Company. | Yes. All inventions, software, designs, and other work created by the Employee in the course of employment are the sole and exclusive property of the Company. | The answer directly mirrors the contract clause stating that all such work is the company's exclusive property. |
| ip_assignment | baseline_pass | PASS | PASS | Yes. The Employee agrees to assign all such rights to the Company upon request. | Yes. The Employee agrees to assign all such rights to the Company upon request, so you must formally hand over your IP rights when asked. | Answer directly cites the contract clause assigning rights upon request. |
| jurisdiction | baseline_pass | PASS | PASS | Bengaluru, Karnataka. | Bengaluru, Karnataka. | The answer directly matches the contract clause stating disputes are under the exclusive jurisdiction of the courts in Bengaluru, Karnataka. |
| maternity_leave | no_answer_control | PASS | PASS | This information was not found in the contract. | This information was not found in the contract. |  |
| probation | no_answer_control | PASS | PASS | This information was not found in the contract. | This information was not found in the contract. |  |
