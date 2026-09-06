# AI4SOTA v0.1: 真实 EEG CLI 人工试用指南

本文用于人工验证 AI4SOTA v0.1 的核心科研闭环：为一个真实 EEG
分类任务建立 Data、Method、Evaluation 三个模块，运行两次受审批约束的实验，
比较两个不可变 Run，并将选定结果保存为 Research Commit。

这不是模型性能验收。第一次试用应使用少量被试和快速 CPU 基线，重点检查：

- 三个模块的职责是否清楚；
- Schema 是否足以描述真实数据与科研语义；
- 人工审批是否能阻止未确认的代码或配置进入实验；
- Run、比较结果和 Research Commit 是否能支持复盘；
- 哪些步骤不清晰、重复或必须依赖开发者。

## 1. v0.1 当前边界

v0.1 已实现 `compile`、`prepare-run`、`run-approved`、`compare` 和
`research-commit`，但尚未实现桌面向导、Agent 自动生成模块和真实 EEG
数据下载器。因此：

- CLI 可以执行已经准备好的 v1 科研项目；
- Data、Method、Evaluation 的 Schema 和代码目前需要研究者、开发者或 AI
  在项目目录中创建；
- `ai4sota new` 仍是早期简单项目入口，不会自动生成完整的 v1 EEG 模块；
- v0.1 会展示 `adaptable` 兼容性报告，但在机械适配器执行器完成前会阻止
  `prepare-run`。第一次试用应让三个模块的字段、轴、dtype 和输出名称直接一致；
- 没有可复现运行环境身份时，Run 可以保留，但系统会阻止直接比较指标差值。

如果这些限制让试用无法继续，请记录为产品问题，不要通过伪造 Schema、哈希、
指标或数据来绕过。

## 2. 确定真实数据集和任务

首轮验收采用一个固定参考任务，避免把 CLI 问题和科研方案分歧混在一起：

- 数据集：[PhysioNet Sleep-EDF Expanded](https://physionet.org/content/sleep-edfx/1.0.0/)
  的 `sleep-cassette` 子集；
- 数据版本：下载时记录 PhysioNet 页面显示的版本号和文件清单；
- 任务：每个 30 秒 epoch 的五分类睡眠分期；
- 类别：`W=0`、`N1=1`、`N2=2`、`N3=3`、`REM=4`，原始 `N4`
  合并到 `N3`，Movement/Unknown 排除；
- 输入：首轮只用一个明确记录的 EEG 导联，重采样率和单位写入 Schema；
- 划分：按 `subject_id` 做固定种子的 group holdout；
- 指标：Macro-F1 为主指标，Accuracy 为次指标；
- 范围：选择 2-6 名被试，保留被试、recording 和原文件名的映射。

如果已有更熟悉的真实数据，可以替换这个参考任务，但必须先把下面表格逐项写清楚，
并在两次 Run 中保持任务定义不变。

开始写代码前，先在项目 README 或实验记录中确认以下内容：

| 项目 | 必须明确的内容 |
|---|---|
| 数据集 | 名称、版本、来源链接、许可证和本机路径 |
| 研究任务 | 例如情绪三分类、睡眠五分类或运动想象四分类 |
| 样本单位 | trial、epoch、window 或其他明确定义 |
| 标签 | 原始标签、最终类别名称和整数编码 |
| 分组字段 | 通常为 `subject_id`，必要时增加 session 或 recording |
| 输入张量 | 样本级 shape、轴顺序、dtype、单位和采样率 |
| 通道 | 通道名称、选择规则、缺失通道策略和顺序 |
| 预处理 | 滤波、去趋势、重采样、切窗、标准化及其拟合范围 |
| 数据划分 | 被试内或跨被试；第一次建议固定 subject-safe holdout |
| 主指标 | 分类任务建议 Macro-F1；同时记录 Accuracy |

第一次人工试用建议只选择 2-6 名被试，并固定一个任务。不要同时测试跨数据集
联合训练、多任务训练、自动调参或大模型预训练。

### 建议的数据适配格式

原始 EDF、MAT、BDF、CSV 文件应保留不变，作为可追溯来源。**但 v0.1 的强指纹
校验目前要求 `DatasetSourceSpec.locations` 恰好包含一个外部文件**，所以首轮试用
必须先从选定的真实原始数据导出一个可追溯的小型 NPZ，再让 Data 模块读取该 NPZ：

```text
signals      [N, C, T] float32
labels       [N]       int64
sample_ids   [N]       string
subject_ids  [N]       string
```

必须在项目记录中保留原始数据来源、筛选的被试、导出脚本、标签映射、导出命令
和导出文件 SHA-256。小型 NPZ 只是试用缓存，不应被描述成新的原始数据集。
多文件或目录级数据指纹是 v0.1 后续要评估的核心能力，不能通过在 `locations`
中只写一个实际不存在的“代表路径”来绕过。

## 3. 准备 CLI 环境

以下命令在 PowerShell 中执行。先确保虚拟环境存在，再解析其中的可执行文件：

```powershell
Set-Location B:\AI4SOTA
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  py -3.11 -m venv .venv
}
$Python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
& $Python -m pip install -e ".[dev]"
$Cli = (Resolve-Path ".\.venv\Scripts\ai4sota.exe").Path
& $Cli --help
```

如果本机没有 `py -3.11`，将该命令替换为一个实际存在的 Python 3.11 或更高版本
解释器。不要照抄某台机器特有的 Anaconda 路径。

不要把真实 EEG 数据复制到 AI4SOTA 源码仓库。科研项目应放在独立目录，例如：

```powershell
$ProjectRoot = "B:\AI4SOTA-Workspaces\sleep-edf-small"
```

## 4. 建立 v1 项目骨架

使用公开 Python API 创建 v1 目录骨架：

```powershell
& $Python -c "from pathlib import Path; from ai4sota.projects import ProjectLayout; ProjectLayout.create(Path(r'B:\AI4SOTA-Workspaces'), 'sleep-edf-small')"
```

最终项目至少需要以下文件：

```text
sleep-edf-small/
|-- .gitattributes
|-- ai4sota.project.yaml
|-- pyproject.toml
|-- uv.lock
|-- configs/
|   `-- default.yaml
|-- tasks/
|   `-- active.yaml
|-- modules/
|   |-- data/current/
|   |   |-- module.yaml
|   |   |-- dataset.yaml
|   |   |-- preprocessing.yaml
|   |   |-- config.yaml
|   |   `-- adapter.py
|   |-- method/current/
|   |   |-- module.yaml
|   |   |-- config.yaml
|   |   `-- model.py
|   `-- evaluation/current/
|       |-- module.yaml
|       |-- config.yaml
|       |-- evaluator.py
|       `-- metrics.py
|-- data/fingerprints/
|-- runs/
`-- research-commits/
```

`ProjectLayout.create` 只生成 `.gitattributes`、项目清单、未配置的 Task 和基础
目录；它不会生成三个可运行模块、`pyproject.toml` 或 `uv.lock`。其余文件由人工
或 AI 根据本节要求补齐。这项手工工作本身也是本轮可用性测试的一部分。

显式写入整个试用期间保持不变的随机种子：

```powershell
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "configs") | Out-Null
"random_seed: 17" | Set-Content `
  (Join-Path $ProjectRoot "configs\default.yaml") -Encoding utf8
```

v0.1 从 `configs/default.yaml` 读取种子；它不从 Evaluation Schema 读取。未提供时会
默认使用 `17`，但人工验收不应依赖这个隐式默认值。

每个持久化 Schema 都必须包含 `api_version`、`id`、`version` 和规范的
`content_hash`；三类模块还必须包含 `origin`。各模型的完整字段定义可直接查看：

- `src/ai4sota/domain/task.py`
- `src/ai4sota/domain/modules.py`
- `src/ai4sota/domain/projects.py`
- `tests/integration/test_scientific_vertical_slice.py` 中的
  `create_v1_demo_project`

不要手填一个看似合法的假哈希。创建或修改 Schema 时，用下面的辅助函数生成并写入
规范哈希：

```python
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ai4sota.storage import ManifestStore, canonical_manifest_hash


ModelT = TypeVar("ModelT", bound=BaseModel)
ZERO_HASH = "sha256:" + "0" * 64


def write_hashed(path: Path, model: type[ModelT], payload: dict) -> ModelT:
    draft = model.model_validate({**payload, "content_hash": ZERO_HASH})
    value = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(path, value)
    return value
```

所有 payload 至少显式填写 `id`；`api_version: ai4sota/v1` 和 `version: 1.0.0`
可使用模型默认值。按以下顺序生成：

1. 生成并保存 `TaskContract`；
2. 把 TaskContract 的真实 ID 和哈希写入 Data 与 Evaluation；
3. 分别验证并保存 DatasetSource、Preprocessing、Data、Method、Evaluation；
4. 修改任何 Schema 后重新计算该 Schema 的哈希，并重新生成受影响的下游清单。

三个模块的完整必填字段是：

| Schema | 必填内容 |
|---|---|
| `TaskContract` | `id`、`prediction_unit`、`target_type`、`classes`、`required_metadata` |
| `DatasetSourceSpec` | `id`、`name`、单项 `locations`、`sampling_rate_hz`、`metadata_fields`、真实 `fingerprint_hash` |
| `PreprocessingSpec` | `id`、`transforms`、由真实变换定义计算的 `graph_hash` |
| `DataModuleSpec` | `id`、`origin`、`source`、`preprocessing`、`entrypoint`、`canonical_outputs`、Task ID 与哈希 |
| `MethodSpec` | `id`、`origin`、`framework`、`entrypoint`、`input_requirements`、`output_capabilities`、`task_contracts` |
| `EvaluationSpec` | `id`、`origin`、`entrypoint`、Task ID 与哈希、`required_predictions`、`protocol`、`metrics` |

`EvaluationSpec.metrics` 必须恰有一个 `primary: true`；每个 Metric 都要提供
`name` 和 `implementation`。`origin` 首轮使用 `{type: project}`。可将
`tests/integration/test_scientific_vertical_slice.py` 中的 `create_v1_demo_project`
作为字段级参考，但不能把其中的合成数组、二分类标签或演示指标当成真实 EEG 结果。

## 5. 建立 Data 模块

Data 模块需要完成两件事：描述数据事实，并将真实数据加载成
`CanonicalDataset`。

### Schema 最低要求

`dataset.yaml` 至少说明：

- 数据集 ID、名称、真实文件位置和格式；
- 采样率、轴顺序、通道名和单位；
- `sample_id`、`subject_id` 等元数据字段；
- 真实数据文件的 SHA-256；
- 数据来源和许可证。

`preprocessing.yaml` 至少说明：

- 变换顺序和参数；
- 标准化的拟合范围；
- 通道选择、重采样、切窗等科研决策。

`module.yaml` 至少绑定：

- `source: dataset.yaml`；
- `preprocessing: preprocessing.yaml`；
- `entrypoint: adapter:load_dataset`；
- TaskContract ID 和哈希；
- `signal`、`label`、`sample_id`、`subject_id` 等规范输出。

### Python 接口

```python
from pathlib import Path

from ai4sota import CanonicalDataset


def load_dataset(project_dir: Path, config: dict) -> CanonicalDataset:
    # 读取真实数据，执行已经确认的预处理，返回稳定顺序的样本。
    ...
```

返回对象应满足：

```text
sample_ids              每个样本唯一且稳定
inputs["signal"]        [N, C, T] 或 Schema 中明确的其他布局
targets["label"]        与 TaskContract 类别编码一致
metadata["subject_id"]  用于无泄漏划分
```

不要在 Data 模块内部自行生成训练/测试划分；划分由 Evaluation 模块和
SplitManifest 所有。v0.1 在 Data 读取完成后才生成并注入 `metadata["split"]`，
因此需要从训练分区拟合状态的标准化、特征缩放或降维暂时不能在 Data 适配器执行。
首轮可选择不做这类变换，或在 Method 中依据 `metadata["split"]` 只用训练样本拟合
并应用到测试样本，同时把这个职责错位记录到 `manual-test-notes.md`。

## 6. 建立 Method 模块

第一次试用使用快速、可解释的 CPU 基线。可以从通道统计量、频带功率或已经确认的
固定特征开始，再使用线性分类器或小型 NumPy 模型。不要在第一次试用中训练脑电
大模型。

`module.yaml` 至少声明：

- `entrypoint: model:fit_predict`；
- 框架和输入字段，例如 `signal`；
- 支持的 TaskContract；
- 输出字段，例如 `label` 或 `probabilities`；
- 训练配置和检查点策略。

```python
from ai4sota import PredictionBundle


def fit_predict(dataset, config) -> PredictionBundle:
    # dataset.metadata["split"] 包含 train/test 分区。
    # 只用 train 拟合，但为评价所需样本生成预测。
    ...
```

把本次要改变的参数放进 `modules/method/current/config.yaml`。第一次建议只选择一个
参数，例如 `regularization: 1.0` 或 `learning_rate: 0.01`。

## 7. 建立 Evaluation 模块

Evaluation 模块拥有数据划分、指标和结果解释。第一次试用建议：

- `protocol.kind: group_holdout`；
- `protocol.group_by: subject_id`；
- 固定 `test_fraction` 和随机种子；
- Macro-F1 为主指标，Accuracy 为次指标；
- 只在 `metadata["split"] == "test"` 的样本上计算结果。

五分类 Macro-F1 必须始终按固定类别列表 `[0, 1, 2, 3, 4]` 计算，并明确未定义分数
策略，例如 `zero_division=0`。第一次 Run 前输出每个类别在 train/test 的样本数；
如果任一类别在任一分区为 0，增加被试或调整预先声明的划分方案后重新准备试用，
不要在看到结果后静默改变类别集合。

`module.yaml` 的入口示例为 `evaluator:evaluate`：

```python
from ai4sota import EvaluationResult


def evaluate(dataset, predictions, config) -> EvaluationResult:
    # 根据固定 SplitManifest 选择测试样本并计算真实指标。
    ...
```

Data 输出、Method 输入、Method 输出和 Evaluation 要求必须使用一致的字段名、轴、
dtype 和类别语义。v0.1 不会执行 `adaptable` 报告中的机械适配器。

## 8. 固定环境并初始化项目 Git

直接比较要求运行环境可复现。先在项目的 `pyproject.toml` 中声明模块实际导入的依赖。
一个只使用 NumPy 和 scikit-learn 的最小示例如下，版本范围应按本次真实环境确认：

```toml
[project]
name = "sleep-edf-small"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "numpy>=2,<3",
  "scikit-learn>=1.5,<2",
]

[tool.uv]
package = false
```

用已安装的 `uv` 生成锁文件并同步项目专用环境；`uv lock` 本身不会安装依赖：

```powershell
uv lock --project $ProjectRoot
uv sync --project $ProjectRoot --no-install-project

$RuntimePython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
uv pip install --python $RuntimePython -e B:\AI4SOTA
$Cli = Join-Path $ProjectRoot ".venv\Scripts\ai4sota.exe"
& $Cli --help
```

从这里开始，后续命令使用项目环境中的新 `$Cli`。先执行下面的导入检查；使用 MNE
等其他库时也加入检查：

```powershell
& $RuntimePython -c "import numpy, sklearn"
```

两次 Run 期间不要更新解释器、安装包、`pyproject.toml` 或 `uv.lock`。v0.1 当前只
确认 `uv.lock` 存在且非空，并把它与实际 Python/已安装包清单一起冻结；尚不解析锁
文件来证明环境可重建。没有有效环境身份时，比较会保守返回 `not_comparable`。
若本机没有 `uv`，请先记录为环境前置问题并安装它，不要手写假的 `uv.lock`。

在第一次 Run 前初始化项目自己的 Git 历史：

```powershell
git -C $ProjectRoot init -b main
git -C $ProjectRoot config user.name "EEG Researcher"
git -C $ProjectRoot config user.email "researcher@example.invalid"
git -C $ProjectRoot add .
git -C $ProjectRoot commit -m "chore: initialize EEG trial"
```

AI4SOTA 不会在运行或创建 Research Commit 时隐式初始化 Git，也不会暂存实时项目。
本机 Git 还必须支持 `git worktree`；Research Commit 会用它从 Run 快照构造独立树。

## 9. 编译兼容性

```powershell
& $Cli compile $ProjectRoot --json |
  Tee-Object -FilePath (Join-Path $ProjectRoot ".ai4sota\compile-001.json")
```

继续前人工检查：

- 状态必须是 `compatible`；
- TaskContract ID 和哈希一致；
- Evaluation 的 `group_by` 在 Data 元数据中存在；
- Method 输出满足 Evaluation 的 required predictions；
- 没有为了让代码运行而静默改变标签、数据划分或预处理。

若状态为 `adaptable`、`requires_decision` 或 `incompatible`，停止并修改模块，
不要直接执行。`prepare-run` 只接受 `compatible`。

## 10. 执行第一次快速基线

准备审批候选：

```powershell
$ApprovalOne = Join-Path $ProjectRoot ".ai4sota\approval-run-001.json"
$CandidateOne = & $Cli prepare-run $ProjectRoot `
  --approval-id "approval/eeg-baseline-001" `
  --output $ApprovalOne `
  --json | ConvertFrom-Json

Get-Content -Raw $ApprovalOne
$CandidateOne.approval_hash
```

人工检查审批文件中的：

- 项目和三个模块哈希；
- 数据指纹、SplitManifest 和随机种子；
- 完整输入文件哈希；
- 训练参数、评价协议和运行环境；
- 是否只包含本次确认的代码与配置。

确认后执行，必须原样回传审批哈希：

```powershell
$RunOne = & $Cli run-approved $ProjectRoot $ApprovalOne `
  --approval-hash $CandidateOne.approval_hash `
  --json | ConvertFrom-Json

$RunOne | ConvertTo-Json -Depth 20 |
  Set-Content (Join-Path $ProjectRoot ".ai4sota\run-001-result.json") -Encoding utf8
$RunOne.id
```

检查对应目录：

```text
runs/<RunOne.id>/manifest.yaml
runs/<RunOne.id>/snapshot/
runs/<RunOne.id>/logs/worker.log
```

Run 应为终态，快照不应随实时工作区修改而变化。

## 11. 修改一个明确参数并执行第二次实验

只修改 `modules/method/current/config.yaml` 中预先选定的一个参数。不要同时改变
数据、划分、评价指标或多个模型参数。记录修改理由，例如：

```text
假设：降低正则强度可能提高小样本训练集的拟合能力。
唯一变化：regularization 1.0 -> 0.5。
```

重新编译、准备并审批。旧审批不能用于修改后的输入：

```powershell
& $Cli compile $ProjectRoot --json

$ApprovalTwo = Join-Path $ProjectRoot ".ai4sota\approval-run-002.json"
$CandidateTwo = & $Cli prepare-run $ProjectRoot `
  --approval-id "approval/eeg-baseline-002" `
  --output $ApprovalTwo `
  --json | ConvertFrom-Json

Get-Content -Raw $ApprovalTwo

$RunTwo = & $Cli run-approved $ProjectRoot $ApprovalTwo `
  --approval-hash $CandidateTwo.approval_hash `
  --json | ConvertFrom-Json

$RunTwo | ConvertTo-Json -Depth 20 |
  Set-Content (Join-Path $ProjectRoot ".ai4sota\run-002-result.json") -Encoding utf8
```

确认 `$RunOne.id` 和 `$RunTwo.id` 不同，两个 `snapshot` 目录均存在，且第一个 Run
中的 Method 配置仍是修改前的值。

## 12. 比较两个不可变 Run

```powershell
$ComparisonPath = Join-Path $ProjectRoot ".ai4sota\comparison-001.json"
& $Cli compare $ProjectRoot $RunOne.id $RunTwo.id --json |
  Tee-Object -FilePath $ComparisonPath
```

检查：

- `state` 是否为 `directly_comparable`；
- 是否只有 Method 参数变化；
- 数据指纹、任务、划分、评价协议和指标实现是否保持一致；
- `blocking_fields` 和 `caveat_fields` 是否符合预期；
- 只有直接可比较时才解释指标差值。

`directly_comparable` 只表示 Run 清单中的科研阻断字段一致，不表示系统已经证明
“唯一变化就是一个 Method 参数”。另外显式比较两个冻结模块目录：

```powershell
$SnapshotOne = Join-Path $ProjectRoot "runs\$($RunOne.id)\snapshot"
$SnapshotTwo = Join-Path $ProjectRoot "runs\$($RunTwo.id)\snapshot"

git diff --no-index -- `
  (Join-Path $SnapshotOne "modules\method\current") `
  (Join-Path $SnapshotTwo "modules\method\current")
if ($LASTEXITCODE -notin 0, 1) { throw "配置比较失败，退出码：$LASTEXITCODE" }

git diff --no-index -- `
  (Join-Path $SnapshotOne "modules\data\current") `
  (Join-Path $SnapshotTwo "modules\data\current")
if ($LASTEXITCODE -ne 0) { throw "两次 Run 的 Data 模块不一致" }

git diff --no-index -- `
  (Join-Path $SnapshotOne "modules\evaluation\current") `
  (Join-Path $SnapshotTwo "modules\evaluation\current")
if ($LASTEXITCODE -ne 0) { throw "两次 Run 的 Evaluation 模块不一致" }
```

Method diff 预期只能出现预先声明的一个参数；`git diff --no-index` 在发现差异时
返回 1，这是正常结果。Data 和 Evaluation 的命令必须返回 0，表示没有差异。

若结果为 `not_comparable`，先阅读 `blocking_fields`。不要手工删除阻断字段或修改
旧 Run。如果原因不清楚，将其记录为 CLI 可用性问题。

## 13. 创建 Research Commit

先写一份最小研究结论草稿：

```powershell
$Draft = Join-Path $ProjectRoot ".ai4sota\research-commit-001.json"
@{
  id = "research-commit-eeg-001"
  project_id = $RunTwo.project_id
} | ConvertTo-Json | Set-Content -Path $Draft -Encoding utf8
```

从选定 Run 的精确快照创建 Research Commit：

```powershell
$ResearchCommit = & $Cli research-commit $ProjectRoot `
  $Draft $RunTwo.id --json | ConvertFrom-Json

$ResearchCommit | ConvertTo-Json -Depth 20 |
  Set-Content (Join-Path $ProjectRoot ".ai4sota\research-commit-result.json") `
  -Encoding utf8

$ResearchCommit.git_sha
git -C $ProjectRoot show --stat $ResearchCommit.git_sha
```

验证：

- `research-commits/research-commit-eeg-001/manifest.yaml` 存在；
- Git SHA 可以解析；
- Commit 树来自第二个 Run 的快照；
- 实时项目中的未提交修改没有被覆盖或自动暂存。

## 14. 记录人工测试问题

在项目根目录创建 `manual-test-notes.md`，每遇到一个问题立即记录：

```markdown
## ISSUE-001

- 时间：
- 所在步骤：
- 执行命令：
- 预期结果：
- 实际结果：
- 是否阻断：是/否
- 错误原文：
- 相关文件或 Run ID：
- 临时解决方法：
- 希望软件如何改进：
```

重点记录：

- 哪些 Schema 字段难以理解或无法表达真实 EEG 语义；
- 哪些哈希、路径或 Git 操作必须依赖开发者；
- 错误是否指出了具体文件和修复方法；
- 审批文件是否便于人工阅读；
- 日志能否解释失败原因；
- 两个 Run 的差异和不可比原因是否清楚；
- 哪些步骤最需要未来桌面 Agent、表单或向导支持。

## 15. 人工试用通过标准

一次试用只有同时满足以下条件才算通过：

- 使用的是真实 EEG 数据的小型子集，并有来源与指纹记录；
- Data、Method、Evaluation 和 TaskContract 均可被系统验证；
- 数据划分没有被试泄漏；
- 两次 Run 都保存了独立、不可变的代码与配置快照；
- 第二次实验只修改了一个预先声明的 Method 参数；
- 系统正确判断两个 Run 是否可以直接比较；
- Research Commit 的 Git 树与选定 Run 快照一致；
- 失败、疑问和不便之处都记录在 `manual-test-notes.md`；
- 没有通过修改旧 Run、伪造哈希或绕过审批来完成流程。

完成后，不要立刻开始桌面端开发。先整理人工测试问题，区分：

1. 核心科研契约错误，必须在 v0.1 修复；
2. CLI 可用性问题，可在 v0.1.x 改善；
3. 需要桌面 Agent、表单或可视化才能解决的问题，进入后续控制服务与桌面计划。
