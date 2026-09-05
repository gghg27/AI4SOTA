# Generated AI4SOTA Project

这是一个三层可编辑实验项目：

- `data/adapter.py`：读取原始数据并返回 `CanonicalDataset`。
- `method/model.py`：训练或运行方法并返回 `PredictionBundle`。
- `evaluation/evaluator.py`：计算指标并返回 `EvaluationResult`。

运行：

```bash
ai4sota validate .
ai4sota run . --note "实验说明"
ai4sota history .
```
