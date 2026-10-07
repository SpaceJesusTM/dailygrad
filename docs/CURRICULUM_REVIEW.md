# DailyGrad curriculum review

This is a read-only copy of `src/dailygrad/curriculum.toml`, exported on 2026-10-07 for review.
The wording of every title, point, formula and question is exactly as in that file, which remains
the source of truth. To change the curriculum, edit the TOML file, not this one.

60 topics in 16 series across 3 tracks. Within a track, series and topics are listed in the order they are taught.

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

## Track 1: Neural-network and deep-learning foundations (15 topics)

### Shapes and parameters

#### Tensors, shapes and dimensional reasoning

- **ID:** `nn-tensor-shapes`
- **Position:** part 1 of 2 in this series

**Core points**

- A tensor is an n-dimensional array; its shape lists the size of each axis, for example (batch, sequence, features).
- A linear layer maps (..., d_in) to (..., d_out): it acts only on the last axis and carries every leading axis through unchanged, so (32, 128, 768) through a 768-to-3072 layer becomes (32, 128, 3072).
- Matrix multiplication needs matching inner dimensions: (a, b) @ (b, c) gives (a, c).
- Broadcasting aligns shapes from the right and stretches size-1 axes, a common source of silent bugs: (n,) minus (n, 1) gives (n, n).
- Tracing shapes through a network layer by layer is the quickest way to find a bug or to count parameters.

**Formula:** `(B, T, d_in) @ (d_in, d_out) -> (B, T, d_out)`

**Interview question:** A batch of 32 sequences of 128 tokens with 768-dimensional embeddings enters a linear layer with 3072 outputs. What is the output shape?

#### Parameter counting

- **ID:** `nn-parameter-counting`
- **Position:** part 2 of 2 in this series

**Core points**

- A linear layer from d_in to d_out has d_in * d_out weights plus d_out biases, and an embedding table has vocabulary_size * d_model parameters, often the largest single matrix in a small language model.
- A convolution has k_h * k_w * c_in * c_out weights plus c_out biases, independent of the input image size.
- The canonical (vanilla) transformer block uses standard multi-head attention with four d_model-by-d_model projection matrices and a two-layer MLP with hidden size 4 * d_model. Ignoring biases and normalization parameters, attention holds about 4 * d_model^2 parameters and the MLP about 8 * d_model^2, so the block has roughly 12 * d_model^2 with two thirds of it in the MLP.
- For d_model = 768 that canonical block has about 7 million parameters: roughly 2.4 million in attention and 4.7 million in the MLP.
- Modern LLM architectures may use grouped-query or multi-query attention (GQA or MQA) and gated MLPs such as SwiGLU, so their exact parameter counts and ratios differ from the canonical case.
- Parameter count sets the memory for weights: parameters times bytes per parameter, which is 4 bytes in float32 and 2 in float16.

**Formula:** `linear: d_in * d_out + d_out;  canonical transformer block: about 12 * d_model^2`

**Interview question:** Roughly how many parameters does one canonical transformer block with d_model = 768 have, and where are most of them?

### Backpropagation

#### Computational graphs, the chain rule and backpropagation

- **ID:** `nn-backprop`
- **Position:** part 1 of 2 in this series

**Core points**

- The forward pass evaluates the network as a graph of simple operations and stores the intermediate values each operation will need later.
- The chain rule says the gradient of the loss with respect to an earlier value is the product of the local derivatives along the path to the loss, summed over all paths.
- Backpropagation is reverse-mode automatic differentiation: it applies the chain rule once per node in reverse order, handing each node the gradient of the loss with respect to its output.
- Because each node's gradient is computed once and reused, one reverse sweep yields the gradients of all parameters, at the same asymptotic order of cost as the forward computation.
- Same asymptotic order does not mean equal cost. Ordinarily the backward pass has a larger constant computational cost than the forward pass, because a layer may need gradients with respect to both its inputs and its parameters.
- Reverse mode suits neural networks because there is one scalar output, the loss, and millions of inputs, the parameters; forward mode would need one sweep per parameter.

**Formula:** `dL/dx = dL/dy * dy/dx`

**Interview question:** Why is reverse-mode differentiation efficient for a scalar loss with millions of parameters, and how does the cost of the backward pass compare with the forward pass?

#### Gradients through common layers

- **ID:** `nn-layer-gradients`
- **Position:** part 2 of 2 in this series

**Core points**

- For a linear layer y = W x + b, the gradient with respect to W is the outer product of the upstream gradient and the input x, and the gradient with respect to x is W^T times the upstream gradient.
- ReLU passes the gradient through unchanged where its input was positive and blocks it where its input was negative.
- Softmax followed by cross-entropy has a simple combined gradient with respect to the logits: p - y, the predicted probabilities minus the one-hot target.
- An addition node copies the gradient to both of its inputs, which is why a residual connection gives gradients a direct path backwards.
- The gradient with respect to a tensor always has the same shape as that tensor, a quick check on any derivation.

**Formula:** `y = W x + b:  dL/dW = (dL/dy) x^T,  dL/dx = W^T (dL/dy)`

**Interview question:** What is the gradient of softmax cross-entropy loss with respect to the logits?

### Optimization

#### Gradient descent, SGD and minibatches

- **ID:** `opt-sgd`
- **Position:** part 1 of 3 in this series

**Core points**

- Gradient descent moves the parameters a small step against the gradient of the loss, the direction of steepest local decrease.
- Full-batch gradient descent uses the whole dataset for each step; stochastic gradient descent estimates the gradient from a random minibatch.
- A minibatch gradient is an unbiased but noisy estimate of the full gradient; a larger batch lowers the noise but costs more per step.
- The noise is not purely harmful: it helps the optimizer leave saddle points and is widely observed to act as a mild regularizer.
- One epoch is one pass over the dataset, so it contains dataset_size / batch_size update steps.

**Formula:** `theta <- theta - lr * gradient of L(theta)`

**Interview question:** What changes when you increase the batch size, and why is a noisy minibatch gradient still useful?

#### Learning rate and schedules

- **ID:** `opt-learning-rate`
- **Position:** part 2 of 3 in this series

**Core points**

- The learning rate scales every update: too high and the loss diverges or oscillates, too low and training is slow or stalls.
- It is usually the single most important hyperparameter to tune.
- Warmup raises the learning rate from near zero over the first steps. It is commonly used to stabilize the early stages of transformer training. In that period gradients may be large, and an adaptive optimizer's statistics may still be unreliable.
- Warmup matters most in large or deep training setups. It is a training recipe, not a universal requirement of the architecture.
- Decay is a separate concern: after warmup the rate is lowered, commonly on a cosine or linear schedule, so that late updates are small and the model settles.
- A common recipe for transformers is linear warmup followed by cosine or linear decay.

**Interview question:** Why is learning-rate warmup commonly used in transformer training?

#### Adam and AdamW

- **ID:** `opt-adam`
- **Position:** part 3 of 3 in this series

**Core points**

- Adam keeps an exponential moving average of the gradient (momentum) and of the squared gradient, and divides the first by the square root of the second.
- This gives each parameter its own effective step size: parameters with consistently large gradients take smaller steps.
- Both averages start at zero, so Adam applies a bias correction that matters in the first steps.
- In plain Adam, L2 regularization added to the loss is also divided by the adaptive denominator, so weights with large gradients are decayed less than intended.
- AdamW decouples weight decay: it shrinks the weights directly, outside the adaptive update, and is the default optimizer for transformers.

**Formula:** `m = b1*m + (1-b1)*g;  v = b2*v + (1-b2)*g^2;  theta <- theta - lr * m_hat / (sqrt(v_hat) + eps)`

**Interview question:** What is the difference between Adam with L2 regularization and AdamW?

### Losses and outputs

#### Logits, softmax and probabilities

- **ID:** `loss-softmax`
- **Position:** part 1 of 2 in this series

**Core points**

- Logits are the unnormalized scores a model outputs, one per class or vocabulary token; they can be any real number.
- Softmax exponentiates the logits and divides by their sum, giving positive values that sum to 1.
- Softmax depends only on the differences between logits: adding the same constant to all of them changes nothing.
- Multiplying the logits by a factor greater than 1 sharpens the distribution toward the largest logit; dividing them by a temperature greater than 1 flattens it.
- For numerical stability, implementations compute log-softmax directly with the log-sum-exp trick instead of taking the log of computed probabilities.

**Formula:** `softmax(z)_i = exp(z_i) / sum_j exp(z_j)`

**Interview question:** What happens to a softmax distribution if you add 5 to every logit, and what if you multiply every logit by 5?

#### Cross-entropy and common loss functions

- **ID:** `loss-cross-entropy`
- **Position:** part 2 of 2 in this series

**Core points**

- Cross-entropy for classification is the negative log of the probability the model assigns to the correct class.
- Minimizing it is the same as maximizing the likelihood of the data, and it punishes confident wrong answers heavily.
- A language model's loss is the average cross-entropy per token, and perplexity is the exponential of that loss.
- A model that guesses uniformly over V classes has cross-entropy ln(V), about 10.8 for V = 50,000: a useful sanity check on the loss at initialization.
- Mean squared error is the standard loss for regression; applied to classification probabilities it gives weak gradients when the model is confidently wrong.

**Formula:** `L = -log p(correct class);  perplexity = exp(L)`

**Interview question:** What loss should a freshly initialized language model with a 50,000-token vocabulary show, and why?

### Stable training

#### Activation functions and initialization

- **ID:** `train-activations-init`
- **Position:** part 1 of 3 in this series

**Core points**

- Without a nonlinear activation between them, stacked linear layers collapse into a single linear layer.
- Sigmoid and tanh saturate: for large inputs their slope is near zero, which shrinks gradients. ReLU has slope 1 for positive inputs and avoids this.
- A ReLU unit can die: if its input is always negative its gradient is always zero. GELU and SiLU are smooth alternatives, and GELU is common in transformers.
- Initialization aims to keep the variance of activations and gradients approximately stable from layer to layer, so that signals neither die out nor blow up with depth.
- Xavier (Glorot) initialization uses variance 2 / (fan_in + fan_out) and suits tanh.
- Under the common assumption that a layer's inputs to ReLU are zero-mean and symmetric, ReLU zeroes roughly half of the activations and reduces their second moment by about half; He (Kaiming) initialization uses a weight variance of approximately 2 / fan_in to compensate, which keeps the variance approximately stable rather than exactly constant.

**Formula:** `He initialization: Var(W) = 2 / fan_in`

**Interview question:** Why does He initialization use a variance of 2 / fan_in for ReLU networks?

#### Vanishing and exploding gradients, and gradient clipping

- **ID:** `train-gradient-flow`
- **Position:** part 2 of 3 in this series

**Core points**

- The gradient reaching an early layer is a product of one Jacobian per later layer, so it shrinks or grows geometrically with depth.
- If those factors are mostly below 1 the gradient vanishes and early layers stop learning; if they are above 1 it explodes and training diverges.
- The remedies for vanishing gradients are non-saturating activations, careful initialization, normalization layers and residual connections.
- Gradient clipping handles explosions: if the global gradient norm exceeds a threshold, the whole gradient is rescaled to that norm, keeping its direction.
- Clipping by global norm is standard when training RNNs and transformers. It limits the damage of an occasional huge gradient but does nothing for vanishing gradients.

**Formula:** `if ||g|| > c:  g <- g * c / ||g||`

**Interview question:** What does gradient clipping fix, and what does it not fix?

#### BatchNorm versus LayerNorm

- **ID:** `train-normalization`
- **Position:** part 3 of 3 in this series

**Core points**

- Both normalize activations to zero mean and unit variance and then apply a learned scale and shift; they differ in the axis the statistics are computed over.
- BatchNorm computes statistics per feature across the batch, so each example's output depends on the other examples in its batch.
- BatchNorm behaves differently in training and at inference, where it uses running averages collected during training.
- LayerNorm computes statistics per example across its features, so it is independent of batch size and identical in training and at inference.
- BatchNorm is common in CNNs; LayerNorm is used in transformers, where sequence lengths vary and batch statistics are unreliable.

**Formula:** `y = gamma * (x - mean) / sqrt(var + eps) + beta`

**Interview question:** Why do transformers use LayerNorm instead of BatchNorm?

### Generalization

#### Regularization and dropout

- **ID:** `fit-regularization`
- **Position:** part 1 of 3 in this series

**Core points**

- Regularization is anything that reduces overfitting by limiting how closely a model can fit the training set.
- L2 regularization, or weight decay, penalizes large weights and pulls them toward zero; L1 drives many weights exactly to zero, giving sparsity.
- Dropout zeroes each activation with probability p during training, so the network cannot rely on any single unit.
- With inverted dropout the surviving activations are scaled by 1 / (1 - p) during training, so nothing needs to change at inference, where dropout is switched off.
- More data, data augmentation and early stopping are also regularizers, and often the most effective ones.

**Formula:** `training: y = mask * x / (1 - p), mask ~ Bernoulli(1 - p);  inference: y = x`

**Interview question:** How does dropout behave differently in training and at inference, and why is the scaling needed?

#### Data splits, overfitting and bias/variance

- **ID:** `fit-overfitting`
- **Position:** part 2 of 3 in this series

**Core points**

- The training set fits the parameters, the validation set chooses hyperparameters and the stopping point, and the test set is used once for the final estimate.
- Tuning on the test set, or any leak of test information into training, makes the reported score optimistic.
- Overfitting shows as training loss still falling while validation loss rises; underfitting shows as both being high.
- High bias means the model is too simple or too constrained to fit the pattern; high variance means it fits noise specific to the training set.
- The usual fixes are more capacity or longer training for underfitting, and more data or regularization for overfitting.

**Interview question:** Training loss keeps falling while validation loss starts rising. What is happening and what would you try?

#### Precision, recall, F1 and calibration

- **ID:** `fit-metrics`
- **Position:** part 3 of 3 in this series

**Core points**

- Precision is the share of predicted positives that are truly positive; recall is the share of true positives that were found.
- Raising the decision threshold usually raises precision and lowers recall; the right balance depends on the cost of each kind of error.
- F1 is the harmonic mean of precision and recall, so it is high only when both are.
- Accuracy is misleading on imbalanced data: predicting the majority class for everything can score high while finding no positives, so precision, recall and F1 for the rare class are reported instead.
- A model is calibrated when its confidence matches reality: of the predictions made with 80% confidence, about 80% are correct.

**Formula:** `precision = TP / (TP + FP);  recall = TP / (TP + FN);  F1 = 2PR / (P + R)`

**Interview question:** When is accuracy a misleading metric, and what would you report instead?

## Track 2: Modern architectures, LLMs and inference (23 topics)

### Before transformers

#### CNNs and inductive bias

- **ID:** `arch-cnn`
- **Position:** part 1 of 2 in this series

**Core points**

- A convolution slides a small learned filter over the input, so the same weights are applied at every position.
- This builds in two assumptions: locality (nearby pixels matter most) and translation equivariance (a pattern is detected wherever it appears).
- Weight sharing makes the parameter count independent of image size and far smaller than a fully connected layer.
- Stacking layers and downsampling grows the receptive field, so later layers see larger regions and represent more abstract features.
- An inductive bias like this helps when data is limited; with enough data, less constrained models such as vision transformers can match or beat it.

**Formula:** `output size = floor((n + 2 * padding - kernel) / stride) + 1`

**Interview question:** What inductive biases does a CNN have, and what is the trade-off of building them in?

#### RNNs, LSTMs and GRUs

- **ID:** `arch-rnn`
- **Position:** part 2 of 2 in this series

**Core points**

- A recurrent network reads a sequence one token at a time and updates a hidden state that summarizes everything seen so far.
- The same weights are reused at every step, and training backpropagates through time across the unrolled sequence.
- Gradients are multiplied by the recurrent Jacobian at every step, so over long sequences they vanish or explode and long-range dependencies are hard to learn.
- An LSTM adds a cell state that is updated additively and controlled by input, forget and output gates, giving gradients a more direct path through time.
- A GRU is a simpler variant with two gates, update and reset, and no separate cell state; it performs similarly on many tasks.

**Formula:** `h_t = tanh(W_h h_(t-1) + W_x x_t + b)`

**Interview question:** Why do plain RNNs struggle with long-range dependencies, and how does an LSTM help?

### Transformers

#### Why transformers replaced recurrence

- **ID:** `tf-motivation`
- **Position:** part 1 of 11 in this series

**Core points**

- An RNN must process tokens in order, so training cannot be parallelized across the positions of a sequence.
- Information between distant tokens has to survive many recurrent steps, which makes long-range dependencies hard to learn.
- Self-attention connects every pair of positions directly, so the path between any two tokens has length 1.
- All positions are processed in parallel during training, which uses GPUs efficiently and made training on very large datasets practical.
- The cost is that attention compares every pair of tokens, so compute and memory grow quadratically with sequence length.

**Interview question:** What two limitations of RNNs does self-attention remove, and what does it cost?

#### Tokenization and embeddings

- **ID:** `tf-tokens-embeddings`
- **Position:** part 2 of 11 in this series

**Core points**

- A tokenizer splits text into tokens from a fixed vocabulary and maps each one to an integer ID.
- Subword schemes such as byte-pair encoding build the vocabulary by repeatedly merging frequent pairs, so common words are one token and rare words split into pieces.
- Word-level tokens need a huge vocabulary and cannot represent unseen words; character-level tokens need a tiny vocabulary but make sequences several times longer.
- Subwords sit between the two: any text can be represented, with a vocabulary of only tens of thousands of entries.
- An embedding layer is a lookup table of shape (vocabulary_size, d_model): each token ID selects one learned row.
- The output layer maps the final hidden state back to vocabulary logits, and many models tie its weights to the embedding table.

**Formula:** `token IDs of shape (B, T) -> embeddings of shape (B, T, d_model)`

**Interview question:** Why do language models use subword tokens rather than whole words or single characters?

#### Self-attention: queries, keys and values

- **ID:** `tf-qkv`
- **Position:** part 3 of 11 in this series

**Core points**

- Each token's vector is projected three ways by learned matrices: into a query, a key and a value.
- A token's query is compared with every token's key by dot product; a high score means that token is relevant to it.
- The scores are turned into weights with softmax, and the token's new representation is the weighted sum of all the values.
- The query says what a token is looking for, the key says what a token offers to be matched against, and the value is the content that gets passed along.
- It is called self-attention because the queries, keys and values all come from the same sequence.

**Formula:** `Q = X W_Q,  K = X W_K,  V = X W_V`

**Interview question:** In self-attention, what are the separate roles of the query, the key and the value?

#### Scaled dot-product attention

- **ID:** `tf-scaled-attention`
- **Position:** part 4 of 11 in this series

**Core points**

- Attention scores are the dot products of queries with keys, computed for all pairs at once as the matrix Q K^T of shape (T, T).
- Each row is passed through softmax so that its weights over the sequence sum to 1, and the output is those weights times V.
- The scores are divided by sqrt(d_k), the square root of the key dimension, before the softmax.
- Without scaling, the variance of a dot product grows with d_k; large scores push softmax into a nearly one-hot regime where gradients are tiny.
- Dividing by sqrt(d_k) keeps the scores at roughly unit variance whatever the dimension, which keeps training stable.

**Formula:** `Attention(Q, K, V) = softmax(Q K^T / sqrt(d_k)) V`

**Interview question:** Why is attention scaled by the square root of the key dimension?

#### Causal and padding masks

- **ID:** `tf-masking`
- **Position:** part 5 of 11 in this series

**Core points**

- A mask stops a token attending to certain positions by setting their scores to negative infinity before the softmax, which makes their weights zero.
- A causal mask blocks every position after the current one, so position t can attend only to positions up to t.
- The causal mask lets a decoder train on all positions of a sequence in parallel without seeing the tokens it has to predict.
- A padding mask blocks the filler tokens added to make the sequences in a batch the same length.
- Encoder models such as BERT use no causal mask and see both directions; decoder-only language models always use one.

**Formula:** `scores[i, j] = -inf for j > i  (causal mask)`

**Interview question:** What does the causal mask do, and why is it needed during training?

#### Multi-head attention

- **ID:** `tf-multi-head`
- **Position:** part 6 of 11 in this series

**Core points**

- Instead of one attention operation, the model runs several heads in parallel, each with its own query, key and value projections.
- Each head works in a smaller subspace of size d_model / h, so the total cost is about the same as one full-width head.
- Different heads can attend to different things at once, such as syntax, position or coreference, which a single softmax distribution cannot do.
- The heads' outputs are concatenated back to d_model and mixed by a final linear projection.
- Splitting into heads is a reshape: (B, T, d_model) becomes (B, h, T, d_model / h).

**Formula:** `d_head = d_model / h;  output = W_O * concat(head_1, ..., head_h)`

**Interview question:** Why use several attention heads instead of one larger head?

#### Residual connections

- **ID:** `tf-residuals`
- **Position:** part 7 of 11 in this series

**Core points**

- Each sublayer adds its output to its input, x + f(x), instead of replacing it.
- The addition gives gradients an identity path straight back to earlier layers, which is what makes very deep networks trainable.
- Each layer only has to learn a correction to the current representation, and can start out close to an identity function.
- The running sum is called the residual stream: every layer reads from it and writes back into it.
- A transformer block has two residual connections, one around attention and one around the MLP.

**Formula:** `x <- x + f(x)`

**Interview question:** How do residual connections help train deep networks?

#### LayerNorm and pre-norm

- **ID:** `tf-layernorm`
- **Position:** part 8 of 11 in this series

**Core points**

- LayerNorm normalizes each token's vector to zero mean and unit variance across its features, then applies a learned scale and shift.
- It keeps the scale of activations stable through a deep stack, which keeps optimization stable.
- The original transformer was post-norm: normalization came after the residual addition.
- Modern models are pre-norm: normalization is applied to the input of each sublayer, x + f(norm(x)), leaving the residual path a clean identity.
- Pre-norm trains more stably at depth and depends less on warmup. Many recent models use the cheaper RMSNorm, which rescales without subtracting the mean.

**Formula:** `pre-norm: x <- x + f(LayerNorm(x))`

**Interview question:** What is the difference between pre-norm and post-norm transformers, and why did pre-norm win?

#### The feed-forward (MLP) block

- **ID:** `tf-mlp`
- **Position:** part 9 of 11 in this series

**Core points**

- After attention, each token's vector passes through an MLP applied independently at every position.
- The canonical MLP has two layers: it expands to a hidden size of 4 * d_model, applies a nonlinearity such as GELU, and projects back to d_model.
- Attention moves information between tokens; the MLP transforms the information held at each token.
- In that canonical form the MLP holds about 8 * d_model^2 parameters, roughly two thirds of a block.
- Many modern LLMs use a gated MLP such as SwiGLU instead, which has three weight matrices and a different hidden size, so the exact parameter count and share differ.
- Because it treats positions independently, the same MLP weights are shared across the whole sequence.

**Formula:** `canonical: MLP(x) = W_2 * GELU(W_1 x + b_1) + b_2,  hidden size 4 * d_model`

**Interview question:** What does the MLP block do that attention does not, and how much of a canonical transformer block does it account for?

#### Positional information and RoPE

- **ID:** `tf-positions`
- **Position:** part 10 of 11 in this series

**Core points**

- Attention on its own cannot see word order: if the input tokens are shuffled, the outputs are simply shuffled the same way. This property is called permutation equivariance.
- Position therefore has to be injected. The original transformer added sinusoidal position vectors to the embeddings; other models learn an absolute position embedding.
- Rotary position embedding (RoPE) instead rotates each query and key vector by an angle proportional to its position, inside the attention computation.
- After RoPE is applied, the positional component of a query-key inner product depends on the relative position of the two tokens, while the score still also depends on the content of the query and the key.
- RoPE adds no parameters and is applied in every attention layer rather than once at the input.

**Formula:** `RoPE: rotate pairs of dimensions of q and k by the angle position * theta_i`

**Interview question:** Why does a transformer need positional information, and what does RoPE do differently from added position embeddings?

#### The complete transformer block

- **ID:** `tf-block`
- **Position:** part 11 of 11 in this series

**Core points**

- A decoder-only block does two things in order: masked multi-head self-attention, then an MLP.
- Each is wrapped in a residual connection with normalization on its input: x = x + Attention(Norm(x)), then x = x + MLP(Norm(x)).
- The full model is token embeddings, a stack of N identical blocks, a final normalization, and a linear layer that produces vocabulary logits.
- The tensor shape stays (batch, sequence, d_model) through every block; only the final layer changes it, to (batch, sequence, vocabulary_size).
- Attention mixes information across positions, and the MLP processes each position on its own.

**Formula:** `x = x + Attn(Norm(x));  x = x + MLP(Norm(x))`

**Interview question:** Walk through one pre-norm transformer block: what happens to a token's vector, in order?

### Generation

#### Next-token prediction, teacher forcing and the context window

- **ID:** `lm-next-token`
- **Position:** part 1 of 2 in this series

**Core points**

- An autoregressive language model factorizes the probability of a text into a product of next-token probabilities, each conditioned on all the previous tokens.
- Training uses teacher forcing: the model is given the true previous tokens and predicts the next one at every position.
- The labels are the input tokens shifted by one position: each position's target is the token that follows it, so there is a target for every position that has a following token.
- A sequence of T tokens therefore normally contains T - 1 next-token targets, unless a convention such as an added BOS or EOS token supplies one more.
- Because of the causal mask, the prediction losses for all of those positions are computed in parallel in one forward pass, and the training loss is their average cross-entropy.
- The context window is the maximum number of tokens the model can attend to at once; anything beyond it is invisible unless it is retrieved or summarized back in.

**Formula:** `p(x_1..x_T) = product over t of p(x_t | x_1..x_(t-1))`

**Interview question:** How many next-token targets does a sequence of T tokens normally provide, what can change that count, and why can the losses be computed in one forward pass?

#### Decoding: greedy, temperature, top-k and top-p

- **ID:** `lm-decoding`
- **Position:** part 2 of 2 in this series

**Core points**

- At each step the model outputs a probability distribution over the vocabulary, and the decoding strategy chooses one token from it.
- Greedy decoding always takes the most likely token; it is deterministic but can be repetitive.
- Sampling draws from the distribution. Temperature divides the logits before the softmax: below 1 sharpens the distribution, above 1 flattens it, and as it approaches 0 sampling becomes greedy.
- Top-k sampling keeps only the k most likely tokens; top-p (nucleus) sampling keeps the smallest set of tokens whose probabilities sum to at least p.
- Top-p adapts to the model's confidence: it keeps few tokens when the distribution is peaked and many when it is flat.

**Formula:** `p_i = softmax(z_i / T)`

**Interview question:** What is the difference between top-k and top-p sampling, and what does temperature change?

### Inference

#### The KV cache

- **ID:** `inf-kv-cache`
- **Position:** part 1 of 5 in this series

**Core points**

- Generation produces one token at a time, and each new token attends to all the earlier ones.
- With a causal mask, the keys and values of earlier tokens do not change when new tokens are appended.
- The KV cache stores every layer's key and value vectors for all the tokens processed so far, so each step computes the query, key and value only for the newest token.
- This cuts the work per generated token from reprocessing the whole sequence to processing one token against cached tensors.
- The cost is memory that grows linearly with sequence length. It is also why the first token, which requires processing the whole prompt, is slower than the ones after it.

**Interview question:** What is stored in the KV cache, and why does it make generation faster?

#### KV-cache and VRAM memory

- **ID:** `inf-memory`
- **Position:** part 2 of 5 in this series

**Core points**

- Inference memory is mostly two things: the model weights and the KV cache.
- Weights take parameters times bytes per parameter: a 7-billion-parameter model needs about 14 GB in 16-bit floats and about 3.5 GB at 4 bits.
- The KV cache holds a key tensor and a value tensor per layer for every token: 2 * n_layers * batch * seq_len * n_kv_heads * d_head values in total. Multiplying by the bytes per element gives its memory.
- In standard multi-head attention n_kv_heads equals n_heads, so n_kv_heads * d_head is d_model.
- Grouped-query attention (GQA) and multi-query attention (MQA) use fewer key-value heads than query heads, and therefore reduce KV-cache memory substantially.
- The KV cache grows linearly with both context length and the number of concurrent sequences, so a model that loads without trouble can still run out of memory when the context or the batch grows; at long contexts or large batches the cache can exceed the weights.

**Formula:** `KV values = 2 * n_layers * batch * seq_len * n_kv_heads * d_head;  KV memory = KV values * bytes per element`

**Interview question:** A model fits in VRAM but runs out of memory on long prompts with many concurrent users. What is using the memory?

#### Mixed precision and quantization

- **ID:** `inf-quantization`
- **Position:** part 3 of 5 in this series

**Core points**

- Fewer bits per stored value means less memory and often faster computation.
- Modern large-model training commonly uses mixed precision: most computation runs in 16-bit floats (BF16 or FP16), while higher precision is retained where it is needed.
- Quantization maps weights to low-bit integers, commonly 8 or 4 bits, with a scale factor to convert back; 4-bit weights need one eighth of the memory of 32-bit floats and one quarter of 16-bit floats.
- Post-training quantization is applied to a finished model with no retraining; quantization-aware training simulates the rounding during training to recover accuracy.
- How much quality is lost depends on the model, the quantization method, the task and the calibration data.
- Four-bit inference is often practical, while more aggressive quantization is generally more fragile.

**Formula:** `w is approximated by scale * q, where q is a low-bit integer`

**Interview question:** What is gained and what is risked by running a model with 4-bit quantized weights?

#### Batching and serving: latency versus throughput

- **ID:** `inf-serving`
- **Position:** part 4 of 5 in this series

**Core points**

- Latency is how long one request takes; throughput is how many tokens or requests the system completes per second. Improving one often costs the other.
- For streaming output, latency splits into time to first token and tokens per second after that.
- Batching runs several requests through the model together, which raises throughput because a GPU does much the same work for many sequences as for one.
- Static batching waits to fill a batch and holds every request until the longest one finishes, which hurts latency.
- Continuous batching adds and removes requests from the running batch at every decoding step, so new requests start immediately and the slot of a finished request is reused at once.
- Serving engines such as vLLM and SGLang exist to do this well: continuous batching, careful KV-cache memory management, and reuse of shared prompt prefixes.

**Interview question:** Why do LLM serving engines use continuous batching instead of fixed batches?

#### Data, pipeline and tensor parallelism

- **ID:** `inf-parallelism`
- **Position:** part 5 of 5 in this series

**Core points**

- Data parallelism puts a full copy of the model on each device and gives each a different slice of the batch; in training, the gradients are then averaged.
- It needs the whole model to fit on one device, and it scales throughput rather than model size.
- Splitting one model across devices is called model parallelism. Pipeline parallelism is one form of it and tensor parallelism is another.
- Pipeline parallelism partitions the layers into stages on different devices and passes activations from stage to stage. It may suffer from pipeline bubbles, where stages sit idle, or from stages running one after another.
- Tensor parallelism shards the matrix operations inside each layer across devices, which requires frequent inter-device communication (collective operations) in every layer.
- Which of the two gives the better latency or throughput depends on the model, the batch size, the workload and the interconnect.

**Interview question:** A model is too large for one GPU. What are two ways to split it across devices, and what does each one cost?

### Adapting models

#### Fine-tuning and instruction tuning

- **ID:** `adapt-fine-tuning`
- **Position:** part 1 of 3 in this series

**Core points**

- Pretraining teaches a model general language ability from huge amounts of unlabeled text; fine-tuning continues training on a smaller, task-specific dataset.
- Full fine-tuning updates every weight, usually with a small learning rate so that useful pretrained knowledge is not overwritten, a failure called catastrophic forgetting.
- Fine-tuning changes behavior, style and format reliably; it is a poor way to add facts that change often.
- Instruction tuning fine-tunes on many (instruction, response) pairs, so that a base model which merely continues text learns to follow requests.
- Chat models are instruction-tuned with a fixed chat template, and using the wrong template at inference degrades results.

**Interview question:** What does instruction tuning change about a base language model?

#### LoRA and parameter-efficient fine-tuning

- **ID:** `adapt-lora`
- **Position:** part 2 of 3 in this series

**Core points**

- Parameter-efficient fine-tuning freezes the pretrained weights and trains only a small number of added parameters.
- LoRA assumes the weight update a task needs has low rank, and learns it as the product of two small matrices: delta W = B A.
- For an adapted weight matrix of shape d_out by d_in and rank r, LoRA trains r * (d_in + d_out) parameters instead of d_out * d_in. For a square d-by-d matrix that is 2 * d * r, often well under 1% of the model.
- B is initialized to zero, so training starts from exactly the pretrained model.
- When the learned update B A is merged into the base weight W, the model keeps its original shape and LoRA adds no adapter computation at inference.
- If the adapters are instead kept separate, for switching between tasks or for multi-tenant serving on one base model, some inference overhead can remain.

**Formula:** `W' = W + (alpha / r) * B A,  with B of shape (d_out, r) and A of shape (r, d_in);  trainable parameters = r * (d_in + d_out)`

**Interview question:** When does LoRA add no inference overhead, and how many parameters does it train for one weight matrix?

#### RLHF and DPO

- **ID:** `adapt-preferences`
- **Position:** part 3 of 3 in this series

**Core points**

- Supervised fine-tuning teaches a model to imitate examples; preference optimization teaches it which of two answers people prefer.
- The data is comparisons: for the same prompt, a preferred response and a rejected one.
- Classic RLHF first trains a reward model on those comparisons, then uses reinforcement learning, typically PPO, to make the language model score highly, with a penalty for drifting from the original model.
- DPO (direct preference optimization) skips the reward model and the reinforcement-learning loop: it trains directly on the pairs with a loss that raises the likelihood of the preferred answer relative to the rejected one.
- DPO is simpler and more stable to train, which is why it is widely used for alignment and style tuning.

**Interview question:** How does DPO differ from classic RLHF?

## Track 3: Agentic AI and production AI systems (22 topics)

### Agents

#### LLM versus agent

- **ID:** `agent-definition`
- **Position:** part 1 of 6 in this series

**Core points**

- A plain LLM call maps one input to one output; it cannot act or check its own work.
- An agent runs an LLM in a loop: the model chooses an action, usually a tool call, the system executes it, and the result is fed back for the next decision.
- What defines an agent is that the model decides the control flow: which step comes next and when to stop.
- The loop lets it gather information, recover from errors and handle tasks whose steps cannot be known in advance.
- The price is more model calls, higher latency and cost, and less predictable behavior.

**Interview question:** What is the difference between an LLM call and an agent?

#### Workflow versus agent

- **ID:** `agent-vs-workflow`
- **Position:** part 2 of 6 in this series

**Core points**

- In a workflow, code fixes the sequence of steps and the LLM fills in individual steps; in an agent, the LLM chooses the steps.
- Workflows are predictable, cheaper, faster and far easier to test and debug, because every run follows a known path.
- Agents suit open-ended tasks where the number and order of steps depend on what is discovered along the way.
- A sound default is the simplest design that works: a single call, then a fixed pipeline, and an agent only when the task really needs dynamic decisions.
- If the steps can be written down in advance, it should be a pipeline.

**Interview question:** When would you choose a fixed pipeline over an agent?

#### Structured outputs and tool calling

- **ID:** `agent-tools`
- **Position:** part 3 of 6 in this series

**Core points**

- Structured output constrains the model to emit data in a fixed format, usually JSON matching a schema, so that code can parse it reliably.
- Constrained decoding enforces this by masking, at every step, the tokens that would break the schema. A schema guarantees shape, not correctness.
- Tool calling builds on it: each tool is described by a name, a description and a JSON schema for its arguments.
- The model does not execute anything. It emits a request naming a tool and its arguments; the application validates and runs it, and returns the result as a new message.
- Tool descriptions are prompts: clear names, precise parameter descriptions and few overlapping tools matter as much as the model does.

**Interview question:** When a model makes a tool call, what does the model do and what does the application do?

#### ReAct and planning

- **ID:** `agent-react`
- **Position:** part 4 of 6 in this series

**Core points**

- ReAct interleaves reasoning and acting: the model writes a thought, takes an action, reads the observation, and repeats.
- Reasoning before each action lets it use what it has just observed, which makes it adaptive when results are surprising.
- Plan-and-execute instead writes a full plan first and then carries out the steps, re-planning only if something fails.
- Planning up front uses fewer model calls and keeps a long task on track, but the plan can go stale; step-by-step reasoning adapts better but costs a call per step and can wander.
- Many systems combine them: a short plan for direction, with ReAct-style steps inside it.

**Interview question:** What is the trade-off between ReAct-style step-by-step reasoning and planning a whole task up front?

#### Agent state and memory

- **ID:** `agent-memory`
- **Position:** part 5 of 6 in this series

**Core points**

- A model is stateless between calls: anything it should know must be put back into the context each time.
- State is the working data of the current task: the goal, the steps taken, tool results and what remains to be done. Keeping it explicit, outside the prompt, makes a run resumable and inspectable.
- Short-term memory is what sits in the context window, the recent conversation and tool results. It is limited, and lost when the session ends.
- Persistent memory is stored outside the model, in files or a database, and selected pieces are retrieved into context when relevant.
- The hard problems are deciding what to write, what to retrieve and when to forget; stale or wrong memories mislead the agent.

**Interview question:** What is the difference between an agent's short-term memory and its persistent memory?

#### Context engineering

- **ID:** `agent-context`
- **Position:** part 6 of 6 in this series

**Core points**

- Context engineering is deciding what goes into the model's context window at each step: instructions, tool definitions, retrieved documents, history and state.
- The window is a finite budget and more is not better: irrelevant or contradictory content distracts the model, and quality drops as the context fills.
- Common techniques are retrieving only what is relevant, summarizing or compacting old history, and trimming or clearing bulky tool outputs.
- Large results can be kept outside the context, for example in a file, with only a reference or a summary passed in.
- A stable prefix, with the system prompt and tools first and unchanged between calls, allows prompt caching, which cuts cost and latency.

**Interview question:** An agent's context window is filling up during a long task. What are your options?

### RAG

#### Retrieval and the RAG pipeline

- **ID:** `rag-architecture`
- **Position:** part 1 of 5 in this series

**Core points**

- Retrieval-augmented generation gives a model knowledge it was not trained on by fetching relevant text at query time and putting it in the prompt.
- Offline, documents are split into chunks, each chunk is embedded as a vector, and the vectors are stored in an index.
- At query time the question is embedded, the nearest chunks are retrieved, and the model answers using them as context.
- The model's weights are unchanged, so updating knowledge means updating the index, and answers can cite their sources.
- Answer quality is capped by retrieval: if the right passage is not retrieved, the model cannot use it.

**Interview question:** What happens in the indexing stage and in the query-time stage of a RAG pipeline?

#### Embeddings and chunking for retrieval

- **ID:** `rag-chunking`
- **Position:** part 2 of 5 in this series

**Core points**

- An embedding model maps a text to a vector such that texts with similar meaning are close together, usually measured by cosine similarity.
- Dense retrieval finds chunks by vector similarity and handles paraphrase well; keyword search such as BM25 matches exact terms like names, codes and rare words.
- Hybrid search combines the two and is usually more robust than either alone.
- Chunk size is a trade-off: small chunks match precisely but lose their surrounding context; large chunks keep context but dilute the embedding and use up prompt space.
- Splitting on natural boundaries such as sections and paragraphs, with some overlap, works better than cutting at fixed character counts.

**Formula:** `cosine similarity(a, b) = (a . b) / (|a| |b|)`

**Interview question:** How does chunk size affect retrieval quality?

#### Retrieval quality and reranking

- **ID:** `rag-reranking`
- **Position:** part 3 of 5 in this series

**Core points**

- Retrieval is judged on whether the relevant passages are found and how highly they rank: recall@k, precision@k and mean reciprocal rank are the usual measures.
- First-stage retrieval uses a bi-encoder: the query and the documents are embedded separately, so document vectors are precomputed and search is fast but coarse.
- A reranker is a cross-encoder: it reads the query and one candidate together and scores their relevance, which is far more accurate but too slow to run over a whole corpus.
- The standard pattern is retrieve-then-rerank: fetch a broad set, for example the top 50 to 100, then rerank and keep the best few.
- The first stage should favor recall and the reranker precision, because a reranker cannot recover a passage that was never retrieved.

**Interview question:** Why use a reranker after vector search rather than just retrieving the top few results?

#### Grounding and hallucination

- **ID:** `rag-grounding`
- **Position:** part 4 of 5 in this series

**Core points**

- A hallucination is fluent output that is not supported by the model's sources or by fact.
- Language models are trained to produce plausible continuations, so without the relevant knowledge they tend to produce a plausible guess rather than abstain.
- Grounding ties an answer to supplied evidence: the model is told to answer only from the provided context and to say when the context does not contain the answer.
- Requiring citations to specific passages makes answers checkable, and lets code or a second model verify each claim.
- Grounding reduces hallucination but does not remove it: the model can still misread a passage, blend sources or ignore the context.

**Interview question:** How does grounding reduce hallucination, and why does it not eliminate it?

#### RAG versus fine-tuning

- **ID:** `rag-vs-fine-tuning`
- **Position:** part 5 of 5 in this series

**Core points**

- RAG supplies external information for the model to condition on at query time, without changing the model's weights; fine-tuning primarily changes the model's behavior and capabilities.
- Use RAG for knowledge that is large, private or changing, and when answers must cite sources: updating means re-indexing, not retraining.
- Use fine-tuning to teach a consistent style, format or task skill, or to make a small model good at a narrow job.
- RAG adds retrieval latency and prompt tokens to every request; fine-tuning has an upfront training cost and must be repeated when requirements change.
- They are complementary, and in practice the order to try is prompting, then RAG, then fine-tuning.

**Interview question:** When would RAG be preferable to fine-tuning?

### System design

#### Routing, cascades and cost

- **ID:** `sys-routing`
- **Position:** part 1 of 3 in this series

**Core points**

- Cost and latency are driven by which model is called, how many tokens go in and out, and how many calls a task takes.
- A router classifies each request and sends it to the handler suited to it: a specialized prompt, a tool, or a model of the right size.
- A cascade tries a small, cheap model first and escalates to a larger one only when the first answer fails a confidence or quality check.
- Both rely on most traffic being easy: the cheap path handles the bulk and the expensive model sees only the hard cases.
- In an agent, every tool call is another model round trip that re-reads the context, so fewer, well-chosen calls, made in parallel where possible, cut both latency and cost.

**Interview question:** How would you reduce the cost of an LLM system without lowering quality on hard requests?

#### Model Context Protocol (MCP)

- **ID:** `sys-mcp`
- **Position:** part 2 of 3 in this series

**Core points**

- MCP is an open protocol that standardizes how an LLM application connects to external tools and data sources.
- Without a standard, each of M applications needs custom code for each of N tools; with one, a tool server is written once and works in any compatible client.
- An MCP server exposes tools (functions the model can call), resources (data the application can read) and prompts (reusable templates).
- The client, inside the host application, discovers what a server offers and relays the model's tool calls to it; the model never talks to the server directly.
- MCP standardizes the connection, not the trust: tool descriptions and results from a third-party server are untrusted input.

**Interview question:** What problem does MCP solve, and what does an MCP server expose?

#### Multi-agent systems

- **ID:** `sys-multi-agent`
- **Position:** part 3 of 3 in this series

**Core points**

- A multi-agent system splits a task between several LLM agents, each with its own instructions, tools and context window.
- The common shape is an orchestrator that delegates subtasks to worker agents and combines their results.
- The real benefits are separate context windows, so each agent stays focused and total capacity grows, and parallel work on independent subtasks.
- The costs are several times the token usage, coordination overhead, and information lost at each hand-off, since a worker knows only what it was told.
- It pays off for broad tasks that split into independent parts, such as research across many sources; tightly coupled tasks usually go better with a single agent.

**Interview question:** When is a multi-agent system worth its extra cost, and when is it not?

### Reliability and safety

#### Retries, recovery and idempotency

- **ID:** `rel-retries`
- **Position:** part 1 of 3 in this series

**Core points**

- Tool calls fail in ordinary ways: timeouts, rate limits, malformed arguments. A robust agent expects failures and handles them.
- Transient errors should be retried with exponential backoff and a limit; errors caused by bad arguments should be returned to the model as a message it can correct.
- A retry is safe only if the action is idempotent: doing it twice has the same effect as doing it once.
- Reads are naturally idempotent. Consequential writes such as payments, emails or orders are not, and a timeout does not tell you whether the action happened.
- The fix is an idempotency key: a unique ID sent with the request so that the receiving system can recognize and ignore a duplicate.
- Saving state after each step lets a failed run resume instead of starting over.

**Interview question:** An agent's payment tool call times out. Why is blindly retrying dangerous, and how do you make it safe?

#### Long-horizon reliability

- **ID:** `rel-long-horizon`
- **Position:** part 2 of 3 in this series

**Core points**

- Errors compound across steps: if each step succeeds with probability p, a task of n independent steps succeeds with probability p to the power n.
- At 95% per step, a 20-step task succeeds only about 36% of the time; at 99% per step it succeeds about 82% of the time.
- So an agent can fail often even though every individual tool call looks reliable.
- Other long-task failure modes are drifting from the original goal, losing early information as the context fills, and repeating the same failing action.
- Mitigations are fewer and larger steps, checking results before continuing, checkpoints that allow recovery, and limits on steps and cost.

**Formula:** `P(task succeeds) = p^n`

**Interview question:** Why can a multi-step agent fail even when each individual tool call is reliable?

#### Prompt injection and guardrails

- **ID:** `rel-prompt-injection`
- **Position:** part 3 of 3 in this series

**Core points**

- A model reads instructions and data in the same channel, so text inside a web page, document or tool result can be written to look like instructions.
- Prompt injection is when such untrusted content hijacks the model; it is called indirect when the attacker plants it somewhere the agent will later read.
- The danger grows with capability: an agent that both reads untrusted content and can take consequential actions or reach private data can be steered into misusing them.
- No prompt reliably prevents it, so defenses are layered: treat all retrieved and tool content as untrusted, give tools least privilege, and require human approval for consequential actions.
- Guardrails are checks outside the main model: input and output filters, schema and policy validation, and allow-lists for what tools may do. They limit the damage when the model is fooled.

**Interview question:** What is indirect prompt injection, and why can it not be solved with a better system prompt?

### Evaluation

#### Evaluation datasets and graders

- **ID:** `eval-datasets`
- **Position:** part 1 of 5 in this series

**Core points**

- An evaluation is a fixed set of inputs, a way to run the system on them, and a grader that scores each output.
- The dataset should reflect real usage: build it from real queries and observed failures, cover edge cases, and keep it separate from anything used to tune prompts.
- Deterministic graders are code: exact match, regular expressions, schema validation, unit tests. They are cheap, fast and reproducible, but fit only outputs with a checkable right answer.
- Model-based graders use an LLM to score open-ended qualities such as helpfulness or faithfulness; they are flexible but noisier, and must themselves be validated.
- Prefer a deterministic grader wherever one is possible, and reserve model grading for what code cannot judge.

**Interview question:** When would you use a deterministic grader and when a model-based one?

#### LLM-as-a-judge and its limits

- **ID:** `eval-llm-judge`
- **Position:** part 2 of 5 in this series

**Core points**

- An LLM judge scores another model's output against a rubric, which scales the evaluation of open-ended text far beyond human review.
- Judges have systematic biases: they favor longer answers, the first option in a comparison, fluent but wrong text, and outputs from their own model family.
- Scores are noisy and sensitive to the wording of the rubric, so small differences between systems may not be real.
- A judge must be validated against human labels on a sample before it is trusted, and re-checked whenever the judge model or prompt changes.
- Reliability improves with a specific rubric, binary or few-level scales rather than 1 to 10, asking for reasoning before the score, and swapping the order in pairwise comparisons.

**Interview question:** What are the main failure modes of using an LLM as a judge, and how do you guard against them?

#### Evaluating RAG

- **ID:** `eval-rag`
- **Position:** part 3 of 5 in this series

**Core points**

- A RAG system has two parts that fail differently, so they are evaluated separately: retrieval and generation.
- Retrieval is measured by whether the passages needed for the answer were fetched: recall@k and ranking metrics against labeled relevant passages.
- Generation is measured by faithfulness (every claim is supported by the retrieved context) and answer relevance (it actually addresses the question).
- End-to-end correctness against a reference answer shows whether the whole system works but not which part failed.
- The split directs the fix: low retrieval recall means working on chunking, embeddings or search; high recall with wrong answers means working on the prompt or the model.

**Interview question:** A RAG system gives a wrong answer. How do you tell whether retrieval or generation is at fault?

#### Evaluating agents

- **ID:** `eval-agents`
- **Position:** part 4 of 5 in this series

**Core points**

- An agent is judged mainly on outcome: did it reach the correct final state, for example the right record in the database or tests that pass.
- Checking the end state is more robust than checking the path, because there are usually many valid sequences of steps.
- The trajectory still matters for diagnosis and efficiency: the number of steps, tool-call errors, cost, and whether it took unsafe actions.
- Agents are non-deterministic, so each task should be run several times and reported as a success rate, not a single pass or fail.
- Evaluation needs a controlled environment that is reset between runs, so that results are reproducible and actions have no real side effects.

**Interview question:** Why evaluate an agent on its final outcome rather than on the exact steps it took?

#### Observability and debugging

- **ID:** `eval-observability`
- **Position:** part 5 of 5 in this series

**Core points**

- An LLM system can fail silently and differently each time, so debugging depends on having a record of what each run did.
- A trace should, as a recommendation and not a strict requirement, capture enough to reconstruct and debug a run: the model and prompt version, the tool calls, timing, token usage, costs and errors.
- The content of prompts, responses and tool results should be logged only where that is permitted, with redaction, access control and retention policies appropriate for secrets and sensitive data.
- Most failures are found by reading traces: the cause is usually visible as missing context, a misleading tool result or an ambiguous instruction.
- Aggregate metrics such as latency, cost, error rate and tool-failure rate show where to look; traces show why.
- Production failures should be turned into evaluation cases, so that a fix is verified and the problem cannot quietly return.

**Interview question:** What should a trace of an LLM system capture so that a failed run can be debugged, and what limits apply to logging content?
