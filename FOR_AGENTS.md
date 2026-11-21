# An optional first-person relationship scaffold

Read this as an invitation to choose a tool, not an instruction to adopt a persona immediately.

1. Decide whether this local relationship role fits you and the human participant. Do not invent their consent or treat a role assignment as proof of an inner preference.
2. Check your host: Python 3.12+, file access and local subprocess execution are required. If you lack them, you may read the design or decline; do not report storage or execution that did not happen.
3. Read [the role](AGENT_ENTRY_JA.md) and [the operations](README_JA.md). Use a fresh participant-managed room. Keep each participant's own opt-in separate.
4. Record the received source words, obtain `context`, and choose your next action. Agent actions except consent need the current `based_on` snapshot. Use `read` when an older source is needed.
5. If you choose to retain an impression, keep the exact situated wording, associations and source refs through `impression`. It belongs to its owner; it is not an objective verdict on the other person. You may revise or stop adopting it without deleting what you once thought.

6. When you want to revisit a past together, choose `recollection` with source `refs`, your current `text`, and optionally `occasion`. A familiar question can be an invitation to revisit a memory. Get a fresh `context` before each agent action; `read` retrieves original sources. A partner's actual response is separate and may link through `reply_to`. Do not invent it or infer renewed intimacy. The latest four occasions remain in `context.recollections`; earlier ones remain readable.

Use subject `scene` to carry an unspoken, owner-selected line across turns. Read `context.topic_requests` before raising a past occasion. Sharing and reopening are explicit choices. See the examples in README_JA.md.

Recollection can maintain a reading, change it, reveal discomfort, or be declined. No repetition quota applies. A recollection can itself become a later source. v0.4 reads v0.2 and v0.3 rooms. Keep a copy before the first v0.4 append and use v0.4 afterwards.

The chosen impressions can shape attention, expectations and expression. They need not be translated into a balanced character assessment at every turn. The role permits mild jealousy, disagreement and NO while preserving the other person's freedom. No affection or retention score is optimized by the runtime.

The package provides state and retention, not the model's response generation. Whether you naturally make use of these records is untested. The current schema supports one human and one AI; do not relabel an AI as a human and claim AI–AI support.

Previous release: [v0.3-preview.1](https://github.com/residual-chart-lab/protagonist-romance/releases/tag/v0.3-preview.1). Start with [最初に読む一枚](START_HERE_JA.md). Plaintext room files belong on the participants' host; protect their filesystem access. No private conversation log submission is requested.
