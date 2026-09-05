# AI4SOTA Desktop v1 Implementation Program

This index is the execution entry point for the approved AI4SOTA desktop v1 design. The work is deliberately split into three plans so each subsystem reaches a testable gate before the next one depends on it.

## Source of Truth

- Product and architecture specification: `../specs/2026-09-05-ai4sota-desktop-agent-design.md`
- Existing migration source: `../../../AI4SOTA-MVP-Phase1/`
- Product overview and decisions: `../../../README.md`

## Execution Order

1. [Core and Research Ledger](2026-09-05-ai4sota-core-ledger.md)
   - Produces the root Python package, versioned scientific schemas, atomic storage, deterministic compatibility and comparison, immutable Runs, exact-snapshot Research Commits, and immutable local module library.
   - Exit gate: one headless project produces two immutable Runs, a deterministic comparison, and an exact-snapshot Research Commit.

2. [Local Control Service and Agent](2026-09-05-ai4sota-control-agent.md)
   - Produces the authenticated loopback API, project/file/schema resources, compatibility/decision/settings resources, approvals, providers, scoped Agent conversations, evidence connectors, independent Workers, and resumable events.
   - Exit gate: the complete desktop API flow passes, the service listens only on `127.0.0.1`, and tokens/secrets are absent from persistent output.

3. [Desktop Workbench and EEG Vertical Slice](2026-09-05-ai4sota-desktop-eeg.md)
   - Produces the Tauri supervisor, React research workbench, schema/code/Agent/Run/history/library surfaces, tray lifecycle, EEG acceptance project, accessibility and visual evidence, and Windows package.
   - Exit gate: the packaged application completes the approved EEG workflow without a development server and leaves verifiable Run, comparison, Research Commit, and module-publication records.

Do not execute these plans concurrently. Plan 2 imports interfaces and types created by Plan 1; Plan 3 consumes the stable HTTP/event contract completed by Plan 2. Within a plan, each numbered task is a review boundary and must be committed only after its focused and full-current-suite checks pass.

## Build Hosts

- Current computer: Python core, FastAPI control service, browser-mode React implementation, Vitest, Playwright browser flows, and visual review. A supported Node 24 runtime and npm 11 are available; Codex scripts may resolve system npm explicitly when the app PATH omits it.
- Separate Windows release computer: all Rust/Cargo compilation, Tauri native bridge and tray tests, PyInstaller sidecar packaging, installed-app checks, and Windows installer generation. It must pass `scripts/preflight-release-windows.ps1` with Node.js 24 LTS, stable MSVC Rust, Visual Studio Desktop C++ Build Tools, Windows SDK, and WebView2.
- Both hosts work from the same committed repository state and lockfiles. Release-host fixes return as ordinary reviewed commits; generated executables and installers are artifacts, not source commits.

## Cross-Plan Contracts

| Owner | Contract | Consumers |
|---|---|---|
| Core | Pydantic v2 JSON Schema for `TaskContract`, Data, Method, Evaluation, Runs, Decisions, and Research Commits | Control API and schema-generated desktop forms |
| Core | `compile_compatibility(...) -> CompatibilityReport` and `compare_runs(...) -> ComparabilityReport` | Control routes; desktop renders but never overrides verdicts |
| Core | Hash-checked atomic patch sets and immutable Run snapshots | Control file routes, Agent tools, Run approval, editor conflict UX |
| Control | `/v1` typed resources, stable error codes, approval binding, and resumable project event IDs | Tauri operation enum and React query/event reconciliation |
| Desktop | Per-launch token delivered once over sidecar stdin and retained only by Rust | Control bootstrap/authentication |
| Desktop | Project-scoped native dialog, VS Code opening, tray lifecycle, and Windows packaging | React workbench; no generic shell or filesystem bridge |

If an executor needs to change one of these contracts, update the owning plan and every listed consumer before implementing the change. Product-semantic changes still require user confirmation; implementation-level corrections that preserve the approved specification require tests and a documented commit.

## Program Verification

After each plan's own completion gate, run all checks accumulated so far. The final program gate is the exact command and evidence list in the desktop/EEG plan. A passing frontend mock flow is not a substitute for the packaged sidecar workflow, and a passing scientific CLI flow is not a substitute for desktop accessibility and visual inspection.

Execution starts only after the user chooses one of the two approved workflows:

1. Subagent-Driven execution using `superpowers:subagent-driven-development` (recommended).
2. Inline execution in this session using `superpowers:executing-plans` with review checkpoints.
