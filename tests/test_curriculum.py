"""The curriculum file, its validation, and the deterministic progression through it."""

from collections import Counter

import pytest

from dailygrad import curriculum
from dailygrad.curriculum import CurriculumError, build_schedule, load_curriculum, next_topic, recall_topic
from dailygrad.models import Topic

# Lesson history in users' databases refers to these IDs. A topic may be added, but an ID in
# this list must never be renamed or removed: doing so fails this test on purpose.
STABLE_IDS = """
nn-tensor-shapes nn-parameter-counting nn-backprop nn-layer-gradients opt-sgd opt-learning-rate
opt-adam loss-softmax loss-cross-entropy train-activations-init train-gradient-flow
train-normalization fit-regularization fit-overfitting fit-metrics
arch-cnn arch-rnn tf-motivation tf-tokens-embeddings tf-qkv tf-scaled-attention tf-masking
tf-multi-head tf-residuals tf-layernorm tf-mlp tf-positions tf-block lm-next-token lm-decoding
inf-kv-cache inf-memory inf-quantization inf-serving inf-parallelism adapt-fine-tuning adapt-lora
adapt-preferences
agent-definition agent-vs-workflow agent-tools agent-react agent-memory agent-context
rag-architecture rag-chunking rag-reranking rag-grounding rag-vs-fine-tuning sys-routing sys-mcp
sys-multi-agent rel-retries rel-long-horizon rel-prompt-injection eval-datasets eval-llm-judge
eval-rag eval-agents eval-observability
""".split()

TOPIC = """
[[topic]]
id = "{id}"
track = "{track}"
series = "{series}"
part = {part}
title = "A title"
points = ["First point.", "Second point.", "Third point."]
question = "{question}"
"""


def topic_toml(id="a-1", track="foundations", series="Series A", part=1, question="Why?"):
    return TOPIC.format(id=id, track=track, series=series, part=part, question=question)


def write(tmp_path, text):
    path = tmp_path / "curriculum.toml"
    path.write_text(text, encoding="utf-8")
    return path


def make_topics(layout):
    """Build topics from {track: [series sizes]}, e.g. {"foundations": [2, 1]}."""
    topics = []
    for track, sizes in layout.items():
        for series_number, size in enumerate(sizes, start=1):
            for part in range(1, size + 1):
                name = f"{track[:2]}{series_number}"
                topics.append(Topic(f"{name}-{part}", track, name, part, f"{name} part {part}", ("a", "b", "c"), f"{name}-{part}?"))
    return topics


def teach(topics, lessons):
    """Run the selector for a number of lessons. Returns the taught IDs and the recall IDs (None when not asked)."""
    schedule, history, recalls, asked = build_schedule(topics), [], [], []
    for _ in range(lessons):
        today = next_topic(schedule, history)
        recall = recall_topic(topics, history, recalls, today)
        asked.append(recall.id if recall else None)
        if recall:
            recalls.append(recall.id)
        history.append(today.id)
    return history, asked


# --- the shipped curriculum


@pytest.fixture(scope="module")
def shipped():
    return load_curriculum()


def test_shipped_curriculum_is_valid_and_the_intended_size(shipped):
    assert 50 <= len(shipped) <= 60
    per_track = Counter(topic.track for topic in shipped)
    assert set(per_track) == set(curriculum.TRACKS)
    # Weighted toward modern material rather than split evenly.
    assert per_track["architectures"] > per_track["foundations"] and per_track["agents"] > per_track["foundations"]


def test_shipped_topic_ids_are_unique_and_stable(shipped):
    ids = [topic.id for topic in shipped]

    assert len(ids) == len(set(ids))
    assert all(curriculum.ID_PATTERN.fullmatch(topic_id) for topic_id in ids)
    assert set(STABLE_IDS) <= set(ids), f"renamed or removed: {sorted(set(STABLE_IDS) - set(ids))}"


def test_shipped_topics_carry_source_material_not_finished_lessons(shipped):
    for topic in shipped:
        assert 3 <= len(topic.points) <= 6, topic.id
        assert all(len(point) > 30 for point in topic.points), topic.id
        assert topic.question.endswith("?") and topic.title, topic.id
    assert sum(bool(topic.formula) for topic in shipped) >= 20


def test_shipped_curriculum_has_multi_day_series(shipped):
    sizes = Counter(topic.series for topic in shipped)

    assert sizes["Transformers"] >= 10 and sizes["RAG"] >= 4 and sizes["Agents"] >= 4
    transformer_titles = [topic.title for topic in shipped if topic.series == "Transformers"]
    assert transformer_titles[0] == "Why transformers replaced recurrence"
    assert transformer_titles[-1] == "The complete transformer block"


# --- parsing and validation


def test_load_parses_every_field(tmp_path):
    path = write(tmp_path, topic_toml() + 'formula = "y = W x"\n')

    assert load_curriculum(path) == [
        Topic("a-1", "foundations", "Series A", 1, "A title", ("First point.", "Second point.", "Third point."), "Why?", "y = W x")
    ]


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "no \\[\\[topic\\]\\] entries"),
        ("[[topic]\nid = 1", "cannot read curriculum"),
        (topic_toml() + topic_toml(part=2), "duplicate topic id a-1"),
        (topic_toml(id="Bad_ID"), "must be lowercase words joined by hyphens"),
        (topic_toml(track="history"), "unknown track history"),
        (topic_toml().replace('title = "A title"\n', ""), "title is missing"),
        (topic_toml().replace("part = 1", 'part = "one"'), "part is missing or is not of type int"),
        (topic_toml() + 'answer = "42"\n', "unknown or invalid field answer"),
        (topic_toml() + "formula = 3\n", "unknown or invalid field formula"),
        (topic_toml().replace(', "Third point."', ""), "points must be 3 to 6"),
        (topic_toml().replace('"Second point."', '"  "'), "points must be 3 to 6 non-empty strings"),
        (topic_toml(question="Explain it."), "question ending in '\\?'"),
        (topic_toml(part=2), "expected part 1"),
        (topic_toml() + topic_toml(id="a-2", part=3), "expected part 2"),
        (
            topic_toml() + topic_toml(id="b-1", series="Series B") + topic_toml(id="a-2", part=2),
            "'Series A' is not listed in one block",
        ),
        (topic_toml() + topic_toml(id="a-2", part=2, track="agents"), "more than one track"),
    ],
)
def test_invalid_curriculum_is_rejected(tmp_path, text, message):
    with pytest.raises(CurriculumError, match=message):
        load_curriculum(write(tmp_path, text))


def test_missing_curriculum_file_is_an_error(tmp_path):
    with pytest.raises(CurriculumError, match="cannot read curriculum"):
        load_curriculum(tmp_path / "missing.toml")


# --- the schedule


def test_schedule_teaches_every_topic_exactly_once(shipped):
    schedule = build_schedule(shipped)

    assert sorted(topic.id for topic in schedule) == sorted(topic.id for topic in shipped)
    assert build_schedule(shipped) == schedule  # deterministic


def test_schedule_keeps_series_and_tracks_in_curriculum_order(shipped):
    schedule = build_schedule(shipped)

    for track in curriculum.TRACKS:
        in_file = [topic.id for topic in shipped if topic.track == track]
        assert [topic.id for topic in schedule if topic.track == track] == in_file
    for series in {topic.series for topic in shipped}:
        parts = [topic.part for topic in schedule if topic.series == series]
        assert parts == list(range(1, len(parts) + 1))


def test_schedule_runs_stay_within_one_series_and_then_switch_track(shipped):
    schedule = build_schedule(shipped)
    runs = [[schedule[0]]]
    for previous, topic in zip(schedule, schedule[1:]):
        if topic.track == previous.track:
            runs[-1].append(topic)
        else:
            runs.append([topic])

    for run in runs:
        assert len(run) <= curriculum.RUN_LENGTH
        assert len({topic.series for topic in run}) == 1
    assert any(len(run) == curriculum.RUN_LENGTH for run in runs)  # subjects do develop over consecutive days


def test_schedule_interleaves_tracks_so_none_goes_missing_for_long(shipped):
    schedule = build_schedule(shipped)
    two_cycles = schedule + schedule  # include the gap across the restart

    for track in curriculum.TRACKS:
        positions = [index for index, topic in enumerate(two_cycles) if topic.track == track]
        longest_gap = max(later - earlier - 1 for earlier, later in zip(positions, positions[1:]))
        assert longest_gap <= 12, f"{track} is absent for {longest_gap} lessons"
    # Every track appears early and is still being taught near the end.
    assert {topic.track for topic in schedule[:8]} == set(curriculum.TRACKS)
    assert {topic.track for topic in schedule[-8:]} == set(curriculum.TRACKS)


def test_schedule_small_example():
    topics = make_topics({"foundations": [2], "architectures": [4], "agents": [1, 1]})

    assert [topic.id for topic in build_schedule(topics)] == [
        "fo1-1", "fo1-2",  # a short series finishes in one run
        "ar1-1", "ar1-2", "ar1-3",  # a long series is cut at RUN_LENGTH
        "ag1-1",  # a run never crosses into the next series
        "ar1-4",
        "ag2-1",
    ]  # fmt: skip


def test_schedule_handles_a_single_track():
    topics = make_topics({"agents": [5]})

    assert [topic.part for topic in build_schedule(topics)] == [1, 2, 3, 4, 5]


# --- choosing the next topic


def test_next_topic_walks_the_schedule_in_order_and_then_starts_again(shipped):
    schedule = build_schedule(shipped)
    expected = [topic.id for topic in schedule]

    history, _ = teach(shipped, 2 * len(schedule) + 3)

    assert history == expected + expected + expected[:3]


def test_next_topic_never_repeats_the_previous_lesson(shipped):
    history, _ = teach(shipped, 3 * len(shipped))

    assert all(today != yesterday for yesterday, today in zip(history, history[1:]))


def test_next_topic_avoids_yesterdays_topic_even_after_the_curriculum_changes():
    topics = make_topics({"foundations": [3]})
    schedule = build_schedule(topics)

    # Every other topic has been taught more often, so "fo1-1" has the fewest lessons, yet it was yesterday's.
    assert next_topic(schedule, ["fo1-2", "fo1-3", "fo1-2", "fo1-3", "fo1-1"]).id != "fo1-1"
    assert next_topic(build_schedule(topics[:1]), ["fo1-1"]).id == "fo1-1"  # unless there is no alternative


def test_next_topic_ignores_history_for_topics_no_longer_in_the_curriculum(shipped):
    schedule = build_schedule(shipped)

    assert next_topic(schedule, ["a-topic-that-was-removed"]) == schedule[0]
    assert next_topic(schedule, [schedule[0].id, "a-topic-that-was-removed"]) == schedule[1]


def test_a_topic_added_later_is_taught_before_the_cycle_repeats():
    topics = make_topics({"foundations": [2]})
    history = ["fo1-1", "fo1-2"]
    extended = topics + make_topics({"agents": [1]})

    assert next_topic(build_schedule(extended), history).id == "ag1-1"


# --- recall questions


def test_recall_is_asked_with_every_third_lesson(shipped):
    _, asked = teach(shipped, 12)

    assert [recall is not None for recall in asked] == [False, False, True] * 4


def test_recall_asks_about_the_oldest_topic_not_yet_asked_about(shipped):
    history, asked = teach(shipped, 12)

    assert [recall for recall in asked if recall] == history[:4]  # lesson 3 asks about lesson 1, lesson 6 about lesson 2...


def test_recall_never_asks_about_todays_or_the_previous_topic(shipped):
    history, asked = teach(shipped, 3 * len(shipped))

    for index, recall in enumerate(asked):
        if recall:
            assert recall not in (history[index], history[index - 1])
            assert recall in history[:index]  # only material already covered


def test_recall_spreads_over_the_curriculum_instead_of_repeating_favourites(shipped):
    _, asked = teach(shipped, 2 * len(shipped))
    questions = [recall for recall in asked if recall]
    assert len(set(questions)) == len(questions) == 40  # two passes: 40 questions, no topic asked twice

    _, asked = teach(shipped, 4 * len(shipped))
    assert {recall for recall in asked if recall} == {topic.id for topic in shipped}  # eventually every topic


def test_recall_prefers_the_least_asked_topic():
    topics = make_topics({"foundations": [3], "agents": [3]})
    history = ["fo1-1", "fo1-2", "fo1-3", "ag1-1", "ag1-2"]
    today = topics[-1]

    assert recall_topic(topics, history, [], today).id == "fo1-1"
    assert recall_topic(topics, history, ["fo1-1"], today).id == "fo1-2"
    assert recall_topic(topics, history, ["fo1-1", "fo1-2", "fo1-3", "ag1-1"], today).id == "fo1-1"


def test_no_recall_when_it_is_not_due_or_nothing_is_old_enough():
    topics = make_topics({"foundations": [3]})

    assert recall_topic(topics, ["fo1-1"], [], topics[1]) is None  # lesson 2: not due
    assert recall_topic(topics, ["fo1-2", "fo1-2"], [], topics[1]) is None  # lesson 3, but only fresh topics
