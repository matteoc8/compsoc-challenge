from app.engine.scoring import Entry, closest_points, score_at_close, super_fast_points, timed_points
from app.judge.benchmark import estimate_class, slope
from app.judge.client import normalise_output, outputs_match, summarise_error
from app.judge.golf import golf_chars
from app.schemas.question import Closest, Flat, Ranked, SpeedWeighted, Timed

P = SpeedWeighted()  # 4000, floors 0.1 / 0.6, min pass 0.5
T = 4 * 60 * 1000


def test_plan_worked_example_exact():
    assert super_fast_points(P, 40_000, T, 7, 10) == 2992  # Alpha
    assert super_fast_points(P, 60_000, T, 10, 10) == 3100  # Delta
    assert super_fast_points(P, 180_000, T, 10, 10) == 1300  # Gamma
    assert 2992 - 1300 == 1692


def test_super_fast_threshold_and_bounds():
    assert super_fast_points(P, 1_000, T, 4, 10) == 0  # below half the tests
    assert super_fast_points(P, 1_000, T, 0, 10) == 0
    assert super_fast_points(P, 0, T, 5, 10) == round(4000 * 1.0 * 0.8)  # exactly half counts
    assert super_fast_points(P, 0, T, 10, 10) == 4000
    assert super_fast_points(P, T, T, 10, 10) == 400  # 10% at the buzzer
    assert super_fast_points(P, T + 5000, T, 10, 10) == 400  # grace period can't go lower
    assert super_fast_points(P, 1000, T, 0, 0) == 0


def test_multiple_choice_timing():
    assert timed_points(Timed(), 0, 20_000) == 1000
    assert timed_points(Timed(), 10_000, 20_000) == 750
    assert timed_points(Timed(), 20_000, 20_000) == 500
    assert timed_points(Timed(), 25_000, 20_000) == 500  # grace period can't go lower


def test_closest_shape():
    r = Closest()
    assert closest_points(r, 100, 100) == 4000
    assert closest_points(r, 200, 100) == 3000  # twice the best gets 75%
    assert closest_points(r, 10_000, 100) == 2020
    assert closest_points(r, 50, 100) == 4000  # can't beat best


def test_score_at_close_modes_and_ties():
    entries = [Entry("a", 40, 1), Entry("b", 40, 2), Entry("c", 80, 3), Entry("d", None, 4)]
    pts = score_at_close(Closest(), entries)
    assert pts == {"a": 4000, "b": 4000, "c": 3000, "d": 2000}
    assert score_at_close(Flat(max=1000), entries) == {"a": 1000, "b": 1000, "c": 1000, "d": 1000}
    ranked = score_at_close(Ranked(points=[400, 300, 200, 100]), entries)
    assert ranked == {"a": 400, "b": 400, "c": 200, "d": 100}  # ties share the better position
    assert score_at_close(Closest(), []) == {}


def test_golf_rule():
    assert golf_chars("print(1)") == 8
    assert golf_chars("print(1)\r\n\r\n  \t") == 8
    assert golf_chars("a=1\r\nprint(a)\n") == len("a=1\nprint(a)")
    assert golf_chars("print('é')") == 10  # code points, not bytes
    assert golf_chars("  x") == 3  # leading whitespace counts


def test_output_normalisation():
    assert normalise_output("1 \n2\t\n\n\n") == "1\n2"
    assert outputs_match("3\r\n", "3")
    assert not outputs_match("3 4", "3  4")


def test_error_summary_never_leaks_messages():
    tb = (
        'Traceback (most recent call last):\n  File "script.py", line 3, in <module>\n'
        "ValueError: invalid literal for int() with base 10: 'SECRET-HIDDEN-INPUT'\n"
    )
    s = summarise_error(tb)
    assert s == "ValueError on line 3"
    assert "SECRET" not in s
    assert summarise_error("") == ""
    assert summarise_error("Killed: something weird") == "Killed"
    assert summarise_error('  File "x", line 9\n    x = (\n        ^\nSyntaxError: ...') == "SyntaxError on line 9"


def test_complexity_estimates():
    est = lambda t, to=None: estimate_class(t, to, 20, 5000)  # noqa: E731
    assert est({500: 1, 2000: 2, 8000: 5}) == "≈ O(n) or better"
    assert slope({2000: 100, 8000: 1600}) == 2.0
    assert est({500: 10, 2000: 100, 8000: 1600}) == "≈ O(n²)"
    assert est({500: 30, 2000: 120, 8000: 480}) == "≈ O(n) / O(n log n)"
    # regression: noisy baseline subtraction left the mid size at ~21 ms for an O(n²) entry
    assert est({500: 0, 2000: 21, 8000: 1388}) == "≈ O(n²)"
    # a timeout counts as at least the CPU limit at that size
    assert est({500: 10, 2000: 160}, 8000) == "≈ O(n²) (timed out at the largest size)"
    assert est({500: 400}, 2000).startswith("≈ O(n²)")
    assert est({}, 500) == "too slow"
    assert est({500: 5, 2000: 400, 8000: 30000}).startswith("≈ O(n³)")
