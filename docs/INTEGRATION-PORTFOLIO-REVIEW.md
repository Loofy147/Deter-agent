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
