---
name: receipts-review
description: Review and tidy the user's Receipts career record. Find incomplete entries, duplicates, timeline gaps and open follow-ups, then fill them in with the user. Use when the user asks what's missing, wants to tidy up, or asks where they are on the timeline.
---

# Review the career record

## 1. Look at the whole thing

- Call `overview` and `timeline`.
- Check the timeline: gaps between roles, overlapping roles that look wrong, roles with no or very few
  entries, and long stretches with nothing recorded.
- Call `search_entries` with no query (and `detail=true` for a role at a time if there are many) to
  find entries that are:
  - missing a date, role or competencies,
  - missing a result or impact,
  - carrying open `follow_ups`,
  - really two stories in one (split them),
  - duplicates of each other (merge them).

## 2. Report briefly

Give the user a short list, most useful first: "Your 2022–2025 role has three entries; the one before it
has twelve", "Four entries have no outcome", "Two entries look like the same restructure". No scores, no padding.

## 3. Work through it together

- Ask the open follow-up questions in small batches (three or four at a time), grouped by story.
- Apply answers with `update_entry` as they come in.
- Before merging or deleting anything, say exactly what you'll do and wait for a yes. To merge:
  update the better entry with the combined detail, then `delete_entry` the other.
- Fix role dates with `update_role`. Entries without a role can be placed by setting `role_id`.

## Rules

- Never invent details to fill a gap. An empty field is better than a guessed one.
- Keep each entry to one story.
- Leave `raw` alone unless the user asks you to change it.
