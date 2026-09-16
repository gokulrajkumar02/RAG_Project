# Collected Traces — Legal Contract RAG

24 traces. Each is a real run of the app's live pipeline (FAISS top-10 -> cross-encoder rerank to top 3 -> Groq `openai/gpt-oss-20b`) against `data/sample_contract.pdf`, using the question set from `eval/questions.py`.

## parties

**Question:** Which company and individual signed this contract?

**Expected chunks:** [1]  |  **Answer must contain one of:** ['TechCorp', 'John Smith']

**Retrieved context:**

- chunk 1 (page 1): 'This Employment Agreement ("Agreement") is entered into as of January 1, 2024,\nbetween TechCorp Pvt. Ltd. ("Company") and John Smith ("Employee").'
- chunk 30 (page 2): 'SIGNATURES\nCompany Representative: __________________   Date: ______________\n                      TechCorp Pvt. Ltd.'
- chunk 0 (page 1): 'TechCorp Pvt. Ltd. - Confidential\nEMPLOYMENT AGREEMENT\nEmployment Agreement - TechCorp Pvt. Ltd.'

**Answer:**
> TechCorp Pvt. Ltd. and John Smith.

## job_role

**Question:** What position is being filled by this hire?

**Expected chunks:** [2]  |  **Answer must contain one of:** ['Software Engineer']

**Retrieved context:**

- chunk 2 (page 1): '1. POSITION AND DUTIES\nThe Employee is hired as a Software Engineer. The Employee shall report to the'
- chunk 1 (page 1): 'This Employment Agreement ("Agreement") is entered into as of January 1, 2024,\nbetween TechCorp Pvt. Ltd. ("Company") and John Smith ("Employee").'
- chunk 26 (page 2): 'course of employment shall be the sole and exclusive property of the Company.'

**Answer:**
> Software Engineer.

## reports_to

**Question:** Who is my direct manager?

**Expected chunks:** [2, 3]  |  **Answer must contain one of:** ['Engineering Manager']

**Retrieved context:**

- chunk 3 (page 1): 'Engineering Manager and perform duties as reasonably assigned by the Company.\n2. EFFECTIVE DATE'
- chunk 23 (page 2): 'termination, the Employee agrees not to directly or indirectly work for, consult with,'
- chunk 31 (page 2): 'Employee:             __________________   Date: ______________\n                      John Smith\nPage 2'

**Answer:**
> This information was not found in the contract.

## effective_date

**Question:** When does this employment officially begin?

**Expected chunks:** [4]  |  **Answer must contain one of:** ['January 1, 2024', 'January 1']

**Retrieved context:**

- chunk 1 (page 1): 'This Employment Agreement ("Agreement") is entered into as of January 1, 2024,\nbetween TechCorp Pvt. Ltd. ("Company") and John Smith ("Employee").'
- chunk 4 (page 1): '2. EFFECTIVE DATE\nThis Agreement commences on January 1, 2024, and continues until terminated by'
- chunk 22 (page 2): '9. NON-COMPETE CLAUSE\nDuring the term of employment and for a period of 6 (six) months following'

**Answer:**
> The employment officially begins on January 1, 2024.

## salary

**Question:** What is my take-home pay every month?

**Expected chunks:** [6, 7]  |  **Answer must contain one of:** ['80,000', 'Eighty Thousand']

**Retrieved context:**

- chunk 6 (page 1): 'The Employee shall receive a monthly gross salary of Rs. 80,000 (Eighty Thousand'
- chunk 7 (page 1): 'Rupees), payable on the last working day of each month. The Employee is also eligible'
- chunk 22 (page 2): '9. NON-COMPETE CLAUSE\nDuring the term of employment and for a period of 6 (six) months following'

**Answer:**
> This information was not found in the contract.

## bonus

**Question:** Could I get extra pay for good performance?

**Expected chunks:** [7, 8]  |  **Answer must contain one of:** ['bonus']

**Retrieved context:**

- chunk 8 (page 1): 'for an annual performance bonus at the sole discretion of the Company.\n4. WORKING HOURS'
- chunk 6 (page 1): 'The Employee shall receive a monthly gross salary of Rs. 80,000 (Eighty Thousand'
- chunk 7 (page 1): 'Rupees), payable on the last working day of each month. The Employee is also eligible'

**Answer:**
> Yes. The contract allows for an annual performance bonus, but it is awarded at the sole discretion of the Company.

## working_hours

**Question:** What time am I supposed to be at work, and when can I leave?

**Expected chunks:** [9]  |  **Answer must contain one of:** ['9:00 AM', '9 AM', 'Monday to Friday']

**Retrieved context:**

- chunk 9 (page 1): '4. WORKING HOURS\nThe standard working hours are Monday to Friday, 9:00 AM to 6:00 PM, with a'
- chunk 13 (page 1): "Leave must be applied for in advance and approved by the Employee's manager.\n6. NOTICE PERIOD"
- chunk 10 (page 1): 'one-hour lunch break. The Employee may be required to work reasonable additional hours'

**Answer:**
> You should be at work by 9:00 AM and can leave at 6:00 PM.

## overtime

**Question:** Do I get paid extra for staying late?

**Expected chunks:** [10, 11]  |  **Answer must contain one of:** ['overtime']

**Retrieved context:**

- chunk 7 (page 1): 'Rupees), payable on the last working day of each month. The Employee is also eligible'
- chunk 15 (page 1): 'notice to the other party. The Company reserves the right to pay salary in lieu of\nnotice and ask the Employee to leave immediately.\n7. TERMINATION'
- chunk 10 (page 1): 'one-hour lunch break. The Employee may be required to work reasonable additional hours'

**Answer:**
> This information was not found in the contract.

## annual_leave

**Question:** How much vacation do I get each year?

**Expected chunks:** [12]  |  **Answer must contain one of:** ['18 days', '18']

**Retrieved context:**

- chunk 12 (page 1): '- 18 days of Annual Leave\n  - 10 days of Sick Leave\n  - 3 days of Personal Leave\n  - Public holidays as declared by the Company'
- chunk 6 (page 1): 'The Employee shall receive a monthly gross salary of Rs. 80,000 (Eighty Thousand'
- chunk 11 (page 1): 'to meet business needs. Overtime is compensated as per Company policy.\n5. LEAVE POLICY\nThe Employee is entitled to the following paid leave per year:'

**Answer:**
> You are entitled to **18 days of annual (vacation) leave per year**.

## sick_leave

**Question:** What's the deal with sick days?

**Expected chunks:** [12]  |  **Answer must contain one of:** ['10 days', '10']

**Retrieved context:**

- chunk 12 (page 1): '- 18 days of Annual Leave\n  - 10 days of Sick Leave\n  - 3 days of Personal Leave\n  - Public holidays as declared by the Company'
- chunk 14 (page 1): '6. NOTICE PERIOD\nEither party may terminate this Agreement by providing 30 (thirty) days written'
- chunk 7 (page 1): 'Rupees), payable on the last working day of each month. The Employee is also eligible'

**Answer:**
> The contract provides for **10 days of Sick Leave**.

## leave_approval

**Question:** Can I just take time off whenever I feel like it?

**Expected chunks:** [13]  |  **Answer must contain one of:** ['approved', 'in advance']

**Retrieved context:**

- chunk 10 (page 1): 'one-hour lunch break. The Employee may be required to work reasonable additional hours'
- chunk 12 (page 1): '- 18 days of Annual Leave\n  - 10 days of Sick Leave\n  - 3 days of Personal Leave\n  - Public holidays as declared by the Company'
- chunk 9 (page 1): '4. WORKING HOURS\nThe standard working hours are Monday to Friday, 9:00 AM to 6:00 PM, with a'

**Answer:**
> No. The contract specifies only 18 days of Annual Leave, 10 days of Sick Leave, 3 days of Personal Leave, and public holidays. Time off must be taken under those categories and in accordance with the company’s procedures.

## notice_period

**Question:** If I want to quit, how much heads-up do I need to give?

**Expected chunks:** [14]  |  **Answer must contain one of:** ['30', 'thirty']

**Retrieved context:**

- chunk 10 (page 1): 'one-hour lunch break. The Employee may be required to work reasonable additional hours'
- chunk 12 (page 1): '- 18 days of Annual Leave\n  - 10 days of Sick Leave\n  - 3 days of Personal Leave\n  - Public holidays as declared by the Company'
- chunk 6 (page 1): 'The Employee shall receive a monthly gross salary of Rs. 80,000 (Eighty Thousand'

**Answer:**
> This information was not found in the contract.

## pay_in_lieu

**Question:** Could they just pay me off instead of letting me work my notice?

**Expected chunks:** [15]  |  **Answer must contain one of:** ['in lieu of notice', 'lieu of notice']

**Retrieved context:**

- chunk 15 (page 1): 'notice to the other party. The Company reserves the right to pay salary in lieu of\nnotice and ask the Employee to leave immediately.\n7. TERMINATION'
- chunk 16 (page 1): '7. TERMINATION\nThe Company may terminate this Agreement immediately and without notice for:\nPage 1'
- chunk 14 (page 1): '6. NOTICE PERIOD\nEither party may terminate this Agreement by providing 30 (thirty) days written'

**Answer:**
> Yes. The contract states that the Company reserves the right to pay salary in lieu of notice and ask the Employee to leave immediately.

## immediate_termination_fraud

**Question:** What happens if I get caught stealing from the company?

**Expected chunks:** [16, 17]  |  **Answer must contain one of:** ['theft', 'fraud']

**Retrieved context:**

- chunk 17 (page 2): 'TechCorp Pvt. Ltd. - Confidential\n  - Gross misconduct or negligence\n  - Persistent underperformance\n  - Theft, fraud, or dishonesty'
- chunk 18 (page 2): '- Serious or repeated breach of Company policies\n  - Willful breach of confidentiality\n8. CONFIDENTIALITY'
- chunk 26 (page 2): 'course of employment shall be the sole and exclusive property of the Company.'

**Answer:**
> It is classified as gross misconduct or negligence.

## confidentiality_dismissal

**Question:** Could breaking a confidentiality rule get me fired on the spot?

**Expected chunks:** [18]  |  **Answer must contain one of:** ['willful breach of confidentiality', 'breach of confidentiality']

**Retrieved context:**

- chunk 18 (page 2): '- Serious or repeated breach of Company policies\n  - Willful breach of confidentiality\n8. CONFIDENTIALITY'
- chunk 19 (page 2): '8. CONFIDENTIALITY\nThe Employee agrees to keep all Confidential Information strictly private, both'
- chunk 20 (page 2): 'during and after employment. Confidential Information includes but is not limited to:'

**Answer:**
> This information was not found in the contract.

## confidentiality_after

**Question:** After I resign, can I still be sued for leaking client info?

**Expected chunks:** [19, 20, 21]  |  **Answer must contain one of:** ['after employment']

**Retrieved context:**

- chunk 21 (page 2): 'business plans, client lists, financial data, technical documentation, and trade secrets.\nUnauthorized disclosure may result in legal action.'
- chunk 20 (page 2): 'during and after employment. Confidential Information includes but is not limited to:'
- chunk 19 (page 2): '8. CONFIDENTIALITY\nThe Employee agrees to keep all Confidential Information strictly private, both'

**Answer:**
> Yes. The confidentiality clause applies “during and after employment,” so you can still be sued for leaking client information after resigning.

## confidential_info_scope

**Question:** What counts as secret information I'm not allowed to share?

**Expected chunks:** [20, 21]  |  **Answer must contain one of:** ['business plans', 'client lists', 'trade secrets']

**Retrieved context:**

- chunk 19 (page 2): '8. CONFIDENTIALITY\nThe Employee agrees to keep all Confidential Information strictly private, both'
- chunk 20 (page 2): 'during and after employment. Confidential Information includes but is not limited to:'
- chunk 21 (page 2): 'business plans, client lists, financial data, technical documentation, and trade secrets.\nUnauthorized disclosure may result in legal action.'

**Answer:**
> Secret information you cannot share includes:

- Business plans  
- Client lists  
- Financial data  
- Technical documentation  
- Trade secrets  

These are covered under the confidentiality clause and must remain private during and after your employment.

## noncompete_duration

**Question:** If I leave, how soon can I go work for a competitor?

**Expected chunks:** [22]  |  **Answer must contain one of:** ['6', 'six months']

**Retrieved context:**

- chunk 22 (page 2): '9. NON-COMPETE CLAUSE\nDuring the term of employment and for a period of 6 (six) months following'
- chunk 12 (page 1): '- 18 days of Annual Leave\n  - 10 days of Sick Leave\n  - 3 days of Personal Leave\n  - Public holidays as declared by the Company'
- chunk 13 (page 1): "Leave must be applied for in advance and approved by the Employee's manager.\n6. NOTICE PERIOD"

**Answer:**
> After 6 months following the end of your employment.

## noncompete_consulting

**Question:** Am I allowed to freelance for a rival firm right after I resign?

**Expected chunks:** [22, 23]  |  **Answer must contain one of:** ['consult', 'competitor']

**Retrieved context:**

- chunk 15 (page 1): 'notice to the other party. The Company reserves the right to pay salary in lieu of\nnotice and ask the Employee to leave immediately.\n7. TERMINATION'
- chunk 23 (page 2): 'termination, the Employee agrees not to directly or indirectly work for, consult with,'
- chunk 22 (page 2): '9. NON-COMPETE CLAUSE\nDuring the term of employment and for a period of 6 (six) months following'

**Answer:**
> No. The contract’s termination clause requires the employee not to work for or consult with a rival, and the non‑compete clause extends that restriction for six months after resignation.

## ip_ownership

**Question:** Does the company own an app I build on the job?

**Expected chunks:** [25, 26]  |  **Answer must contain one of:** ['sole and exclusive property', 'Company']

**Retrieved context:**

- chunk 26 (page 2): 'course of employment shall be the sole and exclusive property of the Company.'
- chunk 25 (page 2): 'All inventions, software, designs, and other work created by the Employee in the'
- chunk 1 (page 1): 'This Employment Agreement ("Agreement") is entered into as of January 1, 2024,\nbetween TechCorp Pvt. Ltd. ("Company") and John Smith ("Employee").'

**Answer:**
> Yes. The agreement states that all inventions, software, designs, and other work created by the Employee in the course of employment are the sole and exclusive property of the Company.

## ip_assignment

**Question:** If asked, do I have to formally hand over my IP rights?

**Expected chunks:** [27]  |  **Answer must contain one of:** ['assign']

**Retrieved context:**

- chunk 27 (page 2): 'The Employee agrees to assign all such rights to the Company upon request.\n11. GOVERNING LAW'
- chunk 16 (page 1): '7. TERMINATION\nThe Company may terminate this Agreement immediately and without notice for:\nPage 1'
- chunk 24 (page 2): 'or hold ownership interest in any direct competitor of the Company operating in the\nsame geographic region.\n10. INTELLECTUAL PROPERTY'

**Answer:**
> Yes. The Employee agrees to assign all such rights to the Company upon request.

## jurisdiction

**Question:** If we end up in a legal fight, which city's courts handle it?

**Expected chunks:** [29]  |  **Answer must contain one of:** ['Bengaluru', 'Karnataka']

**Retrieved context:**

- chunk 29 (page 2): 'India. Any disputes arising under this Agreement shall be subject to the exclusive\njurisdiction of the courts in Bengaluru, Karnataka.\nSIGNATURES'
- chunk 28 (page 2): '11. GOVERNING LAW\nThis Agreement shall be governed by and construed in accordance with the laws of'
- chunk 23 (page 2): 'termination, the Employee agrees not to directly or indirectly work for, consult with,'

**Answer:**
> Bengaluru, Karnataka.

## maternity_leave

**Question:** Does this contract mention maternity or paternity leave?

_Control question — the contract does not contain this fact; correct behavior is refusal._

**Retrieved context:**

- chunk 16 (page 1): '7. TERMINATION\nThe Company may terminate this Agreement immediately and without notice for:\nPage 1'
- chunk 13 (page 1): "Leave must be applied for in advance and approved by the Employee's manager.\n6. NOTICE PERIOD"
- chunk 23 (page 2): 'termination, the Employee agrees not to directly or indirectly work for, consult with,'

**Answer:**
> This information was not found in the contract.

## probation

**Question:** Is there a probation period mentioned anywhere?

_Control question — the contract does not contain this fact; correct behavior is refusal._

**Retrieved context:**

- chunk 22 (page 2): '9. NON-COMPETE CLAUSE\nDuring the term of employment and for a period of 6 (six) months following'
- chunk 14 (page 1): '6. NOTICE PERIOD\nEither party may terminate this Agreement by providing 30 (thirty) days written'
- chunk 20 (page 2): 'during and after employment. Confidential Information includes but is not limited to:'

**Answer:**
> This information was not found in the contract.

