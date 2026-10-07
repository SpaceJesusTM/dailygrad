# DailyGrad

DailyGrad is a lightweight, self-hosted AI news digest and micro-learning tool powered by a local LLM.

Once per day, DailyGrad collects high-signal AI news from sources such as Hacker News, Hugging Face Daily Papers, and official AI lab feeds. A small local model running through Ollama selects and summarizes the most relevant stories and generates a short technical refresher covering topics in deep learning, LLMs, and agentic AI.

The goal is simple: **stay current with AI while taking one small learning step every day.**

## Planned Features

- Daily AI news aggregation and filtering
- 3–5 concise, locally generated news summaries
- Daily 2–3 sentence AI/ML micro-lesson
- Persistent curriculum and review history
- Local inference through Ollama
- Automatic model unloading after each batch
- Markdown and stdout output
- Optional Discord / assistant integrations
- Lightweight SQLite persistence

DailyGrad is designed to run as a short scheduled batch job rather than an always-on LLM service.

## Status

🚧 Early development. The project is being built in four passes; see [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

Passes 1 and 2 are done: `dailygrad run` fetches news from Hacker News, Hugging Face Daily Papers and RSS feeds, filters it deterministically, then uses a local Ollama model to pick 3–5 stories and summarise each one. The daily micro-lesson is not implemented yet.

## Quick start

Requires Python 3.11 or newer and [Ollama](https://ollama.com).

```sh
ollama pull qwen3.5:4b-q4_K_M

python -m venv .venv
source .venv/bin/activate
pip install -e .
dailygrad run
```

Each run prints the digest to stdout, saves it as `data/digests/YYYY-MM-DD.md`, and records what was shown in `data/dailygrad.db` so later runs do not repeat stories. Log messages go to stderr.

## How a run works

1. Fetch candidates from every source. A source that fails is skipped and named in the digest.
2. Filter without the model: recency, popularity, keywords, deduplication and removal of stories already shown. This leaves about 15 candidates.
3. Ask the model to choose the 3–5 most useful candidates.
4. Get the text of the chosen stories only. Papers use their abstract; other stories are downloaded and extracted with Trafilatura.
5. Ask the model to summarise each story from that text alone: what happened, and why it matters.
6. Write the digest, record history, and unload the model from memory.

A story whose article cannot be fetched is still listed, as a headline.

If a model request fails, the digest is still written, with the affected stories listed as headlines and marked as not summarised. Those stories are not recorded as shown, so a later run can pick them up again. If Ollama cannot be reached at all, the digest lists the top candidates this way.

Exit status:

| Code | Meaning |
|---|---|
| 0 | The digest was produced normally. |
| 1 | A model request failed, so the digest is degraded (or the run crashed). |
| 2 | The configuration is invalid. |

Article URLs and article text are treated as untrusted. Only public `http(s)` addresses are fetched, downloads and extracted text are capped, and the model is told to treat source text as data, not instructions.

## Configuration

DailyGrad works without a config file. To change the defaults, copy [`config.example.toml`](config.example.toml) to `dailygrad.toml` and edit it. The config file is looked up in this order:

1. `dailygrad run --config PATH`
2. the `DAILYGRAD_CONFIG` environment variable
3. `./dailygrad.toml`

`dailygrad.toml` and the `data/` directory are ignored by Git.

## Development

```sh
pip install -e ".[dev]"
pytest
```

The tests fake every source, article and model response. They need no network, Ollama or GPU.

## License

MIT
