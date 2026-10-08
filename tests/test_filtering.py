from datetime import timedelta

import pytest

from conftest import NOW
from dailygrad import db
from dailygrad.config import Config
from dailygrad.filtering import balance_feeds, build_shortlist, dedupe, hacker_news_score, interleave, keyword_pattern
from dailygrad.models import canonical_url, normalize_title


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/post",
        "http://www.example.com/post/",
        "https://EXAMPLE.com/post?utm_source=hn&utm_medium=social",
        "https://example.com/post#comments",
        "https://example.com/post?ref=newsletter",
    ],
)
def test_canonical_url_ignores_cosmetic_differences(url):
    assert canonical_url(url) == "example.com/post"


def test_canonical_url_keeps_meaningful_query():
    assert canonical_url("https://example.com/watch?v=abc") != canonical_url("https://example.com/watch?v=xyz")


def test_normalize_title():
    assert normalize_title("  GPT-5:  It's Here! ") == normalize_title("gpt 5 it s here")
    assert normalize_title("模型发布") != normalize_title("另一个标题")  # non-Latin titles stay distinct


def test_keyword_pattern_matches_whole_words():
    pattern = keyword_pattern(["AI", "LLM", "machine learning"])

    assert pattern.search("Why AI matters")
    assert pattern.search("Running LLMs locally")
    assert pattern.search("A Machine Learning primer")
    assert not pattern.search("He said the paint was fine")
    assert keyword_pattern([]) is None


def test_recency(conn, make_candidate):
    fresh = make_candidate("Fresh LLM", age_hours=47)
    stale = make_candidate("Stale LLM", age_hours=49)

    assert build_shortlist([fresh, stale], Config(), conn, NOW) == [fresh]


def hn_score(candidate, config=None, keywords=("AI", "LLM")):
    return hacker_news_score(candidate, config or Config(), keyword_pattern(list(keywords)), NOW)


def test_hackernews_needs_points_but_not_a_keyword(conn, make_candidate):
    on_topic = make_candidate("New LLM released", score=50)
    unpopular = make_candidate("Another LLM released", score=49)
    no_keyword = make_candidate("Show HN: a tiny inference engine in Rust", score=60)

    # A title without a keyword is no longer dropped; it just ranks after the keyword match.
    assert build_shortlist([no_keyword, unpopular, on_topic], Config(), conn, NOW) == [on_topic, no_keyword]


def test_hacker_news_score_combines_popularity_freshness_and_keyword_boost(make_candidate):
    plain = make_candidate("Shipping JPEG XL in Chrome", score=200, comments=100, age_hours=0)

    assert hn_score(plain) == 250  # points + comments / 2, with no boost and full freshness
    assert hn_score(make_candidate("Shipping an LLM in Chrome", score=200, comments=100, age_hours=0)) == 250 * 4
    assert hn_score(make_candidate("Shipping JPEG XL in Chrome", score=200, comments=100, age_hours=24)) == 250 * 0.75
    assert hn_score(make_candidate("Shipping JPEG XL in Chrome", score=200, comments=100, age_hours=48)) == 250 * 0.5
    assert hn_score(make_candidate("Shipping JPEG XL in Chrome", score=200, comments=100, age_hours=500)) == 250 * 0.5


def test_keyword_boost_is_configurable_and_needs_keywords(make_candidate):
    story = make_candidate("A new LLM", score=100, age_hours=0)
    config = Config()
    config.hackernews.keyword_boost = 2.0

    assert hn_score(story, config) == 200
    assert hn_score(story, keywords=()) == 100  # an empty keyword list means no boost at all


def test_keyword_stories_outrank_more_popular_generic_ones_up_to_the_boost(conn, make_candidate):
    ai = make_candidate("New LLM released", score=120)
    generic = make_candidate("Visa and Mastercard face new litigation", score=400)
    huge = make_candidate("A very big story about something else", score=900)

    # 120 x 4 = 480: ahead of the 400-point generic story, behind the 900-point one.
    assert build_shortlist([generic, ai, huge], Config(), conn, NOW) == [huge, ai, generic]


def test_weak_generic_stories_do_not_take_shortlist_places_from_ai_stories(conn, make_candidate):
    config = Config()
    ai = [make_candidate(f"LLM paper club {n}", score=100 + n) for n in range(6)]
    generic = [make_candidate(f"Show HN: my sourdough tracker {n}", score=300 + n) for n in range(10)]
    papers = [make_candidate(f"paper {n}", kind="huggingface", score=50 + n) for n in range(10)]
    posts = [make_candidate(f"post {n}", kind="rss", source="Lab", score=0, age_hours=n + 1) for n in range(10)]

    shortlist = build_shortlist(generic + ai + papers + posts, config, conn, NOW)

    # Each kind of source keeps its own places, however many candidates another has. One feed fills only three.
    assert [sum(c.kind == kind for c in shortlist) for kind in ("hackernews", "huggingface", "rss")] == [6, 4, 3]
    # All six Hacker News places go to the keyword stories, although the generic ones have three times the points.
    assert {c.title for c in shortlist if c.kind == "hackernews"} == {c.title for c in ai}


def test_huggingface_needs_upvotes_but_not_keywords(conn, make_candidate):
    good = make_candidate("Sparse attention revisited", kind="huggingface", score=5)
    unpopular = make_candidate("Dense attention revisited", kind="huggingface", score=4)

    assert build_shortlist([good, unpopular], Config(), conn, NOW) == [good]


def test_rss_needs_neither_score_nor_keywords(conn, make_candidate):
    post = make_candidate("Our quarterly update", kind="rss", source="Lab", score=0)

    assert build_shortlist([post], Config(), conn, NOW) == [post]


def test_non_http_urls_are_dropped(conn, make_candidate):
    bad = make_candidate("Sneaky post", kind="rss", url="javascript:alert(1)")

    assert build_shortlist([bad], Config(), conn, NOW) == []


def test_dedupe_by_url_and_title_keeps_first(make_candidate):
    official = make_candidate("Model X released", url="https://lab.example/model-x", kind="rss")
    same_url = make_candidate("Lab ships Model X", url="http://www.lab.example/model-x/?utm_source=hn")
    same_title = make_candidate("Model X: Released!", url="https://mirror.example/model-x")
    other = make_candidate("Something else", url="https://example.com/else")

    assert dedupe([official, same_url, same_title, other]) == [official, other]


def test_previously_shown_items_are_removed(conn, make_candidate):
    shown = make_candidate("Old LLM news", url="https://example.com/old")
    seen_only = make_candidate("Seen but never shown LLM", url="https://example.com/seen")
    with conn:
        db.record_seen(conn, [shown, seen_only], NOW)
        db.record_run(conn, NOW.date(), "digest.md", shown=[shown], now=NOW)

    reposted = make_candidate("Old LLM news", url="https://other.example/repost")
    fresh = make_candidate("Fresh LLM news", url="https://example.com/fresh")

    assert build_shortlist([shown, seen_only, reposted, fresh], Config(), conn, NOW) == [seen_only, fresh]


def test_interleave_takes_turns_and_keeps_each_queue_in_order():
    assert interleave([["a1", "a2", "a3"], ["b1"], ["c1", "c2"]], size=5) == ["a1", "b1", "c1", "a2", "c2"]
    assert interleave([["a1", "a2"], [], ["c1"]], size=20) == ["a1", "c1", "a2"]
    assert interleave([[], [], []], size=5) == []


def test_hacker_news_cannot_dominate_the_shortlist_by_volume(conn, make_candidate):
    hn = [make_candidate(f"LLM story {n}", score=500 + n) for n in range(30)]
    papers = [make_candidate(f"paper {n}", kind="huggingface", score=10) for n in range(3)]
    posts = [make_candidate(f"post {n}", kind="rss", source="Lab", score=0) for n in range(2)]

    shortlist = build_shortlist(hn + papers + posts, Config(), conn, NOW)

    assert all(c in shortlist for c in papers + posts)  # every paper and post is in, despite 30 HN stories
    assert {c.kind for c in shortlist[:3]} == {"hackernews", "huggingface", "rss"}  # and the sources take turns


# --- the shortlist allocation: 15 feed posts (3 a feed), 4 papers, 6 Hacker News stories


def kinds(shortlist):
    return [sum(c.kind == kind for c in shortlist) for kind in ("rss", "huggingface", "hackernews")]


def per_feed(shortlist):
    counts = {}
    for candidate in shortlist:
        if candidate.kind == "rss":
            counts[candidate.source] = counts.get(candidate.source, 0) + 1
    return counts


@pytest.fixture
def make_post(make_candidate):
    def make(feed, age_hours, title=None):
        title = title or f"{feed} post at {age_hours}h"
        return make_candidate(title, kind="rss", source=feed, score=0, age_hours=age_hours)

    return make


@pytest.fixture
def plenty(make_candidate, make_post):
    """More than enough of everything: 9 feeds with 5 posts each, 10 papers and 12 Hacker News stories."""
    posts = [make_post(f"Feed {f}", age_hours=1 + f + 4 * n) for f in range(9) for n in range(5)]
    papers = [make_candidate(f"paper {n}", kind="huggingface", source="Hugging Face Daily Papers", score=10 + n) for n in range(10)]
    stories = [make_candidate(f"LLM story {n}", score=100 + n) for n in range(12)]
    return posts, papers, stories


def test_default_allocation_is_15_feed_posts_4_papers_and_6_hacker_news_stories(conn, plenty):
    posts, papers, stories = plenty

    shortlist = build_shortlist(stories + papers + posts, Config(), conn, NOW)

    assert len(shortlist) == Config().filter.shortlist_size == 25
    assert kinds(shortlist) == [15, 4, 6]
    assert max(per_feed(shortlist).values()) <= 3
    # Ranking within each kind is unchanged: the most upvoted papers and the highest-scoring stories.
    assert [c.title for c in shortlist if c.kind == "huggingface"] == ["paper 9", "paper 8", "paper 7", "paper 6"]
    assert [c.title for c in shortlist if c.kind == "hackernews"] == [f"LLM story {n}" for n in range(11, 5, -1)]
    assert [c.kind for c in shortlist[:3]] == ["rss", "huggingface", "hackernews"]  # the kinds still take turns


def test_one_busy_feed_cannot_fill_the_feed_places(conn, make_post):
    busy = [make_post("NVIDIA Developer Blog", age_hours=n + 1) for n in range(20)]
    quiet = [make_post("Mistral AI News", age_hours=30)]

    shortlist = build_shortlist(busy + quiet, Config(), conn, NOW)

    assert per_feed(shortlist) == {"NVIDIA Developer Blog": 3, "Mistral AI News": 1}
    assert [c.title for c in shortlist] == [
        "NVIDIA Developer Blog post at 1h", "Mistral AI News post at 30h",  # round 1: each feed's newest, newest first
        "NVIDIA Developer Blog post at 2h", "NVIDIA Developer Blog post at 3h",  # rounds 2 and 3
    ]  # fmt: skip


def test_feeds_that_publish_at_different_rates_are_taken_in_rounds(make_post):
    daily = [make_post("Daily", age_hours=age) for age in (2, 10, 20, 26, 40)]
    weekly = [make_post("Weekly", age_hours=5)]
    twice = [make_post("Twice", age_hours=age) for age in (30, 1)]

    balanced = balance_feeds(daily + weekly + twice, per_feed=3)

    assert [(c.source, c.title.split(" at ")[1]) for c in balanced] == [
        ("Twice", "1h"), ("Daily", "2h"), ("Weekly", "5h"),  # every feed's newest post, newest first
        ("Daily", "10h"), ("Twice", "30h"),  # second newest; the older round-one post still came before these
        ("Daily", "20h"),  # third newest
    ]  # fmt: skip


def test_feed_balancing_does_not_depend_on_feed_order_and_breaks_ties_deterministically(make_post):
    posts = [make_post(feed, age_hours=3, title=f"{feed} {n}") for feed in ("Zeta", "Alpha", "Mid") for n in (2, 1)]

    expected = ["Alpha 1", "Mid 1", "Zeta 1", "Alpha 2", "Mid 2", "Zeta 2"]  # same moment: by feed name, then URL
    assert [c.title for c in balance_feeds(posts, per_feed=3)] == expected
    assert [c.title for c in balance_feeds(posts[::-1], per_feed=3)] == expected


def test_fifteen_feed_places_stop_the_rounds_early(conn, make_post):
    posts = [make_post(f"Feed {f}", age_hours=1 + f + 10 * n) for f in range(9) for n in range(3)]  # 27 eligible

    shortlist = build_shortlist(posts, Config(), conn, NOW)

    assert len(shortlist) == 15
    assert sorted(per_feed(shortlist).values()) == [1, 1, 1, 2, 2, 2, 2, 2, 2]  # round 1, then the 6 newest of round 2
    second_posts = [c for c in shortlist if NOW - c.published > timedelta(hours=10)]
    assert {c.source for c in second_posts} == {f"Feed {f}" for f in range(6)}


def test_unused_places_are_not_given_to_another_kind(conn, plenty, make_post):
    posts, papers, stories = plenty

    assert kinds(build_shortlist(stories + papers, Config(), conn, NOW)) == [0, 4, 6]  # no feed posts at all
    assert kinds(build_shortlist(stories + posts[:2], Config(), conn, NOW)) == [2, 0, 6]
    assert kinds(build_shortlist(papers[:1] + posts, Config(), conn, NOW)) == [15, 1, 0]
    assert build_shortlist([], Config(), conn, NOW) == []


def test_ineligible_items_never_fill_places(conn, make_candidate, make_post):
    """Stale, unpopular, duplicate and already shown items are removed before the places are counted."""
    shown = make_post("Feed A", age_hours=1, title="Already shown")
    with conn:
        db.record_seen(conn, [shown], NOW)
        db.record_run(conn, NOW.date(), "digest.md", shown=[shown], now=NOW)
    fresh = [make_post("Feed A", age_hours=age) for age in (2, 3)]
    stale = [make_post("Feed A", age_hours=age) for age in (49, 60)]
    weak_paper = make_candidate("weak paper", kind="huggingface", score=4)
    weak_story = make_candidate("weak LLM story", score=49)
    duplicate = make_candidate("Feed A post at 2h", score=500, url="https://elsewhere.example/copy")

    shortlist = build_shortlist([shown, *fresh, *stale, weak_paper, weak_story, duplicate], Config(), conn, NOW)

    assert shortlist == fresh  # Feed A has a third place free, and nothing ineligible takes it


def test_allocation_limits_are_configurable(conn, plenty):
    posts, papers, stories = plenty
    config = Config()
    config.rss.max_candidates, config.rss.max_per_feed = 4, 1
    config.huggingface.max_candidates = 2
    config.hackernews.max_candidates = 3

    shortlist = build_shortlist(stories + papers + posts, config, conn, NOW)

    assert kinds(shortlist) == [4, 2, 3] and set(per_feed(shortlist).values()) == {1}


def test_a_smaller_shortlist_size_still_caps_the_total(conn, plenty):
    """A config written when the limit was 18 keeps it: the kinds take turns until 18 are chosen."""
    posts, papers, stories = plenty
    config = Config()
    config.filter.shortlist_size = 18

    shortlist = build_shortlist(stories + papers + posts, config, conn, NOW)

    assert len(shortlist) == 18 and kinds(shortlist) == [8, 4, 6]
