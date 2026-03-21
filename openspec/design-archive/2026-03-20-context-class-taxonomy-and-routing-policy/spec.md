# Context Class Taxonomy and Routing Policy — Design Spec (extracted)

> Auto-extracted from docs/context-class-taxonomy-and-routing-policy.md at decide-time.

## Decisions

### Four stable context classes: Compact (128k), Standard (272k), Extended (400k), Ultra (1m+) (decided)

These classes match the real breakpoints currently observed across Anthropic, OpenAI, Copilot, Codex, and local Ollama models. They are easy for operators to reason about and stable enough to survive upstream drift. Exact token counts remain internal metadata; the classes are the operator-facing and policy-facing abstraction. 1.05M does not need its own class — it belongs in Ultra.

### Routing state tracks both active context capacity and required minimum context floor (decided)

Safe routing requires distinguishing the capacity of the currently selected model from the minimum capacity the current session can safely tolerate. The state model therefore tracks: activeContextWindow/activeContextClass, requiredMinContextWindow/requiredMinContextClass, optional pinned floor, observed usage/headroom, and downgrade safety arm/override status. Without both active and required minima, the harness cannot detect that a proposed switch is unsafe before it happens.

### Revised operator taxonomy: context classes use formation-scale names; thinking levels use Mechanicum cognition ladder (exploring)

Replace placeholder value labels with thematic operator-facing names. Preferred context taxonomy is Mechanicum force scale: Clade (128k), Maniple (272k), Cohort (400k), Macroclade (1m+). Fallback for broader legibility is Astartes force scale: Squad, Company, Chapter, Legion. Preferred thinking taxonomy is Mechanicum cognition ladder: Servitor, Functionary, Adept, Magos, Archmagos, Omnissiah. These keep context and thinking semantically distinct: context names describe operational span, thinking names describe cognitive sophistication.

### Final operator taxonomy: context classes are Squad / Maniple / Clan / Legion; thinking levels are Servitor / Functionary / Adept / Magos / Archmagos / Omnissiah (decided)

Context names should express formation scale and memory span, not generic size claims. The blended Iron Hands / Mechanicum ladder is the strongest fit: Squad (128k), Maniple (272k), Clan (400k), Legion (1m+). It is intuitive, branded, and operator-friendly. Thinking levels should express cognitive sophistication rather than memory size, using the accepted Mechanicum ladder: Servitor, Functionary, Adept, Magos, Archmagos, Omnissiah. This keeps context, thinking, and capability tier as three clearly distinct semantic axes.

### Downgrades are evaluated against concrete route envelopes and classified as compatible, compatible-with-compaction, degrading, or ineligible (decided)

Because upstream providers offer fixed route ceilings rather than arbitrary context selection, the harness must compare the current session's required minimum context floor against a reviewed local matrix of concrete provider/model envelopes. Each candidate route is classified as: compatible (ceiling satisfies the floor directly), compatible-with-compaction (safe compaction can reduce the floor enough), degrading (cannot satisfy the floor safely without operator risk acceptance), or ineligible (fails capability tier, thinking level, policy, or other route constraints). This route-envelope classification becomes the basis for all automatic and manual downgrade behavior.

### Downgrade policy: auto-reroute when compatible, auto-compact only inside safe policy bounds, otherwise require explicit operator confirmation (decided)

The harness first searches for a compatible route that satisfies capability tier, thinking level, and required context floor; if found, it may reroute automatically. If no such route exists, it may compact and reroute only when compaction is judged safe, no pinned floor is violated, and policy allows automatic compaction. If the best available route still falls below the required floor, crosses a pinned floor, or would cause a large multi-class degradation, the harness must stop and require explicit operator confirmation. Unsafe context downshifts must never happen silently. In short: prefer compatible reroute, then safe compaction, then operator-confirmed degradation.

### Routing selection starts from authenticated available providers and uses an opinionated default-provider preference with operator override (decided)

Model selection should first filter to providers/routes the operator is actually logged into and allowed to use, making cross-provider routing a real but bounded edge case rather than an abstract global search. Within that feasible set, Omegon may ship an opinionated default preference order — initially preferring Anthropic routes where capability tier, thinking level, context floor, and policy constraints are all satisfied. This gives stable out-of-the-box behavior while still allowing operators to dismiss, set, or toggle a different default provider preference. Provider preference is therefore a user-configurable routing policy layered on top of hard feasibility checks, not a hidden override of safety constraints.

### Dangerous context-degrading switches use explicit confirmation with durable 'don't ask again' style override controls (decided)

When the best available route requires compaction or a context downgrade that crosses a safety boundary, the harness should present an explicit confirmation dialog describing the current route, target route, context class delta, whether compaction will occur, and the likely consequences. The operator may approve once, cancel, or choose a durable override such as 'always allow this downgrade class/provider transition' or 'prefer provider X by default'. This mirrors other dangerous-operation prompts: safety is armed by default, but operators may intentionally disengage it and persist that choice. Persisted overrides must remain visible and reversible in settings.

### Argo control plane refreshes provider metadata on a schedule, emits reviewed route-matrix snapshots, and opens issues/PRs on drift (decided)

A scheduled automation workflow should probe upstream model catalogs, official docs pages, and local installed metadata sources, then normalize the results into a route-envelope snapshot. On each run it compares the proposed snapshot against the currently reviewed local matrix. If nothing changed, it records a green report and exits. If context ceilings, breakpoint zones, output limits, or route availability changed, the workflow should open or update an issue summarizing the drift and, where safe to automate, generate a PR updating the checked-in route matrix and derived context-class mappings. Routing at runtime must consume only the last reviewed local snapshot, never raw live upstream data.

### Refresh pipeline uses three stages: collect, assess drift, promote reviewed snapshot (decided)

Stage 1: Collect — scheduled Argo workflow fetches authoritative sources (provider docs/catalog APIs where available, installed Pi/Omegon model catalogs, and optionally smoke probes for known routes) and normalizes them into a candidate route matrix. Stage 2: Assess drift — compare candidate vs current reviewed snapshot; classify deltas as additive, limit increase, limit decrease, route removal, breakpoint change, or ambiguity. Stage 3: Promote — additive and confidence-high updates may generate an auto-PR; risky changes such as context decreases, removed routes, or conflicting sources must open/refresh a human-review issue and block automatic promotion until approved. This gives dynamic upstream awareness while preserving a stable, reviewable local abstraction.

## Research Summary

### Providers expose fixed route ceilings, not operator-selectable context sizes

Upstream providers and local runtimes generally do not let operators choose an arbitrary context size per request. Instead, each concrete route has a fixed offered envelope. Current observed examples: Anthropic API Claude Opus 4.6 = 1,000,000 and Claude Sonnet 4.6 = 1,000,000; OpenAI API GPT-5.4 = 272,000, GPT-5.4 Pro = 1,050,000, GPT-5.4 mini = 400,000; GitHub Copilot Claude 4.6 routes = 128,000, GitHub Copilot GPT-5.4 = 400,000; OpenAI Codex GPT-5.4 = 272,000; local Ollama models in this envir…

### Some providers have breakpoint zones inside a larger ceiling

Even where a route supports a large ceiling, provider docs expose important internal breakpoints. Anthropic docs indicate Claude 4.6 requests over 200k input tokens now work automatically without beta headers, making 200k a meaningful operational boundary even within a 1M route. OpenAI docs indicate GPT-5.4 long-context routes have a 272k breakpoint above which full-session pricing changes materially. These are not separate selectable context modes, but they are policy-relevant stability/cost zo…

### Control-plane requirement: track upstream drift without routing against live claims

Provider context metadata changes over time and sometimes regresses or diverges by transport. Pi/Omegon therefore should not fetch provider claims at request time and trust them blindly for routing. Instead, upstream state should be monitored on a schedule, compared against the checked-in local route matrix, and promoted only through a reviewed snapshot. This keeps operator behavior stable while still tracking a fast-moving provider ecosystem.
