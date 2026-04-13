"""
将 BackendConfiguration 和 BackendProperties 模型 (BackendV1) 转换为 Target 模型 (BackendV2)。
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, TYPE_CHECKING

from qiskit.circuit.controlflow import (
    CONTROL_FLOW_OP_NAMES,
    ForLoopOp,
    IfElseOp,
    SwitchCaseOp,
    WhileLoopOp,
)
from qiskit.circuit.gate import Gate
from qiskit.circuit import Instruction
from qiskit.circuit.library.standard_gates import get_standard_gate_name_mapping
from qiskit.circuit.parameter import Parameter
from qiskit.providers.backend import QubitProperties
from qiskit_ibm_runtime.models.exceptions import BackendPropertyError
from qiskit.transpiler.target import InstructionProperties, Target

if TYPE_CHECKING:
    # 延迟导入以避免运行时循环依赖；仅用于类型注解
    from ..backend import BackendConfiguration, BackendProperties

from ..utils.utils import is_fractional_gate


logger = logging.getLogger(__name__)


def convert_to_target(  # type: ignore[no-untyped-def]
    configuration: BackendConfiguration,
    properties: BackendProperties = None,
    *,
    include_control_flow: bool = True,
    include_fractional_gates: bool = True,
    custom_name_mapping: dict[str, Any] | None = None,
    add_delay: bool = True,
    filter_faulty: bool = True,
    **kwargs,
) -> Target:
    """从后端数据集中解码得到转译器的 ``Target``。

    该函数从旧有的中间对象（例如 :class:`.BackendProperties` 和 :class:`.BackendConfiguration`）生成一个 :class:`.Target` 实例。这些输入对象属旧的 :class:`.BackendV1` 模型的组成部分。

    Args:
        configuration: 后端配置，类型为 ``BackendConfiguration``
        properties: 后端属性字典或 ``BackendProperties``
        include_control_flow: 若设为 True，则包含控制流指令。
        include_fractional_gates: 若设为 True，则包含分数门 (fractional gates)。
        custom_name_mapping: 对于不在 Qiskit Standard Gate 名称映射中的操作，
            必须提供名称映射，否则该操作将在生成的 ``Target`` 中被忽略。
        add_delay: 若为 True，则将 ``delay`` 添加到指令集中。
        filter_faulty: 若为 True，则过滤掉不可用/故障的量子比特。

    Returns:
        一个 ``Target`` 实例。
    """
    if "defaults" in kwargs:
        warnings.warn(
            "Backend defaults have been completely from removed IBM Backends. They will be ignored."
        )

    required = ["measure", "delay", "reset"]

    # 加载 qiskit 对象表示
    qiskit_inst_mapping = get_standard_gate_name_mapping()
    if custom_name_mapping:
        qiskit_inst_mapping.update(custom_name_mapping)

    qiskit_control_flow_mapping = {
        "if_else": IfElseOp,
        "while_loop": WhileLoopOp,
        "for_loop": ForLoopOp,
        "switch_case": SwitchCaseOp,
    }

    in_data = {"num_qubits": configuration.n_qubits}

    # 解析全局配置属性
    if hasattr(configuration, "dt"):
        in_data["dt"] = configuration.dt  # type: ignore[assignment]
    if hasattr(configuration, "timing_constraints"):
        in_data.update(configuration.timing_constraints)

    # 从后端配置创建指令属性占位符
    basis_gates = set(getattr(configuration, "basis_gates", []))
    supported_instructions = set(getattr(configuration, "supported_instructions", []))
    instruction_signatures = getattr(configuration, "instruction_signatures", [])
    gate_configs = {gate.name: gate for gate in configuration.gates}
    all_instructions = set.union(
        basis_gates,
        set(required),
        supported_instructions.intersection(CONTROL_FLOW_OP_NAMES),
    )

    inst_name_map = {}

    faulty_ops = set()
    faulty_qubits = set()
    unsupported_instructions = []

    # 创建名称到 qiskit 指令对象表示的映射
    for name in all_instructions:
        if name in qiskit_control_flow_mapping:
            if not include_control_flow:
                # Remove name if this is control flow and dynamic circuits feature is disabled.
                logger.info(
                    "Control flow %s is found but the dynamic circuits are disabled for this backend. "
                    "This instruction is excluded from the backend Target.",
                    name,
                )
                unsupported_instructions.append(name)
            continue
        if name in qiskit_inst_mapping:
            qiskit_gate = qiskit_inst_mapping[name]
            if (not include_fractional_gates) and is_fractional_gate(qiskit_gate):
                # Remove name if this is fractional gate and fractional gate feature is disabled.
                logger.info(
                    "Gate %s is found but the fractional gates are disabled for this backend. "
                    "This gate is excluded from the backend Target.",
                    name,
                )
                unsupported_instructions.append(name)
                continue
            inst_name_map[name] = qiskit_gate
        elif name in gate_configs:
            # GateConfig 模型用于翻译 QASM 操作码。
            # 它自身不包含量子定义，因此 qiskit 转译器在量子域不会对其进行优化。
            # 通常 GateConfig 的对应项应存在于 qiskit 命名空间中，所以这种情况较少发生。
            this_config = gate_configs[name]
            params = list(map(Parameter, getattr(this_config, "parameters", [])))
            coupling_map = getattr(this_config, "coupling_map", [])
            inst_name_map[name] = Gate(
                name=name,
                num_qubits=len(coupling_map[0]) if coupling_map else 0,
                params=params,
            )
        else:
            warnings.warn(
                f"No gate definition for {name} can be found and is being excluded "
                "from the generated target. You can use `custom_name_mapping` to provide "
                "a definition for this operation.",
                RuntimeWarning,
            )
            unsupported_instructions.append(name)

    for name in unsupported_instructions:
        all_instructions.remove(name)

    # Create name to qiskit-ibm-runtime instruction object repr mapping

    for signature in instruction_signatures:
        name = signature.get("name")
        num_qubits = signature.get("num_qubits")
        num_clbits = signature.get("num_clbits")
        param_names = signature.get("parameters")
        # Add generic parameter name
        params = [Parameter(name) for name in param_names]

        instruction = Instruction(
            name=name, num_qubits=num_qubits, num_clbits=num_clbits, params=params
        )
        inst_name_map[name] = instruction
        all_instructions.add(name)

    # 创建指令属性占位符
    # 如果没有任何赋值，properties 的值为 None，
    # 这表示一个全局指令，可应用于任意量子比特集合。
    # 注意 None 的语义不同于空字典。详见 Target.add_instruction 的 API 文档。
    prop_name_map = dict.fromkeys(all_instructions)

    for name in all_instructions:
        if name in gate_configs:
            if coupling_map := getattr(gate_configs[name], "coupling_map", None):
                # Respect operational qubits that gate configuration defines
                # This ties instruction to particular qubits even without properties information.
                # Note that each instruction is considered to be ideal unless
                # its spec (e.g. error, duration) is bound by the properties object.
                prop_name_map[name] = dict.fromkeys(map(tuple, coupling_map))

    # 填充指令属性
    if properties:

        def _get_value(prop_dict: dict, prop_name: str) -> Any:
            if ndval := prop_dict.get(prop_name, None):
                return ndval[0]
            return None

    # is_qubit_operational 是较为昂贵的操作，因此先进行预缓存
        faulty_qubits = {
            q for q in range(configuration.num_qubits) if not properties.is_qubit_operational(q)
        }

        qubit_properties = []
        for qi in range(0, configuration.num_qubits):
            # TODO: 可能需要处理故障量子比特，因为故障量子比特的属性报告没有意义。
            try:
                prop_dict = properties.qubit_property(qubit=qi)
            except KeyError:
                continue
            qubit_properties.append(
                QubitProperties(
                    t1=prop_dict.get("T1", (None, None))[0],  # type: ignore[arg-type, union-attr]
                    t2=prop_dict.get("T2", (None, None))[0],  # type: ignore[arg-type, union-attr]
                    frequency=prop_dict.get(  # type: ignore[arg-type, union-attr]
                        "frequency", (None, None)
                    )[0],
                )
            )
        in_data["qubit_properties"] = qubit_properties  # type: ignore[assignment]

        for name in all_instructions:
            try:
                for qubits, param_dict in properties.gate_property(
                    name
                ).items():  # type: ignore[arg-type, union-attr]
                    if filter_faulty and (
                        set.intersection(faulty_qubits, qubits)
                        or not properties.is_gate_operational(name, qubits)  # type: ignore[arg-type]
                    ):
                        try:
                            # Qubits might be pre-defined by the gate config
                            # However properties objects says the qubits is non-operational
                            del prop_name_map[name][qubits]
                        except KeyError:
                            pass
                        faulty_ops.add((name, qubits))
                        continue
                    if prop_name_map[name] is None:
                        # 该指令被绑定到特定量子比特
                        # 即没有提供 gate config，且该指令被定义为全局指令。
                        prop_name_map[name] = {}
                    prop_name_map[name][qubits] = InstructionProperties(
                        error=_get_value(param_dict, "gate_error"),  # type: ignore[arg-type]
                        duration=_get_value(param_dict, "gate_length"),  # type: ignore[arg-type]
                    )
                if isinstance(prop_name_map[name], dict) and any(
                    v is None for v in prop_name_map[name].values()
                ):
                    # Properties 仅为部分量子比特提供门属性
                    # 相关的量子比特集合可能在 gate config 中定义
                    logger.info(
                        "Gate properties of instruction %s are not provided for every qubits. "
                        "This gate is ideal for some qubits and the rest is with finite error. "
                        "Created backend target may confuse error-aware circuit optimization.",
                        name,
                    )
            except BackendPropertyError:
                # 该门未报告任何属性
                continue

    # 测量指令的属性保存在量子比特属性中
        prop_name_map["measure"] = {}

        for qubit_idx in range(configuration.num_qubits):
            if filter_faulty and (qubit_idx in faulty_qubits):
                continue
            qubit_prop = properties.qubit_property(qubit_idx)
            prop_name_map["measure"][(qubit_idx,)] = InstructionProperties(
                error=_get_value(qubit_prop, "readout_error"),  # type: ignore[arg-type]
                duration=_get_value(qubit_prop, "readout_length"),  # type: ignore[arg-type]
            )

    for op in required:
        # 将必需操作映射到每个可操作的量子比特
        if prop_name_map[op] is None:
            prop_name_map[op] = {
                (q,): None
                for q in range(configuration.num_qubits)
                if not filter_faulty or (q not in faulty_qubits)
            }

    # 将解析后的属性添加到 target
    target = Target(**in_data)
    for inst_name in all_instructions:
        if inst_name == "delay" and not add_delay:
            continue
        if inst_name in qiskit_control_flow_mapping:
            # Control flow operator doesn't have gate property.
            target.add_instruction(
                instruction=qiskit_control_flow_mapping[inst_name],
                name=inst_name,
            )
        else:
            target.add_instruction(
                instruction=inst_name_map[inst_name],
                properties=prop_name_map.get(inst_name, None),
                name=inst_name,
            )
    return target