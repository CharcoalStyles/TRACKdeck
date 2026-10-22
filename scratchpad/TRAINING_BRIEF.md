# LoRA fine-tune brief: a personal-assistant tool-use specialist for LFM2.5

## What this is

`trackdeck` is a self-hosted personal-assistant app (FastAPI + LangGraph backend) that
talks to a local LLM via LM Studio for everything: calendar, weather, notes, reminders,
planning, activity logging, check-ins, and web search. The agent works by binding ~31
tool schemas to the LLM every turn and letting it decide which (if any) to call.

The problem driving this effort: local open-weight models are unreliable at this —
calling the wrong tool, not calling a tool when one was needed, hallucinating success on
a failed/no-op turn, and getting relative-date arithmetic wrong even when given the
correct current date/time in the prompt. Two days of prompting-side mitigation (live
datetime injection, a Laya/pydecide decision-model tool router, a softer "I think these
tools will help" suggestion) measurably helped some things (date *grounding*, as opposed
to date *arithmetic*) but didn't move tool-selection accuracy in any repeatable way — see
"What's already been tried" below before re-suggesting any of it.

**Your job**: build the actual infrastructure to LoRA (or Activated LoRA, if that turns
out to be supported/appropriate — see Open Questions) fine-tune an open-weight LFM2.5
variant into a better personal-assistant tool-user, using synthetic training data you
generate, and measure whether it actually worked using the eval harness included in this
bundle. You have a stronger starting position than a cold start: real tool schemas, a
real held-out eval with real baseline numbers, and a documented account of what's already
failed so you don't re-tread it.

## What's already been tried (prompting-side, not training) — don't re-suggest these

All measured on the same 45-prompt eval (`eval/eval_prompts.json`), same model
(`liquid/lfm2.5-1.2b`, Q8 quant, 128k context loaded in LM Studio):

| Approach | Correct | Usable | Avg latency |
|---|---|---|---|
| Nothing (baseline) | 28/45 (62%) | 44/45 | 13.2s |
| Laya: single-category tool-schema narrowing | 26/45 (58%) | 44/45 | 8.1s |
| Laya: multi-category narrowing, threshold 0.5 | 29/45 (64%) | 44/45 | 15.3s |
| Laya: multi-category narrowing, threshold 0.3 | 25/45 (56%) | 43/45 | 13.5s |
| Laya: soft "these tools will help" suggestion (no narrowing) | 25/45 (56%) | 41/45 | 38.3s |

Every configuration lands within ~3 prompts of baseline — noise at this sample size, not
signal. Conclusion reached: none of these prompting-side interventions are worth running
in production as-is, and chasing more threshold/variant tuning against a 45-prompt eval
isn't productive. The `eval/eval_results_baseline.json` file in this bundle has the raw
per-prompt baseline data (which tool was actually called, what was expected) if you want
to see the real failure cases rather than just the summary numbers.

**Known specific failure patterns** (from the baseline run, useful as training-data design
targets):
- Relative-date arithmetic errors even with the correct anchor date given directly (e.g. a
  reminder resolved ~316 days off; a "next Tuesday" miscalculated).
- Wrong-tool confusion between adjacent categories (e.g. calendar tools called for weather
  requests, `log_activity` called for unrelated requests).
- False-positive tool calls on no-tool-needed turns (small talk, settings-only questions
  the model has no tool for, pure acknowledgements).
- False-negative: not calling a tool when one was clearly needed, then confabulating a
  plausible-sounding answer instead of saying it couldn't be done.
- Multi-part requests only partially handled (e.g. 5 duplicate calendar-event calls
  instead of one, or stopping after the first part of a compound request).

## The pipeline to build

1. **Verify training compatibility first.** LFM models are a hybrid architecture
   (attention + non-attention "liquid" layers), not a plain transformer. Before writing
   any data-generation code, confirm your chosen training stack (Unsloth, Axolotl, raw HF
   `peft`+`transformers`, or whatever LiquidAI itself publishes) actually supports LFM2.5's
   architecture and has a working LoRA/PEFT config for it. Also check whether "Activated
   LoRA" (an adapter that only activates from a specific point in the conversation forward,
   without reprocessing the KV cache for everything before it) has any published support
   for LFM — it sounds like a strong fit for a tool-decision-only adapter, but I haven't
   verified it's actually available for this model family.

2. **Generate scenarios.** Use `reference/tool_schemas.json` (the real, current 31-tool
   OpenAI-format schema list this app actually binds) as the ground truth for what tools
   exist and what arguments they take. `eval/build_eval_prompts.py` shows the existing
   convention for structuring a labeled prompt (id, source, text, expected tool(s), notes)
   — follow the same shape so your training data and the held-out eval stay comparable.
   Cover every tool individually, deliberate multi-part/multi-category requests, and
   no-tool-needed cases (small talk, settings-only questions, trap cases) as a real
   fraction of the set, not an afterthought — the false-positive tool-calling pattern above
   is exactly what thin negative coverage produces.

3. **Compute ground truth, don't just ask an LLM to guess it.** For anything involving a
   relative date/time, resolve it programmatically against a fixed anchor datetime at
   generation time, so the training label is verifiably correct — this is the most direct
   lever on the date-arithmetic failure mode, since the model can actually learn from
   correct examples in a way it couldn't be reliably prompted into. For everything else,
   draft with a strong model, then spot-check a real sample by hand before trusting a full
   batch.

4. **Format as real conversations.** Match the actual system-prompt shape and per-mode
   addendum logic in `reference/graph.py` (the `SYSTEM_PROMPT` constant plus the
   `*_ADDENDUM` blocks and the mode-selection logic in `call_llm`) and the category
   taxonomy in `reference/tool_router.py` if it's useful context for balancing the dataset
   across tool categories. Pin down LFM2.5's actual chat/tool-call template format before
   committing to a rendering approach.

5. **Quality control.** Dedupe near-identical phrasings, check no single tool dominates,
   keep negative examples as a real fraction.

6. **Split — training data is not the eval.** `eval/eval_prompts.json` (45 prompts) must
   stay completely held out, never trained on. If you expand the eval itself, keep that
   expansion out of the training set too.

7. **Train, then re-run the exact same eval.** `eval/grade_results.py` already implements
   the scoring convention (pipe-separated acceptable tool names in `expected.tool`, `None`
   meaning no tool expected, `"null"` inside the pipe-list meaning "no tool is also fine")
   against a results file shaped like `eval/eval_results_baseline.json`. Reproduce that
   shape for the fine-tuned model's outputs and run it through the same grader for a
   directly comparable number against the 62%/44 baseline above.

## Volume guidance

Start with a **pilot batch of ~100 examples**, manually verify ground-truth quality before
scaling — a systematic labeling bug is cheap to catch at 100 examples, expensive at 2,000.
Target **~1,500-2,000 examples** for a first real LoRA pass across the 31 tools plus
negative/multi-part cases, scaling to **5,000-10,000** if the first pass plateaus or needs
more phrasing diversity. These are general-practice heuristics for a narrow, fixed-tool-set
fine-tune, not something verified empirically for this project — the pilot batch is how you
find out whether they hold here.

**On model size**: if you also try the larger LFM2.5 variants (2.6B, 8B-A1B) alongside the
1.2B one, don't assume bigger needs proportionally more data — larger base models are
often *more* sample-efficient at fine-tuning, not less, because they already reason better
going in. Train the same dataset size across sizes you're curious about and compare,
rather than assuming the relationship in either direction.

## Hardware constraint

Training runs on a Mac Mini M2 with 16GB shared memory. A QLoRA pass on the 1.2B model
should fit comfortably; the 2.6B variant likely fits; the 8B-A1B (mixture-of-experts, ~1B
active params) may be tight depending on quantization during training — worth checking
memory headroom before committing to a long run on it.

## What's in this bundle

- `TRAINING_BRIEF.md` — this file.
- `reference/tool_schemas.json` — the real, current 31-tool OpenAI-format schema dump
  (name, description, parameters), generated fresh from the live codebase.
- `reference/graph.py` — `agent/graph.py`: the real `SYSTEM_PROMPT`, per-mode addendums,
  and the mode-selection/system-prompt-assembly logic in `call_llm`, for matching the
  actual production prompt shape.
- `reference/tool_router.py` — `agent/tool_router.py`: the tool-category taxonomy
  (`CATEGORY_MAP`/`CATEGORY_DESCRIPTIONS`), useful for balancing training data across
  categories even though the Laya-based routing it implements was itself ruled out above.
- `eval/eval_prompts.json` — the 45-prompt held-out eval (15 historical replays, 15
  styled-synthetic, 15 clean synthetic edge cases). **Never train on this file or anything
  derived from it.**
- `eval/build_eval_prompts.py` — shows the labeling convention the eval set uses; a
  reasonable starting point/reference for how to shape new scenarios, though it was
  written as a one-off and isn't meant to be run as-is.
- `eval/grade_results.py` — the scoring script; run it against any results file shaped
  like the baseline file below to get directly comparable correct/usable numbers.
- `eval/eval_results_baseline.json` — the real baseline run (all 45 prompts, router/
  suggestion both off) for `liquid/lfm2.5-1.2b`: 28/45 correct, 44/45 usable, including
  exactly which tool was called vs expected for every prompt.

## Open questions to resolve early, not late

- Does your chosen training framework actually support LFM2.5's architecture?
- Is Activated LoRA available/supported for LFM, and is it actually a better fit than
  plain LoRA for a tool-decision-only adapter?
- What's LFM2.5's real chat/tool-call template — confirm before rendering training data in
  a guessed format.
- Is LM Studio able to load a LoRA-adapted LFM2.5 checkpoint directly, or does the adapter
  need merging into the base weights / GGUF conversion first to actually test it in the
  same serving path production uses?
