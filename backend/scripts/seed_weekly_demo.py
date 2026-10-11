"""Sample problems of the week and pupils, to see what the site looks like with data in it.

Uses the three coding questions already in the CompSoc Challenge quiz (no new quiz): Vowel
Counter in September, Pair Sum last week and Staircase this week (still open). Entries are
added as "queued", so restart the site afterwards and the judge marks them.

Run from backend/ with the site stopped:
    python scripts/seed_weekly_demo.py           # add
    python scripts/seed_weekly_demo.py --remove  # take it all out again
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import init_engine, session_scope  # noqa: E402
from app.judge.golf import golf_chars  # noqa: E402
from app.models import Question, Teacher, WeeklyEntry, WeeklyPerson, WeeklyProblem  # noqa: E402

LONDON = ZoneInfo("Europe/London")
WEEKS = {  # question title -> opens (9am London time, stored as UTC); each runs 7 days
    "Vowel Counter": datetime(2026, 9, 18, 9, 0, tzinfo=LONDON).astimezone(timezone.utc),
    "Pair Sum": datetime(2026, 10, 2, 9, 0, tzinfo=LONDON).astimezone(timezone.utc),
    "Staircase": datetime(2026, 10, 9, 9, 0, tzinfo=LONDON).astimezone(timezone.utc),
}

V_OK = "print(sum(c in 'aeiouAEIOU' for c in input()))"
V_OK2 = "s = input().lower()\nprint(sum(s.count(v) for v in 'aeiou'))"
V_LOWER = "print(sum(c in 'aeiou' for c in input()))"  # forgets capitals
V_Y = "print(sum(c in 'aeiouyAEIOUY' for c in input()))"  # counts y

P_FAST = "def solve(nums, k):\n    seen = {}\n    c = 0\n    for x in nums:\n        c += seen.get(k - x, 0)\n        seen[x] = seen.get(x, 0) + 1\n    return c\n"
P_COUNTER = (
    "from collections import Counter\n\ndef solve(nums, k):\n    c = Counter(nums)\n    t = 0\n    for x in c:\n        y = k - x\n"
    "        if x < y:\n            t += c[x] * c.get(y, 0)\n        elif x == y:\n            t += c[x] * (c[x] - 1) // 2\n    return t\n"
)
P_SLOW = "def solve(nums, k):\n    c = 0\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] + nums[j] == k:\n                c += 1\n    return c\n"
P_WRONG = "def solve(nums, k):\n    c = 0\n    for i in range(len(nums)):\n        for j in range(i, len(nums)):\n            if nums[i] + nums[j] == k:\n                c += 1\n    return c\n"  # pairs a number with itself

S_SHORT = "n=int(input())\nfor i in range(n):print(('#'*-~i).rjust(n))"
S_MID = "n=int(input())\nfor i in range(1,n+1):print(('#'*i).rjust(n))"
S_LONG = "n = int(input())\nfor i in range(1, n + 1):\n    print(' ' * (n - i) + '#' * i)\n"
S_LEFT = "n=int(input())\nfor i in range(1,n+1):print('#'*i)"  # left-aligned: only n=1 passes

# name, year group, {question: [(code, hours after it opened)]}
PEOPLE = [
    ("Oliver Bennett", "4", {"Vowel Counter": [(V_LOWER, 20), (V_OK, 21)], "Staircase": [(S_LONG, 30)]}),
    ("Arjun Mehta", "4", {"Vowel Counter": [(V_OK2, 50)], "Pair Sum": [(P_SLOW, 26)], "Staircase": [(S_LEFT, 5), (S_MID, 6)]}),
    ("Leo Fischer", "4", {"Staircase": [(S_LEFT, 8)]}),
    ("Sam Okafor", "5", {"Vowel Counter": [(V_OK, 1.5)], "Pair Sum": [(P_SLOW, 3), (P_FAST, 4)], "Staircase": [(S_MID, 2)]}),
    ("Hugo Laurent", "5", {"Vowel Counter": [(V_Y, 6)], "Pair Sum": [(P_WRONG, 40)]}),
    ("Ethan Zhang", "5", {"Pair Sum": [(P_COUNTER, 12)], "Staircase": [(S_LONG, 3), (S_SHORT, 26)]}),
    ("Felix Hart", "6", {"Vowel Counter": [(V_OK2, 3)], "Pair Sum": [(P_FAST, 30)]}),
    ("Max Ivanov", "6", {"Vowel Counter": [(V_LOWER, 9)], "Staircase": [(S_LONG, 40)]}),
    ("Rohan Kapoor", "L8", {"Vowel Counter": [(V_OK, 0.7)], "Pair Sum": [(P_FAST, 1)], "Staircase": [(S_MID, 1), (S_SHORT, 4)]}),
    ("James Whitfield", "L8", {"Pair Sum": [(P_SLOW, 70)], "Staircase": [(S_LONG, 10)]}),
    ("Alex Morgan", "U8", {"Vowel Counter": [(V_OK, 1.1)], "Pair Sum": [(P_COUNTER, 2)]}),
    ("William Park", "U8", {"Vowel Counter": [(V_Y, 30), (V_OK2, 31)], "Pair Sum": [(P_WRONG, 5), (P_FAST, 6)], "Staircase": [(S_MID, 20)]}),
]


def email_of(name: str) -> str:
    return name.lower().replace(" ", ".") + "@stpaulsschool.org.uk"


async def questions(s) -> dict[str, Question]:
    out = {}
    for title in WEEKS:
        q = (await s.scalars(select(Question).where(Question.title == title, Question.verified_at.is_not(None)))).first()
        if not q:
            raise SystemExit(f"No verified question called {title!r}")
        out[title] = q
    return out


async def seeded_weeks(s, qs) -> list[WeeklyProblem]:
    rows = (await s.scalars(select(WeeklyProblem))).all()
    return [w for w in rows for t, q in qs.items() if w.question_id == q.id and w.opens_at == WEEKS[t]]


async def add() -> None:
    async with session_scope() as s:
        qs = await questions(s)
        if await seeded_weeks(s, qs):
            raise SystemExit("The sample weeks are already there (use --remove first)")
        admin = (await s.scalars(select(Teacher))).first()
        weeks = {}
        for title, opens in WEEKS.items():
            w = WeeklyProblem(owner_id=admin.id, question_id=qs[title].id, opens_at=opens, closes_at=opens + timedelta(days=7), published=True, solution_published=True)
            s.add(w)
            weeks[title] = w
        await s.flush()
        n = 0
        for name, year, entries in PEOPLE:
            email = email_of(name)
            first = min(weeks[t].opens_at + timedelta(hours=h) for t, subs in entries.items() for _, h in subs)
            s.add(WeeklyPerson(email=email, name=name, year_group=year, created_at=first))
            for title, subs in entries.items():
                for code, hours in subs:
                    s.add(WeeklyEntry(weekly_id=weeks[title].id, name=name, email=email, code=code, char_count=golf_chars(code), status="queued", submitted_at=weeks[title].opens_at + timedelta(hours=hours)))
                    n += 1
    print(f"Added 3 weeks, {len(PEOPLE)} people and {n} submissions. Start the site and the judge marks them.")


async def remove() -> None:
    async with session_scope() as s:
        emails = [email_of(n) for n, _, _ in PEOPLE]
        await s.execute(delete(WeeklyEntry).where(WeeklyEntry.email.in_(emails)))
        await s.execute(delete(WeeklyPerson).where(WeeklyPerson.email.in_(emails)))
        weeks = await seeded_weeks(s, await questions(s))
        for w in weeks:
            await s.delete(w)  # takes anyone else's entries for those weeks with it
    print(f"Removed the sample people and {len(weeks)} sample weeks.")


if __name__ == "__main__":
    init_engine()
    asyncio.run(remove() if "--remove" in sys.argv else add())
