# AI4SOTA Landscape Research

Date: 2026-09-05

## Conclusion

AI4SOTA is not simply another AutoML tool. Its strongest product definition is:

> A local, researcher-governed AI workspace that turns data, method, and evaluation into independently editable scientific modules, connects them through explicit contracts, and preserves the evidence and reasoning behind every accepted experiment.

No single reviewed project implements this whole idea. The market is split across visual workflow builders, code-first pipeline frameworks, experiment/version systems, autoresearch agents, literature agents, and desktop coding agents. AI4SOTA can be differentiated by joining these categories around scientific authority and provenance rather than by copying every feature from any one platform.

## Closest References

| Project | Relevant overlap | What AI4SOTA should learn | What remains different |
|---|---|---|---|
| [Weco](https://docs.weco.ai/) / [AIDE ML](https://github.com/WecoAI/aideml) | Metric-driven code improvement, solution tree, traceability, human steering | Inspectable branches, mid-run guidance, local execution | Metric-only optimization; no three scientific modules, semantic gates, or paper-to-result lineage |
| [KNIME](https://www.knime.com/knime-analytics-platform) | Desktop visual workflows, reusable components, data connectors, scripting and extensions | Canvas interaction, component packaging, configuration UX, code escape hatches | Generic analytics platform rather than an AI research collaborator |
| [Orange](https://orangedatamining.com/) | Connected widgets and specialized scientific add-ons | Simple visual composition and domain add-on ecosystem | Primarily visual analysis; limited code/research history model |
| [Kedro](https://docs.kedro.org/en/stable/getting-started/kedro_concepts/) | Named inputs/outputs, modular pipelines, Data Catalog, project templates | Contract design, custom datasets, modularity, tests, plugin boundaries | Code framework, not a desktop research agent or scientific ledger |
| [ZenML](https://docs.zenml.io/) | Versioned pipeline artifacts, snapshots, infrastructure abstraction | Separate workflow semantics from execution backends | Production/MLOps focus; less emphasis on interactive scientific reasoning |
| [DVC Experiments](https://dvc.org/doc/user-guide/experiment-management) | Git-related experiment variants, data/model lineage, metric/plot comparison | Do not turn every Run into a normal commit; curate meaningful history | Does not capture hypotheses, evidence, confirmation, or module semantics |
| [MLflow](https://mlflow.org/docs/latest/ml/tracking/) | Runs, parameters, metrics, artifacts, notes, local/remote storage | Metadata store versus artifact store; experiment browsing | Tracking system, not a code workspace or decision-aware research system |
| [ClearML](https://clear.ml/docs/latest/docs/) | Integrated IDE, data/version management, tracking, tuning, pipelines | End-to-end operational coverage and experiment-center UX | Infrastructure/MLOps platform, not researcher-governed method discovery |
| [goose](https://goose-docs.ai/) | Local desktop agent, CLI/API, MCP extensions, recipes, permissions | Agent shell, model-provider abstraction, extension UI and security | General-purpose agent with no scientific domain model |
| [PaperQA2](https://github.com/Future-House/paper-qa) | Citation-grounded scientific document retrieval and synthesis | Evidence-backed method cards and claim-to-source links | Literature component only; no experiment execution or module contracts |
| [The AI Scientist](https://github.com/SakanaAI/AI-Scientist) | Idea generation, autonomous experiments, paper generation | Automation-loop and sandboxing lessons | Full autonomy conflicts with AI4SOTA's core human-authority principle |

## The Defensible Product Boundary

AI4SOTA should make five concepts first-class:

1. **Scientific Module**: data, method, and evaluation modules declare capabilities, inputs, outputs, invariants, provenance, status, and version.
2. **Compatibility Compiler**: verifies contracts, generates only semantics-preserving adapters automatically, and requests confirmation for transformations that alter scientific meaning.
3. **Module Copilot**: each module has its own scoped discussion, evidence, code, diff review, tests, and output preview.
4. **Run Ledger**: every execution records objective facts including code/config snapshots, data fingerprints, environment, logs, metrics, and artifacts.
5. **Research Commit**: a user-curated scientific checkpoint containing hypothesis, evidence, selected Runs, changes, conclusion, limitations, and next step.

The unit of differentiation is not the visual node itself. It is the traceable chain:

```text
paper/evidence -> proposed change -> reviewed patch -> deterministic run
               -> comparable result -> user-confirmed conclusion
```

## Three Possible Development Strategies

### 1. Contract-first vertical slice (recommended)

Stabilize the scientific schemas and complete one narrow end-to-end workflow before investing heavily in UI or autonomous search. The first slice should support CSV/NPZ classification and one time-series example, allow code inspection, and create two comparable Research Commits.

Advantages: validates the unique product idea, keeps the desktop UI thin, and prevents unstable backend semantics from leaking into every screen. Trade-off: the first visual demo arrives slightly later.

### 2. Desktop-first prototype

Build the Tauri/React canvas, module workspaces, editor, chat, and run browser first, while using the current CLI kernel behind it.

Advantages: quickly validates user experience and creates a compelling demo. Trade-off: likely rework when module schemas, permissions, versioning, and agent events change.

### 3. Agent-first autoresearch

Add paper search, code generation, iterative experiments, and metric optimization immediately.

Advantages: produces impressive automated demonstrations. Trade-off: risks becoming a Weco/AIDE-like optimizer before the human-governed scientific foundation exists. This is the least suitable starting point for the stated product values.

## Recommended Next Vertical Slice

Build this exact loop next:

```text
Create project
  -> import CSV or NPZ
  -> scan structure and draft DatasetSpec
  -> researcher confirms label, sample axis, split key, and transformations
  -> generate an editable Source Adapter
  -> validate CanonicalDataset
  -> connect Logistic Regression and classification evaluation modules
  -> compile compatibility report
  -> run and record artifacts
  -> edit one method module and rerun
  -> promote both Runs to Research Commits
  -> compare with an explicit comparability verdict
```

This slice proves all core claims: format tolerance, explicit scientific semantics, editable code, replaceable modules, deterministic execution, human approval, and learnable history. Parameter search and autonomous method improvement should come only after this loop is reliable.

## Capabilities to Reuse Rather Than Rebuild Early

- Git for source snapshots and diffs.
- SQLite plus local artifact directories for the first ledger implementation.
- Pydantic/JSON Schema for contracts and UI form generation.
- Monaco for editing and diff review.
- React Flow for the three-module canvas.
- MCP-style adapters for paper databases and external tools.
- OpenAlex/Semantic Scholar for discovery and metadata; PaperQA-like retrieval for grounded synthesis.
- Existing libraries such as scikit-learn, PyTorch, Optuna, SHAP/Captum, and established statistical packages inside modules.

## Avoid in the First Product Cycle

- A general plugin marketplace.
- Multi-machine scheduling and cluster orchestration.
- Fully autonomous research decisions.
- Supporting every modality before one real workflow is strong.
- Treating every parameter trial as a Git or Research Commit.
- Automatically changing labels, splits, preprocessing, primary metrics, or evaluation protocols.
- Building a custom editor, version-control engine, literature index, or experiment database when mature components already exist.
