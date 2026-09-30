"""Browser end-to-end run of a whole game: teacher, projector and three team laptops.

    pip install playwright && playwright install chromium
    E2E_BASE=http://localhost:8080 python scripts/browser_e2e.py

Needs a FRESH database (it logs in with the seeded teacher/changeme and sets a new password)
and saves screenshots to ./e2e-shots. Exits non-zero on any browser console error.
"""

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

import os

BASE = os.environ.get("E2E_BASE", "http://localhost:8080")
SHOTS = Path.cwd() / "e2e-shots"
SHOTS.mkdir(exist_ok=True)
errors: list[str] = []
NEW_PW = "e2e-password-123"

VOWELS_OK = "print(sum(c in 'aeiouAEIOU' for c in input()))"
VOWELS_PARTIAL = "print(sum(c in 'aeiou' for c in input()))"
VOWELS_WRONG = "input()\nprint(0)"
STAIRS_LONG = "n = int(input())\nfor i in range(1, n + 1):\n    print(' ' * (n - i) + '#' * i)\n"
STAIRS_SHORT = "n=int(input())\nfor i in range(n):print(('#'*-~i).rjust(n))"
PAIRS_FAST = "def solve(nums, k):\n    seen = {}\n    c = 0\n    for x in nums:\n        c += seen.get(k - x, 0)\n        seen[x] = seen.get(x, 0) + 1\n    return c\n"
PAIRS_SLOW = "def solve(nums, k):\n    c = 0\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] + nums[j] == k:\n                c += 1\n    return c\n"


def watch(page, name):
    # a 401 from /api/auth/me before logging in is expected
    page.on("console", lambda m: m.type == "error" and "status of 401" not in m.text and errors.append(f"[{name}] console: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"[{name}] pageerror: {e}"))


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"))
    print("  shot", name)


def editor_text(page) -> str:
    return page.evaluate("() => Array.from(document.querySelectorAll('.cm-editor .cm-content .cm-line')).map(l => l.textContent).join('\\n')")


def set_code(page, code: str):
    page.locator(".cm-content").first.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(code)


def submit_and_wait(page, expect_text: str):
    page.get_by_role("button", name=re.compile(r"^Submit")).click()
    expect(page.get_by_role("status").filter(has_text=re.compile(expect_text)).first).to_be_visible(timeout=30_000)


def step(msg):
    print(f"== {msg}", flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ------------------------------------------------------------------ teacher
    step("teacher login + forced password change")
    tctx = browser.new_context(viewport={"width": 1440, "height": 900})
    teacher = tctx.new_page()
    watch(teacher, "teacher")
    teacher.goto(f"{BASE}/teacher")
    teacher.wait_for_url("**/teacher/login")
    teacher.get_by_label("Username").fill("teacher")
    teacher.get_by_label("Password").fill("changeme")
    teacher.get_by_role("button", name="Log in").click()
    expect(teacher.get_by_text("Choose your own password")).to_be_visible()
    teacher.get_by_label("New password", exact=True).fill(NEW_PW)
    teacher.get_by_label("Repeat new password").fill(NEW_PW)
    teacher.get_by_role("button", name="Save and continue").click()
    teacher.wait_for_url(f"{BASE}/teacher")
    expect(teacher.get_by_text("CompSoc Challenge").first).to_be_visible()
    shot(teacher, "01-teacher-home")

    step("editor opens and shows the questions")
    teacher.get_by_role("link", name="Edit").first.click()
    teacher.wait_for_url("**/edit")
    expect(teacher.get_by_text("Vowel Counter").first).to_be_visible()
    expect(teacher.get_by_text("What does CPU stand for?").first).to_be_visible()
    expect(teacher.get_by_label("Answer 1", exact=True)).to_have_value("Central Processing Unit")
    # an image on a multiple-choice question
    img = Path.cwd() / "e2e-question.png"
    from PIL import Image, ImageDraw

    pic = Image.new("RGB", (800, 400), (30, 30, 30))
    ImageDraw.Draw(pic).rectangle([60, 60, 740, 340], outline=(189, 164, 119), width=12)
    pic.save(img)
    teacher.locator('input[type="file"][accept^="image/"]').set_input_files(str(img))
    expect(teacher.locator("img[src^='/api/media/']").first).to_be_visible(timeout=15_000)
    expect(teacher.get_by_text("All changes saved")).to_be_visible(timeout=15_000)
    shot(teacher, "02-editor-mcq")
    teacher.get_by_text("Vowel Counter").first.click()
    expect(teacher.locator(".cm-editor").first).to_be_visible(timeout=15_000)
    shot(teacher, "02b-editor-coding")
    teacher.get_by_text("Pair Sum").first.click()
    expect(teacher.get_by_text("Benchmark generator")).to_be_visible()
    teacher.get_by_role("button", name="Test (verify)").click()
    expect(teacher.get_by_text("Reference solution passes every test.")).to_be_visible(timeout=60_000)
    shot(teacher, "03-editor-verified")
    teacher.get_by_role("link", name="← Quizzes").click()

    step("verify all + new game")
    teacher.get_by_role("button", name="Verify all").click()
    expect(teacher.get_by_text("all verified")).to_be_visible(timeout=90_000)
    teacher.get_by_role("button", name="New game").click()
    teacher.wait_for_url("**/teacher/games/**")
    expect(teacher.get_by_text("Lobby", exact=True)).to_be_visible(timeout=15_000)
    code = teacher.locator("header .font-mono").first.inner_text().strip()
    print("  join code", code)
    projector_href = teacher.get_by_role("link", name=re.compile("Open projector")).get_attribute("href")

    # ------------------------------------------------------------------ projector
    step("projector")
    pctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    proj = pctx.new_page()
    watch(proj, "projector")
    proj.goto(BASE + projector_href)
    proj.get_by_role("button", name="Start presentation").click()
    expect(proj.get_by_test_id("join-code")).to_have_text(code, timeout=15_000)

    # ------------------------------------------------------------------ teams
    step("three teams join")
    teams = {}
    for name in ("Alpha", "Delta", "Gamma"):
        ctx = browser.new_context(viewport={"width": 1366, "height": 768})
        page = ctx.new_page()
        watch(page, name)
        page.goto(f"{BASE}/join?code={code}")
        expect(page.get_by_placeholder("Game code")).to_have_value(code)
        page.get_by_placeholder("Team name").fill(name)
        page.get_by_role("button", name="Enter").click()
        page.wait_for_url("**/play")
        expect(page.get_by_text(f"You're in, {name}!")).to_be_visible(timeout=15_000)
        teams[name] = page
    expect(proj.get_by_text("Gamma", exact=True)).to_be_visible()
    shot(proj, "04-projector-lobby")

    step("practice editor: auto-indent, dedent after return, lint, Run")
    a = teams["Alpha"]
    expect(a.locator(".cm-editor")).to_be_visible(timeout=15_000)
    a.locator(".cm-content").click()
    a.keyboard.press("Control+A")
    a.keyboard.press("Delete")
    a.keyboard.type("def f(x):\nreturn x + y\nprint(f(1)")
    time.sleep(0.3)
    txt = editor_text(a)
    print("  typed ->", repr(txt))
    assert txt.startswith("def f(x):\n    return x + y\nprint(f(1)"), txt
    # Ruff: undefined name y shows an error squiggle within a few seconds
    expect(a.locator(".cm-lintRange-error, .cm-lintRange-warning").first).to_be_visible(timeout=30_000)
    shot(a, "05-team-lint")
    set_code(a, "a, b = map(int, input().split())\nprint(a + b)\n")
    a.get_by_role("button", name=re.compile(r"Run")).first.click()
    expect(a.get_by_role("button", name=re.compile(r"Example 1 ✓"))).to_be_visible(timeout=20_000)
    expect(a.get_by_role("button", name=re.compile(r"Example 2 ✓"))).to_be_visible()
    shot(a, "06-team-practice-run")
    # keyboard shortcut Ctrl+' runs too (after the 3 s cooldown)
    time.sleep(3.2)
    set_code(a, "a, b = map(int, input().split())\nprint(a - b)\n")
    a.locator(".cm-content").click()
    a.keyboard.press("Control+'")
    expect(a.get_by_role("button", name=re.compile(r"Example 1 ✗"))).to_be_visible(timeout=20_000)
    expect(a.get_by_text("Your output")).to_be_visible()

    shot(teacher, "08-console-lobby")
    step("start")
    teacher.get_by_role("button", name="▶ Start game").click()

    # ------------------------------------------------------------------ multiple choice
    # sample quiz: 5 questions; correct answers are A, B, C, D, A
    CORRECT = [0, 1, 2, 3, 0]
    for n in range(5):
        step(f"multiple choice question {n + 1}")
        expect(teams["Alpha"].get_by_role("button", name=re.compile("Coral star"))).to_be_visible(timeout=15_000)
        if n == 0:
            expect(proj.locator("img[src^='/api/media/']")).to_be_visible()
            expect(teams["Delta"].locator("img[src^='/api/media/']")).to_be_visible()
            shot(proj, "09-projector-mcq")
            shot(teams["Delta"], "10-team-mcq")
        picks = {"Alpha": CORRECT[n], "Delta": (CORRECT[n] + 1) % 4, "Gamma": CORRECT[n] if n % 2 == 0 else (CORRECT[n] + 2) % 4}
        tile = ["Coral star", "Blue hexagon", "Amber circle", "Teal square"]
        for name in ("Alpha", "Delta", "Gamma"):
            teams[name].get_by_role("button", name=re.compile(tile[picks[name]])).click()
            expect(teams[name].get_by_text("Answer locked in")).to_be_visible(timeout=10_000)
            if n == 0 and name == "Alpha":
                shot(teams["Alpha"], "10b-team-mcq-locked")
        # the last answer closes the question at once
        expect(teams["Alpha"].get_by_text(re.compile(r"Correct! \+"))).to_be_visible(timeout=15_000)
        expect(teams["Delta"].get_by_text("Not this time")).to_be_visible()
        if n == 0:
            time.sleep(1.0)
            shot(proj, "11-projector-mcq-results")
            shot(teams["Alpha"], "11b-team-mcq-correct")
        teacher.get_by_role("button", name=re.compile("Show leaderboard")).click()
        expect(proj.get_by_role("heading", name="Leaderboard")).to_be_visible()
        if n == 0:
            time.sleep(1.5)
            shot(proj, "11c-projector-leaderboard-mcq")
        teacher.get_by_role("button", name=re.compile("Next question")).click()

    # ------------------------------------------------------------------ Super Fast
    step("super fast intro + open")
    expect(proj.get_by_text("Round 1: Super Fast")).to_be_visible(timeout=10_000)
    expect(proj.get_by_text(re.compile("Only the first 3 teams"))).to_be_visible()
    time.sleep(1.0)
    shot(proj, "12-projector-intro-superfast")
    shot(teams["Delta"], "12b-team-intro-superfast")
    expect(teams["Delta"].get_by_text("Vowel Counter").first).to_be_visible(timeout=15_000)
    expect(teams["Delta"].locator(".cm-editor")).to_be_visible(timeout=15_000)
    expect(teams["Delta"].get_by_text(re.compile("3 of 3"))).to_be_visible()

    step("submissions: full (1st), partial (0), wrong")
    set_code(teams["Delta"], VOWELS_OK)
    submit_and_wait(teams["Delta"], "10 / 10 passed")
    set_code(teams["Alpha"], VOWELS_PARTIAL)
    submit_and_wait(teams["Alpha"], "6 / 10 passed")
    set_code(teams["Gamma"], VOWELS_WRONG)
    submit_and_wait(teams["Gamma"], "3 / 10 passed")
    expect(proj.get_by_text(re.compile(r"1st Delta"))).to_be_visible(timeout=10_000)
    expect(teams["Alpha"].get_by_text(re.compile("2 of 3"))).to_be_visible()
    shot(teams["Alpha"], "13-team-partial-result")
    time.sleep(5.2)  # Alpha's submit cooldown
    set_code(teams["Alpha"], VOWELS_OK)
    submit_and_wait(teams["Alpha"], "10 / 10 passed")
    expect(proj.get_by_text(re.compile(r"2nd Alpha"))).to_be_visible(timeout=10_000)
    shot(proj, "13b-projector-question")
    expect(teacher.get_by_text("Solved 2 / 3")).to_be_visible()
    shot(teacher, "14-console-monitor")

    step("refresh a team mid-question: draft restored")
    set_code(teams["Gamma"], "# my unsaved idea\nprint(len(input()))")
    time.sleep(0.8)  # local copy is written on change
    teams["Gamma"].reload()
    expect(teams["Gamma"].locator(".cm-editor")).to_be_visible(timeout=15_000)
    time.sleep(0.5)
    assert "# my unsaved idea" in editor_text(teams["Gamma"]), editor_text(teams["Gamma"])

    step("pause / resume / +15 s / end now")
    teacher.get_by_role("button", name="⏸ Pause").click()
    expect(proj.get_by_text("PAUSED")).to_be_visible()
    expect(teams["Alpha"].get_by_text(re.compile("Paused: keep coding"))).to_be_visible()
    teacher.get_by_role("button", name="▶ Resume").click()
    teacher.get_by_role("button", name="+15 s").click()
    teacher.get_by_role("button", name="End now").click()
    teacher.get_by_role("dialog").get_by_role("button", name="End now").click()
    expect(proj.get_by_text("Time's up!")).to_be_visible(timeout=10_000)
    expect(proj.get_by_text("Vowel Counter").first).to_be_visible(timeout=15_000)
    expect(proj.get_by_text("results", exact=False).first).to_be_visible(timeout=15_000)
    time.sleep(1.5)
    shot(proj, "15-projector-results-r1")
    shot(teams["Alpha"], "16-team-results-r1")

    step("leaderboard")
    teacher.get_by_role("button", name=re.compile("Show leaderboard")).click()
    expect(proj.get_by_role("heading", name="Leaderboard")).to_be_visible()
    time.sleep(2.0)
    shot(proj, "17-projector-leaderboard")
    step("manual points: a bonus and a deduction")
    teacher.get_by_placeholder(re.compile("Reason")).fill("cleanest code")
    teacher.get_by_role("button", name="Add 500 points to Gamma").click()
    expect(teams["Gamma"].get_by_text("+500: cleanest code")).to_be_visible(timeout=10_000)
    expect(proj.get_by_text("+500 cleanest code")).to_be_visible(timeout=10_000)
    teacher.get_by_placeholder(re.compile("Reason")).fill("talking")
    teacher.get_by_role("button", name="Take away 100 points from Delta").click()
    badge = proj.get_by_text("-100 talking")
    expect(badge).to_be_visible(timeout=10_000)
    assert "bg-fail" in (badge.get_attribute("class") or ""), badge.get_attribute("class")
    time.sleep(1.2)
    shot(proj, "18-projector-bonus-and-deduction")
    teacher.get_by_role("button", name="Undo").first.click()
    expect(teacher.get_by_text("undone").first).to_be_visible()

    # ------------------------------------------------------------------ round 2
    step("round 2: code golf")
    teacher.get_by_role("button", name=re.compile("Next question")).click()
    expect(teams["Delta"].get_by_text("Staircase").first).to_be_visible(timeout=15_000)
    expect(teams["Delta"].locator(".cm-editor")).to_be_visible(timeout=15_000)
    set_code(teams["Delta"], STAIRS_SHORT)
    expect(teams["Delta"].get_by_text(f"{len(STAIRS_SHORT)} chars")).to_be_visible()
    submit_and_wait(teams["Delta"], "10 / 10 passed")
    set_code(teams["Alpha"], STAIRS_LONG)
    submit_and_wait(teams["Alpha"], "10 / 10 passed")
    set_code(teams["Gamma"], "print('#')")
    submit_and_wait(teams["Gamma"], "passed")
    shot(teams["Delta"], "19-team-golf")
    expect(proj.get_by_text(str(len(STAIRS_SHORT)), exact=False).first).to_be_visible()
    shot(proj, "20-projector-golf-live")
    teacher.get_by_role("button", name="End now").click()
    teacher.get_by_role("dialog").get_by_role("button", name="End now").click()
    expect(proj.get_by_text("Shortest solutions")).to_be_visible(timeout=20_000)
    time.sleep(7.5)  # top 3 revealed one by one
    shot(proj, "21-projector-golf-reveal")
    teacher.get_by_role("button", name=re.compile("Show leaderboard")).click()
    time.sleep(1)
    teacher.get_by_role("button", name=re.compile("Next question")).click()

    # ------------------------------------------------------------------ round 3
    step("round 3: best time complexity")
    expect(teams["Alpha"].get_by_text("Pair Sum").first).to_be_visible(timeout=15_000)
    expect(teams["Alpha"].locator(".cm-editor")).to_be_visible(timeout=15_000)
    set_code(teams["Alpha"], PAIRS_FAST)
    submit_and_wait(teams["Alpha"], "10 / 10 passed")
    set_code(teams["Delta"], PAIRS_SLOW)
    submit_and_wait(teams["Delta"], "10 / 10 passed")
    shot(teams["Alpha"], "22-team-complexity")
    teacher.get_by_role("button", name="End now").click()
    teacher.get_by_role("dialog").get_by_role("button", name="End now").click()
    expect(proj.get_by_text("Measuring speed…")).to_be_visible(timeout=20_000)
    shot(proj, "23-projector-measuring")
    expect(proj.get_by_text("Pair Sum").first).to_be_visible(timeout=120_000)
    time.sleep(1.5)
    shot(proj, "24-projector-complexity-results")
    shot(teacher, "25-console-results-override")
    teacher.get_by_label("Class for Delta").fill("O(n²) checked")
    teacher.get_by_role("button", name="Save").first.click()
    expect(proj.get_by_text("O(n²) checked")).to_be_visible(timeout=10_000)

    step("podium + finish")
    teacher.get_by_role("button", name=re.compile("Show leaderboard")).click()
    time.sleep(1)
    teacher.get_by_role("button", name=re.compile("Show podium")).click()
    time.sleep(7)
    shot(proj, "26-projector-podium")
    shot(teams["Delta"], "27-team-podium")
    teacher.get_by_role("button", name=re.compile("Finish game")).click()
    expect(teacher.get_by_text("Finished", exact=True)).to_be_visible()
    expect(teacher.get_by_text("Best golfer")).to_be_visible()
    shot(teacher, "28-console-finished")
    r = teacher.request.get(f"{BASE}/api/games/{teacher.url.rsplit('/', 1)[1]}/analytics.csv?kind=teams")
    assert r.status == 200 and "Alpha" in r.text(), r.status

    browser.close()

print("\nCONSOLE/PAGE ERRORS:", len(errors))
for e in errors:
    print("  ", e[:300])
sys.exit(1 if errors else 0)
