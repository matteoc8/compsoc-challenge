"""Question editor, images, import/export, game creation guards."""

import io
import zipfile

from PIL import Image

from .conftest import login_teacher, sample_quiz

NEW_Q = {
    "round_name": "Bonus: Reverse",
    "type": "super_fast",
    "title": "Reverse a line",
    "description_md": "Print the line **reversed**.",
    "starter_code": "s = input()\n",
    "reference_solution": "print(input()[::-1])\n",
    "config": {"examples": [{"stdin": "abc\n", "expected": ""}], "tests": [{"stdin": "hello\n", "expected": ""}, {"stdin": "x\n", "expected": ""}]},
    "time_limit_s": 120,
}


def png_bytes(w=3000, h=1000) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (w, h), (70, 23, 143))
    img.save(buf, "PNG", pnginfo=None)
    return buf.getvalue()


def test_editor_round_trip(client):
    c = client
    login_teacher(c)
    quiz = sample_quiz(c, verify=False)
    qid = quiz["id"]

    # unverified questions block game creation
    r = c.post("/api/games", json={"quiz_id": qid})
    assert r.status_code == 409 and "Verify" in r.json()["detail"]

    # add → generate outputs → verify
    r = c.post(f"/api/quizzes/{qid}/questions", json=NEW_Q)
    assert r.status_code == 200, r.text
    q = r.json()
    n_seed = len(quiz["questions"])
    assert q["position"] == n_seed and q["verified_at"] is None and q["scoring"]["mode"] == "ranked"
    v = c.post(f"/api/questions/{q['id']}/verify").json()
    assert v["ok"] is False  # expected outputs are blank
    g = c.post(f"/api/questions/{q['id']}/generate-outputs").json()
    assert g["failures"] == [] and g["question"]["config"]["tests"][0]["expected"].strip() == "olleh"
    v = c.post(f"/api/questions/{q['id']}/verify").json()
    assert v["ok"] is True and v["question"]["verified_at"]

    # editing the tests un-verifies; editing only the title doesn't
    q = v["question"]
    body = {**NEW_Q, "config": q["config"], "title": "Reverse it", "expected_updated_at": q["updated_at"]}
    r = c.put(f"/api/questions/{q['id']}", json=body)
    assert r.status_code == 200 and r.json()["verified_at"]
    stale = {**body, "title": "Stale edit"}  # still carries the old updated_at
    r = c.put(f"/api/questions/{q['id']}", json=stale)
    assert r.status_code == 409 and r.json()["detail"]["current"]["title"] == "Reverse it"
    fresh = r.json()["detail"]["current"]
    cfg = {**fresh["config"], "tests": fresh["config"]["tests"] + [{"stdin": "ab\n", "expected": "ba\n"}]}
    r = c.put(f"/api/questions/{q['id']}", json={**NEW_Q, "config": cfg, "expected_updated_at": fresh["updated_at"]})
    assert r.status_code == 200 and r.json()["verified_at"] is None

    # validation: wrong scoring mode for the type, bad time limit
    assert c.post(f"/api/quizzes/{qid}/questions", json={**NEW_Q, "scoring": {"mode": "closest"}}).status_code == 422
    assert c.post(f"/api/quizzes/{qid}/questions", json={**NEW_Q, "time_limit_s": 30}).status_code == 422
    assert c.post(f"/api/quizzes/{qid}/questions", json={**NEW_Q, "round_name": "x" * 61}).status_code == 422

    # duplicate, reorder, delete
    dup = c.post(f"/api/questions/{q['id']}/duplicate").json()
    assert dup["title"].endswith("(copy)") and dup["position"] == n_seed + 1
    ids = [x["id"] for x in c.get(f"/api/quizzes/{qid}").json()["questions"]]
    new_order = [ids[-1]] + ids[:-1]
    assert c.put(f"/api/quizzes/{qid}/order", json={"question_ids": new_order}).status_code == 200
    assert [x["id"] for x in c.get(f"/api/quizzes/{qid}").json()["questions"]] == new_order
    assert c.put(f"/api/quizzes/{qid}/order", json={"question_ids": new_order[:2]}).status_code == 400
    assert c.delete(f"/api/questions/{dup['id']}").status_code == 200
    positions = [x["position"] for x in c.get(f"/api/quizzes/{qid}").json()["questions"]]
    assert positions == list(range(len(positions)))

    # image: re-encoded to WebP, resized, metadata gone; non-images rejected
    r = c.post("/api/media", files={"file": ("pic.png", png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["width"] == 1920 and m["height"] == 640
    img = c.get(m["url"])
    assert img.headers["content-type"] == "image/webp" and img.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(img.content)).format == "WEBP"
    assert c.post("/api/media", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")}).status_code == 400
    assert c.post("/api/media", files={"file": ("big.png", b"0" * 6_000_000, "image/png")}).status_code == 413
    r = c.put(f"/api/questions/{q['id']}", json={**NEW_Q, "config": cfg, "image_media_id": m["id"], "image_alt": "purple"})
    assert r.status_code == 200 and r.json()["image_url"] == m["url"]

    # export → import creates an independent copy with the image
    z = c.get(f"/api/quizzes/{qid}/export.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "quiz.json" in names and any(n.startswith("images/") for n in names)
    r = c.post("/api/quizzes/import", files={"file": ("q.zip", z.content, "application/zip")})
    assert r.status_code == 200, r.text
    imported = c.get(f"/api/quizzes/{r.json()['id']}").json()
    assert len(imported["questions"]) == len(c.get(f"/api/quizzes/{qid}").json()["questions"])
    with_img = [x for x in imported["questions"] if x["image_url"]]
    assert with_img and with_img[0]["image_url"] != m["url"]
    assert c.post("/api/quizzes/import", files={"file": ("bad.zip", b"nope", "application/zip")}).status_code == 400

    # the seeded quiz (used in no game) can be deleted
    assert c.delete(f"/api/quizzes/{imported['id']}").status_code == 200


def test_multiple_choice_editing(client):
    c = client
    login_teacher(c)
    quiz = sample_quiz(c, verify=False)
    qid = quiz["id"]
    base = {"round_name": "Question 9", "type": "multiple_choice", "title": "Pick one", "time_limit_s": 20}
    # a half-written draft saves (blank answers) but can't be verified yet
    r = c.post(f"/api/quizzes/{qid}/questions", json={**base, "config": {"options": [{"text": "A"}, {"text": ""}], "correct": []}})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["scoring"] == {"mode": "timed", "max": 1000}
    v = c.post(f"/api/questions/{q['id']}/verify").json()
    assert not v["ok"] and any("correct" in p for p in v["problems"]) and any("text" in p for p in v["problems"])
    good = {**base, "config": {"options": [{"text": "A"}, {"text": "B"}, {"text": "C"}], "correct": [2, 2]}}
    r = c.put(f"/api/questions/{q['id']}", json=good)
    assert r.status_code == 200 and r.json()["config"]["correct"] == [2]
    assert c.post(f"/api/questions/{q['id']}/verify").json()["ok"]
    # coding-only fields are dropped; bad input is refused
    assert r.json()["reference_solution"] == "" and r.json()["config"]["tests"] == []
    bad = [
        {**good, "config": {"options": [{"text": "A"}], "correct": [3]}},  # points at nothing
        {**good, "time_limit_s": 300},  # multiple choice is 5–240 s
        {**good, "config": {"options": [{"text": str(i)} for i in range(5)], "correct": [0]}},  # max 4 answers
        {**good, "scoring": {"mode": "closest"}},
    ]
    for b in bad:
        assert c.put(f"/api/questions/{q['id']}", json=b).status_code == 422, b
