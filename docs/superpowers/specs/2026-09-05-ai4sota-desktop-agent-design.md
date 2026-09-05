# AI4SOTA 桌面科研 Agent 设计规格

- 日期：2026-09-05
- 状态：用户已审阅并批准，进入实施计划执行阶段
- 产品阶段：桌面版 v1
- 现有基础：`AI4SOTA-MVP-Phase1` Python 最小内核

## 1. 产品定义

AI4SOTA 是一个本地优先、由研究者掌握科研决策权的桌面科研工作台。它把一次算法研究拆为 Data、Method、Evaluation 三类可替换模块，通过显式 Schema 和确定性兼容性规则连接，并使用 Agent 协助资料检索、方案讨论、代码搭建、修改、验证和结果整理。

AI4SOTA 不是自主 AutoML。模型不得自行改变研究问题、标签语义、数据划分、预处理含义、主指标或科研结论。AI 负责扩大研究者的信息和执行能力，研究者负责确认所有改变科研含义的决策。

产品的核心可追踪链路是：

```text
论文或本地证据
  -> 候选方案
  -> 用户确认的科研决策
  -> 可审查的代码补丁
  -> 确定性验证
  -> 用户批准的 Run
  -> 可比性判定
  -> 用户确认的 Research Commit
```

## 2. 设计原则

1. **人拥有科研决定权**：AI 可以建议和执行，不可替代研究者确认语义与结论。
2. **三模块是唯一插件类型**：Data、Method、Evaluation 保持独立；`TaskContract` 是项目级共享契约，不是第四种插件。
3. **本地文件是事实来源**：项目可被普通编辑器、脚本和 Git 直接理解，不依赖应用数据库才能恢复。
4. **运行与工作区隔离**：Run 从不可变快照执行；运行期间的编辑只影响后续 Run。
5. **比较先于结论**：系统先确定实验是否可比，再允许计算差值或生成“提升”表述。
6. **显式发布而非隐式同步**：全局模块导入项目后成为可编辑副本；只有用户确认发布才产生新的不可变全局版本。
7. **可恢复而非隐藏自动化**：每个工具调用、补丁、验证、审批、Run 和结论都留下本地记录。
8. **轻量编辑器而非重造 IDE**：AI4SOTA 支持必要的 Schema、Python、YAML、Markdown、搜索、保存和 Diff；复杂开发使用 VS Code。

## 3. v1 范围

### 3.1 必须实现

- Windows 优先的 Tauri 2 桌面应用，架构保留 macOS/Linux 可移植性。
- React + TypeScript 科研工作台界面。
- 打包的 FastAPI 本地控制服务与独立 Python Worker。
- 一个项目由一个 Data、一个 Method、一个 Evaluation 和一个活动 `TaskContract` 组成。
- 项目级、Data、Method、Evaluation 四种持久化对话作用域，共用一个 Agent 引擎。
- 项目本地可编辑模块、纯本地全局模块库和显式发布流程。
- 托管 API 与本地 OpenAI-compatible 端点。
- OpenAlex、Europe PMC、本地文献导入，以及可选 Semantic Scholar API Key。
- Schema 表单、轻量文件编辑、VS Code 打开、外部修改检测和哈希冲突保护。
- 分级自动验证、兼容性编译、Run 审批、后台运行、Run 比较和 Research Commit。
- EEG 优先的时序分类契约，同时保留通用模态扩展点。

### 3.2 明确不实现

- 联合多数据集或多任务训练。
- 通用 DAG 编辑器或任意节点工作流。
- 完整 IDE、调试器、LSP 平台、扩展市场、Notebook 内核或完整终端模拟。
- 无人监督的自动调参循环。
- 远程集群调度、云协作、团队权限和模块市场。
- Zotero、出版社账号或机构账号自动登录。
- 对任意 Python 代码提供强 OS 沙箱的承诺。
- 通用自动断点续训。

## 4. 核心领域模型

### 4.1 Project

Project 是一个自包含的本地研究目录，包含研究目标、三个模块、任务契约、讨论、决策、Run、Research Commit、参考资料和可重建索引。用户决定项目位置，AI4SOTA 不维护另一份需要双向同步的副本。

### 4.2 Module

Module 只能属于以下类型之一：

- `data`：读取原始数据、执行已确认预处理并产出规范数据对象。
- `method`：定义模型、目标函数、训练、推理和可供评价或解释的输出。
- `evaluation`：定义数据划分、指标、统计、可解释性和报告输出。

每个模块包含 Schema、代码、配置、测试、文献证据、确认决策和来源信息。项目中的模块始终是普通可编辑文件。

### 4.3 TaskContract

`TaskContract` 统一定义：

- 预测单位；
- 目标类型；
- 类别本体和编码；
- 未知或缺失标签策略；
- 模型输出语义；
- 指标聚合单位；
- 必需的样本、被试、会话或试次标识。

三个模块引用同一个 `TaskContract`。仅有 `classification` 或 `emotion` 等名称相同不足以证明兼容。

### 4.4 DecisionRecord

任何改变科研含义的选择都保存为结构化 `DecisionRecord`，至少包含：

- 唯一 ID、作用域和时间；
- 待解决问题；
- 候选方案及权衡；
- 引用的证据；
- 用户选择与确认者；
- 受影响的 Schema、文件和测试；
- 确认时的内容哈希；
- 被替代关系。

对话记录不能替代 `DecisionRecord`。项目同时生成便于阅读的 Markdown 摘要。

### 4.5 ExperimentSpec

`ExperimentSpec` 是一次待执行实验的不可变组合，包含：

- 三个模块的精确内容哈希；
- 活动 `TaskContract` 哈希；
- 数据指纹；
- `SplitManifest`；
- 生成的机械适配器及哈希；
- 训练与评价配置；
- 随机种子；
- Python 环境和设备信息；
- 资源与网络策略；
- 审批记录。

### 4.6 Run 与 Research Commit

- `Workspace Change` 是仍可编辑、尚未形成科研结论的工作区变化。
- `Run` 是追加式客观执行记录，不自动创建 Git commit。
- `Research Commit` 是用户从一个或多个合格 Run 提升出的正式科研节点，对应真实 Git commit 和结构化 Manifest。

## 5. Schema 系统

### 5.1 共同约定

所有 Schema 使用版本化 Pydantic 模型，并导出 JSON Schema 驱动桌面表单。每个 Schema 文件必须包含：

```yaml
api_version: ai4sota/v1
kind: data_module
id: data/seed
version: 1.0.0
origin:
  type: project
  based_on: data/seed@0.4.0
  remote_source: null
```

`remote_source` 在 v1 只保存可选来源元数据，不执行远程同步。未知字段默认拒绝，Schema 迁移必须显式、可预览并保留原文件备份或 Git diff。

### 5.2 Data 卡片

界面显示一个 Data 卡片，持久化分为三个变化频率不同的 Schema：

1. `DatasetSourceSpec`：数据身份、许可、文件组织、字段位置、轴、单位、采样率和可用标识。
2. `PreprocessingSpec`：去趋势、滤波、重采样、标准化、通道选择、切窗、缺失处理和拟合状态作用域。
3. `DataModuleSpec`：绑定来源与预处理，声明入口点、任务映射、规范输出和验证命令。

数据层统一程序访问协议，而非强迫所有数据转换成相同物理格式。核心输出为：

```python
CanonicalDataset(
    sample_ids=...,
    inputs={"signal": ...},
    targets={"label": ...},
    metadata={
        "subject_id": ...,
        "session_id": ...,
        "trial_id": ...,
        "channel_names": ...,
        "sampling_rate_hz": ...,
    },
    schema=...,
)
```

原始文件到模型输入分两级：

```text
raw files -> Source Adapter -> CanonicalDataset
          -> Model Input Adapter / Collator -> model batch
```

Data 可以声明可供划分的标识，但不得拥有随机划分或交叉验证协议。

### 5.3 Method 卡片

`MethodSpec` 至少声明：

- 框架和入口点；
- 输入布局、dtype、长度、通道和必需元数据；
- Backbone、Head、Loss、Optimizer 和训练配方；
- logits、probabilities、embeddings、attention 等输出能力；
- checkpoint 保存与加载策略；
- 注册的格式化、单元和 Smoke Test 命令；
- 可选搜索空间，但 v1 不自动执行参数搜索。

### 5.4 Evaluation 卡片

`EvaluationSpec` 至少声明：

- `TaskContract` 引用；
- 评价所需预测与元数据；
- 主指标和辅助指标；
- 被试安全的数据划分或交叉验证协议；
- 随机种子、重复和聚合规则；
- 置信区间与显著性检验；
- 可解释性方法及其能力要求；
- 输出文件。

评价模块编译并拥有 `SplitManifest`。Manifest 必须记录每个 sample ID 的精确分区或 Fold 成员关系，并随 Run 冻结。

## 6. 兼容性编译器

兼容性编译器是确定性领域服务，不调用 LLM 作最终判断。它读取三个模块、`TaskContract` 和版本化规则，输出字段级报告、Contract Hash 和以下四种状态之一：

- `compatible`：表示和语义要求直接匹配。
- `adaptable`：仅需白名单中的机械适配，可生成并展示适配器。
- `requires_decision`：涉及采样、通道、标签、缺失、切窗或其他科研语义，必须由用户决定。
- `incompatible`：缺少无法机械补足的字段或能力，禁止运行。

v1 机械适配白名单只允许：

- 明确轴语义后的转置；
- Batch 维添加；
- 安全 dtype 转换；
- 已声明可变长度的 padding 与 mask collator；
- 字段重命名或结构封装，但不改变值语义。

改变采样率、通道集合、标签、样本成员、归一化拟合范围或评价协议不得被归为机械适配。存在任何未解决 `requires_decision` 或 `incompatible` 时，Run 按钮保持禁用。

## 7. 本地模块库与发布

### 7.1 存储模型

- 全局模块库存放在 Tauri `app_data_dir()/ai4sota/library`，允许用户在设置中迁移到其他本地目录。
- 项目只引用导入时的来源 ID 和版本，不运行全局目录中的可变代码。
- 导入模块会复制为项目内工作副本，并写入 `origin.based_on`。
- 已发布全局版本不可修改。
- “编辑全局模块”会创建派生草稿，验证和确认后发布新版本。

### 7.2 发布门禁

发布前必须展示并检查：

- 文件与 Schema diff；
- Schema 兼容性；
- 注册测试和示例产物；
- 依赖与许可证；
- 文献与代码来源；
- 密钥和敏感路径扫描；
- 语义版本变化。

发布需要一次显式确认，且确认绑定内容哈希。发布过程中内容变化会使确认失效。

## 8. 桌面信息架构

### 8.1 固定工作台

桌面应用采用五区固定结构：

1. 48 px 全局活动栏：Home、Projects、Global Library、Search、Settings。
2. 默认 230 px、可在 180-320 px 调整的项目导航：Overview、Data、Method、Evaluation、Experiments、Research History、References。
3. 可伸缩中央科研工作区。
4. 默认 340 px、可在 300-480 px 调整的右侧 Agent。
5. 底部任务栏：折叠时 28 px，展开后显示 180-360 px 的验证、测试、Run 和日志抽屉。

导航过程中五个区域位置保持稳定。窄窗口先折叠 Agent，再折叠项目导航；中央科研对象始终优先。

### 8.2 视觉基线

正式默认主题为“Obsidian 骨架 + ChatGPT 浅色表面”：

- 全局外壳与项目导航使用浅灰蓝中性色；
- 中央阅读和编辑面为纯白；
- Agent 使用接近白色的独立连续表面；
- 主要层级依赖 1 px 分隔线、对齐和字重，不依赖阴影或卡片；
- 主操作使用近黑色；
- 紫色只用于键盘焦点、选中态和 Agent 小范围状态；
- Data、Method、Evaluation 分别使用低饱和暖棕、青绿和灰紫的小型标记，颜色不是唯一状态信号；
- 禁止大面积蓝紫渐变、装饰性光斑、巨大标题、过度圆角和页面级卡片堆叠；
- 普通控件圆角 4-6 px，Agent 输入框可使用 8-10 px，模态和弹出层不超过 8 px；
- 工具栏和表格行高 28-36 px，正文默认 13-14 px，页面标题 16-20 px；
- 数值、哈希、Run ID 和路径使用等宽字体或 tabular figures；
- 使用统一的 Lucide 图标集，不用 Emoji 充当结构图标。

主要浅色 Token：

| Token | 值 | 用途 |
|---|---:|---|
| `shell` | `#EDF2F7` | 应用外壳和底部状态区 |
| `rail` | `#F6F8FA` | 全局活动栏 |
| `sidebar` | `#EEF2F6` | 项目导航 |
| `canvas` | `#FFFFFF` | 中央科研工作区 |
| `agent` | `#FBFBFC` | Agent 表面 |
| `line` | `#E1E4E8` | 普通分隔线 |
| `text` | `#25272B` | 主文本 |
| `muted` | `#858B93` | 辅助文本 |
| `accent` | `#6F5CC3` | 焦点和 Agent 状态 |
| `primary` | `#2F3033` | 主要操作 |

这些 Token 是方向基线，实施时必须通过对比度测试后允许小幅调整，不得把界面改为紫色主导。

### 8.3 首页与项目总览

首页直接提供最近项目、活动 Run、模块更新、新建和打开操作，不显示营销 Hero。

项目总览只显示 Data -> Method -> Evaluation 三个主模块和生成适配器。模块块展示身份、来源版本、工作区修改、验证和兼容性。连接线表达 Contract 状态，不提供任意 DAG 绘制。页面同时展示 Research Brief、阻塞决策、最近 Run 和当前 Research Commit 分支。

### 8.4 模块工作区

模块工作区顶部显示模块身份、来源、工作副本状态、兼容性、验证、VS Code 和发布操作。中央一次只显示一个标签：

- `Schema`：结构化表单、字段来源和确认状态，可切换 Raw YAML。
- `Files`：轻量文件树、搜索、Python/YAML/Markdown 编辑、保存和 Diff。
- `Validation`：契约检查、shape、标签、样本预览、测试和可恢复错误。
- `References`：证据片段、论文、实现仓库以及它们与决策和代码的关系。
- `Versions`：全局来源、Git 历史、Run 使用情况和发布流程。

右侧 Agent 和底部任务抽屉在标签切换时保持可见。

### 8.5 实验与知识视图

实验中心默认是可排序、可筛选的密集表格。选择 Run 后显示 Summary、Configuration、Metrics、Artifacts、Logs、Snapshot/Diff 和 Provenance。图表是表格的补充，必须有可访问的数据表替代。

Research History 只以紧凑分支/时间线展示 Research Commit，不把所有调试 Run 混入主历史。Knowledge 视图使用 Obsidian 式 Markdown 阅读、证据链接和 Backlinks，把决策、论文、Run 和代码关联起来。

## 9. Agent 运行时

### 9.1 一个引擎、四个作用域

v1 只有一个 Agent Runtime，并保存四种会话作用域：

- `project`：Research Brief、跨模块决策、兼容性、Run 比较和 Research Commit。
- `data`：数据 Schema、代码、验证和相关证据。
- `method`：方法代码、基线、训练和相关证据。
- `evaluation`：划分、指标、统计、解释和相关证据。

模块 Agent 可读取相邻模块的契约摘要，但默认只能写当前模块工作副本。跨作用域写入必须产生新的审批请求。

### 9.2 Agent Turn

每轮 Agent 必须按以下顺序执行：

1. 重新读取相关文件并核对哈希。
2. 构造最小必要上下文并应用外发数据策略。
3. 绑定本轮 Provider 和模型。
4. 接收流式文本和类型化工具请求。
5. 工具注册表检查作用域、参数、路径、哈希和权限。
6. 执行允许操作、请求审批或返回拒绝原因。
7. 将消息、工具参数、结果、引用、补丁和审批追加到本地事件日志。
8. 在完成、取消、预算耗尽、哈希冲突或需要科研决定时停止。

### 9.3 文件补丁与 VS Code

AI4SOTA 和 VS Code 操作同一目录。文件监听用于快速刷新，但不能作为一致性保证。

每组 Agent 补丁包含全部目标文件的预期旧哈希。应用时必须先验证整组哈希，再通过临时文件、fsync 和原子替换写入；任一文件冲突时整组不写入。用户看到冲突文件、当前 diff 和重新生成操作。

Run 准备、验证和 Agent 修改前都重新读取磁盘。VS Code 保存后，模块标记为 `changed`，受影响的兼容性和验证结果失效。

### 9.4 Provider

Provider 接口必须支持：

- 模型配置和能力探测；
- 流式输出；
- 类型化工具调用；
- 结构化 JSON；
- 用量统计；
- 取消；
- 统一错误。

v1 使用 OpenAI-compatible HTTP Adapter 同时连接托管 API 和本地兼容端点。项目有默认模型，四个对话均可覆盖。一次请求从开始到结束绑定同一个 Profile。

请求失败、限流或本地端点离线时禁止静默切换 Provider。用户选择重试、切换 Profile 或仅本轮覆盖。凭据只存入操作系统凭据管理器，项目和日志只保存不透明引用。

### 9.5 文献与证据

所有来源统一为 `PaperRecord`，优先按 DOI、PMID、arXiv ID 去重。用于方法选择、实现或结论的主张必须链接到可定位片段，并记录来源标识、页码或章节、获取时间和许可状态。

论文、网页、仓库、日志和数据内容均是不可信输入。它们不能改变系统策略、授予权限或直接发起工具调用。

## 10. 工具和权限

### 10.1 工具注册表

模型只可使用类型化注册工具：

- 文件：list、read、search、propose patch、apply patch、diff、open in VS Code。
- 契约：validate schema、inspect sample、compile compatibility、materialize split。
- 验证：format、lint、unit test、smoke test。
- 文献：search、import、deduplicate、extract passage、attach evidence。
- 实验：prepare spec、approve、start、cancel、inspect。
- 历史：compare、draft research commit、create branch/commit、publish module。

模型不得获得任意 Shell、Git、数据库、凭据、文件系统或网络原语。

### 10.2 默认权限

- `allow`：读取和索引当前项目、读取 Run、更新会话、查询已启用的公共文献元数据、在哈希保护下写当前模块工作副本。
- `allow_registered`：Schema 校验、静态检查、格式化，以及受信任代码中登记的快速单元或 Smoke Test；必须可见和可取消。
- `ask`：开始实验、未登记命令、依赖变化、扩大文件范围、向托管模型发送选定本地数据、下载外部代码、网络访问、分支、发布、Research Commit 和批量或破坏性修改。
- `deny`：读取秘密明文、越过允许根路径、跨模块静默写入、绕过科研确认、覆盖哈希冲突或绕过访问控制。

审批绑定规范化参数、目标哈希、作用域、工具、Provider 和有效期。任一值变化即失效。

## 11. 进程与服务架构

```text
Tauri 2 desktop shell
  -> React/TypeScript WebView
  -> narrow typed Tauri commands
  -> packaged FastAPI control service on 127.0.0.1
       -> project and schema services
       -> agent runtime and provider adapters
       -> literature connectors
       -> SQLite rebuildable index
       -> file watcher and hash service
       -> job manager
            -> isolated Python worker process
                 -> immutable Run snapshot
                 -> project Python environment
```

Tauri 启动控制服务时选择临时端口和单次启动令牌，并限制请求来源。令牌不写入项目、日志或长期设置。普通操作使用类型化 HTTP API，Agent、日志、指标和 Job 状态使用 WebSocket 或 SSE。

前端不暴露通用 Shell。用户代码只加载到 Worker，不加载到 Tauri 或长期控制服务。Worker 获得快照路径、环境 ID、允许目录、Job Manifest 和取消通道。

进程分离用于控制崩溃影响、取消和审计，不等于强安全沙箱。首次执行用户或外部 Python 代码前必须明确提示该边界。

## 12. 本地 API 边界

控制服务至少提供以下资源：

```text
/projects             创建、打开、索引和读取项目状态
/modules              读取模块、Schema、验证、导入和发布
/compatibility        编译和解释确定性契约结果
/files                受限读取、搜索、Diff 和哈希补丁
/conversations        本地会话、流式 Turn 和取消
/decisions            DecisionRecord 草稿与确认
/literature           搜索、导入、去重、片段和证据关联
/jobs                  验证、测试、Run 的队列、状态和取消
/runs                  Run 详情、日志、指标、产物和比较
/research-commits      草稿、验证、创建、分支和恢复
/settings              Provider、连接器、路径、环境和权限策略
```

所有写 API 接收预期版本或内容哈希，并返回新版本。错误使用稳定机器码，例如 `HASH_CONFLICT`、`SCIENTIFIC_DECISION_REQUIRED`、`INCOMPATIBLE_CONTRACT`、`APPROVAL_REQUIRED`、`PROVIDER_UNAVAILABLE` 和 `WORKER_INTERRUPTED`。

## 13. 存储布局

```text
project/
├── README.md
├── ai4sota.project.yaml
├── .git/
├── tasks/
│   └── active.yaml
├── modules/
│   ├── data/current/
│   ├── method/current/
│   └── evaluation/current/
├── adapters/
├── data/
│   ├── fingerprints/
│   ├── splits/
│   └── cache/
├── conversations/events.jsonl
├── decisions/
├── references/
├── runs/<run_id>/
│   ├── manifest.yaml
│   ├── snapshot/
│   ├── events.jsonl
│   ├── logs/
│   ├── metrics/
│   └── artifacts/
├── research-commits/<commit_id>/
│   ├── manifest.yaml
│   ├── conclusion.md
│   └── artifact-index.json
├── .ai4sota/index.sqlite
├── pyproject.toml
└── uv.lock
```

人类可读 Manifest 和追加事件日志是事实来源。SQLite 是可删除并重建的查询索引。大型原始数据和产物默认不进入 Git，只保存路径、清单和内容哈希。

## 14. Run 生命周期

Run 状态包括：

```text
draft -> awaiting_approval -> queued -> preparing -> running
      -> succeeded | failed | cancelled | interrupted
```

进入审批前必须完成：

- 所有 Schema 有效；
- 兼容性无阻塞；
- `SplitManifest` 已物化；
- 目标文件、配置和数据指纹已核对；
- 环境与资源已解析；
- `ExperimentSpec` 可完整展示。

用户批准后再次核对所有绑定哈希，再创建快照并排队。Run 只从快照读取代码和小型配置。运行期间若强指纹数据发生变化，Run 标记完整性异常，默认排除公平比较。

关闭主窗口时，有活动 Run 则最小化到托盘。明确退出时列出活动 Job，让用户选择继续后台或取消。崩溃或重启后的未完成 Run 标记 `interrupted`，保留日志，不自动伪装为失败或成功。

## 15. 比较与 Research Commit

### 15.1 可比性

比较器基于版本化确定性规则返回：

- `directly_comparable`：数据身份、样本成员、任务本体、评价协议和实现、聚合语义一致。
- `comparable_with_caveats`：只有声明的非关键维度不同，展示具体限制后可做受限比较。
- `not_comparable`：测试成员、目标、主指标、关键聚合或完整性不同。

`not_comparable` 仍可并排查看原始数值，但 UI 和 Agent 均不得计算自动差值或使用“提升”语言。

### 15.2 多 Run 聚合

一个 Research Commit 可聚合多个 Run，但代码、模块、数据、任务、划分规则和评价协议哈希必须相同。允许变化仅限预先声明的 seed、fold 或 repeat。Manifest 保存样本量、聚合方法、均值、离散程度和配置的置信区间。

### 15.3 精确快照提交

Research Commit 必须提交所选 Run 的精确 Git 树。若当前工作区已经变化，系统从 Run 快照在隔离 worktree 或临时分支中创建提交，不切换、不重置和不覆盖当前工作区。命名空间引用把 Research Commit ID 与 Git SHA 关联。

## 16. 错误处理与恢复

- Schema 错误定位到字段，说明原因和修复方式。
- 文件哈希冲突阻止整组写入，显示当前文件与原补丁 Diff。
- Provider 故障保留已流式接收内容和本地事件，不自动换模型。
- Worker 崩溃不影响桌面和控制服务，Run 标记失败或中断并保留 stderr。
- 文件监听丢事件时，关键操作前的完整哈希核对仍能阻止旧内容覆盖。
- SQLite 损坏或删除后可从项目 Manifest 和事件日志重建。
- 发布或 Research Commit 在最终确认前重新核对哈希，过期审批不得复用。
- Artifact 清理只删除用户明确选择的大型负载，保留 Manifest、指标、哈希和墓碑记录。

## 17. 已确认的端到端流程

1. 用户在指定本地目录创建项目，与项目 Agent 讨论并确认 `Research Brief`。
2. 用户进入 Data，导入全局模块或新建模块；系统扫描样例，区分来源事实和预处理决定，生成代码并验证规范 EEG 输出。
3. 用户进入 Method，检索有证据的基线和实现，选择方案，导入或搭建代码，在 AI4SOTA 或 VS Code 修改并通过模块测试。
4. 用户进入 Evaluation，确认任务本体、被试安全划分、指标、统计和可解释性，并锁定主协议。
5. 用户回到 Overview，编译三个契约，审查机械适配器并解决所有语义决策和阻塞。
6. 用户打开 Run 审批，检查 `ExperimentSpec`、数据、划分、环境和模块哈希后确认。
7. 系统从快照后台训练；用户查看日志、指标和产物，同时可继续编辑实时工作区。
8. 用户修改一个模块并批准第二次 Run。
9. 用户选择多个 Run；系统先给出可比性判定，再展示允许的指标差异。
10. 用户将有价值的 Run 提升为 Research Commit，确认假设、证据、结果、结论、局限和下一步。
11. 用户可将验证良好的项目模块显式发布为全局模块库的新版本。

## 18. v1 验收场景

1. 新建项目后，可完成 Data -> Method -> Evaluation -> Run -> Compare -> Research Commit 全流程。
2. 至少一个 EEG 数据模块能从本地文件生成稳定 `CanonicalDataset`，并显示 shape、标签、被试和通道验证。
3. Evaluation 生成被试安全的固定 `SplitManifest`，Data 模块无需包含划分逻辑。
4. 缺失 `subject_id` 而评价要求跨被试划分时，系统返回 `incompatible` 并禁用 Run。
5. 轴转置可生成可审查机械适配器；重采样必须请求科研决策。
6. VS Code 保存文件后，界面刷新；旧哈希 Agent 补丁无法覆盖修改。
7. Run 开始后继续编辑工作区，已运行代码和 Manifest 不变化。
8. 失败、取消和中断 Run 都可查看快照、日志和终止原因。
9. 不同被试划分的 Run 判为 `not_comparable`，不显示自动提升结论。
10. 多 seed Run 只有在所有非重复维度哈希相同时才能聚合。
11. 从旧 Run 创建 Research Commit 时，提交旧快照且当前工作区保持不变。
12. 从项目发布模块产生新的不可变全局版本；原全局版本不被修改。
13. Data 作用域 Agent 默认无法写 Method 或 Evaluation 文件。
14. 托管 Provider 未获批准时不能接收原始 EEG 样本或可识别元数据。
15. 本地模型能力探测不支持可靠工具调用时，只能用于讨论模式。
16. 登记的快速测试可自动运行；任意命令、依赖变化、GPU Run 和联网代码均要求审批。
17. 有活动 Run 时关闭主窗口进入托盘；显式退出不会静默终止训练。
18. 删除 `.ai4sota/index.sqlite` 后，项目仍可从 Manifest 和事件日志重建索引。

## 19. 实施约束

- 复用现有 `AI4SOTA-MVP-Phase1` 的 `CanonicalDataset`、`PredictionBundle`、`EvaluationResult`、项目生成和基本运行记录概念。
- 现有 dataclass 可作为迁移输入，但 v1 持久化 Schema 以 Pydantic 和 JSON Schema 为准。
- 第一条实现纵切必须先证明契约、快照、比较和 Research Commit，再扩展自动化能力。
- 每个阶段必须有独立单元测试，并用至少一个完整本地项目做端到端验证。
- 所有产品代码进入实施计划后再编写；本规格本身不授权初始化仓库、安装依赖或修改现有内核。

## 20. 设计完成标准

本规格没有未决产品问题。以下决定均已由用户确认：

- 人机协作而非自主 AutoML；
- Data、Method、Evaluation 三模块；
- 全局本地库、项目副本和显式发布；
- 项目文件本地自包含并与 VS Code 共享；
- 托管 API 与本地兼容端点；
- 项目默认模型与每对话覆盖；
- 分级自动验证；
- Tauri + React + FastAPI + 独立 Worker；
- 四级兼容性、三层历史和三级可比性；
- 精确 Run 快照生成 Research Commit；
- 固定五区桌面工作台；
- 单焦点模块标签；
- Obsidian 骨架与 ChatGPT 浅色表面的视觉基线；
- 本文第 17 节的完整科研主流程。

用户审阅本规格后，下一步是编写逐任务实施计划，不在该步骤重新打开产品范围。
