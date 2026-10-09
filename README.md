# DailyGrad

***AI disclosure:** This project was developed with assistance from **ChatGPT 5.6 Sol** and **Claude Code with Opus 5.5**. AI was used for planning, implementation, review, and documentation; final decisions and validation were human-directed.*

DailyGrad is a small, self-hosted daily AI briefing. Once a day it gathers AI news, has a
local model pick and summarise five stories, adds one short technical lesson from a
built-in curriculum, and sets one LeetCode problem to think through. Everything runs on your
own machine through [Ollama](https://ollama.com).

The name is the idea: **one small gradient step every day**. Staying current in AI, keeping
fundamentals sharp and keeping interview reasoning in shape all come from short, regular
exposure rather than occasional cramming. A DailyGrad digest takes about two minutes to
read, and its exercise five or ten more to think about.

It is a short batch job, not a service. It runs, writes a few files, unloads the model and
exits.

## What a digest looks like

The first two stories, the lesson and the exercise from a real run. The complete digest, with
all five stories, is in [`examples/sample-digest.md`](examples/sample-digest.md).

> # DailyGrad — 2026-10-09
>
> ## AI News
>
> ### 1. [Agent Lightning v1.0: A 3,500-Line Lightweight Agentic RL Framework for Training Agents with Real Harnesses](https://www.microsoft.com/en-us/research/blog/agent-lightning-v1-0-a-3500-line-lightweight-agentic-rl-framework-for-training-agents-with-real-harnesses/)
>
> _Microsoft Research_
>
> **What happened:** Microsoft Research Asia released Agent Lightning v1.0, a 3,500-line framework implementing Harnessed Agentic RL that allows agents to train using their existing deployment harnesses without reimplementing them, featuring native Kubernetes support and a Collocated Async RL architecture.
>
> **Why it matters:** This approach enables data-efficient training of complex coding agents on open-source models by eliminating the cost and behavioral drift associated with rebuilding agent interaction loops specifically for reinforcement learning.
>
> ### 2. [From Traces to Agentic Worlds: Agentic Language World Models for Interactive Environment Simulation](https://arxiv.org/abs/2610.06100)
>
> _Hugging Face Daily Papers, 171 upvotes_
>
> **What happened:** Researchers introduced Trace2Env, a framework that converts historical interaction traces into a reusable environment worldbook containing schemas and behavioral knowledge to simulate environments without executable access.
>
> **Why it matters:** This approach allows task agents to receive more faithful observations and consistent long-horizon interactions in simulations, improving the validity of actions when replayed in real systems.
>
> *Stories 3 to 5 are omitted here.*
>
> ## AI Micro-Lesson
>
> **Tensors, shapes and dimensional reasoning**
>
> A linear layer maps input (..., d\_in) to output (..., d\_out) by acting only on the last axis while carrying leading axes unchanged. Applying a 768-to-3072 layer to shape (32, 128, 768) produces (32, 128, 3072).
>
> ## LeetCode Micro-Lesson
>
> **[Contains Duplicate](https://leetcode.com/problems/contains-duplicate/)**
>
> _Easy · Source: NeetCode 150_
>
> Given an integer array, decide whether any value appears more than once.
>
> **Example:**
>
> - Input: `nums = [1, 2, 3, 1]`
> - Output: `true`
>
> **Constraints:** 1 ≤ n ≤ 10^5
>
> **Think about:**
>
> 1. What data structure would you choose?
> 2. How would your algorithm work at a high level?
> 3. What would its time complexity be?
> 4. What would its space complexity be?
> 5. What edge cases should you consider?
>
> **Hint:** What should you track about the values you've seen so far?
>
> _No implementation required: describe your approach in words._

Every third lesson also ends with a **Quick recall** question about an earlier topic. The
exercise asks for an approach in words, not for code, and its answer is not in the digest you read:
see [The LeetCode micro-lesson](#the-leetcode-micro-lesson).

## Quick start

You need Python 3.11 or newer and Ollama.

1. Install Ollama from <https://ollama.com/download> and make sure it is running.
2. Download the default model (3.3 GB):

   ```sh
   ollama pull qwen3.5:4b-q4_K_M
   ```

3. Install DailyGrad and run it:

   ```sh
   git clone https://github.com/SpaceJesusTM/dailygrad.git
   cd dailygrad
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   dailygrad run
   ```

The digest is printed and saved under `data/`. No configuration is needed.

## How a run works

```
 sources                deterministic filter         local model               outputs
┌──────────────────┐   ┌───────────────────────┐   ┌──────────────────────┐   ┌──────────────────┐
│ Hacker News      │   │ recency, popularity   │   │ pick 5 stories       │   │ stdout           │
│ HF Daily Papers  │──▶│ deduplicate           │──▶│ fetch their articles │──▶│ digests/DATE.*   │
│ RSS feeds        │   │ drop already shown    │   │ summarise each       │   │ latest.md        │
└──────────────────┘   │ rank, balance sources │   │ write the lesson     │   │ latest.json      │
                       │ pick the day's problem│   │ word the hint        │   │ SQLite history   │
                       └───────────────────────┘   └──────────────────────┘   └──────────────────┘
                         about 2,400 → 25 items       25 → 5 stories
```

1. **Fetch** candidates from every enabled source. A source that fails is skipped and named in the digest.
2. **Filter without the model.** Old items, unpopular items, duplicates and stories already
   shown are removed, and what is left is ranked. Up to 25 candidates go forward, each kind
   of source with its own maximum so that none can crowd out the others (see
   [the shortlist](#the-shortlist)).
3. **Select.** The model chooses the 5 most useful candidates. If it returns fewer, the list
   is topped up from the ranked shortlist, so a digest has exactly 5 stories whenever 5
   candidates exist.
4. **Read.** Only the chosen stories are fetched. Papers use their abstract; other stories
   are downloaded and reduced to their main text with Trafilatura.
5. **Summarise** each story from that text alone: what happened, and why it matters.
6. **Teach.** The next curriculum topic is turned into a two- or three-sentence lesson.
7. **Set the exercise.** The day's LeetCode problem comes from a built-in catalog, chosen
   without the model. The model only words its one hint.
8. **Write** the outputs, record history, and unload the model.

The model is used only where judgement is needed, on a short list, and it never sees more
than one article at a time.

### Sources

| Source | What is taken | Kept if |
|---|---|---|
| Hacker News | Current front-page stories | 50 points or more |
| Hugging Face Daily Papers | Recently featured papers | 5 upvotes or more |
| RSS feeds | OpenAI, Google DeepMind, Google Research, Anthropic, Meta AI Research, the NVIDIA Developer Blog, Mistral AI, Microsoft Research and the Hugging Face blog by default | always |

All sources are limited to the last 48 hours. The feeds, thresholds and time window are
configurable. The digest stays at five stories however many sources are on.

Anthropic publishes no feed, so `anthropic-news` reads an unofficial, community-maintained
one. Only its entries that link to anthropic.com over HTTPS are used. The feeds and their
limits are listed in [`docs/sources.md`](docs/sources.md).

### Choosing sources

Every source is on by default. `dailygrad sources` lists them and switches them on or off,
one at a time or by group:

```sh
dailygrad sources                          # list the sources and their status
dailygrad sources disable hugging-face     # a group: the blog and the daily papers
dailygrad sources disable google-research  # one source
dailygrad sources enable hugging-face-daily-papers
dailygrad sources set labs hacker-news     # only these, now and when sources are added
dailygrad sources set all                  # everything on again, the default
```

| Group | Sources |
|---|---|
| `labs` | `openai`, `google-deepmind`, `google-research`, `anthropic-news`, `meta-ai-research`, `nvidia-developer-blog`, `mistral-ai-news`, `microsoft-research` |
| `hugging-face` | `hugging-face-blog`, `hugging-face-daily-papers` |
| `community` | `hacker-news` |

A change applies from the next run; it does not regenerate today's digest. The choice is
saved in `data/source_preferences.json`, which Git ignores, so it survives updates. At
least one source must stay on, and an unknown ID is refused.

A source that a later version adds is on by default. After `set` with a list it is off,
because that selection means "only these"; `set all` returns to the default. If the
preferences file is ever damaged, a run stops with exit code 2 instead of guessing, and
`dailygrad sources set all` repairs it.

A disabled source is simply not fetched. Its publisher is not blocked: with `openai` off,
a Hacker News story linking to openai.com can still appear.

Add `--json` for output another program can read. [`docs/sources.md`](docs/sources.md) has
the details.

### The shortlist

The model chooses the 5 stories from a shortlist of at most 25 candidates:

| Kind of source | At most | Ranked by |
|---|---:|---|
| RSS feeds, all together | 15, and 3 from any one feed | newest first, in rounds |
| Hugging Face Daily Papers | 4 | upvotes |
| Hacker News | 6 | the score below |

The feeds are taken in rounds: every feed's newest eligible post, then every feed's second
newest, then the third, newest first within a round, until 15 are chosen. A feed that posts
many times a day therefore gets three places at most, and a feed with nothing from the last
48 hours gets none.

These are limits, not quotas. A source that is disabled, unavailable or quiet leaves its
places empty: they are never filled with older or already shown stories, and never handed
to another kind of source. On such a day the shortlist is shorter than 25. The limits apply
only to the shortlist; the model is free to pick its 5 from any sources.

The limits are `max_candidates` and `max_per_feed` in the config file:
see [`config.example.toml`](config.example.toml).

### How Hacker News stories are ranked

The Hacker News front page covers every topic, so its stories are ranked before they
compete for their six places in the shortlist:

```
score = (points + comments / 2) × freshness × keyword boost
```

- **Freshness** falls in a straight line from 1.0 for a new story to 0.5 at the 48-hour limit.
- **Keyword boost** is 4 if the title contains one of the configured AI keywords (such as
  "LLM", "transformer" or "Claude") and 1 otherwise.

The keywords are a boost, not a gate. A story without a keyword still competes, and reaches
the shortlist when it is about four times as popular as the keyword stories around it. That
keeps the shortlist mostly about AI without losing a major story whose title happens not to
say so. The model then decides which candidates are worth a place.

## The micro-lesson curriculum

The curriculum is [`src/dailygrad/curriculum.toml`](src/dailygrad/curriculum.toml):
60 topics chosen for AI and ML engineering interviews.

| Track | Topics |
|---|---|
| Neural-network and deep-learning foundations | 15 |
| Modern architectures, LLMs and inference | 23 |
| Agentic AI and production AI systems | 22 |

Each topic holds vetted source material, not a finished lesson: a few core technical
points, an optional formula, and an interview-style question. The model only rewords that
material. It is told not to add facts or strengthen claims, it never chooses the topic,
and lessons are generated at temperature 0.

Which topic comes next is deterministic:

- Topics belong to series, such as the 11-part Transformers series, and a series is always
  taught in order.
- Lessons come in runs of up to three consecutive topics from one series. After each run
  the next comes from a different track, the one that has covered the smallest share of
  its topics.
- The curriculum advances once per calendar day. Running again on the same day shows that
  day's lesson again.
- When every topic has been taught, the cycle starts again.
- Every third lesson also asks a **Quick recall** question about an earlier topic, without
  the answer.

[`docs/CURRICULUM_REVIEW.md`](docs/CURRICULUM_REVIEW.md) is a readable copy of the whole
curriculum, and [`docs/LESSON_OUTPUT_REVIEW.md`](docs/LESSON_OUTPUT_REVIEW.md) shows a
generated lesson for every topic. Both are snapshots taken when the curriculum was
reviewed; the TOML file is the source of truth. Topic IDs are permanent, so add topics
rather than renaming them.

## The LeetCode micro-lesson

Each digest ends with one LeetCode problem as a **conceptual exercise**: enough of the
problem to think it through, five questions (which data structure, what algorithm, what time
and space complexity, which edge cases), and no answer. It is five or ten minutes of
thinking, not coding.

The problems come from [`src/dailygrad/leetcode.toml`](src/dailygrad/leetcode.toml), a
catalog of 182 problems packaged with DailyGrad. A run never contacts LeetCode or any other
site for it.

| Track | Problems | Source |
|---|---:|---|
| NeetCode 150 | 150 | The [NeetCode 150](https://neetcode.io/practice) list |
| AMD | 17 | [Interview Solver](https://interviewsolver.com/interview-questions/amd)'s AMD page |
| Vanguard | 32 | [Interview Solver](https://interviewsolver.com/interview-questions/vanguard)'s Vanguard page |

Seventeen listings overlap, so the three lists hold 182 different problems. A problem on
several lists is one catalog entry that belongs to each of those tracks. The counts are what
the lists held on the snapshot date, 2026-10-09.

The company lists are a third party's tags, and a digest credits them as such: "AMD
(Interview Solver tag)". They are not LeetCode's own company tags, and Interview Solver's
frequency figures are not kept, because they are not the chance of meeting a problem in an
interview.

Which problem a day gets is deterministic:

- The tracks take turns, one a day: NeetCode 150, AMD, Vanguard, and round again. The turn
  moves on with each exercise shown, so a day without a run does not skip a track.
- Each track goes through its own problems: the easy ones first, then medium, then hard, and
  within each difficulty topic by topic, from arrays and hashing to bit manipulation.
- A problem that another track has already shown is passed over while the track has new ones.
- When a track has nothing new left, its day shows a review instead of being dropped: the
  problem shown least often, with those you marked `needs-review` first. Nothing is deleted
  to make that possible.
- Running again on the same day shows that day's exercise again.

The statement, the example and the constraints are printed from the catalog as written, so
the model cannot change the question. The topic is not shown, because naming it names the
technique.

### Hints

A digest shows one gentle hint. To stop that, or to start it again:

```sh
dailygrad leetcode hints off
dailygrad leetcode hints on
```

Hints are on until you switch them off. The choice is saved in
`data/leetcode_preferences.json`, which Git ignores, so it survives updates. A change
applies from the next digest and the next reply. It does not choose a new problem, and a
digest already posted somewhere stays as it was.

The model words the hint from the catalog's own first hint and is shown nothing of the
answer. What it writes is still checked: a hint that contains one of the problem's spoiler
words, states a complexity or includes code is discarded for the catalog's hint. So is a
hint when Ollama cannot be reached. `model_hints = false` under `[leetcode]` in the config
file prints the catalog's hint every time.

### Following up

```sh
dailygrad leetcode                    # the current exercise, the rotation and your progress
dailygrad leetcode hint               # the next hint, a step firmer than the last
dailygrad leetcode answer             # feedback on your approach, read from standard input
dailygrad leetcode review             # the reference approach and its complexity
dailygrad leetcode mark comfortable   # or: attempted, needs-review, solved, clear
```

`answer` hands your approach to the local model together with the catalog's reference
solution, which is the authority on what is right. The reply says what is right and wrong
in the approach, corrects a complexity estimate, names edge cases you missed and asks at
most one follow-up question:

```sh
echo "I would compare every pair with two loops. O(n) time, O(1) space." | dailygrad leetcode answer
```

```
Your approach of comparing every pair works logically but is inefficient for large inputs.
You incorrectly estimated the time complexity; nested loops actually run in O(n^2) time.
... How would you modify your approach to avoid checking every pair?

(Contains Duplicate: assessed as partly. This is recorded as an attempt, not as solved.)
```

It does not write code, and it does not name the approach to someone who has not found it:
a reply that would is replaced by a fixed sentence. `review` is the deliberate way to see
the answer.

Being shown a problem, attempting it, feeling comfortable with it and having solved it in
code are four separate things. A showing is recorded by the run, an attempt by an answer
that describes an approach. `comfortable`, `needs-review` and `solved` are only ever set by
`dailygrad leetcode mark`.

Every command takes `--json` for another program, and `hint`, `answer`, `review` and `mark`
take `--problem ID` to follow up on an earlier exercise. None of them chooses a problem,
moves the rotation or writes a digest.
After a reply the model stays loaded for five minutes, so that a follow-up is quick, and
Ollama then frees it; `keep_alive_seconds = 0` frees it at once.
[`docs/leetcode.md`](docs/leetcode.md) has the catalog, the JSON of each command and what an
assistant needs to relay answers.

## Output files

| Output | Content |
|---|---|
| stdout | The digest as Markdown. Logs go to stderr. |
| `data/digests/runs/YYYY-MM-DD/run-ID-TIME.md` and `.json` | This run's digest, archived once and never replaced. |
| `data/digests/YYYY-MM-DD.md` | The same digest: the day's last run. |
| `data/digests/YYYY-MM-DD.json` | The digest as structured data: the day's last run. |
| `data/latest.md` | The most recent digest. |
| `data/latest.json` | The most recent digest as structured data: the same document as its dated JSON. |
| `data/dailygrad.db` | SQLite history, used to avoid repeats and to track the curriculum. |
| `data/source_preferences.json` | Which sources are switched off. Written by `dailygrad sources`, not by a run. |
| `data/leetcode_preferences.json` | Whether digests show a hint. Written by `dailygrad leetcode hints`, not by a run. |

The JSON carries a run ID, the run status, the stories with their summaries, the sources
the run used, the lesson, the recall question and the LeetCode exercise, so another program can use a digest without parsing Markdown or reading
the database. For a program that tutors on the exercise it also carries the catalog's reference answer, as `leetcode.reference_solution`, which the Markdown never shows. Its layout is specified in [`docs/output.md`](docs/output.md), with a real
example in [`examples/sample-digest.json`](examples/sample-digest.json).

Files are replaced atomically, so a reader never sees a half-written file.

### Exit codes and degraded runs

| Code | Meaning |
|---|---|
| 0 | The digest was produced normally. |
| 1 | Degraded: a model request failed, so a summary or the lesson is missing, or the LeetCode exercise could not be prepared. A crash also exits with 1. |
| 2 | The configuration or the source preferences file is invalid. Nothing is fetched or written. |

A degraded run still writes every output, and `latest.json` says `"status": "degraded"`.
Nothing is lost: a story the model failed on is not recorded as shown, so a later run can
pick it up, and a failed lesson is retried with the same topic. If Ollama cannot be reached
at all, the digest lists the top candidates as headlines. The LeetCode exercise appears
either way, with the catalog's own hint, and that alone does not make a run degraded.

A story whose page cannot be fetched is listed as a headline without a summary. That is
not counted as a failure.

### Resetting story memory

DailyGrad never shows a story twice. To start that memory afresh, for example after test
runs used up the current news:

```sh
dailygrad reset-story-memory             # preview: how many stories would be freed; changes nothing
dailygrad reset-story-memory --confirm   # do it
```

After a reset, stories shown earlier can be chosen again if a source still offers them.
From the next run on, duplicate prevention works as before: a story shown after the reset
is not repeated.

Nothing is deleted. Every run, archived digest, summary and lesson is kept, and the
curriculum carries on where it is. The reset is one new row in the database marking where
the fresh memory starts; a story shown again keeps its original record and gains a second
one. It never happens by itself, and it does not generate a digest.

### When Ollama is slow or fails

A model request that times out, loses its connection, or gets HTTP 500, 502, 503 or 504
from Ollama is tried once more after two seconds. That includes the first request, which
chooses the stories, so one bad start no longer costs every summary. Errors that a retry
cannot fix, such as a missing model, are not retried. A run makes at most three retries.

A run also has a time budget, `run_budget_seconds`, 450 by default and counted from the
start of the run. No model request may outlast it, and once it is spent the model is not
asked again: the run finishes as a degraded digest with whatever it has. A run therefore
ends within about a minute of the budget even if Ollama hangs on every request. With the
defaults that is under nine minutes.

## Configuration

DailyGrad works with no config file. To change something, copy
[`config.example.toml`](config.example.toml) to `dailygrad.toml` and edit it. The file is
looked up in this order:

1. `dailygrad run --config PATH`
2. the `DAILYGRAD_CONFIG` environment variable
3. `./dailygrad.toml`

A short example:

```toml
data_dir = "/home/you/dailygrad-data"
final_story_count = 5

[ollama]
url = "http://localhost:11434"
model = "qwen3.5:4b-q4_K_M"

[hackernews]
min_points = 100

[[rss.feeds]]
name = "My favourite lab"
url = "https://lab.example/feed.xml"
```

To see the settings in effect and where every file will be written:

```sh
dailygrad config
```

```
Config file:        none (built-in defaults)
Database:           /home/you/dailygrad/data/dailygrad.db
Dated digests:      /home/you/dailygrad/data/digests/YYYY-MM-DD.md and .json
Run archives:       /home/you/dailygrad/data/digests/runs/YYYY-MM-DD/run-ID-TIME.md and .json
Latest digest:      /home/you/dailygrad/data/latest.md
Latest JSON:        /home/you/dailygrad/data/latest.json
Ollama endpoint:    http://localhost:11434
Ollama model:       qwen3.5:4b-q4_K_M
Stories per digest: 5, chosen from up to 25 candidates
Sources:            OpenAI, Google DeepMind, Google Research, Anthropic News, Meta AI Research, NVIDIA Developer Blog, Mistral AI News, Microsoft Research, Hugging Face Blog, Hugging Face Daily Papers, Hacker News
Source preferences: /home/you/dailygrad/data/source_preferences.json
LeetCode:           one exercise a day, rotating neetcode-150 -> amd -> vanguard; hints on
LeetCode settings:  /home/you/dailygrad/data/leetcode_preferences.json
```

`Sources` lists the sources that are switched on.

The LeetCode exercise has its own section, `[leetcode]`. To leave it out of the digest, or to
change which tracks take turns:

```toml
[leetcode]
enabled = true
rotation = ["neetcode-150", "amd", "vanguard"]
```

`dailygrad.toml` and `data/` are ignored by Git.

### Using another model

Any Ollama model that supports structured (JSON schema) output should work with no code
change:

```sh
ollama pull <model>
```

```toml
[ollama]
model = "<model>"
```

Larger models write better summaries and are slower. If requests time out, raise
`timeout_seconds`, and `run_budget_seconds` with it. The endpoint can also point at Ollama on another machine through `url`.
DailyGrad has been tested with the default model only.

## Hardware

The default model, `qwen3.5:4b-q4_K_M`, is a 3.3 GB download and uses about 3.4 GB of
memory while loaded. DailyGrad unloads it at the end of every run.

Development and testing were done on an Apple M4 MacBook Air with 24 GB of memory, where a
run takes about a minute, roughly half of it model time. The exercise adds one short model
request to a run, for the hint. Other hardware has not been
measured. Without a GPU or Apple Silicon expect a slower run, and consider raising
`timeout_seconds`.

## Scheduling

DailyGrad does not schedule itself. Run it from any scheduler, with absolute paths:

```cron
0 7 * * * /home/you/dailygrad/.venv/bin/dailygrad run --config /home/you/dailygrad/dailygrad.toml >/dev/null 2>>/home/you/dailygrad/dailygrad.log
```

[`docs/scheduling.md`](docs/scheduling.md) has complete examples for cron, systemd timers
and macOS launchd. Running more than once a day is safe: stories are not repeated, and the
lesson and the exercise stay the same until the next day.

Other tools can build on the same surface: run `dailygrad run`, check the exit code, and
read stdout, `latest.md` or `latest.json`. To follow up on the exercise they call
`dailygrad leetcode ... --json`, passing an answer on standard input. Assistant and chat
integrations are separate adapters around these outputs, not part of DailyGrad itself.

## Privacy

DailyGrad is local-first.

- All model inference happens in your own Ollama. No text is sent to any hosted AI service.
- The only network requests are to the news sources (the Hacker News search API,
  huggingface.co and the configured feeds) and to the pages of the stories chosen for the
  digest.
- There are no accounts, API keys or telemetry.
- History stays in a SQLite file in your data directory.
- The LeetCode exercise needs no network at all: the problems are packaged with DailyGrad.
  An answer you send for feedback goes to your own Ollama and into that SQLite file, and
  nowhere else.

Web pages are treated as untrusted. Only public `http(s)` addresses are fetched, redirects
are re-checked, downloads and extracted text are capped, and the model is told to treat
article text as data, not instructions. An answer sent for feedback is treated the same way:
read from standard input, capped, and handed to the model as data. Model output is used only
as plain text or as validated numbers; it cannot run anything.

## Development

```sh
pip install -e ".[dev]"
pytest
```

The tests fake every source, article and model response, so they need no network, Ollama
or GPU. GitHub Actions runs them on Python 3.11, 3.12 and 3.13.

To add a built-in RSS feed, add a `Feed` to `DEFAULT_FEEDS` in `src/dailygrad/config.py`,
its ID and group to `SOURCE_GROUPS` in `src/dailygrad/sources/__init__.py`, and the same
entry to `config.example.toml`; then update the tables in `docs/sources.md`.
[`docs/sources.md`](docs/sources.md#adding-a-built-in-feed) has the checks to make first.

To add or correct a LeetCode problem, edit `src/dailygrad/leetcode.toml`. The loader refuses
an entry whose statement or first hint contains one of its own spoiler words, and the tests
check the counts of every source. [`docs/leetcode.md`](docs/leetcode.md#refreshing-the-snapshot)
describes how the snapshot was made.

The code is deliberately plain: no agent framework, vector database or web application.
[`PROJECT_SPEC.md`](PROJECT_SPEC.md) describes the design goals.

## Project status

Version 0.2. The standalone tool is complete: news selection and summaries, the
micro-lesson curriculum, the LeetCode exercise with its hints and feedback, and stable
output files. It is a personal project, tested by its
author on one machine with one model. Expect rough edges, and note that a 4-billion-parameter
model sometimes writes an imprecise sentence.

Known limits:

- Some sites refuse automated requests (openai.com does), so their stories usually appear
  as headlines without a summary.
- A second run on the same day replaces that day's dated digest. Every run's own digest
  stays in `data/digests/runs/`: `dailygrad history` lists them and `dailygrad history show
  RUN_ID` prints one. Runs made before this existed are kept only if their files were still
  on disk (`dailygrad history backfill`).
- Feedback on an answer comes from the same small model. It is given the reference solution
  and judges against it, but it can still misjudge an unusual approach: treat it as a study
  partner, not a grader. It never writes code.
- The company lists are short, 17 and 32 problems, so their days turn to reviews after a few
  weeks, while NeetCode 150 lasts over a year.

## Acknowledgements

DailyGrad's pipeline shape (collect, filter deterministically, then let a model select and
summarise) was inspired by [AI Morning Digest](https://github.com/hukunokina/ai-morning-digest).
DailyGrad is an independent implementation, not a fork, and shares no code with it.

It builds on [Ollama](https://ollama.com), [Trafilatura](https://trafilatura.readthedocs.io),
[feedparser](https://feedparser.readthedocs.io) and [Requests](https://requests.readthedocs.io).

The LeetCode catalog follows the [NeetCode 150](https://neetcode.io/practice) problem list,
read from [richard7ao/neetcode-150](https://github.com/richard7ao/neetcode-150) (Apache 2.0),
and the AMD and Vanguard pages of [Interview Solver](https://interviewsolver.com). Only
which problems are listed was taken from them. The statements, examples, hints and reference
notes were written for DailyGrad, and the problems themselves are LeetCode's: each exercise
links to the original.

## License

[MIT](LICENSE)
