# DailyGrad

DailyGrad is a small, self-hosted daily AI briefing. Once a day it gathers AI news, has a
local model pick and summarise five stories, and adds one short technical lesson from a
built-in curriculum. Everything runs on your own machine through [Ollama](https://ollama.com).

The name is the idea: **one small gradient step every day**. Staying current in AI and
keeping fundamentals sharp both come from short, regular exposure rather than occasional
cramming. A DailyGrad digest takes about two minutes to read.

It is a short batch job, not a service. It runs, writes a few files, unloads the model and
exits.

## What a digest looks like

An excerpt from a real run (the full file is in
[`examples/sample-digest.md`](examples/sample-digest.md)):

> # DailyGrad — 2026-10-07
>
> ## AI News
>
> ### 2. [TRACE: Rollout-Guided Quantization-Aware Training for FP4 Reinforcement Learning of MoE Language Models](https://arxiv.org/abs/2610.07767)
>
> _Hugging Face Daily Papers, 70 upvotes_
>
> **What happened:** Researchers released TRACE, a framework for reinforcement learning on Mixture-of-Experts language models that uses rollout-side quantization results to guide training-side rounding decisions and employs a caching scheme to minimize storage overhead.
>
> **Why it matters:** This approach enables joint FP4 weight/activation and KV-cache rollouts with performance comparable to BF16 while achieving up to 5.4x speedup, addressing the high computation and memory costs of existing low-precision RL methods.
>
> ### 3. [CheckerBench: Can Long-Horizon Agents Synthesize Static-Analysis Checkers?](https://arxiv.org/abs/2610.07557)
>
> _Hugging Face Daily Papers, 52 upvotes_
>
> **What happened:** Researchers released CheckerBench, a benchmark of 300 tasks derived from CVEs across multiple repositories and languages, along with CheckerLab, an evaluation framework to measure checker performance.
>
> **Why it matters:** The results show that current coding agents struggle to reliably synthesize static-analysis checkers from scratch, highlighting a significant gap in their ability to perform complex, multi-step development tasks.
>
> ### 4. [Taming VLAs under Robot Execution Errors: Self-Compensation and Stress Testing](https://arxiv.org/abs/2609.37334)
>
> _Hugging Face Daily Papers, 24 upvotes_
>
> **What happened:** Researchers proposed self-compensating VLA policies that update online using the residual between commanded and executed actions without task rewards, and introduced RoboStress, a simulation benchmark combining friction, backlash, compliance, and gravity models into seven scenarios.
>
> **Why it matters:** This provides a concrete framework for adapting vision-language-action models to real-world mechanical imperfections without requiring labeled task rewards or extensive physical testing.
>
> ### 5. [GPT-6 and Intelligent UI for everyone](https://openai.com/index/gpt-6-for-everyone)
>
> _OpenAI_
>
> ## AI Micro-Lesson
>
> **Tensors, shapes and dimensional reasoning**
>
> A linear layer maps input (..., d_in) to output (..., d_out) by acting only on the last axis while carrying leading axes unchanged. Applying a 768-to-3072 layer to shape (32, 128, 768) produces (32, 128, 3072).

Every third lesson also ends with a **Quick recall** question about an earlier topic.

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
                       └───────────────────────┘   └──────────────────────┘   └──────────────────┘
                         about 2,400 → 18 items       18 → 5 stories            SQLite history
```

1. **Fetch** candidates from every source. A source that fails is skipped and named in the digest.
2. **Filter without the model.** Old items, unpopular items, duplicates and stories already
   shown are removed, and what is left is ranked. Up to 18 candidates go forward, shared
   equally between the three kinds of source so that none can crowd out the others.
3. **Select.** The model chooses the 5 most useful candidates. If it returns fewer, the list
   is topped up from the ranked shortlist, so a digest has exactly 5 stories whenever 5
   candidates exist.
4. **Read.** Only the chosen stories are fetched. Papers use their abstract; other stories
   are downloaded and reduced to their main text with Trafilatura.
5. **Summarise** each story from that text alone: what happened, and why it matters.
6. **Teach.** The next curriculum topic is turned into a two- or three-sentence lesson.
7. **Write** the outputs, record history, and unload the model.

The model is used only where judgement is needed, on a short list, and it never sees more
than one article at a time.

### Sources

| Source | What is taken | Kept if |
|---|---|---|
| Hacker News | Current front-page stories | 50 points or more |
| Hugging Face Daily Papers | Recently featured papers | 5 upvotes or more |
| RSS feeds | OpenAI, Google DeepMind, Google Research and the Hugging Face blog by default | always |

All sources are limited to the last 48 hours. The feeds, thresholds and time window are
configurable.

### How Hacker News stories are ranked

The Hacker News front page covers every topic, so its stories are ranked before they
compete for their share of the shortlist:

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

## Output files

| Output | Content |
|---|---|
| stdout | The digest as Markdown. Logs go to stderr. |
| `data/digests/YYYY-MM-DD.md` | The same digest, kept as an archive. |
| `data/digests/YYYY-MM-DD.json` | The digest as structured data, kept as an archive. |
| `data/latest.md` | The most recent digest. |
| `data/latest.json` | The most recent digest as structured data: the same document as its dated JSON. |
| `data/dailygrad.db` | SQLite history, used to avoid repeats and to track the curriculum. |

The JSON carries a run ID, the run status, the stories with their summaries, the lesson and
the recall question, so another program can use a digest without parsing Markdown or reading
the database. Its layout is specified in [`docs/output.md`](docs/output.md), with a real
example in [`examples/sample-digest.json`](examples/sample-digest.json).

Files are replaced atomically, so a reader never sees a half-written file.

### Exit codes and degraded runs

| Code | Meaning |
|---|---|
| 0 | The digest was produced normally. |
| 1 | Degraded: a model request failed, so a summary or the lesson is missing. A crash also exits with 1. |
| 2 | The configuration is invalid. |

A degraded run still writes every output, and `latest.json` says `"status": "degraded"`.
Nothing is lost: a story the model failed on is not recorded as shown, so a later run can
pick it up, and a failed lesson is retried with the same topic. If Ollama cannot be reached
at all, the digest lists the top candidates as headlines.

A story whose page cannot be fetched is listed as a headline without a summary. That is
not counted as a failure.

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
Latest digest:      /home/you/dailygrad/data/latest.md
Latest JSON:        /home/you/dailygrad/data/latest.json
Ollama endpoint:    http://localhost:11434
Ollama model:       qwen3.5:4b-q4_K_M
Stories per digest: 5, chosen from up to 18 candidates
Sources:            OpenAI, Google DeepMind, Google Research, Hugging Face Blog, Hugging Face Daily Papers, Hacker News
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
`timeout_seconds`. The endpoint can also point at Ollama on another machine through `url`.
DailyGrad has been tested with the default model only.

## Hardware

The default model, `qwen3.5:4b-q4_K_M`, is a 3.3 GB download and uses about 3.4 GB of
memory while loaded. DailyGrad unloads it at the end of every run.

Development and testing were done on an Apple M4 MacBook Air with 24 GB of memory, where a
run takes about a minute, roughly half of it model time. Other hardware has not been
measured. Without a GPU or Apple Silicon expect a slower run, and consider raising
`timeout_seconds`.

## Scheduling

DailyGrad does not schedule itself. Run it from any scheduler, with absolute paths:

```cron
0 7 * * * /home/you/dailygrad/.venv/bin/dailygrad run --config /home/you/dailygrad/dailygrad.toml >/dev/null 2>>/home/you/dailygrad/dailygrad.log
```

[`docs/scheduling.md`](docs/scheduling.md) has complete examples for cron, systemd timers
and macOS launchd. Running more than once a day is safe: stories are not repeated and the
lesson stays the same until the next day.

Other tools can build on the same surface: run `dailygrad run`, check the exit code, and
read stdout, `latest.md` or `latest.json`. Assistant and chat integrations are planned as
separate adapters around these outputs, not as part of DailyGrad itself.

## Privacy

DailyGrad is local-first.

- All model inference happens in your own Ollama. No text is sent to any hosted AI service.
- The only network requests are to the news sources (the Hacker News search API,
  huggingface.co and the configured feeds) and to the pages of the stories chosen for the
  digest.
- There are no accounts, API keys or telemetry.
- History stays in a SQLite file in your data directory.

Web pages are treated as untrusted. Only public `http(s)` addresses are fetched, redirects
are re-checked, downloads and extracted text are capped, and the model is told to treat
article text as data, not instructions. Model output is used only as plain text or as
validated numbers; it cannot run anything.

## Development

```sh
pip install -e ".[dev]"
pytest
```

The tests fake every source, article and model response, so they need no network, Ollama
or GPU. GitHub Actions runs them on Python 3.11, 3.12 and 3.13.

The code is deliberately plain: no agent framework, vector database or web application.
[`PROJECT_SPEC.md`](PROJECT_SPEC.md) describes the design goals.

## Project status

Version 0.1. The standalone tool is complete: news selection and summaries, the
micro-lesson curriculum, and stable output files. It is a personal project, tested by its
author on one machine with one model. Expect rough edges, and note that a 4-billion-parameter
model sometimes writes an imprecise sentence.

Known limits:

- Some sites refuse automated requests (openai.com does), so their stories usually appear
  as headlines without a summary.
- A second run on the same day replaces that day's dated digest.

## Acknowledgements

DailyGrad's pipeline shape (collect, filter deterministically, then let a model select and
summarise) was inspired by [AI Morning Digest](https://github.com/hukunokina/ai-morning-digest).
DailyGrad is an independent implementation, not a fork, and shares no code with it.

It builds on [Ollama](https://ollama.com), [Trafilatura](https://trafilatura.readthedocs.io),
[feedparser](https://feedparser.readthedocs.io) and [Requests](https://requests.readthedocs.io).

## License

[MIT](LICENSE)
