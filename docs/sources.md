# Choosing news sources

`dailygrad sources` shows the news sources and switches them on or off. Every source is on
until you switch it off.

A change applies from the next run. It does not regenerate today's digest; run
`dailygrad run` yourself if you want a new one.

## Sources and groups

| ID | Source | Group |
|---|---|---|
| `openai` | OpenAI | `labs` |
| `google-deepmind` | Google DeepMind | `labs` |
| `google-research` | Google Research | `labs` |
| `hugging-face-blog` | Hugging Face Blog | `hugging-face` |
| `hugging-face-daily-papers` | Hugging Face Daily Papers | `hugging-face` |
| `hacker-news` | Hacker News | `community` |

| Group ID | Name | Members |
|---|---|---|
| `labs` | AI labs and research | `openai`, `google-deepmind`, `google-research` |
| `hugging-face` | Hugging Face | `hugging-face-blog`, `hugging-face-daily-papers` |
| `community` | Community | `hacker-news` |
| `all` | | every source |

A group ID can be used wherever a source ID can. IDs are not case-sensitive.

An ID is the source's name in lower case with hyphens. A feed you add under `[[rss.feeds]]`
gets an ID the same way ("My favourite lab" becomes `my-favourite-lab`) and belongs to no
group. Two sources may not share an ID, and a feed may not be named after a group.

## Commands

```sh
dailygrad sources                          # list the sources and their status
dailygrad sources disable hugging-face     # switch a group off
dailygrad sources enable hugging-face-daily-papers
dailygrad sources disable google-research  # DeepMind and OpenAI stay on
dailygrad sources set labs hacker-news     # only these, now and when sources are added
dailygrad sources set all                  # back to the default: everything on
```

`enable`, `disable` and `set` each take one or more IDs. Every command accepts `--json`
and `--config PATH`.

```
$ dailygrad sources disable hugging-face
ID                         Source                     Group         Status
openai                     OpenAI                     labs          enabled
google-deepmind            Google DeepMind            labs          enabled
google-research            Google Research            labs          enabled
hugging-face-blog          Hugging Face Blog          hugging-face  disabled
hugging-face-daily-papers  Hugging Face Daily Papers  hugging-face  disabled
hacker-news                Hacker News                community     enabled

Groups: labs (AI labs and research), hugging-face (Hugging Face), community (Community), all
Preferences file: /home/you/dailygrad/data/source_preferences.json
Selection: every source except those disabled above. A source added later is enabled.

Saved. The change applies from the next run; today's digest is not regenerated.
```

Rules:

- An unknown ID is refused, and nothing is changed, even if other IDs in the same command
  are valid.
- At least one source must stay enabled. A command that would switch everything off is
  refused.
- Repeating a command is harmless. If nothing would change, the file is not rewritten.

## Two kinds of selection

What happens to a source that appears later, through a DailyGrad update or a feed you add
to the config, depends on how you made your selection:

| You used | Meaning | A source added later is |
|---|---|---|
| nothing, or only `enable` and `disable` | every source except the ones you disabled | enabled |
| `set` with a list of IDs | only the sources you named | disabled, until you `enable` it |
| `set all` | back to the default | enabled |

`set` is exclusive: "only these" stays true whatever is added. That holds even if the list
names every source that exists today. After a `set`, `enable` and `disable` adjust the
list and it stays exclusive; only `set all` returns to the default. The last line of
`dailygrad sources` says which kind is in effect, and `mode` says so in the JSON output.

## What disabling a source does

A disabled source is not fetched: no request is made to it. Filtering, ranking, selection,
summaries and the lesson work as before on whatever the remaining sources return. If they
return fewer than five usable stories, the digest shows those; it never invents any.

Disabling a feed does not block its publisher. With `openai` off and `hacker-news` on, a
Hacker News story that links to openai.com can still appear, credited to Hacker News.

## Where the preferences are kept

In `source_preferences.json` in the data directory, beside the database
(`dailygrad config` prints the path). The data directory is ignored by Git, so the
preferences survive `git pull` and reinstalling. The file is created by the first change;
without it every source is on.

The file holds one of two lists. After `enable` and `disable` alone, it lists what is off:

```json
{
  "version": 1,
  "disabled": [
    "hugging-face-blog",
    "hugging-face-daily-papers"
  ],
  "updated_at": "2026-10-08T14:34:26+00:00"
}
```

After `set` with a list of IDs, it lists what is on, and everything else is off:

```json
{
  "version": 1,
  "enabled_only": [
    "openai",
    "google-deepmind",
    "google-research",
    "hacker-news"
  ],
  "updated_at": "2026-10-08T14:40:02+00:00"
}
```

An ID in the file that no longer exists is ignored.

The config file and the preferences do different jobs. The config decides which sources
exist: the `[[rss.feeds]]` list, and `enabled` under `[hackernews]` and `[huggingface]`.
The preferences switch those sources on and off. A source removed in the config is not
listed by `dailygrad sources` at all.

### If the file is damaged

Use the command to change the file, not an editor. A file that exists but cannot be
understood is an error, never a reason to fetch everything, because that could bring back
a source you switched off. The file is invalid if it is not JSON, has no `"version": 1`,
has both lists or neither, or cannot be read.

While the file is invalid:

- `dailygrad run` stops before fetching anything and exits with 2. No digest is written,
  and the previous digest files are left as they were.
- `dailygrad sources`, `enable` and `disable` are refused with `invalid_preferences`.
- `dailygrad config` still works and shows the problem on its `Sources` line.
- The file itself is never modified or deleted by any of these.

To recover, replace it with an explicit choice:

```sh
dailygrad sources set all                # every source on, the default
dailygrad sources set labs hacker-news   # or exactly the sources you want
```

### Runs and changes at the same time

The file is replaced atomically, so a reader never sees half of it. A run reads it once,
before fetching, and uses that snapshot to the end: a change made while a run is in
progress takes effect on the next run. Changes take a lock, so two changes made at the
same moment are both kept.

## JSON output, for other programs

With `--json`, every `sources` command prints one JSON document on stdout and nothing else
there. Listing and changing return the same layout:

```json
{
  "ok": true,
  "changed": true,
  "mode": "all_except",
  "sources": [
    {"id": "openai", "name": "OpenAI", "group": "labs", "enabled": true},
    {"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": false}
  ],
  "groups": [
    {"id": "labs", "name": "AI labs and research", "sources": ["openai", "google-deepmind", "google-research"]}
  ],
  "preferences_file": "/home/you/dailygrad/data/source_preferences.json"
}
```

| Key | Meaning |
|---|---|
| `ok` | `true`. |
| `changed` | Whether this command changed the preferences. Always `false` for a listing. |
| `mode` | `"all_except"`: every source is on except those disabled, and a source added later is on. `"only"`: an exclusive selection made with `set`, and a source added later is off. |
| `sources` | Every available source, in fetch order, with its state after the command. `group` is `null` for a feed outside the groups. |
| `groups` | The groups and their members. |
| `preferences_file` | Absolute path of the preferences file, which may not exist yet. |

A command that fails prints this instead, and the message also goes to stderr:

```json
{
  "ok": false,
  "error": {
    "code": "no_sources_enabled",
    "message": "at least one source must stay enabled"
  }
}
```

| Exit code | `error.code` | Meaning |
|---|---|---|
| 0 | | Done. Check `changed` to see whether anything was different. |
| 2 | `unknown_source` | An ID is not a known source or group. |
| 2 | `no_sources_enabled` | The command would leave no source enabled. |
| 2 | `invalid_preferences` | The existing file cannot be understood. Listing, `enable` and `disable` fail this way; `set` replaces the file. |
| 2 | `invalid_config` | The DailyGrad config file is invalid. |
| 1 | `write_failed` | The preferences could not be saved. |

Nothing is changed when a command fails. A command line that cannot be parsed at all, such
as `disable` with no ID, exits with 2 and prints a usage message on stderr, not JSON.

Each digest also records the sources its run used: see `sources` in
[output.md](output.md).
