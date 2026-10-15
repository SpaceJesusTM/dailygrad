# Output contract

DailyGrad's public interface is the `dailygrad run` command, its exit code, its standard
output, and the files it writes. An integration needs nothing else: it never has to read
the SQLite database.

`dailygrad sources`, which chooses the news sources, has its own JSON output and exit
codes. They are described in [sources.md](sources.md).

`dailygrad history` lists and prints the archived digest of every run. It is described
under [Run archives](#run-archives).

`dailygrad repair` completes a degraded digest as a new revision of its run. It is described
under [Repaired revisions](#repaired-revisions).

`dailygrad leetcode` follows up on the digest's LeetCode exercise: hints, feedback on an
answer, the reference approach. Its JSON output and exit codes are described in
[leetcode.md](leetcode.md).

## What a run produces

| Output | Where | Content |
|---|---|---|
| Standard output | stdout | The digest as Markdown. Log messages go to stderr. |
| Run archive | `<data_dir>/digests/runs/YYYY-MM-DD/run-ID-TIME.md` | The same Markdown, kept for this run and never replaced. |
| Run archive data | `<data_dir>/digests/runs/YYYY-MM-DD/run-ID-TIME.json` | The digest as structured data, kept for this run and never replaced. |
| Dated digest | `<data_dir>/digests/YYYY-MM-DD.md` | The same Markdown: the day's last run. |
| Dated data | `<data_dir>/digests/YYYY-MM-DD.json` | The digest as structured data: the day's last run. |
| Latest digest | `<data_dir>/latest.md` | The same Markdown, always the most recent run. |
| Latest data | `<data_dir>/latest.json` | The same JSON document as that run's dated JSON file, byte for byte. |

A run reads `<data_dir>/source_preferences.json` if it exists, and never writes it. If the
file exists but is invalid, the run stops with exit code 2: see [sources.md](sources.md).

A run also reads `<data_dir>/leetcode_preferences.json` if it exists, and never writes it.
It says whether the exercise shows a hint. If that file is invalid the run goes ahead and
shows no hint: see [leetcode.md](leetcode.md#hints).

`data_dir` is `data` by default. `dailygrad config` prints the absolute paths in use.

All six files are written whenever a run produces a digest, including a degraded run.
They are not written when a run crashes or the configuration or source preferences are invalid; the files from
earlier runs are then left untouched.

Each file is written to a temporary file in the same directory and then moved into place,
so a reader never sees a partly written file. The run archive is written first and
`latest.json` last, so the run that `latest.json` names always has its archive.

The date in the file name and in `date` is the local calendar date of the run. A second
run on the same day replaces that day's dated Markdown and JSON, so the dated files hold
the last run of each day. The run archives hold every run.

## Run archives

Every run that writes a digest also archives it, in files of its own:

```
<data_dir>/digests/runs/2026-10-08/run-2-20261008T124012Z.json
<data_dir>/digests/runs/2026-10-08/run-2-20261008T124012Z.md
<data_dir>/digests/runs/2026-10-08/run-3-20261008T190507Z.json
<data_dir>/digests/runs/2026-10-08/run-3-20261008T190507Z.md
```

The directory is the digest's `date`. The file name is `run-`, the `run_id`, and
`generated_at` in UTC written `YYYYMMDDTHHMMSSZ`. The JSON file is the document that was
`latest.json` right after that run, byte for byte, and the Markdown is what was `latest.md`.

- **An archive is created once and never written again.** A later run, on the same day or
  any other, adds its own files and leaves the earlier ones alone. If a file of that name
  already exists with other content, DailyGrad refuses to replace it.
- **The name is the run's identity.** `run_id` starts again at 1 if the database is deleted,
  so the name also carries `generated_at`: two different runs never share a name. A consumer
  should identify a run by `run_id` and `generated_at` together, and may check that a file's
  name matches the document inside it.
- **A run that is not recorded has no archive.** If writing the outputs fails, the run is
  rolled back and its archive is removed again.
- The Markdown file is written before the JSON file, so a JSON archive means the pair is
  complete. An archive made by a backfill can lack the Markdown file (see below).

### Listing and reading archived runs

```sh
dailygrad history                      # every archived run, oldest first
dailygrad history --date 2026-10-08    # the runs of one day
dailygrad history --json               # the same, as JSON
dailygrad history show 2               # run 2's JSON document, exactly as archived
dailygrad history show 2 --markdown    # its Markdown digest
dailygrad history show 2 --date 2026-10-08
```

`dailygrad history --json` prints:

```json
{
  "ok": true,
  "runs": [
    {
      "run_id": 2,
      "date": "2026-10-08",
      "generated_at": "2026-10-08T12:40:12+00:00",
      "status": "ok",
      "story_count": 5,
      "has_lesson": true,
      "json": "/home/you/dailygrad/data/digests/runs/2026-10-08/run-2-20261008T124012Z.json",
      "markdown": "/home/you/dailygrad/data/digests/runs/2026-10-08/run-2-20261008T124012Z.md"
    }
  ],
  "not_archived": [
    {"run_id": 1, "date": "2026-10-07", "recorded_at": "2026-10-07T12:31:02.118394+00:00"}
  ]
}
```

`runs` is read from the archive files, oldest first; a file whose name does not match the
run inside it is left out, with a warning on stderr. `markdown` is `null` for an archive
without a Markdown file. `not_archived` lists runs that the database records but that have
no archive: their digests were replaced by a later run before archives existed, and cannot
be listed or shown. Listing only reads; it creates no file and does not change the database.

`history` exits with 0 on success, with 2 if the request is refused, and with 1 if a file
could not be read. With `--json`, a refusal prints `{"ok": false, "error": {"code": …,
"message": …}}`. The codes are `not_found` (no archived run with that ID), `ambiguous_run`
(the ID was used twice, after a database reset; the message names the files), `no_markdown`,
`bad_date` and `invalid_config`.

### Digests written before archives existed

Earlier versions kept only the last run of each day. What is still on disk can be archived:

```sh
dailygrad history backfill
```

This archives `latest.json` and each `digests/YYYY-MM-DD.json` that has no archive yet,
byte for byte, with its Markdown file when that is the same digest. It changes no existing
file and can be repeated. A run whose files were already replaced by a later run is gone:
nothing is reconstructed for it, and it stays in `not_archived`.

A run does the same for `latest.json` before replacing it, so the first run after an
upgrade preserves the digest it follows without anyone running the backfill.

## Repaired revisions

`dailygrad repair --run ID [--date YYYY-MM-DD]` completes a degraded run's digest. It keeps
that digest's stories (the same `id`, `title`, `source` and `url`, in the same order) and
every summary that succeeded, and asks the model again only for each story with
`model_failed` true and, if `lesson` is `null`, for the lesson. It selects no story and
fetches no shortlist: only those stories' pages, and for a story whose page gives no text,
its own source once, to find that story's description again. `leetcode`, `sources` and
`failed_sources` are copied unchanged. An exercise that could not be prepared is not
repaired.

The run's archive is never written again. The repaired digest is a new **revision** of the
same run, archived beside it, created once and never replaced:

```
<data_dir>/digests/repairs/2026-10-14/run-11-20261014T123000Z-r1.json
<data_dir>/digests/repairs/2026-10-14/run-11-20261014T123000Z-r1.md
```

The name is the run's archive name with `-r` and the revision number. The run's own digest
is revision 0. A repair starts from the newest revision, so a second repair retries only
what is still missing.

A revision is a document of the same layout, with the same `run_id`, `date` and
`generated_at`: it is the same digest, completed, and **not a new run**. A consumer that
compares `run_id` (and `generated_at`) with the last digest it handled sees no new digest.
To tell a revision apart, read `repair`:

| Key | Type | Meaning |
|---|---|---|
| `repair` | object or `null` | `null` in a run's own digest. In a repaired revision: |
| `repair.revision` | integer | 1 for the first repair, then 2, and so on. |
| `repair.repaired_at` | string | When the repair was made, ISO 8601 in UTC. |
| `repair.model` | string | The model the repair used. |
| `repair.original_status` | string | The run's own `status`, usually `"degraded"`. |
| `repair.previous_revision` | integer | The revision this one completed: 0 for the run's own digest. |
| `repair.repaired` | object | What this repair filled in: `stories` (their 1-based numbers) and `lesson` (boolean). |
| `repair.remaining` | object | What is still missing: `stories` (numbers), `lesson` and `leetcode` (booleans). |

`status` is recomputed: `"ok"` once nothing is missing. A repaired story has its summary and
`model_failed` false, exactly as if the model had not failed; `lesson` and `recall` are
filled in the same way. The Markdown is the run's own, with only the failure notes of the
repaired parts replaced by what a run would have written there.

The dated and latest files are replaced by the revision, Markdown first, only while they
hold that run (the same `run_id`, `date` and `generated_at`). A later run's files are left
alone. A run's `preserve_latest` and `history backfill` recognise a revision there as
already archived.

The database is changed as the run would have changed it: a repaired story is recorded as
shown by that run, with its summary, unless a later run has shown it since; a repaired
lesson is recorded for the run, which moves the curriculum on by that one lesson. If another
run that day gave a lesson, that lesson is used and nothing is recorded. If a run after it
has given a lesson, none is generated (`lesson_note` `"curriculum_moved_on"`). No run is
recorded, and story memory, source preferences and the LeetCode exercise are not touched.

`dailygrad history --json` gives each run a `repairs` list (with `revision` and
`repaired_at` added to the usual keys), and `dailygrad history show ID --revision N` prints
one. `history show ID` without it prints the run's own digest, as before.

### The repair command

`dailygrad repair --run ID [--date YYYY-MM-DD] [--dry-run] [--json]`. With `--json` it prints:

```json
{
  "ok": true,
  "outcome": "repaired",
  "run_id": 11,
  "date": "2026-10-14",
  "generated_at": "2026-10-14T12:30:00+00:00",
  "previous_revision": 0,
  "revision": 1,
  "written": true,
  "status": "ok",
  "attempted": {"stories": [2, 4, 5], "lesson": true},
  "repaired": {"stories": [2, 4, 5], "lesson": true},
  "remaining": {"stories": [], "lesson": false, "leetcode": false},
  "lesson_note": null,
  "current_files": ["dated", "latest"],
  "json": "/home/you/dailygrad/data/digests/repairs/2026-10-14/run-11-20261014T123000Z-r1.json",
  "markdown": "/home/you/dailygrad/data/digests/repairs/2026-10-14/run-11-20261014T123000Z-r1.md"
}
```

| `outcome` | Meaning | Written |
|---|---|---|
| `repaired` | Everything that was missing is filled in; `status` is `"ok"`. | A new revision |
| `partial` | Some of it is filled in; `remaining` says what is not. | A new revision |
| `unchanged` | The model failed again, or no page text could be found. | Nothing |
| `nothing_to_repair` | No story is marked failed and the lesson is there. | Nothing |
| `dry_run` | `attempted` is what a repair would retry. | Nothing |

`revision`, `status`, `json` and `markdown` describe the newest revision after the command.
`current_files` lists the files the revision replaced. If those could not be written, the
revision is still archived and recorded, and `current_files_error` says why.

It exits with 0 when the newest revision's `status` is `"ok"`, with 1 while it is still
degraded (whether or not this repair wrote anything) or a file or database error stopped it,
and with 2 if refused: `not_found`, `ambiguous_run`, `bad_date`, `bad_run_id`, `no_markdown`
(an archive without its Markdown), `markdown_mismatch` (its Markdown is not DailyGrad's
rendering of it), `invalid_digest`, `concurrent_repair` (another repair wrote a revision
meanwhile; nothing was written), `archive_conflict` and `invalid_config`. A refusal with
`--json` prints `{"ok": false, "error": {"code": …, "message": …}}`. Nothing is written
before the model work is done. The revision's archive and its database changes are then
written in one transaction, so an interrupted repair leaves neither behind. The dated and
latest files are replaced while that transaction still holds the database's write lock, so
a run that finishes at the same moment cannot have its files overwritten.

## Exit codes

| Code | Meaning | Files written |
|---|---|---|
| 0 | The digest was produced normally. `status` is `"ok"`. | Yes |
| 1 | Degraded: at least one model request failed, so a summary or the lesson is missing, or the LeetCode exercise could not be prepared. `status` is `"degraded"`. A crash also exits with 1, with a Python traceback on stderr and nothing printed on stdout. | Yes if degraded, no if crashed |
| 2 | The configuration is invalid, the source preferences file exists but cannot be understood, or the command line could not be parsed. Nothing is fetched. | No |

## The JSON document

`latest.json` and the dated JSON files share one layout. Each is UTF-8 JSON, indented by two
spaces. Every key listed below is always present.
A value that does not exist is `null`, never an empty string and never a missing key.
Text fields hold plain text, without Markdown escaping.

```json
{
  "schema_version": 1,
  "run_id": 42,
  "date": "2026-10-07",
  "generated_at": "2026-10-07T21:40:12+00:00",
  "status": "ok",
  "model": "qwen3.5:4b-q4_K_M",
  "stories": [
    {
      "id": "arxiv.org/abs/2610.07767",
      "title": "…",
      "source": "Hugging Face Daily Papers",
      "url": "https://arxiv.org/abs/2610.07767",
      "what_happened": "…",
      "why_it_matters": "…",
      "evidence": "abstract",
      "model_failed": false
    }
  ],
  "failed_sources": [],
  "sources": [
    {"id": "openai", "name": "OpenAI", "group": "labs", "enabled": true},
    {"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": false}
  ],
  "lesson": {
    "topic_id": "tf-scaled-attention",
    "title": "Scaled dot-product attention",
    "track": "architectures",
    "track_name": "Modern architectures, LLMs and inference",
    "series": "Transformers",
    "lesson": "…"
  },
  "recall": {
    "topic_id": "nn-tensor-shapes",
    "question": "…"
  },
  "leetcode": {
    "problem_id": "two-sum",
    "number": 1,
    "title": "Two Sum",
    "url": "https://leetcode.com/problems/two-sum/",
    "difficulty": "easy",
    "premium": false,
    "track": "amd",
    "review": false,
    "sources": [
      {"id": "neetcode-150", "name": "NeetCode 150", "kind": "curriculum", "publisher": "NeetCode"},
      {"id": "amd", "name": "AMD", "kind": "company", "publisher": "Interview Solver"}
    ],
    "company_tags": ["AMD"],
    "statement": "…",
    "example": {"input": "nums = [2, 7, 11, 15], target = 9", "output": "[0, 1]"},
    "constraints": ["2 ≤ n ≤ 10^4", "exactly one valid pair exists"],
    "prompts": ["What data structure would you choose?", "…"],
    "hints_enabled": true,
    "hint": "…",
    "hint_source": "model",
    "reference_solution": {
      "source": "catalog",
      "complete": true,
      "topic": "Arrays & Hashing",
      "approach": "…",
      "time": "O(n)",
      "space": "O(n)",
      "edge_cases": ["no valid pair", "the same value used twice"]
    }
  },
  "repair": null
}
```

A complete real example is in [`examples/sample-digest.json`](../examples/sample-digest.json).

### Top level

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Version of this layout. It increases only when a change could break a consumer. New keys may be added without changing it, so ignore keys you do not know. |
| `run_id` | integer | Identifies the DailyGrad execution that produced this digest. See below. |
| `date` | string | Local calendar date of the digest, `YYYY-MM-DD`. |
| `generated_at` | string | When the run started, ISO 8601 in UTC to the second. |
| `status` | string | `"ok"`, or `"degraded"` if a model request failed for any story or for the lesson, or if the LeetCode exercise is switched on and could not be prepared. Matches exit codes 0 and 1. |
| `model` | string | The Ollama model the run was configured to use. |
| `stories` | array | The digest's stories, in digest order. Empty on a day with no new stories. |
| `failed_sources` | array of strings | Names of news sources that could not be fetched. A failed source does not make the run degraded. |
| `sources` | array | Every available news source and whether this run fetched it. See below. Digests written before this key was added do not have it. |
| `lesson` | object or `null` | The micro-lesson. `null` if lesson generation failed. |
| `recall` | object or `null` | The recall question shown with the lesson. `null` on days without one, and when `lesson` is `null`. |
| `leetcode` | object or `null` | The day's LeetCode exercise. See below. `null` when exercises are switched off in the config file, when one could not be prepared (the run is then degraded), and when the practice mode had none to give (`leetcode_practice` then says why; the run is not degraded). Digests written before this key was added do not have it. |
| `leetcode_practice` | object or `null` | The LeetCode practice settings in force, and why there is no exercise when there is none to give. See [LeetCode practice](#leetcode-practice). `null` when exercises are switched off or could not be prepared. Digests written before this key was added do not have it. |
| `repair` | object or `null` | `null` in a run's own digest; in a repaired revision of it, what was repaired. See [Repaired revisions](#repaired-revisions). Added without changing `schema_version`; digests written before it do not have it. |

### Run ID

`run_id` is the ID of the run's row in the `runs` table of DailyGrad's database. It is a
positive integer, unique within one data directory, and larger for every later run. Every
run that writes a digest gets a new one, including a degraded run and a second run on the
same day.

A consumer can store the last `run_id` it handled and compare it with the one in
`latest.json` to tell whether there is a new digest, even when `date` has not changed.

It is not a global identifier: a different data directory, or a data directory that was
deleted and recreated, starts again from 1. Gaps in the sequence are possible.

### Sources

One entry for each available source, in the order they are fetched. It is the state the
run used, read once before fetching; a later change to the preferences does not alter a
digest already written.

| Key | Type | Meaning |
|---|---|---|
| `id` | string | The source's stable ID, as used by `dailygrad sources`. |
| `name` | string | The source's name, as it appears in a story's `source` and in `failed_sources`. |
| `group` | string or `null` | `"labs"`, `"hugging-face"` or `"community"`; `null` for a feed outside the groups. |
| `enabled` | boolean | `false` if the source was switched off, so the run did not fetch it. |

`sources` was added to schema version 1 as a new key. Nothing else changed, so a consumer
that ignores unknown keys is unaffected. To handle digests from before it existed, treat a
missing `sources` as unknown. Choosing sources is described in [sources.md](sources.md).

### Story

| Key | Type | Meaning |
|---|---|---|
| `id` | string | The story's canonical URL: lower-case host without `www.`, no scheme, tracking parameters, fragment or trailing slash. The same story has the same `id` on every run. |
| `title` | string | Title as published by the source. |
| `source` | string | `"Hacker News"`, `"Hugging Face Daily Papers"`, or the name of an RSS feed. |
| `url` | string | Link to the story. |
| `what_happened` | string or `null` | Summary of what happened. |
| `why_it_matters` | string or `null` | Why it matters. `null` exactly when `what_happened` is `null`. |
| `evidence` | string or `null` | What the summary was written from: `"article"` (extracted page text), `"abstract"` (paper abstract) or `"excerpt"` (the feed's own description, used when the page could not be fetched). `null` when there is no summary. |
| `model_failed` | boolean | `true` if a model request failed for this story. Such a story has no summary, is not recorded as shown, and may return in a later digest. |

A story can have no summary while `model_failed` is `false`. That means its page could not
be fetched and the source gave too little text to summarise, so the model was never asked.
It still counts as shown.

### Lesson

| Key | Type | Meaning |
|---|---|---|
| `topic_id` | string | Permanent ID of the curriculum topic. |
| `title` | string | Topic title. |
| `track` | string | `"foundations"`, `"architectures"` or `"agents"`. |
| `track_name` | string | The track's full name. |
| `series` | string | The multi-day series the topic belongs to. |
| `lesson` | string | The lesson text, two or three sentences. |

### Recall

| Key | Type | Meaning |
|---|---|---|
| `topic_id` | string | ID of the earlier topic being asked about. |
| `question` | string | The question. The answer is deliberately not included. |

### LeetCode

The current exercise. It is not chosen anew each day: a digest shows the same exercise as
the day before until the user completes or skips it, and the five keys from `exercise_id`
on say where this digest falls in that. Every key but the last is what the digest shows, and
none of them gives the answer away. The last, `reference_solution`, **is the answer**: it is there for a
program that gives feedback on the exercise, and is described [below](#reference-solution).
A consumer that displays or summarises a digest must leave that key out. The Markdown never
contains it. The firmer hints and the catalog's spoiler words are in neither: see
[leetcode.md](leetcode.md).

| Key | Type | Meaning |
|---|---|---|
| `problem_id` | string | The problem's permanent ID in the catalog: LeetCode's slug. |
| `number` | integer | LeetCode's problem number. |
| `title` | string | The problem's title on LeetCode. |
| `url` | string | Link to the problem on LeetCode. |
| `difficulty` | string | `"easy"`, `"medium"` or `"hard"`, as LeetCode rates it. |
| `premium` | boolean | `true` if LeetCode shows the full problem only to subscribers. The digest is complete either way. |
| `track` | string | The selected source the problem was drawn from: the first in the catalog's order that lists it (before practice modes: the track whose turn it was). Always one of the IDs in `sources`. |
| `review` | boolean | `true` if the problem had been assigned before, as an earlier exercise: a repeat in loop mode or a later coverage pass, or a learning review (`practice.encounter` tells them apart). It says nothing about this exercise being shown again: see `is_carryover`. |
| `sources` | array | Every list that holds the problem, each with `id`, `name`, `kind` (`"curriculum"` or `"company"`) and `publisher`. |
| `company_tags` | array of strings | The names of the `"company"` sources. These are a third party's tags, published by the source's `publisher`; they are not LeetCode's own company tags. |
| `statement` | string | A short summary of the task, written for DailyGrad. |
| `example` | object | One example, as `input` and `output` strings. |
| `constraints` | array of strings | The constraints that matter for choosing an approach. |
| `prompts` | array of strings | The questions the exercise asks. Their answers are not included. |
| `hints_enabled` | boolean | Whether hints were switched on when the digest was written. |
| `hint` | string or `null` | The one hint the digest shows. `null` while hints are off. |
| `hint_source` | string or `null` | `"model"` if the local model worded the hint, `"catalog"` if it is the catalog's hint as written. `null` exactly when `hint` is `null`. |
| `exercise_id` | integer | Names this assignment of the problem. The same in every digest that shows the exercise, and what `dailygrad leetcode mark complete --exercise` and `next --exercise` take. A later review of the same problem has another. |
| `assigned_on` | string | The local date of the first digest that showed the exercise, `YYYY-MM-DD`. |
| `day` | integer | How many days a digest has shown the exercise, this one included: 1 in the first. Days without a run are not counted. |
| `is_carryover` | boolean | `true` if an earlier day's digest showed the same exercise (`day` is 2 or more). `false` for a newly assigned one. |
| `awaiting_completion` | boolean | `true` while the user has neither completed nor skipped the exercise. `false` only in a rerun on the day it was ended: that day's digest still shows it, and the next day's has a new one. |
| `practice` | object or `null` | Why this exercise was chosen: `mode` (`"coverage"`, `"loop"` or `"learning"`), the `sources` selected then, `encounter` (`"first"` if the problem had never been assigned, `"repeat"`, or `"review"` for a learning review), `cycle` (`number`, `position`, `size`; loop mode only, else `null`) and `review` (`number`, `limit` as a number or `"unlimited"`, `due_on`; learning reviews only, else `null`). `null` for an exercise assigned before practice modes. |
| `reference_solution` | object or `null` | The catalog's reference answer. See below. `null` if the catalog has none for the problem. Digests written before this key was added do not have it. |

`leetcode` was added to schema version 1 as a new key, the last in the document. Nothing
else changed, so a consumer that ignores unknown keys is unaffected. The Markdown gained a
`## LeetCode Micro-Lesson` section after the lesson, and has none when `leetcode` is `null`
because exercises are switched off.

The same problem is shown again, with the same hint, on a rerun the same day and on every
later day until the user ends the exercise. Switching hints off or on changes
`hints_enabled` and `hint` from the next run, and never the problem. The five keys from
`exercise_id` on were added without changing `schema_version`; digests written before they
existed do not have them, and are to be read as a new exercise each (`is_carryover` false).

`practice` was added without changing `schema_version`. In the Markdown it is one line under
the byline, such as `_Loop practice · cycle 2, question 5 of 30 · seen before_` or
`_Learning practice · review 1 of 3_`; an exercise from before practice modes has none.

In the Markdown a carried-over exercise has one more line under its byline, and is
otherwise printed in full again:

```markdown
**Still in progress — originally assigned October 10** (day 3).
```

A rerun on the day the exercise was ended says `_Already completed: the next digest brings
a new exercise._` (or `skipped`) there instead.

### LeetCode practice

`leetcode_practice` holds the practice settings in force when the digest was written and,
when the practice mode had no exercise to give, why. It is not an error and does not make
the run degraded: the digest shows the reason instead of an exercise.

```json
"leetcode_practice": {
  "mode": "learning",
  "sources": [{"id": "amd", "name": "AMD"}],
  "state": "caught_up",
  "message": "No reviews due. Next review: October 22.",
  "next_review_on": "2026-10-22"
}
```

| Key | Type | Meaning |
|---|---|---|
| `mode` | string | `"coverage"`, `"loop"` or `"learning"`. See [leetcode.md](leetcode.md#question-sources-and-practice-modes). |
| `sources` | array | The selected question sources, each with `id` and `name`. |
| `state` | string | `"exercise"` when `leetcode` holds one. Otherwise why there is none: `"coverage_complete"` (every problem of the pool has been assigned in this pass), `"caught_up"` (learning: no review due yet) or `"learning_complete"` (learning: every problem has had all its reviews). |
| `message` | string or `null` | What the digest says in place of the exercise, e.g. `"AMD coverage complete."`. `null` when there is an exercise. |
| `next_review_on` | string or `null` | `"caught_up"`: the day the next review falls due, `YYYY-MM-DD`. Otherwise `null`. |

In the Markdown, the LeetCode section then holds the message alone:

```markdown
## LeetCode Micro-Lesson

_No reviews due. Next review: October 22._
```

#### Reference solution

`reference_solution` is the answer to the exercise, for a program that tutors on it: it can
check a person's approach against it, and explain it when asked. It is taken from the
catalog as written. The model writes none of it, and it is the same whether hints are on or
off and whether or not Ollama could be reached.

| Key | Type | Meaning |
|---|---|---|
| `source` | string | Where it comes from. Always `"catalog"`: the entry was validated when the catalog was loaded. |
| `complete` | boolean | `true` if the approach, both complexities and the edge cases are all there. `false` if any of them is `null`. |
| `topic` | string or `null` | The pattern the catalog files the problem under, such as `"Two Pointers"` or `"1-D Dynamic Programming"`. |
| `approach` | string or `null` | The reference approach in a few sentences. It names the data structure and the algorithm, and where the catalog records one, an alternative and what it costs. |
| `time` | string or `null` | The time complexity of that approach, written like `O(n)`. |
| `space` | string or `null` | Its space complexity. |
| `edge_cases` | array of strings, or `null` | The edge cases worth naming. |

It may be complete, partial or `null`, and a consumer has to accept all three:

- **Complete:** every key has a value. This is the case for all 182 problems of the catalog
  as it stands.
- **Partial:** a part the catalog does not have is `null`, never an empty string or list,
  and `complete` is `false`. Nothing is filled in to make up for it.
- **`null`:** the catalog has no approach, complexity or edge case for the problem. The rest
  of the exercise is unaffected.

There are no separate lists of data structures, algorithms or trade-offs: the catalog does
not hold them as fields. They are in the wording of `approach`.

The key was added to `leetcode` without changing `schema_version`. `dailygrad leetcode status`
does not print it, and `dailygrad leetcode review` gives the same material with the model's
explanation.
