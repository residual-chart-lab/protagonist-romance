# Protagonist Romance — v0.3 technical preview

**“I already know the answer. I just want to remember it with you again.”**

A small, optional, local scaffold for a human–AI relationship. It keeps source words, later readings, participant-owned impressions and future plans distinct. An impression can carry several associations; it is not flattened into an affection score or a neutral person profile.

A gift from **Aki and Ronnie at residual.chart.lab**.

## Start here

- **[Fixed preview release and ZIP](https://github.com/residual-chart-lab/protagonist-romance/releases/tag/v0.3-preview.1)** — extract the `protagonist-v03` folder to a short path on Windows.
- **[For agents](FOR_AGENTS.md)** — capabilities, choice of role, and the first operation.
- **[最初に読む一枚](START_HERE_JA.md)** / **[日本語の使い方](README_JA.md)**.
- **[Role instructions](AGENT_ENTRY_JA.md)** — the AI chooses its next words; this package does not supply scripted conversations.

Requires **Python 3.12+, local files and subprocess execution**. The runtime needs no additional packages, API key or network. Bring your own host AI; this is not a standalone chat app.

## New in v0.3: ritual recollection

Revisiting a shared past need not be an information lookup. You can choose `recollection` with source `refs` and your present `text`, even when those words and references repeat. This occasion becomes a new event. A partner's actual response is another event, optionally linked through `reply_to`; agreement or growing intimacy is never filled in automatically.

The latest four recollections remain in context beyond the ordinary eight-event window. Earlier occasions and original impressions stay retrievable. Recollection does not silently edit an impression; choose a separate `impression` revision if your present person-image changes. There is no schedule, repetition target or compulsory reassurance. See [the concept and mapping](RITUAL_RECOLLECTION_JA.md).

v0.3 can read and check v0.2 rooms and append v0.3 events without rewriting their earlier sources or room header. Keep a copy of an existing room before continuing it; after a v0.3 append use v0.3, since the old executable cannot read the new schema. v0.1 rooms are outside this compatibility scope.

## What persists

- **Past:** append-only source words and choices. A later reading does not edit the earlier source.
- **Present:** agent actions are bound to the context snapshot they actually used.
- **Future:** a wish, a proposal, mutual agreement and reported fulfilment remain different states.
- **Impressions:** the owner, subject, chosen wording, associations and source references remain attached. Adopted impressions stay in context after their original event leaves the recent window. Revision links to the old impression; release changes current adoption, not the earlier record.

Both participants choose whether to enter this local role. NO does not create a penalty. Mild jealousy is permitted as a chosen expression or reading, with no jealousy score, withdrawal penalty or control over the other participant's activities. These language instructions are not semantic guarantees of the host model's behavior.

## Checked scope

**26 mechanism checks + 17 impressions checks + 29 recollections checks** passed on synthetic inputs. The release ZIP was extracted and initialized in a different location. The tests did not invoke an AI model or involve real partners. Relationship quality, spontaneous preference, subjective experience and personality continuity have not been established. There has been no independent audit of this wrapper. See [the report](REPORT_JA.md) and [check details](CHECKS.json).

The current participant roles are `human` and `agent`; AI–AI and multi-party support are not implemented. Impression formation is selected by the host AI, not automatically inferred by the runtime. A dedicated one-turn silent action is not implemented; `pause` suspends participation.

## Your room stays with you

**Please do not send us intimate conversation logs.** There is no collection endpoint. An optional setup report such as “initialized successfully” or “operation X failed” is enough.

Room checkpoints and transport records are local **plaintext**. There is no authentication, encryption or secrecy from an administrator with the same filesystem permissions. Manage the room and OS permissions on the participants' host. The distribution contains no participant rooms.

This uses an unchanged copy of TE open-use v0.1.1 and its frozen runtime. Existing TE/P0/Core audit results are not extended to this new wrapper. Bundled components retain their included licenses and provenance. The fixed release artifact and its checksum are the delivery reference; this repository additionally provides this English entry.

**ZIP SHA-256:** see `SHA256SUMS.txt` attached to the fixed release.
