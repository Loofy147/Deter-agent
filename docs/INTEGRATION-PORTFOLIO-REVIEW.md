# Integration Portfolio Review: Keyvault and Related Repositories

**Reviewed:** 2026-10-26  
**Target:** `Loofy147/Deter-agent`, feature branch `spec/deterministic-control-hardening`  
**Disposition:** architecture and integration boundary review; no runtime secret-provider dependency is added by this document.

## Executive decision

Reuse the existing projects through explicit host-owned interfaces. Do not copy whole subsystems into Deter-agent or treat a repository's green tests as proof that the repository is a production security boundary.

- **Keyvault** is the candidate local credential-use broker. Keep it local and optional until its own P0 release blockers are closed.
- **Loofy-Extensions** is the closest architectural reference for exact-scope grants, host-side authorization, durable task results, and a local audit hash chain. Its own documentation states that identity and approval verification remain host responsibilities.
- **Conversational** is the reference for immutable revision history, source/provenance binding, replay/restore verification, and explicitly separating restored context from authority for external actions.
- **Context-swarm** is the repository-native source-intake and dependency-impact workflow. Its current operating model does not require a database or deployed service.
- **Ledger System** is a deterministic decision/context ledger, not an authorization service or tamper-proof event store.
- Security fuzzing, project intelligence, context curation, and CI/CD workflow collections are supporting development tools, not components of the runtime trust boundary.

## 1. Keyvault assessment

Repository: https://github.com/Loofy147/keyvault  
Release-gate evidence: https://github.com/Loofy147/keyvault/blob/main/docs/PRODUCTION_READINESS.md  
Threat model: https://github.com/Loofy147/keyvault/blob/main/docs/THREAT_MODEL.md  
Architecture: https://github.com/Loofy147/keyvault/blob/main/docs/ARCHITECTURE.md

### Verified capability

Keyvault is a local encrypted credential vault with a CLI, a loopback-only UI, a stdio MCP server, and a credential-injecting HTTPS proxy. Its MCP interface exposes credential metadata and a credential-backed HTTP request; it does not provide a tool that returns stored secret values. Its README describes scrypt + AES-256-GCM at rest, credential host/method allowlists, request/response limits, best-effort redaction, and an OS-native credential store for the cached derived key by default.

Its own authoritative release-gate file says **NOT PRODUCTION READY**. The following remain explicit blockers:

1. **P0 — Destination IP / SSRF boundary:** host allowlists are not enough. DNS answers are not validated and pinned at connection time, so DNS rebinding and private/loopback destination risks remain.
2. **P0 — Native keychain evidence:** macOS Keychain, Windows Credential Locker, and Linux Secret Service behavior have not been verified on the native platforms; tests use a double.
3. **P0 — Cross-process writes/recovery:** the documented write behavior is last-writer-wins. Cross-process locking or compare-and-swap and crash-recovery tests remain open.
4. **P0 — Local UI:** browser-driven end-to-end security coverage remains incomplete. The UI is local-only and must not be exposed through a public tunnel, reverse proxy, port forwarding, or LAN binding.

The repository metadata currently reports no license. Resolve licensing before presenting it as a generally reusable package or external dependency. Internal use by the same repository owner is a separate issue from redistribution rights.

### Safe integration boundary

Deter-agent must store a **credential reference**, not the credential value. The deterministic engine remains responsible for selecting the action, validating the frozen decision, applying policy, approval, idempotency, state-CAS and outcome verification. A host-owned adapter may call Keyvault using a named credential only after Deter-agent has authorized the exact action.

If both layers are used, authorization is conjunctive: **Deter-agent permits the action AND Keyvault permits the destination host/method**. Neither layer can override a denial from the other. Keyvault should never receive the Deter-agent database, policy-authority role, evaluation records, approval decision rights, or production identity authority.

A future adapter must not put secret values in agent specs, rule metadata, frozen decisions, traces, evaluation results, policy diffs, exception messages, or model-visible tool outputs. Never call Keyvault's direct secret-printing CLI command from an agent/model-visible path.

### Bootstrap signing use case

A locally held operator signing key could be stored as a Keyvault credential and made available only to a short-lived, operator-invoked seed-signing process. The resulting seed is then verified by Deter-agent against an independently pinned public key. This is a proposed operator workflow, **not an implemented or tested end-to-end integration**. The private key must never be committed, added to the seed payload, or supplied to the running agent. Keyvault's process-environment injection deliberately passes plaintext to the selected child process, so the signing child must be trusted and short-lived.

For a deployed, multi-user or remote execution service, prefer a managed secret service / KMS with an explicit identity and rotation model rather than turning this local, single-user vault into a network service.

## 2. Related owned repositories and reuse decisions

| Repository | Verified useful contribution | Deter-agent decision | Limitation that must remain visible |
|---|---|---|---|
| [Loofy-Extensions](https://github.com/Loofy147/Loofy-Extensions) | Exact tenant/principal/version/capability/resource/environment grants; default-deny host gateway; correlated operation audit; transactional SQLite persistence; locally verifiable SHA-256 audit chain; bounded manifest-validation task runner | Reuse the boundary contracts and audit-chain design as implementation references; do not create a second policy authority or extension registry inside Deter-agent | Its README describes a reference implementation. Caller identity and approval verification are host-supplied; the hash chain has no independent trust anchor by itself |
| [Conversational](https://github.com/Loofy147/Conversational) | Immutable event/revision artifacts, canonicalization and digest checks, lineage/source registry, deterministic reduction and restore validation | Reuse the evidence-package and replay-validation pattern for release records and handoffs | Its current trust-boundary document explicitly calls authenticity `SELF_INTEGRITY_ONLY`; repository integrity is not an external signature or proof that claims are true |
| [Context-swarm](https://github.com/Loofy147/Context-swarm) | GitHub source snapshots, typed intake, blocked-vs-empty source distinction, dependency-impact planning, capability verification and bounded repository-native cycles | Use for repository inventory, evidence freshness and planning the next verification/change tasks; keep it outside the per-request execution path | The current operating model is repository-native and explicitly does not require a backend; its plans are proposals, not production authorization |
| [Ledger System](https://github.com/Loofy147/ledger-system-source-of-truth) | Deterministic decision entries, explicit supersession, contradiction checks and an MCP surface | Optional decision/context register for human-readable rationale, if needed | Its own architecture says file persistence does not establish authorization, concurrency safety, immutability against filesystem control, or tamper-proof audit |
| [meta-secure-framework](https://github.com/Loofy147/meta-secure-framework) | Fuzzing, mutation and self-attack testing ideas | Reuse test design ideas against Deter-agent's policy, rule and lifecycle mutants | Do not use it as a production security oracle; its current threat model is only a minimal stub and does not constitute an independent assessment |
| [Syst-me-d-fensif-](https://github.com/Loofy147/Syst-me-d-fensif-) | Attack/defense simulation and deterministic test ideas | Optional offline adversarial test corpus; no runtime dependency | Simulation output is not authorization, and the repository's self-description is not production evidence |
| [Workflows--ci-cd](https://github.com/Loofy147/Workflows--ci-cd) | CI/CD and release workflow patterns | Reuse only individually reviewed templates and controls; keep Deter-agent's validation workflow canonical for this repository | The README describes an early-stage, still-being-populated resource collection |
| [ACE-Agentic-Context-Engineering](https://github.com/Loofy147/ACE-Agentic-Context-Engineering) | Playbook generation/reflection/curation for open-ended context improvement | Optional later knowledge-curation input; accepted changes still require deterministic validation | Generated context must not alter authorization, trust roots, rule priority, or production policy automatically |
| [Project-Intelligence-Contribution-Engine](https://github.com/Loofy147/Project-Intelligence-Contribution-Engine) | Project inventory, work-item planning, source relations and evaluation automation | Useful for planning and tracking this integration work, not as a runtime security dependency | Issue/work-item state is not deployment or authorization evidence |

## 3. Target integration topology

```text
Operator / host identity
        |
        v
Deter-agent: immutable spec + deterministic rules
        |
        v
Deter-agent gateway: exact tool/resource/environment policy
        |
        v
Runtime: approval binding + idempotency + state CAS
        |
        v
Host-owned action adapter (credential reference only)
        |
        +------ local development: optional Keyvault named credential
        |
        +------ deployed service: managed secret service/KMS adapter
        |
        v
External API / tool

Evidence plane:
Deter-agent SQLite evidence + test/promotion records
        |
        +--> hash-chain + independent checkpoint design (future)
        +--> Conversational-style provenance/replay package
        +--> Context-swarm source snapshots / dependency impact
```

Secret storage is not a policy engine. Context, provenance, audit, secret retrieval, approval, and external-action execution are separate trust domains.

## 4. Integration contract for a future credential adapter

1. The agent action contains a stable non-secret `credential_ref`; no token, passphrase, private key, or Authorization header may come from model input.
2. Deter-agent validates the requested action, tool catalog version, target environment, resource, payload schema, policy version and approval evidence before the adapter is invoked.
3. The adapter accepts only an explicit credential reference plus typed HTTP method/URL/header/body inputs. It cannot choose a credential or widen scope based on model instructions.
4. Keyvault independently enforces credential visibility, host patterns, HTTP method allowlists, managed-auth-header protection, redirects-disabled behavior, response limits and redaction.
5. An adapter error, missing/unlocked credential, stale policy, unavailable authorization state or denied request fails closed. Never fall back to logging or returning the secret.
6. Deter-agent's idempotency contract must match the external provider. A local request key does not prove the remote API deduplicated a side effect.
7. Audit records keep the credential reference, destination host, method, policy/evaluation/approval binding, correlation ID and outcome—not credential values, request secrets, or full secret-bearing bodies.

Do not implement this adapter over Keyvault's HTTP proxy for production until the proxy's P0 destination-IP controls are closed and independently reviewed. A localhost-only process arrangement does not by itself close DNS rebinding in the outbound proxy.

## 5. Evidence and supply-chain controls adopted now

- Use immutable full-commit action references rather than floating major-version tags.
- Test the same deterministic contract on the supported Python version matrix.
- Keep GitHub Actions at least privilege and disable persisted checkout credentials when the workflow only needs read access.
- Preserve the separation between evaluation evidence and promotion approval. A test run, repository restore or audit-chain verification is not an approval.
- Treat hash chains as local tamper evidence only. Establish an independent signed/checkpointed release record before claiming externally anchored audit integrity.
- Keep operator signing keys outside Git history; only the public-key trust root and its fingerprint/configuration reference may be versioned after review.

## 6. Recommended gates, in order

1. **Current PR:** maintain deterministic rule/runtime/registry/evaluation gates and cross-Python CI.
2. **Keyvault hardening:** resolve P0 destination pinning, native keychain evidence, cross-process writes/recovery and UI E2E; decide license and release ownership.
3. **Credential adapter:** implement only with a real external API/tool handler, typed contract tests, fake credential tests, secret-leak checks and idempotency behavior.
4. **Audit provenance:** add a versioned append-only evidence chain for selected Deter-agent events and define an external checkpoint/signature trust root; don't treat a local hash chain as sufficient.
5. **Production identity:** integrate a verified principal/approval provider; bind permissions and approvals to immutable spec/evaluation/policy-diff identities, including expiry and revocation.
6. **Deployment integration:** add provider-specific secrets, timeouts/cancellation, bounded retries, rate limits, monitoring, rollback and recovery evidence.

This review intentionally adds no external-service dependency to the deterministic runtime until the first real integration and its security prerequisites are ready.


## 7. Other repository types in the wider portfolio

The repositories below are useful to assess because the portfolio spans product applications, data acquisition, local-first storage, media generation, infrastructure economics, education, and research. They are **not automatically Deter-agent dependencies**. Reuse should happen at a named interface or a small, tested capability—not by making the projects share a runtime or trust authority.

| Type | Repository and observed capability | Potential value to other projects | Boundary / next evidence required |
|---|---|---|---|
| **Evidence acquisition and provenance** | [My_browser](https://github.com/Loofy147/My_browser) documents a small multi-source acquisition/evidence kernel: canonical JSON, SHA-256 artifact identities, evidence records, transformation lineage/replay, verification records, and SQLite history. Its current source probes accept already-obtained inputs; they do not constitute a full browser or PDF/network transport. | Candidate shared contract for research pipelines, source snapshots, document ingestion and reproducible project investigations. | A digest proves byte identity, not source authenticity or truth. Add real source adapters only with explicit acquisition, retention, licensing and source-verification contracts. |
| **Portable local data and app primitives** | [From-everything-to-apps](https://github.com/Loofy147/From-everything-to-apps) documents a capability-extraction approach rather than copying its large reference collection wholesale. Its current work includes Portable Archive, Record Vault, and Khidma/Archive prototypes with focused tests and stated recovery/cross-browser gates. | Reuse small, tested export/import, versioned local-record, archive validation, recovery and tamper-detection patterns in offline-first tools. | This is **not a secrets vault** and SHA-256 alone is neither encryption nor authentication. Preserve schema versioning, migration, failure recovery, license/provenance and data-loss tests. |
| **Privacy-sensitive decision support** | [digital-twin](https://github.com/Loofy147/digital-twin) documents consent/audit primitives, ownership checks, export/deletion, interpretable profile inference, scenario simulation, and normalized observation ingestion. Its README explicitly labels the local token login as development-only and provider OAuth as configuration-dependent. | Borrow consent lifecycle, data ownership, export/delete and explainable-output patterns where they fit. | Do not reuse its development authentication as production identity. Do not treat heuristic profiles as objective truth or use this system as a clinical, employment, financial, legal or other high-stakes decision-maker. |
| **Video and deliverable production** | [video-workbench](https://github.com/Loofy147/video-workbench) has a local brief/storyboard/render workflow with versioned campaign artifacts, a watermarked MP4 path and technical provenance. The README says deployed multi-user identity, upload workflow and identity-bound approval are incomplete. | Reuse the staged deliverable lifecycle—brief → scope/storyboard → validated render → reviewable artifact—in marketing, product demos and contribution deliverables. | Keep production workbench separate from [FastVideo](https://github.com/Loofy147/FastVideo), which is a large upstream-derived model framework. Selective reuse requires checking upstream license, model/checkpoint terms, model provenance, compute requirements and reproducibility; do not copy the stack wholesale. |
| **Cloud cost and infrastructure governance** | [CloudCostGuard](https://github.com/Loofy147/CloudCostGuard) describes a Go CLI that analyzes Terraform plan JSON, estimates monthly AWS cost deltas and reports them into pull requests, with a pricing service/backend. | Potential optional CI gate for infrastructure-changing repositories: catch estimated cost changes before merge. | Treat “production-ready” in a README as a claim, not release evidence. Verify calculation coverage and freshness of price data, credentials, backend trust, failure behavior, license and real integration tests before using its estimates as a merge gate. |
| **Commerce / marketplace products** | [Doha-platform-](https://github.com/Loofy147/Doha-platform-) describes a marketplace for products and services, including seller storefronts, inventory/orders, buyer discovery, promotion and analytics. [Contribution Network](https://github.com/Loofy147/contribution-network) separately defines a cross-niche outcome/contribution model. | Reuse domain discovery and workflow research, marketplace lifecycle concepts, seller onboarding or delivery/evidence patterns where the business requirements overlap. | Do not merge two distinct business models into one schema simply because both connect participants. Verify payments, refunds, dispute handling, seller rights, data protection, delivery obligations and local legal requirements independently. |
| **Education and gamification** | [Bravolino](https://github.com/Loofy147/Bravolino) describes curriculum-aligned lessons, educational games, progress maps, rewards, parent controls and teacher/classroom workflows. | Its progress and motivation patterns may inform onboarding, learning paths and contribution-level UX; only reuse general interaction patterns when the target users and outcomes match. | Child profiles and learning histories are sensitive. A points/badges mechanism is not evidence of learning impact; require child-safety, consent, data minimization, retention, accessibility and outcomes testing. |
| **Revenue/business operations dashboards** | [Drogon](https://github.com/Loofy147/Drogon) describes an AutoRevenue Pro dashboard for revenue tracking, strategy management, AI insights and integrations. Its setup material includes example JWT/database environment configuration. | Could provide product-specific dashboard or revenue-workflow ideas for business experiments. | Do not infer that revenue strategies are validated or profitable from the UI/README. No autonomous money movement, trading, credential use or other consequential external action should be enabled without separately verified risk, authorization, idempotency and outcome controls. |
| **AI application / model workflow templates** | [ai-chatbot](https://github.com/Loofy147/ai-chatbot) is based on a Next.js AI SDK chat template with multiple model providers and persistence/auth integrations; [run-gemini-cli](https://github.com/Loofy147/run-gemini-cli) documents model-assisted GitHub review, issue triage and coding workflows through Actions. | Reuse UI/provider adapters or bounded review/triage workflow patterns after evaluating current upstream versions and licenses. | Model output remains untrusted proposal text. Scope GitHub permissions, secrets, prompt-injection exposure and generated diffs; require human approval and deterministic checks before merging or releasing. |
| **Mathematical / algorithmic research** | [Solver](https://github.com/Loofy147/Solver) documents combinatorial/symmetry-oriented algorithms, theorem files and benchmarks. | May supply hypotheses, formalization targets, or optimization ideas where a concrete workload has matching mathematical structure. | Independently check proofs, definitions, assumptions and baselines. A README claim, self-generated theorem check or benchmark table is not by itself peer validation or evidence of a production speedup. |
| **Repository portfolio and workflow intelligence** | [Project-Intelligence-Contribution-Engine](https://github.com/Loofy147/Project-Intelligence-Contribution-Engine) inventories project files and technology markers, relates sources, and turns verified gaps into reviewable work plans; [Context-swarm](https://github.com/Loofy147/Context-swarm) maintains source-grounded, versioned repository contexts and dependency-impact plans. | Use these to maintain portfolio inventory, map capabilities to projects, record provenance, and select the next evidence-gated task. | Work plans and context records are planning evidence, not implementation proof, authorization, or proof that a build/deployment succeeded. |
| **Early or under-documented scaffolds** | [ai-meta-orchestrator](https://github.com/Loofy147/ai-meta-orchestrator) has generic starter documentation and a Flask/frontend/Docker shape; [Smart-bot](https://github.com/Loofy147/Smart-bot) exposes only a minimal README in the inspected default branch; [Gptscraper](https://github.com/Loofy147/Gptscraper) currently reports an empty repository. | Keep on the discovery list; inspect actual files, tests, license and history before deciding whether anything is reusable. | Do not rank these as implementations based on their names. No architectural integration is recommended until runnable behavior and ownership/licensing are verified. |

## 8. Cross-repository reuse policy

Apply the following order to every candidate:

1. **State the target problem.** Identify the consumer and the acceptance outcome; do not integrate a repository just because it exists.
2. **Inspect the actual implementation.** Read source, tests, dependency manifests, license, recent history and release gates. README descriptions are discovery signals, not proof.
3. **Extract the smallest capability.** Prefer a small adapter, schema or independently testable algorithm over shared databases, copied applications or cross-repository runtime coupling.
4. **Preserve authority boundaries.** Credentials, identity, policy, approvals, provenance, business data and external side effects must have explicit owners. A capability provider does not become the policy authority.
5. **Verify before adoption.** Add contract tests, negative tests, failure/recovery behavior, license/provenance records and an evidence link to the consuming repository. Reassess maintenance and dependency cost before adding a new runtime.

The current best cross-cutting candidate is the **My_browser evidence contract** for source-bound research artifacts, combined with **From-everything-to-apps** only where a consumer demonstrably needs portable local records. **Deter-agent remains the deterministic execution/authorization layer**, not the place to consolidate all product functionality.


## 9. Additional niche repositories found during the expanded inventory

This section extends the earlier portfolio review. Capability statements reflect inspected repository READMEs and artifacts; promotional status labels are not treated as independent verification.

| Type | Repository and observed shape | Possible portfolio value | Reuse decision / open evidence |
|---|---|---|---|
| **Algerian market data and datasets** | [Algerian-datasets](https://github.com/Loofy147/Algerian-datasets) describes a FastAPI data platform for company, salary and demographic information, data-quality expectations, wilaya/legal-form normalization and economic forecasts. | Could become a source for local-market research, business discovery, market-size hypotheses and Algerian-context applications. | Do not assume collected data is legally reusable, complete, representative or current from the README. Audit every source, collection date, license/consent basis, schema, quality suite and forecasting baseline; isolate private or personal data. |
| **API discovery registry** | [Agentic APIs](https://github.com/Loofy147/agentic-apis) describes a machine-readable catalogue of more than 12,000 APIs, organized into categories and JSON. | Could feed extension discovery, integration research and a shortlist of potential providers without hand-searching each category. | A catalogue entry is not an authorized capability. Check endpoint existence, authentication model, pricing, terms, rate limits, data handling, source license, duplication and freshness. Require an adapter contract and governed approval before enabling an integration. |
| **Multi-tenant business operating platform** | [api-platform-algeria](https://github.com/Loofy147/api-platform-algeria) describes a Node/TypeScript, PostgreSQL, Redis and MinIO business-management API with tenant isolation and a proprietary “All Rights Reserved” license in its README. | Potential source of domain workflows for Algerian SMEs, business records and multi-tenant product requirements. | Treat the stated proprietary license as a hard reuse boundary: no redistribution or code transplant without explicit permission. Read actual tenant-isolation, migration, authentication and authorization tests before relying on security claims. |
| **Bilingual small-business automation** | [algeria-multiagent-platform](https://github.com/Loofy147/algeria-multiagent-platform) describes Arabic/French workflows for sales, support, marketing and operations. [Workflows-n8n-builder-](https://github.com/Loofy147/Workflows-n8n-builder-) describes a larger event-driven, model-gateway and workflow-governance architecture. | Candidate business-process library for locally relevant automations, language-aware workflow design and provider-routing requirements. | Claims such as “production-ready”, “zero-trust” or “post-quantum readiness” require proof in actual configuration, cryptographic code, CI, threat models and operational tests. Prefer exporting individual workflow templates with explicit inputs, side effects and rollback over embedding another orchestration runtime. |
| **Startup, collaborator and investment matching** | [Synapse Platform](https://github.com/Loofy147/synapse-platform) describes founder, freelancer, investor and collaborator roles; project matching; validation; team-costing; financial projections; application workflows and progression. | Significant domain overlap with [Contribution Network](https://github.com/Loofy147/contribution-network). Compare participant onboarding, project readiness, skill matching, collaboration history and paid-service needs as possible research inputs. | Do not merge product concepts by default. Establish distinct target users, actual willingness-to-pay evidence, rules for investment claims, disputes, user data and reward economics before carrying any workflow into the contribution platform. |
| **Fusion engine and multi-sensor reasoning** | [Robust Fusion Platform](https://github.com/Loofy147/robust-fusion-platform) wraps a versioned FusionEngine with a server-side Python bridge, bounded sensor-matrix inputs, fault-scenario demos, diagnostics and persistent demo/licensing records where a database is configured. Its README identifies AGPLv3 licensing. | Possible reference for fault injection, sensor-trust diagnostics, fusion result provenance and a UI that explains system behavior against explicit scenarios. | This is domain-specific, not a general replacement for Deter-agent or My_browser. AGPLv3 is a copyleft obligation, not interchangeable with MIT/permissive terms; do not copy or link code into another distribution without a compatibility decision. Validate the engine independently on reproducible inputs. |
| **Market-data validation and trading research** | [Trading Validations Principles](https://github.com/Loofy147/trading-validations-principles) documents a Market Evidence Governor, retained versioned release archives, raw and normalized Bybit BTCUSDT 1-hour pilot data, and a structural temporal audit. | Useful candidate for evidence-first quantitative research: preserve raw inputs, normalize time boundaries explicitly, track data-quality results and make claims conditional on identifiable evidence. | A structural-temporal PASS does not validate a strategy or show profitability. Require point-in-time data, leakage checks, costs/slippage, out-of-sample and walk-forward testing, baselines, reproducible reports and risk caps before any live-trading consideration. |
| **Autonomous financial execution / ledger** | [Agentdit](https://github.com/Loofy147/agentdit) describes a financial execution layer with double-entry accounting, a Soft Actor-Critic reinforcement-learning agent and automated governance/evaluation. | Its claims can formulate testable research questions around accounting invariants, simulation, risk monitoring and evaluation gates. | **Do not integrate into real-money execution based on README claims.** Independently verify accounting, economic semantics, model training, risk controls, custody/signing boundaries, adversarial behavior and failure recovery. Test in a synthetic sandbox only until reviewed evidence passes explicit release gates. |
| **Crypto UI prototype** | [v0-crypto-dashboard](https://github.com/Loofy147/v0-crypto-dashboard) says it syncs the generated app from v0.app and connects to Vercel deployments. [leverscan-app](https://github.com/Loofy147/leverscan-app) actually presents itself as a generic React/tRPC/Express/Manus OAuth app template, despite its name. | The former may be a UI starting point; the latter may be reusable as a generic application scaffold after stack and authentication review. | A rendered dashboard or auto-synced template is not evidence of a market data feed, trading signal or validated exchange adapter. Keep display-only prototypes disconnected from funds and execution permissions. |
| **Symbolic rule reasoning** | [Child AI System Final Level](https://github.com/Loofy147/Child-AI-System-Final-Level) explicitly describes a small deterministic Horn-rule engine with facts, confidence/provenance metadata, forward chaining, basic proof traces and explicit conflict reporting. Its README says storage is in-memory and lost on restart. | Could be a small experimental reference for explainable rule evaluation and proof objects if Deter-agent needs a formally distinct domain reasoning component. | Do not substitute it for Deter-agent's policy/gateway. Compare rule semantics and threat model; add persistence, resource bounds, malformed-input tests, conflict semantics and adversarial tests before using it beyond a prototype. |
| **Learning-augmented decision support** | [Guardian AI](https://github.com/Loofy147/Guardian-Ai) describes ML predictions combined with learning-augmented algorithms, a FastAPI/PostgreSQL/Redis/Celery backend and a React UI. | Potential research candidate where predictions can improve a heuristic while a rigorously verified fallback retains a performance guarantee. | Independently prove the guarantee and test where predictions are wrong, late or adversarial. A README claim is not a proof; never place the system on a high-stakes decision path without domain-specific review. |
| **Personalized conversational learning** | [Personal AI System](https://github.com/Loofy147/Personal-ai-system) describes a Hugging Face model, Redis-backed conversation history, a FastAPI chat endpoint and a CLI. | May be useful as a learning-assistant prototype or for studying explicit conversation-history persistence and model serving. | Prefer the canonical [Conversational](https://github.com/Loofy147/Conversational) protocol for verified continuity where appropriate. Establish user isolation, retention/deletion, prompt-injection resistance, model/data licensing and actual resource requirements before production use. |
| **Hierarchical agent frameworks and agent templates** | [Rust-agents](https://github.com/Loofy147/Rust-agents) describes hierarchical delegation; [agent-hub](https://github.com/Loofy147/agent-hub) describes a seven-identity project template; [Unified-ai](https://github.com/Loofy147/Unified-ai) describes hierarchical memory and multi-agent orchestration. | Useful for comparing scheduling, task routing, tool adapters, supervisor/worker decomposition and evaluation designs. | These are competing architecture candidates, not a reason to combine agents indiscriminately. The Context-swarm design defines persistent bounded contexts and state transitions as the unit of coordination; keep identity prompts separate from durable project state and authorization. Verify claims in executable tests and current source. |
| **Small-model and mobile AI experiments** | [Q-Optimized Small Model](https://github.com/Loofy147/q-optimized-small-model) describes a custom small-model training structure; [screal](https://github.com/Loofy147/screal) README follows an Android AI Studio app template. | Potential local-inference or mobile UX experiments if inference cost, latency or offline behavior becomes a demonstrated requirement. | Require dataset and checkpoint provenance, reproducible training/evaluation, privacy review, model license, device memory/latency measurements and provider-key protection. Do not introduce a model merely because it exists. |
| **Early marketplace, social and app shells** | [Contacto Platform](https://github.com/Loofy147/Contacto-platform), [socials](https://github.com/Loofy147/socials), [Viral](https://github.com/Loofy147/Viral) and [Algerian Print-on-Demand Platform](https://github.com/Loofy147/Algerian-Print-on-Demand-Platform) had only minimal README descriptions in this inspection. | Retain as candidates for later domain inventory; actual code may show specific useful flows. | Do not infer a product capability from a repository name. Inspect source trees, manifests, license, test suites, active branches and deployed behavior before classifying as reusable. |

## 10. Portfolio-level cleanup and architecture decisions

The search surfaced several names that suggest overlapping projects or alternate iterations. These are **candidate clusters to compare**, not confirmed duplicates:

- **Algerian multi-agent business automation:** algeria-multiagent-platform and algeria-multi-agent-platform.
- **Smart delivery:** smart-delivery-plat, Smart-delivery-platform, and smart-delivery-platform-2; at least one inspected repository reports as empty.
- **Doha marketplace:** Doha-platform and Doha-platform-.
- **Personal and unified AI:** Personal-ai, Personal-ai-system, Unified-ai, agent-hub, Rust-agents and other specialized agent repositories.
- **Crypto/trading:** trading-validations-principles, v0-crypto-dashboard, Trading-app, -AI-Driven-Crypto-Portfolio-Manager-, leverscan-app and agentdit. Their names span data validation, UI scaffolds, app templates and execution ambitions; they are not one coherent system today.

Before consolidating a cluster, compare source trees, commit ancestry, issue/PR history, package names, actual deployment references, licenses and unique assets. Then assign each project one disposition: **canonical implementation**, **research/reference**, **prototype**, **archived**, or **empty/unverified**. Do not delete, transfer, merge or overwrite a repo solely because its name overlaps.

### Highest-value next audits

1. **API registry and local datasets:** audit Agentic APIs and Algerian-datasets for license, provenance, freshness, schema quality and a small executable sample. These could provide broad research value across several unrelated projects.
2. **Market Evidence Governor:** inspect the real validation tests and reports in trading-validations-principles, determine which evidence gates are genuinely enforced, and keep that research system separate from execution.
3. **Business automation:** compare the two Algerian multi-agent platform repos against Loofy-Extensions and existing automation capabilities; extract workflow definitions only where they reduce real duplication.
4. **Candidate overlap resolution:** produce a compact canonical/prototype/reference/empty registry for the name clusters above, backed by tree and history comparisons before any destructive cleanup.

The policy remains: make the smallest useful reuse decision, record source/license/provenance, test the boundary in the receiving project, and avoid new runtime dependencies when a documented interface or copied, independently tested small component is sufficient.


## 11. Capability lifecycle, external authority and mobile execution

A further pass located a more specific family of execution and recovery systems. These are not generic agent frameworks; they address typed capability state, durable runs, external-effect reconciliation, or user-owned mobile execution.

| Repository | Ref observed | What the inspected material establishes | Integration position |
|---|---|---|---|
| [canonical-capability-core](https://github.com/Loofy147/canonical-capability-core) | `master@6396327425e7f5e6c23456579ebc286ca69f771f` | README preserves a v0.16 immutable semantic reference and describes later v0.22 conformance-hardening candidate releases. The stated v0.22 evidence includes 132 passing tests, 500/500 lifecycle cycles, and 2,128/2,128 mutation attempts rejected; its documented lineage caveat remains explicit. | Strongest candidate for a mechanism-level comparison of capability qualification, action/observation/reconciliation and conservative state transitions. Do not silently make it a dependency or promote a candidate release to canonical truth; inspect the actual current release, schemas, tests and lineage first. |
| [external-staging-authority](https://github.com/Loofy147/external-staging-authority) | `main@5e313c05245dfa5b646d3b80713b74d443b8c528` | Its qualification record names a pinned container image, separate authority ledger/volume, and synthetic P0-P5 cases covering pre-dispatch refusal, timeout-before-commit, timeout-after-commit, restart/rehydration, reconciliation, confirmed success, delay and unavailability. Its audit reports one dispatch and zero redispatches for the uncertain effect. | Candidate independent test target for lost-response and reconciliation qualification, **only after confirming the adapter contract matches Deter-agent**. Existing evidence qualifies the named canonical-capability-core image in controlled CI; it does not prove Deter-agent passes or establish an independent physical host or production authority. |
| [m0-durable-run](https://github.com/Loofy147/m0-durable-run) | `main@69b07a54e4b2f8421532b78b8abffca308bbe3da` | README describes a deliberately minimal SQLite execution envelope and separate-process restart demo: reusing the same `run_id` is expected to return the existing Run without invoking the executor again. It explicitly avoids a scheduler and provider registry. | Best small reference for restart/idempotency invariants. Reproduce the behavior against current HEAD and real provider fault cases before importing the primitive; do not add a broad abstraction layer prematurely. |
| [unified-knowledge-work-system](https://github.com/Loofy147/unified-knowledge-work-system) | `main@683c38fdc3c921c1d7977786d5b5ed8617969476` | README documents a relationship-aware module registry, routing, audits, evaluation suites, persistence and explicit evidence-bearing handoffs. It states consequential external actions need confirmation. | Portfolio/control-plane reference for task routing and evidence packages. Keep it outside Deter-agent's per-effect authorization path; planning and routing cannot grant execution authority. |
| [Llms-mcp-android](https://github.com/Loofy147/Llms-mcp-android) | `main@78afd5d3d7716fe31a5f109a5796eb3db7f99970` | README defines an Android `AgentRuntime` and action/policy/approval/egress/run/invocation/observation/verification/evidence lifecycle. Its prior documented test baseline is not revalidated by this review against the present HEAD. | Strong mobile runtime/control-plane design reference. Compare the contract with Deter-agent and the UWS control plane, but do not introduce cross-repository shared state without explicit ownership and failure semantics. |

### The useful experiment is not a merger

The most informative next experiment is a narrow, non-destructive contract comparison:

1. Define one provider-neutral effect command, including an immutable command identity, an idempotency key, an attempt number, and the exact action/environment scope.
2. Define the state machine for `NOT_DISPATCHED`, `UNKNOWN_OUTCOME`, `RECONCILED_SUCCEEDED`, `RECONCILED_ABSENT`, and terminal failure. Do not equate a client timeout with proof that the provider did nothing.
3. Run the same synthetic case matrix against the current Deter-agent adapter and an independently hosted test authority only if its contract is compatible.
4. Compare durable state after restart, external ledger count, dispatch count, command binding, evidence age and mismatch rejection.
5. Preserve failure output and treat each engine's result as evidence about that engine only.

This proposed experiment has **not** been run against Deter-agent. The external staging repository's own qualification record is existing source evidence, not Deter-agent test evidence. The physical-host independence and production authorization claims remain open.

## 12. Additional execution, decision and local-first system types

| Type | Repository and observed capability | Value to investigate | Boundary |
|---|---|---|---|
| **Typed decision substrate / abstaining model composition** | [Open System One](https://github.com/Loofy147/Open-System-One), `main@fb21d176d0ed1b083df889cf747ac562d449ceef`, separates decision contracts, deterministic composition, replaceable model backends and research receipts. Its README labels browser ONNX execution experimentally supported while set-aware advantage remains open. | Could help separate a probabilistic recommendation/score from a typed downstream decision, including explicit abstention. | Never treat model confidence as permission to act. Preserve experiment-specific claims and do not assume an experimental benchmark transfers to another domain. |
| **Browser-local inference / offline PWA** | [All-time-](https://github.com/Loofy147/All-time-), `main@c9f8662acde83808b64ad75ac8bef4ee67edd5da`, documents pinned model revisions, WebGPU with WASM/CPU fallback and a PWA shell. Its README says current main is beyond the last known READY deployment, so current production verification remains open. | Candidate for private/offline user assistance when local inference materially improves privacy or cost. | Measure real device performance, memory, battery, model provenance and browser fallback. Do not claim a deployment is current from an older release's success. |
| **Autonomous contribution governance** | [outonomos-system](https://github.com/Loofy147/outonomos-system), `main@71f4f46156507a6741a4cf55b6f222c8274af643`, describes an intake gate for code patches with security scanning, license checks, risk tiering and human escalation. | Compare with Deter-agent promotion gates and Contribution Network acceptance/verification. Candidate shared contract: patch intake, findings, risk classification and approval requirement. | The README's “production-grade” label is not independent evidence. Inspect actual rules/tests, scanner coverage, bypass paths and false-negative behavior. It must not self-approve its own authority or substitute a label scan for legal license review. |
| **BYOK multi-provider mobile assistant** | [Agora-32Bit](https://github.com/Loofy147/Agora-32Bit), `master@f16485b19a5a74628469eb08d9fcbec4d0b6f822`, describes local conversation storage, multiple model providers, MCP, local models and remote shell tools; the README identifies MIT licensing. | Compare provider configuration, context budgeting, MCP connection and user-controlled credential flows with Llms-mcp-android. | Review permissions and secrets handling in source. Remote shell/MCP tools create a consequential-action boundary; a BYOK design does not by itself establish authorization, sandboxing or secret isolation. |
| **Local penetration-testing assistant** | [METATRON](https://github.com/Loofy147/METATRON), `main@9dd2ee3daa33397453c76e9fcba446f117d22cb6`, describes local-LLM-assisted recon using common network and web assessment tools with stored scan history. | Potential authorized lab assessment and security-test orchestration reference. | Limit use to owned or explicitly authorized targets, with a recorded scope and rate/concurrency limits. Treat LLM-produced findings as unverified until tool evidence is reviewed; no exploit automation should be enabled by default. |
| **Reflective/interpreted programming environment** | [Log-OS](https://github.com/Loofy147/log-os) describes a LISP-like Python interpreter and experiments in reflection/bootstrapping. | Research-only option for studying small interpreters, structured transformations or self-hosting. | Do not infer general self-improvement or safe self-modification from the project goal. Require a reproducible executable example, semantic tests, sandboxing and a versioned evaluator before using generated code to change itself. |
| **Privacy/security side-channel research** | [Device Activity Tracker](https://github.com/Loofy147/device-activity-tracker) describes a proof-of-concept using messaging-delivery timing to infer activity patterns. | Could inform threat modeling, privacy education and defensive evaluation of metadata leakage. | **Do not repurpose it to monitor real people.** Keep any use confined to consented synthetic or owned test devices; focus on documenting leakage and mitigations, not targeting individuals. |
| **Offline communication / mesh** | [bitchat-android](https://github.com/Loofy147/bitchat-android) describes Bluetooth mesh plus Nostr transport and a public-domain release; [LinuxOnAndroid](https://github.com/Loofy147/LinuxOnAndroid) describes a GPL-2.0-or-later Android environment for running Linux distributions without root. | Possible references for offline messaging, local control surfaces, and mobile development constraints if these are actual product requirements. | Both add platform-specific operational complexity. Verify exact upstream revision, compatibility, permissions, device support, and dependency/license effects; neither is a generic backend or agent runtime. |

## 13. Reuse decisions clarified by this pass

1. **Treat capability qualification, effect execution and portfolio routing as separate interfaces.** Canonical Capability Core is a candidate semantics reference; the external authority is a candidate test service; m0 is a candidate durability primitive; UWS is a planning/control plane; Llms-mcp-android is a mobile runtime. They are related by problem space, not proven to be one implementation.
2. **Prefer a single discriminating experiment over a multi-repo merge.** Unknown-outcome reconciliation is a high-value cross-system test because it can falsify claims about durable effects. Reproducing it on Deter-agent and a synthetic target gives more signal than adding several new agent frameworks.
3. **Carry model output through a typed proposal boundary.** Open System One and local-inference projects can be useful upstream of a deterministic gate, but scores, rationale and natural-language instructions remain untrusted data.
4. **Use outonomos-system as an adjacent governance comparison, not a second automatically trusted promotion authority.** Align interfaces only after inspecting the actual implementation and bypass tests.
5. **Preserve project boundaries and licenses.** No runtime dependency or code copying has been introduced as a result of this review.
