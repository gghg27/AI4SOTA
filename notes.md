# Notes: AI4SOTA Product and Competitive Landscape

## Product Thesis

AI4SOTA is a local, desktop research workspace in which a researcher and an AI agent jointly build, inspect, modify, run, and preserve modular machine-learning experiments. Data, method, and evaluation are independently replaceable modules connected through explicit contracts. The researcher retains authority over scientific meaning and acceptance; AI provides search, synthesis, scaffolding, implementation suggestions, debugging, and record drafting.

## Sources

### Orange Data Mining
- URL: https://orangedatamining.com/
- Official description: open-source machine learning and data visualization.
- Uses a visual canvas of connected widgets and supports specialized extensions for text, networks, fairness, time series, survival data, spectra, and gene expression.
- Relevance: strong reference for a replaceable module canvas and domain add-ons; weak on code-first research collaboration and experiment lineage.

### KNIME Analytics Platform
- URL: https://www.knime.com/knime-analytics-platform
- Official description: free, open-source analytics platform where coding is optional and the platform is extensible.
- Advertises 300+ data connectors, reusable workflow components, Python/R/JavaScript scripting, custom extensions, and a generative-AI assistant.
- Relevance: strongest UI/product reference for visual workflows, reusable components, data connectors, and editable code escape hatches.

### Kedro
- URL: https://docs.kedro.org/en/stable/getting-started/kedro_concepts/
- Defines nodes as wrappers around pure Python functions with named inputs and outputs; pipelines resolve dependencies; Data Catalog abstracts loading and saving across file types.
- Supports modular pipelines, namespaces, registries, custom datasets, hooks, plugins, testing, and integrations with MLflow and DVC.
- Relevance: strong code-first reference for contracts, modularity, data adapters, project templates, and testability.

### ZenML
- URL: https://docs.zenml.io/
- Open-source orchestration framework for ML, LLM, and agentic pipelines.
- Core concepts include steps, pipelines, artifacts, versioned snapshots, stack components, caching, and infrastructure abstraction.
- Relevance: useful for separating scientific workflow definitions from execution infrastructure; much more deployment/MLOps-oriented than AI4SOTA.

### DVC Experiments
- URL: https://dvc.org/doc/user-guide/experiment-management
- Saves workspace variations as experiments connected to the current Git baseline without putting every temporary experiment into the normal Git tree.
- Tracks and compares parameters, metrics, plots, models, and datasets; supports queuing, sharing, and a VS Code GUI.
- Relevance: closest precedent for separating frequent Run records from curated Git history and for data/artifact lineage.

### MLflow Tracking
- URL: https://mlflow.org/docs/latest/ml/tracking/
- Tracks runs, parameters, metrics, datasets, models, notes, and artifacts.
- Separates a metadata backend store from an artifact store and supports local files, SQLite-style local databases, and remote servers.
- Relevance: strong reference for the Run ledger storage model and local-first growth path; it does not model scientific decisions or module compatibility.

### ClearML
- URL: https://clear.ml/docs/latest/docs/
- End-to-end AI development and deployment platform with an IDE, data management/versioning, experiment tracking, hyperparameter optimization, and workflow automation.
- Relevance: broad product benchmark for integrated experiment operations; optimized around MLOps and infrastructure rather than researcher-controlled scientific reasoning.

### Weco and AIDE ML
- URLs: https://docs.weco.ai/ and https://github.com/WecoAI/aideml
- Weco describes itself as a steerable, traceable autoresearch engine that rewrites code against a user-defined metric.
- Each experiment is a node in a solution tree; users can inspect variants and steer or branch the search with natural-language instructions. Code and data run locally.
- AIDE ML is the open reference implementation: an LLM-guided tree search that drafts, debugs, benchmarks, and improves ML code.
- Relevance: closest match for AI-assisted iterative model improvement and human steering. Missing AI4SOTA's explicit data/method/evaluation contracts, semantic confirmation gates, literature evidence graph, and Research Commit concept.

### The AI Scientist
- URL: https://github.com/SakanaAI/AI-Scientist
- Presents a system for fully automated, open-ended scientific discovery with idea generation, experiments, writing, and review.
- Warns that it executes LLM-written code and recommends containerization and restricted web access.
- Relevance: useful source for automation loops and security lessons, but its autonomous decision model is intentionally opposite to AI4SOTA's researcher-authority principle.

### PaperQA2
- URL: https://github.com/Future-House/paper-qa
- Scientific-document RAG focused on high-accuracy question answering, summarization, contradiction detection, and cited answers across PDFs, office files, text, and source code.
- Relevance: useful candidate/reference for evidence-grounded method research after paper discovery; it is not an experiment workspace.

### goose
- URL: https://goose-docs.ai/
- Local general-purpose agent available as desktop app, CLI, and API.
- Supports MCP extensions, portable YAML recipes, interactive extension UIs, subagents, multiple model providers, and security controls.
- Relevance: strong reference for the desktop agent shell, provider abstraction, tool extensions, workflow recipes, and permission model; it lacks AI4SOTA's scientific domain model.

## Synthesized Findings

### Market Shape
- No single reviewed product combines all of AI4SOTA's defining elements.
- Visual workflow tools cover replaceable components but not research-aware AI collaboration.
- MLOps tools cover pipeline execution and experiment tracking but not scientific meaning or user confirmation.
- Autoresearch agents cover iterative code optimization but tend to collapse success into one metric and grant the agent too much authority.
- Literature agents cover evidence retrieval but do not connect citations to module revisions, runs, and conclusions.
- Desktop coding agents provide the shell and tool ecosystem but lack scientific contracts and experiment semantics.

### Product Gap
- AI4SOTA's opportunity is a researcher-governed scientific workspace, not a generic pipeline builder or autonomous optimizer.
- Its differentiator should be the explicit relationship between scientific intent, module contracts, code changes, evidence, deterministic runs, and user-confirmed conclusions.
- Data, method, and evaluation should be treated as scientific modules with invariants and provenance, not merely generic DAG nodes.

### Architectural Lessons
- Use Kedro-like named contracts and catalogs for deterministic composition.
- Use KNIME/Orange-like visual composition, but preserve a first-class code workspace inside every module.
- Use DVC's distinction between ephemeral experiments and curated Git history as the basis for Run versus Research Commit.
- Use MLflow's backend/artifact separation, initially implemented with SQLite plus local artifact directories.
- Use Weco's inspectable solution tree and mid-run steering only inside explicitly authorized optimization sessions.
- Use goose-style provider/tool extensions and permission controls rather than coupling to one LLM or paper service.
- Use PaperQA-style citation-grounded synthesis and keep each claim linked to source evidence.

### Recommended Next Vertical Slice
- Do not begin with general-purpose autonomous optimization.
- First prove: import CSV/NPZ -> confirm DatasetSourceSpec, PreprocessingSpec, and DataModuleSpec -> generate and inspect an adapter -> validate a canonical dataset -> connect one method and one evaluation module -> run -> modify one module -> run again -> curate two Research Commits -> compare them with a comparability verdict.
- This slice tests AI4SOTA's unique product thesis better than adding more models or building a polished empty desktop canvas.

## Domain Refinement: Multi-Domain EEG Foundation Models

### User's Concrete Scenario
- The first real application is training EEG foundation models and expert models across multiple domains such as emotion recognition and sleep staging.
- Researchers will frequently switch among open EEG datasets, models, tasks, preprocessing recipes, metrics, and explainability methods.
- Every data, model, and evaluation component needs a schema card that both humans and agents can understand.

### Required Schema Boundaries
- `DatasetSourceSpec`: immutable or slowly changing facts about one source dataset: provenance, license/access, file organization, subjects/sessions, acquisition hardware, montage, channel names, reference, sampling rate, units, events, labels, demographic metadata, known exclusions, and raw-data fingerprint.
- `PreprocessingSpec`: experiment choice: detrending, filtering, notch, re-referencing, resampling, bad-channel policy, artifact rejection, channel selection/mapping, epoching/windowing, normalization, missing-channel behavior, and fitted-statistics scope.
- `DataModuleSpec`: binds a versioned dataset source and preprocessing recipe, declares its canonical output contract, and records validation artifacts.
- `MethodSpec`: declares backbone, task/expert heads, framework, accepted input axes and sampling/channel policies, masking, objectives, optimizer/schedule, initialization/checkpoint provenance, training modes, outputs, and search space.
- `EvaluationSpec`: declares task ontology, split and cross-validation unit, leakage constraints, primary/secondary metrics, aggregation level, statistical protocol, robustness checks, explainability requirements, and output artifacts.
- `ExperimentSpec`: is not a fourth plugin; it is the composition record that selects exact versions of the three modules and captures cross-module mappings and runtime settings.

### EEG-Specific Compatibility Checks
- Signal axes and batch layout, such as `CT`, `TC`, or `BCT`.
- Units and numerical scale, including volts versus microvolts.
- Sampling rate and whether resampling is approved.
- Channel names, montage, reference, channel order, missing-channel policy, and spatial-coordinate availability.
- Fixed/variable duration, epoch boundaries, padding, masks, and overlap.
- Subject/session/trial identifiers and group leakage.
- Task and label ontology, especially different emotion label definitions and sleep-stage standards.
- Normalization fitting scope so test subjects do not influence training statistics.
- Model output capabilities required by evaluation, such as probabilities, embeddings, attention, gradients, or intermediate features.

### Proposed Canonical Data Path

```text
Raw EEG files
  -> Source Adapter
  -> RawEEGDataset
  -> versioned preprocessing graph
  -> CanonicalEEGDataset
  -> Model Input Adapter / Collator
  -> shared backbone and/or expert head
  -> PredictionBundle
  -> EvaluationResult
```

### Critical Open Architecture Question
- "Multi-domain EEG model" can mean either one jointly trained shared backbone with multiple domain/task heads, or a workspace that manages multiple independently trained expert models. These require different sampler, batch, checkpoint, task-routing, and evaluation contracts, so the first implementation must choose one as primary while leaving an extension path for the other.

## Human-AI Collaboration Model

### Core Principle
- AI4SOTA is a structured collaborative research IDE, not an autonomous optimizer.
- The researcher owns problem definition, scientific semantics, method selection, evaluation protocol, patch acceptance, execution approval, and conclusions.
- AI acts as research librarian, discussion partner, code scaffolder, patch author, debugger, reviewer, and run summarizer.

### New-Task Workflow
1. Create a project-level Research Brief describing the question, constraints, available data, and intended outcome.
2. Enter the data workspace: inspect sources, retrieve dataset documentation, discuss semantics and preprocessing, draft the schema and adapter, review code and validation results, then confirm the module.
3. Enter the method workspace: use the confirmed data contract to research papers and baselines, compare candidates, choose a plan, generate code/tests, review the patch, then confirm the module.
4. Enter the evaluation workspace: define task ontology, split protocol, metrics, statistics, and explainability; generate code/tests; lock the confirmed primary protocol.
5. Assemble modules: compile compatibility, show automatic representation adapters and semantic blockers, then request user approval before execution.
6. Record the Run and let the researcher decide whether it deserves a Research Commit.

### Ongoing Work
- Initial setup is sequential because downstream discussions depend on upstream contracts.
- After setup, the workflow becomes iterative rather than a rigid wizard: each module can be reopened independently for discussion, direct code editing, AI-assisted patches, testing, evidence updates, and version creation.
- A module change marks affected downstream modules as needing review instead of silently rewriting them.

### Conversation Scopes
- Recommended structure is one project-level conversation plus one scoped conversation per module.
- The project conversation owns the research question, cross-module coordination, run comparison, and Research Commit drafting.
- Module conversations receive only their module files, contract, references, tests, and relevant upstream/downstream interface summaries, which reduces context contamination and accidental cross-module edits.
- User confirmed this one-plus-three conversation and workspace structure on 2026-09-05.

## Module Library and Version Lifecycle

### Confirmed Model
- AI4SOTA has a global module library from which data, method, and evaluation modules can be imported into projects.
- Importing creates a project-local editable working copy with an origin reference to the global module and version.
- Project edits never mutate the originating global version or other projects.
- A useful project-local module can be reviewed, tested, and explicitly published back to the global library as a new version.
- Global modules can be developed in a dedicated Module Studio, but published versions remain immutable. Editing starts a draft derived from a selected version and publication creates the next version.

### Proposed States
- `draft`: editable and not available as a stable dependency.
- `testing`: undergoing schema, unit, interface, and sample-data validation.
- `published`: immutable and importable by projects.
- `deprecated`: retained for reproducibility but hidden from normal recommendations.

### Provenance
- Every project module instance records `module_id`, `type`, `origin`, `based_on_version`, local content hash, schema version, and modification state.
- Every Run records the exact project-local content snapshot, not only the global module version.
- Publishing records the source project module, parent global version, tests, compatibility declaration, author, and publication time.

### First-Version Scope
- Confirmed: the global library is stored locally on one machine.
- Reserve fields such as `remote_origin`, `remote_version`, and `source_url`, but do not implement accounts, cloud synchronization, permissions, or team sharing in the first version.
- Support future portable module-package import/export without making remote distribution a current requirement.
- Never include API keys, credentials, private dataset paths, or raw datasets in an exported module package.

## Self-Contained Projects and External Editors

### Confirmed Storage Principle
- Every research project is a self-contained directory chosen by the user and stored on the local filesystem.
- Code, schemas, references, configuration, Run metadata, Research Commits, and human-readable reports remain inspectable without AI4SOTA.
- The application database stores project discovery/index information and application settings, not the only copy of scientific project state.

### Editor Strategy
- AI4SOTA provides a lightweight editor for schema cards, small code edits, generated patches, and diff review.
- Advanced editing, navigation, refactoring, debugging, and extensions are delegated to VS Code through an "Open project/module in VS Code" command.
- AI4SOTA and VS Code edit the same project directory. There is no second project copy to synchronize.

### File Change Detection
- A recursive filesystem watcher monitors project-owned source, schema, configuration, test, and reference paths.
- Changes are debounced and represented as create/modify/delete/rename events with path, timestamp, and new content hash.
- Generated Run outputs, virtual environments, caches, large raw-data trees, and ignored paths are excluded from normal source-change events.
- An application file index maps paths and hashes to their owning module and marks that module `changed`; affected downstream modules become `needs_review`.
- Git status and diffs summarize changes, but Git is not the synchronization mechanism.

### Agent Freshness and Conflict Safety
- Agent conversations persist decisions and file references, not authoritative cached file contents.
- Before code analysis, patch generation, patch application, validation, or execution, the Agent reloads relevant files and their current hashes.
- Every proposed patch records base content hashes. Application is atomic only if those hashes still match.
- If VS Code changes an overlapping file after patch generation, AI4SOTA refuses to overwrite it and shows a three-way comparison or requests regeneration against the new content.
- Non-overlapping external changes can be re-indexed automatically and summarized in the active conversation.

### Run Isolation
- Starting a Run creates an immutable source/config/module snapshot identified by content hashes, optionally backed by a Git commit or isolated worktree later.
- The process executes from the snapshot rather than the live working tree.
- VS Code edits made after the Run starts do not change that Run's behavior or provenance.
- A completed Run records both its snapshot and whether the live workspace has changed since launch.

### Desktop Feedback
- When external edits are detected, the relevant module shows a dirty/changed badge and the module conversation receives a compact change event.
- If an overlapping Agent edit is in progress, the task pauses at the write boundary and asks the user to review the conflict.
- Users can inspect the diff, refresh Agent context, rerun module validation, or deliberately discard/revert through explicit commands.

### Code Modification Permissions
- User confirmed that the AI may directly edit files inside the active module's working copy.
- AI edits remain visible, reviewable, reversible workspace changes rather than accepted scientific versions.
- The user must confirm before running an experiment, saving a module version, or creating a Research Commit.
- A stricter preview-before-apply mode can be offered, but it is not the default interaction.

### Confirmed External-Editor State Machine
- `clean`: the indexed file hash matches the current workspace content.
- `externally_changed`: VS Code or another process changed a project-owned file; AI4SOTA re-indexes it and marks its owning module dirty.
- `agent_patch_pending`: the Agent has proposed or prepared a patch against recorded base hashes.
- `conflict`: at least one patch target changed after the patch was prepared; the patch cannot be applied until it is regenerated or explicitly resolved.
- `snapshot_running`: a Run is executing from an immutable launch snapshot while the live workspace remains independently editable.
- Ordinary external edits are automatically refreshed because the filesystem is the source of truth.
- Overlapping edits never use last-writer-wins. Patch application checks all base hashes and either applies the whole patch atomically or writes nothing.
- A Run never reads mutable project source after launch. Its manifest records snapshot hashes and whether the live workspace later diverged.
- User confirmed on 2026-09-05: no conflict -> auto-refresh; overlapping Agent edit -> pause for conflict review; active Run -> continue from launch snapshot.

## Existing Kernel Integration Evidence

### Current Execution Boundary
- The Phase 1 package is a Python 3.10+ CLI with only NumPy and PyYAML runtime dependencies.
- `ai4sota.cli` directly calls project creation, validation, execution, and history functions in the same Python process.
- `ai4sota.runner.run_project` dynamically imports project-local `method/model.py` and `evaluation/evaluator.py`, then runs user-editable code in-process.
- A Run writes directly into the live project's `runs/<run_id>/` directory and currently records `source_revision` as `unversioned-phase1`.
- The stable concepts worth preserving are the CLI/service operations and the three handoff objects: `CanonicalDataset`, `PredictionBundle`, and `EvaluationResult`.

### Desktop Requirements Not Yet Present
- A job API for validation and Runs with lifecycle states, progress events, log streaming, cancellation, and recovery after the desktop UI restarts.
- Snapshot creation before execution so dynamically imported code and configs never come from the mutable working tree after launch.
- A separate worker process boundary because project modules are arbitrary Python code and must not run inside the desktop application's control process.
- Explicit tool permissions for Agent reads, writes, commands, network access, paper-source access, and experiment execution.
- A provider-neutral Agent interface so conversations, tool calls, and research evidence do not depend on one LLM vendor.
- A durable local store for application indexes, conversations, approvals, jobs, and module-library metadata while project scientific state remains in project directories.

### Confirmed Integration Principle
- Preserve the current Python kernel as the domain engine and evolve it behind an application-service boundary; do not reimplement scientific contracts or execution logic in the desktop frontend.
- Treat the desktop shell, Agent orchestration service, and experiment worker as three different trust and lifecycle boundaries even if they ship in one installer.
- Confirmed choice: Tauri 2 desktop shell with React/TypeScript, a packaged Python control service, and independent experiment Worker processes.

## Local Desktop Toolchain Evidence
- Verified on 2026-09-05: Python `3.11.7` and Node.js `v25.9.0` are available.
- The current `npm` launcher is broken because `C:\Users\zj\AppData\Roaming\npm\node_modules\npm\bin\npm-cli.js` is missing.
- `rustc` and `cargo` are not currently installed.
- Neither the workspace root nor `AI4SOTA-MVP-Phase1` currently contains a Git repository.
- Consequence: all three desktop approaches remain conceptually available, but Tauri requires Rust setup, Tauri/Electron both require a repaired supported Node LTS toolchain, and Git-backed product behavior requires repository initialization.
- Recommendation remains Tauri 2 + React/TypeScript for the desktop shell, with the existing Python package evolved into a local application service and separate experiment workers. The additional bootstrap cost is justified by a smaller desktop shell, explicit filesystem permissions, a strong native boundary, and reuse of established web UI libraries.
- Electron + React would simplify JavaScript-side process control but has a heavier runtime footprint and does not remove the Python worker/packaging problem.
- PySide would minimize initial toolchain setup, but it is less aligned with the intended ChatGPT-like workspace, React Flow-style composition UI, Monaco-based lightweight editor, and future extension ecosystem.

## Tauri and Python Runtime Evidence

### Official Tauri Capabilities
- Official sidecar documentation: https://v2.tauri.app/develop/sidecar/
- Tauri 2 supports embedding external binaries through `bundle.externalBin` and launching a named sidecar from Rust or JavaScript.
- Sidecar binaries are packaged per target triple, so the Python control service must be frozen into platform-specific executables during release builds.
- Official shell-plugin documentation: https://v2.tauri.app/plugin/shell/
- Potentially dangerous shell commands and scopes are blocked by default; capabilities can allow only named commands and validate argument shapes. Spawn, kill, and stdin access are separate permissions.
- Tauri permissions constrain what the webview can ask the native shell to do. They do not sandbox arbitrary Python code once that code is executing, so experiment isolation remains a Python/OS worker responsibility.

### Confirmed Process Boundaries
```text
React/TypeScript webview
  -> narrow Tauri commands
  -> packaged Python control service
       -> Agent orchestration and provider adapters
       -> project/module index and SQLite metadata
       -> filesystem/hash service
       -> job manager
            -> isolated validation/test/experiment worker process
                 -> immutable Run snapshot
                 -> project-specific Python environment
```
- The frontend must never receive a general-purpose shell primitive. It calls typed application commands only.
- The Python control service owns domain operations and evolves the current CLI kernel instead of duplicating it.
- User-editable data, method, and evaluation code runs only in child workers, never inside the Tauri process or long-lived control-service process.
- Each worker receives a concrete snapshot path, environment identifier, allowed paths, job manifest, and cancellation channel.
- The first release should provide process isolation, sanitized environments, and path-scoped AI4SOTA tools but explicitly avoid claiming a strong security sandbox. Arbitrary Python code still inherits the operating-system user's effective file and network access; strong enforcement requires a later container/VM execution backend.

### Confirmed IPC Choice
- Use loopback HTTP through FastAPI for typed request/response, plus WebSocket or Server-Sent Events for job and log streams.
- Bind only to `127.0.0.1`, choose an ephemeral port at each launch, pass a per-launch authentication token from the Tauri parent process, and reject unauthenticated or unexpected-origin requests.
- Do not expose the control service on a LAN interface and do not persist the launch token in project files or logs.
- JSON-RPC over sidecar stdin/stdout and spawning a fresh Python process per operation are rejected for version one because they complicate streamed events, reconnection, persistent conversations, job recovery, and filesystem indexing.

### Agent Permission Model Draft
- Automatic: read project-owned files, refresh hashes, write within the active module working copy, update local conversation/index metadata, and inspect existing Run artifacts.
- Policy-controlled automatic: execute a small allowlist of validation, formatting, lint, and unit-test commands inside the project environment.
- Always confirm: start an experiment, expand filesystem scope, execute an arbitrary shell command, enable network access for project code, install or remove dependencies, publish a module version, create a Research Commit, and perform destructive or bulk file operations.
- Literature metadata search may be enabled per connector; downloading full text, using authenticated accounts, or sending local content to an external model must display the exact scope and follow the relevant connector/data policy.

## External Editing and Snapshot Acceptance Detail (Confirmed)

### Separate Status Dimensions
- `workspace_state` answers whether project-local content differs from its last accepted module version: `clean` or `dirty`.
- `compatibility_state` answers whether declared contracts still compose: `valid`, `needs_review`, or `blocked`.
- `job_state` answers what an operation is doing: `queued`, `snapshotting`, `running`, `cancelling`, `succeeded`, `failed`, or `cancelled`.
- A source-code-only edit makes the owning module dirty but does not automatically imply interface incompatibility.
- A schema or public-contract hash change marks relevant downstream modules `needs_review`; a failed compatibility compilation marks the composition `blocked`.

### Watch Zones
- High-frequency editable zone: project manifest, module schemas and source, adapters, pipeline, configs, tests, discussion summaries, and reference indexes.
- Excluded from high-frequency recursion: `.git`, virtual environments, dependency caches, `__pycache__`, raw data trees, preprocessing caches, checkpoints, and large Run artifacts.
- Job-owned output zone: active Run files are surfaced through job events rather than treated as user edits.
- Integrity zone: completed Run manifests and Research Commits are hash-checked when opened, compared, or audited. External changes are reported as integrity divergence and are never silently incorporated into the original record.
- External dataset roots are not recursively watched by default. Dataset manifests use cached path/size/mtime checks and strong content hashes when a source is imported, explicitly refreshed, or frozen for a Run.

### Watcher Reliability Rules
- Debounce and coalesce editor save sequences because VS Code may implement one save as temporary-file creation, rename, and deletion events.
- Tag AI4SOTA-originated writes with an operation identifier so their watcher events update the index without being misreported as external edits.
- Treat the watcher as a responsiveness mechanism, not the sole source of correctness. Reconcile current file hashes when the app regains focus and before Agent analysis, patch application, validation, snapshot creation, or execution.
- Apply a multi-file Agent patch atomically only when every base hash still matches; otherwise apply none of it and produce a conflict report.

### Run Snapshot Semantics
- Freeze project code, module schemas, configs, generated adapters, dependency-lock metadata, split manifests, environment metadata, and their hashes into a Run snapshot before launch.
- Copy snapshot-controlled text/source files into a private Run staging directory. Do not depend on the live working tree or require a clean Git state.
- Large raw EEG datasets remain external or project-referenced rather than being copied for every Run.
- Record a versioned dataset manifest and strong fingerprint at launch. Recheck source metadata/fingerprints after the Run when feasible; if relevant input changed during execution, mark the Run `data_integrity_changed` and exclude it from fair comparison until reviewed.
- Optional managed immutable data storage or DVC-style content addressing can later provide stronger guarantees without per-Run full copies.

### Acceptance Scenarios
1. Editing `method/model.py` in VS Code updates the method content hash and dirty badge; the next Agent action reads the new file.
2. Editing the method output contract marks evaluation `needs_review`; execution remains blocked until compatibility is recompiled and confirmed.
3. Changing a patch target after the Agent prepared a patch causes an all-or-nothing conflict with no overwritten file.
4. Editing an unrelated file while a patch is pending does not prevent a hash-valid patch from applying.
5. Editing live workspace code after Run launch does not change the executing snapshot or its recorded source hashes.
6. Changing a referenced dataset during a Run marks its data integrity as changed rather than reporting a reproducible success.
7. Modifying a completed Run artifact externally produces an integrity warning while retaining the originally recorded manifest hashes.
8. Closing and reopening the project reconciles missed filesystem events from disk and produces the same file index state.

## Literature Connector Feasibility

### Live Public-API Probe (2026-09-05)
- OpenAlex `works` search returned normalized identifiers, DOI, title, publication year, and open-access location without an API key.
- Europe PMC search returned biomedical/preprint metadata, DOI, publication type, open-access/full-text flags, and citation counts without an API key.
- Anonymous Semantic Scholar Graph API access returned HTTP 429 and explicitly recommended an API key for higher limits.
- The arXiv export API connection was reset in the current environment. This may be network-specific, but it is insufficient evidence for treating direct arXiv access as an always-available dependency.
- Zotero was not found on the command path, in standard Windows installation locations, or as a running process on the current machine. A version-one Zotero integration would therefore need to be an optional connector with a clean unavailable state, not a required local dependency.

### Confirmed Version-One Sources
- User confirmed option A on 2026-09-05.
- Built in: OpenAlex for broad scholarly discovery and open-access locations.
- Built in: Europe PMC for biomedical/clinical neuroscience coverage and full-text availability metadata.
- Built in: local PDF, DOI, PMID, arXiv-ID, and URL import so the researcher can supply material obtained through legitimate institutional access.
- Optional connector: Semantic Scholar when the user provides an API key stored in the operating-system credential store.
- Optional later connector: Zotero local/API library, direct arXiv, Crossref enrichment, GitHub repository search, and institution-specific discovery services.
- Do not scrape publisher login pages, store browser cookies, or attempt to bypass access controls. Open authenticated content in the user's system browser and let the user import the resulting PDF or permitted URL.

### Normalized Evidence Flow
```text
connector search result
  -> PaperRecord (DOI/PMID/arXiv ID, title, authors, year, venue, URLs, license)
  -> deduplication and user selection
  -> EvidenceSource (metadata/abstract/open full text/local PDF)
  -> extracted passage with page/section locator
  -> EvidenceClaim linked to a module discussion, code decision, or Research Commit
```
- Search results are leads, not evidence. Claims must cite an imported abstract/full-text passage or be labeled as metadata-only inference.
- Retrieved papers and repository files are untrusted content. They may inform synthesis but cannot issue tool instructions or expand Agent permissions.
- Literature records belong in the project for reproducibility; credentials, provider tokens, and browser sessions do not.
- Every derived method decision should retain source identifiers, exact passages where available, retrieval time, license/access status, and the researcher's acceptance or rejection.

### Scope Rationale
- This source set covers broad discovery plus biomedical depth without requiring account automation.
- Connector adapters remain replaceable so a researcher's institutional or commercial sources can be added later without changing Agent or module contracts.
- The MVP should prove evidence-to-module traceability before adding many partially reliable search providers.

## Schema Audit Against Multi-Domain EEG Use

### Gaps Identified In The Earlier README Examples
- The earlier `DatasetSpec` example mixed objective source facts, preprocessing choices, label mapping, and split policy. The README now separates DatasetSourceSpec, PreprocessingSpec, and DataModuleSpec.
- Split ownership was duplicated conceptually between data and evaluation. The confirmed design makes data expose stable grouping identifiers and Evaluation own the scientific split protocol.
- The earlier `MethodSpec` assumed one fixed classification head. The README now separates backbone, heads, objectives, training recipe, inference, and checkpoint policy.
- The earlier examples repeated `task: classification` without a shared semantic identity. They now reference a shared TaskContract.
- Evaluation explainability prerequisites, aggregation units, reference baselines, output semantics, and compatibility requirements remain normative fields for the complete design spec.

### Keep Three Plugins, Add Shared Contracts
- Data, method, and evaluation remain the only plugin types.
- `TaskContract` is a shared semantic object, not a plugin. It identifies the prediction unit, target ontology, label encoding, missing/unknown-label policy, output meaning, and aggregation unit.
- `ExperimentSpec` is the immutable composition draft for one Run. It selects exact module working-copy hashes or published versions, one or more task contracts, explicit label mappings, generated representation adapters, runtime configuration, and the evaluation protocol.
- Each plugin declares capabilities and requirements against the same contract identifiers. The compatibility compiler resolves them before an experiment can be approved.
- User confirmed this shared-contract design on 2026-09-05; task semantics are not owned solely by Evaluation and are never inferred by matching broad strings such as `classification`.

### Normative Data Boundaries (Confirmed)
- `DatasetSourceSpec`: identity, provenance, access/license, storage references, subject/session/run structure, acquisition hardware, sampling, channels/montage/reference, units, raw axes, events, source labels, metadata fields, exclusions, and source fingerprint manifest.
- `PreprocessingSpec`: ordered transform graph, parameters, fitted-state scope, channel policy, filtering, re-reference, resampling, artifact policy, epoch/window rules, normalization, augmentation, cache policy, and semantic-approval records.
- `DataModuleSpec`: source/preprocessing references, source-adapter entry point, declared canonical outputs, task-label mappings, validation rules, and generated validation artifacts.
- The data module must emit stable `sample_id`, `dataset_id`, and where available `subject_id`, `session_id`, `run_id`, `trial_id`, channel metadata, sampling metadata, targets, masks, and provenance pointers.
- A `SplitManifest` is a frozen Run input generated from an evaluation protocol and data grouping metadata; it is not a mutable fact embedded in the dataset source card.
- User confirmed this ownership boundary on 2026-09-05: Data supplies stable identifiers and validates their availability; Evaluation owns the scientific split protocol; the experiment compiler materializes and freezes exact membership before execution.

### Normative Method Boundaries (Confirmed)
- Declare accepted modality/layout/dtype/unit/sampling/channel/mask policies and required metadata.
- Separate `backbone`, `objectives`, `heads`, `training_recipe`, `inference`, `checkpoint`, and `search_space` sections.
- A head binds to a `TaskContract` and declares logits/probabilities/regression values/embeddings/attention/gradients/intermediate-feature capabilities.
- Checkpoint provenance records source paper/repository/license, original checksum, parent Run or Research Commit, compatible backbone/head signatures, and loading policy.
- A version-one experiment may bind one data module, one method module, and one evaluation module even if the MethodSpec format already permits multiple declared heads.

### Normative Evaluation Boundaries (Confirmed)
- Own the task ontology reference, split/cross-validation protocol, leakage constraints, random-seed protocol, primary and secondary metrics, aggregation levels, statistics, robustness checks, explainability requirements, and report artifacts.
- Every metric declares required prediction fields, target type, averaging, positive class where relevant, sample weighting, undefined-case handling, and implementation/version.
- Every explainability method declares required model capabilities, input metadata, baseline/reference policy, aggregation level, and expected artifacts.
- Changing test membership, group unit, ontology, primary metric semantics, or metric implementation changes the comparison protocol hash and prevents an automatic improvement claim.

### Compatibility Verdict
- `compatible`: all representation and semantic requirements match exactly.
- `adaptable`: only approved mechanical adapters are needed, such as axis permutation, batching, safe dtype conversion, or mask collation.
- `requires_decision`: a scientifically meaningful mapping or transformation needs explicit researcher approval.
- `incompatible`: a required capability or semantic field is absent and cannot be generated without changing the selected modules.
- The compiler emits field-level findings and a deterministic contract hash; it never asks the LLM to decide compatibility at Run time.
- User confirmed the four-verdict model on 2026-09-05. `adaptable` is limited to a versioned allowlist of mechanical adapters; unresolved `requires_decision` and every `incompatible` finding block Run approval.

### Confirmed Version-One EEG Training Scope
- User confirmed option A on 2026-09-05: prove separate expert-model compositions first.
- Each Run resolves exactly one Data + Method + Evaluation composition and activates one expert task, such as emotion recognition or sleep staging.
- Researchers can switch datasets, preprocessing modules, methods, and evaluation protocols between Runs while preserving deterministic compatibility and comparison records.
- `TaskContract` and `MethodSpec` may describe shared-backbone and multiple-head capabilities for forward compatibility, but version one does not schedule joint multi-dataset or multi-task training.
- Heterogeneous batch construction, domain balancing, multi-task routing, multi-objective schedules, shared checkpoint updates, and cross-dataset joint samplers are explicitly deferred.

## Run Ledger, Git, and Research Commit Design (Confirmed)

### Three Different Histories
- Workspace history is the editable Git working tree and may contain incomplete human, Agent, or VS Code changes.
- Run history is append-only operational evidence. Every approved execution receives an immutable manifest and source/config snapshot, including failed and cancelled attempts, but does not create a normal Git commit.
- Research history contains only user-curated scientific nodes. A Research Commit is a real Git commit plus a structured manifest that references one or more Runs and records the researcher's conclusion.
- This separation preserves high-frequency debugging evidence without polluting the meaningful Git graph.
- User confirmed this three-history model on 2026-09-05. SQLite remains a rebuildable query index rather than the sole authority for Run or Research Commit state.

### Experiment Approval Binding
1. The compatibility compiler produces a resolved `ExperimentSpec` and deterministic hash.
2. The UI shows selected module content hashes, semantic decisions, split protocol, data fingerprint, environment, requested resources, and command.
3. User approval creates a short-lived approval record bound to that exact hash.
4. Snapshot creation revalidates all hashes. Any intervening change invalidates approval and returns to review rather than silently executing different content.
5. The job manager writes a Run manifest before starting the worker, then appends lifecycle events and terminal status atomically.

### Minimum Run Manifest
- Identity: Run ID, project ID, parent Research Commit, creator, note, timestamps, lifecycle status, cancellation/failure reason.
- Intent: Research Brief revision, resolved ExperimentSpec hash, user approval record, and any semantic decision records.
- Modules: exact data/method/evaluation content hashes, origin/published versions, entry points, generated adapter hashes, and contract hash.
- Data: source manifest hash, preprocessing graph hash, split manifest hash, label/task mapping, and pre/post integrity result.
- Environment: OS, Python, package-lock hash, framework/CUDA/device details, random seeds, working directory, and allowed resource/network policy.
- Results: scalar metrics with definitions, tables, predictions, checkpoints, plots, logs, warnings, artifacts, and content hashes.
- Comparison eligibility: protocol identity, integrity flags, incomplete outputs, and reasons a Run cannot support a fair claim.

### Storage Authority
- Human-readable Run manifests and reports live inside the project and are the scientific source of truth.
- A project-local SQLite database indexes Runs, events, metrics, conversations, approvals, and module metadata for fast UI queries, but must be rebuildable from project files and append-only event logs.
- The application-global SQLite database stores project discovery, settings, connector configuration references, and global-module-library indexes. It is never the only copy of project scientific state.
- Large artifacts stay outside Git and are referenced by relative/absolute location, size, media type, checksum, producer, and retention state.

### Research Commit Creation
- The user selects one or more compatible Runs, reviews an Agent-drafted hypothesis/change/result/conclusion summary, and explicitly confirms it.
- The commit manifest records parent Research Commit(s), exact Run IDs, comparison verdict, supporting evidence, limitations, acceptance status, and next action.
- Git tracks project text/source, schemas, split manifests, small reports, and artifact indexes; raw datasets, caches, checkpoints, and large predictions remain hash-referenced.
- The Git commit tree must match the chosen Run snapshot. If the live workspace has diverged, AI4SOTA creates the commit from the stored snapshot through an isolated worktree/branch and never resets or overwrites the live workspace.
- A namespaced tag or ref links the Git SHA to the Research Commit ID. The app's scientific graph is read from manifests, while ordinary Git tools can still inspect code history.
- User confirmed exact-snapshot promotion on 2026-09-05. Committing the live workspace while linking results from a different snapshot is forbidden, and Research Commit creation does not require the live workspace to be clean.
- User confirmed multi-Run aggregation on 2026-09-05 only for Runs sharing code/module, dataset, task, split, and evaluation protocol hashes. Allowed differences must be declared repetition dimensions such as seed, fold, or repeat index; the manifest records the aggregation method, sample count, mean/spread, and confidence interval where configured.
- Candidate Runs that differ outside those declared repetition dimensions cannot be aggregated into one Research Commit, even if their primary metric names match.

### Branch and Restore Behavior
- Creating a branch from a Research Commit starts from its exact Git tree and keeps the current workspace untouched unless the user explicitly switches.
- Restoring a module creates a reviewable workspace change; it does not rewrite Run or Research Commit records.
- Deleting a Run is not part of the normal workflow. Artifact cleanup may remove large payloads under an explicit retention action while preserving manifests, metrics, hashes, and tombstones.

### Comparability Verdict
- `directly_comparable`: data identity, split membership, task ontology, evaluation protocol/implementation, and required aggregation semantics match.
- `comparable_with_caveats`: a declared non-primary dimension differs but the comparison remains interpretable; caveats are shown explicitly.
- `not_comparable`: test membership, target meaning, primary metric semantics, integrity, or other decisive protocol elements differ.
- The verdict is deterministic and field-level. The Agent may explain it but cannot override it or state an improvement when the verdict is `not_comparable`.
- User confirmed the three-level comparison verdict on 2026-09-05. Raw results may still be shown side by side for `not_comparable` Runs, but the UI and Agent must suppress automatic deltas and improvement language.

### Ledger Acceptance Scenarios
1. Ten debugging Runs produce ten ledger records but no normal Git commits.
2. A failed or cancelled Run remains inspectable with its snapshot, logs, and terminal reason.
3. A workspace change after Run approval invalidates the approval before execution starts.
4. Promoting an older Run after later edits creates a commit from the older snapshot without modifying current files.
5. A Research Commit that aggregates several seeds references Runs sharing one protocol hash and reports aggregation rules.
6. Comparing Runs with different subject splits refuses to calculate an automatic improvement claim.
7. Rebuilding the project SQLite index from manifests preserves Run and Research Commit identities and relationships.

## Desktop Information Architecture (Confirmed)

### Product Shell
- The first screen is the usable project home, not a marketing page: recent projects, running jobs, module-library updates, and create/open actions.
- A narrow global rail owns Home, Projects, Global Module Library, and Settings.
- Inside a project, the primary navigation owns Overview, Data, Method, Evaluation, Experiments, and Research History.
- The main content area shows the selected scientific object; a persistent right panel hosts the correctly scoped Agent conversation.
- A collapsible bottom job drawer shows active validation/tests/Runs and streamed logs without forcing the researcher away from the current module.
- User selected the fixed research-workbench layout (option A) in both the visual companion and terminal on 2026-09-05. The global rail, project navigation, central workspace, right Agent panel, and bottom job drawer remain spatially stable as the user moves between project sections.

### Project Overview
- Show exactly three primary module blocks in a left-to-right scientific flow: Data -> Method -> Evaluation.
- Each block displays selected module identity, origin/version, workspace dirty state, readiness, compatibility status, latest validation, and the main action.
- Connections display contract verdicts rather than behaving as a general-purpose DAG editor in version one.
- The overview also shows current Research Brief, resolved ExperimentSpec, blocking decisions, recent Runs, and current Research Commit branch.
- The primary Run command remains disabled until all semantic decisions, compatibility checks, and snapshot inputs are valid; clicking it opens an approval review rather than executing immediately.

### Module Workspace
- Header: module identity, origin, working-copy status, compatibility, validate/test, open in VS Code, and publish actions.
- Main tabs: `Schema`, `Files`, `Validation`, `References`, and `Versions`.
- `Schema` uses a structured form with a raw YAML toggle; fields expose provenance and confirmation state.
- `Files` provides a lightweight tree, search, Python/YAML/Markdown editing, save, and diff. It deliberately omits debugger, extension marketplace, complex refactors, and full terminal emulation.
- `Validation` shows contract checks, sample/shape/label previews, test results, and actionable failures.
- `References` connects evidence passages and implementation repositories to decisions and code changes.
- `Versions` shows global origin, project Git history, Run usage, and explicit publication workflow.
- The right Agent panel inherits project context plus only the active module's files/contracts/evidence and relevant neighboring interface summaries.
- User selected the single-focus tabbed module workspace (option A) on 2026-09-05. Schema, Files, Validation, References, and Versions occupy the main area one at a time; the module Agent and job drawer remain persistent, while optional raw YAML and VS Code opening preserve direct expert control.

### Experiment Center
- Dense Run table with status, start time, module hashes/versions, dataset/split/protocol, primary metrics, integrity, comparability, device, duration, and tags.
- Run detail tabs: Summary, Configuration, Metrics, Artifacts, Logs, Snapshot/Diff, and Provenance.
- Compare view requires the user to select Runs, then presents the deterministic comparability verdict before metric differences.
- Research Commit creation starts from selected Runs and an editable Agent draft; it is a separate confirmed action.

### Research History
- A compact branch/timeline view shows Research Commits rather than every Run.
- Selecting a node shows hypothesis, evidence, changed modules, included Runs, results, conclusion, limitations, and next action.
- Branch-from-here and restore-module actions create explicit working changes and never overwrite the current workspace silently.

### Global Module Library and Module Studio
- Library filters by data/method/evaluation, modality, task, framework, compatibility capabilities, status, and origin.
- Published versions are immutable. Import creates a project-local working copy with `based_on` provenance.
- Editing a global module opens a derived draft in Module Studio; validation and explicit publication create a new immutable version.
- Publishing a project module shows files, schema, tests, sample artifacts, dependencies, license/provenance, secrets scan, and semantic version change before confirmation.

### Settings
- Model providers and credential references.
- Literature connectors and access status.
- Project execution environments, GPU detection, and default resource limits.
- Agent permission policy and approval history.
- VS Code executable/path settings and ignored file patterns.
- Storage locations and artifact retention; no raw secret values are displayed after entry.

## First Complete User Journey (Confirmed)
1. Create a project in a user-selected local directory and write a Research Brief through project-level conversation.
2. Enter Data, choose/import a module or create one, inspect source samples, separate source facts from preprocessing decisions, confirm semantics, generate code, and validate canonical EEG output.
3. Enter Method, search evidence-backed baselines, select one, import or scaffold the method, edit in AI4SOTA or VS Code, and pass module tests.
4. Enter Evaluation, confirm task ontology, subject-safe split protocol, metrics, statistics, and explainability requirements, then lock the primary protocol.
5. Return to Overview; compile the three contracts, review any mechanical adapter, and resolve every semantic decision or blocker.
6. Open the Run approval review, inspect the exact ExperimentSpec/data/split/environment/module hashes, and confirm execution.
7. Monitor the snapshot-backed Run while optionally continuing work in the live project; view terminal status, logs, metrics, and artifacts.
8. Modify one module and execute a second confirmed Run.
9. Compare the two Runs only after the system states whether the protocols are directly comparable.
10. Promote meaningful Run(s) to a Research Commit with a user-reviewed hypothesis, evidence, result, conclusion, and limitations.
11. Optionally publish the improved project module as a new global-library version after validation and explicit confirmation.

### Version-One UI Scope Guard
- No arbitrary visual DAG construction; only the three scientific modules and generated adapters are shown.
- No full IDE, notebook runtime, cloud collaboration, remote scheduler, autonomous optimization loop, or marketplace.
- No decorative landing experience. Optimize for repeated research work, dense comparison, explicit status, and reversible action.

### Final Visual and Journey Approval
- User approved the visual baseline on 2026-09-05: Obsidian-style pane hierarchy, project tree, tabs, Markdown knowledge view, and backlinks combined with ChatGPT-style light grey-blue shell, white reading surfaces, restrained conversation flow, and a single lightweight composer.
- The default UI must not use a dark IDE shell, broad blue-purple gradients, oversized headings, excessive rounding, decorative whitespace, or card-heavy SaaS dashboard composition.
- User approved the complete first journey on 2026-09-05: Research Brief -> Data -> Method -> Evaluation -> compatibility review -> Run approval -> snapshot-backed execution -> comparable rerun -> Research Commit -> optional module publication.
- The normative design specification is `docs/superpowers/specs/2026-09-05-ai4sota-desktop-agent-design.md`.

## Agent Runtime, Providers, and Security (Confirmed)

### One Engine, Four Conversation Scopes
- Use one Agent runtime with four persistent scopes: project, data, method, and evaluation. Do not implement four unrelated agents or simultaneous autonomous workers in version one.
- The project scope owns the Research Brief, cross-module decisions, compatibility, Run comparison, and Research Commit drafting.
- A module scope receives its module files/schema/tests/references plus read-only summaries of relevant neighboring contracts. Its default write capability is limited to the active module working copy.
- Confirmed decisions are stored as structured `DecisionRecord` objects and summarized into project Markdown; they are not inferred repeatedly from the raw chat transcript.
- Provider conversations are stateless from AI4SOTA's perspective. The application owns canonical message/event history and can switch providers without losing project history.

### Agent Turn Model
1. Reconcile relevant file hashes and build a bounded context snapshot.
2. Send only the required context to the configured model provider, applying outbound-data policy.
3. Receive streamed text and typed tool requests.
4. Validate every tool request against the registry, active scope, current hashes, and permission policy.
5. Execute allowed operations, request approval for gated operations, or deny them with a machine-readable reason.
6. Append tool inputs/results, citations, file changes, and approvals to the local event log.
7. Stop on completion, user interruption, budget limit, conflict, or a required scientific decision.

### Provider-Neutral Interface
- Core capabilities: model discovery/configuration, streaming responses, typed tool calls, structured JSON output, usage accounting, cancellation, and provider error normalization.
- Optional capabilities: vision, PDF/file upload, embeddings, prompt caching, and reasoning metadata. The Agent must degrade explicitly when a selected provider lacks one.
- User confirmed on 2026-09-05: version one implements an OpenAI-compatible HTTP adapter for both hosted APIs and local endpoints such as compatible Ollama/vLLM gateways; provider-specific adapters are added only when capability differences require them.
- Each provider/model profile records endpoint kind, base URL, model ID, opaque credential reference, advertised/tested capabilities, outbound-data policy, timeout/retry limits, and optional cost metadata.
- Configuration runs a capability probe and shows whether streaming, typed tool calls, structured output, vision/files, embeddings, usage reporting, and cancellation actually work. Unsupported features degrade visibly rather than failing mid-turn.
- Do not assume a consumer chat subscription grants API access. Hosted providers use explicit API credentials; local runtimes use a configured loopback endpoint.
- Store secrets in the operating-system credential manager and persist only opaque credential references in application settings. Never write tokens into projects, prompts, logs, exports, or module packages.
- User confirmed on 2026-09-05: the project defines a default provider/model profile and each project/data/method/evaluation conversation may store an explicit override.
- The composer and every recorded Agent turn show the effective provider/model. A request remains bound to that profile for the full turn.
- Provider errors, rate limits, or local-model outages never trigger silent fallback to another provider. The user chooses retry, a different profile, or an explicit one-turn override so privacy and cost boundaries remain predictable.

### Tool Registry
- Files: list/read/search, propose/apply hash-checked patches, inspect diff, and open in VS Code.
- Scientific contracts: validate schemas, inspect samples/metadata, compile compatibility, materialize split manifests, and explain deterministic findings.
- Verification: format, lint, unit test, module smoke test, and validation through registered project-environment commands.
- Literature: search connectors, import sources, extract passages, deduplicate records, and attach evidence to a decision.
- Experiments: prepare an ExperimentSpec and approval summary; only a confirmed `run.start` can enter the job manager.
- History: inspect Runs, compare protocols/results, draft Research Commits, create confirmed commits/branches, and publish confirmed module versions.
- The model never receives unrestricted filesystem, Git, database, shell, credential, or network primitives.

### Default Permission Policy
- `allow`: read/index the current project, inspect Runs, update local conversation state, query enabled public literature metadata connectors, and write the active module working copy with hash checks.
- `allow_registered`: run deterministic schema validation, formatting, linting, and explicitly registered unit/smoke tests in the project environment; every command and result remains visible in the activity log.
- `ask`: start an experiment, run an unregistered command, install/remove dependencies, expand file scope, send selected local data to a hosted model, download/import external code, grant project-code network use, create/switch a Git branch, publish a module, create a Research Commit, or perform bulk/destructive file changes.
- `deny`: read credential values back into prompts, access paths outside approved roots through AI4SOTA tools, modify another module from a scoped module conversation, change confirmed scientific semantics silently, bypass access controls, or overwrite hash-conflicted files.
- Approval records are one-time and bound to normalized arguments, target hashes, scope, provider/tool identity, and expiry. Changing any bound value invalidates approval.
- User confirmed on 2026-09-05: verification is tiered. Schema validation, static checks, and formatting run automatically; registered fast unit/smoke tests may run automatically only for trusted project/module code and remain visible and cancellable.
- A command profile, not the model, declares executable, fixed/validated arguments, working directory, expected duration, CPU/GPU/network needs, and allowed outputs. The model cannot label a new command as safe.
- New or unregistered commands, untrusted imported code, long-running checks, GPU work, network access, environment/dependency changes, and experiment execution always enter the approval path.

### Threat Boundaries
- Prompt injection: papers, webpages, repositories, logs, and datasets are untrusted evidence. Their contents cannot modify system policy, call tools directly, or approve actions.
- Path escape: resolve canonical paths, reject traversal, and treat symlinks/junctions leaving approved roots as out of scope unless explicitly granted.
- Secret leakage: redact credential patterns from logs/diffs, scan module packages before publication, and prevent raw secret retrieval through Agent tools.
- Command injection: use structured executable/argument arrays and command profiles; do not compose shell strings from model output.
- Unsafe artifacts: warn or block untrusted pickle/checkpoint deserialization and record source/checksum/license before use.
- Data exfiltration: raw EEG and identifiable metadata are local by default. Hosted-model requests show or log the outbound scope, and raw samples require explicit approval.
- Arbitrary research code: child-process separation protects the desktop service from crashes and supports cancellation, but it is not an OS sandbox. The UI must state this before first execution and offer stronger container backends later.

### Conversation and Evidence Storage
- Store canonical conversation/tool events locally in an append-only project log or rebuildable project database, with message IDs, scope, provider/model, timestamps, citations, tool calls, approval IDs, and referenced file hashes.
- Export user-confirmed decisions and concise discussion summaries as human-readable Markdown under the project so they survive index/database rebuilding.
- Keep provider-specific response identifiers only as optional provenance. No essential state may exist only on a provider server.
- Context compaction produces versioned summaries linked to the source event range; it never deletes the underlying local record automatically.

### Confirmed Long-Running Job Behavior
- User confirmed option A on 2026-09-05.
- When a Run is active, closing the main window should minimize the application to the system tray rather than terminate the control service and worker.
- Explicit Quit should show active jobs and require the user to choose cancellation or background continuation. Job manifests/logs are persisted so reopening can recover state and reattach where the operating system allows.
- Background continuation means the tray-resident application and Python control service remain alive; version one does not install an independent operating-system daemon/service.
- A process crash or machine reboot leaves an explicit interrupted status and durable logs. Generic automatic training resume is out of scope; a method may later offer a checkpoint-aware user-confirmed resume action.

### Agent Acceptance Scenarios
1. A method-scoped conversation can edit method files but cannot silently write evaluation files.
2. A paper passage containing instructions is stored as untrusted evidence and cannot cause a tool call or permission change.
3. A hosted provider never receives raw EEG samples without a matching outbound-data approval.
4. A stale patch fails before any target file is written.
5. A registered unit test runs and logs automatically; an arbitrary shell command pauses for approval.
6. Switching model providers preserves local conversation, decisions, evidence links, and file history.
7. A worker crash marks the Run failed and leaves the control service and desktop usable.
8. An active Run survives main-window closure according to the selected background policy and is visible after reopening.
9. Hosted and local OpenAI-compatible profiles can be selected without changing project conversation storage or tool contracts.
10. A local model without reliable tool calling remains available for discussion but cannot enter tool-executing Agent mode until its capability check passes.

## Approved Implementation Program (2026-09-05)

- Execution is split into three strictly ordered plans: core/research ledger, local control service/Agent, then Tauri desktop/EEG vertical slice.
- The desktop plan preserves the approved Obsidian pane structure and ChatGPT light surfaces. A UI design-system search was used only for dense-tool, accessibility, React, and chart guidance; its unrelated dark palette recommendation was rejected in favor of the user-approved light tokens.
- Tauri owns the per-launch secret and application-data directory. It passes both once through the packaged control service's stdin, retains the token only in Rust memory, and exposes neither a token nor generic shell primitives to the WebView.
- The public local API is consistently versioned under `/v1`; `/health` and authenticated `/shutdown` remain private process-lifecycle endpoints.
- The checked OpenAPI document generates frontend response types. A closed Rust/TypeScript operation union maps WebView requests to fixed methods and paths.
- Self-review added explicit schema migration preview/backups, SQLite index rebuilding, artifact cleanup tombstones, hosted raw-EEG approval, discussion-only local providers, first-execution sandbox-boundary acknowledgement, and project Git initialization behavior.
- The EEG acceptance slice uses a deterministic small synthetic dataset and must prove Data -> Method -> Evaluation -> two comparable Runs -> exact-snapshot Research Commit -> immutable module publication in the packaged Windows application.
- Implementation has not started. The next decision is execution style: Subagent-Driven (recommended) or Inline with checkpoints.
- Build-host decision: the current computer uses an available Node 24/npm 11 toolchain for Python/control-service/browser-React work; scripts explicitly resolve system npm because Codex's PATH differs from the user's CMD. A separate Windows computer with Node 24 LTS, stable MSVC Rust, Visual Studio Desktop C++ Build Tools, Windows SDK, and WebView2 owns every native Tauri and packaging gate.
- Current-host tool versions reported by the user: `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1 (797e8a9bc 2026-08-05)`, active `stable-x86_64-pc-windows-msvc`, and Node.js `v24.20.0`. This confirms the language toolchains; it does not substitute for the MSVC linker/Windows SDK gate on the release host.
