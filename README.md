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

🚧 Early development.

See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) for the current implementation plan.

## License

MIT
