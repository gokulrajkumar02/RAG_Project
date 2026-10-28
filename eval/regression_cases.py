"""
Production failures turned into permanent eval cases - the Week 11 failure->test loop.

One JSON file per case in eval/regression/, written by observability/make_case.py from the logged trace
of a real complaint. eval/run_suite.py runs them together with the 24 Week-6 questions (questions.py,
untouched), so a fix for a new failure is always checked against every old one too.

A case has the same keys as a Week-6 question (id, problem_type, question, expected_chunks,
answer_keywords), so the Week-6 rule check and judge score it unchanged, plus:
  citation       {"required": [...], "allowed": [...]}: clause numbers the answer must cite, and the only
                 ones it may cite. Checked by observability/citations.py.
  logged_answer  the bad answer exactly as it was logged. The suite replays it through the same checks
                 every run, so the test is seen failing on the failure that actually happened - not only on
                 whatever the model happens to say today.
  source         where it came from: trace id, time, prompt version, retrieved context ids.
"""

import glob
import json
import os

REGRESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression")


def load():
    cases = []
    for path in sorted(glob.glob(os.path.join(REGRESSION_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
        case["_file"] = os.path.relpath(path, os.path.dirname(REGRESSION_DIR))
        cases.append(case)
    return cases


REGRESSION_CASES = load()
