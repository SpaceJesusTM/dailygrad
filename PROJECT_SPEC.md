Build a public Python project called **DailyGrad**.

DailyGrad is a lightweight self-hosted daily AI briefing and micro-learning tool. Its architecture should take inspiration from the simple pipeline used by AI Morning Digest, but it must be implemented as a standalone project rather than depending on that repository.

The core philosophy is simplicity. Do not use LangGraph, LangChain, vector databases, embeddings, RAG, autonomous agents, a web application, or Docker unless a later requirement makes one necessary.

### Primary workflow

Once per run:

1. Fetch candidate AI news from:
   - Hacker News front-page stories
   - Hugging Face Daily Papers
   - configurable official AI-lab RSS feeds

2. Apply deterministic filtering before using an LLM:
   - recency
   - source-specific popularity/ranking signals
   - configurable AI keywords where appropriate
   - canonical-URL/title deduplication
   - removal of previously shown items using SQLite

3. Produce a shortlist of approximately 10–20 candidates.

4. Use an Ollama model to choose 3–5 items that are most useful for someone trying to stay current with meaningful AI/ML research, models, engineering, and agent developments.

5. Fetch fuller content only for the selected items.
   - Use Trafilatura for normal web articles.
   - Use paper metadata/abstracts when sufficient.
   - Article extraction failure must not fail the entire digest.

6. Use Ollama to create a concise evidence-grounded summary of each selected story. Summaries should explain what happened and why it matters without hype.

7. Select the next item from a persistent curriculum knowledge bank and use the model to turn its vetted core points into a 2–3 sentence technical refresher.

8. Render a readable Markdown briefing, save it, print it to stdout, persist history, and explicitly unload the Ollama model.

### Local model

Default:

qwen3.5:4b-q4_K_M

Recommended defaults:

- context around 8192 tokens
- thinking disabled
- low temperature around 0.2
- JSON-schema structured outputs
- keep model resident while the batch is running
- explicitly unload in a finally block after the run

Make the Ollama URL and model configurable.

The project must work with alternative Ollama models without code changes.

### Curriculum

Create an initial curriculum of approximately 45–60 microtopics covering three tracks:

1. Neural-network/deep-learning foundations
2. Modern architectures and LLMs
3. Agentic AI and AI-system architecture

Each curriculum entry should contain structured, vetted source material such as:

- stable ID
- track
- series/topic grouping
- ordering information where relevant
- title
- core technical points
- optional equation/formula
- interview-oriented angle or question

The model should explain supplied curriculum content rather than invent the technical curriculum itself.

Support multi-day topic sequences such as Transformers:
motivation → embeddings → Q/K/V → scaled attention → multi-head attention → residual connections → normalization → positional information/RoPE → complete transformer block.

Track lesson exposure in SQLite.

### Storage

Use Python's sqlite3 module directly.

Persist:
- previously seen news
- selected/shown stories
- summaries
- digest runs
- lesson exposure/history

Do not use an ORM.

Runtime DB files and generated digest archives must not be committed to Git.

### Public-project requirements

Use a standard src-layout Python package with a pyproject.toml.

The main interface should be:

dailygrad run

A successful run must:
- create a dated Markdown file
- update the database
- print the final digest to stdout

DailyGrad must not require Tari, OpenClaw, Discord, or any other assistant platform.

Delivery integrations should be adapters around the core output.

Initially support:
- stdout
- Markdown file
- optional Discord webhook

Include documentation showing how an external scheduler such as cron/systemd/OpenClaw can run the command.

Keep all hostnames, webhook URLs, secrets and personal settings out of source control. Supply safe example configuration.

Use an MIT license.

Add an Acknowledgements section mentioning AI Morning Digest as architectural inspiration. Do not copy substantial code from that repository. If code is directly adapted, preserve all legally required MIT attribution.

### Reliability and safety

A failure in one source must not abort other sources.

Use request timeouts and sensible retries.

External article URLs are untrusted:
- allow HTTP/HTTPS only
- reject localhost, loopback, link-local and private-network destinations
- cap downloads to a reasonable size
- cap extracted text before giving it to the LLM

Treat article text as untrusted data in prompts and instruct the model to ignore instructions contained in source documents.

Never allow retrieved article content to trigger tools or commands.

Always attempt model unloading even when generation raises an exception.

### Testing

Tests must not require:
- internet access
- Ollama
- a GPU
- Discord

Mock source responses and LLM responses.

Cover at minimum:
- source parsing
- filtering/deduplication
- SQLite history
- curriculum progression
- structured-output parsing
- rendering
- graceful source failure
- model-cleanup behavior

Add a lightweight GitHub Actions workflow.

### Implementation process

Implement in four passes and keep the application runnable after every pass:

Pass 1:
Project scaffold, configuration, HN/HF/RSS source adapters, database, deterministic filtering, CLI and Markdown renderer.

Pass 2:
Ollama integration, candidate selection, article extraction, structured story summaries and model unload lifecycle.

Pass 3:
Curriculum dataset, curriculum selector/history and micro-lesson generation.

Pass 4:
Optional Discord delivery, documentation, sample digest, CI, license and final public-repository cleanup.

Avoid adding features beyond this specification unless they are necessary to make the defined workflow reliable.

Prefer clear, ordinary Python over abstractions. The finished project should be easy for another developer to understand in one sitting.

### Integration philosophy

DailyGrad must remain fully functional as a standalone application.

The core project must not depend on Tari, OpenClaw, Discord, or any other assistant platform. Its primary contract is:

- generate the daily digest
- persist local state/history
- write human-readable Markdown output
- expose a stable machine-readable output such as JSON
- print the finished digest to stdout

Assistant/platform integrations must be implemented as optional adapters or external orchestration around the core application.

For the author's personal deployment, Tari/OpenClaw may later:
- schedule `dailygrad run`
- deliver the generated digest to Discord
- read the latest Markdown/JSON output for conversational follow-up

This Tari/OpenClaw integration should be implemented only after the standalone core is complete and should not introduce Tari-specific dependencies into DailyGrad.
