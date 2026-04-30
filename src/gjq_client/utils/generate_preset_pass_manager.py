# =============================================================================
# 基于 Qiskit (C) IBM 2024 代码修改
# Licensed under the Apache License, Version 2.0
# 修改说明: 对原始代码进行了调整以适配项目需求
# =============================================================================

"""
PassManager 生成函数
"""
import copy
import warnings

from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES, get_control_flow_name_mapping
from qiskit.circuit.library.standard_gates import get_standard_gate_name_mapping
from qiskit.circuit import Qubit
from qiskit.providers.backend import Backend
from qiskit.transpiler.coupling import CouplingMap
from qiskit.transpiler.exceptions import TranspilerError
from qiskit.transpiler.instruction_durations import InstructionDurations
from qiskit.transpiler.layout import Layout
from qiskit.transpiler.passmanager_config import PassManagerConfig
from qiskit.transpiler.preset_passmanagers.common import is_clifford_t_basis
from qiskit.transpiler.target import Target, _FakeTarget
from qiskit.transpiler.passmanager import StagedPassManager

from qiskit.transpiler.preset_passmanagers.level0 import level_0_pass_manager
from qiskit.transpiler.preset_passmanagers.level1 import level_1_pass_manager
from qiskit.transpiler.preset_passmanagers.level2 import level_2_pass_manager
from qiskit.transpiler.preset_passmanagers.level3 import level_3_pass_manager


OVER_3Q_GATES = ["ccx", "ccz", "cswap", "rccx", "c3x", "c3sx", "rc3x"]


def generate_preset_pass_manager(
    optimization_level=2,
    backend=None,
    target=None,
    basis_gates=None,
    coupling_map=None,
    initial_layout=None,
    layout_method=None,
    routing_method=None,
    translation_method=None,
    scheduling_method=None,
    approximation_degree=1.0,
    seed_transpiler=None,
    unitary_synthesis_method="default",
    unitary_synthesis_plugin_config=None,
    hls_config=None,
    init_method=None,
    optimization_method=None,
    dt=None,
    qubits_initially_zero=True,
    *,
    _skip_target=False,
):
    """
    生成预设的 PassManager

    该函数用于快速生成一个预设的 Pass Manager。预设 Pass Manager 是
    transpile 函数默认使用的 Pass Manager。该函数提供了一种简单便捷的方法，
    用于构建一个独立的 PassManager 对象，其行为与 transpile 内部构建的 PassManager 相同。

    目标约束可通过 Target 实例、BackendV2 实例，或松散约束（basis_gates、coupling_map 或 dt）指定。
    优先级规则如下：
    - 如果提供 target，则优先使用 target。
    - 如果提供 backend 和松散约束，松散约束优先覆盖 backend 对应约束。

    用户约束优先级示例：
    - basis_gates: target > basis_gates
    - coupling_map: target > coupling_map
    - dt: target > dt

    参数：
    - optimization_level (int): 优化等级，可选 0,1,2,3，默认 2。
        None：直接返回 PassManager，提交任务时提交源码
        0: 不优化
        1: 轻量优化
        2: 重度优化
        3: 极重优化
    - backend (Backend, 可选): 用作 basis_gates、coupling_map 和 target 的默认来源。
    - target (Target, 可选): 编译目标，未设置时可从此推断 coupling_map 和 basis_gates。
    - basis_gates (list, 可选): 要展开到的基础门列表，例如 ['u1','u2','u3','cx']。
    - coupling_map (CouplingMap 或 list, 可选): 有向耦合图，列表形式为 [[0,1],[0,3],...]。
    - dt (float, 可选): backend 采样时间，单位秒。None 时使用 backend.dt。
    - initial_layout (Layout 或 list[int], 可选): 虚拟量子比特在物理量子比特上的初始位置。
    - layout_method (str, 可选): 初始布局算法，可选 'trivial','dense','sabre' 或外部插件。
    - routing_method (str, 可选): 路由算法，可选 'basic','lookahead','sabre','none' 或外部插件。
    - translation_method (str, 可选): 门转换方法，可选 'translator','synthesis' 或外部插件。
    - scheduling_method (str, 可选): 指令调度方法，可选 'alap','asap' 或外部插件。
    - approximation_degree (float, 可选): 电路近似度，1.0 表示无近似，0.0 表示最大近似。
    - seed_transpiler (int, 可选): 随机种子。
    - unitary_synthesis_method (str, 可选): 单位矩阵综合方法名称，默认 'default'。
    - unitary_synthesis_plugin_config (dict, 可选): 传递给单位矩阵综合插件的配置。
    - hls_config (HLSConfig, 可选): 高级综合配置。
    - init_method (str, 可选): init 阶段使用的插件名称。
    - optimization_method (str, 可选): optimization 阶段使用的插件名称。
    - qubits_initially_zero (bool, 可选): 输入电路是否零初始化。

    返回：
    - StagedPassManager: 根据指定选项生成的预设 Pass Manager

    异常：
    - ValueError: 当传入无效的 optimization_level 时。
    """

    # 处理 target 和 backend 的位置参数。
    # 这使得可以通过 `generate_preset_pass_manager(backend.target)` 
    # 为指定 target 快速生成默认的 Pass Manager。

    if backend is not None and backend.configuration().simulator:
        basis_gates = backend.configuration().basis_gates
        backend=None

    if isinstance(optimization_level, Target):
        target = optimization_level
        optimization_level = 2
    elif isinstance(optimization_level, Backend):
        backend = optimization_level
        optimization_level = 2

    # 如果没有松散约束，则使用 backend 的 target（如果可用）。
    _no_loose_constraints = basis_gates is None and coupling_map is None and dt is None

    # 如果唯一的松散约束是 dt，则使用 backend 的 target，并修改 dt。
    _adjust_dt = backend is not None and dt is not None

    # 警告 backend 与松散约束不一致的情况（dt 通常不影响）。
    if backend is not None and (coupling_map is not None or basis_gates is not None):
        warnings.warn(
            "Providing `coupling_map` and/or `basis_gates` along with `backend` is not "
            "recommended, as this will invalidate the backend's gate durations and error rates.",
            category=UserWarning,
            stacklevel=2,
        )

    # 针对每个松散约束与 backend 约束逐一处理。
    # 优先级顺序：松散约束 > backend 约束。
    dt = _parse_dt(dt, backend)
    instruction_durations = _parse_instruction_durations(backend, dt)
    timing_constraints = _parse_timing_constraints(backend)
    coupling_map = _parse_coupling_map(coupling_map, backend)
    basis_gates, name_mapping = _parse_basis_gates(basis_gates, backend)

    # 检查是否提供了耦合图（独立提供或通过 backend），
    # 并配合用户定义的 basis_gates，判断是否包含三量子比特及以上的门。
    if coupling_map is not None and basis_gates is not None:
        for gate in OVER_3Q_GATES:
            if gate in basis_gates:
                raise ValueError(
                    f"Gates with 3 or more qubits ({gate}) in `basis_gates` or `backend` are "
                    "incompatible with a custom `coupling_map`. To include 3-qubit or larger "
                    " gates in the transpilation basis, provide a custom `target` instead."
                )

    if target is None:
        if backend is not None and _no_loose_constraints:
            # 如果指定了 backend 且没有松散约束，则直接使用 backend 的 target。
            target = backend.target
        elif _adjust_dt:
            # 如果指定了 backend 且有松散 dt，则使用 backend 的 target，并调整 dt 值。
            target = copy.deepcopy(backend.target)
            target.dt = dt
        else:
            if basis_gates is not None:
                # 根据约束构建 target。
                target = Target.from_configuration(
                    basis_gates=basis_gates,
                    num_qubits=backend.num_qubits if backend is not None else None,
                    coupling_map=coupling_map,
                    instruction_durations=instruction_durations,
                    concurrent_measurements=(
                        backend.target.concurrent_measurements if backend is not None else None
                    ),
                    dt=dt,
                    timing_constraints=timing_constraints,
                    custom_name_mapping=name_mapping,
                )
            else:
                target = _FakeTarget.from_configuration(
                    num_qubits=backend.num_qubits if backend is not None else None,
                    coupling_map=coupling_map,
                    dt=dt,
                )

    # 更新松散约束以填充 PassManager 的选项。
    if coupling_map is None:
        coupling_map = target.build_coupling_map()
    if basis_gates is None and len(target.operation_names) > 0:
        basis_gates = target.operation_names
    if instruction_durations is None:
        instruction_durations = target.durations()
    if timing_constraints is None:
        timing_constraints = target.timing_constraints()

    # 解析与 target 无关的 PassManager 选项。
    initial_layout = _parse_initial_layout(initial_layout)
    approximation_degree = _parse_approximation_degree(approximation_degree)
    seed_transpiler = _parse_seed_transpiler(seed_transpiler)

    pm_options = {
        "target": target,
        "basis_gates": basis_gates,
        "coupling_map": coupling_map,
        "instruction_durations": instruction_durations,
        "timing_constraints": timing_constraints,
        "layout_method": layout_method,
        "routing_method": routing_method,
        "translation_method": translation_method,
        "scheduling_method": scheduling_method,
        "approximation_degree": approximation_degree,
        "seed_transpiler": seed_transpiler,
        "unitary_synthesis_method": unitary_synthesis_method,
        "unitary_synthesis_plugin_config": unitary_synthesis_plugin_config,
        "initial_layout": initial_layout,
        "hls_config": hls_config,
        "init_method": init_method,
        "optimization_method": optimization_method,
        "qubits_initially_zero": qubits_initially_zero,
    }

    if backend is not None:
        pm_options["_skip_target"] = _skip_target
        pm_config = PassManagerConfig.from_backend(backend, **pm_options)
    else:
        pm_config = PassManagerConfig(**pm_options)

    pm_config._is_clifford_t = is_clifford_t_basis(
        basis_gates=pm_config.basis_gates, target=pm_config.target
    )

    if optimization_level is None:
        pm=StagedPassManager()
        return pm

    if optimization_level == 0:
        pm = level_0_pass_manager(pm_config)
    elif optimization_level == 1:
        pm = level_1_pass_manager(pm_config)
    elif optimization_level == 2:
        pm = level_2_pass_manager(pm_config)
    elif optimization_level == 3:
        pm = level_3_pass_manager(pm_config)
    else:
        raise ValueError(f"Invalid optimization level {optimization_level}")
    return pm


def _parse_basis_gates(basis_gates, backend):
    standard_gates = get_standard_gate_name_mapping()
    # 默认将控制流门添加到基础门集合和名称映射中。
    default_gates = {"measure", "delay", "reset"}.union(CONTROL_FLOW_OP_NAMES)
    name_mapping = get_control_flow_name_mapping()
    try:
        instructions = set(basis_gates)
        for name in default_gates:
            if name not in instructions:
                instructions.add(name)
    except TypeError:
        instructions = None

    if backend is None:
        # 检查是否存在自定义指令。
        if instructions is None:
            return None, name_mapping

        for inst in instructions:
            if inst not in standard_gates and inst not in default_gates:
                raise ValueError(
                    f"Providing non-standard gates ({inst}) through the ``basis_gates`` "
                    "argument is not allowed. Use the ``target`` parameter instead. "
                    "You can build a target instance using ``Target.from_configuration()`` and provide "
                    "custom gate definitions with the ``custom_name_mapping`` argument."
                )

        return list(instructions), name_mapping

    instructions = instructions or backend.operation_names
    name_mapping.update(
        {name: backend.target.operation_from_name(name) for name in backend.operation_names}
    )

    # 检查自定义指令
    for inst in instructions:
        if inst not in standard_gates and inst not in default_gates:
            if inst not in backend.operation_names:
                # 当自定义指令来自 backend 时不抛出错误
                # （在 BasicSimulator 中是常见情况）
                raise ValueError(
                    f"Providing non-standard gates ({inst}) through the ``basis_gates`` "
                    "argument is not allowed. Use the ``target`` parameter instead. "
                    "You can build a target instance using ``Target.from_configuration()`` and provide "
                    "custom gate definitions with the ``custom_name_mapping`` argument."
                )

    return list(instructions) if instructions else None, name_mapping


def _parse_dt(dt, backend):
    if dt is None and backend is not None:
        dt = backend.target.dt
    return dt


def _parse_coupling_map(coupling_map, backend):
    if coupling_map is None and backend is not None:
        coupling_map = backend.coupling_map

    # coupling_map 可以为 None，或是列表嵌套列表，例如 [[0, 1], [2, 1]]
    if coupling_map is None or isinstance(coupling_map, CouplingMap):
        return coupling_map
    if isinstance(coupling_map, list) and all(
        isinstance(i, list) and len(i) == 2 for i in coupling_map
    ):
        return CouplingMap(coupling_map)
    else:
        raise TranspilerError(
            "Only a single input coupling map can be used with generate_preset_pass_manager()."
        )


def _parse_instruction_durations(backend, dt):
    """Create a list of ``InstructionDuration``s populated from the backend."""
    final_durations = InstructionDurations()
    backend_durations = InstructionDurations()
    if backend is not None:
        backend_durations = backend.instruction_durations
    final_durations.update(backend_durations, dt or backend_durations.dt)
    return final_durations


def _parse_timing_constraints(backend):
    if backend is None:
        return None
    else:
        return backend.target.timing_constraints()


def _parse_initial_layout(initial_layout):
    # initial_layout 可以为 None，或整数列表，例如 [0, 5, 14]；
    # 也可以是元组/None 列表，例如 [qr[0], None, qr[1]]，或字典，例如 {qr[0]: 0}。
    if initial_layout is None or isinstance(initial_layout, Layout):
        return initial_layout
    if isinstance(initial_layout, dict):
        return Layout(initial_layout)
    initial_layout = list(initial_layout)
    if all(phys is None or isinstance(phys, Qubit) for phys in initial_layout):
        return Layout.from_qubit_list(initial_layout)
    return initial_layout


def _parse_approximation_degree(approximation_degree):
    if approximation_degree is None:
        return None
    if approximation_degree < 0.0 or approximation_degree > 1.0:
        raise TranspilerError("Approximation degree must be in [0.0, 1.0]")
    return approximation_degree


def _parse_seed_transpiler(seed_transpiler):
    if seed_transpiler is None:
        return None
    if not isinstance(seed_transpiler, int) or seed_transpiler < 0:
        raise ValueError("Expected non-negative integer as seed for transpiler.")
    return seed_transpiler
