"""创建GJQBackend实例所需的工具函数"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import traceback

import dateutil.parser
from qiskit.circuit.library.standard_gates import get_standard_gate_name_mapping

from .converters import utc_to_local_all
from .utils import is_fractional_gate

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..backend import BackendProperties, QasmBackendConfiguration


def configuration_from_server_data(
    raw_config: dict,
    use_fractional_gates: bool | None = False,
) -> QasmBackendConfiguration | None:
    """根据服务器返回的原始数据创建一个QasmBackendConfiguration对象。

    参数：
        raw_config: 原始配置数据。
        instance: 服务实例。
        use_fractional_gates: 若设为 True, 则允许 backend 包含分数门.
    返回：
        QasmBackendConfiguration 对象。
    """
    # 确保是一个字典类型，否则无法正确解析配置数据
    if not isinstance(raw_config, dict):
        logger.warning(
            "Error retrieving backend information, some backends may not be available "
            "(检索后端信息时发生错误，部分后端可能无法使用)"
        )
        return None
    try:
        _normalize_simulator_configuration(raw_config)
        if raw_config.get("online_date"):
            raw_config["online_date"] = dateutil.parser.isoparse(raw_config["online_date"])
        filter_raw_configuration(raw_config, use_fractional_gates=use_fractional_gates)
        # 延迟导入以避免与 src.backend 中的模块产生循环导入
        from ..backend import QasmBackendConfiguration

        return QasmBackendConfiguration.from_dict(raw_config)
    except Exception:
        logger.warning(
            "Remote backend %s could not be instantiated due to invalid server-side configuration "
            "(由于服务端配置无效，远程后端 %s 无法被实例化)",
            raw_config.get("backend_name", raw_config.get("name", "unknown")),
            raw_config.get("backend_name", raw_config.get("name", "unknown")),
        )
        logger.debug("Invalid configuration (无效的配置): %s", traceback.format_exc())
    return None


def _normalize_simulator_configuration(raw_config: dict) -> None:
    """补齐模拟器配置示例中为 null 但 SDK 模型需要的字段。"""
    if not raw_config.get("simulator"):
        return

    basis_gates = raw_config.get("basis_gates") or []
    if raw_config.get("gates") is None:
        raw_config["gates"] = [
            {
                "name": gate_name,
                "parameters": ["theta"] if gate_name in {"rx", "ry", "rz"} else [],
                "qasm_def": None,
            }
            for gate_name in basis_gates
        ]
    if raw_config.get("coupling_map") is None:
        raw_config["coupling_map"] = []


def filter_raw_configuration(raw_config: dict, use_fractional_gates: bool | None = False) -> None:
    """过滤原始配置数据以排除分数门(fractional gates).

    Args:
        use_fractional_gates: 设置为 True 可以允许后端包含分数门(fractional gates).
    """
    if use_fractional_gates is None:
        return

    gate_map = get_standard_gate_name_mapping()
    if not use_fractional_gates:
        if raw_config.get("basis_gates") is not None:
            raw_config["basis_gates"] = [
                g
                for g in raw_config["basis_gates"]
                if g not in gate_map or not is_fractional_gate(gate_map[g])
            ]
        if raw_config.get("gates") is not None:
            raw_config["gates"] = [
                g
                for g in raw_config["gates"]
                if g.get("name") not in gate_map or not is_fractional_gate(gate_map[g.get("name")])
            ]
        if raw_config.get("supported_instructions") is not None:
            raw_config["supported_instructions"] = [
                i
                for i in raw_config["supported_instructions"]
                if i not in gate_map or not is_fractional_gate(gate_map[i])
            ]


def properties_from_server_data(
    properties: dict, use_fractional_gates: bool | None = False
) -> BackendProperties:
    """解码后端属性.

    参数: 
        properties: 原始属性数据.
        use_fractional_gates: 设置为 True 时, 允许后端包含分数门(fractional gates)。

    Returns:
        一个 BackendProperties 实例.
    """
    gate_map = get_standard_gate_name_mapping()

    if "gates" in properties and isinstance(properties["gates"], list):
        if use_fractional_gates is not None and not use_fractional_gates:
            properties["gates"] = [
                g
                for g in properties["gates"]
                if g.get("name") not in gate_map or not is_fractional_gate(gate_map[g.get("name")])
            ]

    if isinstance(properties["last_update_date"], str):
        properties["last_update_date"] = dateutil.parser.isoparse(properties["last_update_date"])
        for qubit in properties["qubits"]:
            for nduv in qubit:
                nduv["date"] = dateutil.parser.isoparse(nduv["date"])
        for gate in properties["gates"]:
            for param in gate["parameters"]:
                param["date"] = dateutil.parser.isoparse(param["date"])
        for gen in properties["general"]:
            gen["date"] = dateutil.parser.isoparse(gen["date"])

    properties = utc_to_local_all(properties)
    # 延迟导入以避免循环导入问题
    from ..backend import BackendProperties

    return BackendProperties.from_dict(properties)
