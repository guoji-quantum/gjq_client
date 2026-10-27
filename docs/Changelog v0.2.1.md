# Changelog

## 编写规范 Convention

本变更日志格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，本项目遵循[语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 目录 Content

- 0.2.1 - [中文](#021-中文) | [English](#021-english)

- [Previous releases: 0.2.0](Changelog%20v0.2.0.md)

<a id="021-中文"></a>

## \[0.2.1] - 2026-10-26

#### 🚀 版本更新

本版本扩展 MPS 与 Guoji08 Estimator 的观测量和具名求和支持，完善 PennyLane 方差梯度与结果映射，并补充 Session 查询能力。用户可计算更丰富的 Pauli 观测量，按指定名称读取期望值，并获得更清晰的任务结果和云平台错误提示。

#### ✨ 新增特性

- **Session 查询能力**:

  - 新增 Session 列表、详情及所属任务查询接口，便于在不同代码段中跟踪和管理已创建的 Session。

- **运行状态查询**:

  - 补充后端状态与任务详情查询能力，方便获取云端资源和任务的最新信息。

#### 🛠 改进优化

- **MPS 结果语义**:

  - MPS Sampler 以整数 `counts` 返回采样次数，并通过 `probabilities` 单独保留概率分布。

  - 完善 MPS 期望值结果的完整性检查，并保留线路中未使用量子比特的声明宽度。

  - MPS Estimator 新增有限实数系数、多比特 Pauli 观测量、恒等项和具名 Hamiltonian 求和支持。

  - 多项 `SparsePauliOp` 作为一个名为 `observable` 的整体观测量提交；显式具名观测量列表保留调用者指定的结果名称。

- **Guoji08 Estimator**:

  - 支持有限实数系数、多比特 X/Y/Z Pauli 观测量及具名求和，并按调用者指定的名称分别返回期望值。

  - 正确处理恒等项、零系数、重复项及同一 Pauli 对应不同名称的观测量。

  - 自动规范末端测量范围，兼容未测量和部分测量的输入线路，并保留调用者原线路。

- **真机执行与转译**:

  - 改进任务完成后结果尚未就绪时的重试处理，减少瞬时数据延迟造成的读取失败。

  - 完善后端配置、耦合关系和转译布局处理，使线路与观测量更准确地映射到目标后端。

  - 支持自动分解具有定义的自定义门，并正确识别后端声明支持的原生门。

- **安全性与错误提示**:

  - 加强本地凭证文件保护，并对冲突或无效的认证配置提供更明确的提示。

  - 对非 JSON 格式的 HTTP 错误优先报告实际 HTTP 错误、处理建议和响应摘要，避免误报为 JSON 解析失败。

  - 启用 PQC 通道时默认校验服务端指纹，并改进通道恢复、带参数请求及错误信息返回。

#### 🐛 问题修复

- **Estimator 与 MPS 校验修复**:

  - 修复部分非 MPS Estimator 任务可能依据错误测量基计算期望值的问题，并按最终转译布局处理观测量。

  - 修复 MPS 线路宽度、无效系数及不完整期望值结果的判断问题。

  - 修复通过服务接口重新获取任务结果时上下文缺失的问题，保留 MPS 整数计数及 Guoji08 具名求和的结果语义。

  - 修复 Guoji08 Estimator 直接 JSON 提交的测量顺序校验，在提交前拒绝测量后继续作用于同一比特的计算门，包括将已测量比特用作控制位的情况。

- **PennyLane 结果与梯度修复**:

  - 统一 PennyLane 的 `counts`、`sample` 和 `probs` 返回顺序，使其与测量中显式指定的 wires 顺序一致；Runtime 原始结果继续遵循 Qiskit 小端序约定。

  - 修复 MPS Pauli 求和方差的参数偏移梯度，保留平方算符及常数项对梯度的影响。

  - 根据编译后的测量映射还原逻辑 wires 的采样结果，正确处理物理比特重排及额外辅助比特。

- **后端配置兼容性修复**:

  - 修复 Baihua 后端门集合与耦合关系解析不一致的问题。

#### 📚 文档

- **使用指南更新**:

  - 更新中英文使用指南与 README，补充 Session 生命周期和查询、MPS 结果字段、后端选择及 PennyLane 测量顺序说明。

  - 完善 MPS 与 PennyLane 示例，帮助用户区分采样计数、概率和期望值结果。

使用示例见 [README](../README.md)。



<a id="021-english"></a>

## \[0.2.1] - 2026-10-26

#### 🚀 Release Update

This release expands observable and named-sum support in MPS and Guoji08 Estimator, improves PennyLane variance gradients and result mapping, and adds Session query capabilities. Users can evaluate a wider range of Pauli observables, retrieve expectation values under their supplied names, and receive clearer job results and cloud error messages.

#### ✨ Features

- **Session queries**:

  - Added APIs for listing Sessions, retrieving Session details, and querying jobs submitted within a Session.

- **Runtime status queries**:

  - Added access to backend status and cloud task details.

#### 🛠 Improvements

- **MPS result semantics**:

  - MPS Sampler now returns integer shot frequencies in `counts` and preserves the probability distribution separately in `probabilities`.

  - Improved completeness checks for MPS expectation values and preserved the declared width of circuits containing idle qubits.

  - MPS Estimator now supports finite real coefficients, multi-qubit Pauli observables, identity terms, and named Hamiltonian sums.

  - A multi-term `SparsePauliOp` is submitted as one observable named `observable`, while explicitly named observable lists preserve their supplied result names.

- **Guoji08 Estimator**:

  - Added finite real coefficients, multi-qubit X/Y/Z Pauli observables, and named sums, with separate expectation values returned under caller-supplied names.

  - Correctly handled identity terms, zero coefficients, repeated terms, and distinct names for the same Pauli observable.

  - Automatically normalized terminal measurement coverage for unmeasured and partially measured input circuits while preserving the caller's circuit.

- **Hardware execution and transpilation**:

  - Improved result retrieval when a completed job's data is briefly unavailable, reducing failures caused by transient propagation delays.

  - Improved backend configuration, coupling-map, and transpiled-layout handling for more accurate circuit and observable mapping.

  - Added automatic decomposition for defined custom gates while recognizing native gates declared by a backend.

- **Security and error reporting**:

  - Strengthened protection for locally stored credentials and clarified errors for conflicting or invalid authentication settings.

  - Reported the actual HTTP error, actionable guidance, and a response excerpt for non-JSON error responses instead of misclassifying them as JSON parsing failures.

  - Enabled server fingerprint verification by default when using the PQC channel, with improved channel recovery, parameterized requests, and error reporting.

#### 🐛 Fixes

- **Estimator and MPS validation**:

  - Fixed cases where non-MPS Estimator jobs could derive expectation values from the wrong measurement basis, and applied observables according to the final transpiled layout.

  - Fixed validation of MPS circuit width, invalid coefficients, and incomplete expectation-value results.

  - Restored task context when retrieving results through the service API, preserving MPS integer counts and Guoji08 named-sum semantics.

  - Fixed measurement-order validation for direct Guoji08 Estimator JSON submissions, rejecting computation on previously measured qubits before submission, including measured control qubits.

- **PennyLane results and gradients**:

  - Aligned PennyLane `counts`, `sample`, and `probs` results with the wire order explicitly requested by each measurement, while raw Runtime results continue to follow Qiskit's little-endian convention.

  - Fixed parameter-shift gradients of MPS Pauli-sum variances, preserving contributions from squared observables and constant terms.

  - Reconstructed logical-wire sampling results from compiled measurement mappings, including physical-qubit permutations and additional ancillas.

- **Backend configuration compatibility**:

  - Fixed inconsistent parsing of the Baihua backend's gate set and coupling information.

#### 📚 Docs

- **User guide updates**:

  - Updated the Chinese and English user guides and README with Session lifecycle and query usage, MPS result fields, backend selection, and PennyLane measurement ordering.

  - Improved MPS and PennyLane examples to clarify sampling counts, probabilities, and expectation-value results.

For usage examples, see the [README](../README.md).
