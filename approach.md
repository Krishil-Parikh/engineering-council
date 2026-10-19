I'll read the dataset paper and your project notes, look at the actual recordings, then survey the Mamba and ASR-aware speech enhancement literature before proposing anything.

I treated this as a reviewer's gap analysis. I checked the three clips you attached, read the TacRFC paper, and went through the Mamba speech enhancement (SE) work and the work on SE for speech recognition (ASR). Two notes on inputs:

- **Missing files:** no folder or transcription CSV came through, only the three MP3s. `record1_a` and `record1_b` are byte-identical, so I really had two recordings.
- **Unclear paper names:** I couldn't find a speech enhancement paper called LC-Mamba. "USC-Mamba" is most likely USEMamba (Chao et al.); send me links if you meant other papers.

## What the recordings show (and the paper doesn't say)

1. **Each recording mixes two very different conditions.** Stretches of radio-received speech alternate with quieter, cleaner stretches, and the switches are abrupt, at every push-to-talk. In the radio stretches, speech sits only about 0–8 dB above the noise, and about –4 to +3 dB between 1.75 and 3.25 kHz. In the other stretches it sits about 7–23 dB above. The paper's single "9 dB average" hides this.
2. **There's a steady 150.0 Hz tone that is present only while the radio is transmitting.** It sits 30–50 dB above the floor when on and is absent otherwise. 150 Hz is the standard squelch tone on tactical FM radios (SINCGARS, PRC-25). Its level also moves within a transmission (dips of 10–20 dB), and on clip 1 it tracks the hiss level (correlation 0.88). That makes it a free signal telling the model whether the channel is on and how strong it is.
3. **Your error analysis lines up with the damaged frequency band.** The paper reports substitutions as the main error (51%), with callsigns in 51% of erroneous chunks and numbers in 40%, e.g. *three→six*, *zulu→kilo*. The consonant cues that separate those words sit largely in the 2–4 kHz region where the radio stretches are at or below 0 dB.
4. **These clips aren't in the training format.** They are 44.1 kHz stereo MP3, while the paper describes 16 kHz WAV. Train SE on the WAVs, because MP3 compression adds artifacts of its own.

## What everyone is doing wrong

**G1. Synthetic training, synthetic testing.** SEMamba, Mamba-SEUNet, CSMamba, RT-SEMamba and MambAttention all train and test on noise added to clean speech (VoiceBank-DEMAND, DNS). Radio damage isn't added noise: it's band-limiting, automatic gain changes, squelch switching, clicks and codecs. TacRFC also has **no clean reference**, so none of these supervised models can even be trained on it directly.

**G2. They optimise the wrong target.** None of the Mamba SE papers above report WER; USEMamba only reports word accuracy in a challenge setting. Ochiai, Iwamoto et al. show that *artifacts* (errors that don't sound like speech or noise) hurt ASR far more than leftover noise. Your DeepFilterNet3 result (cleaner audio, no WER gain) is a textbook case, and a 2026 SAM-Audio + Whisper study found the same: denoising improved signal quality but raised WER.

**G3. Mamba has no idea when the channel changes.** In Mamba, the step size Δₜ and the B and C matrices depend only on the audio content xₜ. The model's memory builds up a running picture of the noise and carries it across a push-to-talk boundary into a completely different noise condition. MambAttention suggests that this kind of domain-specific information building up in the hidden state hurts generalisation in recurrent models.

**G4. ASR-driven SE is brittle where it exists.** ROSE (the closest prior work, on air traffic control radio) still needs clean references for its ASR-oriented loss. Training through one frozen recogniser also teaches the enhancer tricks specific to that recogniser, which don't carry over to Whisper or Seamless. And every token counts equally, although a digit swap is catastrophic while *hai→he* is harmless.

**G5. Generative SE invents speech.** Flow-matching and language-model-based enhancers (USEMamba-Flow, SenSE, AnyEnhance) can produce wrong sounds; USEMamba itself reports wrong phonemes in packet-loss concealment. Their speech-token priors are not built for Hinglish callsigns and the NATO alphabet, and an invented "six" in a grid reference is unacceptable.

**G6. The metric choice is weak.** BERTScore barely moves when *three* becomes *six*, so it under-penalises exactly the errors that matter operationally.

**G7. Nobody uses channel side-information.** Communications engineering uses known transmitted signals (pilots) to estimate the channel. Radios send one for free (the squelch tone), and I found no SE work that uses it.

## What I would do: Channel-State-Gated Mamba, trained from transcripts

**(A) Mamba that resets at each transmission (the mathematical change to the model).** A fixed signal-processing front end, with no learning and no labels, produces a channel-state vector cₜ: the 150 Hz tone level, its slope, the hiss-band level, and a transmitting-or-not probability.

$$\Delta_t=\mathrm{softplus}(W_\Delta x_t+U_\Delta c_t+b)$$
$$h_t=(1-\rho_t)\,e^{\Delta_t A}\,h_{t-1}+\Delta_t B_t x_t$$

- **Where ρₜ comes from:** it is the probability that the channel changed at time t, from Bayesian online changepoint detection (Adams & MacKay) run on cₜ.
- **Speed is preserved:** (1−ρₜ)e^{ΔₜA} is still just a per-step decay factor, so Mamba's fast parallel scan works unchanged.
- **A provable property:** unrolling gives h_t=\sum_k\big[\prod_{j=k+1}^{t}(1-\rho_j)e^{\Delta_jA}\big]\Delta_kB_kx_k. When ρ→1 at a boundary τ, everything before τ drops out of the memory, and the leakage from earlier conditions is bounded by ∏(1−ρⱼ). With scalar A=−λ and power-spectrum input, this reduces to classic recursive noise tracking with a reset, which makes the model interpretable.
- **Gain correction from the tone:** the tone is transmitted at constant amplitude a₀, so the received level âₜ ≈ gₜa₀ estimates the gain gₜ. We divide it out, then subtract the known 150 Hz sinusoid itself with a closed-form least-squares fit.
- **Fallback without a tone:** if some radios don't send it, cₜ falls back to hiss-level squelch detection. The method then still applies to air traffic control data, which helps the generality claim.

**(B) ASR-driven training without clean audio.** The transcripts are the supervision:

$$\mathcal L=\sum_m \mathcal L_{\text{ASR}}^{(m)}(\hat s,\text{text})+\lambda\,\mathcal L_{\text{mask}}$$

- **Several frozen recognisers, not one:** fine-tuned SeamlessM4T, Whisper-large-v3 and IndicConformer.
- **Only follow agreed directions:** the enhancer keeps only the gradient components whose sign agrees across the recognisers. Updates all of them agree on reflect real speech cues; updates only one recogniser wants are exploits.
- **The key reviewer experiment:** train with two recognisers and test on the held-out third, to show the gains aren't recogniser-specific.
- **Built-in "observation adding":** the output is ŝ = (1−ωₜ)·S_θ(Y) + ωₜ·Y, where ωₜ is predicted from cₜ. Mixing back the original recording is Ochiai's fix for artifacts, and they prove it monotonically improves the signal-to-artifact ratio whenever ⟨ŝ, Y⟩ > 0. Here the model learns to leave the clean local-speaker stretches nearly untouched and to work hard only on the radio stretches.
- **Bounded mask:** the mask term 𝓛_mask is a penalty that stops the enhancer adding energy (|M| ≤ 1 outside a narrow band) and smooths the mask, which suppresses "musical noise" artifacts.
- **Starting point before real data:** pre-train on clean Hindi, English and code-mixed speech passed through a radio-channel simulator whose band shape, hiss, tone and gating are fitted to TacRFC's measured statistics. Then adapt on real TacRFC using the ASR losses alone.

**(C) Extra weight on mission-critical words.**
$$\alpha_i = 1+\beta\sum_{v\in\mathcal K,\,v\neq y_i}p(v\mid\cdot)$$

- **What 𝒦 is:** callsigns, NATO letters, digits and grid references. Your corpus statistics justify the focus: 52.9% of utterances contain callsigns and 27.9% contain numbers.
- **How the weight behaves:** a word gets more weight when the recogniser puts probability on a *confusable critical competitor*, which directly targets three↔six.
- **A new metric:** a Critical-Token Error Rate, tested with the same Wilcoxon and BH-FDR setup as your dataset paper.

## Risks a reviewer will raise

- **Beating plain fine-tuning:** SE must improve on the fine-tuned Seamless baseline (WER 0.57), not just on zero-shot models. Report both "frozen fine-tuned ASR + our SE" and joint training.
- **The tone must hold up across the corpus:** check that it appears across all 834 recordings and on both bands, and work out whether the dips come from fading or the radio's limiter.
- **"This is just an ASR front end":** report listening-quality scores (DNSMOS/NISQA) alongside WER, CER and the critical-token metric.
- **Target venues:** IEEE/ACM TASLP, Speech Communication, or Computer Speech & Language.

The quickest next step is to add the dataset folder in the desktop app. I'll then check whether the tone appears in every recording, and whether the two-condition structure holds, with the segment CSV, before we commit to (A). I can also turn this into a proposal doc for your supervisor.

Sources:
- [TacRFC paper (attached)](#)
- [SEMamba – An Investigation of Incorporating Mamba for SE](https://arxiv.org/pdf/2405.06573)
- [USEMamba – Universal SE with Regression and Generative Mamba](https://arxiv.org/html/2505.21198v2)s
- [Mamba-SEUNet](https://arxiv.org/html/2412.16626v2)
- [CSMamba – Cross- and Sub-band SSM for SE](https://arxiv.org/html/2502.16207v1)
- [RT-SEMamba](https://arxiv.org/html/2608.12099v2)
- [MambAttention](https://arxiv.org/html/2507.00966v3)
- [Ochiai et al. – Rethinking Processing Distortions](https://www.arxiv.org/pdf/2404.14860)
- [Iwamoto et al. – How Bad Are Artifacts?](https://arxiv.org/pdf/2201.06685)
- [ROSE – Recognition-Oriented SE in ATC](https://arxiv.org/html/2312.06118v2)
- [When Denoising Hinders – SAM-Audio + Whisper](https://arxiv.org/html/2603.04710v1)
- [Text-Informed Knowledge Distillation for SE and ASR](https://audiocc.sjtu.edu.cn/user/pages/05.members/wei.wang/publications/Text-Informed@Knowledge@Distillation@for@Robust@Speech@Enhancement@and@Recognition/paper.pdf)
- [SenSE – Semantic-Aware Universal SE](https://arxiv.org/pdf/2509.24708)
- [URGENT 2025 Challenge](https://arxiv.org/pdf/2505.23212)
- [SINCGARS 150 Hz squelch](https://www.hfunderground.com/wiki/index.php/SINCGARS)
- [Mamba (Gu & Dao)](https://arxiv.org/pdf/2312.00752)


I'll check the full dataset first (does the 150 Hz tone and the two-condition structure hold across recordings?), then run a proper prior-art search on each idea before going deeper into the math.

Let me use the shell on your machine instead to get an overview.

Quick update from scanning all 834 recordings (7.83 h). Two of my earlier claims need correcting before I start the novelty search:

- **The 150 Hz tone is not dataset-wide.** It is clearly present in about 234 files (28%), mostly the 8 kHz ones. Another ~42 files carry a ~219 Hz tone instead, and the rest have none.
- **The tone's level dips are not fading.** Within transmissions, the tone level goes *down* when speech gets louder (median correlation −0.37, often around −0.7). That is the radio's limiter/compressor sharing gain with the speech, not the channel fading.
- **What this means:** the "pilot-tone channel estimation" idea can't be the core of the paper. I'm dropping it as a headline idea.

What does hold across the dataset:

- **Abrupt noise-floor jumps in 88% of files:** the noise floor (1 s windows) shifts by more than 6 dB about 19 times per minute (median), and moves over a ~14 dB range within a file. This is an upper bound, since dense speech can also lift the floor estimate.
- **Mixed sample rates:** 287 files are 8 kHz (nothing above 4 kHz), 480 are 44.1 kHz and 67 are 48 kHz (the long UHF sessions, ~3.75 min each).
- **A dip at 2–3 kHz in every sample-rate group**, with a rise again around 3.5–5 kHz.
- **The gain is not fixed:** the radio's gain depends on the speech level itself, so the noisy audio is not simply clean speech plus noise.

Next I'm running a prior-art check on each candidate idea.

Before writing anything up, I'll numerically check the key Lipschitz claim, since it's the centrepiece of the math.

I checked the full dataset (834 recordings, 7.83 h) and ran a prior-art search on every idea from last time plus several new ones. Most of my earlier ideas are already published or too small to carry a paper. One direction appears open, and it has real math behind it.

## What the full dataset shows

- **150 Hz tone:** it is only in about 28% of files, and its level drops when speech gets louder. That is the radio's limiter, not fading, so I've dropped the tone idea.
- **Abrupt noise changes:** 88% of files have sudden noise-floor jumps of more than 6 dB, about every 3 s (median). Treat this as an upper bound, because dense speech can also look like a jump.
- **Mixed sample rates:** 287 files are 8 kHz, 480 are 44.1 kHz, and 67 are 48 kHz. The 48 kHz ones are the long UHF sessions, about 225 s each.
- **Spectral dip:** in every sample-rate group the 2–3 kHz band sits 15–22 dB below the 500–1000 Hz band, and energy rises again at 3.5–5 kHz.
- **Closed vocabulary:** NATO alphabet words make up 20.5% of all tokens, number words 5.5%, and radio procedure words (over, out, roger, okay) 10%.
- **Housekeeping:** only 717 of the 834 audio files match a row in the transcript sheet. The rest are spacing typos such as `record303 _a`.

## Novelty audit

| Idea | Closest prior work | Verdict |
|---|---|---|
| Use the 150 Hz tone to estimate the channel | — | Dropped: the data doesn't support it |
| Feed channel information into Mamba's step size / reset its memory at channel changes | Mamba's step size can already do a reset (Gu & Dao). SLICE (2026) conditions an enhancer on side information | Incremental |
| Learned mixing of enhanced and original audio for ASR | AB-SDR (Ochiai et al.), the MISP 2025 ASR-aware mixing, the real-speech bridging module (Cui et al.), polar projection (2026) | **Done** |
| Train the enhancer through an ASR loss, with no clean audio | MixIT + ASR embedding (Microsoft 2021), text-informed distillation (2022), ROSE | **Done** |
| Keep only updates that several recognisers agree on | Gradient remedy (2023) and generic gradient-agreement tricks | Incremental |
| Extra weight on callsigns and numbers | Frequency-weighted enhancement losses (Monir 2025) | Incremental; better used as an evaluation metric |
| Kalman-style probabilistic Mamba | KalMamba (reinforcement learning), parallel Kalman filters for language models | Crowded; weak story for enhancement |
| Mamba that scans along pitch harmonics | HAMMER (2026) models harmonics only implicitly | Open, but doesn't serve the ASR goal |
| **Formula splitting "why enhancement hurts ASR" into information loss + mismatch** | Only empirical studies (Ochiai; "Too Good to Be True"; "When De-noising Hurts"; polar projection) | **Open** |
| **Enhancer that provably cannot squash or stretch differences in its input beyond set limits ("bi-Lipschitz")** | Flow-based enhancers are invertible but for generation; LipSSM (2026) covers fixed-parameter models only and isn't speech | **Open** |
| **A Mamba sensitivity bound that doesn't grow with recording length** | Cao et al. (ICML 2026) prove a bound that grows linearly with length. The underlying principle (forgetting ⇒ stability) is known | **Partly open** |
| **Averaging the recogniser's loss over small random perturbations so the enhancer can't "game" it** | Randomized smoothing has been used for robustness to adversarial attacks on ASR (Olivier & Raj), not as an enhancer training objective | **Open** |

## The surviving direction

The four open rows fit together into one method.

**1. Why enhancement hurts ASR.** For a frozen recogniser R with posterior q_R, the expected ASR loss on enhanced audio f(y) splits exactly into three parts:

$$\mathbb E[-\log q_R(w\mid f(y))]=\underbrace{H(w\mid y)}_{\text{irreducible}}+\underbrace{I(w;y)-I(w;f(y))}_{\Delta I\;\ge 0:\ \text{information lost}}+\underbrace{\mathbb E\,\mathrm{KL}\big(p(w\mid f(y))\,\|\,q_R(w\mid f(y))\big)}_{\text{mismatch}}$$

- **What it predicts:** enhancement can only help by reducing mismatch, and it always risks some information loss.
- **Corollary:** a recogniser retrained to be optimal on whatever audio it receives can never be improved by any enhancer.
- **Why your DeepFilterNet3 result is expected:** fine-tuning Seamless on TacRFC already removed most of the mismatch, so only the information-loss term was left for the enhancer to affect.
- **It can be measured:** fine-tune the same ASR on enhanced audio and on noisy audio. If it does worse on enhanced audio, the enhancer destroyed information. Only the identity is textbook; using it as an estimator for enhancement seems new.

**2. An enhancer that can't crush or stretch cues too far.** Work on log-magnitudes, z = log|Y|, keep the noisy phase, and predict a correction g:

$$\hat z = z + g(z),\qquad \mathrm{Lip}(g)\le c<1 \;\Rightarrow\; (1-c)\,\|z_1-z_2\|\le\|\hat z_1-\hat z_2\|\le(1+c)\,\|z_1-z_2\|$$

- **What the bounds mean:** this is an invertible residual network (Behrmann et al., 2019). The lower bound means two inputs that differ (say /θ/ vs /s/) can never be mapped closer together than a factor of (1−c). The upper bound caps how sharply the enhancer can expand differences, which is what produces "musical noise".
- **Why this matters in the theory:** whatever a recogniser could read from y, a slightly less smooth recogniser (its smoothness limit loosened by 1/(1−c)) can read from f(y). That bounds the "usable" version of the information-loss term above.
- **How it differs from polar projection and observation adding:** those multiply the whole correction by α. That weakens both *how much* noise is removed and *how sharply* removal depends on the input. The Lipschitz constraint only limits the sharpness, so a constant amount of suppression stays free.
- **Testable prediction:** at the same WER, this enhancer removes more noise than α-scaling does.

**3. Keeping Mamba's sensitivity bounded on long recordings.** Write each Mamba state update as h_t = a_t h_{t-1} + b_t x_t with a_t = e^{-λΔ_t}, and force the step size to stay above a floor, Δ_t ≥ Δ_min. Then a_t ≤ ρ := e^{-λΔ_min} < 1, and

$$\Big\|\tfrac{\partial h_t}{\partial x_s}\Big\| \le \rho^{\,t-s}\Big(K_b + \bar H K_a\Big)\;\Rightarrow\;\mathrm{Lip}=O\!\Big(\tfrac{1}{1-\rho}\Big)\ \text{for any length }T$$

- **The trade-off:** sensitivity now scales with the memory horizon τ = 1/(1−ρ), not with the recording length.
- **Why your data allows it:** the noise floor changes about every 3 s, so the model loses nothing by forgetting beyond a couple of seconds.
- **Where it matters:** the 225 s UHF sessions (about 22,500 frames at a 10 ms hop) are exactly where an unbounded sensitivity would blow up.
- **Toy check:** I verified this numerically on a single-channel selective state-space model. With no floor, the Jacobian norm kept rising with length (0.54 → 1.32 from T = 50 to 1600). With a floor it levelled off (≈1.55 for Δ_min = 0.01, ≈1.65 for Δ_min = 0.05). Mamba-2's code already has a `dt_limit` setting, so the new part is the theorem and its use for guarantees, not the knob itself.

**4. Training from transcripts without gaming the recogniser.** Training an enhancer only to lower an ASR's loss is the same optimisation as building a "helpful adversarial example". The enhancer can learn tiny, recogniser-specific patterns that don't transfer to other ASRs. So average the loss over Gaussian noise added to the enhancer's output:

$$\tilde\ell(\hat z)=\mathbb E_{\delta\sim\mathcal N(0,\sigma^2 I)}\,\ell\big(R(\hat z+\delta),w\big)$$

- **Why it works:** for a loss bounded in [0,1], the averaged loss changes at most √(2/π)/σ per unit change in the input. Patterns much smaller than σ can't lower it, so the enhancer is forced to make real, audible changes.
- **What it needs:** only TacRFC audio and transcripts, no clean reference.

## Where this could fail

- **Too weak to denoise:** chaining K residual blocks gives lower and upper limits of (1−c)^K and (1+c)^K, and both are set by the same c. The model might then be too gentle to beat a fine-tuned ASR. This is the main risk.
- **Loose bounds:** worst-case Lipschitz bounds are often far looser than what the model actually does (Cao et al. report about 100×). Expect to need a constraint built into the architecture plus a measured-Jacobian penalty during training.
- **Searches aren't exhaustive:** run a final check on IEEE Xplore and Google Scholar before writing, since I can't see inside paywalled venues.

The cheapest first test uses the information-loss estimator from part 1 on DeepFilterNet3 output: fine-tune Seamless on DFN3-enhanced TacRFC and compare it with the model fine-tuned on noisy audio. If it does worse, that confirms the core story with your existing models.

Sources:
- [Mamba (Gu & Dao)](https://arxiv.org/pdf/2312.00752)
- [Mamba-3](https://arxiv.org/pdf/2603.15569)
- [A Control-Theoretic View of Mamba (Cao et al.)](https://lacuna.tiptreesystems.com/work/a-control-theoretic-view-of-mamba-on-stability-and-robustness/wrk_3bd76e2f71c8895d6f8c14f15f903e41)
- [LipSSM](https://arxiv.org/html/2609.30973)
- [Rethinking Processing Distortions (Ochiai et al.)](https://www.arxiv.org/pdf/2404.14860)
- [Where SE Hurts Recognition: Polar Projection](https://arxiv.org/html/2607.11157v1)
- [ASR-aware Observation Addition, MISP 2025](https://arxiv.org/html/2505.22013v1)
- [Real-Speech-Trained Bridging Module](https://arxiv.org/html/2501.02452v1)
- [Too Good to Be True](https://arxiv.org/html/2605.12107v1)
- [When De-noising Hurts](https://arxiv.org/pdf/2512.17562)
- [Unsupervised SE with ASR embedding (MixIT)](https://arxiv.org/abs/2111.08678)
- [Text-Informed Knowledge Distillation](https://audiocc.sjtu.edu.cn/user/pages/05.members/wei.wang/publications/Text-Informed@Knowledge@Distillation@for@Robust@Speech@Enhancement@and@Recognition/paper.pdf)
- [ROSE](https://arxiv.org/html/2312.06118v2)
- [Gradient Remedy](https://arxiv.org/abs/2302.11362)
- [Frequency-Weighted SE Losses](https://arxiv.org/html/2506.18714v1)
- [SLICE](https://arxiv.org/pdf/2603.05302v1)
- [HAMMER](https://arxiv.org/html/2609.21171)
- [KalMamba](https://arxiv.org/abs/2406.15131)
- [Sequential Randomized Smoothing for ASR](https://arxiv.org/pdf/2112.03000)
- [MambAttention](https://arxiv.org/html/2507.00966v3)
- [USEMamba](https://arxiv.org/html/2505.21198v2)
- [SINCGARS 150 Hz squelch](https://www.hfunderground.com/wiki/index.php/SINCGARS)