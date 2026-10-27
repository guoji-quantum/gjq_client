# Changelog

## 编写规范 Convention

本变更日志格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，本项目遵循[语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 目录 Content

- 0.2.0 - [中文](#020-中文) | [English](#020-english)

- [Previous releases: 0.1.1](Changelog%20v0.1.1.md)

<a id="020-中文"></a>

## \[0.2.0] - 2026-09-14

#### 🚀 版本更新

本版本新增 Session 资源独占任务机制、最高支持 1,000 比特的矩阵乘积态（MPS）模拟器及 PennyLane 适配。用户可通过 Session 组织迭代任务，运行更大规模的模拟线路，并通过 GJQ Runtime 执行支持梯度计算的 PennyLane QNode。

#### ✨ 新增特性

- **Session 任务支持**:

  - 在支持 Session 模式的后端上，将相关任务组织到同一 Session，在 Session 活跃期间独占后端资源。

  - 支持通过 `Sampler(mode=session)` 和 `Estimator(mode=session)` 提交任务。

  - 支持 Session 状态查询、详情查询、任务列表查询、关闭与取消操作。

- **MPS 模拟器支持**:

  - 新增 `MPS` 后端，支持 2 至 1,000 比特线路，实际运行性能取决于线路深度与纠缠程度。

  - 提供 `fast`、`balanced`、`accurate` 模拟预设，以及用于高级配置的 `expert` 模式。

  - 支持 MPS 采样与 Pauli 期望值计算。

  - **建议性能限制**：总门数不超过10万；观测量总数不超过3000；大比特数时（100～1000），近邻线路建议控制在约 20 层以内。

- **PennyLane 适配**:

  - 新增可选安装依赖 `gjq-client[pennylane]`，通过 `qml.device("gjq", ...)` 接入 PennyLane 0.45.x。

  - 支持有限 shots 下的期望值、方差、概率、样本和计数，以及参数偏移法求导。

  - 支持 MPS模拟器调用、Session任务执行、自定义量子比特标签和参数广播。

#### 🛠 改进优化

- **模拟配置与任务规模校验**:

  - 在提交前校验 MPS 配置和线路规模，并为较大规模任务提供使用提示。

  - 增加门数与观测量数量限制，帮助用户在提交前识别不支持的任务规模。

- **后端与任务处理**:

  - 完善 MPS 后端配置处理，并展示后端任务模式，方便选择支持 Session 的资源。

  - 统一独立任务与 Session 任务的提交格式。

- **可观测量支持**:

  - PennyLane 期望值与方差支持 Pauli 算子的实系数线性组合，包括多比特 Pauli 乘积。

#### 🐛 问题修复

- **MPS 结果处理修复**:

  - 修复 MPS 配置与结果解析，在 `counts` 中保留概率值，并通过 `evs` 返回具名期望值。

  - 修复 PennyLane 将 MPS 概率转换为有限 shots 计数时的处理，确保计数总和与请求 shots 一致。

- **Session 生命周期处理修复**:

  - 修复任务提交中的 Session 标识处理，并拒绝向已关闭的 Session 提交任务。

- **参数校验修复**:

  - 完善无效模拟器参数、不支持的测量类型和单振幅后端请求的错误处理。

#### 📚 文档

- **更新使用示例**:

  - 更新英文 README，补充 0.2.0 特性简介及Session、MPS 和 PennyLane 示例。

  - 新增 MPS 期望值计算与 PennyLane 参数偏移梯度示例。

使用示例见 [README](../README.md)。



<a id="020-english"></a>

## \[0.2.0] - 2026-09-14

#### 🚀 Release Update

This release introduces Session-based exclusive resource execution, the Matrix Product State (MPS) simulator with support for up to 1,000 qubits, and PennyLane integration. Users can group iterative jobs in a Session, simulate larger circuits, and run differentiable PennyLane QNodes through GJQ Runtime.

#### ✨ Features

- **Session-based execution**:

  - Added Sessions for grouping related jobs with exclusive backend resources while a Session is active, on backends that support Session mode.

  - Added `Sampler(mode=session)` and `Estimator(mode=session)` execution.

  - Added Session status, details, task listing, close, and cancel operations.

- **MPS simulator support**:

  - Added the `MPS` backend for circuits with 2 to 1,000 qubits, with practical performance depending on circuit depth and entanglement.

  - Added `fast`, `balanced`, and `accurate` simulation presets, plus `expert` settings for advanced configuration.

  - Added MPS sampling and Pauli expectation-value evaluation.

- **PennyLane integration**:

  - Added the optional `gjq-client[pennylane]` installation extra and the `qml.device("gjq", ...)` device for PennyLane 0.45.x.

  - Added finite-shot expectations, variances, probabilities, samples, and counts, with parameter-shift differentiation.

  - Added support for MPS, Session execution, custom wire labels, and parameter broadcasting.

#### 🛠 Improvements

- **Simulation configuration and workload checks**:

  - Added validation of MPS settings and circuit size before submission, with guidance for larger workloads.

  - Added gate and observable count limits to identify unsupported workloads before submission.

- **Backend and task handling**:

  - Improved MPS backend configuration handling and exposed backend job modes to help users select Session-capable resources.

  - Unified task submission across standalone and Session jobs.

- **Observable support**:

  - Added real linear combinations of Pauli words, including multi-qubit products, in PennyLane expectations and variances.

#### 🐛 Fixes

- **MPS result handling**:

  - Fixed MPS configuration and result parsing, preserving probability-valued `counts` and exposing named expectation values through `evs`.

  - Fixed PennyLane conversion of MPS probabilities to finite-shot counts so that the requested shot total is preserved.

- **Session lifecycle handling**:

  - Fixed Session identifiers in task submissions and rejection of submissions to closed Sessions.

- **Input validation**:

  - Improved error handling for invalid simulator settings, unsupported measurements, and single-amplitude backend requests.

#### 📚 Docs

- **Public usage examples**:

  - Updated the English README with a 0.2.0 feature overview and concise Session, MPS, and PennyLane examples.

  - Added examples for MPS expectation values and PennyLane parameter-shift gradients.

For usage examples, see the [README](../README.md).
