import pytest

from conftest import NOW
from dailygrad import db
from dailygrad.config import Config
from dailygrad.filtering import build_shortlist, dedupe, hacker_news_score, interleave, keyword_pattern
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

    assert len(shortlist) == config.filter.shortlist_size == 18
    # Each source keeps a third of the shortlist, however many candidates it has.
    assert [sum(c.kind == kind for c in shortlist) for kind in ("hackernews", "huggingface", "rss")] == [6, 6, 6]
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


def test_interleave_balances_sources_and_ranks_within_each(make_candidate):
    hn = [make_candidate(f"hn {score}", score=score) for score in (10, 300, 200)]
    papers = [make_candidate(f"paper {score}", kind="huggingface", score=score) for score in (7, 90)]
    posts = [make_candidate(f"post {age}", kind="rss", score=0, age_hours=age) for age in (5, 1)]

    shortlist = interleave(hn + papers + posts, size=5, rank=lambda c: c.score)

    assert [c.title for c in shortlist] == ["hn 300", "paper 90", "post 1", "hn 200", "paper 7"]


def test_interleave_fills_from_remaining_sources(make_candidate):
    hn = [make_candidate(f"hn {score}", score=score) for score in (4, 3, 2, 1)]
    post = make_candidate("only post", kind="rss")

    assert len(interleave(hn + [post], size=4, rank=lambda c: c.score)) == 4
    assert len(interleave(hn + [post], size=20, rank=lambda c: c.score)) == 5


def test_hacker_news_cannot_dominate_the_shortlist_by_volume(conn, make_candidate):
    hn = [make_candidate(f"LLM story {n}", score=500 + n) for n in range(30)]
    papers = [make_candidate(f"paper {n}", kind="huggingface", score=10) for n in range(3)]
    posts = [make_candidate(f"post {n}", kind="rss", source="Lab", score=0) for n in range(2)]

    shortlist = build_shortlist(hn + papers + posts, Config(), conn, NOW)

    assert all(c in shortlist for c in papers + posts)  # every paper and post is in, despite 30 HN stories
    assert {c.kind for c in shortlist[:3]} == {"hackernews", "huggingface", "rss"}  # and the sources take turns
