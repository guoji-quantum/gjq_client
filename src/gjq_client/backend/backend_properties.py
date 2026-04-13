"""后端属性类."""

import copy
import datetime
from typing import Any, TypeVar
from collections.abc import Iterable
import dateutil.parser

from qiskit.utils.units import apply_prefix

from qiskit_ibm_runtime.models.exceptions import BackendPropertyError

PropertyT = tuple[Any, datetime.datetime]
NduvT = TypeVar("NduvT", bound="Nduv")
GatePropertiesT = TypeVar("GatePropertiesT", bound="GateProperties")
BackendPropertiesT = TypeVar("BackendPropertiesT", bound="BackendProperties")


class Nduv:
    """表示 name-date-unit-value 的类.

    属性:
        date: 日期.
        name: 名称.
        unit: 单位.
        value: 值.
    """

    def __init__(self, date: datetime.datetime, name: str, unit: str, value: float) -> None:
        """初始化 name-date-unit-value 对象.

        参数:
            date (datetime.datetime): 日期字段.
            name (str): 名称字段.
            unit (str): Nduv 单位.
            value (float): Nduv 的值.
        """
        self.date = date
        self.name = name
        self.unit = unit
        self.value = value

    @classmethod
    def from_dict(cls: type[NduvT], data: dict[str, Any]) -> NduvT:
        """从字典创建一个新的 Nduv 对象.

        参数:
            data (dict): 一个字典, 用于表示要创建的 Nduv.

        返回:
            Nduv: 从输入字典创建的 Nduv.
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """返回对象的字典格式表示.

        返回:
            dict: Nduv 的字典格式.
        """
        out_dict = {
            "date": self.date,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
        }
        return out_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Nduv):
            if self.to_dict() == other.to_dict():
                return True
        return False

    def __repr__(self) -> str:
        return f"Nduv({repr(self.date)}, {self.name}, {self.unit}, {self.value})"


class GateProperties:
    """表示门的属性类.

    属性:
        qubits: 量子比特.
        gate: 门名称.
        parameters: 参数.
    """

    _data: dict[Any, Any] = {}

    def __init__(self, qubits: list[int], gate: str, parameters: list[Nduv], **kwargs: Any) -> None:
        """初始化 :class:GateProperties对象.

        参数:
            qubits (list): 表示量子比特的整数列表.
            gate (str): 门的名称.
            parameters (list): :class:Nduv实例列表, 表示门的 name-date-unit-value.
            kwargs: 可选的附加字段.
        """
        self._data = {}
        self.qubits = qubits
        self.gate = gate
        self.parameters = parameters
        self._data.update(kwargs)

    def __getattr__(self, name: str) -> str:
        try:
            return self._data[name]
        except KeyError as ex:
            raise AttributeError(f"Attribute {name} is not defined") from ex

    @classmethod
    def from_dict(cls: type[GatePropertiesT], data: dict[str, Any]) -> GatePropertiesT:
        """从字典创建一个新的 Gate 对象.

        参数:
            data (dict): 一个字典, 用于表示要创建的 Gate.

        返回:
            GateProperties: 输入字典中的 Nduv.
        """
        in_data: dict[Any, Any] = {}
        for key, value in data.items():
            if key == "parameters":
                in_data[key] = list(map(Nduv.from_dict, value))
            else:
                in_data[key] = value
        return cls(**in_data)

    def to_dict(self) -> dict[str, Any]:
        """返回 BackendStatus 的字典格式表示.

        返回:
            dict: Gate 的字典格式.
        """
        out_dict: dict[str, Any] = {
            "qubits": self.qubits,
            "gate": self.gate,
            "parameters": [x.to_dict() for x in self.parameters],
        }
        out_dict.update(self._data)
        return out_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, GateProperties):
            if self.to_dict() == other.to_dict():
                return True
        return False


Gate = GateProperties


class BackendProperties:
    """表示后端属性的类.

    该类用于保存由提供方测量得到的后端属性. 所有属性均为可选提供, 这些属性可以描述量子比特、量子门, 或后端的其他通用属性.
    """

    _data: dict = {}

    def __init__(
        self,
        backend_name: str,
        backend_version: str,
        last_update_date: datetime.datetime | str,
        qubits: list,
        gates: list,
        general: list,
        **kwargs: Any,
    ) -> None:
        """初始化 BackendProperties 实例.

        参数:
            backend_name (str): 后端名称.
            backend_version (str): 后端版本, 格式为 X.Y.Z.
            last_update_date (datetime.datetime 或 str): 属性最后更新的日期/时间, 如果为 str, 则必须为 ISO 格式.
            qubits (list): 系统量子比特参数, 为 :class:`Nduv` 实例的列表的列表.
            gates (list): 系统量子门参数, 为 :class:`GateProperties` 对象的列表.
            general (list): 通用参数, 为 :class:`Nduv` 对象的列表.
            kwargs: 可选的附加字段.
        """
        self._data = {}
        self.backend_name = backend_name
        self.backend_version = backend_version
        if isinstance(last_update_date, str):
            last_update_date = dateutil.parser.isoparse(last_update_date)
        self.last_update_date = last_update_date
        self.general = general
        self.qubits = qubits
        self.gates = gates

        self._qubits = {}
        for qubit, props in enumerate(qubits):
            formatted_props = {}
            for prop in props:
                value = self._apply_prefix(prop.value, prop.unit)
                formatted_props[prop.name] = (value, prop.date)
                self._qubits[qubit] = formatted_props

        self._gates: dict = {}
        for gate in gates:
            if gate.gate not in self._gates:
                self._gates[gate.gate] = {}
            formatted_props = {}
            for param in gate.parameters:
                value = self._apply_prefix(param.value, param.unit)
                formatted_props[param.name] = (value, param.date)
            self._gates[gate.gate][tuple(gate.qubits)] = formatted_props
        self._data.update(kwargs)

    def __getattr__(self, name: str) -> str:
        try:
            return self._data[name]
        except KeyError as ex:
            raise AttributeError(f"Attribute {name} is not defined") from ex

    @classmethod
    def from_dict(cls: type[BackendPropertiesT], data: dict) -> BackendPropertiesT:
        """从字典创建一个新的 BackendProperties 对象.

        参数:
            data (dict): 一个字典, 表示要创建的 BackendProperties, 格式与 :meth:`to_dict` 输出一致.

        返回:
            BackendProperties: 输入字典生成的 BackendProperties.
        """
        in_data = copy.copy(data)
        backend_name = in_data.pop("backend_name")
        backend_version = in_data.pop("backend_version")
        last_update_date = in_data.pop("last_update_date")
        qubits = []
        for qubit in in_data.pop("qubits"):
            nduvs = []
            for nduv in qubit:
                nduvs.append(Nduv.from_dict(nduv))
            qubits.append(nduvs)
        gates = [GateProperties.from_dict(x) for x in in_data.pop("gates")]
        general = [Nduv.from_dict(x) for x in in_data.pop("general")]
        return cls(
            backend_name, backend_version, last_update_date, qubits, gates, general, **in_data
        )

    def to_dict(self) -> dict:
        """返回 BackendProperties 的字典格式表示.

        返回:
            dict: BackendProperties 的字典格式.
        """
        out_dict: dict = {
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "last_update_date": self.last_update_date,
        }
        out_dict["qubits"] = []
        for qubit in self.qubits:
            qubit_props = []
            for item in qubit:
                qubit_props.append(item.to_dict())
            out_dict["qubits"].append(qubit_props)
        out_dict["gates"] = [x.to_dict() for x in self.gates]
        out_dict["general"] = [x.to_dict() for x in self.general]
        out_dict.update(self._data)
        return out_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, BackendProperties):
            if self.to_dict() == other.to_dict():
                return True
        return False

    def gate_property(
        self,
        gate: str,
        qubits: int | Iterable[int] = None,
        name: str = None,
    ) -> dict[tuple[int, ...], dict[str, PropertyT]] | dict[str, PropertyT] | PropertyT:
        """
        返回指定门的属性.

        参数:
            gate: 门的名称.
            qubits: 要查找属性的量子比特.
            name: 可选, 用于指定要返回的门属性名称.

        返回:
            门属性, 格式为 (值, 测量时间) 的元组.

        异常:
            BackendPropertyError: 如果未找到属性, 或指定了 name 但未指定 qubit.
        """
        try:
            result = self._gates[gate]
            if qubits is not None:
                if isinstance(qubits, int):
                    qubits = (qubits,)
                result = result[tuple(qubits)]
                if name:
                    result = result[name]
            elif name:
                raise BackendPropertyError(f"Provide qubits to get {name} of {gate}")
        except KeyError as ex:
            raise BackendPropertyError(f"Could not find the desired property for {gate}") from ex
        return result

    def faulty_qubits(self) -> list:
        """返回故障量子比特的列表."""
        faulty = []
        for qubit in self._qubits:
            if not self.is_qubit_operational(qubit):
                faulty.append(qubit)
        return faulty

    def faulty_gates(self) -> list:
        """返回故障门的列表."""
        faulty = []
        for gate in self.gates:
            if not self.is_gate_operational(gate.gate, gate.qubits):
                faulty.append(gate)
        return faulty

    def is_gate_operational(self, gate: str, qubits: int | Iterable[int] = None) -> bool:
        """
        返回指定门的可用状态.

        参数:
            gate: 门的名称.
            qubits: 要查找可用状态的量子比特.

        返回:
            bool: 指定门的可用状态. True 表示可用, False 表示不可用.
        """
        properties = self.gate_property(gate, qubits)
        if "operational" in properties:
            return bool(properties["operational"][0])  # type: ignore[index, call-overload]
        return True  # if property operational not existent, then True.

    def gate_error(self, gate: str, qubits: int | Iterable[int]) -> float:
        """
        返回后端属性中的门误差估计值.

        参数:
            gate: 要获取误差的门.
            qubits: 该门对应的具体量子比特.

        返回:
            指定门和量子比特的门误差.
        """
        return self.gate_property(gate, qubits, "gate_error")[0]  # type: ignore[index, return-value]

    def gate_length(self, gate: str, qubits: int | Iterable[int]) -> float:
        """
        返回门的持续时间(单位:秒).

        参数:
            gate: 要获取持续时间的门.
            qubits: 该门对应的具体量子比特.

        返回:
            指定门和量子比特的门持续时间.
        """
        return self.gate_property(gate, qubits, "gate_length")[0]  # type: ignore[index, return-value]

    def qubit_property(
        self,
        qubit: int,
        name: str = None,
    ) -> dict[str, PropertyT] | PropertyT:
        """
        返回指定量子比特的属性.

        参数:
            qubit: 要查找属性的量子比特.
            name: 可选, 用于指定层级中的具体属性.

        返回:
            量子比特属性, 格式为 (值, 测量时间) 的元组.

        异常:
            BackendPropertyError: 如果未找到属性.
        """
        try:
            result = self._qubits[qubit]
            if name is not None:
                result = result[name]  # type: ignore[assignment]
        except KeyError as ex:
            formatted_name = "y '" + name + "'" if name else "ies"
            raise BackendPropertyError(
                f"Couldn't find the propert{formatted_name} for qubit {qubit}."
            ) from ex
        return result

    def t1(self, qubit: int) -> float: 
        """
        返回指定量子比特的 T1 时间.

        参数:
            qubit: 要返回 T1 时间的量子比特.

        返回:
            指定量子比特的 T1 时间.
        """
        return self.qubit_property(qubit, "T1")[0]  

    def t2(self, qubit: int) -> float:  
        """
        返回指定量子比特的 T2 时间.

        参数:
            qubit: 要返回 T2 时间的量子比特.

        返回:
            指定量子比特的 T2 时间.
        """
        return self.qubit_property(qubit, "T2")[0]  

    def frequency(self, qubit: int) -> float:
        """
        返回指定量子比特的频率.

        参数:
            qubit: 要返回频率的量子比特.

        返回:
            指定量子比特的频率.
        """
        return self.qubit_property(qubit, "frequency")[0]  

    def readout_error(self, qubit: int) -> float:
        """
        返回指定量子比特的读出误差.

        参数:
            qubit: 要返回读出误差的量子比特.

        返回:
            指定量子比特的读出误差.
        """
        return self.qubit_property(qubit, "readout_error")[0]  

    def readout_length(self, qubit: int) -> float:
        """
        返回指定量子比特的读出时长(秒).

        参数:
            qubit: 要返回读出时长的量子比特.

        返回:
            指定量子比特的读出时长.
        """
        return self.qubit_property(qubit, "readout_length")[0] 

    def is_qubit_operational(self, qubit: int) -> bool:
        """
        返回指定量子比特的可用状态.

        参数:
            qubit: 要返回可用状态的量子比特.

        返回:
            指定量子比特的可用状态.
        """
        properties = self.qubit_property(qubit)
        if "operational" in properties:
            return bool(properties["operational"][0])  
        return True  

    def _apply_prefix(self, value: float, unit: str) -> float:
        """
        给定一个 SI 单位前缀和数值, 将前缀应用于数值以转换为标准 SI 单位.

        参数:
            value: 需要应用前缀的数值.
            unit: 字符串前缀.

        返回:
            转换后的数值.

        异常:
            BackendPropertyError: 如果单位无法识别.
        """
        try:
            return apply_prefix(value, unit)
        except Exception as ex:
            raise BackendPropertyError(f"Could not understand units: {unit}") from ex
