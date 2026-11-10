# Changelog

## 编写规范 Convention

本变更日志格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，本项目遵循[语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 目录 Content

- 0.2.2 - [中文](#022-中文) | [English](#022-english)

- [Previous releases: 0.2.1](Changelog%20v0.2.1.md)

<a id="022-中文"></a>

## \[0.2.2] - 2026-11-09

#### 🚀 版本更新

本版本新增本地全振幅模拟器 `FAS-LOCAL`，支持无需 API Key 和网络访问的本地量子线路采样，并修复 Guoji04 Estimator 的多观测量编码与结果适配。同时统一 Session 关闭接口，调整任务结果查询返回值及 MPS expert 参数上限；使用相关接口的调用方需按下文说明更新代码或配置。

#### ✨ 新增特性

- **本地模拟器 FAS-LOCAL**:

  - 新增本地 CPU 全振幅模拟器，通过 `LocalSimulator()` 或 `service.backend("FAS-LOCAL")` 获取后端，支持最多 20 个量子比特和每次 1 至 100000 shots。

  - 复用 Sampler、I/Z Estimator、转译和 PennyLane 设备调用接口，直接使用 `LocalSimulator()` 无需创建云端客户端或配置 API Key。

  - 支持通过 `options={"seed": ...}` 指定采样种子；未指定时自动生成，并在结果与任务日志中记录，便于重放采样结果。

  - 本地任务同步执行，结果仅保存在所属本地客户端实例内存中；不支持跨实例恢复、Session、`simulator_config` 或 `amplitude_index`，本地 Estimator 不支持具名观测量列表。

#### 🛠 改进优化

- **Session 关闭接口（兼容性变更）**:

  - 移除 `Session.cancel()` 和 `RuntimeClient.cancel_session()`，统一使用 `Session.close()` 和 `RuntimeClient.close_session()`；底层 REST 适配器以 `close()` 替代 `update_status()`，关闭请求改用 `POST /sessions/closeSession`。

  - 明确会话关闭语义：不再接受新任务，排队任务由服务端取消，正在运行的任务继续执行至完成；退出 `with` 时的自动关闭遵循相同规则。

  - 成功关闭后缓存服务端返回结果，重复调用 `close()` 直接返回首次结果，避免重复发送关闭请求。

  - 关闭请求发生超时、连接错误或可重试 HTTP 错误时不自动重发；退出 `with` 时不再重复发送已尝试的关闭请求，调用方可显式调用 `close()` 重试。

- **任务结果查询（兼容性变更）**:

  - `GJQRuntimeService.task_result(task_id)` 改为直接返回底层客户端提供的完整任务结果字典，保留后端字段及嵌套结构，不再仅提取 `counts` 或 `evs`。

  - 移除 `observable` 参数，不再预先查询任务状态或等待完成；空结果与客户端异常直接传递给调用方。

  - 需要等待任务完成并解析采样计数或期望值时，使用提交任务所得的 `RuntimeJob.result()`。

- **MPS expert 参数范围（兼容性变更）**:

  - 将 `simulator_config.mps.max_bond_dimension` 的最大值由 4096 下调至 1024，有效整数范围为 `[2, 1024]`；原有大于 1024 的配置需同步调整。

  - Sampler、Estimator 与直接 JSON 提交统一执行该范围校验，在提交前拒绝超限配置。

#### 🐛 问题修复

- **本地模拟器结果与输入校验**:

  - 将 Sampler/Estimator 的 `counts` 统一为量子位序，右侧为 q0，保留线路量子比特宽度与前导零，并将未测量量子位填为 0，与云端 FAS 的计数约定保持一致。

  - 按量子位观测量计算本地期望值，正确处理交换测量、部分测量、多个经典寄存器及转译布局，并保留观测量系数。

  - 本地 Estimator 在提交前拒绝重复测量、经典位覆盖、观测量所需量子位未测量及不支持的观测量格式，避免提交成功后才因结果无法解析而失败。

  - 拒绝 `reset` 和无实际测量的本地线路，并从本地转译 Target 中移除 `reset`，避免错误采样分布、种子无法重放或伪造的全零计数。

- **Guoji04 Estimator 多观测量适配**:

  - 将已有的 Guoji08 原生观测量编码与结果重建逻辑扩展至 Guoji04，统一使用全宽 Pauli 标签，避免不同目标量子位的观测量产生标签歧义。

  - 正确处理具名多观测量、实数系数与 Pauli 求和，按调用者指定的名称返回期望值，避免系数重复计算，并检查缺失的观测量结果。

  - 统一 SDK 与直接 JSON 提交路径的观测量编码与校验；SDK 自动规范末端测量范围，直接 JSON 提交则校验测量完整性，在缺失测量时明确拒绝。

- **Session 状态解析**:

  - 同时兼容详情响应顶层的 `status` 和嵌套的 `sessionInfo.status`，修复嵌套响应下无法读取 Session 状态的问题。

#### 📚 文档

- **本地模拟器使用指南**:

  - 更新 README 与中英文 v0.2 使用教程，补充离线入口、采样种子重放、量子位序结果、任务生命周期和本地能力限制。

  - 补充本地模拟器修复说明，记录测量映射、输入校验及与云端 FAS 结果约定对齐的行为。

- **接口迁移说明**:

  - 更新 Session 显式关闭、上下文自动关闭及任务结果查询示例，说明完整任务结果字典与 `RuntimeJob.result()` 解析结果的区别。

  - 同步 MPS expert 最大键维度的参数范围及校验说明。

使用示例见 [README](../README.md)。



<a id="022-english"></a>

## \[0.2.2] - 2026-11-09

#### 🚀 Release Update

This release adds the local full-amplitude simulator `FAS-LOCAL` for circuit sampling without an API Key or network access, and fixes multi-observable encoding and result adaptation for Guoji04 Estimator. It also unifies Session closing, changes task-result query return values, and lowers the MPS expert bond-dimension limit. Callers using these interfaces must update their code or configuration as described below.

#### ✨ Features

- **Local simulator FAS-LOCAL**:

  - Added a local CPU full-amplitude simulator accessible through `LocalSimulator()` or `service.backend("FAS-LOCAL")`, supporting up to 20 qubits and 1 to 100000 shots per run.

  - Reused the Sampler, I/Z Estimator, transpilation, and PennyLane device interfaces. Direct use of `LocalSimulator()` requires neither a cloud client nor an API Key.

  - Added sampling seeds through `options={"seed": ...}`. A seed is generated when omitted and recorded in results and task logs for replay.

  - Local jobs execute synchronously, and results remain only in the owning local client instance's memory. Cross-instance recovery, Sessions, `simulator_config`, and `amplitude_index` are unsupported; local Estimator does not accept named observable lists.

#### 🛠 Improvements

- **Session closing (breaking change)**:

  - Removed `Session.cancel()` and `RuntimeClient.cancel_session()` in favor of `Session.close()` and `RuntimeClient.close_session()`. The REST adapter replaces `update_status()` with `close()` and sends closing requests through `POST /sessions/closeSession`.

  - Clarified Session closing semantics: no new jobs are accepted, queued jobs are cancelled by the server, and running jobs continue to completion. Automatic closing on context exit follows the same rules.

  - Cached the server response after a successful close. Repeated `close()` calls return the first response without sending another request.

  - Disabled automatic retries for closing requests after timeouts, connection errors, or retryable HTTP errors. Exiting a `with` block does not resend an already attempted close; callers may explicitly call `close()` to retry.

- **Task-result queries (breaking change)**:

  - Changed `GJQRuntimeService.task_result(task_id)` to return the complete task-result dictionary supplied by the underlying client, preserving backend fields and nested structures instead of extracting only `counts` or `evs`.

  - Removed the `observable` argument, preliminary status queries, and waiting for task completion. Empty results and client exceptions pass through to the caller.

  - Use the `RuntimeJob.result()` method on the submitted job to wait for completion and parse sampling counts or expectation values.

- **MPS expert parameter range (breaking change)**:

  - Lowered the maximum `simulator_config.mps.max_bond_dimension` from 4096 to 1024. The valid inclusive integer range is `[2, 1024]`; existing configurations above 1024 must be updated.

  - Applied the same range validation to Sampler, Estimator, and direct JSON submissions, rejecting out-of-range configurations before submission.

#### 🐛 Fixes

- **Local simulator results and input validation**:

  - Aligned Sampler/Estimator `counts` with qubit order, with q0 on the right. Keys preserve the circuit's qubit width and leading zeros, with unmeasured qubits filled with 0, matching the cloud FAS count convention.

  - Computed local expectation values using qubit-order observables, correctly handling swapped measurements, partial measurements, multiple classical registers, and transpiled layouts while preserving observable coefficients.

  - Rejected repeated measurements, overwritten classical bits, unmeasured qubits required by observables, and unsupported observable formats before local Estimator submission, preventing failures that previously occurred only during result parsing.

  - Rejected local circuits containing `reset` or no actual measurement, and removed `reset` from the local transpilation Target to prevent incorrect sampling distributions, unreplayable seeds, or fabricated all-zero counts.

- **Guoji04 Estimator multi-observable adaptation**:

  - Extended the existing Guoji08 native observable encoding and result reconstruction to Guoji04, using full-width Pauli labels to distinguish observables acting on different target qubits.

  - Correctly handled multiple named observables, real coefficients, and Pauli sums, returning expectation values under caller-supplied names, avoiding repeated coefficient application, and checking for missing observable results.

  - Unified observable encoding and validation across SDK and direct JSON submissions. The SDK automatically normalizes terminal measurement coverage, while direct JSON submissions validate measurement completeness and reject missing measurements.

- **Session status parsing**:

  - Accepted both top-level `status` and nested `sessionInfo.status` in detail responses, fixing unavailable Session status values for nested responses.

#### 📚 Docs

- **Local simulator user guides**:

  - Updated the README and Chinese and English v0.2 guides with offline entry points, seed replay, qubit-order results, task lifetime, and local capability limits.

  - Added local simulator fix documentation covering measurement mappings, input validation, and alignment with cloud FAS result conventions.

- **API migration guidance**:

  - Updated examples for explicit Session closing, automatic closing on context exit, and task-result queries, explaining the difference between complete task-result dictionaries and results parsed by `RuntimeJob.result()`.

  - Updated the MPS expert maximum bond-dimension range and validation guidance.

For usage examples, see the [README](../README.md).
