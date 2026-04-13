import logging
from typing import Any
from datetime import datetime as python_datetime
from copy import deepcopy
from enum import Enum, IntEnum

from qiskit import QuantumCircuit
from qiskit.transpiler.target import Target

from .backend import BackendV2 as Backend
from .options import Options
from .backend_status import BackendStatus
from .backend_properties import BackendProperties
from .backend_configuration import QasmBackendConfiguration, GateConfig

from ..gjq_runtime import gjq_runtime_service  

from ..client import RuntimeClient
from ..utils import (
    GJQBackendApiProtocolError,
    GJQBackendError,
)
from ..utils.backend_converter import convert_to_target

from ..utils.backend_decoder import (
    properties_from_server_data,
    configuration_from_server_data,
)
from ..utils.converters import local_to_utc

class MeasReturnType(str, Enum):
    """meas_return 允许的取值, 由旧版 PulseQobjConfig 对象定义, 但仍被 Result 使用."""

    AVERAGE = "avg"
    SINGLE = "single"


class MeasLevel(IntEnum):
    """MeasLevel 允许的取值, 由旧版 PulseQobjConfig 对象定义, 但仍被 Result 使用."""

    RAW = 0
    KERNELED = 1
    CLASSIFIED = 2


logger = logging.getLogger(__name__)

QOBJRUNNERPROGRAMID = "circuit-runner"
QASM3RUNNERPROGRAMID = "qasm3-runner"


class GJQBackend(Backend):
    """与量子真机后端交互的后端类.

        该类表示一个量子真机后端。其属性和方法提供有关该后端的信息。包含operational和pending_jobs 属性，分别表示该后端是否处于可运行状态，以及该后端在服务器队列中的任务数量：

        status = backend.status()
        is_operational = status.operational
        jobs_in_queue = status.pending_jobs

        以下是该类中可用的属性列表：
            name: 后端名称。
            backend_version: 后端版本。
            num_qubits: 量子比特数量。
            target: 后端对应的Target对象。
            basis_gates: 后端的基门名称列表。
            gates: 后端的基门列表。
            local: 后端是否为本地或远程。
            simulator: 后端是否为模拟器。
            conditional: 后端是否支持条件操作。
            open_pulse: 后端是否支持开放脉冲(open pulse)。
            memory: 后端是否支持内存。
            coupling_map(list): 设备的耦合图。
            supported_instructions(List[str]): 后端支持的指令。
            dynamic_reprate_enabled(bool): 是否可以动态设置基本操作之间的延迟(例如通过 rep_delay)。默认值为 False。
            rep_delay_range(List[float]): 定义后端支持的重复延迟范围(单位: 微秒 μs)的二维列表。第一个值为下限，第二个值为上限。可选参数，当 dynamic_reprate_enabled=True 时会提供。
            default_rep_delay(float): 在用户未指定且 dynamic_reprate_enabled=True 时使用的默认 rep_delay 值。
            n_uchannels: u 通道数量。
            u_channel_lo: 设备中 u 通道的低频振荡器(LO)关系。
            meas_levels: 支持的测量级别。
            qubit_lo_range: 每个量子比特的 LO 范围，格式为 (min, max)，单位 GHz。
            meas_lo_range: 每个量子比特的测量 LO 范围，格式为 (min, max)，单位 GHz。
            dt: 量子比特驱动通道的时间步长，单位为纳秒。
            dtm: 测量驱动通道的时间步长，单位为纳秒。
            rep_times: 后端支持的重复执行时间(单位 μs)。
            meas_kernels: 支持的测量核。
            discriminators: 支持的判别器。
            hamiltonian: 可选字典，用于描述系统哈密顿量的特性。
            channel_bandwidth(list): 所有通道(量子比特、测量、U 通道)的带宽。
            acquisition_latency(list): 维度为 n_qubits x n_registers 的数组，表示将测量结果写入寄存器的延迟(单位 dt)。
            conditional_latency(list): 维度为 n_channels [d→u→m] x n_registers 的数组，表示条件操作的延迟(单位 dt)。
            meas_map(list): 测量分组(多路复用)。
            sample_name(str): 后端的样本名称。
            n_registers(int): 用于反馈的寄存器槽数量(在 conditional=True 时)。
            register_map(list): 维度为 n_qubits x n_registers 的数组，表示某个量子比特是否可以将测量结果存储到某个寄存器槽。
            configurable(bool): 如果后端是模拟器且可配置，则为 True。
            credits_required(bool): 运行任务是否需要信用点。
            online_date(datetime): 设备上线时间。
            display_name(str): 后端的显示名称(别名)。
            description(str): 后端的描述信息。
            tags(list): 用于描述后端的一组标签。
            version: Backend 类的版本(例如 1 或 2)。
            channels: 可选字典，包含每个通道的信息——用途、类型以及其操作的量子比特。
            parametric_pulses(list): 后端支持的脉冲形状列表，例如 ['gaussian', 'constant']。
            processor_type(dict): 该后端的处理器类型，格式为: 
            {"family": <str>, "revision": <str>, segment: <str>}，例如: 
            {"family": "Canary", "revision": "1.0", segment: "A"}
    """

    id_warning_issued = False

    def __init__(
        self,
        configuration: QasmBackendConfiguration,
        service: "gjq_runtime_service.GJQRuntimeService",
        api_client: RuntimeClient,
        instance: str | None = None,
        calibration_id: str | None = None,
    ) -> None:
        """GJQBackend 构造函数.

        参数：
            configuration: 后端配置
            service: GJQRuntimeService 的实例
            api_client: 用于与服务器通信的 IBM 客户端
            calibration_id: 可选的校准 ID,用于该后端
        """
        super().__init__(
            name=configuration.backend_name,
            online_date=configuration.online_date,
            backend_version=configuration.backend_version,
        )
        print(f"Loading backend (加载后端): {self.name}")
        self._calibration_id = calibration_id
        self._instance = instance
        self._service = service
        self._api_client = api_client
        self._configuration = deepcopy(configuration)
        self._properties: Any = None
        self._target: Any = None
        if (
            not self._configuration.simulator
            and hasattr(self.options, "noise_model")
            and hasattr(self.options, "seed_simulator")
        ):
            self.options.set_validator("noise_model", type(None))
            self.options.set_validator("seed_simulator", type(None))
        if hasattr(configuration, "rep_delay_range"):
            self.options.set_validator(
                "rep_delay",
                (configuration.rep_delay_range[0], configuration.rep_delay_range[1]),
            )

    def __getattr__(self, name: str) -> Any:
        """从自身或配置中获取属性。

        当用户访问类中尚不存在的属性时，会执行此方法。
        """
        # Prevent recursion since these properties are accessed within __getattr__
        if name in ["_properties", "_target", "_configuration"]:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(self.__class__.__name__, name)
            )

        # Lazy load properties and pulse defaults and construct the target object.
        self.properties()
        self._convert_to_target()
        # Check if the attribute now is available on IBMBackend class due to above steps
        try:
            return super().__getattribute__(name)
        except AttributeError:
            pass
        # If attribute is still not available on IBMBackend class,
        # fallback to check if the attribute is available in configuration
        try:
            return self._configuration.__getattribute__(name)
        except AttributeError:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(self.__class__.__name__, name)
            )

    def _convert_to_target(self, refresh: bool = False) -> None:
        """将后端配置和属性转换为 Target 对象。"""
        if refresh or not self._target:
            self._target = convert_to_target(
                configuration=self._configuration,  # type: ignore[arg-type]
                properties=self._properties,
            )

    @classmethod
    def _default_options(cls) -> Options:
        """默认运行时选项。"""
        return Options(
            shots=4000,
            memory=False,
            meas_level=MeasLevel.CLASSIFIED,
            meas_return=MeasReturnType.AVERAGE,
            memory_slots=None,
            memory_slot_size=100,
            rep_time=None,
            rep_delay=None,
            init_qubits=True,
            use_measure_esp=None,
            use_fractional_gates=False,
            # Simulator only
            noise_model=None,
            seed_simulator=None,
        )

    @property
    def calibration_id(self) -> str | None:
        """该后端使用的校准 id。"""
        return self._calibration_id

    @property
    def service(self) -> "gjq_runtime_service.GJQRuntimeService":
        """返回“service”对象。

        返回：
            service: GjqRuntimeService 的实例。
        """
        return self._service

    @property
    def dtm(self) -> float:
        """返回输出信号的系统时间分辨率。

        返回：
            dtm: 输出信号的时间步长,单位为秒。
        """
        return self._configuration.dtm

    @property
    def max_circuits(self) -> None:
        """该属性曾用于返回后端配置中的“max_experiments”值,但该值已不再准确表示后端电路限制.将添加新字段以指示新的限制.
        """

        return None

    @property
    def meas_map(self) -> list[list[int]]:
        """返回多路复用测量的分组。

        如果后端支持 Pulse 调度,则必须实现此方法.

        返回：
            meas_map: 多路复用测量的分组.
        """
        return self._configuration.meas_map

    @property
    def target(self) -> Target:
        """后端的“Target”对象.

        返回：
            Target对象.
        """
        self.properties()
        self._convert_to_target()
        return self._target

    def target_history(self, datetime: python_datetime | None = None) -> Target:
        """后端的“Target”对象.

        返回：
            在指定“datetime”时刻的 Target 属性.
        """

        return convert_to_target(
            configuration=self._configuration,  # type: ignore[arg-type]
            properties=self.properties(datetime=datetime),  # pylint: disable=unexpected-keyword-arg
        )

    def properties(
        self, refresh: bool = False, datetime: python_datetime | None = None
    ) -> BackendProperties | None:
        """返回后端属性，可选过滤。

        此数据描述量子比特属性(如 T1 和 T2)、门属性(如门时长和误差)以及后端的其他通用属性。

        参数：
            refresh: 若为 True, 则重新从服务器获取后端属性，否则返回缓存版本。
            datetime: 指定“datetime”时, 返回时间戳最接近且早于该时间的 BackendProperties 实例。

        返回：
            后端属性，若当前不可用则为 None.

        异常：
            TypeError: 输入参数类型不正确时抛出。
            NotImplementedError: 当 cloud runtime 下指定 datetime 时抛出。
        """
        # pylint: disable=arguments-differ
        if self._configuration.simulator:
            # Simulators do not have backend properties.
            return None
        if not isinstance(refresh, bool):
            raise TypeError(
                "The 'refresh' argument needs to be a boolean. "
                "{} is of type {}".format(refresh, type(refresh))
            )
        if datetime:
            if not isinstance(datetime, python_datetime):
                raise TypeError("'{}' is not of type 'datetime'.")
            datetime = local_to_utc(datetime)
        if datetime or refresh or self._properties is None:
            api_properties = self._api_client.backend_properties(
                self.name
            )
            if not api_properties:
                return None
            backend_properties = properties_from_server_data(
                api_properties,
                use_fractional_gates=self.options.use_fractional_gates,
            )
            if datetime:  # Don't cache result.
                return backend_properties
            self._properties = backend_properties
        return self._properties

    def configuration(
        self,
    ) -> QasmBackendConfiguration:
        """返回后端配置.

        后端配置包含有关后端的固定信息，如名称、量子比特数、基础门、耦合映射、量子体积等.

        返回：
            后端的配置.
        """
        return self._configuration

    def __repr__(self) -> str:
        return "<{}('{}')>".format(self.__class__.__name__, self.name)

    def __call__(self) -> "Backend":
        # For backward compatibility only, can be removed later.
        return self

    def check_faulty(self, circuit: QuantumCircuit) -> None:
        """检查输入电路是否使用了故障量子比特或边.

        参数：
            circuit: 要检查的电路.

        异常：
            ValueError: 如果发现操作在故障量子比特或边上的指令则抛出.
        """
        if not self.properties():
            return 

        faulty_qubits = self.properties().faulty_qubits()
        faulty_gates = self.properties().faulty_gates()
        faulty_edges = [tuple(gate.qubits) for gate in faulty_gates if len(gate.qubits) > 1]

        for instr in circuit.data:
            if instr.operation.name == "barrier":
                continue
            qubit_indices = tuple(circuit.find_bit(x).index for x in instr.qubits)

            for circ_qubit in qubit_indices:
                if circ_qubit in faulty_qubits:
                    raise ValueError(
                        f"Circuit {circuit.name} contains instruction "
                        f"{instr} operating on a faulty qubit {circ_qubit}."
                    )

            if len(qubit_indices) == 2 and qubit_indices in faulty_edges:
                raise ValueError(
                    f"Circuit {circuit.name} contains instruction "
                    f"{instr} operating on a faulty edge {qubit_indices}"
                )

    def __deepcopy__(self, _memo: dict = None) -> "GJQBackend":
        cpy = GJQBackend(
            configuration=deepcopy(self.configuration()),
            service=self._service,
            api_client=deepcopy(self._api_client),
            instance=self._instance,
        )
        cpy.name = self.name
        cpy.description = self.description
        cpy.online_date = self.online_date
        cpy.backend_version = self.backend_version
        cpy._coupling_map = self._coupling_map
        cpy._target = deepcopy(self._target, _memo)
        cpy._options = deepcopy(self._options, _memo)
        return cpy

    def run(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """
        异常：
            GJQBackendError:run()方法已不再支持。

        """
        raise GJQBackendError(
            "backend.run() is no longer supported."
        )

    def get_translation_stage_plugin(self) -> str:
        """返回 IBM 后端的默认翻译阶段插件名称。"""
        if not self.options.use_fractional_gates:
            return "ibm_dynamic_circuits"
        return "ibm_dynamic_and_fractional"


class IBMRetiredBackend(Backend):
    """与已下线 IBM Quantum 设备交互的后端类。"""

    def __init__(
        self,
        configuration: QasmBackendConfiguration,
        service: "gjq_runtime_service.GJQRuntimeService",
        api_client: RuntimeClient | None = None,
    ) -> None:
        """IBMRetiredBackend 构造函数。

        参数：
            configuration：后端配置。
            service：QiskitRuntimeService 实例。
            api_client：用于与服务器通信的 IBM Quantum 客户端。
        """
        super().__init__(configuration, service, api_client)
        self._status = BackendStatus(
            backend_name=self.name,
            backend_version=self.configuration().backend_version,
            operational=False,
            pending_jobs=0,
            status_msg="This backend is no longer available.",
        )

    @classmethod
    def _default_options(cls) -> Options:
        """默认运行时选项。"""
        return Options(shots=4000)

    def properties(self, refresh: bool = False, datetime: python_datetime | None = None) -> None:
        """返回后端属性。"""
        return None

    def status(self) -> BackendStatus:
        """返回后端状态。"""
        return self._status