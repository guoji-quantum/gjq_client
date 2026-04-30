# Changelog

## 目录
+ 0.1.1 - [中文](#011-中文) | [English](#011-english)
+ 0.1.0 - [中文](#010-中文) | [English](#010-english)

<a id="011-中文"></a>
## [0.1.1] - 2026-04-30

#### 🚀 版本更新
本版本围绕云端模拟器接入、任务提交稳定性和发布安全性进行增强。`gjq-client` 现在可更顺畅地调用国基量子云平台的 `FAS-CPU` 与 `SAS-CPU` 模拟器后端，并在任务提交前提供更清晰的后端可用性校验与错误提示。

#### ✨ 新增特性
+ **云端模拟器后端支持**:
    - 新增对 `FAS-CPU`（全振幅模拟器）与 `SAS-CPU`（单振幅模拟器）的后端识别与任务提交支持。
    - 针对模拟器后端补齐配置与属性查询的兼容逻辑，使其可通过统一的 `backend()` 流程接入。
+ **任务提交前置校验**:
    - 提交任务前自动查询当前可用后端列表，避免将任务提交到维护中或不可用的后端。
    - 当所有后端维护或目标后端不可用时，返回中英文说明与可用后端提示，方便用户快速定位问题。

#### 🛠 改进优化
+ **任务数据格式兼容**:
    - 提升与云端数据接口兼容性。
+ **发布安全性增强**

#### 🐛 问题修复
+ **后端状态处理修复**:
    - 修复模拟器配置/属性接口返回非量子设备响应时的兼容处理。
    - 修复后端不可用、全维护等场景下任务仍可能继续提交的问题。
+ **参数校验修复**:
    - 对缺失 `device_name` 的任务 payload 提供明确错误。
    - 对 `SAS-CPU` 缺失 `amplitude-index` 的任务提交提前给出清晰异常。

#### 📚 文档
+ **用户文档更新**:
    - 更新量子编程框架用户使用教程，补充云端模拟器、后端选择、任务提交与常见使用说明。


<a id="011-english"></a>
## [0.1.1] - 2026-04-30

#### 🚀 Release Update
This release improves cloud simulator integration, task submission stability, and release security. `gjq-client` can now work more smoothly with the `FAS-CPU` and `SAS-CPU` simulator backends on GuoJi Quantum Cloud, with clearer backend availability checks and error messages before task submission.

#### ✨ Features
+ **Cloud simulator backend support**:
    - Added backend recognition and task submission support for `FAS-CPU` (full-amplitude simulator) and `SAS-CPU` (single-amplitude simulator).
    - Added compatibility handling for simulator backend configuration and properties queries, allowing simulators to be accessed through the unified `backend()` workflow.
+ **Pre-submission backend availability checks**:
    - Automatically queries the currently available backend list before submitting tasks, avoiding submissions to unavailable or maintenance backends.
    - Provides bilingual messages and available backend hints when all backends are under maintenance or the target backend is unavailable.

#### 🛠 Improvements
+ **Task payload compatibility**:
    - Improved compatibility with cloud data interfaces.
+ **Release security enhancement**:
    - Enhanced release packaging security by reducing exposure of sensitive connection implementation details.

#### 🐛 Fixes
+ **Backend status handling fixes**:
    - Fixed compatibility handling when simulator configuration or properties APIs return non-quantum-device responses.
    - Fixed cases where tasks could still be submitted when the target backend was unavailable or all backends were under maintenance.
+ **Parameter validation fixes**:
    - Added clearer errors for task payloads missing `device_name`.
    - Added early validation and clearer exceptions when `SAS-CPU` submissions are missing `amplitude-index`.

#### 📚 Docs
+ **User documentation update**:
    - Updated the quantum programming framework user guide with cloud simulator usage, backend selection, task submission, and common usage notes.


<a id="010-中文"></a>
## [0.1.0] - 2026-04-13

#### 🎉 首次发布
`gjq-client`(GuoJi Quantum Cloud Client SDK) 的首个公开发布版本！本版本提供了与国基量子云平台交互的核心能力，并全面兼容**Qiskit 2.0+框架**。

#### ✨ 核心特性
+ **服务认证与会话管理**: 
    - 基于API Key的身份验证及自动平台访问令牌维护。
+ **量子后端支持**:
    - 支持查询云平台可用的计算资源（真实量子计算机硬件）。
    - 支持将后端云数据析为兼容Qiskit 2.0 Target标准的GJQBackend对象。
+ **量子原语执行**:
    - 完整支持原语，允许向云端提交量子线路并获取结果。
+ **任务管理**:
    - 支持异步轮询查询任务生命周期，支持任务状态更新、结果获取及超时异常处理。
+ **编译优化**:
    - 提供兼容真实机器拓扑结构的预设编译通道。
+ **多语言友好设计**:
    - 报错、日志及异常已实现良好的中英双语输出机制，提升开发者体验。

<a id="010-english"></a>
## [0.1.0] - 2026-04-13

#### 🎉 Initial Release
The first public release of `gjq-client` (GuoJi Quantum Cloud Client SDK). This version provides the core capabilities for interacting with the GuoJi Quantum Cloud Platform and is fully compatible with the **Qiskit 2.0+ framework**.

#### ✨ Features
+ **Service authentication and session management**:
    - API Key based authentication with automatic platform access token maintenance.
+ **Quantum backend support**:
    - Supports querying available cloud computing resources, including real quantum hardware.
    - Supports parsing cloud backend data into `GJQBackend` objects compatible with the Qiskit 2.0 Target standard.
+ **Quantum primitive execution**:
    - Provides primitive support for submitting quantum circuits to the cloud and retrieving results.
+ **Task management**:
    - Supports asynchronous polling across the task lifecycle, including task status updates, result retrieval, and timeout handling.
+ **Compilation optimization**:
    - Provides preset compilation pass managers compatible with real-machine topology constraints.
+ **Bilingual developer experience**:
    - Errors, logs, and exceptions include Chinese and English messages to improve the developer experience.
