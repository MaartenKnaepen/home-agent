# Doc Co-Authoring — Structured Technical Documentation

Guide through collaborative document creation in three stages: Context Gathering → Refinement & Structure → Reader Testing.

**Use when:** writing technical specs, decision docs, RFCs, ADRs, phase plans, or any substantial structured document.

---

## Opening

Offer the user the three-stage workflow and explain it briefly:
1. **Context Gathering** — close the gap between what you know and what I know
2. **Refinement & Structure** — build the document section by section
3. **Reader Testing** — spawn a fresh subagent with no context to verify the doc works for readers

Ask if they want the structured workflow or prefer to work freeform. If freeform, proceed without the structure below.

---

## Stage 1 — Context Gathering

### Initial Questions

Ask the user:
1. What type of document? (spec, decision doc, ADR, phase plan, RFC)
2. Who is the primary audience? (future me, other developers, LLM agents reading it)
3. What is the desired impact when someone reads this?
4. Is there an existing template or format to follow?
5. Any constraints or context to know upfront?

If they mention an existing document, read it with the Read tool.

### Info Dump

Once initial questions are answered, ask the user to dump all relevant context:
- Background on the problem
- Why alternative approaches weren't chosen
- Technical dependencies or constraints
- Relevant decisions from `docs/LLM/memory.yaml`
- Timeline or scope constraints

Advise them not to organize it — just get it out.

### Clarifying Questions

After their dump, generate 5–10 numbered questions based on gaps:

> "1: What happens if the MCP server is down?
> 2: Is this intended to be read by LLM agents or humans?
> 3: ..."

Let them answer in shorthand (e.g., "1: graceful degradation, 2: both").

**Exit Stage 1 when:** you can ask about edge cases without needing basics explained.

---

## Stage 2 — Refinement & Structure

### Propose Structure

Based on document type, suggest 3–5 sections appropriate for it.

Example for an architecture decision doc:
- Context and Problem
- Decision
- Alternatives Considered
- Consequences
- Implementation Notes

Ask if the structure works or needs adjustment.

### Create Scaffold

Use the Write tool to create the file at an appropriate path (e.g., `docs/LLM/plans/design-{feature}.md`).

Create it with all section headers and `[To be written]` placeholders.

### Work Section by Section

For each section:

**Step 1 — Clarify**
Ask 3–5 specific questions about what to include in this section.

**Step 2 — Brainstorm**
Generate 5–15 numbered points that might belong in this section.
At the end: "Want more options?"

**Step 3 — Curate**
Ask which points to keep, remove, or combine.
Accept shorthand: "Keep 1,3,5. Remove 4 (already covered above). Combine 7 and 8."

**Step 4 — Draft**
Use the Edit tool to replace the placeholder with real content.

**Step 5 — Refine**
Ask them to indicate changes rather than edit directly — this helps learn their style.
Use the Edit tool for all changes. Never reprint the whole document.

After 3 iterations with no substantial changes, ask if anything can be removed without losing information.

Confirm section complete. Move to the next.

### Near Completion

When 80%+ of sections are drafted, read the full document and check:
- Flow and consistency
- Redundancy or contradictions
- Generic filler ("slop") — every sentence must carry weight
- Whether it achieves the stated impact

Provide a final pass of specific suggestions.

---

## Stage 3 — Reader Testing (Claude Code Sub-Agent)

Spawn a **general-purpose** subagent with the following instructions:

```
You are a reader with no context about how this document was created.
Read the document at {DOCUMENT_PATH} and answer these questions:

1. {QUESTION_1}
2. {QUESTION_2}
[... 5-10 questions a real reader would ask ...]

For each question:
- Provide your answer based only on the document
- Note anything that was ambiguous or unclear
- Note any knowledge the document assumes you already have

Also check:
- Are there internal contradictions or inconsistencies?
- What is the single most confusing part of this document?
```

Generate 5–10 realistic reader questions based on the document type and audience before spawning.

### Interpret Results

After the subagent returns:
- If it answered correctly with no confusion: the doc is ready
- If it struggled: identify the problematic sections and loop back to Stage 2

### Final Review

When reader testing passes:
1. Recommend the user do a final read-through — they own this document
2. Suggest double-checking any facts, links, or technical details
3. Ask if they want one more review pass or are done

**Completion tips:**
- Consider linking this conversation in an appendix
- Use appendices to provide depth without bloating the main doc
- Update the doc as feedback arrives from real readers
