# DailyGrad lesson output review

One generated micro-lesson for each of the 60 curriculum topics, for checking against
`docs/CURRICULUM_REVIEW.md`. The lessons are unedited model output.

How these were produced:

- Model `qwen3.5:4b-q4_K_M` on Ollama 0.40.0, thinking off, on 2026-10-07.
- 13 lessons, marked "regenerated" below, were generated after the technical corrections to their curriculum entries. They use the current lesson prompt, including the rule against strengthening claims, at temperature 0. At temperature 0 the output is reproducible, so these are what a real digest would show.
- The other 47 lessons are from the earlier full pass and were deliberately not regenerated. Their curriculum entries are unchanged, but they were produced with the earlier prompt, before that rule was added, at temperature 0.2. A real digest would now word them differently.

Topics are grouped by track and series, in the same order as the curriculum review. "Taught as lesson N" is the
topic's position in the daily schedule. The question is the curriculum's interview question, which is not shown
with the lesson: it is asked later as a **Quick recall** question.

- **Track 1: Neural-network and deep-learning foundations** (15 topics)
  - Shapes and parameters (2)
  - Backpropagation (2)
  - Optimization (3)
  - Losses and outputs (2)
  - Stable training (3)
  - Generalization (3)
- **Track 2: Modern architectures, LLMs and inference** (23 topics)
  - Before transformers (2)
  - Transformers (11)
  - Generation (2)
  - Inference (5)
  - Adapting models (3)
- **Track 3: Agentic AI and production AI systems** (22 topics)
  - Agents (6)
  - RAG (5)
  - System design (3)
  - Reliability and safety (3)
  - Evaluation (5)

## Track 1: Neural-network and deep-learning foundations

### Shapes and parameters

#### Tensors, shapes and dimensional reasoning

`nn-tensor-shapes` · taught as lesson 1

> A linear layer maps input (..., d_in) to output (..., d_out) by acting only on the last axis while carrying leading axes unchanged. Applying a 768-to-3072 layer to shape (32, 128, 768) produces (32, 128, 3072).

**Question:** A batch of 32 sequences of 128 tokens with 768-dimensional embeddings enters a linear layer with 3072 outputs. What is the output shape?

#### Parameter counting

`nn-parameter-counting` · taught as lesson 2 · regenerated after its curriculum entry was corrected

> A canonical transformer block has roughly 12 * d_model^2 parameters, with about two thirds located in its MLP layer. For d_model = 768 this totals approximately 7 million parameters, where the MLP holds 4.7 million and attention holds 2.4 million.

**Question:** Roughly how many parameters does one canonical transformer block with d_model = 768 have, and where are most of them?

### Backpropagation

#### Computational graphs, the chain rule and backpropagation

`nn-backprop` · taught as lesson 11 · regenerated after its curriculum entry was corrected

> Backpropagation applies the chain rule once per node in reverse order to compute gradients for all parameters using a single sweep. This yields gradients at the same asymptotic order of cost as the forward computation, though the backward pass typically has a larger constant cost due to computing gradients for both inputs and parameters.

**Question:** Why is reverse-mode differentiation efficient for a scalar loss with millions of parameters, and how does the cost of the backward pass compare with the forward pass?

#### Gradients through common layers

`nn-layer-gradients` · taught as lesson 12

> Softmax followed by cross-entropy yields a combined gradient equal to p minus y, where p is predicted probabilities and y is the one-hot target. This simple form applies directly to the logits input of the softmax layer.

**Question:** What is the gradient of softmax cross-entropy loss with respect to the logits?

### Optimization

#### Gradient descent, SGD and minibatches

`opt-sgd` · taught as lesson 19

> Increasing batch size lowers noise but raises cost per step while reducing update steps per epoch. A noisy minibatch gradient remains useful because it helps the optimizer escape saddle points and acts as a mild regularizer.

**Question:** What changes when you increase the batch size, and why is a noisy minibatch gradient still useful?

#### Learning rate and schedules

`opt-learning-rate` · taught as lesson 20 · regenerated after its curriculum entry was corrected

> Warmup raises the learning rate from near zero over the first steps to stabilize early training when gradients may be large and adaptive optimizer statistics are unreliable. This approach matters most in large or deep training setups, though it is a recipe rather than a universal requirement of the architecture.

**Question:** Why is learning-rate warmup commonly used in transformer training?

#### Adam and AdamW

`opt-adam` · taught as lesson 21

> In plain Adam, L2 regularization is divided by the adaptive denominator, causing large-gradient weights to decay less than intended. AdamW shrinks weights directly outside the adaptive update, decoupling weight decay from the gradient statistics.

**Question:** What is the difference between Adam with L2 regularization and AdamW?

### Losses and outputs

#### Logits, softmax and probabilities

`loss-softmax` · taught as lesson 30

> Adding 5 to every logit changes nothing in the softmax distribution because softmax depends only on differences between logits. Multiplying every logit by 5 sharpens the distribution toward the largest logit since the factor is greater than 1.

**Question:** What happens to a softmax distribution if you add 5 to every logit, and what if you multiply every logit by 5?

#### Cross-entropy and common loss functions

`loss-cross-entropy` · taught as lesson 31

> A uniformly guessing model over V classes has cross-entropy equal to ln(V). For a 50,000 token vocabulary, this yields approximately 10.8 loss. Perplexity is the exponential of that average cross-entropy per token.

**Question:** What loss should a freshly initialized language model with a 50,000-token vocabulary show, and why?

### Stable training

#### Activation functions and initialization

`train-activations-init` · taught as lesson 39 · regenerated after its curriculum entry was corrected

> Under the assumption that ReLU inputs are zero-mean and symmetric, it zeroes roughly half activations and reduces their second moment by about half. He initialization uses a weight variance of approximately 2 / fan_in to compensate for this reduction and keep the variance approximately stable rather than exactly constant.

**Question:** Why does He initialization use a variance of 2 / fan_in for ReLU networks?

#### Vanishing and exploding gradients, and gradient clipping

`train-gradient-flow` · taught as lesson 40

> Gradient clipping fixes exploding gradients by rescaling the global norm when it exceeds a threshold c. It does not fix vanishing gradients because shrinking factors below one remain unaddressed. This remedy limits damage from occasional huge gradients while preserving direction.

**Question:** What does gradient clipping fix, and what does it not fix?

#### BatchNorm versus LayerNorm

`train-normalization` · taught as lesson 41

> Transformers use LayerNorm because it computes statistics per example across features rather than per feature across the batch. This makes normalization independent of batch size and identical in training and inference, unlike BatchNorm which relies on running averages.

**Question:** Why do transformers use LayerNorm instead of BatchNorm?

### Generalization

#### Regularization and dropout

`fit-regularization` · taught as lesson 53

> During training, dropout zeroes activations with probability p and scales survivors by 1 / (1 - p) using inverted dropout. This scaling compensates for reduced signal so inference output y = x matches training expectations without modification.

**Question:** How does dropout behave differently in training and at inference, and why is the scaling needed?

#### Data splits, overfitting and bias/variance

`fit-overfitting` · taught as lesson 54

> Overfitting occurs when training loss continues to fall while validation loss rises. This indicates the model fits noise specific to the training set rather than the general pattern. You would try adding more data or applying regularization to reduce variance.

**Question:** Training loss keeps falling while validation loss starts rising. What is happening and what would you try?

#### Precision, recall, F1 and calibration

`fit-metrics` · taught as lesson 55

> Accuracy is misleading on imbalanced data because predicting the majority class scores high while finding no positives. Instead, precision, recall, and F1 for the rare class are reported. F1 equals 2PR divided by P plus R, so it is high only when both precision and recall are high.

**Question:** When is accuracy a misleading metric, and what would you report instead?

## Track 2: Modern architectures, LLMs and inference

### Before transformers

#### CNNs and inductive bias

`arch-cnn` · taught as lesson 3

> A convolution applies the same weights at every position to build locality and translation equivariance. Weight sharing keeps the parameter count independent of image size while reducing it compared to fully connected layers.

**Question:** What inductive biases does a CNN have, and what is the trade-off of building them in?

#### RNNs, LSTMs and GRUs

`arch-rnn` · taught as lesson 4

> Plain RNNs multiply gradients by the recurrent Jacobian at each step, causing them to vanish or explode over long sequences. An LSTM adds a cell state updated additively with input, forget, and output gates, providing a more direct path for gradients through time.

**Question:** Why do plain RNNs struggle with long-range dependencies, and how does an LSTM help?

### Transformers

#### Why transformers replaced recurrence

`tf-motivation` · taught as lesson 8

> Self-attention removes the requirement that RNNs process tokens in order by connecting every pair of positions directly with path length 1. It also eliminates the difficulty of learning long-range dependencies because information between distant tokens no longer needs to survive many recurrent steps. The cost is that compute and memory grow quadratically with sequence length since attention compares every pair of tokens.

**Question:** What two limitations of RNNs does self-attention remove, and what does it cost?

#### Tokenization and embeddings

`tf-tokens-embeddings` · taught as lesson 9

> Subword schemes merge frequent pairs to create a vocabulary of tens of thousands, avoiding the huge size needed for word-level tokens. This approach represents any text while keeping sequences shorter than character-level tokenization. The embedding layer maps these token IDs to learned rows in a table of shape (vocabulary_size, d_model).

**Question:** Why do language models use subword tokens rather than whole words or single characters?

#### Self-attention: queries, keys and values

`tf-qkv` · taught as lesson 10

> The query defines what a token is looking for, while the key indicates what it offers to be matched against via dot product scores. The value contains the content that gets passed along after the scores are turned into weights with softmax. All three projections come from the same sequence using learned matrices W_Q, W_K, and W_V.

**Question:** In self-attention, what are the separate roles of the query, the key and the value?

#### Scaled dot-product attention

`tf-scaled-attention` · taught as lesson 16

> Dividing scores by sqrt(d_k) keeps their variance at roughly unit variance regardless of d_k. Without this scaling, dot product variance grows with d_k, pushing softmax into a one-hot regime with tiny gradients.

**Question:** Why is attention scaled by the square root of the key dimension?

#### Causal and padding masks

`tf-masking` · taught as lesson 17

> The causal mask sets scores[i, j] to -inf for j > i, forcing weights to zero for future positions. This prevents position t from attending to any position after it during training. It allows the decoder to train on all sequence positions in parallel without seeing tokens it must predict.

**Question:** What does the causal mask do, and why is it needed during training?

#### Multi-head attention

`tf-multi-head` · taught as lesson 18

> Multiple heads run in parallel with smaller subspace sizes d_model / h to achieve a total cost similar to a single full-width head. Different heads attend simultaneously to distinct patterns like syntax or position, which a single softmax distribution cannot capture. The outputs are concatenated and projected back to d_model using output = W_O * concat(head_1, ..., head_h).

**Question:** Why use several attention heads instead of one larger head?

#### Residual connections

`tf-residuals` · taught as lesson 25

> The addition of sublayer output to input creates an identity path for gradients, making very deep networks trainable. Each layer learns a correction to the current representation within the residual stream defined by x <- x + f(x).

**Question:** How do residual connections help train deep networks?

#### LayerNorm and pre-norm

`tf-layernorm` · taught as lesson 26

> The original transformer used post-norm where normalization followed residual addition, while modern models use pre-norm with the formula x <- x + f(LayerNorm(x)). Pre-norm trains more stably at depth and depends less on warmup by keeping activation scales stable through a deep stack.

**Question:** What is the difference between pre-norm and post-norm transformers, and why did pre-norm win?

#### The feed-forward (MLP) block

`tf-mlp` · taught as lesson 27 · regenerated after its curriculum entry was corrected

> The MLP transforms information held at each token independently, whereas attention moves information between tokens. In the canonical form, this block expands to a hidden size of 4 * d_model and holds about 8 * d_model^2 parameters, which is roughly two thirds of the block.

**Question:** What does the MLP block do that attention does not, and how much of a canonical transformer block does it account for?

#### Positional information and RoPE

`tf-positions` · taught as lesson 32 · regenerated after its curriculum entry was corrected

> Transformers lack inherent word order due to permutation equivariance, requiring injected positional data. Unlike static absolute embeddings, RoPE rotates query and key vectors by an angle proportional to position within every attention layer.

**Question:** Why does a transformer need positional information, and what does RoPE do differently from added position embeddings?

#### The complete transformer block

`tf-block` · taught as lesson 33

> A decoder-only block first applies normalization then masked multi-head self-attention to mix information across positions. It then applies normalization followed by an MLP to process each position independently. The tensor shape remains (batch, sequence, d_model) throughout both operations.

**Question:** Walk through one pre-norm transformer block: what happens to a token's vector, in order?

### Generation

#### Next-token prediction, teacher forcing and the context window

`lm-next-token` · taught as lesson 37 · regenerated after its curriculum entry was corrected

> A sequence of T tokens normally provides T - 1 next-token targets unless a convention like BOS or EOS adds one. Because the causal mask allows parallel computation, the average cross-entropy loss is computed in a single forward pass.

**Question:** How many next-token targets does a sequence of T tokens normally provide, what can change that count, and why can the losses be computed in one forward pass?

#### Decoding: greedy, temperature, top-k and top-p

`lm-decoding` · taught as lesson 38

> Top-k sampling keeps only the k most likely tokens, while top-p sampling retains the smallest set of tokens whose probabilities sum to at least p. Temperature changes the distribution by dividing logits before softmax: values below 1 sharpen it and values above 1 flatten it.

**Question:** What is the difference between top-k and top-p sampling, and what does temperature change?

### Inference

#### The KV cache

`inf-kv-cache` · taught as lesson 45

> The KV cache stores every layer's key and value vectors for all tokens processed so far. This allows each new token to compute its query against cached tensors instead of reprocessing the whole sequence, cutting work per token significantly.

**Question:** What is stored in the KV cache, and why does it make generation faster?

#### KV-cache and VRAM memory

`inf-memory` · taught as lesson 46 · regenerated after its curriculum entry was corrected

> Inference memory consists of model weights and the KV cache, which grows linearly with context length and batch size. The KV cache holds key and value tensors per layer for every token, calculated as 2 * n_layers * batch * seq_len * n_kv_heads * d_head values multiplied by bytes per element.

**Question:** A model fits in VRAM but runs out of memory on long prompts with many concurrent users. What is using the memory?

#### Mixed precision and quantization

`inf-quantization` · taught as lesson 47 · regenerated after its curriculum entry was corrected

> Running a model with 4-bit weights reduces memory usage to one quarter of 16-bit floats and often speeds up computation. The risk is that quality loss depends on the model, task, and calibration data, making aggressive quantization generally more fragile.

**Question:** What is gained and what is risked by running a model with 4-bit quantized weights?

#### Batching and serving: latency versus throughput

`inf-serving` · taught as lesson 51

> Continuous batching adds and removes requests at every decoding step so new requests start immediately. This avoids the latency penalty of static batching, which holds requests until the longest one finishes. The approach reuses finished slots instantly while maintaining high throughput.

**Question:** Why do LLM serving engines use continuous batching instead of fixed batches?

#### Data, pipeline and tensor parallelism

`inf-parallelism` · taught as lesson 52 · regenerated after its curriculum entry was corrected

> Pipeline parallelism partitions layers into stages, while tensor parallelism shards matrix operations inside each layer. Pipeline parallelism may suffer from pipeline bubbles or sequential stage execution, whereas tensor parallelism requires frequent inter-device collective operations in every layer.

**Question:** A model is too large for one GPU. What are two ways to split it across devices, and what does each one cost?

### Adapting models

#### Fine-tuning and instruction tuning

`adapt-fine-tuning` · taught as lesson 56

> Instruction tuning fine-tunes on many (instruction, response) pairs so that a base model which merely continues text learns to follow requests. Chat models are instruction-tuned with a fixed chat template, and using the wrong template at inference degrades results.

**Question:** What does instruction tuning change about a base language model?

#### LoRA and parameter-efficient fine-tuning

`adapt-lora` · taught as lesson 57 · regenerated after its curriculum entry was corrected

> LoRA adds no inference overhead when the learned update B A is merged into the base weight W, keeping the model's original shape. For a weight matrix of shape d_out by d_in and rank r, it trains r * (d_out + d_in) parameters.

**Question:** When does LoRA add no inference overhead, and how many parameters does it train for one weight matrix?

#### RLHF and DPO

`adapt-preferences` · taught as lesson 58

> Classic RLHF trains a reward model on comparisons then uses PPO to optimize scores while penalizing drift. DPO skips the reward model and reinforcement-learning loop, training directly on pairs with a loss that raises the likelihood of the preferred answer relative to the rejected one.

**Question:** How does DPO differ from classic RLHF?

## Track 3: Agentic AI and production AI systems

### Agents

#### LLM versus agent

`agent-definition` · taught as lesson 5

> A plain LLM maps one input to one output without acting or checking work, while an agent runs an LLM in a loop where the model decides control flow. The agent executes tool calls, feeds results back for the next decision, and handles unknown steps but incurs higher latency and cost.

**Question:** What is the difference between an LLM call and an agent?

#### Workflow versus agent

`agent-vs-workflow` · taught as lesson 6

> Choose a fixed pipeline when the number and order of steps can be written down in advance. Pipelines are predictable, cheaper, faster, and easier to test because every run follows a known path. Use an agent only when task requirements depend on discoveries made along the way.

**Question:** When would you choose a fixed pipeline over an agent?

#### Structured outputs and tool calling

`agent-tools` · taught as lesson 7

> The model emits a request naming a tool and its arguments without executing anything. The application validates these arguments against the JSON schema and runs the tool, returning the result as a new message.

**Question:** When a model makes a tool call, what does the model do and what does the application do?

#### ReAct and planning

`agent-react` · taught as lesson 13

> ReAct interleaves thought, action, and observation to adapt when results are surprising by using what it has just observed. Planning up front uses fewer model calls and keeps a long task on track but can go stale, while step-by-step reasoning adapts better at the cost of a call per step.

**Question:** What is the trade-off between ReAct-style step-by-step reasoning and planning a whole task up front?

#### Agent state and memory

`agent-memory` · taught as lesson 14

> Short-term memory sits in the context window and includes recent conversation and tool results, but it is limited and lost when the session ends. Persistent memory is stored outside the model in files or a database, where selected pieces are retrieved into context when relevant. The hard problem is deciding what to write, retrieve, and forget because stale or wrong memories mislead the agent.

**Question:** What is the difference between an agent's short-term memory and its persistent memory?

#### Context engineering

`agent-context` · taught as lesson 15

> Options include retrieving only relevant content, summarizing or compacting old history, and trimming bulky tool outputs. Large results can be kept outside the context with only a reference or summary passed in. A stable prefix allows prompt caching to cut cost and latency.

**Question:** An agent's context window is filling up during a long task. What are your options?

### RAG

#### Retrieval and the RAG pipeline

`rag-architecture` · taught as lesson 22

> Offline, documents are split into chunks, each chunk is embedded as a vector, and the vectors are stored in an index. At query time the question is embedded, the nearest chunks are retrieved, and the model answers using them as context.

**Question:** What happens in the indexing stage and in the query-time stage of a RAG pipeline?

#### Embeddings and chunking for retrieval

`rag-chunking` · taught as lesson 23

> Small chunks match precisely but lose surrounding context, while large chunks keep context but dilute the embedding and use up prompt space. Splitting on natural boundaries with overlap works better than cutting at fixed character counts.

**Question:** How does chunk size affect retrieval quality?

#### Retrieval quality and reranking

`rag-reranking` · taught as lesson 24

> Vector search uses bi-encoders for fast, coarse retrieval but lacks precision. A reranker employs cross-encoders to score query-candidate pairs more accurately at the cost of speed. The standard pattern retrieves many candidates first, then reranks them to keep only the best few.

**Question:** Why use a reranker after vector search rather than just retrieving the top few results?

#### Grounding and hallucination

`rag-grounding` · taught as lesson 28

> Grounding reduces hallucination by tying answers to supplied evidence and requiring citations for verification. It does not eliminate hallucination because models can still misread passages, blend sources, or ignore context.

**Question:** How does grounding reduce hallucination, and why does it not eliminate it?

#### RAG versus fine-tuning

`rag-vs-fine-tuning` · taught as lesson 29 · regenerated after its curriculum entry was corrected

> RAG supplies external information for the model to condition on at query time without changing the model's weights, while fine-tuning primarily changes the model's behavior and capabilities. Use RAG for knowledge that is large, private or changing, and when answers must cite sources since updating means re-indexing rather than retraining.

**Question:** When would RAG be preferable to fine-tuning?

### System design

#### Routing, cascades and cost

`sys-routing` · taught as lesson 34

> Cost is driven by which model is called, token counts, and call frequency. A cascade tries a small, cheap model first and escalates only when confidence or quality fails. Most traffic stays on the cheap path while the expensive model handles hard cases.

**Question:** How would you reduce the cost of an LLM system without lowering quality on hard requests?

#### Model Context Protocol (MCP)

`sys-mcp` · taught as lesson 35

> MCP solves the problem where each application requires custom code for every tool by standardizing connections between LLM applications and external sources. An MCP server exposes tools, resources, and prompts to enable clients to discover capabilities without direct model access to the server.

**Question:** What problem does MCP solve, and what does an MCP server expose?

#### Multi-agent systems

`sys-multi-agent` · taught as lesson 36

> A multi-agent system splits a task between several LLM agents with separate context windows to enable parallel work on independent subtasks. This architecture pays off for broad tasks that split into independent parts, but costs more due to token usage and information lost at hand-offs. Tightly coupled tasks usually go better with a single agent because coordination overhead outweighs the benefits of parallelism.

**Question:** When is a multi-agent system worth its extra cost, and when is it not?

### Reliability and safety

#### Retries, recovery and idempotency

`rel-retries` · taught as lesson 42

> Blindly retrying a payment is dangerous because payments are consequential writes that are not idempotent, meaning doing them twice causes different effects than once. A timeout does not indicate whether the action succeeded or failed, so a duplicate request could charge twice. Safety requires an idempotency key to recognize and ignore duplicates, combined with saving state after each step to resume instead of restarting.

**Question:** An agent's payment tool call times out. Why is blindly retrying dangerous, and how do you make it safe?

#### Long-horizon reliability

`rel-long-horizon` · taught as lesson 43

> Errors compound across steps, meaning a task of n independent steps succeeds with probability p to the power n. At 95% per step, a 20-step task succeeds only about 36% of the time despite individual reliability. Mitigations include fewer larger steps, checking results before continuing, and limits on steps and cost.

**Question:** Why can a multi-step agent fail even when each individual tool call is reliable?

#### Prompt injection and guardrails

`rel-prompt-injection` · taught as lesson 44

> Indirect prompt injection occurs when untrusted content planted in retrieved data hijacks the model during inference. Since models read instructions and data in the same channel, no single system prompt can reliably prevent this attack. Therefore, defenses must layer guardrails such as input filters and least-privilege tool access.

**Question:** What is indirect prompt injection, and why can it not be solved with a better system prompt?

### Evaluation

#### Evaluation datasets and graders

`eval-datasets` · taught as lesson 48

> Use a deterministic grader when outputs have a checkable right answer, such as with exact match or schema validation. Reserve model-based graders for open-ended qualities like helpfulness where code cannot judge the result.

**Question:** When would you use a deterministic grader and when a model-based one?

#### LLM-as-a-judge and its limits

`eval-llm-judge` · taught as lesson 49

> LLM judges exhibit systematic biases favoring longer answers, fluent but wrong text, and outputs from their own model family while scores remain noisy and sensitive to rubric wording. Guard against these failures by validating the judge against human labels before trust and re-checking whenever the model or prompt changes.

**Question:** What are the main failure modes of using an LLM as a judge, and how do you guard against them?

#### Evaluating RAG

`eval-rag` · taught as lesson 50

> Evaluate retrieval using recall@k and ranking metrics against labeled relevant passages to check if needed content was fetched. Measure generation by faithfulness, ensuring every claim is supported by retrieved context, and answer relevance to verify it addresses the question. End-to-end correctness confirms system failure but does not identify whether the fault lies in retrieval or generation.

**Question:** A RAG system gives a wrong answer. How do you tell whether retrieval or generation is at fault?

#### Evaluating agents

`eval-agents` · taught as lesson 59

> An agent is judged mainly on whether it reached the correct final state, such as the right database record or passing tests. Checking the end state is more robust than checking the path because there are usually many valid sequences of steps.

**Question:** Why evaluate an agent on its final outcome rather than on the exact steps it took?

#### Observability and debugging

`eval-observability` · taught as lesson 60 · regenerated after its curriculum entry was corrected

> A trace should capture enough to reconstruct and debug a run: the model and prompt version, tool calls, timing, token usage, costs, and errors. Logging prompts, responses, and tool results is permitted only where appropriate, using redaction, access control, and retention policies for secrets and sensitive data.

**Question:** What should a trace of an LLM system capture so that a failed run can be debugged, and what limits apply to logging content?
