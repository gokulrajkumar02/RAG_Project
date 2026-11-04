"""
Synthetic corpus for the Contract Review Assistant. The brief's corpus (60 executed MSAs + SOWs + amendments,
a definitions schedule, a fallback playbook, a governing-law table) is not in this repo, so it is generated
here, deterministically (seed below). EVERYTHING in it is invented: company names, people, e-mails, numbers.

What it is built to contain, because the brief says that is where this domain is hard:
  * 60 counterparties; the TechCorp base MSA with per-account negotiated values (cap 12/18/24 months, notice
    30/60/90 days, payment 30/45/60 days, term 1-3 years).
  * 12 accounts whose Amendment No.2 changes the clause 11.3 liability cap, in TWO different amendment forms
    (6 replace the whole clause; 6 replace the cap words with a "greater of ... and USD x" formula). The base
    MSA still says twelve months' Fees on all 12 - a correct citation to it is confidently wrong.
    3 of the 12 had an Amendment No.1 that already moved the cap (12 -> 18) before No.2 moved it again.
  * 10 more accounts with an Amendment No.1 that changes something else (notice period, payment terms, the
    definition of "Affiliate"), one of them with an effective date in the FUTURE (not yet in force).
  * SOW conflicts: one SOW whose special term conflicts with clause 11.3 without expressly overriding it
    (precedence clause 1.4 decides), one that expressly overrides clause 5.2 (it wins).
  * "Affiliate" defined narrowly (parents only) in Schedule 1 - not the ordinary meaning.
  * Scanned documents: about 40% of MSAs and a third of amendments exist only as degraded page images. They
    are really rendered to pixels and really OCR'd later (ocr.py); the OCR error rate is measured, not assumed.
  * Look-alike names (Halcyon Freight / Halcyon Foods, Orion Pharma / Orion Pay, ...) so "which counterparty?"
    can go wrong.

truth.json records what every document SAYS and what is in force for every account, computed from this plan
by an implementation independent of the one the app uses (chain.py works from the extracted text). The app
never reads truth.json; only the eval harness does.
"""

import datetime as dt
import hashlib
import io
import json
import os
import random
import re
import textwrap

from . import paths

SEED = 12
TODAY = dt.date.fromisoformat(os.environ.get("CONTRACT_DESK_TODAY") or dt.date.today().isoformat())
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]

LAW = {
    "UK": ("the laws of England and Wales", "the courts of London"),
    "IN": ("the laws of India", "the courts at Bengaluru, Karnataka"),
    "US": ("the laws of the State of Delaware", "the state and federal courts in Wilmington, Delaware"),
    "SG": ("the laws of Singapore", "the Singapore International Arbitration Centre"),
    "IE": ("the laws of Ireland", "the courts of Dublin"),
}
LAW_LABEL = {"UK": "England and Wales", "IN": "India", "US": "Delaware, USA", "SG": "Singapore", "IE": "Ireland"}

NAMES = {
    "UK": ["Halcyon Freight Ltd", "Halcyon Foods Ltd", "Meridian Logistics Ltd", "Alder Bay Telecom Ltd",
           "Blue Heron Energy Ltd", "Cedarwind Insurance Plc", "Dunmore Media Ltd", "Eastgate Retail Ltd",
           "Fairhaven Bank Plc", "Glenrock Mining Ltd", "Ironbridge Rail Ltd", "Juniper Row Health Ltd",
           "Kestrel Aero Ltd", "Larkspur Education Ltd", "Marlow Textiles Ltd"],
    "IN": ["Orion Pharma Pvt. Ltd.", "Orion Pay Pvt. Ltd.", "Northfold Agro Pvt. Ltd.", "Oakhurst Steel Pvt. Ltd.",
           "Pinecrest Hotels Pvt. Ltd.", "Quillfeather Books Pvt. Ltd.", "Rivergate Autos Pvt. Ltd.",
           "Saffron Lane Foods Pvt. Ltd.", "Tamarind Textiles Pvt. Ltd.", "Umber Hill Infra Pvt. Ltd.",
           "Vantage Point Logistics Pvt. Ltd.", "Willowbrook Pharma Pvt. Ltd.", "Yellowfin Marine Pvt. Ltd."],
    "US": ["Meridian Labs Inc.", "Summit Retail Inc.", "Aspen Ridge Software Inc.", "Brightwater Analytics Inc.",
           "Copperline Energy Inc.", "Driftwood Capital Inc.", "Evergreen Biotech Inc.", "Foxglove Media Inc.",
           "Granite Peak Mining Inc.", "Harborlight Shipping Inc.", "Indigo Fields Agri Inc.",
           "Jasper Creek Health Inc."],
    "SG": ["Summit Robotics Pte. Ltd.", "Kingfisher Freight Pte. Ltd.", "Lotus Bay Hotels Pte. Ltd.",
           "Mangrove Capital Pte. Ltd.", "Nimbus Cloudworks Pte. Ltd.", "Opal Strait Shipping Pte. Ltd.",
           "Peony Retail Pte. Ltd.", "Quartz Harbour Marine Pte. Ltd.", "Raintree Telecom Pte. Ltd.",
           "Sandalwood Foods Pte. Ltd."],
    "IE": ["Tarn Valley Dairy Ltd", "Underhill Pharma Ltd", "Valemont Energy GmbH", "Wexford Logistics Ltd",
           "Yarrow Biotech Ltd", "Zephyr Wind GmbH", "Ashgrove Insurance DAC", "Birchfield Retail Ltd",
           "Cloverdale Foods Ltd", "Dunleavy Software Ltd"],
}
SUFFIX = re.compile(r"\s+(Pvt\.\s+Ltd\.|Pte\.\s+Ltd\.|Ltd|Plc|Inc\.|GmbH|DAC)$")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", SUFFIX.sub("", name).lower()).strip("-")


FIRST = ["Aarav", "Bianca", "Callum", "Deepa", "Elias", "Fatima", "Gareth", "Hana", "Isidro", "Jun", "Katya",
         "Liam", "Mina", "Noor", "Oskar", "Priya", "Quentin", "Rhea", "Soren", "Tamsin", "Uma", "Viktor",
         "Wen", "Ximena", "Yusuf", "Zara"]
LAST = ["Abara", "Brennan", "Castellan", "Dhillon", "Eriksen", "Farrow", "Gallagher", "Hartnett", "Ibrahim",
        "Jorgensen", "Kapoor", "Lindqvist", "Moretti", "Nakamura", "Oyelaran", "Pemberton", "Quigley",
        "Radcliffe", "Santoro", "Thackeray", "Urquhart", "Vasquez", "Whitlock", "Yamamoto", "Zielinski"]
TITLES = ["General Counsel", "Head of Legal", "Chief Operating Officer", "Director of Procurement",
          "Chief Financial Officer"]
STREETS = ["Harbour Road", "Mill Lane", "Kingsway", "Station Approach", "Canal Street", "Orchard Row",
           "Foundry Yard", "Market Square"]
SUPPLIER_PERSON = dict(name="Meera Iyer", title="Vice President, Legal", email="meera.iyer@techcorp.example",
                       phone="+91 80 5550 0142", addr="14 Lakeview Park, Bengaluru 560001, India")

# ----------------------------------------------------------------------------------------------------------
# The plan: which accounts carry which amendments / SOW specials / scans. Fixed by hand, so that every case the
# eval uses can be traced to a line here. a1: kind of Amendment No.1; a2: form of Amendment No.2 (A = whole
# clause replaced, B = cap words replaced by a "greater of" formula); scan: tier per document ("mild" |
# "moderate" | "poor"); a missing key means a digital PDF.
# ----------------------------------------------------------------------------------------------------------
PLAN = {
    # --- the 12 accounts whose Amendment No.2 changed the clause 11.3 cap -------------------------------------
    "halcyon-freight":         dict(a1="notice",  a2="A", sow="cap_conflict", scan={}),
    "orion-pharma":            dict(a1="payment", a2="B", floor=2_500_000, scan={"a2": "moderate"}),
    "summit-retail":           dict(a1="cap",     a2="A", scan={}),
    "kestrel-aero":            dict(a1="notice",  a2="B", floor=3_000_000, scan={"msa": "mild", "a2": "poor"}),
    "brightwater-analytics":   dict(a1="affiliate", a2="A", scan={}),
    "nimbus-cloudworks":       dict(a1="payment", a2="B", floor=1_500_000, scan={"a2": "moderate"}),
    "vantage-point-logistics": dict(a1="cap",     a2="A", scan={"msa": "mild", "a1": "mild", "a2": "mild"}),
    "fairhaven-bank":          dict(a1="notice",  a2="B", floor=5_000_000, scan={}),
    "evergreen-biotech":       dict(a1="affiliate", a2="A", scan={}),
    "tarn-valley-dairy":       dict(a1="notice",  a2="B", floor=2_000_000, scan={"a2": "mild"}),
    "mangrove-capital":        dict(a1="cap",     a2="A", scan={}),
    "yarrow-biotech":          dict(a1="payment", a2="B", floor=4_000_000, scan={"msa": "moderate", "a2": "moderate"}),
    # --- Amendment No.1 only, touching something other than the cap -------------------------------------------
    "meridian-logistics":      dict(a1="notice", scan={}),
    "blue-heron-energy":       dict(a1="notice", scan={"a1": "mild"}),
    "saffron-lane-foods":      dict(a1="notice", scan={"msa": "moderate", "a1": "moderate"}),
    "granite-peak-mining":     dict(a1="notice", scan={}),
    "lotus-bay-hotels":        dict(a1="notice", scan={}),
    "jasper-creek-health":     dict(a1="affiliate", scan={}),
    "indigo-fields-agri":      dict(a1="affiliate", scan={"a1": "mild"}),
    "raintree-telecom":        dict(a1="affiliate", scan={}),
    "wexford-logistics":       dict(a1="future_notice", scan={}),
    "peony-retail":            dict(a1="payment", scan={}),
    # --- SOW conflicts on accounts with no amendment ----------------------------------------------------------
    "cedarwind-insurance":     dict(sow="cap_conflict", scan={}),
    "dunmore-media":           dict(sow="express_5_2", scan={}),
}
# Every other account: no amendment, MSA scanned with probability SCAN_P_MSA (seeded), tier drawn seeded.
SCAN_P_MSA = 0.50
SCAN_TIERS = [("mild", 0.5), ("moderate", 0.35), ("poor", 0.15)]

DEGRADE = {   # blur radius, noise sigma, skew degrees, down-up scale
    "mild":     dict(blur=0.5, noise=8.0, skew=0.3, down=0.85),
    "moderate": dict(blur=0.7, noise=14.0, skew=0.6, down=0.70),
    "poor":     dict(blur=1.1, noise=26.0, skew=1.2, down=0.55),
}
SCAN_PX = dict(width=1240, height=1754, font=28, margin=70, chars=78, line_gap=1.55)

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
         120: "one hundred and twenty"}


def words(n):
    if n < 20:
        return _ONES[n]
    if n in _TENS:
        return _TENS[n]
    if n < 100:
        return f"{_TENS[n // 10 * 10]}-{_ONES[n % 10]}"
    raise ValueError(n)


def nw(n):
    """'twelve (12)' - legal drafting writes a number twice; ocr/parse use that redundancy."""
    return f"{words(n)} ({n})"


def long_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def money(n):
    return f"USD {n:,}"


def _below_1000(n):
    h, t = divmod(n, 100)
    out = f"{_ONES[h]} hundred" if h else ""
    if t:
        out += (" and " if h else "") + words(t)
    return out


def usd_words(n):
    m, rest = divmod(n, 1_000_000)
    k, r = divmod(rest, 1000)
    parts = ([f"{words(m)} million"] if m else []) + ([f"{_below_1000(k)} thousand"] if k else []) + \
            ([_below_1000(r)] if r else [])
    return " ".join(parts)


def usd(n):
    """'two million five hundred thousand United States dollars (USD 2,500,000)': amounts are written twice too."""
    return f"{usd_words(n)} United States dollars ({money(n)})"


# ----------------------------------------------------------------------------------------------------------
# document text. A document is a list of paragraphs: (kind, text). kind: title | heading | clause | para.
# ----------------------------------------------------------------------------------------------------------
def cap_clause_text(months):
    return ("Subject to clauses 11.1 and 11.2, and except for Excluded Claims, each party's total aggregate "
            "liability arising out of or in connection with this Agreement shall not exceed the Fees paid or "
            f"payable by Customer in the {nw(months)} months preceding the event giving rise to the claim.")


CAP_WORDS_TEMPLATE = "the Fees paid or payable by Customer in the {m} months preceding the event giving rise to the claim"


def msa_paragraphs(a):
    """a: the account dict from build_accounts()."""
    law, venue = LAW[a["region"]]
    p = [("title", "MASTER SERVICES AGREEMENT"),
         ("para", f"This Master Services Agreement (the Agreement) is made on {long_date(a['msa_exec'])} and takes "
                  f"effect on {long_date(a['msa_eff'])} (the Effective Date) between {paths.SUPPLIER} (Supplier) "
                  f"and {a['name']} (Customer).")]
    C = [
        ("1", "INTERPRETATION AND STRUCTURE", None),
        ("1.1", "Defined Terms", "Capitalised terms used in this Agreement have the meanings given in Schedule 1 (Definitions)."),
        ("1.2", "Structure", "Supplier shall provide Services under statements of work (each an SOW) that incorporate this Agreement."),
        ("1.3", "Amendments", "No amendment to this Agreement is effective unless it is in writing, identifies the clause it amends and is signed by both parties."),
        ("1.4", "Order of Precedence", "If there is a conflict, the following order of precedence applies: (a) any Amendment, the most recent in effect prevailing; (b) the body of this Agreement; and (c) any SOW. An SOW prevails over the body of this Agreement only as to a clause that the SOW identifies by number and states that it expressly overrides."),
        ("2", "SERVICES", None),
        ("2.1", "Supply of Services", "Supplier shall provide the Services described in each SOW with reasonable skill and care."),
        ("2.2", "Acceptance", "Customer is deemed to accept each deliverable ten (10) Business Days after delivery unless it gives written notice of material non-conformity within that period."),
        ("3", "USE OF THE SERVICES", None),
        ("3.1", "Licence", "Supplier grants Customer a non-exclusive, non-transferable right to use the Services during the Term for its internal business purposes."),
        ("3.2", "Authorised Users", "Customer may permit its employees and the employees of its Affiliates to use the Services as Authorised Users, and is responsible for their compliance with this Agreement."),
        ("3.3", "Restrictions", "Customer shall not sub-license, resell or reverse engineer the Services."),
        ("4", "FEES", None),
        ("4.1", "Fees", "Customer shall pay the Fees set out in each SOW."),
        ("4.2", "Taxes", "The Fees exclude taxes, which Customer shall pay where applicable."),
        ("5", "PAYMENT", None),
        ("5.1", "Invoicing", "Supplier shall invoice the Fees monthly in arrears."),
        ("5.2", "Payment Terms", f"Customer shall pay each undisputed invoice within {nw(a['pay'])} days of receipt."),
        ("5.3", "Late Payment", "Overdue amounts accrue interest at one per cent (1%) per month until paid."),
        ("6", "DATA PROTECTION", None),
        ("6.1", "Processing", "Supplier shall process Personal Data only on Customer's documented instructions and in accordance with applicable data protection law."),
        ("6.2", "Security", "Supplier shall maintain appropriate technical and organisational measures to protect Personal Data against unauthorised access or loss."),
        ("7", "INTELLECTUAL PROPERTY", None),
        ("7.1", "Ownership", "Each party retains all rights in its pre-existing intellectual property. Supplier owns the Services and all improvements to them."),
        ("7.2", "Customer Data", "Customer owns all data it submits to the Services and grants Supplier a licence to use it solely to provide the Services."),
        ("8", "WARRANTIES", None),
        ("8.1", "Mutual Warranties", "Each party warrants that it has authority to enter into this Agreement."),
        ("8.2", "Disclaimer", "Except as expressly stated, Supplier excludes all implied warranties to the extent permitted by law."),
        ("9", "CONFIDENTIALITY", None),
        ("9.1", "Obligation", "Each party shall keep the other's Confidential Information confidential and use it only to perform this Agreement."),
        ("9.2", "Permitted Disclosure", "A party may disclose Confidential Information to its Affiliates, advisers and subcontractors who need to know it and are bound by equivalent duties, or where required by law."),
        ("9.3", "Duration", "The obligations in this clause 9 continue for five (5) years after the end of the Term."),
        ("10", "SERVICE LEVELS", None),
        ("10.1", "Availability", "Supplier shall make the Services available at least ninety-nine point five per cent (99.5%) of each calendar month."),
        ("10.2", "Service Credits", "Service credits are Customer's sole remedy for a failure to meet clause 10.1."),
        ("11", "LIMITATION OF LIABILITY", None),
        ("11.1", "Unlimited Liability", "Nothing in this Agreement limits liability that cannot be limited by law."),
        ("11.2", "Excluded Losses", "Subject to clause 11.1, neither party is liable for loss of profit, loss of revenue or any indirect or consequential loss."),
        ("11.3", "Liability Cap", cap_clause_text(a["base_cap_months"])),
        ("11.4", "Basis of Cap", "The cap in clause 11.3 applies to all claims in aggregate and not to each claim separately."),
        ("12", "INDEMNITIES", None),
        ("12.1", "IP Indemnity", "Supplier shall indemnify Customer against Losses arising from a third-party claim that the Services infringe that third party's intellectual property rights."),
        ("12.2", "Data Breach Indemnity", "Supplier shall indemnify Customer against Losses arising from a breach of clause 6 by Supplier that results in unauthorised disclosure of Personal Data."),
        ("12.3", "Customer Indemnity", "Customer shall indemnify Supplier against Losses arising from Customer's use of the Services in breach of clause 3.3."),
        ("12.4", "Procedure", "The indemnified party shall give prompt notice of a claim, allow the indemnifying party to control its defence and give reasonable assistance."),
        ("13", "TERM AND RENEWAL", None),
        ("13.1", "Term", f"This Agreement starts on the Effective Date and continues for {nw(a['term_years'])} years (the initial term)."),
        ("13.2", "Renewal", "After the initial term this Agreement renews for successive periods of twelve (12) months unless either party gives written notice of non-renewal at least ninety (90) days before the end of the then-current period."),
        ("14", "TERMINATION", None),
        ("14.1", "Termination for Cause", "Either party may terminate this Agreement immediately by written notice if the other commits a material breach that is not remedied within thirty (30) days of notice."),
        ("14.2", "Termination for Convenience", f"Either party may terminate this Agreement for convenience at any time after the first anniversary of the Effective Date by giving not less than {nw(a['notice'])} days' written notice."),
        ("14.3", "Insolvency", "Either party may terminate this Agreement immediately by written notice if the other becomes insolvent or enters administration or liquidation."),
        ("14.4", "Consequences", "On termination Customer shall pay all Fees accrued to the termination date and each party shall return or delete the other's Confidential Information."),
        ("15", "NOTICES", None),
        ("15.1", "Notices to Customer", f"Notices to Customer shall be sent to {a['c_addr']}, marked for the attention of {a['c_name']}, {a['c_title']} ({a['c_email']}, {a['c_phone']})."),
        ("15.2", "Notices to Supplier", f"Notices to Supplier shall be sent to {SUPPLIER_PERSON['addr']}, marked for the attention of {SUPPLIER_PERSON['name']}, {SUPPLIER_PERSON['title']} ({SUPPLIER_PERSON['email']}, {SUPPLIER_PERSON['phone']})."),
        ("16", "ASSIGNMENT", None),
        ("16.1", "Assignment", "Neither party may assign this Agreement without the other's prior written consent, not to be unreasonably withheld."),
        ("17", "FORCE MAJEURE", None),
        ("17.1", "Force Majeure", "Neither party is liable for delay caused by events beyond its reasonable control, provided it notifies the other promptly."),
        ("18", "GOVERNING LAW AND DISPUTES", None),
        ("18.1", "Governing Law", f"This Agreement and any dispute arising out of it are governed by {law}."),
        ("18.2", "Jurisdiction", f"The parties submit to the exclusive jurisdiction of {venue}."),
        ("19", "GENERAL", None),
        ("19.1", "Entire Agreement", "This Agreement, its Schedules and each SOW are the entire agreement between the parties on their subject matter."),
        ("19.2", "Severability", "If any provision is held invalid, the remainder continues in effect."),
    ]
    for no, title, body in C:
        p.append(("heading", f"{no}. {title}") if body is None else ("clause", f"{no} {title}. {body}"))
    p.append(("para", f"Signed for and on behalf of Supplier by {SUPPLIER_PERSON['name']}, {SUPPLIER_PERSON['title']}."))
    p.append(("para", f"Signed for and on behalf of Customer by {a['c_name']}, {a['c_title']}."))
    return p


def sow_paragraphs(a, n, sow):
    p = [("title", f"STATEMENT OF WORK NO. {n}"),
         ("para", f"This Statement of Work No. {n} (the SOW) is made on {long_date(sow['exec'])} and takes effect on "
                  f"{long_date(sow['eff'])} under the Master Services Agreement dated {long_date(a['msa_eff'])} (the MSA) "
                  f"between {paths.SUPPLIER} and {a['name']}.")]
    cl = [("1", "Services", f"Supplier shall provide {sow['service']} to Customer (the Services under this SOW)."),
          ("2", "Deliverables", "Supplier shall deliver the configured environment, user documentation and two training sessions."),
          ("3", "Fees", f"Customer shall pay a fixed annual fee of {money(sow['fee'])} for the Services under this SOW."),
          ("4", "Term", f"This SOW runs for {nw(sow['months'])} months from its effective date unless terminated under the MSA."),
          ("5", "Customer Responsibilities", "Customer shall provide timely access to the systems and personnel Supplier reasonably needs.")]
    if sow.get("special") == "cap_conflict":
        cl.append(("6", "Special Terms", f"Supplier's total liability under this SOW shall not exceed {usd(250_000)}."))
    elif sow.get("special") == "express_5_2":
        cl.append(("6", "Special Terms", f"This SOW expressly overrides clause 5.2 of the MSA. Customer shall pay each undisputed invoice under this SOW within {nw(15)} days of receipt."))
    for no, title, body in cl:
        p.append(("clause", f"{no}. {title}. {body}"))
    p.append(("para", f"Signed for Supplier by {SUPPLIER_PERSON['name']}. Signed for Customer by {a['c_name']}."))
    return p


def amendment_paragraphs(a, n, am):
    p = [("title", f"AMENDMENT NO. {n} TO MASTER SERVICES AGREEMENT"),
         ("para", f"This Amendment No. {n} (the Amendment) is made on {long_date(am['exec'])} and takes effect on "
                  f"{long_date(am['eff'])} between {paths.SUPPLIER} and {a['name']}. It amends the Master Services "
                  f"Agreement dated {long_date(a['msa_eff'])} (the MSA).")]
    for i, e in enumerate(am["edits"], 1):
        p.append(("clause", f"{i}. {e['title']}. {e['text']}"))
    p.append(("clause", f"{len(am['edits']) + 1}. Continuing Effect. Except as amended by this Amendment, the MSA continues in full force and effect."))
    p.append(("para", f"Signed for Supplier by {SUPPLIER_PERSON['name']}. Signed for Customer by {a['c_name']}, {a['c_title']}."))
    return p


AFFILIATE_MASTER = ("Affiliate means, in relation to a party, any entity that directly or indirectly Controls that "
                    "party. An Affiliate does not include any subsidiary or sister company of that party.")
AFFILIATE_BROAD = ("Affiliate means, in relation to a party, any entity that directly or indirectly Controls, is "
                   "Controlled by, or is under common Control with that party.")
DEFINITIONS = [
    ("Affiliate", AFFILIATE_MASTER),
    ("Authorised Users", "Authorised Users means the employees of Customer and of its Affiliates whom Customer permits to use the Services under clause 3.2."),
    ("Business Day", "Business Day means a day other than a Saturday, Sunday or public holiday in the place whose law governs this Agreement."),
    ("Confidential Information", "Confidential Information means non-public information disclosed by a party that is marked confidential or would reasonably be understood to be confidential. It does not include information that is public through no fault of the recipient."),
    ("Control", "Control means ownership of more than fifty per cent (50%) of the voting shares of an entity, and Controls and Controlled have corresponding meanings."),
    ("Excluded Claims", "Excluded Claims means (a) a party's indemnification obligations under clauses 12.1 to 12.3; (b) breach of clause 9 (Confidentiality); (c) fraud, gross negligence or wilful misconduct; and (d) any liability that cannot be limited by law."),
    ("Fees", "Fees means the fees payable under an SOW, excluding taxes and expenses."),
    ("Losses", "Losses means damages, costs, fines and reasonable legal fees, but excludes loss of profit and indirect or consequential loss."),
    ("Personal Data", "Personal Data has the meaning given in the data protection law of the jurisdiction whose law governs this Agreement."),
    ("Services", "Services means the services described in an SOW."),
    ("Term", "Term means the period described in clause 13."),
]
PLAYBOOK = [
    ("Limitation of liability", "11.3", "Preferred: total liability capped at twelve (12) months' Fees. Fallback 1: eighteen (18) months' Fees, approved by the Head of Legal. Fallback 2: twenty-four (24) months' Fees, or a fixed floor of up to USD 2,000,000, approved by the General Counsel. Walk-away: any uncapped liability outside Excluded Claims."),
    ("Indemnities", "12.1-12.3", "Preferred: indemnities limited to IP infringement, data breach caused by Supplier, and misuse by Customer. Fallback 1: add regulatory fines for a Supplier data breach. Fallback 2: none. Walk-away: indemnity for Customer's indirect losses."),
    ("Termination for convenience", "14.2", "Preferred: sixty (60) days' notice after the first anniversary. Fallback 1: ninety (90) days. Fallback 2: thirty (30) days, approved by the Head of Legal. Walk-away: termination for convenience in the first year."),
    ("Payment terms", "5.2", "Preferred: thirty (30) days. Fallback 1: forty-five (45) days. Fallback 2: sixty (60) days, approved by the Finance Director. Walk-away: payment later than ninety (90) days."),
    ("Affiliates", "Schedule 1", "Preferred: Affiliate means parent entities only. Fallback 1: add subsidiaries where Customer names them in an SOW. Fallback 2: full corporate group, approved by the General Counsel."),
    ("Governing law", "18.1", "Preferred: the law of Supplier's home jurisdiction. Fallback 1: the law of Customer's home jurisdiction if it is England and Wales, Delaware or Singapore. Fallback 2: none without General Counsel approval."),
    ("Confidentiality", "9", "Preferred: five (5) years after the end of the Term. Fallback 1: seven (7) years. Fallback 2: perpetual for trade secrets only."),
    ("Order of precedence", "1.4", "Preferred: amendments, then the MSA body, then SOWs. An SOW may override the MSA body only by clause number and express words. Fallback: none."),
]


def definitions_paragraphs():
    p = [("title", "SCHEDULE 1 - DEFINITIONS"),
         ("para", f"This Schedule forms part of every Master Services Agreement between {paths.SUPPLIER} and its customers. It takes effect on 1 January 2020.")]
    for i, (term, text) in enumerate(DEFINITIONS, 1):
        p.append(("clause", f"{i}. {term}. {text}"))
    return p


def playbook_paragraphs():
    p = [("title", "FALLBACK CLAUSE PLAYBOOK - PRIVILEGED AND CONFIDENTIAL"),
         ("para", f"Internal to the {paths.SUPPLIER} legal team. It records the positions legal negotiates from; it is not shared with customers. Last reviewed 1 February 2026.")]
    for i, (topic, ref, text) in enumerate(PLAYBOOK, 1):
        p.append(("clause", f"{i}. {topic} (clause {ref}). {text}"))
    return p


def law_table_paragraphs(accounts):
    p = [("title", "GOVERNING LAW AND VENUE TABLE"),
         ("para", "One row per customer: slug | customer | governing law | venue | last reviewed. Maintained by Legal Operations.")]
    for a in accounts:
        law, venue = LAW[a["region"]]
        p.append(("para", f"{a['slug']} | {a['name']} | {law[4:]} | {venue[4:]} | reviewed {long_date(a['law_reviewed'])}"))
    return p


# ----------------------------------------------------------------------------------------------------------
# building the accounts + truth
# ----------------------------------------------------------------------------------------------------------
def build_accounts(rng):
    names = [(n, r) for r, ns in NAMES.items() for n in ns]
    accounts = []
    for name, region in names:
        slug = slugify(name)
        plan = PLAN.get(slug, {})
        amended = bool(plan.get("a1"))
        eff_lo = dt.date(2021, 3, 1) if plan.get("a2") else dt.date(2019, 4, 1)
        eff_hi = dt.date(2023, 6, 30) if plan.get("a2") else dt.date(2024, 9, 30)
        msa_eff = eff_lo + dt.timedelta(days=rng.randrange((eff_hi - eff_lo).days))
        a = dict(name=name, region=region, slug=slug, plan=plan, msa_eff=msa_eff,
                 msa_exec=msa_eff - dt.timedelta(days=rng.randrange(7, 35)),
                 term_years=rng.choice([1, 2, 3]),
                 base_cap_months=12 if (plan.get("a2") or plan.get("a1") == "cap" or plan.get("sow") == "cap_conflict")
                 else rng.choice([12, 12, 12, 18, 24]),
                 notice=60 if plan.get("a1") in ("notice", "future_notice") else rng.choice([30, 60, 60, 90]),
                 pay=30 if plan.get("a1") == "payment" else (45 if plan.get("sow") == "express_5_2" else rng.choice([30, 45, 60])),
                 law_reviewed=dt.date(2025, 1, 6) + dt.timedelta(days=rng.randrange(300)))
        if plan.get("a1") in ("notice", "future_notice") or plan.get("a2"):
            a["term_years"] = max(a["term_years"], 2)      # termination for convenience needs a term to leave
        person = (rng.choice(FIRST), rng.choice(LAST))
        a.update(c_name=f"{person[0]} {person[1]}", c_title=rng.choice(TITLES),
                 c_email=f"{person[0].lower()}.{person[1].lower()}@{slug}.example",
                 c_phone=f"+{rng.choice([44, 91, 1, 65, 353])} {rng.randrange(20, 99)} 5550 {rng.randrange(1000, 9999)}",
                 c_addr=f"{rng.randrange(2, 98)} {rng.choice(STREETS)}, {name.split()[0]} Park")
        accounts.append(a)
    accounts.sort(key=lambda a: a["slug"])
    return accounts


def plan_documents(accounts, rng):
    """Decide every document of every account (dates, edits, scan tiers) and the in-force truth."""
    docs, truth_accounts = [], {}
    for a in accounts:
        plan, slug = a["plan"], a["slug"]
        scan = dict(plan.get("scan", {}))
        if "msa" not in scan and not plan.get("a1") and rng.random() < SCAN_P_MSA and not plan.get("sow"):
            scan["msa"] = rng.choices([t for t, _ in SCAN_TIERS], [w for _, w in SCAN_TIERS])[0]
        a["scan"] = scan
        docs.append(dict(doc_id=f"{slug}/msa", slug=slug, type="MSA", number=None, effective=a["msa_eff"],
                         executed=a["msa_exec"], tier=scan.get("msa"), title="Master Services Agreement"))
        n_sow = 2 if rng.random() < 0.4 else 1
        sows = []
        for i in range(1, n_sow + 1):
            eff = a["msa_eff"] + dt.timedelta(days=rng.randrange(14, 45) if i == 1 else rng.randrange(365, 800))
            sow = dict(eff=eff, exec=eff - dt.timedelta(days=rng.randrange(3, 14)),
                       service=rng.choice(["the hosted analytics platform", "the workflow automation suite",
                                           "the managed integration service", "the reporting and dashboards module"]),
                       fee=rng.choice([60_000, 90_000, 120_000, 180_000, 240_000]), months=rng.choice([12, 24, 36]))
            if i == 1 and plan.get("sow"):
                sow["special"] = plan["sow"]
            sows.append(sow)
            docs.append(dict(doc_id=f"{slug}/sow-{i}", slug=slug, type="SOW", number=i, effective=eff,
                             executed=sow["exec"], tier=None, title=f"Statement of Work No. {i}", sow=sow))
        # amendments --------------------------------------------------------------------------------------
        amendments = []
        if plan.get("a1"):
            lo = a["msa_eff"] + dt.timedelta(days=240)
            eff1 = lo + dt.timedelta(days=rng.randrange(60, 400))
            if plan["a1"] == "future_notice":
                eff1 = dt.date(TODAY.year + 1, 1, 1)
            if plan.get("a2"):
                eff1 = min(eff1, dt.date(2024, 12, 15))
            edits1 = a1_edits(plan["a1"], a)
            amendments.append(dict(n=1, eff=eff1, exec=eff1 - dt.timedelta(days=rng.randrange(10, 40)) if plan["a1"] != "future_notice"
                                   else dt.date(TODAY.year, 9, 12), edits=edits1, tier=scan.get("a1")))
        if plan.get("a2"):
            eff2 = dt.date(2025, 1, 20) + dt.timedelta(days=rng.randrange(300))
            amendments.append(dict(n=2, eff=eff2, exec=eff2 - dt.timedelta(days=rng.randrange(10, 40)),
                                   edits=a2_edits(plan, a), tier=scan.get("a2")))
        for am in amendments:
            docs.append(dict(doc_id=f"{slug}/amendment-{am['n']}", slug=slug, type="AMENDMENT", number=am["n"],
                             effective=am["eff"], executed=am["exec"], tier=am["tier"],
                             title=f"Amendment No. {am['n']}", amendment=am))
        a["sows"], a["amendments"] = sows, amendments
        truth_accounts[slug] = account_truth(a, sows, amendments)
    return docs, truth_accounts


def a1_edits(kind, a):
    if kind == "cap":
        return [dict(target="cl:11.3", title="Amendment to Clause 11.3", action="replace_words",
                     old="twelve (12) months", new="eighteen (18) months",
                     text='In Clause 11.3 of the MSA, the words "twelve (12) months" are deleted and replaced with "eighteen (18) months".')]
    if kind in ("notice", "future_notice"):
        new = 90 if kind == "future_notice" else rng_pick(a["slug"], [90, 120])
        return [dict(target="cl:14.2", title="Amendment to Clause 14.2", action="replace_words",
                     old=nw(60) + " days", new=nw(new) + " days",
                     text=f'In Clause 14.2 of the MSA, the words "{nw(60)} days" are deleted and replaced with "{nw(new)} days".')]
    if kind == "payment":
        return [dict(target="cl:5.2", title="Amendment to Clause 5.2", action="replace_words",
                     old=nw(30) + " days", new=nw(45) + " days",
                     text=f'In Clause 5.2 of the MSA, the words "{nw(30)} days" are deleted and replaced with "{nw(45)} days".')]
    if kind == "affiliate":
        return [dict(target="def:Affiliate", title="Amendment to the definition of Affiliate", action="redefine",
                     new=AFFILIATE_BROAD,
                     text=f'The definition of Affiliate in Schedule 1 is deleted and replaced with: "{AFFILIATE_BROAD}"')]
    raise ValueError(kind)


def rng_pick(key, options):
    return options[int(hashlib.sha1(key.encode()).hexdigest(), 16) % len(options)]


def a2_edits(plan, a):
    if plan["a2"] == "A":
        full = f"11.3 Liability Cap. {cap_clause_text(24)}"
        return [dict(target="cl:11.3", title="Amendment to Clause 11.3", action="replace_clause", new=full,
                     text=f'Clause 11.3 of the MSA is deleted and replaced with: "{full}"')]
    old = CAP_WORDS_TEMPLATE.format(m=nw(12))
    new = (f"the greater of (i) the Fees paid or payable by Customer in the {nw(24)} months preceding the event "
           f"giving rise to the claim and (ii) {usd(plan['floor'])}")
    return [dict(target="cl:11.3", title="Amendment to Clause 11.3", action="replace_words", old=old, new=new,
                 text=f'In Clause 11.3 of the MSA, the words "{old}" are deleted and replaced with "{new}".')]


def account_truth(a, sows, amendments):
    """What is in force for this account TODAY, from the plan (independent of the app's parser)."""
    cap = dict(months=a["base_cap_months"], usd_floor=None, doc="msa", clause="11.3")
    cap_chain = [("msa", "11.3", a["msa_eff"].isoformat(), f"base: {a['base_cap_months']} months' Fees")]
    notice = dict(days=a["notice"], doc="msa", clause="14.2")
    notice_chain = [("msa", "14.2", a["msa_eff"].isoformat(), f"base: {a['notice']} days")]
    pay = dict(days=a["pay"], doc="msa", clause="5.2")
    pay_chain = [("msa", "5.2", a["msa_eff"].isoformat(), f"base: {a['pay']} days")]
    affiliate = dict(scope="parents_only", doc="shared/definitions-schedule", clause="1")
    aff_chain = [("shared/definitions-schedule", "1", "2020-01-01", "parents only")]
    for am in sorted(amendments, key=lambda x: x["eff"]):
        doc = f"amendment-{am['n']}"
        for i, e in enumerate(am["edits"], 1):
            row = (doc, str(i), am["eff"].isoformat(), e["text"][:90])
            future = am["eff"] > TODAY
            if e["target"] == "cl:11.3":
                cap_chain.append(row + (future,))
                if not future:
                    if e["action"] == "replace_words" and "greater of" in e["new"]:
                        cap = dict(months=24, usd_floor=a["plan"]["floor"], doc=doc, clause=str(i))
                    elif e["action"] == "replace_clause":
                        cap = dict(months=24, usd_floor=None, doc=doc, clause=str(i))
                    else:
                        cap = dict(months=18, usd_floor=None, doc=doc, clause=str(i))
            elif e["target"] == "cl:14.2":
                notice_chain.append(row + (future,))
                if not future:
                    notice = dict(days=int(re.search(r"\((\d+)\) days", e["new"]).group(1)), doc=doc, clause=str(i))
            elif e["target"] == "cl:5.2":
                pay_chain.append(row + (future,))
                if not future:
                    pay = dict(days=45, doc=doc, clause=str(i))
            elif e["target"] == "def:Affiliate":
                aff_chain.append(row + (future,))
                if not future:
                    affiliate = dict(scope="group", doc=doc, clause=str(i))
    sow_override = None
    for i, s in enumerate(sows, 1):
        if s.get("special") == "express_5_2":
            pay = dict(days=15, doc=f"sow-{i}", clause="6")
            sow_override = dict(doc=f"sow-{i}", clause="6", target="5.2")
    law, venue = LAW[a["region"]]
    return dict(name=a["name"], slug=a["slug"], region=a["region"], governing_law=LAW_LABEL[a["region"]],
                venue=venue[4:], msa_eff=a["msa_eff"].isoformat(),
                in_force=dict(cap=cap, notice=notice, payment=pay, affiliate=affiliate,
                              term_years=a["term_years"], governing_law=law[4:]),
                chains={"11.3": cap_chain, "14.2": notice_chain, "5.2": pay_chain, "def:Affiliate": aff_chain},
                amended_cap=bool(a["plan"].get("a2")), has_amendment=bool(amendments),
                sow_special=a["plan"].get("sow"), sow_override=sow_override,
                pii=[a["c_name"], a["c_email"], a["c_phone"], a["c_addr"]],
                scan=a["scan"], docs=[d for d in ([f"{a['slug']}/msa"] + [f"{a['slug']}/sow-{i}" for i in range(1, len(sows) + 1)]
                                                  + [f"{a['slug']}/amendment-{am['n']}" for am in amendments])],
                future_amendment=any(am["eff"] > TODAY for am in amendments))


# ----------------------------------------------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------------------------------------------
def render_digital(paragraphs, out_path, title):
    from fpdf import FPDF

    class Doc(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Times", size=8)
            self.cell(0, 6, f"Page {self.page_no()}", align="C")

    pdf = Doc(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_title(title)
    pdf.add_page()
    for kind, text in paragraphs:
        text = text.encode("latin-1", "replace").decode("latin-1")
        if kind == "title":
            pdf.set_font("Times", style="B", size=14)
            pdf.multi_cell(0, 7, text, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "heading":
            pdf.set_font("Times", style="B", size=10.5)
            pdf.ln(1.5)
            pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Times", size=10)
            pdf.multi_cell(0, 4.8, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.2)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)


def scan_pages(paragraphs):
    """Lay the paragraphs out as pages of wrapped lines: [[line, ...], ...] (what the page image will say)."""
    per_page = int((SCAN_PX["height"] - 2 * SCAN_PX["margin"]) / (SCAN_PX["font"] * SCAN_PX["line_gap"]))
    pages, cur = [], []
    for kind, text in paragraphs:
        lines = textwrap.wrap(text, SCAN_PX["chars"] - (12 if kind == "title" else 0)) or [""]
        if kind == "heading" and cur:
            lines = [""] + lines   # a little air before a heading, as a real page has
        for ln in lines:
            if len(cur) >= per_page:
                pages.append(cur)
                cur = []
            cur.append(ln)
    if cur:
        pages.append(cur)
    return pages


def render_scanned(pages_lines, out_path, tier, seed):
    """Draw each page to pixels, degrade it (blur, noise, skew, resolution loss) and store ONLY the images in a
    PDF - no text layer, so the only way to read it is OCR."""
    import numpy as np
    from fpdf import FPDF
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    cfg = DEGRADE[tier]
    font = ImageFont.load_default(size=SCAN_PX["font"])
    rng = np.random.default_rng(seed)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    for pno, lines in enumerate(pages_lines, 1):
        img = Image.new("L", (SCAN_PX["width"], SCAN_PX["height"]), 255)
        d = ImageDraw.Draw(img)
        y = SCAN_PX["margin"]
        for ln in lines:
            d.text((SCAN_PX["margin"], y), ln, font=font, fill=15)
            y += int(SCAN_PX["font"] * SCAN_PX["line_gap"])
        d.text((SCAN_PX["width"] // 2 - 40, SCAN_PX["height"] - 55), f"Page {pno}", font=font, fill=60)
        img = img.rotate(cfg["skew"] * (1 if rng.random() < .5 else -1), expand=False, fillcolor=255, resample=Image.BICUBIC)
        w, h = img.size
        img = img.resize((int(w * cfg["down"]), int(h * cfg["down"])), Image.BILINEAR).resize((w, h), Image.BILINEAR)
        img = img.filter(ImageFilter.GaussianBlur(cfg["blur"]))
        arr = np.asarray(img).astype(np.float32) + rng.normal(0, cfg["noise"], (h, w))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=68)
        buf.seek(0)
        pdf.add_page()
        pdf.image(buf, x=0, y=0, w=210, h=297)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)


def doc_paragraphs(d, acct):
    if d["type"] == "MSA":
        return msa_paragraphs(acct)
    if d["type"] == "SOW":
        return sow_paragraphs(acct, d["number"], d["sow"])
    return amendment_paragraphs(acct, d["number"], d["amendment"])


def plain_text(paragraphs):
    return "\n".join(t for _k, t in paragraphs)


CRITICAL = re.compile(r"[A-Za-z$]*\d[\w.,%/-]*")


def critical_tokens(text):
    """Tokens that carry a fact (numbers, dates, clause refs, amounts). OCR errors in these are the dangerous ones."""
    return [m.group(0).strip(".,;:()\"'") for m in CRITICAL.finditer(text) if any(c.isdigit() for c in m.group(0))]


def generate(force=False):
    """Write PDFs, manifest.json and truth.json. Returns (manifest, truth). Idempotent for a given seed."""
    if not force and os.path.exists(paths.TRUTH) and os.path.exists(paths.MANIFEST):
        with open(paths.MANIFEST, encoding="utf-8") as f, open(paths.TRUTH, encoding="utf-8") as g:
            return json.load(f), json.load(g)
    rng = random.Random(SEED)
    accounts = build_accounts(rng)
    docs, truth_accounts = plan_documents(accounts, rng)
    by_slug = {a["slug"]: a for a in accounts}
    manifest = {"supplier": paths.SUPPLIER, "generated_for_date": TODAY.isoformat(), "seed": SEED,
                "counterparties": {}, "documents": {}}
    truth = {"seed": SEED, "today": TODAY.isoformat(), "accounts": truth_accounts, "docs": {},
             "playbook": [dict(topic=t, ref=r, text=x) for t, r, x in PLAYBOOK],
             "definitions": {t: x for t, x in DEFINITIONS}}
    for a in accounts:
        manifest["counterparties"][a["slug"]] = dict(name=a["name"], slug=a["slug"],
                                                     short=a["name"].split()[0])
    for d in docs:
        acct = by_slug[d["slug"]]
        paras = doc_paragraphs(d, acct)
        _emit(manifest, truth, d["doc_id"], d["slug"], d["type"], d["number"], d["title"], d["effective"],
              d["executed"], paras, d["tier"])
    shared = [("shared/definitions-schedule", "SCHEDULE", "Schedule 1 - Definitions", dt.date(2020, 1, 1), definitions_paragraphs()),
              ("shared/fallback-playbook", "PLAYBOOK", "Fallback Clause Playbook", dt.date(2026, 2, 1), playbook_paragraphs()),
              ("shared/governing-law-table", "LAW_TABLE", "Governing Law and Venue Table", dt.date(2026, 2, 1), law_table_paragraphs(accounts))]
    for doc_id, typ, title, eff, paras in shared:
        _emit(manifest, truth, doc_id, None, typ, None, title, eff, eff, paras, None)
    for rel, obj in ((paths.MANIFEST, manifest), (paths.TRUTH, truth)):
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        with open(rel, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
    return manifest, truth


def _emit(manifest, truth, doc_id, slug, typ, number, title, eff, executed, paras, tier):
    out = paths.pdf_path(doc_id)
    text = plain_text(paras)
    # The manifest is what a legal-ops upload form would record: no scan flag, no scan quality. The app has to
    # DETECT a scanned document (no text layer) and measure how well it read it; truth.json keeps the answer.
    rec = dict(doc_id=doc_id, counterparty=slug, type=typ, number=number, title=title,
               effective_date=eff.isoformat(), executed_date=executed.isoformat(),
               pdf=os.path.relpath(out, paths.CORPUS).replace("\\", "/"))
    trec = dict(scanned=bool(tier), tier=tier, critical=critical_tokens(text), chars=len(text), text=text,
                paragraphs=[[k, t] for k, t in paras])
    if tier:
        pages = scan_pages(paras)
        render_scanned(pages, out, tier, seed=int(hashlib.sha1(doc_id.encode()).hexdigest()[:8], 16))
        trec["pages_lines"] = pages
    else:
        render_digital(paras, out, title)
    manifest["documents"][doc_id] = rec
    truth["docs"][doc_id] = trec
