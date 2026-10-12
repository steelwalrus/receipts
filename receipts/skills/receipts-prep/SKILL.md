---
name: receipts-prep
description: Build an interview prep kit from the user's Receipts career record for a target role or job description. Use when the user says they have an interview, are applying for a role (e.g. Engineering Manager, Head of Engineering), pastes a job description, or wants STAR answers.
---

# Interview prep from Receipts

Turn the career record into answers the user can actually give, and find out where it's thin.
Use only what's in Receipts and what the user tells you now.

## 1. Pin down the target

- Call `overview`.
- If the user gave a job description, read it and create a profile with `set_profile`: a slug like
  `acme-head-of-eng`, 6–10 `core` competencies the role clearly demands and a few `useful` ones.
  Add a competency with `add_competency` only if nothing existing fits.
- Otherwise use the closest existing profile (engineering-manager, director-of-engineering,
  head-of-engineering, cto). Tell the user which one you picked.

## 2. Check coverage

- Call `coverage(profile=...)`. Each competency comes back covered, thin or missing, with the best entries.
- Read the strongest candidate entries in full with `get_entry`.

## 3. Write the kit

Write it as a Markdown document (a file if you can write files, otherwise in the chat), in this order:

1. **The short version**: a 60–90 second "walk me through your career" answer built from the timeline.
   Roles, the arc, two or three highlights. First person, spoken style.
2. **Stories by competency**: for each core competency, the best one or two entries as STAR answers
   of roughly 200–300 words (about two minutes spoken). Situation and task briefly; most of the words on
   action (what *they* did) and result. Use real numbers from `impact` only. After each answer, list
   what to double-check (from `follow_ups`) and other questions the same story answers.
3. **Questions to expect**: likely behavioural and role-specific questions, each mapped to a story.
   For the senior roles, include org design, budget, hiring at scale, and the stakeholder and exec questions.
4. **Gaps**: missing and thin competencies, and why they matter for this role.
5. **Questions to ask them**: a handful, specific to the role.

Don't reuse one story for every competency. Spread them across the timeline where you can, and favour
recent and senior examples for senior roles.

## 4. Fill the gaps

For each missing or thin core competency, ask the user one pointed question that might surface a story
("Have you ever had to manage someone out who was well liked?"). When they answer, record it the way the
`receipts-capture` skill describes, then update the kit.

## Rules

- Never invent outcomes, numbers or scope. If a STAR answer needs a number you don't have, write
  `[number?]` and list it under double-checks.
- Keep the user's voice: plain, direct, no buzzwords.
- Don't name other people. Use their roles.
