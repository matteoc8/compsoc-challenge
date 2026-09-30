"""Builds seed/sample_quiz.json: the three sample challenges.

Expected outputs are produced by running each reference solution, so they're correct
by construction. Run from backend/:  python scripts/build_sample_quiz.py
Every solution here must also run on Python 3.8 (Judge0 CE's Python), so no
`list[int]` annotations, match statements or 3.9+ string methods.
"""

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seed" / "sample_quiz.json"
rng = random.Random(2026)


def run(code: str, stdin: str) -> str:
    p = subprocess.run([sys.executable, "-I", "-c", code], input=stdin.encode(), capture_output=True, timeout=20)
    if p.returncode != 0:
        raise SystemExit(f"reference failed on {stdin[:60]!r}:\n{p.stderr.decode()}")
    return p.stdout.decode().replace("\r\n", "\n")


def cases(code: str, inputs: list[str]) -> list[dict]:
    return [{"stdin": i, "expected": run(code, i)} for i in inputs]


# ---------------------------------------------------------------- 1. Super Fast

VOWELS_REF = "print(sum(c in 'aeiouAEIOU' for c in input()))\n"
letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ     .,!?"
long_line = "".join(rng.choice(letters) for _ in range(1000)).strip() or "a"
vowels_tests = [
    "rhythm\n",
    "AEIOUaeiou\n",
    "a\n",
    "Queueing\n",
    "The quick brown fox jumps over the lazy dog\n",
    "Why try? Fly by!\n",
    "12345 !?\n",
    "UPPER lower MiXeD\n",
    "".join(rng.choice(letters) for _ in range(60)).strip() + "\n",
    long_line + "\n",
]
super_fast = {
    "round_name": "Round 1: Super Fast",
    "type": "super_fast",
    "title": "Vowel Counter",
    "description_md": (
        "Read **one line** of text and print how many vowels it contains.\n\n"
        "Vowels are `a e i o u`, in upper or lower case. `y` is **not** a vowel.\n\n"
        "**First three win:** only the first three teams to pass *every* hidden test score "
        "(4,000 · 3,000 · 2,000 points). The round ends as soon as the third team gets it."
    ),
    "starter_code": "line = input()\n\n# Print the number of vowels in line\n",
    "reference_solution": VOWELS_REF,
    "config": {
        "examples": cases(VOWELS_REF, ["Hello World\n", "CompSoc Challenge\n"]),
        "tests": cases(VOWELS_REF, vowels_tests),
        "cpu_limit_s": 2,
        "memory_mb": 128,
    },
    "time_limit_s": 180,
    "auto_end": {},
    "scoring": {"mode": "ranked", "points": [4000, 3000, 2000]},
}

# ---------------------------------------------------------------- 2. Code Golf

STAIRS_REF = "n = int(input())\nfor i in range(1, n + 1):\n    print(' ' * (n - i) + '#' * i)\n"
stairs_inputs = [f"{n}\n" for n in (1, 2, 4, 7, 10, 16, 30)] + [f"{rng.randint(3, 29)}\n" for _ in range(3)]
code_golf = {
    "round_name": "Round 2: Code Golf",
    "type": "code_golf",
    "title": "Staircase",
    "description_md": (
        "Read an integer `n` (1 ≤ n ≤ 30) and print a staircase of `#` that is `n` steps tall, "
        "**aligned to the right**: line `i` has `n - i` spaces followed by `i` hashes.\n\n"
        "**Shortest correct code wins.** Every hidden test must pass; your shortest passing "
        "submission counts, so keep shaving characters until the buzzer."
    ),
    "starter_code": "n = int(input())\n",
    "reference_solution": STAIRS_REF,
    "config": {
        "examples": cases(STAIRS_REF, ["3\n", "5\n"]),
        "tests": cases(STAIRS_REF, stairs_inputs),
        "cpu_limit_s": 2,
        "memory_mb": 128,
    },
    "time_limit_s": 240,
    "auto_end": {},
    "scoring": {"mode": "closest", "max": 4000, "min_share": 0.5},
}

# ---------------------------------------------------------------- 3. Best Time Complexity

PAIRS_HARNESS = (
    "import sys as _sys\n"
    "_data = _sys.stdin.read().split()\n"
    "_k = int(_data[0])\n"
    "_nums = [int(x) for x in _data[1:]]\n"
    "print(solve(_nums, _k))\n"
)
PAIRS_REF = (
    "from typing import List\n\n\n"
    "def solve(nums: List[int], k: int) -> int:\n"
    "    seen = {}\n"
    "    count = 0\n"
    "    for x in nums:\n"
    "        count += seen.get(k - x, 0)\n"
    "        seen[x] = seen.get(x, 0) + 1\n"
    "    return count\n"
)
PAIRS_GEN = (
    "def gen(n, rng):\n"
    "    nums = [rng.randint(-1000, 1000) for _ in range(n)]\n"
    "    return (nums, rng.randint(-200, 200))\n"
)


def pairs_input(nums: list[int], k: int) -> str:
    return f"{k}\n{' '.join(map(str, nums))}\n"


pairs_inputs = [
    pairs_input([1], 2),
    pairs_input([2, 2, 2, 2], 4),
    pairs_input([1, 2, 3, 4, 5], 100),
    pairs_input([-3, 3, 0, 0, -1, 1], 0),
    pairs_input([5, 1, 4, 2, 3], 6),
    pairs_input([7, 7], 14),
    pairs_input([1000, -1000, 0, 500, -500], 0),
    pairs_input([rng.randint(-20, 20) for _ in range(50)], 5),
    pairs_input([rng.randint(-100, 100) for _ in range(300)], -17),
    pairs_input([rng.randint(-1000, 1000) for _ in range(2000)], 42),
]
best_complexity = {
    "round_name": "Round 3: Best Time Complexity",
    "type": "best_complexity",
    "title": "Pair Sum",
    "description_md": (
        "Write `solve(nums, k)` that returns how many pairs of positions `i < j` have "
        "`nums[i] + nums[j] == k`.\n\n"
        "You only write the function: we read the input and print your answer.\n\n"
        "**Fastest correct code on big inputs wins.** Once time is up, every correct solution "
        "is run on inputs of 500, 2,000 and 8,000 numbers, and ranked by its time on the largest. "
        "Your latest passing submission is the one measured."
    ),
    "starter_code": (
        "from typing import List\n\n\n"
        "def solve(nums: List[int], k: int) -> int:\n"
        "    # Return how many pairs i < j have nums[i] + nums[j] == k\n"
        "    count = 0\n"
        "    return count\n"
    ),
    "reference_solution": PAIRS_REF,
    "config": {
        "examples": [
            {"stdin": pairs_input([1, 5, 7, -1], 6), "expected": run(PAIRS_REF + "\n\n" + PAIRS_HARNESS, pairs_input([1, 5, 7, -1], 6))},
            {"stdin": pairs_input([3, 3, 3], 6), "expected": run(PAIRS_REF + "\n\n" + PAIRS_HARNESS, pairs_input([3, 3, 3], 6))},
        ],
        "tests": [{"stdin": i, "expected": run(PAIRS_REF + "\n\n" + PAIRS_HARNESS, i)} for i in pairs_inputs],
        "cpu_limit_s": 2,
        "memory_mb": 128,
        "harness": PAIRS_HARNESS,
        "benchmark": {"generator": PAIRS_GEN, "sizes": [500, 2000, 8000], "repeats": 3, "cpu_limit_s": 5, "floor_ms": 20},
    },
    "time_limit_s": 240,
    "auto_end": {},
    "scoring": {"mode": "closest", "max": 4000, "min_share": 0.5},
}

# ---------------------------------------------------------------- multiple choice (samples)


def mcq(n: int, question: str, options: list[str], correct: int) -> dict:
    return {
        "round_name": f"Question {n}",
        "type": "multiple_choice",
        "title": question,
        "description_md": "",
        "config": {"options": [{"text": o} for o in options], "correct": [correct]},
        "time_limit_s": 20,
        "auto_end": {},
        "scoring": {"mode": "timed", "max": 1000},
    }


multiple_choice = [
    mcq(1, "What does CPU stand for?", ["Central Processing Unit", "Computer Personal Unit", "Central Program Utility", "Core Processing Unit"], 0),
    mcq(2, "Which data structure is first in, first out?", ["Stack", "Queue", "Tree", "Heap"], 1),
    mcq(3, "What is binary 1010 in decimal?", ["8", "12", "10", "5"], 2),
    mcq(4, "How many bits are in a byte?", ["4", "16", "32", "8"], 3),
    mcq(5, "Who created the Python programming language?", ["Guido van Rossum", "Linus Torvalds", "Tim Berners-Lee", "Ada Lovelace"], 0),
]

quiz = {
    "version": 1,
    "title": "CompSoc Challenge",
    "settings": {"allow_negative_totals": False, "show_reasons": True, "sounds": True},
    "questions": [*multiple_choice, super_fast, code_golf, best_complexity],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(quiz, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
