import pytest

from conftest import NOW
from dailygrad import db
from dailygrad.config import Config
from dailygrad.filtering import build_shortlist, dedupe, interleave, keyword_pattern
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


def test_hackernews_needs_points_and_keyword(conn, make_candidate):
    good = make_candidate("New LLM released", score=50)
    unpopular = make_candidate("Another LLM released", score=49)
    off_topic = make_candidate("Show HN: my sourdough tracker", score=900)

    assert build_shortlist([good, unpopular, off_topic], Config(), conn, NOW) == [good]


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

    shortlist = interleave(hn + papers + posts, size=5)

    assert [c.title for c in shortlist] == ["hn 300", "paper 90", "post 1", "hn 200", "paper 7"]


def test_interleave_fills_from_remaining_sources(make_candidate):
    hn = [make_candidate(f"hn {score}", score=score) for score in (4, 3, 2, 1)]
    post = make_candidate("only post", kind="rss")

    assert len(interleave(hn + [post], size=4)) == 4
    assert len(interleave(hn + [post], size=20)) == 5
