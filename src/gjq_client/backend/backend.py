"""后端抽象接口."""


from abc import ABC
from abc import abstractmethod
import datetime
from typing import List, Union, Tuple

from qiskit.circuit.gate import Instruction
from qiskit._accelerate.target import QubitProperties


class Backend:
    """所有版本化后端抽象类的基础通用类型。
    """

    version = 0


class BackendV2(Backend, ABC):
    """后端的抽象类

    此抽象类用于提供者创建的所有后端对象。
    此版本与早期的抽象后端类不同，配置属性不再存在。
    相反，添加了暴露后端设备等效所需不可变属性的属性。
    例如，``backend.configuration().n_qubits`` 现在可以通过 ``backend.num_qubits`` 访问。

    后端的 ``options`` 属性用于包含后端的动态用户可配置选项。
    它应更多地用于配置后端使用方式的运行时选项。
    例如，对于运行实验的后端，``shots`` 字段可能包含一个整数，表示要执行的次数。

    后端对象可以选择性地包含名为 ``get_translation_stage_plugin`` 和 ``get_scheduling_stage_plugin`` 的方法。
    如果这些方法存在于后端对象上，并且此对象用于 :func:`~.transpile` 或 :func:`~.generate_preset_pass_manager`，
    则转换过程将默认使用这些方法的输出作为调度阶段和转换编译阶段。
    这使得具有自定义编译要求的后端可以为这些阶段指定阶段插件，以启用自定义电路转换，确保其可在后端上运行。
    默认情况下启用这些钩子，仅在 **需要** 额外编译步骤以确保电路可执行或具有预期性能时使用。
    这些方法不接受输入参数，预期返回一个 ``str`` 表示的方法名称，
    该名称应为阶段插件 (see: :mod:`qiskit.transpiler.preset_passmanagers.plugin` 获取有关插件的更多详细信息)。
    典型的预期用例是后端提供者为 ``translation`` 或 ``scheduling`` 实现一个阶段插件，
    其中包含自定义编译过程，然后后端对象上的钩子方法返回插件名称，
    以便 :func:`~.transpile` 在目标后端时默认使用它。

    子类应覆盖公共方法 :meth:`run` 和内部方法 :meth:`_default_options`:

    .. automethod:: _default_options
    """

    version = 2

    def __init__(
        self,
        provider=None,
        name: str = None,
        description: str = None,
        online_date: datetime.datetime = None,
        backend_version: str = None,
        **fields,
    ):
        """初始化一个基于 BackendV2 的后端

        参数：
            provider: 提供者对象的可选反向引用，该后端来自该提供者
            name: 后端的可选名称
            description: 后端的可选描述
            online_date: 后端上线的可选日期时间
            backend_version: 可选的后端版本字符串.
            fields: 用于覆盖默认选项值的关键字参数.

        异常：
            AttributeError: 如果指定的字段超出后端的选项范围
        """

        self._options = self._default_options()
        self._provider = provider
        if fields:
            for field in fields:
                if field not in self._options:
                    raise AttributeError(f"Options field {field} is not valid for this backend")
            self._options.update_options(**fields)
        self.name = name
        self.description = description
        self.online_date = online_date
        self.backend_version = backend_version
        self._coupling_map = None

    @property
    def instructions(self) -> List[Tuple[Instruction, Tuple[int]]]:
        """后端上的指令元组列表，形式为 ``(instruction, (qubits)``"""
        return self.target.instructions

    @property
    def operations(self) -> List[Instruction]:
        """:class:`~qiskit.circuit.Instruction` 实例的列表，表示后端支持的操作."""
        return list(self.target.operations)

    @property
    def operation_names(self) -> List[str]:
        """后端支持的指令名称列表."""
        return list(self.target.operation_names)

    @property
    @abstractmethod
    def target(self):
        """后端的 :class:`qiskit.transpiler.Target` 对象.

        :rtype: Target
        """
        pass

    @property
    def num_qubits(self) -> int:
        """返回后端的量子比特数量."""
        return self.target.num_qubits

    @property
    def coupling_map(self):
        """返回 :class:`~qiskit.transpiler.CouplingMap` 对象"""
        if self._coupling_map is None:
            self._coupling_map = self.target.build_coupling_map()
        return self._coupling_map

    @property
    def instruction_durations(self):
        """返回 :class:`~qiskit.transpiler.InstructionDurations` 对象。"""
        return self.target.durations()

    @property
    @abstractmethod
    def max_circuits(self):
        """单个作业中可运行的最大电路数量。

        如果没有限制，则返回 None
        """
        pass

    @classmethod
    @abstractmethod
    def _default_options(cls):
        """返回默认选项

        此方法将返回一个 :class:`qiskit.providers.Options` 子类对象，
        用于默认选项。这些应为后端选项的默认参数。

        返回：
            qiskit.providers.Options: 一个设置了默认值的选项对象
        """
        pass

    @property
    def dt(self) -> Union[float, None]:
        """返回输入信号的系统时间分辨率

        如果后端支持脉冲调度，则需要实现此方法。

        返回：
            输入信号时间步长 (以秒为单位)。如果后端未定义 ``dt``，则返回 ``None``。
        """
        return self.target.dt

    @property
    def dtm(self) -> float:
        """返回输出信号的系统时间分辨率

        返回：
            输出信号时间步长 (以秒为单位)。

        异常：
            NotImplementedError: 如果后端不支持查询输出信号时间步长
        """
        raise NotImplementedError

    @property
    def meas_map(self) -> List[List[int]]:
        """返回多路复用的测量分组

        如果后端支持脉冲调度，则需要实现此方法。

        返回：
            多路复用的测量分组

        异常：
            NotImplementedError: 如果后端不支持查询测量映射
        """
        raise NotImplementedError

    def qubit_properties(
        self, qubit: Union[int, List[int]]
    ) -> Union[QubitProperties, List[QubitProperties]]:
        """返回给定量子比特的 QubitProperties。

        如果未定义或后端不支持查询这些详细信息，则无需实现此方法。

        参数：
            qubit: 要获取 :class:`.QubitProperties` 对象的量子比特。
                可以是单个整数表示一个量子比特，或一个量子比特列表，
                返回的将是一个 :class:`.QubitProperties` 对象列表。
        返回：
            指定量子比特的 :class:`~.QubitProperties` 对象。
            如果提供了量子比特列表，则返回一个列表。
            如果量子比特的属性缺失，可以返回 ``None``。

        异常：
            NotImplementedError: 如果后端不支持查询量子比特属性
        """
        # 由于目标以前并不总是具有量子比特属性属性，
        # 为确保此处的行为与早期 BackendV2 实现的向后兼容性，
        # 在这些实现中，此方法会引发 NotImplementedError。
        if self.target.qubit_properties is None:
            raise NotImplementedError
        if isinstance(qubit, int):
            return self.target.qubit_properties[qubit]
        return [self.target.qubit_properties[q] for q in qubit]

    def set_options(self, **fields):
        """设置后端的选项字段

        此方法用于更新后端的选项。
        如果需要在运行之前更改任何选项，只需传入带有新值的关键字参数。

        参数：
            fields: 要更新选项的字段

        异常：
            AttributeError: 如果传入的字段不是选项的一部分
        """
        for field in fields:
            if not hasattr(self._options, field):
                raise AttributeError(f"Options field {field} is not valid for this backend")
        self._options.update_options(**fields)

    @property
    def options(self):
        """返回后端的选项

        后端的选项是定义后端使用方式的动态参数。
        它们用于控制 :meth:`run` 方法。
        """
        return self._options

    @property
    def provider(self):
        """返回后端提供者。

        返回：
            provider: 负责后端的提供者。
        """
        return self._provider

    @abstractmethod
    def run(self, run_input, **options):
        """在后端上运行。

        此方法返回一个 :class:`~qiskit.providers.Job` 对象，
        该对象运行电路。根据后端的不同，这可能是异步或同步调用。
        提供者可以自行决定运行是否应阻塞，直到执行完成：
        Job 类可以处理任一情况。

        参数：
            run_input (QuantumCircuit 或 list):
                要在后端上运行的 :class:`.QuantumCircuit` 对象的单个实例或列表。
            options: 运行配置时传递给后端的任何关键字参数。
                如果选项属性/对象中也存在某个键，则期望使用指定的值，
                而不是选项对象中设置的值。

        返回：
            Job: 运行的作业对象
        """
        pass
