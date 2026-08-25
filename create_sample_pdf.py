"""
Run this script to generate a sample Employment Contract PDF for testing.

Usage:
    python create_sample_pdf.py

Output:
    data/sample_contract.pdf
"""

from fpdf import FPDF
import os


TITLE = "EMPLOYMENT AGREEMENT"

SECTIONS = [
    ("", """This Employment Agreement ("Agreement") is entered into as of January 1, 2024,
between TechCorp Pvt. Ltd. ("Company") and John Smith ("Employee")."""),

    ("1. POSITION AND DUTIES",
     """The Employee is hired as a Software Engineer. The Employee shall report to the
Engineering Manager and perform duties as reasonably assigned by the Company."""),

    ("2. EFFECTIVE DATE",
     """This Agreement commences on January 1, 2024, and continues until terminated by
either party in accordance with the terms of this Agreement."""),

    ("3. SALARY AND COMPENSATION",
     """The Employee shall receive a monthly gross salary of Rs. 80,000 (Eighty Thousand
Rupees), payable on the last working day of each month. The Employee is also eligible
for an annual performance bonus at the sole discretion of the Company."""),

    ("4. WORKING HOURS",
     """The standard working hours are Monday to Friday, 9:00 AM to 6:00 PM, with a
one-hour lunch break. The Employee may be required to work reasonable additional hours
to meet business needs. Overtime is compensated as per Company policy."""),

    ("5. LEAVE POLICY",
     """The Employee is entitled to the following paid leave per year:
  - 18 days of Annual Leave
  - 10 days of Sick Leave
  - 3 days of Personal Leave
  - Public holidays as declared by the Company
Leave must be applied for in advance and approved by the Employee's manager."""),

    ("6. NOTICE PERIOD",
     """Either party may terminate this Agreement by providing 30 (thirty) days written
notice to the other party. The Company reserves the right to pay salary in lieu of
notice and ask the Employee to leave immediately."""),

    ("7. TERMINATION",
     """The Company may terminate this Agreement immediately and without notice for:
  - Gross misconduct or negligence
  - Persistent underperformance
  - Theft, fraud, or dishonesty
  - Serious or repeated breach of Company policies
  - Willful breach of confidentiality"""),

    ("8. CONFIDENTIALITY",
     """The Employee agrees to keep all Confidential Information strictly private, both
during and after employment. Confidential Information includes but is not limited to:
business plans, client lists, financial data, technical documentation, and trade secrets.
Unauthorized disclosure may result in legal action."""),

    ("9. NON-COMPETE CLAUSE",
     """During the term of employment and for a period of 6 (six) months following
termination, the Employee agrees not to directly or indirectly work for, consult with,
or hold ownership interest in any direct competitor of the Company operating in the
same geographic region."""),

    ("10. INTELLECTUAL PROPERTY",
     """All inventions, software, designs, and other work created by the Employee in the
course of employment shall be the sole and exclusive property of the Company.
The Employee agrees to assign all such rights to the Company upon request."""),

    ("11. GOVERNING LAW",
     """This Agreement shall be governed by and construed in accordance with the laws of
India. Any disputes arising under this Agreement shall be subject to the exclusive
jurisdiction of the courts in Bengaluru, Karnataka."""),

    ("SIGNATURES", """Company Representative: __________________   Date: ______________
                      TechCorp Pvt. Ltd.

Employee:             __________________   Date: ______________
                      John Smith"""),
]


class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "TechCorp Pvt. Ltd. - Confidential", align="R", new_x="LMARGIN", new_y="NEXT")

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


pdf = PDF()
pdf.set_margins(25, 20, 25)
pdf.add_page()

pdf.set_font("Helvetica", "B", 18)
pdf.set_text_color(30, 30, 100)
pdf.cell(0, 12, TITLE, align="C", new_x="LMARGIN", new_y="NEXT")

pdf.set_font("Helvetica", size=10)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 6, "Employment Agreement - TechCorp Pvt. Ltd.", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.ln(8)

for heading, body in SECTIONS:
    if heading:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 30, 100)
        pdf.multi_cell(0, 7, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 6, body.strip(), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

os.makedirs("data", exist_ok=True)
out_path = os.path.join("data", "sample_contract.pdf")
pdf.output(out_path)
print(f"✅ Sample PDF created: {out_path}")
print("   Upload this file to the app to test your RAG system.")
