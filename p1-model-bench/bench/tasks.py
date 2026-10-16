"""Loading the task suite, and grading answers.

Every scorer is deterministic: the same output always gets the same mark, and
anyone can re-run the suite and reproduce the grade. That rules out an
LLM-as-judge, which would be more forgiving about phrasing but would also make
the numbers unreproducible and would add a model's opinion to a measurement
that is supposed to be about models.

The cost of determinism is that grading is strict. A model that answers
"Canberra." with a full stop still passes, because normalisation strips
punctuation; a model that answers "The capital is Canberra" does not, because
the instruction said to reply with the bare value. That is the behaviour being
measured, so the strictness is the point rather than a flaw.
"""

from __future__ import annotations

import json
import re
import string
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config"
TASKS_FILE = CONFIG / "tasks.json"


def load_tasks() -> dict:
    return json.loads(TASKS_FILE.read_text())


def iter_cases(tasks: dict):
    """Yield (family, case) for every case in the suite."""
    for family in tasks["families"]:
        for case in family["cases"]:
            yield family, case


# --- helpers ---------------------------------------------------------------

_PUNCT = str.maketrans("", "", string.punctuation)


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(text.lower().translate(_PUNCT).split())


def strip_fences(text: str) -> str:
    """Remove a ```json ... ``` wrapper if the model added one despite being told not to."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return fence.group(1).strip() if fence else text.strip()


def first_json_object(text: str) -> dict | None:
    """Find and parse the first balanced {...} in the text."""
    text = strip_fences(text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def last_number(text: str) -> float | None:
    """The last number in the text, which is where the suite asks for the answer."""
    matches = re.findall(r"-?\d[\d,]*\.?\d*", text.replace("$", ""))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


# --- scorers ---------------------------------------------------------------
# Each returns (passed: bool, reason: str). The reason is recorded so a failure
# can be read later without re-running anything.


def score_exact_choice(case: dict, output: str) -> tuple[bool, str]:
    got = normalise(output)
    want = normalise(case["expected"])
    if got == want:
        return True, "exact"
    if want in got.split():
        return False, f"right answer, extra words: {got!r}"
    return False, f"expected {want!r}, got {got!r}"


def score_json_fields(case: dict, output: str) -> tuple[bool, str]:
    parsed = first_json_object(output)
    if parsed is None:
        return False, "no parseable JSON object"

    wrong = []
    for field, expected in case["expected_fields"].items():
        if field not in parsed:
            wrong.append(f"{field} missing")
            continue
        actual = parsed[field]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                ok = abs(float(actual) - float(expected)) < 0.01
            except (TypeError, ValueError):
                ok = False
        else:
            ok = normalise(str(actual)) == normalise(str(expected))
        if not ok:
            wrong.append(f"{field}={actual!r} wanted {expected!r}")

    return (True, "all fields correct") if not wrong else (False, "; ".join(wrong))


def score_word_limit(case: dict, output: str) -> tuple[bool, str]:
    text = output.strip()
    words = len(text.split())
    limit = case["max_words"]
    if words > limit:
        return False, f"{words} words, limit {limit}"
    needles = case.get("must_include_any", [])
    if needles and not any(n.lower() in text.lower() for n in needles):
        return False, f"{words} words but none of {needles} present"
    return True, f"{words} words"


def score_numeric(case: dict, output: str) -> tuple[bool, str]:
    got = last_number(output)
    if got is None:
        return False, "no number in output"
    want = float(case["expected"])
    tolerance = float(case.get("tolerance", 0.0001))
    if abs(got - want) <= tolerance:
        return True, f"{got}"
    return False, f"expected {want}, got {got}"


SCORERS = {
    "exact_choice": score_exact_choice,
    "json_fields": score_json_fields,
    "word_limit": score_word_limit,
    "numeric": score_numeric,
}


def score(family: dict, case: dict, output: str) -> tuple[bool, str]:
    return SCORERS[family["scorer"]](case, output)
