# AI4SOTA Desktop Workbench and EEG Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the Windows-first Tauri desktop workbench and prove one researcher-governed EEG Data -> Method -> Evaluation -> Run -> Compare -> Research Commit workflow through the real control-service contract.

**Architecture:** A Tauri 2 process owns the packaged Python control-service sidecar, its ephemeral loopback address, and its per-launch secret. React talks through typed, allowlisted Tauri operations and consumes normalized desktop events; the Python service remains the only owner of research state, policy, and Worker orchestration. The interface uses an Obsidian-like fixed pane structure with ChatGPT-like light continuous surfaces, not a card dashboard.

**Tech Stack:** Local development on Node.js 22-25 with npm 10+, release verification on Node.js 24 LTS, React 19, TypeScript 5, Vite 7, Tauri 2, Rust stable MSVC, TanStack Query 5, Zustand 5, React Router 7, RJSF/AJV, Monaco Editor, Recharts, Lucide React, Vitest, Testing Library, axe-core, Playwright, PyInstaller

**Spec:** `docs/superpowers/specs/2026-09-05-ai4sota-desktop-agent-design.md`

## Global Constraints

- Complete `2026-09-05-ai4sota-core-ledger.md` and `2026-09-05-ai4sota-control-agent.md` first; consume their public API instead of duplicating Python domain logic in TypeScript or Rust.
- The current computer is the Python/FastAPI/browser-React development host and does not require Visual Studio C++ Build Tools. A separate Windows release host owns every `cargo`, native Tauri, tray, sidecar-package, installer, and installed-app verification command.
- The release host must use Node.js 24 LTS, npm 10+, Rust stable `x86_64-pc-windows-msvc`, Visual Studio Build Tools with Desktop C++, a Windows 10/11 SDK, and WebView2. Any non-LTS local Node within the supported development range is not release evidence.
- Preserve the existing `AI4SOTA-MVP-Phase1/` directory as migration evidence until the packaged EEG acceptance flow passes.
- The Tauri layer exposes only typed allowlisted operations, project-scoped VS Code opening, native dialogs, tray commands, and normalized event streams; it exposes no generic shell command.
- Tauri generates a fresh 32-byte launch token, writes it once to the sidecar stdin pipe, retains it only in process memory, and never sends it to the WebView.
- The sidecar binds only to `127.0.0.1` on an ephemeral port. Tokens and credential values never enter process arguments, projects, logs, screenshots, crash reports, or persistent settings.
- The desktop never determines scientific compatibility, comparability, approval validity, or Research Commit eligibility; it renders control-service verdicts and disables actions that the service blocks.
- Use the approved “Obsidian skeleton + ChatGPT light surfaces” tokens. No gradients, decorative blobs, marketing hero, oversized headings, excessive rounding, nested cards, or purple-dominant surfaces.
- Use one Lucide outline icon family, semantic HTML, visible focus, text/icon status pairs, and accessible table alternatives for every chart.
- At wide widths keep the 48 px rail, 180-320 px project pane, flexible workspace, 300-480 px Agent pane, and 28/180-360 px jobs drawer stable. At narrow widths collapse Agent before project navigation.
- Keep normal body text at 13-14 px for this desktop tool, page headings at 16-20 px, controls and rows at 28-36 px, and long prose at a readable measure. Do not scale fonts with viewport width and keep letter spacing at `0`.
- Every task ends with focused tests, the full current desktop suite, and one Conventional Commit. Do not claim completion without fresh test, build, screenshot, and packaged-flow evidence.

---

### Task 1: Desktop Toolchain Gate and React/Tauri Scaffold

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/package-lock.json`
- Create: `desktop/tsconfig.json`
- Create: `desktop/tsconfig.node.json`
- Create: `desktop/vite.config.ts`
- Create: `desktop/index.html`
- Create: `desktop/src/main.tsx`
- Create: `desktop/src/app/App.tsx`
- Create: `desktop/src/app/routes.tsx`
- Create: `desktop/src/test/setup.ts`
- Create: `desktop/src/test/smoke.test.tsx`
- Create: `desktop/src-tauri/Cargo.toml`
- Create: `desktop/src-tauri/build.rs`
- Create: `desktop/src-tauri/src/main.rs`
- Create: `scripts/preflight-desktop.ps1`
- Create: `scripts/preflight-release-windows.ps1`

**Interfaces:**
- Consumes: Node.js, npm, Git, and Python 3.11 on the local development host; Node.js 24 LTS, Rust/Cargo MSVC, Visual Studio C++ Build Tools, Windows SDK, and WebView2 on the separate release host.
- Produces: local `npm run test`, `npm run typecheck`, and `npm run build` gates plus a separate failing-fast native release preflight.

- [ ] **Step 1: Write the preflight script and failing React smoke test**

```powershell
$nodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -lt 22 -or $nodeMajor -gt 25) { throw "AI4SOTA local web development requires Node.js 22-25; found $(node --version)" }
$npmPath = (Get-Command npm -ErrorAction SilentlyContinue).Source
if (-not $npmPath -and (Test-Path 'C:\Program Files\nodejs\npm.cmd')) { $npmPath = 'C:\Program Files\nodejs\npm.cmd' }
if (-not $npmPath) { throw "npm 10+ is required" }
$npmVersion = & $npmPath --version
$npmMajor = [int]($npmVersion.Split('.')[0])
if ($npmMajor -lt 10) { throw "npm 10+ is required; found $npmVersion" }
py -3.11 --version
git --version
```

```powershell
$nodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -ne 24) { throw "Release host requires Node.js 24 LTS" }
if ((rustup show active-toolchain) -notmatch 'stable-x86_64-pc-windows-msvc') { throw "Stable MSVC Rust toolchain is required" }
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "Visual Studio Build Tools are required on the release host" }
$vsInstall = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsInstall) { throw "Desktop C++ workload is missing" }
if (-not (Test-Path 'C:\Program Files (x86)\Windows Kits\10\Lib')) { throw "Windows SDK is missing" }
rustc --version
cargo --version
npm --prefix desktop exec tauri info
```

```tsx
it("renders the application landmark", () => {
  render(<App />);
  expect(screen.getByRole("main", { name: "Research workspace" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the gate and record the expected current failure**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\preflight-desktop.ps1
```

Expected on the current development host: PASS with a supported Node, npm 10+, Python 3.11, and Git. The 2026-09-05 Codex process resolves bundled Node `v24.19.0`; the system installation at `C:\Program Files\nodejs` provides Node `v24.20.0` and npm `11.19.0`, so the script must accept the explicit npm fallback when PATH is stale. On the separate Windows release host also run `scripts\preflight-release-windows.ps1`; it must pass before Tasks 2, 11, or 12 can be marked complete.

- [ ] **Step 3: Scaffold exact dependencies after the gate passes**

```json
{
  "name": "ai4sota-desktop",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=22 <26", "npm": ">=10" },
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b --pretty false",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "generate:api": "openapi-typescript ../docs/api/openapi.json -o src/api/generated.ts",
    "tauri": "tauri"
  },
  "dependencies": {
    "@monaco-editor/react": "^4.7.0",
    "@rjsf/core": "^5.24.0",
    "@rjsf/validator-ajv8": "^5.24.0",
    "@tanstack/react-query": "^5.80.0",
    "@tauri-apps/api": "^2.5.0",
    "@tauri-apps/plugin-dialog": "^2.2.0",
    "lucide-react": "^0.468.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-markdown": "^10.1.0",
    "react-router": "^7.6.0",
    "recharts": "^2.15.0",
    "rehype-sanitize": "^6.0.0",
    "remark-gfm": "^4.0.0",
    "yaml": "^2.8.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.55.0",
    "@tauri-apps/cli": "^2.5.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.3.0",
    "@testing-library/user-event": "^14.6.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "@vitejs/plugin-react": "^4.5.0",
    "axe-core": "^4.10.0",
    "jsdom": "^26.1.0",
    "openapi-typescript": "^7.8.0",
    "typescript": "^5.8.0",
    "vite": "^7.0.0",
    "vitest": "^3.2.0"
  }
}
```

Generate and commit `package-lock.json`; do not use floating Git dependencies. If a listed range has no release compatible with the selected Node LTS at execution time, change only that package to the newest compatible stable release, record the resolved version in the lockfile, and rerun the complete Task 1 gate.

- [ ] **Step 4: Run scaffold tests and builds**

Run:

```powershell
Set-Location desktop
npm ci
npm run test
npm run typecheck
npm run build
cargo test --manifest-path src-tauri\Cargo.toml
Set-Location ..
```

Run the `cargo test` line only on the release host. Expected locally: smoke test, TypeScript check, and Vite browser build pass. Expected on the release host: the same checks plus the empty Rust harness pass.

- [ ] **Step 5: Commit the desktop baseline**

```powershell
git add desktop scripts/preflight-desktop.ps1 scripts/preflight-release-windows.ps1
git commit -m "chore: scaffold tauri desktop workbench"
```

### Task 2: Secure Sidecar Supervision and Typed Native Bridge

**Files:**
- Create: `desktop/src-tauri/tauri.conf.json`
- Create: `desktop/src-tauri/capabilities/default.json`
- Create: `desktop/src-tauri/src/control/mod.rs`
- Create: `desktop/src-tauri/src/control/protocol.rs`
- Create: `desktop/src-tauri/src/control/supervisor.rs`
- Create: `desktop/src-tauri/src/commands.rs`
- Create: `desktop/src-tauri/src/events.rs`
- Modify: `desktop/src-tauri/src/main.rs`
- Test: `desktop/src-tauri/tests/control_supervisor.rs`

**Interfaces:**
- Consumes: `ai4sota-control` stdin bootstrap protocol and `/v1` OpenAPI contract from the control-service plan.
- Produces: `ControlSupervisor::start`, `call(ControlOperation, Value)`, `subscribe(project_id, cursor)`, `shutdown`, and Tauri commands `control_call`, `select_project_directory`, `open_in_vscode`, and `set_close_policy`.

- [ ] **Step 1: Write failing handshake, allowlist, redaction, and path tests**

```rust
#[tokio::test]
async fn token_is_sent_on_stdin_and_never_returned_to_webview() {
    let child = FakeControl::ready_on(43127);
    let session = ControlSupervisor::start_with(child).await.unwrap();
    assert_eq!(session.public_status().port, 43127);
    assert!(!serde_json::to_string(&session.public_status()).unwrap().contains(&session.test_token()));
}

#[test]
fn operation_enum_rejects_arbitrary_urls() {
    assert!(serde_json::from_str::<ControlOperation>(r#"{"kind":"raw","url":"http://evil"}"#).is_err());
}

#[test]
fn vscode_target_must_be_inside_open_project() {
    assert!(validate_editor_target(project_root(), project_root().join("..\\secret.txt")).is_err());
}
```

- [ ] **Step 2: Run and verify the bridge is absent**

Run: `cargo test --manifest-path desktop\src-tauri\Cargo.toml control_supervisor`

Expected: compilation fails because `ControlSupervisor` and `ControlOperation` do not exist.

- [ ] **Step 3: Implement the supervisor and closed operation enum**

```rust
#[derive(Debug, Deserialize)]
#[serde(tag = "resource", rename_all = "camelCase", rename_all_fields = "camelCase")]
pub enum ControlOperation {
    Projects { action: ProjectAction },
    Modules { project_id: Option<String>, kind: Option<ModuleKind>, action: ModuleAction },
    Files { project_id: String, action: FileAction },
    Compatibility { project_id: String, action: CompatibilityAction },
    Conversations { project_id: String, scope: Scope, action: ConversationAction },
    Decisions { project_id: String, action: DecisionAction },
    Literature { project_id: String, action: LiteratureAction },
    Approvals { project_id: String, action: ApprovalAction },
    Providers { action: ProviderAction },
    Jobs { project_id: String, action: JobAction },
    Runs { project_id: String, action: RunAction },
    ResearchCommits { project_id: String, action: HistoryAction },
    Settings { action: SettingsAction },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ModuleKind { Data, Method, Evaluation }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope { Project, Data, Method, Evaluation }

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ProjectAction { List, Create, Open, Read }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ModuleAction { Read, SaveSchema, PreviewMigration, ApplyMigration, Import, LibraryList, LibraryResolve, CreateDraft, Publish }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum FileAction { List, Read, Search, Diff, Patch }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum CompatibilityAction { Compile }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ConversationAction { List, StartTurn, CancelTurn }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum DecisionAction { List, Draft, Confirm, Supersede }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum LiteratureAction { Search, Import, ExtractPassage, AttachEvidence }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ApprovalAction { Approve, Reject }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ProviderAction { List, SaveProfile, Probe, StoreCredential }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum JobAction { List, SubmitValidation, Cancel, ReadLogs }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RunAction { List, Prepare, Start, Cancel, Detail, Compare, CleanupArtifacts }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HistoryAction { List, Draft, Validate, Create }
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SettingsAction { Read, Update }
```

Generate 32 random bytes with the OS RNG, encode them URL-safely, spawn the sidecar with piped stdin/stdout/stderr, send one bounded bootstrap JSON line containing the token, approved origins, and Tauri `app_data_dir`, close stdin, parse only the first `ready` record, and retain base URL plus bearer token in Rust memory. `control_call` maps enum variants to fixed methods and relative paths and validates which optional IDs are required for each action. Redact authorization headers and bootstrap data from all errors. Stream SSE in Rust and emit normalized `ai4sota://control-event` payloads with stable event IDs. The Tauri capability file grants only dialog access and the listed commands; it denies generic shell and unrestricted filesystem APIs.

- [ ] **Step 4: Verify lifecycle, event replay, and containment**

Run:

```powershell
cargo test --manifest-path desktop\src-tauri\Cargo.toml
cargo check --manifest-path desktop\src-tauri\Cargo.toml
```

Expected: timeout, malformed-ready, crash, graceful shutdown, forced shutdown, SSE replay, redaction, and project-root containment tests pass; Rust check resolves all native bridge types. Packaged sidecar resolution is deferred to Task 12 after the binary exists.

- [ ] **Step 5: Commit native supervision**

```powershell
git add desktop/src-tauri
git commit -m "feat: supervise control service from tauri"
```

### Task 3: Frontend Contract, Query Cache, and Event Reconciliation

**Files:**
- Create: `desktop/src/api/contracts.ts`
- Create: `desktop/src/api/generated.ts`
- Create: `desktop/src/api/operations.ts`
- Create: `desktop/src/api/controlClient.ts`
- Create: `desktop/src/api/eventStream.ts`
- Create: `desktop/src/api/queryKeys.ts`
- Create: `desktop/src/app/providers.tsx`
- Create: `desktop/src/store/workspaceStore.ts`
- Create: `desktop/src/test/fakeBridge.ts`
- Test: `desktop/src/api/controlClient.test.ts`
- Modify: `desktop/src/app/App.tsx`

**Interfaces:**
- Consumes: Tauri `control_call`, `ai4sota://control-event`, and the exact OpenAPI shapes in `docs/api/openapi.json`.
- Produces: `controlClient.call<T>(operation)`, `subscribeToProject(projectId, afterEventId)`, stable query keys, and UI-only workspace state.

- [ ] **Step 1: Write failing operation and invalidation tests**

```tsx
it("never accepts a raw path operation", async () => {
  expectTypeOf<Parameters<typeof controlClient.call>[0]>().not.toMatchTypeOf<{ url: string }>();
});

it("invalidates module and compatibility state after an external save", async () => {
  const client = createTestQueryClient();
  reconcileControlEvent(client, fileChanged("p1", "modules/data/current/adapter.py"));
  expect(client.getQueryState(queryKeys.module("p1", "data"))?.isInvalidated).toBe(true);
  expect(client.getQueryState(queryKeys.compatibility("p1"))?.isInvalidated).toBe(true);
});
```

- [ ] **Step 2: Run and verify missing frontend contract**

Run: `npm --prefix desktop run test -- src/api/controlClient.test.ts`

Expected: imports fail because the client and event reconciler are absent.

- [ ] **Step 3: Implement discriminated operations and event ownership**

```ts
export type ConversationScope = "project" | "data" | "method" | "evaluation";
export type ModuleKind = Exclude<ConversationScope, "project">;

export type ControlOperation =
  | { resource: "projects"; action: "list" | "create" | "open" | "read"; payload?: unknown }
  | { resource: "modules"; projectId?: string; kind?: ModuleKind; action: "read" | "saveSchema" | "previewMigration" | "applyMigration" | "import" | "libraryList" | "libraryResolve" | "createDraft" | "publish"; payload?: unknown }
  | { resource: "compatibility"; projectId: string; action: "compile" }
  | { resource: "files"; projectId: string; action: "list" | "read" | "search" | "diff" | "patch"; payload?: unknown }
  | { resource: "conversations"; projectId: string; scope: ConversationScope; action: "list" | "startTurn" | "cancelTurn"; payload?: unknown }
  | { resource: "decisions"; projectId: string; action: "list" | "draft" | "confirm" | "supersede"; payload?: unknown }
  | { resource: "literature"; projectId: string; action: "search" | "import" | "extractPassage" | "attachEvidence"; payload?: unknown }
  | { resource: "approvals"; projectId: string; action: "approve" | "reject"; payload: unknown }
  | { resource: "providers"; action: "list" | "saveProfile" | "probe" | "storeCredential"; payload?: unknown }
  | { resource: "jobs"; projectId: string; action: "list" | "submitValidation" | "cancel" | "readLogs"; payload?: unknown }
  | { resource: "runs"; projectId: string; action: "list" | "prepare" | "start" | "cancel" | "detail" | "compare" | "cleanupArtifacts"; payload?: unknown }
  | { resource: "researchCommits"; projectId: string; action: "list" | "draft" | "validate" | "create"; payload?: unknown }
  | { resource: "settings"; action: "read" | "update"; payload?: unknown };
```

Generate `generated.ts` from the checked OpenAPI file, wrap only ergonomic aliases in `contracts.ts`, and fail CI when regeneration changes the checked file. Keep the TypeScript operation discriminants in a parity test against serialized Rust fixtures. Keep server data in TanStack Query and only navigation, pane visibility/widths, selected tab, editor buffers, and per-conversation provider override in Zustand. Events invalidate precise query keys; they never synthesize scientific state. Reconnect with the last stable event ID and surface a non-blocking “reconciled from disk” status after replay.

- [ ] **Step 4: Run contract and state tests**

Run:

```powershell
npm --prefix desktop run test -- src/api src/store
npm --prefix desktop run generate:api
git diff --exit-code -- desktop/src/api/generated.ts
npm --prefix desktop run typecheck
npm --prefix desktop run test
```

Expected: operation exhaustiveness, error-code mapping, cancellation, reconnect, replay, and query invalidation tests pass.

- [ ] **Step 5: Commit the frontend contract**

```powershell
git add desktop/src/api desktop/src/store desktop/src/app desktop/src/test
git commit -m "feat: add typed desktop control client"
```

### Task 4: Fixed Research Workbench and Approved Visual System

**Files:**
- Create: `desktop/src/styles/tokens.css`
- Create: `desktop/src/styles/global.css`
- Create: `desktop/src/styles/workbench.css`
- Create: `desktop/src/components/primitives/IconButton.tsx`
- Create: `desktop/src/components/primitives/Status.tsx`
- Create: `desktop/src/components/primitives/ResizablePane.tsx`
- Create: `desktop/src/components/layout/ActivityRail.tsx`
- Create: `desktop/src/components/layout/ProjectNavigation.tsx`
- Create: `desktop/src/components/layout/AgentPane.tsx`
- Create: `desktop/src/components/layout/JobsDrawer.tsx`
- Create: `desktop/src/components/layout/WorkbenchShell.tsx`
- Test: `desktop/src/components/layout/WorkbenchShell.test.tsx`

**Interfaces:**
- Consumes: workspace layout store and React Router location.
- Produces: five stable regions, accessible pane resizing, wide/narrow collapse behavior, and the permanent visual baseline used by all views.

- [ ] **Step 1: Write failing landmark, keyboard, and responsive tests**

```tsx
it("keeps all five workbench regions in document order", () => {
  renderWorkbench();
  expect(screen.getByLabelText("Global navigation")).toBeVisible();
  expect(screen.getByLabelText("Project navigation")).toBeVisible();
  expect(screen.getByRole("main", { name: "Research workspace" })).toBeVisible();
  expect(screen.getByLabelText("Research agent")).toBeVisible();
  expect(screen.getByLabelText("Jobs and logs")).toBeVisible();
});

it("resizes the project pane with arrow keys", async () => {
  const separator = screen.getByRole("separator", { name: "Resize project navigation" });
  separator.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(separator).toHaveAttribute("aria-valuenow", "238");
});
```

- [ ] **Step 2: Run and verify the fixed shell is absent**

Run: `npm --prefix desktop run test -- src/components/layout/WorkbenchShell.test.tsx`

Expected: landmark and separator queries fail.

- [ ] **Step 3: Implement tokens and stable pane geometry**

```css
:root {
  --surface-shell: #edf2f7;
  --surface-rail: #f6f8fa;
  --surface-sidebar: #eef2f6;
  --surface-canvas: #ffffff;
  --surface-agent: #fbfbfc;
  --border-default: #e1e4e8;
  --text-primary: #25272b;
  --text-muted: #6f757d;
  --focus-accent: #6f5cc3;
  --action-primary: #2f3033;
  --module-data: #8c6a54;
  --module-method: #39766c;
  --module-evaluation: #756d88;
  --radius-control: 5px;
  --radius-agent: 9px;
  --rail-width: 48px;
  --jobs-collapsed: 28px;
  letter-spacing: 0;
}
```

Use CSS Grid tracks `48px var(--project-pane) minmax(360px, 1fr) var(--agent-pane)` with the jobs drawer as the second row. Clamp saved widths to the approved ranges. Below 1100 px collapse Agent behind a toggle; below 820 px also collapse project navigation into an overlay while preserving the central object. Resizers use `role="separator"`, pointer capture, Arrow keys in 8 px steps, Home/End limits, and visible focus. All rail icons have tooltips and accessible names; the selected destination includes a text label in the expanded navigation and `aria-current="page"`.

- [ ] **Step 4: Run layout, axe, contrast, and visual token tests**

Run:

```powershell
npm --prefix desktop run test -- src/components/layout src/styles
npm --prefix desktop run typecheck
npm --prefix desktop run test
```

Expected: landmarks, focus order, keyboard resize, breakpoint collapse, color-not-only status, contrast, and forbidden-gradient/radius scans pass.

- [ ] **Step 5: Commit the approved shell**

```powershell
git add desktop/src/styles desktop/src/components/layout desktop/src/components/primitives
git commit -m "feat: build fixed research workbench shell"
```

### Task 5: Home, Project Overview, and Schema-Driven Module Workspace

**Files:**
- Create: `desktop/src/features/home/HomeView.tsx`
- Create: `desktop/src/features/project/ProjectOverview.tsx`
- Create: `desktop/src/features/project/CompositionStrip.tsx`
- Create: `desktop/src/features/project/DecisionQueue.tsx`
- Create: `desktop/src/features/modules/ModuleWorkspace.tsx`
- Create: `desktop/src/features/modules/ModuleHeader.tsx`
- Create: `desktop/src/features/modules/SchemaEditor.tsx`
- Create: `desktop/src/features/modules/RawYamlEditor.tsx`
- Create: `desktop/src/features/modules/schemaUi.ts`
- Test: `desktop/src/features/project/ProjectOverview.test.tsx`
- Test: `desktop/src/features/modules/SchemaEditor.test.tsx`

**Interfaces:**
- Consumes: project/module JSON Schema, current document hash, `CompatibilityReport`, DecisionRecord resources, native directory picker, and module import/publish requests.
- Produces: recent-project actions, fixed Data -> Method -> Evaluation overview, project blocker list, single-focus module tabs, generated forms, and Raw YAML saves with optimistic concurrency.

- [ ] **Step 1: Write failing compatibility and hash-conflict interaction tests**

```tsx
it("disables Run and links each blocking finding to its field", () => {
  renderOverview({ compatibility: incompatibleMissingSubjectId() });
  expect(screen.getByRole("button", { name: "Prepare run" })).toBeDisabled();
  expect(screen.getByRole("link", { name: /subject_id/ })).toHaveAttribute("href", expect.stringContaining("evaluation"));
});

it("preserves local YAML after a hash conflict", async () => {
  renderSchemaEditor({ saveResult: hashConflict("module.yaml") });
  await editRawYaml("version: 1.1.0");
  await userEvent.click(screen.getByRole("button", { name: "Save schema" }));
  expect(screen.getByText("The file changed on disk")).toBeVisible();
  expect(screen.getByDisplayValue(/version: 1.1.0/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Review differences" })).toBeEnabled();
});
```

- [ ] **Step 2: Run and verify views are absent**

Run: `npm --prefix desktop run test -- src/features/project src/features/modules`

Expected: overview and schema editor imports fail.

- [ ] **Step 3: Implement research-first project and module views**

Render the composition as a semantic ordered list with three unframed module blocks and one generated-adapter row; use thin connectors plus icon/text verdicts, not a freeform DAG canvas. Keep the home page operational: recent projects, active Runs, module updates, New Project, and Open Project, with no hero section.

```tsx
<Form
  schema={jsonSchema}
  formData={draft}
  validator={validator}
  uiSchema={buildUiSchema(jsonSchema)}
  onChange={({ formData }) => setDraft(formData)}
  onSubmit={() => save({ document: draft, expectedHash })}
  showErrorList="top"
  focusOnFirstError
/>
```

Use visible labels, field paths, source/decision markers, inline errors, and a linked error summary. Validate on blur or explicit save, not every keypress. Toggle between Form and Raw YAML with a segmented control. Raw YAML parses locally, but the service remains authoritative. When a registered schema migration is needed, show its source/target versions, complete diff, target document, backup path policy, and stale-hash behavior before enabling Apply migration. Expose exactly one active module tab among Schema, Files, Validation, References, and Versions; preserve its scroll and draft state when switching the Agent scope.

- [ ] **Step 4: Verify form, overview, and navigation behavior**

Run:

```powershell
npm --prefix desktop run test -- src/features/home src/features/project src/features/modules
npm --prefix desktop run test
npm --prefix desktop run typecheck
```

Expected: create/open, form/YAML parity, schema error focus, conflict recovery, fixed composition, adapter review, and blocker navigation tests pass.

- [ ] **Step 5: Commit project and schema workspaces**

```powershell
git add desktop/src/features/home desktop/src/features/project desktop/src/features/modules desktop/src/app
git commit -m "feat: add project and schema workspaces"
```

### Task 6: Lightweight File Editing, Diff, Validation, and VS Code Handoff

**Files:**
- Create: `desktop/src/features/files/FileWorkspace.tsx`
- Create: `desktop/src/features/files/FileTree.tsx`
- Create: `desktop/src/features/files/CodeEditor.tsx`
- Create: `desktop/src/features/files/DiffView.tsx`
- Create: `desktop/src/features/files/conflicts.ts`
- Create: `desktop/src/features/validation/ValidationView.tsx`
- Create: `desktop/src/features/validation/SamplePreview.tsx`
- Test: `desktop/src/features/files/FileWorkspace.test.tsx`
- Test: `desktop/src/features/validation/ValidationView.test.tsx`

**Interfaces:**
- Consumes: scoped file list/read/search/diff/patch operations, external-change events, registered validation jobs, and `open_in_vscode`.
- Produces: searchable module file tree, Python/YAML/Markdown Monaco editing, hash-aware save/diff/conflict recovery, validation detail, and VS Code handoff.

- [ ] **Step 1: Write failing stale-save and external-refresh tests**

```tsx
it("never overwrites an external VS Code save", async () => {
  const view = renderFileWorkspace({ file: pythonFile("old", "a".repeat(64)) });
  await view.edit("local edit");
  view.emit(fileChanged("modules/method/current/model.py", "b".repeat(64)));
  await view.save();
  expect(view.patchCalls()).toHaveLength(0);
  expect(screen.getByRole("dialog", { name: "File changed outside AI4SOTA" })).toBeVisible();
});

it("marks validation stale after a relevant file event", () => {
  renderValidationView({ state: "passed" });
  emitFileChanged("modules/data/current/adapter.py");
  expect(screen.getByText("Validation is out of date")).toBeVisible();
});
```

- [ ] **Step 2: Run and verify editor modules are missing**

Run: `npm --prefix desktop run test -- src/features/files src/features/validation`

Expected: imports fail for file and validation workspaces.

- [ ] **Step 3: Implement bounded editing and recoverable conflicts**

Load Monaco only when the Files or Raw YAML tab first opens. Support Python, YAML, Markdown, JSON, find, undo/redo, save, and read-only diff; omit terminals, extensions, debugging, notebooks, and LSP. Keep editor buffers keyed by `projectId:path:baseHash`. Before save, compare the latest event hash with the base hash, then send the base hash in the patch request. On `HASH_CONFLICT`, show base/local/current three-way context and offer Reload from disk, Keep local draft, or Ask Agent to regenerate; no force-overwrite action exists.

Validation rows show command profile, state, duration, timestamp, log access, cancellation, and a recovery action. Sample preview explicitly shows EEG shape, dtype, label distribution, subject/session/trial coverage, channels, sampling rate, missingness, and preprocessing provenance. “Open in VS Code” targets the selected project or file through the Rust containment check.

- [ ] **Step 4: Run editor, conflict, and validation tests**

Run:

```powershell
npm --prefix desktop run test -- src/features/files src/features/validation
npm --prefix desktop run test
npm --prefix desktop run build
```

Expected: scoped editing, keyboard save, large-file read-only fallback, external refresh, stale conflict, diff, VS Code target, validation cancel, and sample preview tests pass.

- [ ] **Step 5: Commit lightweight editing**

```powershell
git add desktop/src/features/files desktop/src/features/validation
git commit -m "feat: add hash aware module editing"
```

### Task 7: Scoped Agent Streaming, Evidence, and Approval Interaction

**Files:**
- Create: `desktop/src/features/agent/AgentConversation.tsx`
- Create: `desktop/src/features/agent/AgentComposer.tsx`
- Create: `desktop/src/features/agent/Message.tsx`
- Create: `desktop/src/features/agent/ToolActivity.tsx`
- Create: `desktop/src/features/agent/ApprovalPrompt.tsx`
- Create: `desktop/src/features/agent/ProviderSelector.tsx`
- Create: `desktop/src/features/references/ReferencesView.tsx`
- Create: `desktop/src/features/references/EvidencePassage.tsx`
- Test: `desktop/src/features/agent/AgentConversation.test.tsx`
- Test: `desktop/src/features/references/ReferencesView.test.tsx`

**Interfaces:**
- Consumes: project/data/method/evaluation conversation APIs, stream events, cancellation, provider profiles/capabilities, approval requests, literature search/import, and evidence records.
- Produces: one persistent scoped Agent pane, visible effective provider, typed tool activity, hash-bound approvals, citations, and recovery states.

- [ ] **Step 1: Write failing scope, approval, and provider-failure tests**

```tsx
it("shows the active scope and cannot silently approve a cross-scope patch", async () => {
  renderAgent({ scope: "data", events: [approvalRequired({ targetScope: "method" })] });
  expect(screen.getByText("Data agent")).toBeVisible();
  expect(screen.getByText("Writes Method files")).toBeVisible();
  expect(screen.getByRole("button", { name: "Approve once" })).toBeVisible();
});

it("keeps partial text and offers choices when a provider stops", () => {
  renderAgent({ events: [delta("Partial answer"), providerUnavailable("local") ] });
  expect(screen.getByText("Partial answer")).toBeVisible();
  expect(screen.getByRole("button", { name: "Retry local" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Choose another profile" })).toBeEnabled();
});
```

- [ ] **Step 2: Run and verify Agent UI is absent**

Run: `npm --prefix desktop run test -- src/features/agent src/features/references`

Expected: Agent and reference component imports fail.

- [ ] **Step 3: Implement explicit streamed turns and evidence display**

Pin the Agent pane while central tabs change. Show scope, model/profile, outbound-data classification, and remaining running state above the composer. Render streamed Markdown with raw HTML disabled and sanitized links. Group tool calls by turn and display typed arguments, affected paths, expected hashes, result, duration, logs, and approval status. Approval prompts state the research or system consequence in plain language, bind to the server request ID/hash, expire visibly, and disable after use or target changes.

Do not silently change providers. A provider error preserves partial output and presents Retry same profile, Choose another profile, or Continue discussion-only where capabilities permit. Literature passages show title, identifiers, locator, retrieval time, access status, and links to attached decisions/code; untrusted content is visually labeled as evidence, never as an instruction.

- [ ] **Step 4: Verify streaming, accessibility, and policy rendering**

Run:

```powershell
npm --prefix desktop run test -- src/features/agent src/features/references
npm --prefix desktop run test
npm --prefix desktop run typecheck
```

Expected: streaming order, cancellation, four scopes, provider override, no fallback, single-use approval, stale approval, citation, prompt-injection label, focus return, and live-region tests pass.

- [ ] **Step 5: Commit the Agent and evidence UI**

```powershell
git add desktop/src/features/agent desktop/src/features/references desktop/src/components/layout/AgentPane.tsx
git commit -m "feat: add scoped agent conversations"
```

### Task 8: Run Approval, Jobs Drawer, Experiments, and Comparison

**Files:**
- Create: `desktop/src/features/runs/RunApprovalDialog.tsx`
- Create: `desktop/src/features/runs/ExperimentsView.tsx`
- Create: `desktop/src/features/runs/RunTable.tsx`
- Create: `desktop/src/features/runs/RunDetail.tsx`
- Create: `desktop/src/features/runs/MetricChart.tsx`
- Create: `desktop/src/features/runs/ComparisonView.tsx`
- Create: `desktop/src/features/jobs/JobList.tsx`
- Create: `desktop/src/features/jobs/LogStream.tsx`
- Test: `desktop/src/features/runs/ExperimentsView.test.tsx`
- Test: `desktop/src/features/runs/ComparisonView.test.tsx`
- Test: `desktop/src/features/jobs/JobList.test.tsx`

**Interfaces:**
- Consumes: prepare/approve/start/cancel/detail/compare APIs, immutable `ExperimentSpec`, Run/Job events, metrics, artifacts, logs, snapshots, and comparability reports.
- Produces: inspectable Run approval, persistent job status, sortable/filterable Run table, Run detail tabs, accessible charts, and verdict-gated comparison language.

- [ ] **Step 1: Write failing approval-hash and non-comparable tests**

```tsx
it("invalidates approval when a bound hash changes", () => {
  const view = renderRunApproval(preparedRun());
  view.emit(moduleChanged("method", "new-hash"));
  expect(screen.getByRole("button", { name: "Approve and queue" })).toBeDisabled();
  expect(screen.getByText("Workspace changed; prepare a new snapshot")).toBeVisible();
});

it("requires the process-isolation acknowledgement before first user-code execution", () => {
  renderRunApproval(preparedRun(), { hasAcknowledgedExecutionBoundary: false });
  expect(screen.getByText("Python code is process-isolated, not OS-sandboxed")).toBeVisible();
  expect(screen.getByRole("button", { name: "Approve and queue" })).toBeDisabled();
});

it("does not compute or describe improvement for non-comparable runs", () => {
  renderComparison(notComparableDifferentSubjects());
  expect(screen.getByText("Not comparable")).toBeVisible();
  expect(screen.queryByText(/improv|提升|delta/i)).not.toBeInTheDocument();
  expect(screen.getAllByRole("cell", { name: /0\./ })).not.toHaveLength(0);
});
```

- [ ] **Step 2: Run and verify experiment views are absent**

Run: `npm --prefix desktop run test -- src/features/runs src/features/jobs`

Expected: imports fail for Run approval and experiment components.

- [ ] **Step 3: Implement dense research records and verdict gates**

The approval dialog shows module/TaskContract/adapter hashes, data fingerprint, exact split summary, seed, environment, device, resources, network policy, and registered commands before enabling one explicit approval. Before the first execution of project or imported Python, require a persistent local acknowledgement that process separation limits crashes and supports audit/cancellation but is not an OS security sandbox. The bottom drawer has a 28 px collapsed status bar and 180-360 px expanded log region, announces terminal states without stealing focus, and keeps cancellation visible.

Use a semantic virtualized table when Run count exceeds 50. Columns include status, task, Data, Method, Evaluation, primary metric, seed/fold, started time, duration, integrity, and Research Commit link. Run detail tabs are Summary, Configuration, Metrics, Artifacts, Logs, Snapshot/Diff, and Provenance. Artifact cleanup requires explicit row selection, displays retained scientific records, requests a destructive-operation approval, and replaces removed payloads with visible tombstone metadata. Use line charts for learning curves and grouped bars/dot plots with confidence intervals for discrete comparisons; add direct labels, units, keyboard-readable tooltips, series toggles, a concise text summary, and the full sortable data table.

Only render numerical deltas and “better/improved” language for `directly_comparable` or explicitly accepted `comparable_with_caveats`. For `not_comparable`, show raw values side-by-side and the field-level reasons with `metric_deltas === null`.

- [ ] **Step 4: Run Run, job, table, and chart tests**

Run:

```powershell
npm --prefix desktop run test -- src/features/runs src/features/jobs
npm --prefix desktop run test
npm --prefix desktop run build
```

Expected: approval expiry, queue transitions, cancel, failed/interrupted logs, sorting/filtering, chart table fallback, confidence interval, and all three comparability verdict tests pass.

- [ ] **Step 5: Commit experiment operations**

```powershell
git add desktop/src/features/runs desktop/src/features/jobs desktop/src/components/layout/JobsDrawer.tsx
git commit -m "feat: add experiment runs and comparison"
```

### Task 9: Research History and Obsidian-Style Knowledge View

**Files:**
- Create: `desktop/src/features/history/ResearchHistoryView.tsx`
- Create: `desktop/src/features/history/ResearchCommitDraft.tsx`
- Create: `desktop/src/features/history/ResearchTimeline.tsx`
- Create: `desktop/src/features/knowledge/KnowledgeView.tsx`
- Create: `desktop/src/features/knowledge/MarkdownDocument.tsx`
- Create: `desktop/src/features/knowledge/Backlinks.tsx`
- Test: `desktop/src/features/history/ResearchHistoryView.test.tsx`
- Test: `desktop/src/features/knowledge/KnowledgeView.test.tsx`

**Interfaces:**
- Consumes: Research Commit draft/validate/create endpoints, exact Run snapshot metadata, Git ref/SHA, references, decisions, and backlink index.
- Produces: curated commit-only timeline, explicit conclusion workflow, linked Markdown reading, and backlinks among evidence, decisions, code, Runs, and commits.

- [ ] **Step 1: Write failing exact-snapshot and backlink tests**

```tsx
it("states that a diverged workspace will not be replaced", () => {
  renderResearchCommitDraft({ selectedRun: oldSnapshotRun(), workspaceChanged: true });
  expect(screen.getByText("Commit the selected Run snapshot")).toBeVisible();
  expect(screen.getByText("Your current workspace will remain unchanged")).toBeVisible();
});

it("backlinks navigate to typed local research objects", async () => {
  renderKnowledge(decisionWithRunBacklink());
  await userEvent.click(screen.getByRole("link", { name: "Run run-002" }));
  expect(mockNavigate).toHaveBeenCalledWith("/projects/p1/experiments/run-002");
});
```

- [ ] **Step 2: Run and verify history and knowledge views are absent**

Run: `npm --prefix desktop run test -- src/features/history src/features/knowledge`

Expected: imports fail for the new views.

- [ ] **Step 3: Implement curated history and linked reading**

Keep debugging Runs in Experiments and show only Research Commits in the main history. The compact branch/timeline row includes commit ID, Git SHA, accepted Runs, task, primary result, conclusion status, author, date, and parent. The draft requires hypothesis, evidence, selected Runs, result, conclusion, limitations, and next step; it shows aggregation eligibility and a final hash-bound approval.

Render project Markdown as an unframed reading surface with sanitized content, stable heading anchors, typed `ai4sota:` links, and a restrained right/lower backlinks list. Each backlink states relationship type, source title, locator, and last-known content hash. Preserve file opening into the lightweight editor or VS Code.

- [ ] **Step 4: Run exact-snapshot, navigation, and Markdown security tests**

Run:

```powershell
npm --prefix desktop run test -- src/features/history src/features/knowledge
npm --prefix desktop run test
npm --prefix desktop run typecheck
```

Expected: aggregation gates, old-snapshot wording, stale approvals, commit-only timeline, sanitized Markdown, heading navigation, backlinks, and empty states pass.

- [ ] **Step 5: Commit research history and knowledge**

```powershell
git add desktop/src/features/history desktop/src/features/knowledge
git commit -m "feat: add research history and knowledge views"
```

### Task 10: Global Module Library and Settings

**Files:**
- Create: `desktop/src/features/library/LibraryView.tsx`
- Create: `desktop/src/features/library/ModuleVersionDetail.tsx`
- Create: `desktop/src/features/library/PublishModuleDialog.tsx`
- Create: `desktop/src/features/settings/SettingsView.tsx`
- Create: `desktop/src/features/settings/ProviderProfiles.tsx`
- Create: `desktop/src/features/settings/PathSettings.tsx`
- Create: `desktop/src/features/settings/PolicySettings.tsx`
- Test: `desktop/src/features/library/LibraryView.test.tsx`
- Test: `desktop/src/features/settings/SettingsView.test.tsx`

**Interfaces:**
- Consumes: local module library import/draft/publish APIs, publish-gate reports, app settings, provider capability probes, keyring credential actions, and native directory picker.
- Produces: searchable immutable version library, editable derived drafts, explicit publication, local path migration, hosted/local profiles, and visible policy defaults.

- [ ] **Step 1: Write failing immutable-version and credential tests**

```tsx
it("offers a derived draft instead of editing a published version", () => {
  renderModuleVersionDetail(publishedModule("data/seed@1.0.0"));
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create editable draft" })).toBeEnabled();
});

it("never renders a stored credential value", () => {
  renderProviderProfiles(profileWithCredentialRef("openai-main"));
  expect(screen.getByText("Credential stored in Windows Credential Manager")).toBeVisible();
  expect(screen.queryByDisplayValue(/sk-/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify library/settings views are absent**

Run: `npm --prefix desktop run test -- src/features/library src/features/settings`

Expected: imports fail for the new views.

- [ ] **Step 3: Implement local-only library and settings workflows**

Library rows show type, ID, immutable version, source, license, verification, updated time, and project usage. Import explicitly states that it creates a project-local editable copy. Published versions are read-only; “Edit” creates a derived draft. Publication shows Schema/file diff, compatibility, tests/example artifacts, dependencies/license, literature/code provenance, secret/path scan, and semantic-version change before requesting approval bound to the draft hash. `remote_source` is displayed as metadata only and has no sync action.

Settings sections cover library location, Python environments, provider profiles, literature connectors, default validation policy, appearance density, and diagnostics. Hosted and local OpenAI-compatible profiles show capability probe results; project default and per-conversation override remain separate. Credential creation invokes a dedicated native/control operation that writes directly to keyring, returning only an opaque reference. Moving the library requires a preflight summary and explicit approval; failure leaves the old path active.

- [ ] **Step 4: Run publication, settings, and capability tests**

Run:

```powershell
npm --prefix desktop run test -- src/features/library src/features/settings
npm --prefix desktop run test
npm --prefix desktop run build
```

Expected: copy-on-import, immutable version, derived draft, publish hash expiry, remote metadata, path migration rollback, capability probe, no silent fallback, and credential redaction tests pass.

- [ ] **Step 5: Commit library and settings surfaces**

```powershell
git add desktop/src/features/library desktop/src/features/settings
git commit -m "feat: add module library and settings"
```

### Task 11: Tray Lifecycle and Active Job Protection

**Files:**
- Create: `desktop/src-tauri/src/tray.rs`
- Create: `desktop/src-tauri/src/window_lifecycle.rs`
- Modify: `desktop/src-tauri/src/main.rs`
- Create: `desktop/src/components/system/QuitDialog.tsx`
- Create: `desktop/src/features/jobs/useActiveJobs.ts`
- Test: `desktop/src/components/system/QuitDialog.test.tsx`
- Test: `desktop/src-tauri/tests/window_lifecycle.rs`

**Interfaces:**
- Consumes: active Job summaries and control-supervisor lifecycle.
- Produces: minimize-to-tray on close with active Runs, Restore/Open Jobs/Quit tray actions, and explicit Continue in background or Cancel jobs and quit choices.

- [ ] **Step 1: Write failing close-policy tests**

```rust
#[test]
fn close_with_active_jobs_hides_window_instead_of_stopping_sidecar() {
    let decision = decide_close(CloseIntent::WindowClose, active_jobs(1));
    assert_eq!(decision, CloseDecision::HideToTray);
}

#[test]
fn explicit_quit_requires_a_job_disposition() {
    let decision = decide_close(CloseIntent::Quit, active_jobs(2));
    assert_eq!(decision, CloseDecision::AskUser);
}
```

- [ ] **Step 2: Run and verify lifecycle policy is absent**

Run:

```powershell
cargo test --manifest-path desktop\src-tauri\Cargo.toml window_lifecycle
npm --prefix desktop run test -- src/components/system/QuitDialog.test.tsx
```

Expected: Rust and React imports fail.

- [ ] **Step 3: Implement explicit background and quit behavior**

Intercept main-window close. When Jobs are active, hide the window and keep Tauri, control service, and Workers alive; update tray tooltip with a textual active count. An explicit Quit opens one accessible dialog listing Run ID, task, state, and elapsed time. “Continue in background” hides the window, “Cancel jobs and quit” sends cancellation then waits for terminal acknowledgements up to the documented timeout, and “Return” restores focus without state loss. With no active jobs, Quit shuts down SSE, requests graceful service shutdown, waits, then terminates the sidecar if required.

- [ ] **Step 4: Verify window, tray, cancellation, and restart recovery**

Run:

```powershell
cargo test --manifest-path desktop\src-tauri\Cargo.toml
npm --prefix desktop run test -- src/components/system src/features/jobs
npm --prefix desktop run test
```

Expected: close-to-tray, restore, explicit quit, cancel timeout, sidecar cleanup, and interrupted-job reconciliation tests pass.

- [ ] **Step 5: Commit desktop lifecycle protection**

```powershell
git add desktop/src-tauri desktop/src/components/system desktop/src/features/jobs
git commit -m "feat: protect active jobs in system tray"
```

### Task 12: EEG Acceptance Project, Visual Verification, and Windows Packaging

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Create: `examples/eeg-emotion/ai4sota.project.yaml`
- Create: `examples/eeg-emotion/pyproject.toml`
- Create: `examples/eeg-emotion/.gitignore`
- Create: `examples/eeg-emotion/README.md`
- Create: `examples/eeg-emotion/scripts/generate_fixture.py`
- Create: `examples/eeg-emotion/modules/data/current/**`
- Create: `examples/eeg-emotion/modules/method/current/**`
- Create: `examples/eeg-emotion/modules/evaluation/current/**`
- Create: `examples/eeg-emotion/tasks/active.yaml`
- Create: `desktop/playwright.config.ts`
- Create: `desktop/e2e/research-flow.spec.ts`
- Create: `desktop/e2e/visual-workbench.spec.ts`
- Create: `desktop/e2e/accessibility.spec.ts`
- Create: `desktop/e2e/helpers/controlFixture.ts`
- Create: `scripts/build-control-sidecar.ps1`
- Create: `scripts/package-windows.ps1`
- Create: `desktop/src-tauri/binaries/.gitkeep`
- Modify: `desktop/src-tauri/tauri.conf.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: all three implementation plans, deterministic synthetic EEG fixture, PyInstaller sidecar build, and Tauri Windows bundler.
- Produces: one full EEG expert-task acceptance flow, baseline screenshots, accessibility evidence, packaged sidecar, and installable Windows artifact.

- [ ] **Step 1: Write the failing end-to-end scientific journey**

```ts
test("researcher completes the EEG workflow and preserves run history", async ({ page, control }) => {
  await control.openEegProject();
  await page.getByRole("link", { name: "Data" }).click();
  await expect(page.getByText("62 channels")).toBeVisible();
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByText("Compatible")).toBeVisible();
  await page.getByRole("button", { name: "Prepare run" }).click();
  await page.getByRole("button", { name: "Approve and queue" }).click();
  await expect(page.getByText("Succeeded")).toBeVisible({ timeout: 120_000 });
  await control.createSecondSeedRun();
  await page.getByRole("button", { name: "Compare selected runs" }).click();
  await expect(page.getByText("Directly comparable")).toBeVisible();
  await page.getByRole("button", { name: "Draft research commit" }).click();
  await expect(page.getByText("Commit the selected Run snapshot")).toBeVisible();
});
```

- [ ] **Step 2: Run the browser flow and verify the missing acceptance fixture**

Run: `npm --prefix desktop run test:e2e -- research-flow.spec.ts`

Expected: FAIL because the EEG project fixture, desktop bridge fixture, or final route wiring is absent.

- [ ] **Step 3: Build the deterministic EEG slice and package scripts**

Generate a small local NPZ fixture with a fixed seed: 24 trials, 6 synthetic subjects, 62 named channels, 200 samples per trial, 200 Hz, and three emotion labels. The Data adapter loads it into `CanonicalDataset`, applies declared detrending and train-fitted channel standardization, and exposes stable subject/trial IDs. The Method is a fast CPU baseline with declared input/output shapes and checkpoint behavior. Evaluation owns a subject-safe fixed split, macro F1 primary metric, accuracy secondary metric, per-class table, confidence interval, confusion matrix, and a simple capability-compatible saliency artifact. Keep all generated scientific files deterministic and small enough for source control.

Add `PyInstaller>=6.13,<7` to the root `dev` extra. `build-control-sidecar.ps1` creates a clean PyInstaller build from the root lock/environment, names the binary using Tauri's target-triple sidecar convention, and copies only the executable into `desktop/src-tauri/binaries/`. Ignore generated sidecar executables, Rust `target/`, Vite output, Playwright transient output, and installers while retaining `binaries/.gitkeep` and committed visual baselines. `package-windows.ps1` runs Python tests/lint, npm tests/typecheck/build, Cargo tests, sidecar build, Playwright, then `npm run tauri build`; it stops on the first failure and prints artifact paths without secrets.

- [ ] **Step 4: Run full functional, visual, accessibility, and package verification**

Run:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
npm --prefix desktop run test
npm --prefix desktop run typecheck
npm --prefix desktop run build
cargo test --manifest-path desktop\src-tauri\Cargo.toml
npm --prefix desktop run test:e2e
powershell -ExecutionPolicy Bypass -File scripts\package-windows.ps1
```

Playwright must capture Home, Overview, Data Schema, Files/Diff, Agent approval, Run approval, running log drawer, Experiments, Comparison, Research History, Global Library, and Settings at 1440x900, 1024x768, and 760x700, plus a 390x844 browser-only narrow-layout check. Inspect the screenshots and assert: no blank regions caused by failed rendering; no overlaps or clipped controls; the central object remains usable after pane collapse; no gradients or decorative blobs; headings stay within 16-20 px; cards are limited to repeated records/dialogs; focus is visible; text contrast is at least 4.5:1; UI components/icons are at least 3:1; zoom to 200% still exposes every action; reduced motion disables nonessential transitions; tables remain reachable; charts have visible data tables; long IDs/paths wrap or reveal their full value.

Expected: all Python, React, Rust, Playwright, axe-core, screenshot, and packaging checks pass; the EEG flow produces two immutable comparable Runs and one exact-snapshot Research Commit; the Windows installer launches with the packaged control service listening only on `127.0.0.1`.

- [ ] **Step 5: Commit the acceptance slice and release candidate**

```powershell
git add examples desktop scripts README.md
git commit -m "feat: complete eeg desktop vertical slice"
git status --short
```

Expected: the commit succeeds and `git status --short` is empty.

## Plan Completion Gate

Execute `scripts\package-windows.ps1` from a clean checkout, install the produced bundle on a Windows test account, and run the complete scenario without a development server:

```text
Create/open EEG project
  -> inspect Data shape, labels, subjects, channels, and preprocessing
  -> review Method baseline and evidence
  -> confirm Evaluation split, metrics, statistics, and explanation
  -> compile compatibility and inspect any generated adapter
  -> approve and complete Run A
  -> edit only the declared repetition seed and complete Run B
  -> receive directly_comparable and inspect table/chart values
  -> create a Research Commit from the exact selected snapshot
  -> publish the validated Method as a new immutable local-library version
  -> close during a third active Run, restore from tray, and cancel explicitly
```

Required evidence: Python/TypeScript/Rust test output, loopback binding check, token/redaction test, screenshot matrix, axe-core report, packaged installer path, two Run manifests, comparison report, Research Commit manifest plus Git SHA, immutable published module ref, and a clean Git worktree.
