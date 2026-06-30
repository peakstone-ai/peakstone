# vision.md — Peakstone

> A companion to [PLAN.md](./PLAN.md). PLAN is the *engineering plan* (architecture, schema,
> roadmap, what's built). This is the *vision* — the concept at altitude: what Peakstone is for,
> who uses it and how, where its real strength and fragility lie, whether it can become the
> standard for local-LLM testing, and which directions are worth taking next.

---

## 1. The concept in one breath

**Peakstone measures how far the open-model capability frontier has reached — and proves it.**

Most benchmarks tell you a *number*. Peakstone tells you a number you can **re-derive yourself**,
on **your own hardware**, against a challenge the model **could not have memorized**. Three words
carry the whole project:

- **Reproducible** — every score ships with everything needed to re-run it (signed result bundle).
- **Contamination-aware** — the headline metric counts only challenges published *after* a model
  was released. You can't train on a problem that didn't exist yet.
- **Yours** — the leaderboard is a *query*, not a table. "Best coder that fits my 3090" is one filter.

The metaphor is load-bearing: tsunami stones mark how far the water reached, permanently, so the
next generation knows. Peakstone marks how far open models reached — set in stone, verifiable,
and self-healing as new dated challenges arrive.

---

## 2. Why now — the three things that are broken

```
   Problem in the wild                     Peakstone's answer
   ─────────────────────                   ──────────────────
1. "Trust me, it scored 92%."        →     Signed bundle: weights SHA, serve flags, env,
   Numbers you can't reproduce.            transcripts. Re-run it or reject it.

2. Benchmarks leak into training.    →     Held-out score: only challenges dated AFTER the
   Saturation ≠ capability.                model's release. Self-heals as the corpus grows.

3. "Best model" ignores YOUR box.    →     Faceted leaderboard: filter by VRAM, quant, ctx,
   Cloud-scale rankings, local GPU.        tok/s. Each family collapses to its best *qualifying* run.
```

The third is the wedge. There is no neutral, reproducible place today that answers *"which open
model is best **for the machine I actually own**"* — and that is the single most-asked question in
every local-LLM community. Peakstone is built around that question first, everything else extends it.

---

## 3. The mental model

Three orthogonal axes keep the whole thing from collapsing into a one-dimensional ranking:

```
                        WHAT is tested (capability)
                        categories:  code · math · library · long-context · safety
                          · tool-calling · agentic · planning · (logic · vision →)
                        modifiers (ride on those): self-repair · calibration
                          · language-robustness · efficiency
                          │
                          │
     HOW it's scored ─────┼───── HOW HARD it is (calibrated tier)
     (drives trust)       │      T0 saturated → T4 frontier/unsolved
     tests (hard)         │      ↑ computed from who-passes, not author-guessed
     judge  (soft)        │      ↓ challenges migrate DOWN tiers as models improve
     goal-state-env       │        ── that migration IS the evolution story
     human                │
```

A **challenge** declares what capability it needs and how it's verified. A **run** is one fully
specified config `(weights + quant + ctx + serve flags + hardware + driver + engine)` scored on a
**suite** (a versioned, curated slice of the open corpus). Runs are **never collapsed** — a
Q4@24GB run and a Q8@48GB run are different points on the map. The leaderboard is the act of
*querying* that map under a filter.

The hero view is **capability-vs-release-date**: watch the open frontier climb, per capability,
over time — with contaminated results filtered out so the climb is real.

**Default test selection is part of the measurement, not an afterthought.** A model shouldn't be
graded on a uniform slab of challenges — it should default to the slice that both *makes it
comparable* to its peers and *challenges it* near its own frontier (held-out by date + calibrated
to its tier, via the existing levels/relevance machinery). The vast imported corpus exists mostly
for **backwards-compat** — so old/small models still have a floor to stand on and the evolution
chart reaches back in time — not because every model should run all of it. Each model runs what is
*meaningful for it*; the corpus guarantees there's always something meaningful at every era.

### 3a. The capability measurement framework

Not every capability needs its own corpus, and conflating them blurs the picture. Two distinctions
keep the axes sharp and the cost low.

**Categories vs. modifiers.** A **category** is a skill with its *own* challenges — `code`, `math`
(kept separate from code: a strong coder can be weak at competition math and vice-versa),
`library-fluency`, `long-context`, `safety`, `tool-calling`, `agentic` (multi-machine goal-state),
`planning`, and later `logic` and `vision`. A **modifier** is a probe *layered on challenges that
already exist*, so it costs almost nothing: `self-repair` (re-run with the test error fed back —
debugging-from-feedback), `calibration` (ask *before*: "will you solve this?" and *after*: "did
you?" — does the model know what it knows?), `language-robustness` (restate a spec in another
language, measure the pass-rate *delta*), and `efficiency` (tokens / LOC / RAM per solve).

**Agentic ≠ iterative ≠ calibration** — the easy confusion to avoid. **Agentic** is driving a
multi-node environment with tools over many turns to a goal. **Iterative self-repair** is fixing one
file from its test error. **Calibration** is knowing whether you got it right. A model can be strong
at one and weak at another; they are *separate* axes and must be scored separately (as `code` and
`math` already are).

**Measure cheaply — probes, not full sweeps.** A modifier rarely needs the whole suite: calibration
wants ~20 difficulty-spanning challenges, self-repair runs *only on the failures*, language-
robustness on ~10 translated specs. Combined with relevance gating (a challenge declares the
capabilities it needs; a model runs only those — vision only for vision models), the operating rule
is: **prefer modifiers over new corpora, run on representative probe subsets, gate by capability and
by where-it-makes-sense, and harvest the free byproducts** (post-hoc confidence is one extra yes/no
on a run you're already doing).

**Metric roadmap (cheap → expensive):** (1) ✅ **calibration** axis — *built*:
`self_verify_accuracy` (post-hoc "is my solution correct?" vs reality) + `confidence_score`
(1 − Brier on the pre-hoc "will I solve this?"), via the `--calibration` modifier (auto-skips
long-context; the post-hoc fires on the *first* attempt before any retry feedback, so it can't cheat).
(2) ✅ **self-repair** — *built*: `--retries` feeds the test error back; the **headline stays
first-try** (`code_score`/held-out are single-shot), and recovery is its *own* axis `recovery_rate`
(of first-try failures, what fraction it fixed). (3) **language-robustness** — a translated probe
subset; (4) post-launch: **logic** category, then **multimodal / vision** (gated to capable models).

**End-to-end run workflow** (the modifier philosophy made concrete): **one main run** does most of it —
`runner --level standard --models <m>` now bakes in calibration + retries, so a single command yields
*code · math · safety · long-context · calibration · self-repair* in one bundle (modifiers ride on the
challenges already being run). Only fundamentally-different *setups* are separate runs: `--env`
(agentic, multi-machine provisioning) and `--planner` (needs a fixed second model). No result-merging
gymnastics — each is a clean bundle; a model's profile is 1 main run + optional agentic + optional planner.

---

## 4. Who it's for, and what they actually do

Peakstone serves five distinct people. Each has a different "aha," and the product should make
each one's first five minutes obvious.

### A. The local-LLM owner — *"what runs best on my box?"*
The largest audience and the wedge. Opens the **TUI**, which already shows live GPU/CPU/RAM next
to the leaderboard *pre-filtered to what fits*.
```
  open TUI ─► it reads my 24GB/64GB ─► leaderboard auto-filtered to runs that fit
           ─► sort by code | tok/s | efficiency ─► "reproduce this run" on my own model
```
Aha: *the ranking changes when it knows my hardware, and I can verify any row.*

### B. The model author / fine-tuner — *"did I actually improve it?"*
Runs the engine against a checkpoint, gets a signed bundle, submits. Over time their family draws
a line on the evolution chart.
```
  serve checkpoint ─► run suite (+ --retries, --agents-md) ─► signed bundle ─► submit
                   ─► appears on evolution chart ─► community re-runs ─► "verified" badge
```
Aha: *a credible, third-party-reproducible claim my model climbed — not a screenshot.*

### C. The challenge author — *"where do models actually differ?"*
Writes `spec.md + tests/ + reference/`, the reference must pass in the sandbox, signs a proposal,
admin canonizes it into a suite. New challenges accrete at the T3/T4 frontier.
Aha: *I can probe a weakness no public benchmark exposes, and watch models climb my hill.*

### D. The researcher / journalist — *"how fast is open catching up?"*
Reads the evolution chart and the held-out leaderboard. The contamination filter is what makes
this citable instead of hand-wavy.
Aha: *a defensible "open models climbed X in Y months" with the confounds named.*

### E. The team picking a model for a private codebase — *(latent, not yet served)*
Today they can only run public suites — which leak, and don't look like their code. This persona
is the opening for the **Test Crafter** (§7). It's the highest-value unserved user.

---

## 5. The flywheel

Peakstone only matters if it spins. The loop:

```
        more submitters
       ┌───────────────────────────────────────────┐
       │                                            │
       ▼                                            │
  more runs ──► better calibration ──► more useful  │
  per config     (real difficulty       leaderboard │
       │          tiers, "fits my       & charts    │
       │          hardware" envelope)      │        │
       │                                   ▼        │
       │                            people trust &  │
       └──── verification tier ◄──── cite it ───────┘
             (community re-runs
              deterministic results)
```

Two engines drive the wheel, and they're asymmetric in difficulty:

- **The data engine** (runs in) is the hard one — classic cold-start. A leaderboard with three
  models is not interesting. Bootstrapping needs either a flood of seed runs (the maintainer
  re-running everything) or a *reason to run anyway* that doesn't depend on the leaderboard being
  populated yet (CI gating, the recommender, the Test Crafter — see §7).
- **The trust engine** (verification) is the moat — it's the thing LMArena-style and
  vendor-reported boards structurally can't do. It's worth protecting and foregrounding.

---

## 6. Strengths and weaknesses — honest read

### Strengths (the genuine differentiators)
1. **Reproducibility is the schema, not a feature.** The signed bundle is the contract between
   engine and API. This is rare and hard to retrofit; Peakstone has it from the foundation.
2. **Contamination-resistance is first-class.** Held-out-by-date as the *headline* number directly
   attacks the #1 reason people distrust benchmarks. Few boards even try.
3. **"Fits-my-hardware" is a real, unmet need.** Faceted-query-not-a-table is the right data model
   and answers the question the audience actually has.
4. **Real execution, up to multi-machine.** Goal-state verification in microVMs/containers (with
   network shaping, partitions, p2p convergence) is far beyond "does the string match." This is an
   unusually ambitious and credible agentic-eval foundation.
5. **Calibrated difficulty from data.** Tiers come from who-passes, not author ego. The
   tier-migration-over-time *is* the evolution narrative — elegant.
6. **Breadth already in place.** Code, library fluency, self-repair, planning, tool-calling,
   injection/refusal/secure-code, long-context, token-efficiency — a wide, extensible taxonomy.

### Weaknesses & risks (where it could fail or stall)
1. **Cold-start dominates everything.** All the cleverness is worthless until the board is
   populated by *independent* submitters. This is the existential risk, and it's social, not
   technical. → Mitigation must be a use that's valuable at N=1 (CI, recommender, Test Crafter).
2. **Trust depends on critical mass of re-runners.** "Community-verified" needs ≥N independent
   identities per config. Below that threshold most rows are "self-reported," which is exactly the
   thing Peakstone is trying to replace. The verified tier is the moat *and* the chicken-and-egg.
3. **Presentation must not let the corpus speak louder than the signal.** The imported corpus is
   large *by design* — BigCodeBench (1,140), Codeforces (377), LiveCodeBench (175), AIME (60),
   HumanEval (164) exist mainly for **backwards-compat**: a floor for old/small models and reach
   back in time for the evolution chart. That's a strength, not a flaw — *but* most imports are
   already contaminated and saturated, so if a default view averaged over all of it, the headline
   would measure memorization. **Decision (locked):** the public leaderboard defaults to the
   **contamination-filtered (held-out)** view, and each model defaults to the test slice that makes
   it comparable *and* challenges it (§3). The saturated all-corpus view is a deliberate opt-in for
   the backwards-compat story, never the front page.
4. **Contamination metric is only as good as its dates.** `release_date` is public/unforgeable
   (good), but per-challenge `published_at` and especially `training_cutoff` are fragile/
   self-reported. The whole headline rests on date hygiene.
5. **Surface area vs. one maintainer.** Engine + API + web + TUI + importers + microVM provider +
   sandbox is a large platform. Contributor onboarding and maintenance load are real threats to
   longevity. Ruthless focus on the killer view beats breadth here.
6. **Security is permanent, not a phase.** Running untrusted *model output* and untrusted
   *user-authored challenges* at scale is a standing attack surface. One sandbox escape is a
   reputational event for a "trust" project.
7. **Audience ceiling.** Closed frontier models can't submit (no weights/serve flags), so
   Peakstone is structurally an *open-model* board. That's a feature (focus) but caps the TAM and
   the "is this THE standard" claim to the open ecosystem.
8. **Judge-based axes stay soft.** Subjective quality (readability, design taste) can't be made
   reproducible, so a chunk of "is this code good?" stays outside the verifiable core.

---

## 7. Where it can go next — ideas, evaluated

Ordered by *leverage on the cold-start problem* (the thing that decides whether Peakstone lives),
not by how fun they are to build.

#### The cold-start lens

A leaderboard is a network-effect product: it's worth ~nothing to visitor #1 (nothing to compare),
but the only way to get data is for people to run the engine — which they won't *because* there's
nothing to compare. That loop kills most benchmark projects. Two reframes break it:

**There are three cold-starts, and only one is hard.**

| Cold-start | Status | Why |
|---|---|---|
| Challenge supply | ~solved | ~2,400 challenges + importers already exist. *What to test* isn't the problem. |
| **Run supply** (submissions) | **the real one** | Needs people to run the engine and submit bundles. |
| Verification (independent re-runs of the *same* config) | hardest, last | Genuinely needs N>1 per config — no single-player trick fakes it. |

**Single-player value, multiplayer exhaust.** Every idea below must be valuable at **N=1** — to a
person who is the only user in the world — where the *byproduct* of that selfish local use is
exactly the run-supply the board needs. Nobody contributes altruistically to populate a table; they
run the engine for their *own* payoff, and submission is the near-zero-cost exhaust (one `--submit`
flag, or an automatic CI step). The leaderboard isn't the bootstrap product — it's what *emerges*
once enough exhaust accumulates. So sequence it: **single-player tools first → runs flow →
verification ignites last**, naturally, once popular configs get re-run by multiple people. (Three
accelerants compound this: seed the board non-empty with the maintainer's own ~10-model `results/`;
shrink the network unit — "best on a 24GB card" needs only a handful of 24GB runs, and that's
already the data model; and treat verification as a *late* milestone, not a launch expectation.)

### ★ Idea 1 — CI / regression gate — **the ignition play; cheap, build first**
`peakstone check` as a CI step for fine-tuners and quant-makers: "did this checkpoint regress on
tier-2 Go / long-ctx / injection vs. the last one?" Exit non-zero on regression.
- **Highest cold-start leverage of anything here.** The comparison is against the user's *own*
  previous run — valuable at N=1, no other users required. It creates a *daily, automated* reason
  to run the engine, and every CI run is a ready-to-submit signed bundle. Small surface (the engine
  already produces the numbers); huge funnel into run-supply. This is the lead bootstrap play.

### ★ Idea 2 — Private Test Crafter (the user's idea) — **the strategic keystone**
A capable planning model helps a user turn their *own* domain — a private repo, an API, a
problem class — into a **private, verifiable, never-published challenge collection**, then ranks
models on it locally.

Why this is the strategic keystone (and also a strong N=1 play):
- **It is the ultimate answer to contamination.** A benchmark that exists only on your disk and
  is never published *cannot* be in any training set. Peakstone's public side fights contamination
  with dates; the private side eliminates it by construction. The two halves reinforce the same
  thesis.
- **It serves persona E and is valuable at N=1.** It doesn't need a populated leaderboard to be
  useful — it directly attacks cold-start by giving people a reason to run the engine *today*,
  alone, for their own benefit. The runs they produce can *optionally* feed anonymized difficulty
  calibration back to the public corpus.
- **It turns "which model for my codebase" from vibes into a number.** That's a question teams pay
  attention to.

Shape it carefully (the risks are real):
- **Verifiability is the hard part.** Auto-generated tests are only as trustworthy as their
  determinism. Lean on what already exists: extract real functions + their real tests from the
  user's repo; mutate/parameterize; *require the reference to pass in the sandbox* before a
  generated challenge counts — the same gate the public corpus uses.
- **Avoid the circularity trap.** A model authoring challenges to test models is circular if
  unchecked. Keep a human-in-the-loop review step, and prefer *grounding in the user's existing
  passing tests* over free invention.
- **Privacy is the product.** Generation and scoring run locally; nothing leaves the box unless
  the user opts into sharing aggregate calibration (never the challenge content). Say this loudly.
- Reuses the planner eval, the sandbox, `propose.py`'s reference-must-pass gate, and the faceted
  leaderboard — mostly *composition*, not new infrastructure.

#### Commit-and-reveal: making private results *publicly verifiable* — **post-release; revisit pronto**
> Status: designed, **not built**. The minimal slices are scoped below. Pick this up right after
> launch — it's the highest-leverage extension of the keystone.

Today the private side is framed as fully local ("nothing leaves the box"), which means it produces
**zero public exhaust** — a private run can't be shown without leaking the challenge. A
**commit-and-reveal** scheme fixes that and makes a private run the *strongest possible held-out
point* (the public side fights contamination by *date*; a sealed-then-revealed challenge proves
"couldn't have trained on it" *by construction*):

- **Commit (at submission):** submit **only** the score numbers (`final/passed/total`) + a salted
  commitment `H(spec ‖ tests ‖ reference ‖ salt)` + safe metadata (category/difficulty). **Omit
  spec/solution/transcript** (they leak the challenge). Server stamps `submitted_at` — the integrity
  anchor proving the numbers predate the reveal. Recorded as a `committed-private` trust tier with
  **no headline credit** (a sealed claim is just a timestamped self-report until opened).
- **Reveal (later):** publish content + salt → server verifies `H(content‖salt) == commitment`
  (unaltered + pre-existing), runs the reference-must-pass gate, sets `published_at` (source
  `private-reveal`), flips trust to `revealed` → joins the held-out board. Re-runs by others →
  `reproduced`. Publishing also makes the challenge **public → contaminated for models released after
  the reveal**: a one-shot gold held-out probe that converts to a normal regression test.

Mostly composition — reuses per-result `challenge_hash`, signed bundles + server `submitted_at`,
`published_at` boundary logic, the reference-must-pass gate, and the now-recorded seed+stack (so the
numbers are re-runnable). **Honest caveats:** the headline must credit *only revealed+verified*
results; selective reveal (file-drawer) can't be prevented cryptographically, only made visible via a
"committed N / revealed M" count; reproduction proves correctness (`passed/total`), not perf.
**Staged build:** (1) redaction-safe private-result shape in the bundle + optional schema fields;
(2) pure `verify_reveal(content, salt, commitment)` + the reference gate (the crypto core,
unit-testable, zero UI); (3) ingest `committed-private` tier + `peakstone reveal` flow + leaderboard
surfacing. Sequence it after the public board has seed runs (CI gate → runs flow → this layers on).

### ★ Idea 3 — Model recommender / advisor — **flagship UX, mostly built**
`recommend.py` exists; promote it to a front-door. Input: hardware + a task profile ("mostly Rust,
need 128k ctx, latency-sensitive"). Output: the model + the *exact serve config* to run it.
- This is the local owner's actual question, answered in one screen. It also surfaces the unique
  knowledge the lab already accumulated (n-cpu-moe offload recipes, KV-quant gotchas) that *no one
  else centralizes*.

### ★ Idea 4 — Serving-config knowledge base — **uniquely defensible**
The hard-won facts in the project's own history (which quant, `--n-cpu-moe N`, KV-cache quant,
`-fa on`, ctx-vs-tok/s tradeoffs per card) are gold and exist nowhere central. Make
"best serve flags for model X on a 24GB card" a first-class, community-contributed artifact tied
to runs. This is a moat competitors can't copy from data alone.

### Idea 5 — The "unsolved board" (T4 bounties) — **community/marketing engine**
A public page of frontier challenges nothing reliably passes yet, framed as bounties. Gamifies
challenge authoring (persona C), gives the press a "here's what open models still can't do" hook,
and continuously refreshes the contamination-resistant top of the corpus.

### Idea 6 — Contamination *probes* — **proves the core claim**
Canary/near-duplicate challenges designed to detect memorization directly (a model that aces the
public version but fails a semantically-identical private mutation is flagged). Turns "we filter by
date" into "we can *show* this model memorized X." Pairs naturally with the Test Crafter's mutation
engine.

### Idea 7 — Cost/energy axis — **natural extension, partly there**
Efficiency metrics exist (score-per-1k-tokens, peak RSS). Extend to **$/solved-challenge** and
**watts/task**. "Cheapest model that clears tier-3" is a real procurement question and a clean,
fully-deterministic axis.

### Idea 8 — Head-to-head transcript diff — **cheap delight**
Pick two runs of the same challenge, see prompts/outputs/test results side by side. Makes the data
visceral and shareable; trivial given transcripts are already stored.

---

## 8. Could it become the standard for local-LLM testing?

**For open/local coding models specifically: yes, plausibly — and there's a real vacuum to fill.**
No incumbent combines *reproducible* + *contamination-aware* + *fits-my-hardware* for local models.
LMArena is human-preference and closed-model-centric; vendor numbers are self-reported; static
public benchmarks are saturated and leaked. Peakstone's three pillars are exactly the gaps.

**But "the standard" is won socially, not technically, and three things must go right:**

1. **Solve cold-start.** Become useful at N=1 *before* the network exists — via CI gating, the
   recommender, and the Test Crafter. If the only reason to run is "to populate someone's board,"
   it won't populate. This is the make-or-break.
2. **Make held-out the default lens. (Decided.)** If the front page can be read as "Qwen aces
   HumanEval," the contamination thesis is undercut by Peakstone's own homepage. The default
   leaderboard is contamination-filtered, and each model defaults to the slice that makes it
   comparable and challenges it; the saturated all-corpus view is a deliberate opt-in for the
   backwards-compat story. This is now a launch requirement, not a someday-toggle (see §10).
3. **Neutral, durable governance.** Standards need a credible, non-partisan home. "The Peakstone
   Authors" is fine to start, but legitimacy (and resistance to "the maintainer's model wins
   suspiciously often") eventually needs transparent suite governance, reproducible-by-anyone
   verification, and ideally a foundation/entity. Get the *trust tier* visibly working early — it's
   the one thing structurally unavailable to every competitor.

**Honest ceiling:** it will be the standard for *open-model, locally-runnable, verifiable*
evaluation — not for closed frontier models (they can't submit weights/configs) and not for
subjective quality (un-reproducible). That's a focused, winnable category, not a consolation prize.

---

## 9. Before first release — the one thing to get right

**The gating launch question is not "what's on the board" but "what tests run on which model."**
Everything credible about Peakstone — comparability, the contamination thesis, discriminating
power — collapses if this selection is wrong. It is the lens through which every visitor reads the
project, so it must be right *at launch*, not iterated into shape afterward.

Three forces pull on the selection, and the default must balance all three:

```
   COMPARABILITY            CHALLENGE                 COST / HONESTY
   every model shares       run near each model's     don't run 2,400 per
   an overlapping core  ×   own frontier (calibrated  model; never average
   so scores sit on the     tier) so the score        over contaminated,
   same axis                discriminates             saturated tasks
```

- **Too uniform** (everyone runs the same fixed slab) → small/old models bottom out at ~0 and
  frontier models saturate at ~1; the board stops discriminating and reads as a param-count proxy.
- **Too bespoke** (each model runs a totally different set) → scores aren't comparable; there's no
  shared axis to rank on.
- **Too much** (run the whole corpus) → slow, expensive, and the average is dominated by
  contaminated/saturated imports — the exact failure mode §6.3 warns about.

The shape that satisfies all three (and which the existing **levels / relevance / calibration**
machinery already mostly implements — make it the *default*, not a flag):

1. **A comparable core** — a held-out, deterministic, content-pinned overlap set every relevant
   model runs, so any two models share enough challenges to be ranked on one axis.
2. **A frontier band** — challenges calibrated to *this* model's tier (a rung or two around where
   it starts failing), so the score actually separates it from neighbors instead of saturating.
3. **Relevance gating** — only axes the model can attempt (don't score a non-tool model on
   tool-calling); a skipped axis is shown as skipped, never as zero.
4. **Held-out by default** — the date filter is applied before selection, so the corpus's
   backwards-compat bulk never silently leaks into the headline.
5. **Deterministic & pinned** — selection is model-independent and content-hashed, so the *same*
   model+config re-runs identically and two submitters can verify each other (this is what feeds
   the trust tier).

> **A "Peakstone" = a frozen release of a level (post-release idea).** `(level, version,
> content_hash)` already *defines* the collection — e.g. `standard@2026-06-30`. The natural artifact
> is to **freeze** it as a small versioned **manifest**: the ordered challenge ids + each one's
> `content_hash` + the suite `content_hash`. That makes a Peakstone a portable, immutable,
> reproducible release anyone can reconstruct and verify (regenerate the imported challenges, checkout
> the native ones, re-check the hashes). Prefer this over materializing the collection as a folder of
> filesystem **symlinks**: the imported corpora are gitignored/regenerated, so symlink targets aren't
> versioned or portable, and the manifest+hash is already the single source of truth the bundle
> records. The dynamic `levels.resolve()` stays "the current standard"; a frozen manifest snapshots a
> dated release. (Vocabulary: individual items are *challenges*; a *Peakstone* is our curated
> collection — see the renamed TUI.)

If launch nails this — *the right, defensible, reproducible test set chosen automatically per
model* — Peakstone ships with its core promise intact. If it ships uniform-or-everything, the first
impression is "another saturated leaderboard," and the contamination thesis is undercut by
Peakstone's own front page. **This is the pre-release priority above all others.**

### The launch checklist — what "default" must mean

Grounded in the code as it stands today. The good news: most machinery exists; the gaps are mostly
*defaults pointing the wrong way* plus one genuinely-unbuilt piece (the frontier band). Items are
tagged **[wire]** (flip/connect existing code), **[decide]** (a call to lock first), or **[build]**
(new work).

**A. Selection — what runs per model (`engine/`)**
- [x] *Comparable core exists.* `levels.toml` + `levels.resolve()` already produce a deterministic,
  model-independent, content-hashed id list; `runner --level X` stamps `suite_id=level-X`,
  `suite_version`, and a `content_hash` into the bundle — so "comparable iff same (level, version,
  content_hash)" already holds.
- [x] *Relevance gating exists.* `GATED_CAP` + `relevant()` skip axes a model can't attempt
  (tools → tool-calling/injection; agentic → swebench/env). Verify it's applied at selection time
  and that a skipped axis is recorded as *skipped*, never scored 0.
- [ ] **[decide] Pick the official default level.** Today `--level` is optional; with no level a run
  is `suite_id="adhoc"` and **not comparable to anything**. Choose the launch default (likely
  `standard`) and make the runner/dashboard default to it, so a casual `peakstone run` produces a
  *comparable* bundle, not an orphan. Adhoc stays available, labelled non-official.
- [ ] **[build] The frontier band.** This is the one real gap. `levels.toml` selection is static
  (`family` + fixed `difficulty` + `limit`), not calibrated to the model under test — so strong
  models saturate and weak ones floor on the same slab. *Honest launch scoping:* ship the static
  comparable core **+ held-out** for v1 (calibration needs submission data that doesn't exist yet —
  chicken/egg), and add the adaptive frontier band in the post-launch slice once
  `challenge_calibration` (PLAN §6) has real pass-rates. Say this is deferred; don't pretend it's
  adaptive on day one.

**B. Leaderboard query — held-out as the default lens (`api/main.py`)**
- [x] *Held-out is fully computed.* `_held_out()`/`_summarize()` emit `held_out_score` +
  `held_out.{coverage,n_clean,n_contaminated,n_unknown}`; `SORT_ORDER` already lists
  `held_out_score` (desc) and its own comment calls it "the headline timeline metric."
- [ ] **[wire] Flip the default sort.** `leaderboard(... sort: str = "code_score")` → default to
  `held_out_score`. (`code_score` stays selectable as the opt-in all-corpus view.)
- [ ] **[decide] None-handling policy.** Ranking by `held_out_score` currently drops any model with
  no `release_date` or no post-release challenges (`if val is None: continue`) — on a *default*
  board that silently disappears real models. Lock the rule: e.g. show qualifying (held-out) models
  ranked, then an "insufficient held-out coverage" section below, rather than vanishing them. Pairs
  with a **minimum-coverage threshold** (`held_out.coverage`) before a held-out number is shown as
  solid vs. provisional.
- [ ] **[decide] Default board scopes to the official suite.** Today the default query mixes all
  suites/levels, averaging across different selections. Default-filter to the official
  `(suite, version)` so the headline is apples-to-apples; other suites become an explicit picker.

**C. Web default view (`web/app/page.tsx`)**
- [ ] **[wire] Default sort + title.** `const sort = sp.sort ?? "code_score"` → `"held_out_score"`;
  retitle the hero from "Coder leaderboard" to make held-out the headline (e.g. "Held-out coding
  leaderboard"), and reword the blurb to lead with "challenges published *after* each model's
  release — what it couldn't have trained on."
- [ ] **[build] A Held-out column + coverage badge.** The table shows Code/Agentic/Planner/Safety
  but **no held-out column** — add it as the lead score, with a small `coverage`/`n_clean` badge
  (and an ⚠ when coverage is low) so the contamination basis is visible, not buried.
- [ ] **[wire] Keep contaminated view one click away.** The existing "Rank by" control already
  exposes `code_score`; label it clearly as the all-corpus/backwards-compat view so the opt-in is
  honest, not hidden.

**D. Decisions to lock before any of the above ships**
1. Official default **level** (A) — proposed: `standard`.
2. **None/low-coverage** display policy + minimum coverage threshold (B).
3. Whether the default board hard-scopes to the official **(suite, version)** (B).
4. Confirm the **frontier band is explicitly deferred** to a post-calibration slice (A) — and
   nothing in the UI implies adaptive selection until it exists.

**The one-line test of success:** a first-time visitor lands on a board that, by default, ranks
models on *challenges they couldn't have trained on*, on *the same comparable test set*, with the
contamination basis visible — and can opt into the saturated all-corpus view, never the reverse.

## 10. North star

> A person with a GPU types one command, sees the open models that fit their card ranked by a
> number they can re-derive and that no model could have memorized — and, when they want, points
> the same tool at their *own* code to find the best model for the work they actually do.

Everything above is in service of that sentence. The public platform makes the frontier legible;
the private Test Crafter makes it personal. Same engine, same reproducibility contract, two halves
of one bet: **that the only benchmark worth trusting is one you can run yourself.**
