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

Pass 1 is done: `dailygrad run` fetches news from Hacker News, Hugging Face Daily Papers and RSS feeds, filters it deterministically, and writes a Markdown digest listing the shortlisted stories. Model-based selection, summaries and the daily micro-lesson are not implemented yet.

## Quick start

Requires Python 3.11 or newer.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
dailygrad run
```

Each run prints the digest to stdout, saves it as `data/digests/YYYY-MM-DD.md`, and records what was shown in `data/dailygrad.db` so later runs do not repeat stories. Log messages go to stderr.

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

The tests use canned responses and never touch the network.

## License

MIT
