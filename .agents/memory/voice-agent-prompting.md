---
name: Realtime voice agent prompt design (DAWA)
description: Why DAWA's phone assistant hallucinated, looped, and went silent — and the prompt rules that fix each failure mode.
---

# Realtime voice-agent prompting

Four distinct real-call failure modes, each with a distinct prompt-level cause.
These are properties of scripted LLM voice prompts generally, not of one provider.

## 1. Hallucinated facts ← no closed-world rule
An instruction like "only confirm medication intake, don't discuss dosage" is a
*topic* restriction, not an *epistemic* one. The model still answers from general
medical knowledge whenever the patient asks something outside the script.

**Rule:** state explicitly that supplied facts are a CLOSED WORLD, that anything
absent is unknown, that general medical knowledge is forbidden, and give the exact
refusal sentence to speak instead.

**Why:** topic bans tell the model what not to bring up; only a closed-world rule
tells it what it is not allowed to *know*.

## 2. Repetitive looping ← hardcoded script question in the base prompt
Baking `then ask: "have you taken your medicine today?"` into the persistent
assistant prompt makes the model treat that question as a goal state it must
return to after every patient turn. Binary `if yes / if no` branches make it worse:
a patient *question* is a third case that falls off the script, so the model
improvises (hallucination) or resets to the script (loop).

**Rule:** never put a literal script question in a base prompt. Instead instruct:
answer the current question, follow the patient's branch, do not return to the
opening reminder, never restart the greeting mid-call.

## 3. Mid-sentence cutoff then silence ← no turn-length budget
"Keep it brief" is not actionable. Long turns get truncated by telephony turn
detection, and after truncation the model has no defined recovery so it stalls.

**Rule:** a hard numeric budget (one short sentence, ~5-15 spoken words) plus an
explicit "then STOP SPEAKING and wait" that defines yielding the turn.

## 4. Base prompt vs per-call context contradiction
A base assistant prompt carrying clinical truth competes with per-call context
supplying different truth. The model sees both and blends them.

**Rule:** the persistent assistant prompt must be entirely generic — no patient
name, no medication, no clinical facts. All truth arrives per-call.
Verify with a test asserting no domain nouns appear in the base prompt.

## Context format
Realtime LLMs ground far more reliably on short labelled key/value blocks
(`VERIFIED FACTS` / `CURRENT MEDICATION` / `RESOLUTION RULES` / `SAFETY`) than on
Urdu prose paragraphs. Compact structured context also reduces the chance of a
long hallucinated monologue.

## Ambiguity must be derived, never hardcoded
Cue values shared by *every* one of a patient's medications cannot identify one.
Compute that set from the DB. Two separate situations must stay distinct in the
prompt: resolving an *unknown* medicine from patient cues (apply ambiguity rules,
ask the discriminator) versus describing the *already-verified* due medicine
(stating its cues is fine).

**When asking a discriminator question, offer EVERY verified value of ONE key.**
Offering only the first two silently excludes a real medication and pushes the
patient toward a wrong answer. Do not pool values across different cue keys.
