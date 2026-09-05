# AI4SOTA MVP — Phase 1

这是 AI4SOTA 本地科研算法项目工作台的第一阶段：先用命令行跑通“创建项目 → 验证三层接口 → 运行 → 查看历史”的最小闭环。

## 当前能力

- 生成数据层、方法层、评价层均可直接修改的科研项目。
- 使用统一对象连接三层：`CanonicalDataset`、`PredictionBundle`、`EvaluationResult`。
- 创建内置 `.npz(X, y)` 二分类演示数据。
- 运行纯 NumPy Logistic Regression 基线。
- 保存每次运行的配置、验证报告、指标和日志。
- 通过命令行查看历史实验。

本阶段暂不包含 Git 自动版本、桌面 GUI、任意格式数据适配和 Agent。它们分别属于后续阶段。

## 安装

建议在虚拟环境中运行：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -e .
```

macOS/Linux：

```bash
source .venv/bin/activate
pip install -e .
```

## 5 分钟跑通

在本仓库根目录执行：

```bash
ai4sota new demo --output ./workspaces --demo
ai4sota validate ./workspaces/demo
ai4sota run ./workspaces/demo --note "第一次基线实验"
ai4sota history ./workspaces/demo
```

不安装命令行入口时，也可以使用：

```bash
PYTHONPATH=src python -m ai4sota new demo --output ./workspaces --demo
```

## 使用自己的 NPZ 数据

第一阶段的默认 Adapter 只约定 `.npz` 文件中包含：

- `X`：第一维为样本维度。
- `y`：一维二分类标签，可使用任意两个不同值。
- `split`：可选，一维字符串数组，值为 `train` 或 `test`。未提供时会按配置随机划分。

```bash
ai4sota new my_project --output ./workspaces --data /path/to/data.npz
```

创建后可以直接修改：

- `data/adapter.py`
- `method/model.py`
- `evaluation/evaluator.py`

## 项目结构

```text
demo/
├── project.yaml
├── data/
│   ├── dataset.yaml
│   └── adapter.py
├── method/
│   ├── method.yaml
│   └── model.py
├── evaluation/
│   ├── evaluation.yaml
│   └── evaluator.py
├── configs/default.yaml
├── demo_data/demo.npz
├── runs/
└── pipeline.py
```

## 运行记录

每次运行会在 `runs/<run_id>/` 下保存：

- `run.json`：运行状态、时间、备注和核心摘要。
- `metrics.json`：评价指标。
- `validation.json`：运行前的数据与接口验证结果。
- `logs.txt`：标准输出或错误堆栈。

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

