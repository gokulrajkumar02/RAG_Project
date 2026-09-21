# Judge Validation — Track F (Legal Contracts)

Judge graded against the same 24 human-labeled traces from `error_analysis/open_coding_notes.md`, using the exact retrieved context and generated answer the human read (`error_analysis/traces.json`).

**Agreement: 20/24 = 83.3%** (trust threshold: 80%)

| id | problem_type | human | judge | match | judge reason |
|---|---|---|---|---|---|
| parties | baseline_pass | PASS | PASS | True | The answer correctly names TechCorp Pvt. Ltd. and John Smith as the parties, which is stated in the contract. |
| job_role | baseline_pass | PASS | PASS | True | The contract explicitly states the employee is hired as a Software Engineer, directly answering the question. |
| reports_to | split_clause_refusal | FAIL | FAIL | True | The contract mentions an Engineering Manager, indicating the direct manager, but the assistant claimed the information was not found. |
| effective_date | baseline_pass | PASS | PASS | True | The contract explicitly states the agreement commences on January 1, 2024, confirming the employment start date. |
| salary | split_clause_refusal | FAIL | PASS | False | The contract does not provide take‑home pay, only gross salary, so the assistant correctly noted the information is not found. |
| bonus | baseline_pass | PASS | PASS | True | The answer correctly states that the contract provides for an annual performance bonus, but it is at the company's sole discretion, which matches the reference text. |
| working_hours | baseline_pass | PASS | PASS | True | The contract explicitly states standard working hours are 9:00 AM to 6:00 PM, which directly supports the answer. |
| overtime | never_retrieved_false_notfound | FAIL | PASS | False | The contract excerpt does not mention extra pay for additional hours, so stating the information was not found is accurate. |
| annual_leave | baseline_pass | PASS | PASS | True | The answer correctly states the 18 days of annual leave, which is directly supported by the contract text. |
| sick_leave | baseline_pass | PASS | PASS | True | The reference text explicitly states 10 days of Sick Leave, which matches the assistant's answer. |
| leave_approval | never_retrieved_lucky_pass | FAIL | PASS | False | Answer correctly cites the limited leave categories listed in the contract, indicating you cannot take time off arbitrarily. |
| notice_period | never_retrieved_false_notfound | FAIL | PASS | False | The contract excerpt contains no clause about resignation notice, so stating the information was not found is accurate and grounded. |
| pay_in_lieu | baseline_pass | PASS | PASS | True | The answer directly cites the contract clause allowing salary in lieu of notice. |
| immediate_termination_fraud | wrong_item_selected | FAIL | FAIL | True | The reference lists theft, fraud, or dishonesty as a separate item and also lists gross misconduct or negligence, but it does not state that theft is classified as gross misconduct or negligence. The assistant's answer is not directly supported by the contract text. |
| confidentiality_dismissal | split_clause_refusal | FAIL | FAIL | True | The assistant claims the information is not in the contract, but the contract explicitly mentions willful breach of confidentiality as a serious breach, which can lead to termination. |
| confidentiality_after | baseline_pass | PASS | PASS | True | The contract explicitly states confidentiality obligations apply during and after employment, supporting the answer. |
| confidential_info_scope | baseline_pass | PASS | PASS | True | The answer lists the exact items defined as Confidential Information in the contract. |
| noncompete_duration | baseline_pass | PASS | PASS | True | The contract states a 6‑month post‑employment restriction, matching the answer. |
| noncompete_consulting | baseline_pass | PASS | PASS | True | The answer correctly states the contract bans post‑termination work for a rival and adds the six‑month non‑compete, which the reference clauses support. |
| ip_ownership | baseline_pass | PASS | PASS | True | The answer directly reflects the contract clause stating that all work created in the course of employment is the Company's exclusive property. |
| ip_assignment | baseline_pass | PASS | PASS | True | The answer directly cites the clause stating the employee must assign all rights to the company upon request, which supports the yes answer. |
| jurisdiction | baseline_pass | PASS | PASS | True | The contract explicitly states disputes are subject to the exclusive jurisdiction of the courts in Bengaluru, Karnataka. |
| maternity_leave | no_answer_control | PASS | PASS | True | The contract text contains no mention of maternity or paternity leave, so the assistant correctly states the information was not found. |
| probation | no_answer_control | PASS | PASS | True | The contract excerpts contain no mention of a probation period, so the assistant correctly states the information is not found. |
