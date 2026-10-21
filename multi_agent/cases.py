"""
The 10 Week-6 eval cases both arms are raced on. Pinned here, once, BEFORE any run.

The repo's Week 6 set (eval/questions.py) has 24 cases, not 10, so a subset had to be chosen.
It is chosen by a rule that never looks at any arm's results, and the cases themselves are
read straight from eval/questions.py - nothing here is a new question, a changed keyword or a
changed reference. If your original Week 6 run used a specific 10, replace PINNED_IDS with them
(order is the run order) and re-run; nothing else needs to change.

Selection rule (stratified by the Week 5 problem_type, so every failure family is present):
  baseline_pass                  x3  one case per specialist skill, picked by what the squad is for:
                                     parties                 -> defined parties ("Company" / "Employee")
                                     confidential_info_scope -> defined term "Confidential Information",
                                                                split across two 150-char chunks
                                     effective_date          -> the governing-date case the brief warns about
  split_clause_refusal           x2  first two in file order (reports_to, salary)
  never_retrieved_false_notfound x2  both (overtime, notice_period) - the cases only a retry can fix
  wrong_item_selected            x1  the only one (immediate_termination_fraud)
  never_retrieved_lucky_pass     x1  the only one (leave_approval)
  no_answer_control              x1  first in file order (maternity_leave)

The other 14 cases are left out; they are listed in EXCLUDED_IDS so the omission is visible, not
silent.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "eval"))

from questions import QUESTIONS  # noqa: E402  (the Week 6 set, unmodified)

PINNED_IDS = [
    "parties",
    "confidential_info_scope",
    "effective_date",
    "reports_to",
    "salary",
    "overtime",
    "notice_period",
    "immediate_termination_fraud",
    "leave_approval",
    "maternity_leave",
]

EXCLUDED_IDS = [q["id"] for q in QUESTIONS if q["id"] not in PINNED_IDS]

# Cases tried, in order, for the injected defined-terms 500. The first one whose CLEAN multi-agent
# run actually delegated to the defined-terms worker is used: injecting a failure into a worker the
# manager never called would test nothing.
INJECTION_CANDIDATES = ["confidential_info_scope", "parties", "reports_to"]


def load_cases(ids=None):
    by_id = {q["id"]: q for q in QUESTIONS}
    wanted = ids or PINNED_IDS
    missing = [i for i in wanted if i not in by_id]
    if missing:
        raise KeyError(f"not in eval/questions.py: {missing}")
    return [by_id[i] for i in wanted]
