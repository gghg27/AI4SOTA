# Task Plan: AI4SOTA Product Definition and Landscape Research

## Goal
Turn the AI4SOTA idea into a precise product thesis and architecture for multi-domain EEG foundation-model research, identify relevant existing products, and establish an implementable first vertical slice.

## Phases
- [x] Phase 1: Read the existing repository and product definition
- [x] Phase 2: Research comparable products and open-source projects
- [x] Phase 3: Synthesize reusable patterns, gaps, and positioning
- [x] Phase 4: Deliver the landscape report and start design clarification
- [x] Phase 5: Define the human-AI collaboration model and schema-card boundaries
- [x] Phase 6: Define local module-library and self-contained project storage
- [x] Phase 7: Define built-in/external editor synchronization and run isolation
- [x] Phase 8: Define Agent runtime, tool/provider integration, permissions, and security
- [x] Phase 9: Finalize schemas, compatibility rules, Run ledger, and Research Commit lifecycle
- [x] Phase 10: Finalize desktop information architecture and first end-to-end user journey
- [x] Phase 11: Write and review the complete architecture specification
- [ ] Phase 12: Execute the approved implementation program and verify the desktop application

## Key Questions
1. Which existing tools overlap with AI4SOTA's three-module workflow?
2. Which tools support human-in-the-loop code and research decisions?
3. Which ideas should AI4SOTA reuse, and where is its defensible product gap?
4. What should be the next vertical slice after the current CLI kernel?
5. How should AI4SOTA detect and handle files changed by VS Code while an Agent task or Run is active?
6. Which Agent providers, paper sources, execution permissions, and isolation guarantees are required in the first release?

## Decisions Made
- Treat this as an architectural product-design task, not a bounded code change.
- Research adjacent categories separately because no single competitor is expected to match the full concept.
- Do not modify the existing Phase 1 kernel during this research stage.
- Position AI4SOTA as a researcher-governed scientific workspace, not a general DAG builder or autonomous optimizer.
- Recommend a contract-first vertical slice before a desktop-first or agent-first build.
- Use multi-domain EEG foundation-model research as the first real product scenario.
- Keep dataset identity separate from preprocessing choices even when both appear inside one data-module card in the UI.
- Confirmed: use one project-level Agent conversation plus independent data, method, and evaluation Agent workspaces.
- Confirmed: use a global module library, editable project copies, and explicit publication of useful project modules back to the global library.
- Published global module versions are immutable; global editing creates a draft derived from an existing version and publishes a new version.
- Confirmed: the first global module library is local-only, with reserved remote-origin metadata but no accounts, cloud sync, or multi-user sharing.
- Confirmed: AI may edit files inside the active module workspace, but execution, module-version creation, and Research Commit creation require user confirmation.
- Confirmed: each project is a self-contained local directory; the desktop app indexes and operates projects but does not own their only copy.
- Confirmed: AI4SOTA and VS Code edit the same project directory; ordinary external changes auto-refresh, overlapping stale Agent patches stop for human conflict review, and Runs execute from immutable launch snapshots.
- Confirmed: large raw datasets are referenced through frozen manifests and fingerprints rather than copied into every Run; detected source changes invalidate integrity/comparability claims.
- Confirmed: version one supports both hosted APIs and local OpenAI-compatible endpoints through one provider-neutral interface; capabilities are detected per configured model rather than assumed.
- Confirmed: each project has a default provider/model, while project/data/method/evaluation conversations may override it independently; the active model is always visible and cross-provider fallback is never automatic.
- Confirmed: use tiered automatic verification. Schema/static/format checks and registered fast tests in trusted modules may run automatically; new, untrusted, long, GPU, networked, dependency-changing, or arbitrary commands require approval.
- Confirmed: version-one literature support includes OpenAlex, Europe PMC, local PDF/DOI/PMID/arXiv-ID/URL import, and an optional Semantic Scholar API-key connector; Zotero and publisher/institution account integrations are deferred.
- Confirmed: closing the main window keeps active Runs alive in the system tray; explicit quit requires choosing background continuation or cancellation, while crash/reboot recovery records interruption but does not promise generic automatic resume in version one.
- Confirmed: use Tauri 2 with a React/TypeScript webview, a packaged Python control service, and independent experiment Worker processes. The desktop frontend may call only narrow typed Tauri commands and never receives an unrestricted Shell primitive.
- Confirmed: Tauri and the Python control service communicate over loopback FastAPI bound to `127.0.0.1`, using an ephemeral port and a per-launch authentication token. Experiment Workers execute immutable Run snapshots in project-specific Python environments and remain separate from both the Tauri process and the long-lived control service.
- Confirmed: version one promises process separation, scoped application tools, sanitized Worker environments, and auditable approvals, but does not claim that arbitrary user Python is strongly sandboxed at the operating-system level.
- Confirmed: the first EEG release trains separate expert-model compositions. Each Run resolves one Data + Method + Evaluation composition for one expert task; contracts remain ready to describe shared backbones and multiple heads, but joint multi-dataset or multi-task training is deferred.
- Confirmed: the Evaluation module owns split and cross-validation protocols, while the Data module exposes stable sample/group identifiers. The compiler materializes a frozen `SplitManifest` for each Run; split policy is not stored as a mutable dataset-source fact.
- Confirmed: define one project-level shared `TaskContract` referenced by Data, Method, and Evaluation. It is a semantic contract, not a fourth plugin; `ExperimentSpec` remains the immutable composition record for an approved Run.
- Confirmed: compatibility compilation returns one of four deterministic verdicts: `compatible`, `adaptable`, `requires_decision`, or `incompatible`. AI may explain findings and draft adapters, but cannot override the compiler or classify semantic changes as mechanical.
- Confirmed: keep three distinct histories. Workspace changes remain editable; every execution becomes an append-only immutable Run record without an automatic Git commit; only user-curated Research Commits create real Git commits linked to selected Runs and conclusions.
- Confirmed: a Research Commit always commits the exact selected Run snapshot. If the live workspace has diverged, AI4SOTA creates the commit through an isolated Git worktree/branch and never resets, switches, or overwrites the user's current workspace.
- Confirmed: Run comparison uses deterministic three-level verdicts: `directly_comparable`, `comparable_with_caveats`, and `not_comparable`. AI may explain field-level reasons but cannot override a verdict or claim an improvement for non-comparable Runs.
- Confirmed: one Research Commit may aggregate multiple Runs only when their code/module, dataset, task, split, and evaluation protocol hashes match. Differences are limited to declared repetition dimensions such as seed, fold, or repeat index, and aggregation rules/statistics are recorded explicitly.
- Confirmed: use a fixed research-workbench desktop layout with a narrow global rail, project navigation, central scientific workspace, persistent right-side scoped Agent panel, and collapsible bottom job/log drawer.
- Confirmed: module workspaces use a single-focus tab layout for Schema, Files, Validation, References, and Versions, with the scoped module Agent remaining visible. A raw YAML toggle and Open in VS Code provide expert escape hatches without turning version one into a full IDE.

## Errors Encountered
- `agent-browser` CLI is not installed in this environment. Use the available desktop browser automation as the read-only research fallback.
- Local desktop toolchain is usable for browser development. The user's CMD reported Node `v25.9.0`/npm `11.14.0`; the Codex process resolves bundled Node `v24.19.0`, while direct system executables report Node `v24.20.0`/npm `11.19.0`. The plan therefore validates supported version ranges and explicitly resolves system npm instead of assuming one PATH order.
- The user chose not to install the large Visual Studio C++ workload on the current computer because of C-drive capacity. Rust/Tauri native compilation, tray integration, PyInstaller sidecar bundling, and Windows packaging will run on a separate Windows release computer with the complete MSVC toolchain.
- The current computer now has `rustc 1.98.1`, `cargo 1.98.1`, the default `stable-x86_64-pc-windows-msvc` toolchain, and Node.js `v24.20.0`. Rust source can be authored here, but native completion evidence still comes from the separate release computer because this computer intentionally omits Visual Studio C++ Build Tools and the Windows linker/SDK workload.
- Neither `B:\AI4SOTA` nor `B:\AI4SOTA\AI4SOTA-MVP-Phase1` is currently a Git repository; design commits and Research Commit functionality need Git initialization during the approved setup phase.
- An external-conflict proposal was briefly written into the authoritative README before approval and was removed immediately; the user later approved the hash-conflict behavior, which is now incorporated in the specification and implementation plans.
- Literature connector probe on 2026-09-05: arXiv's export endpoint reset the connection in this environment, and the anonymous Semantic Scholar Graph API returned HTTP 429. Treat both as optional/fallback connectors rather than sole MVP dependencies.
- Implementation-plan audit found an inconsistent launch-token owner and unversioned API examples. The plans now define Tauri-generated stdin bootstrap, Rust-only token retention, and `/v1` for all public resource calls.
- Two read-only review commands were malformed: PowerShell bound a file path as a regex because `Select-String` lacked named parameters, and ripgrep rejected a lookahead without `--pcre2`. Both checks were rerun with corrected syntax and produced valid results.
- The first final-gate script applied `-notmatch` directly to the array returned by `Get-Content -TotalCount`; PowerShell evaluated per-line results and raised a false status failure. The approved status was present on line 4, and the gate was corrected to join the header before matching.
- Codex and the user's standalone CMD expose different Node/npm resolution. Read-only checks found Codex's bundled Node first and no npm on its PATH, while `C:\Program Files\nodejs\node.exe` and `npm.cmd` work directly. The desktop preflight now handles this deterministically.

## Status
**Currently in Phase 12** - The approved specification and three ordered implementation plans are complete. Execution is waiting for the user's choice between Subagent-Driven execution (recommended) and Inline execution with checkpoints.
