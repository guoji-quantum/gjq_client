"""QasmBackendConfiguration类"""
import datetime
import copy
from typing import Any, TypeVar

from ..utils import GJQBaseError

GateConfigT = TypeVar("GateConfigT", bound="GateConfig")
UchannelLOT = TypeVar("UchannelLOT", bound="UchannelLO")  # pylint: disable=[invalid-name]
QasmBackendConfigurationT = TypeVar("QasmBackendConfigurationT", bound="QasmBackendConfiguration")


class GateConfig:
    """表示量子门配置的类
 
     属性:
        name: 该量子门在 OpenQASM 中引用时使用的名称.
        parameters: 量子门参数的变量名列表(如果存在参数).
        qasm_def: 该量子门在 OpenQASM 2 中的定义，使用基本门 U 和 CX 表示.
    """

    def __init__(
        self,
        name: str,
        parameters: list[str],
        qasm_def: str,
        coupling_map: list = None,
        latency_map: list = None,
        conditional: bool = None,
        description: str = None,
    ):
        """初始化 GateConfig 对象

        参数：
            name (str)：该量子门在 OpenQASM 中引用时使用的名称.
            parameters (list)：量子门参数的变量名列表(如果存在参数)，以字符串列表形式表示.
            qasm_def (str)：该量子门在 OpenQASM 2 中的定义，使用基本门 U 和 CX 表示.
            coupling_map (list)：该量子门的可选耦合映射.其形式为由整数组成的列表的列表，表示该量子门可以作用的量子比特组合.
            latency_map (list)：该量子门的可选延迟映射.其形式为由 0 或 1 组成的整型列表的列表，表示一个维度为 len(coupling_map) x n_registers 的数组, 用于指定在该量子门上执行条件操作时各寄存器的延迟(1 表示快, 0 表示慢).
            conditional (bool): 可选参数, 指定该量子门是否支持条件操作(true/false).如果未指定, 则该量子门继承后端(backend)的 conditional 属性.
            description (str)：量子门操作的描述.
        """

        self.name = name
        self.parameters = parameters
        self.qasm_def = qasm_def
        if coupling_map:
            self.coupling_map = coupling_map
        if latency_map:
            self.latency_map = latency_map
        if conditional is not None:
            self.conditional = conditional
        if description is not None:
            self.description = description

    @classmethod
    def from_dict(cls: type[GateConfigT], data: dict[str, Any]) -> GateConfigT:
        """从字典创建 GateConfig 对象

        参数：
            data (dict)：一个字典，用于表示要创建的 GateConfig.其格式与 `to_dict` 方法输出的格式相同.

        返回值：
            GateConfig: 由输入字典生成的 GateConfig 对象.
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """返回 GateConfig 的字典格式表示.

        返回:
            dict: GateConfig 的字典形式.
        """
        out_dict: dict[str, Any] = {
            "name": self.name,
            "parameters": self.parameters,
            "qasm_def": self.qasm_def,
        }
        if hasattr(self, "coupling_map"):
            out_dict["coupling_map"] = self.coupling_map
        if hasattr(self, "latency_map"):
            out_dict["latency_map"] = self.latency_map
        if hasattr(self, "conditional"):
            out_dict["conditional"] = self.conditional
        if hasattr(self, "description"):
            out_dict["description"] = self.description
        return out_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, GateConfig):
            if self.to_dict() == other.to_dict():
                return True
        return False

    def __repr__(self) -> str:
        out_str = f"GateConfig({self.name}, {self.parameters}, {self.qasm_def}"
        for i in ["coupling_map", "latency_map", "conditional", "description"]:
            if hasattr(self, i):
                out_str += ", " + repr(getattr(self, i))
        out_str += ")"
        return out_str


class UchannelLO:
    """表示 U 通道本振(U Channel LO)的类

    属性：
        q: 该通道对应的量子比特(qubit).
        scal: 该通道的缩放系数.
    """

    def __init__(self, q: int, scale: complex) -> None:
        """初始化 UchannelLOSchema 对象

        参数：
            q (int)：该缩放系数对应的量子比特编号，必须大于等于 0
            scale (complex)：量子比特频率的缩放因子

        异常：
            GJQBaseError: 当 q 小于 0 时抛出
        """
        if q < 0:
            raise GJQBaseError("q must be >=0")
        self.q = q
        self.scale = scale

    @classmethod
    def from_dict(cls: type[UchannelLOT], data: dict[str, Any]) -> UchannelLOT:
        """从字典创建一个新的 UchannelLO 对象

        参数：
            data (dict)：用于表示要创建的 UchannelLO 的字典其格式与 to_dict 方法输出的格式相同

        返回：
            UchannelLO: 由输入字典生成的 UchannelLO 对象
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """返回 UChannelLO 的字典格式表示.

        返回:
            dict: UChannelLO 的字典形式.
        """
        out_dict: dict[str, Any] = {
            "q": self.q,
            "scale": self.scale,
        }
        return out_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, UchannelLO):
            if self.to_dict() == other.to_dict():
                return True
        return False

    def __repr__(self) -> str:
        return f"UchannelLO({self.q}, {self.scale})"


class QasmBackendConfiguration:
    """表示 OpenQASM 2.0 后端配置的类.

    属性：
        backend_name: 后端名称
        backend_version: 后端版本，格式为 X.Y.Z
        n_qubits: 量子比特数量
        basis_gates: 后端支持的基础门名称列表
        gates: 后端支持的基础门列表
        local: 后端是本地还是远程
        simulator: 后端是否为模拟器
        conditional: 后端是否支持条件操作
        open_pulse: 后端是否支持 OpenPulse
        memory: 后端是否支持 memory 功能
    """

    _data: dict[Any, Any] = {}

    def __init__(
        self,
        backend_name: str,
        backend_version: str,
        n_qubits: int,
        basis_gates: list,
        gates: list,
        local: bool,
        simulator: bool,
        conditional: bool,
        open_pulse: bool,
        memory: bool,
        coupling_map: list,
        meas_levels: list[int] = None,
        meas_kernels: list[str] = None,
        discriminators: list[str] = None,
        meas_map: list = None,
        supported_instructions: list[str] = None,
        dynamic_reprate_enabled: bool = False,
        rep_delay_range: list[float] = None,
        default_rep_delay: float = None,
        sample_name: str = None,
        n_registers: int = None,
        register_map: list = None,
        configurable: bool = None,
        credits_required: bool = None,
        online_date: datetime.datetime = None,
        display_name: str = None,
        description: str = None,
        tags: list = None,
        dt: float = None,
        dtm: float = None,
        processor_type: dict = None,
        parametric_pulses: list = None,
        **kwargs: Any,
    ):
        """初始化 QasmBackendConfiguration 对象

    参数：
        backend_name (str):  后端名称.
        backend_version (str):  后端版本, 格式为 X.Y.Z.
        n_qubits (int):  后端的量子比特数量.
        basis_gates (list):  后端支持的基础门名称字符串列表.
        gates (list):  后端基础门对应的 GateConfig 对象列表.
        local (bool):  若为 True 表示本地后端, False 表示远程后端.
        simulator (bool):  若为 True 表示该后端为模拟器.
        conditional (bool):  若为 True 表示后端支持条件操作.
        open_pulse (bool):  若为 True 表示后端支持 OpenPulse.
        memory (bool):  若为 True 表示后端支持 memory 功能.
        coupling_map (list):  设备的耦合映射.
        meas_levels:  支持的测量级别.
        meas_kernels:  支持的测量核(measurement kernels).
        discriminators:  支持的判别器(discriminators).
        meas_map (list):  复用测量的分组方式.
        supported_instructions (List[str]):  后端支持的指令列表.
        dynamic_reprate_enabled (bool):  是否支持动态设置程序之间的延迟(即通过 rep_delay 设置), 默认 False.
        rep_delay_range (List[float]):  二维列表, 定义后端支持的重复延迟范围(单位 μs).第一个元素为下限, 第二个元素为上限.当 dynamic_reprate_enabled=True 时通常会提供该参数.
        default_rep_delay (float):  当用户未指定且 dynamic_reprate_enabled=True 时使用的默认 rep_delay 值.
        sample_name (str):  后端的样本名称.
        n_registers (int):  用于反馈的寄存器槽数量(当 conditional 为 True 时).
        register_map (list):  维度为 n_qubits x n_registers 的数组, 指示某个量子比特是否可以将测量结果存入指定寄存器槽.
        configurable (bool):  若为 True 表示后端是可配置的(通常用于模拟器).
        credits_required (bool):  若为 True 表示运行任务需要消耗积分(credits).
        online_date (datetime.datetime):  设备上线时间.
        display_name (str):  后端的显示名称(备用名称).
        description (str):  后端的描述信息.
        tags (list):  用于描述后端的字符串标签列表.
        dt (float):  量子比特驱动通道的时间步长(单位:  纳秒).
        dtm (float):  测量驱动通道的时间步长(单位:  纳秒).
        processor_type (dict):  该后端的处理器类型, 格式为{"family": <str>, "revision": <str>, "segment": <str>}, 例如{"family": "Canary", "revision": "1.0", "segment": "A"}.
            - family:  处理器所属系列.
            - revision:  处理器版本号.
            - segment:  该处理器在更大芯片中的分段标识.
        parametric_pulses (list):  后端支持的脉冲形状列表, 例如:  ['gaussian', 'constant'].

        **kwargs:  其他可选字段.
        """
        self._data = {}

        self.backend_name = backend_name
        self.backend_version = backend_version
        self.n_qubits = n_qubits
        self.basis_gates = basis_gates
        self.gates = gates
        self.local = local
        self.simulator = simulator
        self.conditional = conditional
        self.open_pulse = open_pulse
        self.memory = memory
        self.coupling_map = coupling_map
        self.meas_levels = meas_levels
        self.meas_kernels = meas_kernels
        self.discriminators = discriminators
        if meas_map is not None:
            self.meas_map = meas_map
        if supported_instructions:
            self.supported_instructions = supported_instructions

        self.dynamic_reprate_enabled = dynamic_reprate_enabled
        if rep_delay_range:
            self.rep_delay_range = [_rd * 1e-6 for _rd in rep_delay_range]
        if default_rep_delay is not None:
            self.default_rep_delay = default_rep_delay * 1e-6 

        if sample_name is not None:
            self.sample_name = sample_name
        
        if n_registers:
            self.n_registers = 1
        # register_map 至少必须包含一个条目
        if register_map:
            self.register_map = register_map
        if configurable is not None:
            self.configurable = configurable
        if credits_required is not None:
            self.credits_required = credits_required
        if online_date is not None:
            self.online_date = online_date
        if display_name is not None:
            self.display_name = display_name
        if description is not None:
            self.description = description
        if tags is not None:
            self.tags = tags
        # 在此添加脉冲相关属性，因为某些后端并不完全符合 Qasm / Pulse 后端的划分
        if dt is not None:
            self.dt = dt * 1e-9
        if dtm is not None:
            self.dtm = dtm * 1e-9
        if processor_type is not None:
            self.processor_type = processor_type
        if parametric_pulses is not None:
            self.parametric_pulses = parametric_pulses

        if "qubit_lo_range" in kwargs:
            kwargs["qubit_lo_range"] = [
                [min_range * 1e9, max_range * 1e9]
                for (min_range, max_range) in kwargs["qubit_lo_range"]
            ]

        if "meas_lo_range" in kwargs:
            kwargs["meas_lo_range"] = [
                [min_range * 1e9, max_range * 1e9]
                for (min_range, max_range) in kwargs["meas_lo_range"]
            ]

        if "rep_times" in kwargs:
            kwargs["rep_times"] = [_rt * 1e-6 for _rt in kwargs["rep_times"]]

        self._data.update(kwargs)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError as ex:
            raise AttributeError(f"Attribute {name} is undefined") from ex

    @classmethod
    def from_dict(
        cls: type[QasmBackendConfigurationT], data: dict[str, Any]
    ) -> QasmBackendConfigurationT:
        """从字典创建一个新的 QasmBackendConfiguration 对象.

        参数：
            data (dict): 用于表示要创建的 GateConfig 的字典，其格式与 to_dict 方法输出的格式相同

        返回：
            GateConfig: 由输入字典生成的 GateConfig 对象
        """
        in_data: dict[str, Any] = copy.copy(data)
        gates = [GateConfig.from_dict(x) for x in in_data.pop("gates")]
        in_data["gates"] = gates
        return cls(**in_data)

    def to_dict(self) -> dict[str, Any]:
        """返回 BackendConfiguration 的字典格式表示.

        返回：
            dict: GateConfig 的字典形式.
        """
        out_dict: dict[str, Any] = {
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "n_qubits": self.n_qubits,
            "basis_gates": self.basis_gates,
            "gates": [x.to_dict() for x in self.gates],
            "local": self.local,
            "simulator": self.simulator,
            "conditional": self.conditional,
            "open_pulse": self.open_pulse,
            "memory": self.memory,
            "coupling_map": self.coupling_map,
            "dynamic_reprate_enabled": self.dynamic_reprate_enabled,
            "meas_levels": self.meas_levels,
            "meas_kernels": self.meas_kernels,
            "discriminators": self.discriminators,
        }
        if hasattr(self, "meas_map"):
            out_dict["meas_map"] = self.meas_map

        if hasattr(self, "supported_instructions"):
            out_dict["supported_instructions"] = self.supported_instructions

        if hasattr(self, "rep_delay_range"):
            out_dict["rep_delay_range"] = [_rd * 1e6 for _rd in self.rep_delay_range]
        if hasattr(self, "default_rep_delay"):
            out_dict["default_rep_delay"] = self.default_rep_delay * 1e6

        for kwarg in [
            "sample_name",
            "n_registers",
            "register_map",
            "configurable",
            "credits_required",
            "online_date",
            "display_name",
            "description",
            "tags",
            "dt",
            "dtm",
            "processor_type",
            "parametric_pulses",
        ]:
            if hasattr(self, kwarg):
                out_dict[kwarg] = getattr(self, kwarg)

        out_dict.update(self._data)

        if "dt" in out_dict: 
            out_dict["dt"] *= 1e9
        if "dtm" in out_dict:
            out_dict["dtm"] *= 1e9

        if "qubit_lo_range" in out_dict:
            out_dict["qubit_lo_range"] = [
                [min_range * 1e-9, max_range * 1e-9]
                for (min_range, max_range) in out_dict["qubit_lo_range"]
            ]

        if "meas_lo_range" in out_dict:
            out_dict["meas_lo_range"] = [
                [min_range * 1e-9, max_range * 1e-9]
                for (min_range, max_range) in out_dict["meas_lo_range"]
            ]

        if "rep_times" in out_dict:
            out_dict["rep_times"] = [_rt * 1e6 for _rt in out_dict["rep_times"]]

        return out_dict

    @property
    def num_qubits(self) -> int:
        """返回量子比特的数量.

        返回:
            int: 量子比特的数量
        """
        return self.n_qubits

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, QasmBackendConfiguration):
            if self.to_dict() == other.to_dict():
                return True
        return False

    def __contains__(self, item: str) -> bool:
        return item in self.__dict__


class BackendConfiguration(QasmBackendConfiguration):
    """用于表示抽象后端配置的向后兼容性适配层."""

    pass
