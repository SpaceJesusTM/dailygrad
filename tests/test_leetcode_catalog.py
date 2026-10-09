"""The LeetCode catalog: the packaged question bank, its validation, and the deterministic choice of the next problem."""

import re
from collections import Counter

import pytest

from dailygrad.config import LEETCODE_TRACKS
from dailygrad.leetcode import review_ranks
from dailygrad.leetcode_catalog import (
    CATEGORIES, DIFFICULTIES, CatalogError, gives_away, load_catalog, next_problem, spoiler_in, track_for_day,
)  # fmt: skip
from dailygrad.models import Problem

CATALOG = load_catalog()
ROTATION = list(LEETCODE_TRACKS)

SOURCE = """
[[source]]
id = "{id}"
name = "{id}"
kind = "{kind}"
publisher = "Someone"
url = "https://example.com/{id}"
retrieved = "2026-10-09"
problems = {problems}
"""

PROBLEM = """
[[problem]]
id = "two-sum"
number = 1
title = "Two Sum"
difficulty = "easy"
category = "arrays-hashing"
tracks = ["neetcode-150", "amd", "vanguard"]
statement = "Find the two elements that add up to the target."
input = "nums = [2, 7], target = 9"
output = "[0, 1]"
constraints = ["exactly one pair exists"]
hints = ["Could remembering earlier elements help?", "Look up the partner value quickly."]
spoilers = ["hash"]
approach = "Scan once with a hash map from value to index."
time = "O(n)"
space = "O(n)"
edge_cases = ["the same value twice"]
"""


def write_catalog(tmp_path, problem=PROBLEM, counts=(1, 1, 1), header='[catalog]\nsnapshot = "2026-10-09"\n'):
    kinds = ("curriculum", "company", "company")
    sources = "".join(
        SOURCE.format(id=track, kind=kind, problems=count) for track, kind, count in zip(LEETCODE_TRACKS, kinds, counts)
    )
    path = tmp_path / "leetcode.toml"
    path.write_text(header + sources + problem, encoding="utf-8")
    return path


def make_problem(id, tracks, difficulty="easy", category="arrays-hashing"):
    return Problem(
        id=id, number=abs(hash(id)) % 9000 + 1, title=id, difficulty=difficulty, category=category, tracks=tuple(tracks),
        statement="s", example_input="i", example_output="o", constraints=("c",), hints=("h",), spoilers=("x",),
        approach="a", time="O(n)", space="O(1)", edge_cases=("e",),
    )  # fmt: skip


def simulate(tracks, rotation, days, ranks=None):
    """Run the rotation for `days` days over {track: [problems in order]}. Returns [(track, problem id, review)]."""
    shown, result = [], []
    for _ in range(days):
        track = track_for_day(rotation, len(shown))
        problem, review = next_problem(tracks[track], shown, ranks)
        shown.append(problem.id)
        result.append((track, problem.id, review))
    return result


# --- the packaged catalog


def test_all_three_sources_load_with_the_counts_they_listed():
    assert list(CATALOG.sources) == ["neetcode-150", "amd", "vanguard"]
    counts = {track: len(CATALOG.track(track)) for track in CATALOG.sources}

    assert counts == {"neetcode-150": 150, "amd": 17, "vanguard": 32}  # what each list held on the snapshot day
    assert all(source.problems == counts[track] for track, source in CATALOG.sources.items())
    assert len(CATALOG.problems) == 182  # 150, plus 32 that only the company lists have


def test_the_snapshot_date_and_provenance_are_kept():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", CATALOG.snapshot)
    for source in CATALOG.sources.values():
        assert source.retrieved == CATALOG.snapshot and source.url.startswith("https://") and source.publisher


def test_company_lists_are_credited_to_the_third_party_that_publishes_them():
    neetcode, amd, vanguard = CATALOG.sources.values()

    assert (neetcode.kind, neetcode.credit) == ("curriculum", "NeetCode 150")
    for company in (amd, vanguard):
        assert company.kind == "company" and company.publisher == "Interview Solver"
        assert "interviewsolver.com" in company.url
        assert company.credit == f"{company.name} (Interview Solver tag)"  # never a bare, official-looking tag


def test_ids_numbers_and_urls_are_valid_and_unique():
    ids, numbers = [p.id for p in CATALOG.problems], [p.number for p in CATALOG.problems]

    assert len(set(ids)) == len(ids) and len(set(numbers)) == len(numbers)
    for problem in CATALOG.problems:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", problem.id) and problem.number >= 1
        assert problem.url == f"https://leetcode.com/problems/{problem.id}/"
        assert problem.difficulty in DIFFICULTIES and problem.category in CATEGORIES and problem.title.strip()


def test_metadata_follows_leetcode_where_a_source_was_wrong():
    assert (CATALOG.get("two-sum").number, CATALOG.get("two-sum").difficulty) == (1, "easy")
    assert CATALOG.get("edit-distance").difficulty == "medium"  # the NeetCode repository says hard
    assert CATALOG.get("powx-n").number == 50  # its directory is named pow-x-n, which is not LeetCode's slug
    assert CATALOG.get("pow-x-n") is None and CATALOG.get(None) is None


def test_a_problem_listed_by_several_sources_is_one_entry_with_every_track():
    assert CATALOG.get("two-sum").tracks == ("neetcode-150", "amd")
    assert CATALOG.get("course-schedule").tracks == ("neetcode-150", "vanguard")
    assert CATALOG.get("climbing-stairs").tracks == ("neetcode-150", "amd", "vanguard")
    assert [source.id for source in CATALOG.sources_of(CATALOG.get("climbing-stairs"))] == ROTATION

    listed = sum(len(problem.tracks) for problem in CATALOG.problems)
    assert listed == 150 + 17 + 32 and listed - len(CATALOG.problems) == 17  # 15 overlap; two of them twice
    assert sum(len(problem.tracks) > 1 for problem in CATALOG.problems) == 15


def test_every_problem_has_practice_material_and_reference_material():
    for problem in CATALOG.problems:
        assert 20 <= len(problem.statement) <= 420 and problem.example_input and problem.example_output
        assert problem.constraints and len(problem.hints) >= 2 and problem.spoilers
        assert len(problem.approach) >= 40 and problem.edge_cases
        assert re.fullmatch(r"O\(.+\)", problem.time) and re.fullmatch(r"O\(.+\)", problem.space)


def test_what_a_digest_shows_never_gives_the_approach_away():
    for problem in CATALOG.problems:
        assert spoiler_in(problem, problem.statement) is None, problem.id
        assert not gives_away(problem, problem.hints[0]), problem.id
        assert not any(re.search(r"\bO\s*\(", hint) for hint in problem.hints), problem.id  # no hint states a complexity


def test_premium_problems_are_marked():
    assert CATALOG.get("meeting-rooms").premium and CATALOG.get("logger-rate-limiter").premium
    assert not CATALOG.get("two-sum").premium
    assert sum(problem.premium for problem in CATALOG.problems) == 13


@pytest.mark.parametrize("track", LEETCODE_TRACKS)
def test_a_track_starts_easy_and_walks_the_topics_in_order_at_each_difficulty(track):
    order = CATALOG.track(track)
    keys = [(DIFFICULTIES.index(p.difficulty), list(CATEGORIES).index(p.category)) for p in order]

    assert keys == sorted(keys)  # easy before medium before hard, and topics in order within each
    assert order[0].difficulty == "easy" and all(track in problem.tracks for problem in order)


def test_the_first_problems_are_accessible_fundamentals():
    assert [p.id for p in CATALOG.track("neetcode-150")[:3]] == ["contains-duplicate", "valid-anagram", "two-sum"]
    assert CATALOG.track("amd")[0].id == "two-sum"
    assert all(problem.difficulty == "easy" for problem in CATALOG.track("vanguard")[:11])


# --- validation


def test_a_small_valid_catalog_loads(tmp_path):
    catalog = load_catalog(write_catalog(tmp_path))

    assert [problem.id for problem in catalog.problems] == ["two-sum"]
    assert catalog.problems[0].tracks == ("neetcode-150", "amd", "vanguard") and not catalog.problems[0].premium


@pytest.mark.parametrize(
    "old, new, message",
    [
        ('id = "two-sum"', 'id = "Two Sum"', "LeetCode slug"),
        ("number = 1", "number = 0", "positive number"),
        ('difficulty = "easy"', 'difficulty = "trivial"', "unknown difficulty or category"),
        ('category = "arrays-hashing"', 'category = "sorting"', "unknown difficulty or category"),
        ('tracks = ["neetcode-150", "amd", "vanguard"]', 'tracks = ["neetcode-150", "google", "amd", "vanguard"]', "tracks must name"),
        ('tracks = ["neetcode-150", "amd", "vanguard"]', 'tracks = ["amd", "amd", "neetcode-150", "vanguard"]', "each once"),
        ('time = "O(n)"', 'time = "linear"', "written like O(n)"),
        ('input = "nums = [2, 7], target = 9"', 'input = "`nums`"', "plain single lines"),
        ('constraints = ["exactly one pair exists"]', "constraints = []", "constraints must be 1 to 4"),
        ('spoilers = ["hash"]', 'spoilers = ["hash"]\nanswer = "x"', "unknown or invalid field answer"),
        ('approach = "Scan once with a hash map from value to index."', 'approach = " "', "approach is empty"),
        ('title = "Two Sum"', "title = 2", "title is missing or is not of type str"),
    ],
)
def test_an_invalid_entry_is_refused_with_its_reason(tmp_path, old, new, message):
    assert old in PROBLEM
    with pytest.raises(CatalogError, match=re.escape(message)):
        load_catalog(write_catalog(tmp_path, PROBLEM.replace(old, new)))


def test_a_first_hint_that_names_the_approach_is_refused(tmp_path):
    spoiled = PROBLEM.replace("Could remembering earlier elements help?", "Try a hash map of earlier elements.")

    with pytest.raises(CatalogError, match="first hint contains the spoiler 'hash'"):
        load_catalog(write_catalog(tmp_path, spoiled))


def test_a_statement_that_names_the_approach_is_refused(tmp_path):
    spoiled = PROBLEM.replace("Find the two elements", "Using hashing, find the two elements")

    with pytest.raises(CatalogError, match="statement contains the spoiler"):
        load_catalog(write_catalog(tmp_path, spoiled))


def test_a_hint_that_states_a_complexity_is_refused(tmp_path):
    spoiled = PROBLEM.replace("Look up the partner value quickly.", "Aim for O(n) time.")

    with pytest.raises(CatalogError, match="a hint states a complexity"):
        load_catalog(write_catalog(tmp_path, spoiled))


def test_the_same_problem_twice_is_refused_instead_of_becoming_two_entries(tmp_path):
    with pytest.raises(CatalogError, match="duplicate problem id: two-sum"):
        load_catalog(write_catalog(tmp_path, PROBLEM + PROBLEM, counts=(2, 2, 2)))


def test_a_source_whose_count_no_longer_matches_is_refused(tmp_path):
    with pytest.raises(CatalogError, match="source amd lists 43 problems but the catalog holds 1"):
        load_catalog(write_catalog(tmp_path, counts=(1, 43, 1)))


def test_a_catalog_without_its_snapshot_date_sources_or_problems_is_refused(tmp_path):
    with pytest.raises(CatalogError, match="snapshot"):
        load_catalog(write_catalog(tmp_path, header=""))
    with pytest.raises(CatalogError, match=r"no \[\[problem\]\] entries"):
        load_catalog(write_catalog(tmp_path, problem=""))
    bare = tmp_path / "bare.toml"
    bare.write_text('[catalog]\nsnapshot = "2026-10-09"\n' + PROBLEM, encoding="utf-8")
    with pytest.raises(CatalogError, match=r"no \[\[source\]\] entries"):
        load_catalog(bare)


def test_an_unreadable_catalog_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="cannot read the LeetCode catalog"):
        load_catalog(tmp_path / "missing.toml")
    broken = tmp_path / "broken.toml"
    broken.write_text("[[problem", encoding="utf-8")
    with pytest.raises(CatalogError, match="cannot read the LeetCode catalog"):
        load_catalog(broken)


# --- spoilers


def test_a_spoiler_matches_at_the_start_of_a_word_in_any_case():
    two_sum = CATALOG.get("two-sum")

    assert spoiler_in(two_sum, "Use a Hash Map.") == "hash"
    assert spoiler_in(two_sum, "Try hashing the values.") == "hash"
    assert spoiler_in(two_sum, "Look for the complement.") == "complement"
    assert spoiler_in(two_sum, "Have you thrashed it out?") is None  # inside a word is not a match
    assert spoiler_in(two_sum, "Use a hash map.", already_said="I would use a HASH map") is None


def test_generated_text_gives_the_approach_away_by_spoiler_complexity_or_code():
    two_sum = CATALOG.get("two-sum")

    assert gives_away(two_sum, "A dictionary would help.")
    assert gives_away(two_sum, "You can do it in O(n).") and gives_away(two_sum, "This takes O (n log n) time.")
    assert gives_away(two_sum, "```python\nfor x in nums: ...\n```")
    assert not gives_away(two_sum, "Could remembering what you have already seen save repeated work?")


# --- the rotation and each track's progress


def test_the_default_rotation_repeats_neetcode_amd_vanguard():
    assert [track_for_day(ROTATION, day) for day in range(7)] == [
        "neetcode-150", "amd", "vanguard", "neetcode-150", "amd", "vanguard", "neetcode-150",
    ]  # fmt: skip


def test_a_rotation_can_be_reconfigured():
    assert [track_for_day(["amd"], day) for day in range(3)] == ["amd", "amd", "amd"]
    assert [track_for_day(["amd", "amd", "vanguard"], day) for day in range(4)] == ["amd", "amd", "vanguard", "amd"]


def test_each_track_advances_through_its_own_problems():
    tracks = {
        "a": [make_problem(f"a{n}", ["a"]) for n in range(3)],
        "b": [make_problem(f"b{n}", ["b"]) for n in range(3)],
    }

    days = simulate(tracks, ["a", "b"], 6)

    assert days == [("a", "a0", False), ("b", "b0", False), ("a", "a1", False), ("b", "b1", False), ("a", "a2", False), ("b", "b2", False)]


def test_a_problem_another_track_already_showed_is_not_repeated_while_new_ones_remain():
    shared = make_problem("shared", ["a", "b"])
    tracks = {"a": [shared, make_problem("a1", ["a"])], "b": [shared, make_problem("b1", ["b"])]}

    days = simulate(tracks, ["a", "b"], 3)

    assert days == [("a", "shared", False), ("b", "b1", False), ("a", "a1", False)]  # b skips what a showed


def test_a_track_whose_problems_were_all_used_elsewhere_keeps_its_day_as_a_review():
    shared = [make_problem("s0", ["a", "b"]), make_problem("s1", ["a", "b"])]
    tracks = {"a": [*shared, make_problem("a2", ["a"]), make_problem("a3", ["a"])], "b": shared}

    days = simulate(tracks, ["a", "a", "b"], 3)

    assert days == [("a", "s0", False), ("a", "s1", False), ("b", "s0", True)]  # never an empty or skipped day


def test_an_exhausted_track_recycles_least_shown_first_without_losing_history():
    order = [make_problem(f"p{n}", ["a"]) for n in range(3)]

    days = simulate({"a": order}, ["a"], 9)

    assert [problem for _, problem, _ in days] == ["p0", "p1", "p2", "p0", "p1", "p2", "p0", "p1", "p2"]
    assert [review for _, _, review in days] == [False] * 3 + [True] * 6
    assert Counter(problem for _, problem, _ in days) == {"p0": 3, "p1": 3, "p2": 3}


def test_a_review_never_repeats_the_previous_day_when_there_is_another_choice():
    order = [make_problem("p0", ["a"]), make_problem("p1", ["a"])]

    assert next_problem(order, ["p1", "p0"]) == (order[1], True)
    assert next_problem(order, ["p0", "p1", "p1"]) == (order[0], True)
    assert next_problem(order[:1], ["p0"]) == (order[0], True)  # a one-problem track has no other choice


def test_among_equally_shown_problems_a_review_takes_the_one_marked_as_needing_it():
    order = [make_problem(f"p{n}", ["a"]) for n in range(4)]
    shown = ["p0", "p1", "p2", "p3", "x"]
    ranks = review_ranks({
        "p0": (None, "comfortable", None),
        "p1": (None, None, "2026-10-09T00:00:00"),  # solved in code
        "p2": (None, "needs-review", None),
    })  # fmt: skip

    assert ranks == {"p0": 2, "p1": 3, "p2": 0}
    assert next_problem(order, shown, ranks)[0].id == "p2"
    assert next_problem(order, shown)[0].id == "p0"  # with nothing marked: the one shown longest ago
    assert next_problem(order, [*shown, "p2", "y"], ranks)[0].id == "p3"  # a mark never beats being shown less often


def test_the_choice_depends_only_on_the_catalog_and_the_history():
    order, shown = CATALOG.track("amd"), ["two-sum", "contains-duplicate", "move-zeroes"]

    assert next_problem(order, shown) == next_problem(order, list(shown))
    assert next_problem(order, shown) == (CATALOG.get("merge-sorted-array"), False)
    assert shown == ["two-sum", "contains-duplicate", "move-zeroes"]  # and it does not touch the history


def test_two_years_of_the_real_rotation_never_leave_a_day_empty():
    tracks = {track: CATALOG.track(track) for track in ROTATION}
    days = simulate(tracks, ROTATION, 730)

    assert [track for track, _, _ in days[:6]] == ROTATION * 2
    assert all(CATALOG.get(problem_id) and track in CATALOG.get(problem_id).tracks for track, problem_id, _ in days)

    first_showings = [problem_id for _, problem_id, review in days if not review]
    assert len(first_showings) == len(set(first_showings)) == 182  # every problem is new exactly once
    for track in ROTATION:  # a track reviews only once nothing of its own is left unseen
        own = [(problem_id, review) for day_track, problem_id, review in days if day_track == track]
        first_review = next(index for index, (_, review) in enumerate(own) if review)
        assert not any(review for _, review in own[:first_review]) and all(review for _, review in own[first_review:])
    new = Counter(track for track, _, review in days if not review)
    # The company tracks reach the problems they share with NeetCode 150 first, so it is NeetCode that skips them.
    assert new == {"neetcode-150": 135, "amd": 17, "vanguard": 30}
