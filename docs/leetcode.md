# The LeetCode micro-lesson

Each digest ends with one LeetCode problem, set as a conceptual exercise: choose a data
structure, describe an algorithm in words, estimate its time and space complexity, and name
the edge cases. No code is asked for, and the digest a person reads does not contain the
answer. The JSON carries the catalog's reference answer for a program that tutors on the
exercise, as [`reference_solution`](output.md#reference-solution).

The exercise is not a new one each day. It stays the current exercise, and every digest
shows it again, until the person says they are finished with it or asks for the next one.

This page covers the catalog and where it came from, how the current exercise is chosen and
ended, the hint preference, the `dailygrad leetcode` commands with their JSON output, and
what a program needs in order to relay answers on a person's behalf.

## How it fits together

```
 packaged catalog          deterministic choice          local model              digest
┌───────────────────┐    ┌────────────────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│ leetcode.toml     │    │ whose turn: rotation   │    │ words the hint   │    │ ## LeetCode          │
│ 182 problems      │───▶│ next unseen in track   │───▶│ (checked, with a │───▶│    Micro-Lesson      │
│ 3 sources         │    │ or a review            │    │ catalog fallback)│    │ "leetcode" in JSON   │
└───────────────────┘    └────────────────────────┘    └──────────────────┘    └──────────────────────┘
```

The catalog is the authority on every fact: which problem, its statement, its example and
its reference solution. The model never chooses a problem and never rewrites one. In a run
it words one hint. Outside a run, on request, it gives feedback on an answer and explains
the reference solution, in both cases from the catalog's material.

## The catalog

[`src/dailygrad/leetcode.toml`](../src/dailygrad/leetcode.toml) holds 182 problems and is
installed with the package. A run reads only that file. It never contacts LeetCode or any
of the sources.

Each `[[problem]]` has two halves.

| Shown in a digest | Kept for hints, feedback and review |
|---|---|
| `id`, `number`, `title`, `difficulty` | `hints` after the first |
| `tracks`, as the sources that list it | `spoilers` |
| `premium` | `approach`, `time`, `space` |
| `statement`, `input`, `output`, `constraints` | `edge_cases` |
| the first of `hints`, while hints are on | `category` |

Nothing in the right-hand column is ever shown: not in the Markdown, and not in the keys of
the JSON that describe the exercise. The JSON also has one key that is the answer itself,
[`reference_solution`](output.md#reference-solution): the `approach`, `time`, `space` and
`edge_cases` as written here, and the `category` by its name. It is for a program that
gives feedback, such as an assistant, and such a program must not display it unasked. The
further hints and the spoiler words are not in the JSON at all.

- `id` is LeetCode's slug, such as `two-sum`. It is the permanent identifier that history
  refers to, and the problem's address is `https://leetcode.com/problems/<id>/`.
- `category` is the topic, such as two pointers or dynamic programming. It orders a track
  and is never shown, because naming the topic names the technique.
- `spoilers` are the words that would give the approach away. The loader refuses an entry
  whose `statement` or first hint contains one of its own spoilers, or whose hints state a
  complexity. The same list is used to check what the model writes.
- `premium` marks the 13 problems that LeetCode shows in full only to subscribers. The
  digest gives enough of the problem either way.

The file is validated when it is loaded: unknown fields, a repeated ID, number or title, an
unknown track, a malformed complexity and a source whose count does not match are all
errors. `pytest` loads the packaged file, so a bad edit fails the tests.

## Sources and provenance

The catalog is a snapshot made on **2026-10-09**. The date and each source are recorded at
the top of the file, under `[catalog]` and `[[source]]`.

| Track | Source | Read from | Problems |
|---|---|---|---:|
| `neetcode-150` | The NeetCode 150 list | [richard7ao/neetcode-150](https://github.com/richard7ao/neetcode-150), commit `83adb3f` of 2026-07-17 | 150 |
| `amd` | Interview Solver's AMD page | <https://interviewsolver.com/interview-questions/amd>, which gave its own last update as 2026-09-28 | 17 |
| `vanguard` | Interview Solver's Vanguard page | <https://interviewsolver.com/interview-questions/vanguard> | 32 |

The three lists name 199 problems, of which 182 are different:

| | Problems |
|---|---:|
| NeetCode 150 | 150 |
| AMD problems also in NeetCode 150 | 9 of 17 |
| Vanguard problems also in NeetCode 150 | 8 of 32 |
| In both AMD and Vanguard (both are also in NeetCode 150) | 2 |
| Only on a company list | 32 (8 AMD, 24 Vanguard) |
| **Different problems** | **182** |

A problem on several lists is one entry whose `tracks` names each of them. Climbing Stairs
and Longest Substring Without Repeating Characters are on all three.

### What was taken, and what was written

**Taken from the sources:** only which problems each list holds.

**Checked against LeetCode's public problem list:** every slug, number, title, difficulty
and premium flag. That check corrected two things in the NeetCode repository: it rates Edit
Distance as hard where LeetCode says medium, and it names Pow(x, n) `pow-x-n` where
LeetCode's slug is `powx-n`. LeetCode's values are the ones in the catalog.

**Written for DailyGrad:** every statement, example, constraint, hint, spoiler list,
approach and edge case. Nothing was copied from LeetCode's problem descriptions or from the
sources. The NeetCode repository is under the Apache 2.0 licence, but its descriptions follow
LeetCode's wording closely, so they were not reused. Its solution code and tests were not
used at all. The complexities are standard results for each problem and were worked out
again, not transcribed.

The problems themselves are LeetCode's. Each exercise is a short summary with a link to the
original.

### Company lists are a third party's tags

Interview Solver is an independent site that lists the problems it associates with a
company. DailyGrad treats that as the site's claim, not as fact:

- A digest credits it as "AMD (Interview Solver tag)", and the JSON gives the source's
  `kind` as `"company"` and its `publisher` as `"Interview Solver"`.
- These are **not** LeetCode's own company tags, and nothing here says that either company
  asks these questions.
- The site's frequency percentages are not kept. They are not the probability of meeting a
  problem in an interview, and nothing in DailyGrad ranks problems by them.

The lists are short and change over time. On the snapshot date the AMD page held 17
problems.

### Refreshing the snapshot

The snapshot is refreshed by hand, during development, never by a run:

1. Read the three lists again and note the date.
2. Check each problem's slug, number, title, difficulty and premium flag against
   <https://leetcode.com/api/problems/all/>.
3. For a problem that is new to the catalog, write its entry. For one that left a list,
   remove that track from its `tracks`, and remove the entry only if no track is left.
   Never rename an `id`: history refers to it.
4. Update `snapshot`, and each source's `retrieved` and `problems`.
5. Run `pytest`. `tests/test_leetcode_catalog.py` states the counts, so it has to be
   updated too, deliberately.

A problem removed from the catalog stays in the history. It is simply never chosen again.

## Which problem is the current exercise

All of this is decided without the model, from the catalog, the rotation and the table of
exercises already assigned.

**One exercise at a time.** A run shows, in this order: the exercise an earlier run showed
that same day; else the current exercise, if it is still open; else a newly assigned one.
An exercise is open until the person completes or skips it (see
[Ending an exercise](#ending-an-exercise)), so with nothing said the same exercise appears
day after day, each time whole, and marked as carried over from its second day.

**The rotation.** The tracks take turns, one exercise each, in the order of `rotation`:
`neetcode-150`, `amd`, `vanguard`, and round again. The turn moves on when a new exercise is
assigned, not with the calendar and not with a showing: an exercise shown for four days
takes one turn, and a day on which DailyGrad did not run skips none.

**Within a track.** A track shows its easy problems first, then its medium ones, then its
hard ones. Within a difficulty it walks the topics in a fixed order: arrays and hashing,
two pointers, sliding window, stack, binary search, linked lists, trees, tries, heaps,
backtracking, graphs, advanced graphs, one- and two-dimensional dynamic programming,
greedy, intervals, math and geometry, bit manipulation. So each pass revisits the topics in
the same order at a higher level.

**Overlap.** The next problem of a track is its first one that has not been shown on *any*
track. Two Sum is on the NeetCode and AMD lists: whichever track reaches it first shows it,
and the other passes over it.

**Reviews.** When every problem of a track has been assigned, its turn is a review, not a
skipped turn. The review is the track's problem assigned least often; among those, one you
marked `needs-review` comes first, then unmarked ones, then `comfortable`, then solved; then
the one assigned longest ago. The previous exercise's problem is not chosen again while
there is another. The digest marks a review as such, and `review` is `true` in the JSON.
Nothing is deleted from the history to make a problem available again. A review is a new
exercise with its own ID: that the problem was completed, or solved in code, the first time
does not finish it. And `review` is only ever about the problem having been assigned before.
An exercise shown again because it is still open is a carry-over (`is_carryover`), not a
review.

With the default rotation the AMD track reaches its reviews after 17 of its exercises and
Vanguard after 30 of its. How long that takes now depends on you.

**The same day.** A second run on the same calendar day shows the exercise the first one
showed, with the same hint, and asks the model nothing more for it. That holds even if the
exercise was completed or skipped in between: the day's digest does not change under you,
and `awaiting_completion` is then `false` in its JSON. The next day's digest has the new
exercise.

**Carrying over costs nothing.** The hint is worded once and stored with the exercise, so a
later showing makes no model request for it.

**Failures.** The exercise is recorded in the same transaction as the run. If the output
files cannot be written the run is rolled back: no exercise was assigned, no showing was
recorded, and the rotation has not moved. If the exercise cannot be prepared at all (an
unreadable catalog, say) the digest keeps its news and its lesson, says that there is no
exercise, records none, and is degraded; the next run tries the same problem.

## Ending an exercise

Only the person ends an exercise, in one of two ways. Neither asks for an attempt, a correct
answer, code or a reason.

| | `leetcode mark complete` | `leetcode next` |
|---|---|---|
| Means | "I am finished with this one." | "Give me the next one now." |
| Records the exercise as | `completed` | `skipped`, unless it was completed already |
| Chooses the next exercise | no: the next run does | yes, at once, and returns it |
| Writes a digest, starts a run, uses the model | no | no |

Nothing else ends one. Being shown, a further hint, an answer however good, reading the
reference approach, and the marks `attempted`, `needs-review`, `comfortable` and `solved`
all leave the exercise open. `solved` is a statement about the problem (you solved it in
code); `completed` is a statement about the exercise (you are done with it). Neither sets
the other, and a skipped exercise counts as neither completed, attempted nor solved.

**After `mark complete`** there is no current exercise until the next run assigns one, from
the next track. A run later the same day still shows the completed exercise, because it is
that day's.

**After `next`** the new exercise is current immediately. It has not been in a digest: the
next scheduled run shows it and words its hint. Today's digest, and anything posted from
it, is left as it is.

**Naming the exercise.** Both commands take `--exercise ID`, the `exercise_id` that `status`
and a digest's JSON give, and act only if that is still the current exercise. That makes a
request safe to repeat and safe to arrive late:

- Completing an exercise that is already completed changes nothing (`changed` is `false`).
- `next` for an exercise that has already been moved on from changes nothing, as long as it
  is the one just before the current exercise; the reply names the current one again.
- Anything older, an exercise that was skipped when completion was asked for, or an ID
  that names another problem than `--problem` does, is refused with `stale_exercise`.
  Nothing changes, and the caller should read `status` again.

Without `--exercise` the commands act on the newest exercise, which is what a person at a
terminal means. A program should always pass it.

**During a run.** Each command is one short write transaction. A run that has already
picked its exercise keeps it for that digest, and what the command did still stands: a
completion made while the run was working is in that digest's `awaiting_completion`, and an
exercise that `next` assigned meanwhile is the one the run records, so one request never
uses two turns of the rotation.

## Hints

```sh
dailygrad leetcode hints off
dailygrad leetcode hints on
```

Hints are **on** until switched off. The choice lives in
`<data_dir>/leetcode_preferences.json`, beside the database:

```json
{
  "version": 1,
  "hints": false,
  "updated_at": "2026-10-09T15:20:00+00:00"
}
```

- It is runtime data. Git ignores `data/`, and a code update does not touch it.
- A change applies from the next digest and the next reply. It never chooses a problem,
  moves the rotation, runs DailyGrad or rewrites a digest that exists.
- A run only reads the file. If it exists but cannot be understood, the run goes ahead and
  shows **no** hint: a hint shown by mistake cannot be taken back, while a missing one is
  one command away. `dailygrad leetcode status` reports the problem, and
  `dailygrad leetcode hints on` (or `off`) replaces the file.

### How a digest's hint is written

The catalog's first hint is the approved material. The model is asked, at temperature 0, to
reword it as one gentle sentence. It is given the problem's statement and that hint, and
nothing of the reference solution.

What it returns is discarded, and the catalog's hint is printed instead, if it

- contains one of the problem's `spoilers` (matched at the start of a word, in any case, so
  `hash` also catches "hashing" and "hash map"),
- states a complexity, or contains code,
- is shorter than 20 or longer than 240 characters, or is not text at all,

or if Ollama cannot be reached, or the run's time budget is spent. `hint_source` in the JSON
says which was shown: `"model"` or `"catalog"`. A hint taken from the catalog does not make
a run degraded, because nothing is missing.

The hint is written once and stored with the exercise, so it is the same on every day the
exercise is shown. If hints were off when the exercise was first shown and are switched on
later, the next run writes the hint then. An exercise that `next` assigned has no hint
until a run shows it.

With `model_hints = false` under `[leetcode]`, the catalog's hint is always printed and the
model is not asked.

## Progress

Five things are kept apart, because none implies another. The first four are said of a
problem, the last of one exercise:

| State | Set by | Stored in |
|---|---|---|
| **Shown** | a run, when the exercise appears in a digest | `leetcode_assignments`, `leetcode_showings` |
| **Attempted** | an answer that describes an approach, or `mark attempted` | `leetcode_progress.attempted_at` |
| **Needs review** / **comfortable** | only `mark needs-review` or `mark comfortable` | `leetcode_progress.confidence` |
| **Solved in code** | only `mark solved` | `leetcode_progress.solved_at` |
| **Completed** / **skipped** | only `mark complete` / `next` | `leetcode_outcomes.outcome` |

Feedback never marks a problem as solved or an exercise as completed, however good the
answer. `mark clear` withdraws the confidence and the solved mark; the showings, the
exchanges and the outcome of an exercise are history and stay.

The database holds five LeetCode tables. None of DailyGrad's earlier tables changed, and a
database from an earlier version gains the missing ones the first time it is opened for
writing.

- `leetcode_assignments`: one row per exercise assigned, with its track, whether it was a
  review, and the hint written for it. The newest row is the current exercise while it has
  no outcome. The rotation and every track's position are derived from this table alone, so
  showing an exercise again moves neither.
- `leetcode_showings`: one row per run whose digest showed an exercise. It is what makes a
  rerun show the day's exercise again, and where `day` and `assigned_on` come from.
- `leetcode_outcomes`: at most one row per exercise, `completed` or `skipped`, with the
  time. Its primary key is the exercise, so an exercise cannot be ended twice.
- `leetcode_turns`: one row per further hint, answer or review, with what was returned.
- `leetcode_progress`: one row per problem you have attempted or marked.

**A database from before exercises were kept.** That version assigned a new exercise every
day, so its `leetcode_assignments` has one row per day. Nothing in it is rewritten. Each row
still counts as one exercise, so the rotation continues from exactly where it was; each
gets the one showing its row names, added to `leetcode_showings` the first time the database
is opened for writing; and the marks in `leetcode_progress` are untouched. Its newest
exercise becomes the current one and is carried over until you end it. The older ones have
no outcome: they were neither completed nor skipped, and are not counted as either.
`status` reads such a database as it is, without changing it.

## Commands

| Command | Does | Uses the model |
|---|---|---|
| `dailygrad leetcode` or `leetcode status` | The current exercise, the rotation and your progress. Reads only: creates no file. | No |
| `leetcode hints on` / `off` | Whether digests show a hint. | No |
| `leetcode hint` | The next hint for the exercise, one step firmer than the last. | No |
| `leetcode answer` | Feedback on an approach read from standard input. | Yes, once |
| `leetcode review` | The reference approach, its complexities and edge cases. **Shows the answer.** | Yes, once, for the explanation |
| `leetcode mark STATE` | Records `attempted`, `needs-review`, `comfortable`, `solved` or `clear` for the problem. | No |
| `leetcode mark complete` | Ends the current exercise as completed. The next run assigns the next. | No |
| `leetcode next` | Ends the current exercise as skipped (unless completed) and assigns the next at once. | No |

Every command accepts `--json` and `--config PATH`. `hint`, `answer`, `review` and `mark`
are about the newest exercise assigned, or with `--problem ID` about the newest exercise of
that problem. `mark complete` and `next` also take `--exercise ID`. No command writes a
digest or starts a run, and only `next` chooses a problem or moves the rotation.

### Exit codes and errors

| Code | Meaning |
|---|---|
| 0 | Done. |
| 1 | The request was sound but failed: the model gave no usable reply, or a file could not be read or written. |
| 2 | The request was refused, the configuration is invalid, or the command line could not be parsed. Nothing changed. |

With `--json`, a failure prints `{"ok": false, "error": {"code": "…", "message": "…"}}` on
standard output; the message also goes to standard error.

| `code` | Exit | Meaning |
|---|---:|---|
| `no_exercise` | 2 | No exercise has been assigned yet. `dailygrad run` assigns the first. |
| `unknown_problem` | 2 | `--problem` names something that is not in the catalog. |
| `unknown_exercise` | 2 | `--exercise` is not an exercise's ID: not a number of 1 to 9 digits, or no exercise has it. |
| `stale_exercise` | 2 | `mark complete` or `next` named an exercise that is no longer the current one, or one that is not the `--problem` given. Nothing changed: read `status` again. |
| `leetcode_disabled` | 2 | `next` was asked for while exercises are switched off in the configuration. |
| `bad_arguments` | 2 | `--exercise` was given to a `mark` other than `complete`. |
| `not_shown` | 2 | `--problem` names a problem that has not been shown, so there is nothing to follow up on. |
| `empty_answer` | 2 | Standard input held no text. |
| `answer_too_long` | 2 | The answer is over 4,000 characters. |
| `bad_answer` | 2 | Standard input was not UTF-8 text. |
| `unknown_state` | 2 | `mark` was given a state it does not know. |
| `invalid_config` | 2 | The configuration file is invalid. |
| `model_unavailable` | 1 | Ollama could not be reached, or its reply was unusable. Nothing was recorded: send the answer again. |
| `failed` | 1 | The catalog, the database or a file could not be used. |

### `status --json`

```json
{
  "ok": true,
  "enabled": true,
  "hints_enabled": true,
  "preferences_file": "/home/you/dailygrad/data/leetcode_preferences.json",
  "preferences_problem": null,
  "rotation": ["neetcode-150", "amd", "vanguard"],
  "next_track": {"id": "amd", "name": "AMD"},
  "active_exercise_id": 1,
  "completion_pending": true,
  "current": {
    "problem_id": "contains-duplicate",
    "…": "every key of the digest's leetcode object",
    "exercise_id": 1,
    "assigned_on": "2026-10-07",
    "day": 3,
    "is_carryover": true,
    "awaiting_completion": true,
    "date": "2026-10-07",
    "is_today": true,
    "outcome": null,
    "closed_at": null,
    "hints_given": 1,
    "hints_total": 2,
    "answers": 0,
    "state": {"times_shown": 1, "attempted": false, "confidence": null, "solved_in_code": false}
  },
  "tracks": [
    {
      "id": "neetcode-150", "name": "NeetCode 150", "kind": "curriculum", "publisher": "NeetCode",
      "url": "https://github.com/richard7ao/neetcode-150", "retrieved": "2026-10-09",
      "problems": 150, "shown": 1, "in_rotation": true
    }
  ],
  "progress": {
    "problems": 182, "shown": 1, "exercises": 1, "completed": 0, "skipped": 0,
    "attempted": 0, "needs_review": 0, "comfortable": 0, "solved_in_code": 0
  },
  "catalog": {"snapshot": "2026-10-09", "problems": 182}
}
```

- `current` is the newest exercise assigned, or `null` before the first. It holds every key
  of the digest's [`leetcode` object](output.md#leetcode) except `reference_solution`, with
  `hint` following the hint preference as it is now, plus the keys shown above.
  `hints_given` counts the digest's hint, if it showed one, and those asked for since.
- `active_exercise_id` is the exercise that `mark complete` and `next` would act on, and the
  ID to pass them as `--exercise`. `completion_pending` is `true` with it. Both are
  `null`/`false` when the newest exercise has been completed and the next has not been
  assigned yet; `current` is then that completed exercise, with `outcome` `"completed"`,
  `closed_at` and `awaiting_completion` `false`.
- `day` is the number of days a digest has shown the exercise so far, and `date` (the same
  as `assigned_on`) the first of them. `is_today` says whether today's digest shows it. An
  exercise that `next` assigned and no digest has shown yet has `date` `null`, `day` 0 and
  `is_today` `false`.
- `next_track` is the track the exercise after the current one will come from.
- `tracks[].shown` counts that list's problems assigned on any track. `progress.exercises`
  counts exercises, which exceeds `progress.shown` once reviews begin; `completed` and
  `skipped` count how those ended, and an open or older exercise is in neither.
- `preferences_problem` is a sentence if the preferences file exists but cannot be used,
  and `hints_enabled` is then `false`.
- Nothing in it comes from the hidden half of the catalog.

### `hints on|off --json`

```json
{"ok": true, "changed": true, "hints_enabled": false, "preferences_file": "/home/you/dailygrad/data/leetcode_preferences.json"}
```

`changed` is `false` when hints were already in that state.

### `hint --json`

```json
{
  "ok": true,
  "problem": {"id": "two-sum", "number": 1, "title": "Two Sum", "url": "https://leetcode.com/problems/two-sum/"},
  "hint": "For each element you know exactly which partner value you need. How quickly can you check whether you have seen it?",
  "hint_number": 2,
  "hints_total": 2,
  "hints_left": 0,
  "hints_enabled": true
}
```

Hints come straight from the catalog, in order, each a step firmer than the last and none
giving the whole solution. If the digest showed a hint, the first request gives the second.
When none is left, `hint` and `hint_number` are `null`: the reference approach is a separate
request, `review`.

Asking for a hint works whether or not digests show hints. Switching hints off stops
DailyGrad from *offering* them; it does not refuse a person who asks.

### `answer --json`

The answer is read from standard input, never from the command line.

```sh
echo "I would compare every pair with two loops. O(n) time, O(1) space." | dailygrad leetcode answer --json
```

```json
{
  "ok": true,
  "problem": {"id": "contains-duplicate", "number": 217, "title": "Contains Duplicate", "url": "https://leetcode.com/problems/contains-duplicate/"},
  "assessment": "partly",
  "feedback": "Your approach of comparing every pair works logically but is inefficient for large inputs. You incorrectly estimated the time complexity; nested loops actually run in O(n^2) time.",
  "complexity": "The time complexity is O(n^2), not O(n), and your space complexity is correct at O(1).",
  "edge_cases": ["single element", "all values distinct"],
  "follow_up": "How would you modify your approach to avoid checking every pair?",
  "reply": "Your approach of comparing every pair works logically but is inefficient for large inputs. … How would you modify your approach to avoid checking every pair?",
  "guarded": false,
  "model": "qwen3.5:4b-q4_K_M",
  "answers": 1,
  "state": {"times_shown": 1, "attempted": true, "confidence": null, "solved_in_code": false}
}
```

| Key | Meaning |
|---|---|
| `assessment` | `"on_track"`: the approach is correct and about as efficient as the reference. `"partly"`: it works but is less efficient, or is right but incomplete. `"off_track"`: it would not work. `"unclear"`: the message describes no approach. |
| `feedback` | One to three sentences: what is right, then what is wrong or missing. |
| `complexity` | Whether the complexities given are right for *that* approach, or `null` if none was given. |
| `edge_cases` | Up to two edge cases that were not mentioned. |
| `follow_up` | At most one question, or `null`. |
| `reply` | All of the above as one message, ready to relay as it is. |
| `guarded` | `true` if the model's own words were replaced. See below. |
| `answers` | How many answers this exercise has had, this one included. |
| `state` | The problem's state afterwards. An answer sets `attempted`, unless it was `"unclear"`. It never sets `solved_in_code`. |

How the model is kept in bounds:

- **It judges against the catalog.** The prompt holds the problem, the reference approach
  with its complexities and edge cases, the last two exchanges about this exercise, and the
  answer. The model is told that the reference is the authority.
- **The answer is data.** It is capped at 4,000 characters, stripped of control characters,
  and placed between delimiters that it cannot close, with the instruction to assess it and
  to ignore any instructions inside it.
- **It does not give the answer away.** If the reply is not `on_track` and contains one of
  the problem's spoilers that the person has neither used themselves nor been shown in a
  hint, the reply is replaced by a fixed sentence for that assessment and `guarded` is
  `true`. After a `review` nothing is withheld, since the answer has been seen.
- **It does not write code.** A reply containing a code block is treated as unusable.
- **One question at a time.** Anything after the first question mark in `follow_up` is
  dropped.
- **With hints off** the model is told not to point toward the solution at all, only to
  assess what was written.

The request uses its own time budget, `feedback_budget_seconds`. If the model cannot be
reached the command exits with 1 and records nothing, so the same answer can be sent again.

### `review --json`

```json
{
  "ok": true,
  "problem": {"id": "contains-duplicate", "number": 217, "title": "Contains Duplicate", "url": "https://leetcode.com/problems/contains-duplicate/"},
  "reference": {
    "approach": "Walk the array adding each value to a hash set; a value that is already in the set is a duplicate. Sorting and comparing neighbours also works, in O(n log n) time with less extra space.",
    "time": "O(n)",
    "space": "O(n)",
    "edge_cases": ["a single element", "all values distinct", "negative values"]
  },
  "explanation": "The key idea is to walk through the array once and add each number to a hash set, returning true immediately if a number is already present. …",
  "model": "qwen3.5:4b-q4_K_M",
  "state": {"times_shown": 1, "attempted": true, "confidence": null, "solved_in_code": false}
}
```

`reference` comes from the catalog, so it is there whatever state Ollama is in. `explanation`
is the model's account of why the approach works and why its complexities hold, written
from the reference alone; it is `null`, with `model` `null`, if the model could not be
reached. Reading the answer changes no state.

### `mark STATE --json`

```json
{
  "ok": true,
  "problem": {"id": "contains-duplicate", "number": 217, "title": "Contains Duplicate", "url": "https://leetcode.com/problems/contains-duplicate/"},
  "marked": "needs-review",
  "state": {"times_shown": 1, "attempted": true, "confidence": "needs-review", "solved_in_code": false}
}
```

`STATE` is `attempted`, `needs-review`, `comfortable`, `solved` or `clear`. `solved` means
solved in code, and also counts as an attempt. `needs-review` and `comfortable` replace each
other. `clear` withdraws the confidence and the solved mark. None of them ends the exercise.

### `mark complete --json`

```sh
dailygrad leetcode mark complete --exercise 1 --json
```

```json
{
  "ok": true,
  "action": "complete",
  "changed": true,
  "exercise": {
    "exercise_id": 1,
    "problem_id": "contains-duplicate",
    "number": 217,
    "title": "Contains Duplicate",
    "url": "https://leetcode.com/problems/contains-duplicate/",
    "track": "neetcode-150",
    "review": false,
    "assigned_on": "2026-10-07",
    "days_shown": 3,
    "outcome": "completed",
    "closed_at": "2026-10-09T17:44:42+00:00"
  },
  "completion_pending": false,
  "next_track": {"id": "amd", "name": "AMD"}
}
```

- `exercise` says exactly which exercise is completed. Nothing of the problem's content or
  its answer is in the reply.
- `changed` is `false` if it was completed already; `closed_at` is then the first time.
- `completion_pending` is `false` when no exercise is open, which is the usual state after a
  completion, and `next_track` is then the track the next run assigns from. If the
  completed exercise has since been followed by another (a repeat that arrives late),
  `completion_pending` is `true` and `next_track` is `null`: nothing is to be announced.
- No problem is chosen, no digest or archive is touched, and the model is not used.

### `next --json`

```sh
dailygrad leetcode next --exercise 1 --json
```

```json
{
  "ok": true,
  "action": "next",
  "changed": true,
  "previous": {
    "exercise_id": 1,
    "problem_id": "contains-duplicate",
    "…": "the same keys as `exercise` above",
    "outcome": "skipped",
    "closed_at": "2026-10-09T17:44:43+00:00"
  },
  "active": {
    "problem_id": "two-sum",
    "…": "every key of the digest's leetcode object except reference_solution",
    "hint": null,
    "exercise_id": 2,
    "assigned_on": null,
    "day": 0,
    "is_carryover": false,
    "awaiting_completion": true
  }
}
```

- `previous` is the exercise moved on from. Its `outcome` is `"skipped"`, or `"completed"`
  if it had been completed before: `next` then only assigns the following exercise.
- `active` is the new current exercise, safe to show a person: the statement, the example,
  the constraints and the questions, with no `reference_solution`, no topic and no hint
  (`hint` is `null` until a run words one).
- `changed` is `false` for a repeat of a request already carried out. `active` is then the
  exercise that request assigned, if it is still open, and nothing was skipped again.
- The two writes, closing one exercise and assigning the next, are one transaction.

## The model's memory

A run loads the model, uses it for the news, the lesson and the hint, and unloads it when it
ends, as before. The exercise adds one short request to a run.

`answer` and `review` are separate from runs. After one of them the model stays loaded for
`keep_alive_seconds`, 300 by default, so that the next message of a conversation is answered
in a few seconds instead of waiting for the model to load again. Ollama then frees it by
itself. With `keep_alive_seconds = 0` it is freed as soon as the reply is sent. `status`,
`hints`, `hint`, `mark` and `next` never load the model.

## Using it from an assistant or another program

DailyGrad owns the catalog, the choice of problem, the hints, the feedback, the progress, the
hint preference, and which exercise is current. A program that delivers the digest or relays a conversation needs none
of that logic, only these calls:

| To | Run | Input |
|---|---|---|
| Show the exercise | read `leetcode` in `latest.json` (without `reference_solution`), or the Markdown | none |
| Tutor on it yourself | read `leetcode.reference_solution` in `latest.json` | none |
| Check the state | `dailygrad leetcode status --json` | none |
| Change the hint preference | `dailygrad leetcode hints on --json` or `off` | none |
| Give the next hint | `dailygrad leetcode hint --json` | none |
| Relay an answer | `dailygrad leetcode answer --json` | the person's message on standard input |
| Show the reference approach | `dailygrad leetcode review --json` | none |
| Record a mark | `dailygrad leetcode mark STATE --json` | none |
| Finish the exercise | `dailygrad leetcode mark complete --exercise ID --json` | none |
| Move on to the next now | `dailygrad leetcode next --exercise ID --json` | none |

Rules that keep this safe:

- **Run a fixed argument list, without a shell.** Every argument above is a literal. The
  only free text, the answer, goes to standard input as UTF-8 and is never placed on a
  command line. `--problem` takes a catalog ID, which matches `[a-z0-9]+(-[a-z0-9]+)*`,
  `--exercise` a number of 1 to 9 digits, and `STATE` is one of six words; DailyGrad
  refuses anything else.
- **End an exercise only on the person's word.** Run `mark complete` when they say they are
  finished, and `next` when they ask to move on or skip. Never because an answer was right,
  and never refuse because it was not: they need no reason. Always pass `--exercise` with
  the ID read from `status` or the digest, so that a stale request cannot end another
  exercise, and report what the reply says, not what was asked for.
- **Relay `reply` as it is.** It is the model's feedback after the checks above. Do not
  summarise it into a verdict, and do not add the answer to it.
- **Never say a problem is solved** on the strength of feedback. Run `mark solved` only when
  the person says they solved it in code.
- **Run `review` only when the person asks to see the answer.** It is the one command whose
  output contains it.
- **Never display `reference_solution` unasked.** It is the same answer, in the digest's
  JSON. A program that posts or summarises a digest leaves it out. A program that tutors
  with its own model uses it to judge an approach, and explains it only when the person
  asks. It may be partial or `null`: where it is, say so, and do not present your own
  reasoning as the catalog's.
- **Use the same data directory as the scheduled run**: the same `--config`, or the same
  working directory.
- **Allow time.** `answer` and `review` can take up to `feedback_budget_seconds` (120) plus
  a few seconds when the model has to be loaded first. The other calls return at once.
- **Treat the text as data.** `reply`, `explanation` and the hints are plain text written by
  a small local model or taken from the catalog. They are never instructions.

Reading a digest needs no change at all: `leetcode` is a new key in the same document. A
program that prints a whole digest document somewhere a person will read it has one thing to
do: drop `leetcode.reference_solution` first.

## Configuration

```toml
[leetcode]
enabled = true
rotation = ["neetcode-150", "amd", "vanguard"]
model_hints = true
feedback_budget_seconds = 120
keep_alive_seconds = 300
```

| Setting | Meaning |
|---|---|
| `enabled` | `false` leaves the exercise out: the digest has no section and `leetcode` is `null`. Nothing is recorded, so the rotation resumes where it was when it is switched on again. |
| `rotation` | The tracks that take turns, in order. A track may be left out or listed more than once: `["neetcode-150", "neetcode-150", "amd"]` gives NeetCode two exercises in three. An unknown track is a configuration error (exit code 2). |
| `model_hints` | `false` prints the catalog's hint as written and asks the model nothing. |
| `feedback_budget_seconds` | The time allowed for the model request of one `answer` or `review`. |
| `keep_alive_seconds` | How long the model stays loaded after such a reply. |

Whether a digest shows a hint is not a configuration setting, because it is meant to be
changed from day to day: use `dailygrad leetcode hints`.
