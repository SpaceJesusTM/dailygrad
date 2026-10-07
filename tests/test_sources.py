from datetime import datetime, timezone

import pytest

from dailygrad.config import Feed
from dailygrad.sources import hackernews, huggingface, rss

HN_PAYLOAD = {
    "hits": [
        {
            "objectID": "101",
            "title": "Mistral Large 4",
            "url": "https://mistral.ai/news/mistral-large-4/",
            "points": 1677,
            "num_comments": 1001,
            "created_at_i": 1791292549,
        },
        {"objectID": "102", "title": "Ask HN: Which local LLM do you use?", "url": None, "points": 80, "created_at_i": 1791292000},
        {"objectID": "103", "url": "https://example.com/no-title", "points": 5, "created_at_i": 1791292000},
    ]
}

HF_PAYLOAD = [
    {
        "publishedAt": "2026-10-05T20:00:00.000Z",
        "title": "Towards In-Parameter Memory",
        "paper": {
            "id": "2610.08630",
            "title": "Towards In-Parameter Memory\nAugmentation",
            "summary": "Recently LLMs  need\nlong-term memory.",
            "upvotes": 42,
            "publishedAt": "2026-10-06T00:00:00.000Z",
            "submittedOnDailyAt": "2026-10-07T00:00:00.000Z",
        },
    },
    {"publishedAt": "2026-10-05T20:00:00.000Z", "paper": {"id": "2610.00001", "title": "No featured date", "upvotes": 3}},
    {"publishedAt": "2026-10-05T20:00:00.000Z", "paper": {"title": "No id"}},
]

RSS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Lab Blog</title>
<item>
  <title>Introducing &amp; shipping Model X</title>
  <link>https://lab.example/blog/model-x</link>
  <pubDate>Tue, 06 Oct 2026 15:30:00 GMT</pubDate>
  <description>&lt;p&gt;Model X is &lt;b&gt;faster&lt;/b&gt;.&lt;/p&gt;</description>
</item>
<item>
  <title>Undated post</title>
  <link>https://lab.example/blog/undated</link>
</item>
</channel></rss>"""

ATOM_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Lab Blog</title>
<entry>
  <title>Atom post</title>
  <link href="https://lab.example/atom-post"/>
  <updated>2026-10-06T10:00:00+02:00</updated>
  <summary>Plain summary.</summary>
</entry>
</feed>"""

FEED = Feed("Lab Blog", "https://lab.example/rss.xml")


def test_hackernews_parse():
    story, ask = hackernews.parse(HN_PAYLOAD)  # the hit without a title is skipped

    assert story.kind == "hackernews"
    assert story.title == "Mistral Large 4"
    assert story.url == "https://mistral.ai/news/mistral-large-4/"
    assert story.score == 1677
    assert story.published == datetime.fromtimestamp(1791292549, timezone.utc)
    assert ask.url == "https://news.ycombinator.com/item?id=102"


def test_huggingface_parse():
    papers = huggingface.parse(HF_PAYLOAD)

    assert [p.url for p in papers] == ["https://arxiv.org/abs/2610.08630", "https://arxiv.org/abs/2610.00001"]
    featured, fallback = papers
    assert featured.title == "Towards In-Parameter Memory Augmentation"
    assert featured.summary == "Recently LLMs need long-term memory."
    assert featured.score == 42
    assert featured.published == datetime(2026, 10, 7, tzinfo=timezone.utc)
    assert fallback.published == datetime(2026, 10, 5, 20, tzinfo=timezone.utc)


def test_rss_parse():
    (post,) = rss.parse(FEED, RSS_FEED)  # the undated item is skipped

    assert post.kind == "rss"
    assert post.source == "Lab Blog"
    assert post.title == "Introducing & shipping Model X"
    assert post.url == "https://lab.example/blog/model-x"
    assert post.summary == "Model X is faster ."
    assert post.published == datetime(2026, 10, 6, 15, 30, tzinfo=timezone.utc)
    assert post.score == 0


def test_atom_parse_converts_dates_to_utc():
    (post,) = rss.parse(FEED, ATOM_FEED)

    assert post.url == "https://lab.example/atom-post"
    assert post.published == datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)


def test_unparseable_feed_raises():
    with pytest.raises(ValueError, match="Lab Blog"):
        rss.parse(FEED, b"<html><body>502 Bad Gateway")
