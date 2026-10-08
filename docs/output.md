# Output contract

DailyGrad's public interface is the `dailygrad run` command, its exit code, its standard
output, and the files it writes. An integration needs nothing else: it never has to read
the SQLite database.

`dailygrad sources`, which chooses the news sources, has its own JSON output and exit
codes. They are described in [sources.md](sources.md).

`dailygrad history` lists and prints the archived digest of every run. It is described
under [Run archives](#run-archives).

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

## Exit codes

| Code | Meaning | Files written |
|---|---|---|
| 0 | The digest was produced normally. `status` is `"ok"`. | Yes |
| 1 | Degraded: at least one model request failed, so a summary or the lesson is missing. `status` is `"degraded"`. A crash also exits with 1, with a Python traceback on stderr and nothing printed on stdout. | Yes if degraded, no if crashed |
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
  }
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
| `status` | string | `"ok"`, or `"degraded"` if a model request failed for any story or for the lesson. Matches exit codes 0 and 1. |
| `model` | string | The Ollama model the run was configured to use. |
| `stories` | array | The digest's stories, in digest order. Empty on a day with no new stories. |
| `failed_sources` | array of strings | Names of news sources that could not be fetched. A failed source does not make the run degraded. |
| `sources` | array | Every available news source and whether this run fetched it. See below. Digests written before this key was added do not have it. |
| `lesson` | object or `null` | The micro-lesson. `null` if lesson generation failed. |
| `recall` | object or `null` | The recall question shown with the lesson. `null` on days without one, and when `lesson` is `null`. |

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
