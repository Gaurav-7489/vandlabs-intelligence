# Action-risk matrix (approval policy)

Principle: **separation of duties for material actions.** A requester can never approve their own decision, including owners and in single-person organizations.

| Class | Examples | Path | Approval | Audit |
|---|---|---|---|---|
| Read / analysis | search, insights, ask | direct | none | none for reads; usage accounted for AI |
| **Low-risk internal write** | create or update a task for yourself/team, acknowledge/dismiss an insight, change task status | direct API (`POST /tasks` etc.) with `tasks.write` / `insights.write` | none, **but labelled `origin=direct`; never shown as an approved decision** | `task.created_direct`, `task.status_changed`, `insight.status_changed` |
| **Material internal action** | task created *because of* a recommendation, anything that changes commitments or owners | decision workflow | different person with `decisions.approve` | full decision/approval/execution/outcome trail |
| Administrative | invite/role change/remove members, revoke sessions | `members.write`; only an owner may grant or alter owner/admin | owner rule above; last owner protected | `member.*` |
| External / irreversible (payments, external messages, deletions of critical records) | — | **not implemented; must not be added without a dedicated policy and approval flow** | — | — |

Single-person organizations: the platform deliberately does not offer self-approval. Options are (a) add a second approver (an external advisor can be given the `manager` role), or (b) use the low-risk direct path for low-risk work. A future "break-glass self-approval" would require explicit policy, a written justification field, and a distinct audit label; it is not implemented.
