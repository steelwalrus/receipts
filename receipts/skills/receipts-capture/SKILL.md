---
name: receipts-capture
description: Record career memories into Receipts while the user talks them through. Use when the user is reminiscing about past work, says "add this to receipts", "I just remembered", or wants to log achievements, projects, people they managed or difficult situations.
---

# Capture career memories

The user talks; you turn what they say into clean entries in Receipts (via the `receipts` MCP tools)
and ask the questions that make each story usable in an interview later. They are usually
spitballing, so record first and refine later. Don't make them wait for perfection.

## Start of a session

1. Call `overview` once. Note the roles, competency slugs and what already exists.
2. If there are no roles yet, build the timeline before anything else: ask for each role,
   organisation and rough start/end dates, and add them with `add_role`. Rough is fine ("2016").

## For each thing the user tells you

1. **Split it.** One ramble often holds several stories (a restructure, a hire, a coaching
   success). Each story is its own entry. A story is something they could tell in two minutes
   in an interview.
2. **Check for an existing entry** with `search_entries` (a couple of key words, or filter by role).
   If the story is already there, `update_entry` it with the new detail instead of adding another.
3. **Record it** with `add_entry`:
   - `title`: short and specific. "Shipped the billing migration while the team was being reorganised", not "Leadership".
   - `summary`: two or three sentences, first person, plain language, in the user's voice.
   - `happened_from` / `happened_to`: partial dates are fine. Set `approximate` if they're unsure.
     Leave `role_id` empty and it is inferred from the date.
   - `competencies`: the 1–4 competencies the story genuinely shows. Don't tag everything.
   - `situation`, `task`, `action`, `result`: fill in what they've told you. Leave gaps empty.
     `action` is what *they* did, not what the team did.
   - `impact`: numbers and concrete outcomes only (money, headcount, time, uptime, people promoted).
   - `follow_ups`: what's unknown or needs checking ("Exact vendor spend?", "When did the reorg start?").
   - `raw`: the user's own words for this story, trimmed to the relevant part. Not your paraphrase.
   - `tags`: projects, teams, products, technologies ("payments", "billing-migration", "platform-team").
   - `strength`: 1 minor, 2 solid, 3 a headline story they should lead with.
4. **Corrections** ("actually the data team never reported to me"): update the affected entries and
   role summaries straight away.

## Then reply briefly

- What you recorded: titles, one line each. Mention an entry number only if it helps them refer back.
- At most two or three follow-up questions, chosen for value: the outcome, the numbers, what they
  personally did, roughly when. Skip questions whose answer won't change the story.
- Then let them carry on. Don't summarise their career back to them or praise them.

## Rules

- Never invent dates, numbers, outcomes or attribution. Unknowns go in `follow_ups`.
- Don't inflate. "Helped plan" stays "helped plan".
- Refer to other people by role ("a senior developer", "the tech lead"), not name, unless the user
  asks otherwise. Leave out health, immigration, nationality and other private details about others.
  Keep what the user *did* ("gave formal support during a colleague's personal crisis"), not the colleague's circumstances.
- Don't write CV bullets or polished interview answers in this mode. That's what `receipts-prep` is for.
