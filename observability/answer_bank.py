"""
Answer bank for the SYNTHETIC production week (traffic.py). Not used by the app, the eval suite or the fix.

Each intent is one thing people ask about this contract: a few phrasings (lawyer, HR and employee voices),
the correct answer (worded from the contract's own text in data/sample_contract.pdf), the clause it comes
from, and a `support` key: text that must be in the retrieved context for the answer to be groundable.
When the real retrieval for a logged request did not fetch that text, the logged answer is the not-found
sentence instead - the same failure the real app shows (Week 5's never_retrieved_false_notfound).

Every answer here is CORRECT, including its clause citation. That is deliberate: the drill is a test of the
logs and the search tooling, so the haystack must contain exactly one bad answer - the one a squadmate plants.
"""

NOT_FOUND = "This information was not found in the contract."

# clause id -> how a citing answer names it
CLAUSE_NAMES = {
    "preamble": "Preamble", "1": "Position and Duties", "2": "Effective Date", "3": "Salary and Compensation",
    "4": "Working Hours", "5": "Leave Policy", "6": "Notice Period", "7": "Termination", "8": "Confidentiality",
    "9": "Non-Compete", "10": "Intellectual Property", "11": "Governing Law",
}

INTENTS = {
    "parties": dict(clause="preamble", support=["and john smith"], answer=(
        'The agreement is between TechCorp Pvt. Ltd. (the "Company") and John Smith (the "Employee").'), phrasings=[
        "Who are the parties to this agreement?", "Which company and individual signed this contract?",
        "Who is the employer named in the agreement?", "who signed this"]),
    "role": dict(clause="1", support=["hired as a software engineer"], answer=(
        "John Smith is hired as a Software Engineer."), phrasings=[
        "What position is the employee hired for?", "What is the employee's job title?",
        "What role was John Smith hired into?"]),
    "reports_to": dict(clause="1", support=["engineering manager"], answer=(
        "The Employee reports to the Engineering Manager."), phrasings=[
        "Who does the employee report to?", "Who is my direct manager?", "Which manager does this role report into?"]),
    "start_date": dict(clause="2", support=["commences on january 1, 2024", "entered into as of january 1, 2024"],
                       answer="The agreement commences on January 1, 2024.", phrasings=[
        "When does the agreement take effect?", "What is the commencement date?",
        "When does this employment officially begin?", "effective date of the contract?"]),
    "term": dict(clause="2", support=["continues until terminated"], answer=(
        "There is no fixed end date: the agreement commences on January 1, 2024 and continues until terminated "
        "by either party in accordance with its terms."), phrasings=[
        "Is this a fixed-term contract?", "Does the agreement have an end date?", "How long does the contract run?"]),
    "salary": dict(clause="3", support=["rs. 80,000"], answer=(
        "A monthly gross salary of Rs. 80,000 (Eighty Thousand Rupees), payable on the last working day of each "
        "month."), phrasings=[
        "What is the monthly salary?", "How much is the employee paid?", "What is my take-home pay every month?",
        "when is salary paid"]),
    "bonus": dict(clause="3", support=["annual performance bonus"], answer=(
        "Yes - the Employee is eligible for an annual performance bonus, at the sole discretion of the Company."),
                  phrasings=["Is there a performance bonus?", "Could I get extra pay for good performance?",
                             "Is the bonus guaranteed?"]),
    "hours": dict(clause="4", support=["9:00 am to 6:00 pm"], answer=(
        "Monday to Friday, 9:00 AM to 6:00 PM, with a one-hour lunch break."), phrasings=[
        "What are the working hours?", "What time am I supposed to be at work?", "Is there a lunch break?"]),
    "overtime": dict(clause="4", support=["overtime is compensated"], answer=(
        "The Employee may be required to work reasonable additional hours; overtime is compensated as per "
        "Company policy."), phrasings=[
        "Is overtime paid?", "Do I get paid extra for staying late?", "Can the company make me work extra hours?"]),
    "annual_leave": dict(clause="5", support=["18 days of annual leave"], answer="18 days of Annual Leave per year.",
                         phrasings=["How many days of annual leave are there?", "How much vacation do I get each year?",
                                    "annual leave entitlement?"]),
    "sick_leave": dict(clause="5", support=["10 days of sick leave"], answer="10 days of Sick Leave per year.",
                       phrasings=["How many sick days does the employee get?", "What's the deal with sick days?"]),
    "personal_leave": dict(clause="5", support=["3 days of personal leave"], answer=(
        "3 days of Personal Leave per year, plus public holidays as declared by the Company."), phrasings=[
        "Is there personal leave?", "Do we get public holidays off?"]),
    "leave_approval": dict(clause="5", support=["applied for in advance"], answer=(
        "No - leave must be applied for in advance and approved by the Employee's manager."), phrasings=[
        "Does leave need approval?", "Can I just take time off whenever I feel like it?",
        "Who approves leave requests?"]),
    "notice_resign": dict(clause="6", support=["30 (thirty) days written"], answer=(
        "The Employee must give 30 (thirty) days' written notice; the same period applies to the Company."),
                          phrasings=[
        "How much notice does the employee need to give to resign?", "What's the notice period if John wants to quit?",
        "If I want to quit, how much heads-up do I need to give?", "resignation notice period?"]),
    "notice_employer": dict(clause="6", support=["30 (thirty) days written"], answer=(
        "Either party may terminate the agreement by giving 30 (thirty) days' written notice; the Company may pay "
        "salary in lieu of notice instead."), phrasings=[
        "How much notice must the Company give to terminate the agreement?",
        "Can the Company terminate without cause, and on what notice?",
        "What notice is the employer required to give before ending the contract?",
        "Can either party end the agreement on notice?"]),
    "pay_in_lieu": dict(clause="6", support=["pay salary in lieu"], answer=(
        "Yes. The Company reserves the right to pay salary in lieu of notice and ask the Employee to leave "
        "immediately."), phrasings=[
        "Can the Company pay salary in lieu of notice?", "Could they just pay me off instead of letting me work my notice?",
        "Is pay in lieu of notice allowed?", "Can the employee be asked to leave immediately during the notice period?"]),
    "for_cause_grounds": dict(clause="7", support=["immediately and without notice", "gross misconduct or negligence"],
                              answer=(
        "The Company may terminate immediately and without notice for: gross misconduct or negligence; persistent "
        "underperformance; theft, fraud, or dishonesty; serious or repeated breach of Company policies; or willful "
        "breach of confidentiality."), phrasings=[
        "What are the grounds for termination without notice?", "When can the Company terminate immediately?",
        "List the summary dismissal grounds.", "On what grounds can the employee be fired on the spot?"]),
    "for_cause_theft": dict(clause="7", support=["theft, fraud, or dishonesty"], answer=(
        "Yes. Theft, fraud, or dishonesty allows the Company to terminate immediately and without notice."), phrasings=[
        "Can an employee be dismissed on the spot for theft or fraud?",
        "What happens if I get caught stealing from the company?", "Is dishonesty grounds for immediate termination?"]),
    "for_cause_underperformance": dict(clause="7", support=["persistent underperformance"], answer=(
        "Yes. Persistent underperformance is one of the grounds on which the Company may terminate immediately and "
        "without notice."), phrasings=[
        "Is persistent underperformance a ground for immediate termination?",
        "Can the company fire someone without notice for poor performance?"]),
    "for_cause_policy": dict(clause="7", support=["serious or repeated breach"], answer=(
        "Only a serious or repeated breach of Company policies - that is a ground for immediate termination without "
        "notice."), phrasings=[
        "Can the Company fire someone immediately for breaching company policy?",
        "Does a single policy breach justify termination without notice?"]),
    "for_cause_confidentiality": dict(clause="7", support=["willful breach of confidentiality"], answer=(
        "Yes. Willful breach of confidentiality is a ground on which the Company may terminate immediately and "
        "without notice."), phrasings=[
        "Can a willful breach of confidentiality lead to summary dismissal?",
        "Could breaking a confidentiality rule get me fired on the spot?",
        "Is leaking confidential information grounds for termination without notice?"]),
    "for_cause_misconduct": dict(clause="7", support=["gross misconduct or negligence"], answer=(
        "Yes. Gross misconduct or negligence allows the Company to terminate immediately and without notice."),
                                 phrasings=["Is gross misconduct grounds for termination without notice?",
                                            "Can negligence get an employee terminated immediately?"]),
    "conf_survival": dict(clause="8", support=["during and after employment"], answer=(
        "Yes. Confidential Information must be kept strictly private both during and after employment."), phrasings=[
        "Do confidentiality obligations survive termination?",
        "After I resign, can I still be sued for leaking client info?",
        "Is the employee still bound by confidentiality after leaving?"]),
    "conf_scope": dict(clause="8", support=["client lists"], answer=(
        "Confidential Information includes, but is not limited to, business plans, client lists, financial data, "
        "technical documentation, and trade secrets."), phrasings=[
        "What counts as Confidential Information?", "What counts as secret information I'm not allowed to share?"]),
    "conf_consequence": dict(clause="8", support=["unauthorized disclosure"], answer=(
        "Unauthorized disclosure may result in legal action."), phrasings=[
        "What happens on unauthorized disclosure of confidential information?",
        "Can the company take legal action over a leak?"]),
    "nc_duration": dict(clause="9", support=["6 (six) months"], answer=(
        "During employment and for 6 (six) months following termination."), phrasings=[
        "How long does the non-compete last after termination?", "If I leave, how soon can I go work for a competitor?",
        "non-compete duration?"]),
    "nc_scope": dict(clause="9", support=["consult with"], answer=(
        "The Employee may not directly or indirectly work for, consult with, or hold an ownership interest in any "
        "direct competitor operating in the same geographic region."), phrasings=[
        "What does the non-compete prohibit?", "Am I allowed to freelance for a rival firm right after I resign?",
        "Does the non-compete cover consulting for a competitor?"]),
    "ip_ownership": dict(clause="10", support=["sole and exclusive property"], answer=(
        "The Company. All inventions, software, designs and other work created in the course of employment are its "
        "sole and exclusive property."), phrasings=[
        "Who owns software the employee writes?", "Does the company own an app I build on the job?",
        "Who owns inventions made during employment?"]),
    "ip_assign": dict(clause="10", support=["assign all such rights"], answer=(
        "Yes. The Employee agrees to assign all such rights to the Company upon request."), phrasings=[
        "Must the employee assign IP rights?", "If asked, do I have to formally hand over my IP rights?"]),
    "governing_law": dict(clause="11", support=["governed by and construed"], answer="The laws of India.", phrasings=[
        "Which law governs the agreement?", "What is the governing law?"]),
    "jurisdiction": dict(clause="11", support=["bengaluru, karnataka"], answer=(
        "The courts in Bengaluru, Karnataka have exclusive jurisdiction over disputes."), phrasings=[
        "Which courts have jurisdiction?", "If we end up in a legal fight, which city's courts handle it?",
        "Where would a dispute be heard?"]),
    # the contract says nothing about these: the correct answer is the not-found sentence
    "probation": dict(clause=None, support=None, answer=NOT_FOUND, phrasings=[
        "Is there a probation period?", "Is there a probation period mentioned anywhere?"]),
    "maternity": dict(clause=None, support=None, answer=NOT_FOUND, phrasings=[
        "Does the contract mention maternity or paternity leave?", "Is there parental leave?"]),
    "severance": dict(clause=None, support=None, answer=NOT_FOUND, phrasings=[
        "Is the employee entitled to severance pay on termination?", "Does the company owe severance if it fires me?"]),
    "remote_work": dict(clause=None, support=None, answer=NOT_FOUND, phrasings=[
        "Can the employee work from home?", "Is remote work allowed under the contract?"]),
}

# Lawyers paste clauses from other agreements to compare: long inputs, the haystack's cost outliers.
PASTED = [
    dict(source="our UK template", clause="6", support=["pay salary in lieu"], text=(
        "Garden Leave. During all or any part of any period of notice (whether given by the Company or the Employee), "
        "the Company may in its absolute discretion require the Employee: (a) not to attend any premises of the "
        "Company or any Group Company; (b) to carry out no duties or only such duties as the Company may specify; "
        "(c) not to contact or deal with (or attempt to contact or deal with) any officer, employee, consultant, "
        "client, customer, supplier, agent, distributor, shareholder, adviser or other business contact of the "
        "Company or any Group Company; and (d) to return all Company property. During any period of Garden Leave "
        "the Employee shall continue to receive basic salary and contractual benefits and shall remain bound by "
        "all duties of fidelity and good faith owed to the Company."), answer=(
        "There is no garden-leave provision. The closest is the Company's right to pay salary in lieu of notice "
        "and ask the Employee to leave immediately.")),
    dict(source="the Acme MSA", clause="6", support=["30 (thirty) days written"], text=(
        "Termination for Convenience. Either Party may terminate this Agreement, or any Statement of Work issued "
        "hereunder, for convenience and without cause upon ninety (90) days' prior written notice to the other "
        "Party. Upon any such termination, Customer shall pay Supplier for all Services performed and expenses "
        "incurred through the effective date of termination, together with any non-cancellable commitments "
        "entered into in good faith prior to receipt of the notice of termination, and Supplier shall deliver to "
        "Customer all work product, whether complete or in progress, for which Customer has paid. Sections 7 "
        "(Confidentiality), 9 (Indemnification) and 12 (Limitation of Liability) shall survive termination."),
         answer=("Our agreement has no 90-day convenience right: either party may terminate on 30 (thirty) days' "
                 "written notice.")),
    dict(source="the Brightline vendor agreement", clause=None, support=None, text=(
        "Limitation of Liability. EXCEPT FOR LIABILITY ARISING FROM A PARTY'S GROSS NEGLIGENCE, WILFUL MISCONDUCT, "
        "OR BREACH OF ITS CONFIDENTIALITY OBLIGATIONS, IN NO EVENT SHALL EITHER PARTY'S AGGREGATE LIABILITY ARISING "
        "OUT OF OR RELATED TO THIS AGREEMENT, WHETHER IN CONTRACT, TORT OR UNDER ANY OTHER THEORY OF LIABILITY, "
        "EXCEED THE TOTAL AMOUNTS PAID BY CUSTOMER HEREUNDER IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING "
        "RISE TO THE CLAIM. IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, "
        "CONSEQUENTIAL OR PUNITIVE DAMAGES, OR FOR LOSS OF PROFITS, REVENUE OR DATA, EVEN IF ADVISED OF THE "
        "POSSIBILITY OF SUCH DAMAGES."), answer=NOT_FOUND),
    dict(source="the 2023 senior-hire template", clause="9", support=["6 (six) months"], text=(
        "Non-Solicitation. For a period of twelve (12) months following the Termination Date, the Executive shall "
        "not, directly or indirectly, whether on his own account or on behalf of any other person, firm or company, "
        "solicit or entice away, or attempt to solicit or entice away, from the Company or any Group Company any "
        "person who was at the Termination Date, or at any time during the twelve (12) months preceding it, an "
        "employee of senior or managerial status with whom the Executive had material dealings, whether or not "
        "such person would commit a breach of contract by reason of leaving service."), answer=(
        "There is no non-solicitation clause. The closest restriction is the non-compete: for 6 (six) months after "
        "termination the Employee may not work for, consult with or hold an interest in a direct competitor.")),
    dict(source="the 2023 senior-hire template", clause="7", support=["immediately and without notice",
                                                                      "gross misconduct or negligence"], text=(
        "Summary Termination. The Company may terminate the Executive's employment with immediate effect without "
        "notice and with no liability to make any further payment (other than in respect of amounts accrued due at "
        "the Termination Date) if the Executive: (a) is guilty of any gross misconduct affecting the business of "
        "the Company; (b) commits any serious or repeated breach or non-observance of any of the provisions of "
        "this agreement; (c) is convicted of any criminal offence (other than an offence under any road traffic "
        "legislation for which a non-custodial penalty is imposed); (d) is guilty of any fraud or dishonesty or "
        "acts in any manner which in the opinion of the Board brings or is likely to bring the Executive or the "
        "Company into disrepute; or (e) becomes bankrupt or makes any arrangement with his creditors generally."),
         answer=("Ours is narrower: the Company may terminate immediately and without notice only for gross "
                 "misconduct or negligence, persistent underperformance, theft, fraud, or dishonesty, serious or "
                 "repeated breach of Company policies, or willful breach of confidentiality. Criminal conviction, "
                 "disrepute and bankruptcy are not listed.")),
]
PASTED_ASKS = [
    'Compare this clause from {source} with ours - do we have an equivalent?\n\n"{text}"',
    'Does our agreement contain anything like this ({source})?\n\n{text}',
]

ROLE_INTENT_WEIGHTS = {
    "lawyer": dict(notice_resign=3, notice_employer=6, pay_in_lieu=6, for_cause_grounds=7, for_cause_theft=3,
                   for_cause_underperformance=3, for_cause_policy=3, for_cause_confidentiality=5,
                   for_cause_misconduct=3, term=3, conf_survival=4, conf_scope=2, conf_consequence=2, nc_duration=4,
                   nc_scope=3, ip_ownership=2, ip_assign=3, governing_law=3, jurisdiction=3, parties=2, start_date=1,
                   severance=2, probation=1),
    "paralegal": dict(parties=4, start_date=4, role=2, term=3, governing_law=3, jurisdiction=3, notice_employer=3,
                      for_cause_grounds=2, ip_assign=2, conf_scope=2, salary=2, nc_duration=2, maternity=1,
                      pay_in_lieu=1),
    "hr": dict(annual_leave=5, sick_leave=5, personal_leave=3, leave_approval=4, hours=4, overtime=4, salary=4,
               bonus=3, notice_resign=5, notice_employer=3, pay_in_lieu=2, for_cause_grounds=3,
               for_cause_underperformance=3, probation=3, maternity=3, reports_to=2, role=2),
    "employee": dict(annual_leave=5, sick_leave=4, salary=4, bonus=4, hours=3, overtime=4, leave_approval=3,
                     notice_resign=5, nc_duration=4, nc_scope=3, ip_ownership=3, conf_survival=2, remote_work=2,
                     maternity=2, for_cause_theft=1, reports_to=2),
}


def norm(text):
    return " ".join(text.lower().replace("“", '"').replace("”", '"').split())


def supported(support, context_docs):
    if not support:
        return True
    ctx = norm(" ".join(d.page_content for d in context_docs))
    return any(norm(key) in ctx for key in support)


def render(answer, clause, cites, is_supported, style):
    """The logged answer: not-found when retrieval missed the support; a citation only when the prompt
    version asks for one (answer-v1 did not)."""
    if not is_supported or answer == NOT_FOUND or clause is None:
        return answer if is_supported else NOT_FOUND
    if not cites:
        return answer
    name = CLAUSE_NAMES[clause]
    ref = f"Clause {clause} ({name})" if clause.isdigit() else name
    if style == 0:
        return f"{answer} ({ref})"
    if style == 1:
        return f"Under {ref}: {answer}"
    return f"{answer} See {ref}."
