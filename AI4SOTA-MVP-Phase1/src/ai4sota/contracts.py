# -*- coding: utf-8 -*-
"""AI4SOTA 三层架构的"契约"（contracts）定义。

这里的三个 dataclass 是数据层、方法层、评价层之间唯一的交接格式：
  CanonicalDataset  数据层 -> 方法层
  PredictionBundle  方法层 -> 评价层
  EvaluationResult  评价层 -> 运行器（存档）

每个类都自带 validate() 方法，能在层与层交接时自动检查格式是否正确，
避免错误数据在流水线里一路传递、直到最后才暴露。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class CanonicalDataset:
    """数据层(adapter)与方法层(model)之间的稳定交接格式。

    之所以用 dict 来存 inputs / targets，是为了以后支持 EEG、图像、多模态等
    输入，而不用把所有数据都硬塞进单一的 X/y 张量。
    """

    # 样本 ID：一维数组，每个样本一个唯一标识
    sample_ids: np.ndarray
    # 输入数据：字典 {输入名: 数组}，例如 {"features": X}
    inputs: dict[str, np.ndarray]
    # 目标/标签：字典 {目标名: 数组}，例如 {"label": y}
    targets: dict[str, np.ndarray]
    # 元数据：如 train/test 划分(split)、样本属性等，同样以样本为 0 轴
    metadata: dict[str, np.ndarray] = field(default_factory=dict)
    # 额外说明信息(如任务类型、轴含义)，不参与计算
    schema: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> dict[str, Any]:
        """校验数据集是否合法，并返回一份摘要报告。"""
        # --- 1) 校验 sample_ids：必须是一维、非空、且不重复 ---
        sample_ids = np.asarray(self.sample_ids)
        if sample_ids.ndim != 1:
            raise ValueError("sample_ids must be a one-dimensional array")
        if len(sample_ids) == 0:
            raise ValueError("dataset must contain at least one sample")
        # ID 转成字符串后去重：数量必须和原长度一致，否则说明有重复
        if len(np.unique(sample_ids.astype(str))) != len(sample_ids):
            raise ValueError("sample_ids must be unique")

        # --- 2) inputs / targets 至少各有一个 ---
        if not self.inputs:
            raise ValueError("inputs must contain at least one named input")
        if not self.targets:
            raise ValueError("targets must contain at least one named target")

        # --- 3) 检查 inputs/targets/metadata 里每个数组的样本数 ---
        groups = {
            "inputs": self.inputs,
            "targets": self.targets,
            "metadata": self.metadata,
        }
        shapes: dict[str, dict[str, list[int]]] = {}
        for group_name, values in groups.items():
            shapes[group_name] = {}
            for name, value in values.items():
                array = np.asarray(value)
                # 数组必须是非标量，且第 0 维(样本轴)长度 == 样本数
                if array.ndim == 0 or len(array) != len(sample_ids):
                    raise ValueError(
                        f"{group_name}.{name} must use sample axis 0 and contain "
                        f"{len(sample_ids)} samples; got shape {array.shape}"
                    )
                shapes[group_name][name] = list(array.shape)

        # --- 4) 返回摘要报告：样本数、各数组形状、schema ---
        return {
            "sample_count": int(len(sample_ids)),
            "shapes": shapes,
            "schema": self.schema,
        }


@dataclass
class PredictionBundle:
    """方法层(model)产出的预测结果，交给评价层(evaluator)使用。"""

    # 预测对应的样本 ID，应与数据集 sample_ids 对齐
    sample_ids: np.ndarray
    # 预测输出：如 {"label": 预测类别, "positive_probability": 概率}
    outputs: dict[str, np.ndarray]
    # 其他信息，如类别列表 classes
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> dict[str, Any]:
        """校验预测结果格式，返回摘要。"""
        sample_ids = np.asarray(self.sample_ids)
        if sample_ids.ndim != 1 or len(sample_ids) == 0:
            raise ValueError("prediction sample_ids must be a non-empty 1D array")
        if not self.outputs:
            raise ValueError("prediction outputs must not be empty")
        shapes: dict[str, list[int]] = {}
        for name, value in self.outputs.items():
            array = np.asarray(value)
            # 每个输出数组的第 0 维长度必须等于样本数
            if array.ndim == 0 or len(array) != len(sample_ids):
                raise ValueError(
                    f"outputs.{name} must contain {len(sample_ids)} samples; "
                    f"got shape {array.shape}"
                )
            shapes[name] = list(array.shape)
        return {"sample_count": int(len(sample_ids)), "shapes": shapes}


@dataclass
class EvaluationResult:
    """评价层(evaluator)产出的机器可读结果，交给运行器存档。"""

    # 核心指标：如 {"accuracy": 0.9, "macro_f1": 0.88}
    metrics: dict[str, float]
    # 表格类结果：如混淆矩阵、每类 F1
    tables: dict[str, Any] = field(default_factory=dict)
    # 产物文件路径：如保存的图表
    artifacts: dict[str, str] = field(default_factory=dict)
    # 警告信息列表
    warnings: list[str] = field(default_factory=list)

    def validate(self) -> dict[str, Any]:
        """校验指标并做规范化：非空、且每个值都是有限数值。"""
        if not self.metrics:
            raise ValueError("evaluation metrics must not be empty")
        normalized: dict[str, float] = {}
        for name, value in self.metrics.items():
            number = float(value)
            # 拒绝 NaN / 正负无穷
            if not np.isfinite(number):
                raise ValueError(f"metric {name!r} is not finite: {number}")
            normalized[name] = number
        # 把规范化后的指标写回，统一类型为 float
        self.metrics = normalized
        return {"metric_names": sorted(normalized), "warning_count": len(self.warnings)}
