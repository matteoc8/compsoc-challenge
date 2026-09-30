"""serialize_question is the security boundary: no hidden data for teams or the projector."""

import json
import uuid
from pathlib import Path

import pytest

from app.engine.serialize import serialize_question
from app.models import Question, QuestionType

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed" / "sample_quiz.json").read_text(encoding="utf-8"))


def make_question(d: dict) -> Question:
    return Question(
        id=uuid.uuid4(),
        quiz_id=uuid.uuid4(),
        position=0,
        round_name=d["round_name"],
        type=QuestionType(d["type"]),
        title=d["title"],
        description_md=d["description_md"],
        starter_code=d.get("starter_code", ""),
        reference_solution=d.get("reference_solution", ""),
        config=d["config"],
        time_limit_s=d["time_limit_s"],
        auto_end=d["auto_end"],
        scoring=d["scoring"],
    )


def secrets_of(d: dict) -> list[str]:
    out = [d["reference_solution"].strip()] if d.get("reference_solution", "").strip() else []
    out += [t["stdin"].strip() for t in d["config"].get("tests", []) if len(t["stdin"].strip()) > 3]
    if d["config"].get("harness"):
        out.append(d["config"]["harness"].strip())
    if d["config"].get("benchmark"):
        out.append(d["config"]["benchmark"]["generator"].strip())
    return out


@pytest.mark.parametrize("qd", SEED["questions"], ids=lambda q: q["type"])
@pytest.mark.parametrize("role", ["team", "screen", "teacher"])
def test_no_hidden_data(qd, role):
    q = make_question(qd)
    blob = json.dumps(serialize_question(q, role))
    for secret in secrets_of(qd):
        # visible examples may legitimately share an input with a test; check those aren't tests-only
        if any(secret == e["stdin"].strip() for e in qd["config"].get("examples", [])):
            continue
        assert secret not in blob, f"{role} view leaks: {secret[:40]!r}"
    view = serialize_question(q, role)
    for key in ("tests", "reference_solution", "harness", "benchmark", "config"):
        assert key not in view
    if qd["type"] == "multiple_choice":
        assert [o["text"] for o in view["options"]] == [o["text"] for o in qd["config"]["options"]]
        assert ("correct" in view) == (role == "teacher")  # the answer only reaches the console


def test_team_view_has_what_the_workspace_needs():
    q = make_question(next(x for x in SEED["questions"] if x["type"] == "best_complexity"))
    v = serialize_question(q, "team")
    assert v["starter_code"] and v["examples"] and v["tests_total"] == 10
    assert v["benchmark_sizes"] == [500, 2000, 8000]
    assert "starter_code" not in serialize_question(q, "screen")


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        serialize_question(make_question(SEED["questions"][0]), "hacker")
