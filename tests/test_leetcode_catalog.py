"""The LeetCode catalog: the packaged question bank, its validation, and the pools practice draws from."""

import re
from collections import Counter

import pytest

from dailygrad.config import LEETCODE_TRACKS
from dailygrad.leetcode_catalog import CATEGORIES, DIFFICULTIES, CatalogError, gives_away, load_catalog, spoiler_in

CATALOG = load_catalog()

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
    assert [source.id for source in CATALOG.sources_of(CATALOG.get("climbing-stairs"))] == list(LEETCODE_TRACKS)

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


# --- pools: the selected sources together


@pytest.mark.parametrize("track", LEETCODE_TRACKS)
def test_a_one_source_pool_is_that_sources_list(track):
    assert CATALOG.pool((track,)) == CATALOG.track(track)
    assert len(CATALOG.pool((track,))) == CATALOG.sources[track].problems


def test_a_pool_holds_each_problem_once_however_many_of_its_sources_list_it():
    everything = CATALOG.pool(LEETCODE_TRACKS)
    ids = [problem.id for problem in everything]
    assert len(ids) == len(set(ids)) == len(CATALOG.problems) == 182  # 150 + 17 + 32 listings, 182 problems

    amd_and_neetcode = CATALOG.pool(("amd", "neetcode-150"))
    union = {p.id for p in CATALOG.track("amd")} | {p.id for p in CATALOG.track("neetcode-150")}
    assert {problem.id for problem in amd_and_neetcode} == union
    assert len(amd_and_neetcode) == len(union) < 150 + 17  # the overlap is counted once
    assert CATALOG.pool(("amd", "neetcode-150")) == CATALOG.pool(("neetcode-150", "amd"))  # the selection's order is not the pool's


def test_a_problem_in_a_pool_keeps_every_list_it_is_on():
    two_sum = next(problem for problem in CATALOG.pool(("amd",)) if problem.id == "two-sum")
    assert set(two_sum.tracks) >= {"neetcode-150", "amd"}  # reported by every list, not only the selected one
    assert [source.id for source in CATALOG.sources_of(two_sum)] == list(two_sum.tracks)


def test_a_pool_introduces_easy_problems_first_then_walks_the_topics():
    pool = CATALOG.pool(LEETCODE_TRACKS)
    keys = [(DIFFICULTIES.index(p.difficulty), list(CATEGORIES).index(p.category)) for p in pool]
    assert keys == sorted(keys)
    within = [p.id for p in pool if (p.difficulty, p.category) == ("easy", "arrays-hashing")]
    assert within == [p.id for p in CATALOG.problems if (p.difficulty, p.category) == ("easy", "arrays-hashing")]  # file order
