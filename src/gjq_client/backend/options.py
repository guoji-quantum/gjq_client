"""后端选项的容器类。"""

import io
from collections.abc import Mapping


class Options(Mapping):
    """基础选项对象

    这个类是所有后端选项的基础。该类的属性旨在全部动态可调整，
    以便用户可以按需重新配置后端。如果一个属性对用户来说是不可变的 (例如量子比特的数量)，
    那应该是后端类本身的配置，而不是选项。

    此类的实例的行为类似于字典。使用 `get()` 方法访问具有默认值的选项：

    >>> options = Options(opt1=1, opt2=2)
    >>> options.get("opt1")
    1
    >>> options.get("opt3", default="hello")
    'hello'

    可以使用 `items()` 方法检索所有选项的键值对：

    >>> list(options.items())
    [('opt1', 1), ('opt2', 2)]

    选项可以按名称更新：

    >>> options["opt1"] = 3
    >>> options.get("opt1")
    3

    运行时验证器可以被注册。查看 `set_validator`。
    通过 `update_options` 和索引 (`__setitem__`) 进行更新会在执行更新之前验证新值，
    如果新值无效，则会引发 `ValueError`。

    >>> options.set_validator("opt1", (1, 5))
    >>> options["opt1"] = 4
    >>> options["opt1"]
    4
    >>> options["opt1"] = 10  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    ValueError: ...
    """

    # 这个类前言是一个 hack，用来使 `Options` 的工作方式类似于 SimpleNamespace，
    #
    # 使 `__dict__` 成为一个属性来获取一个 slotted 属性可以解决第二行。
    # Slotted 属性不是存储在 `__dict__` 中的，而且 `__slots__` 类会抑制 `__dict__` 的创建。
    # 这样我们可以自由地用一个属性来覆盖它，该属性返回选项命名空间 `_fields`。
    #
    # 我们需要使属性设置也只设置选项，以支持 `options.key = value` 形式的语句。
    # 我们还需要确保现有用途不会覆盖任何新方法。我们通过覆盖 `__setattr__` 来完成这一点，
    # 使其纯粹地写入我们的 `_fields` 字典。这具有高度不寻常的行为：
    #       >>> options = Options()
    #       >>> options.validator = "my validator option setting"
    #       >>> options.validator
    #       {}
    #       >>> options.get("validator")
    #       "my validator option setting"
    # 这是我们能做的最好的事情来支持旧接口；获取属性必须在适当时返回新形式，
    # 但设置适用于任何东西。所有选项总是可以通过 `Options.get` 返回。
    # 为了在 `__init__` 中初始化属性，我们需要绕过 `__setattr__` 的覆盖，并向上调用 `object.__setattr__`。
    #
    # 为了支持复制和 pickling，我们还需要定义如何设置我们的状态，
    # 因为 Python 的正常 unpickle 方式会失败。
    #

    __slots__ = ("_fields", "validator")

    # Mapping ABC 的实现：

    def __getitem__(self, key):
        return self._fields[key]

    def __iter__(self):
        return iter(self._fields)

    def __len__(self):
        return len(self._fields)


    def __setitem__(self, key, value):
        self.update_options(**{key: value})


    @property
    def __dict__(self):
        return self._fields


    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError as ex:
            raise AttributeError(f"Option {name} is not defined") from ex
    
    def __setattr__(self, key, value):
        self._fields[key] = value


    def __getstate__(self):
        return (self._fields, self.validator)

    def __setstate__(self, state):
        _fields, validator = state
        super().__setattr__("_fields", _fields)
        super().__setattr__("validator", validator)

    def __copy__(self):
        """返回选项的副本。

        返回的选项和验证器值是原始值的浅表副本。
        """
        out = self.__new__(type(self))  # pylint:disable=no-value-for-parameter
        out.__setstate__((self._fields.copy(), self.validator.copy()))
        return out

    def __init__(self, **kwargs):
        super().__setattr__("_fields", kwargs)
        super().__setattr__("validator", {})


    def __repr__(self):
        items = (f"{k}={v!r}" for k, v in self._fields.items())
        return f"{type(self).__name__}({', '.join(items)})"

    def __eq__(self, other):
        if isinstance(self, Options) and isinstance(other, Options):
            return self._fields == other._fields
        return NotImplemented

    def set_validator(self, field, validator_value):
        """为选项中的字段设置可选验证器

        设置验证器可以在调用选项更新时
        验证对选项值的更改是否正确。例如，如果您有一个数值字段，如 ``shots``,
        您可以指定一个边界元组来设置值的上下界，例如::

            options.set_validator("shots", (1, 4096))

        在这种情况下，每当用户更新 ``"shots"`` 选项时，
        它将强制该值 >= 1 且 <= 4096。如果超出这些边界，将引发 ``ValueError``。
        如果已存在指定字段的验证器，它将被无声地覆盖。

        参数：
            field (str): 要设置验证器的字段名
            validator_value (list 或 tuple 或 type): 用于验证器的值，取决于类型，
                指示如何强制执行字段的值。如果传入元组，则必须的长度为 2，
                将强制整数或浮点数值选项的最小值和最大值 (包含)。
                如果是列表，则将列出字段的有效值。如果是 ``type``，
                验证器将只强制值的类型。
        异常：
            KeyError: 如果字段不在选项对象中
            ValueError: 如果 ``validator_value`` 对于给定的类型具有无效值
            TypeError: 如果 ``validator_value`` 不是有效的类型
        """

        if field not in self._fields:
            raise KeyError(f"Field {field} does not exist in this options object")
        if isinstance(validator_value, tuple):
            if len(validator_value) != 2:
                raise ValueError(
                    "A tuple validator must be of the form '(lower, upper)' "
                    "where lower and upper are the lower and upper bounds "
                    "inclusive of the numeric value"
                )
        elif isinstance(validator_value, list):
            if len(validator_value) == 0:
                raise ValueError("A list validator must have at least one entry")
        elif isinstance(validator_value, type):
            pass
        else:
            raise TypeError(
                f"{type(validator_value)} is not a valid validator type, it "
                "must be a tuple, list, or class/type"
            )
        self.validator[field] = validator_value  

    def update_options(self, **fields):
        """使用关键字参数更新选项"""
        for field_name, field in fields.items():
            field_validator = self.validator.get(field_name, None)
            if isinstance(field_validator, tuple):
                if field > field_validator[1] or field < field_validator[0]:
                    raise ValueError(
                        f"Specified value for '{field_name}' is not a valid value, "
                        f"must be >={field_validator[0]} or <={field_validator[1]}"
                    )
            elif isinstance(field_validator, list):
                if field not in field_validator:
                    raise ValueError(
                        f"Specified value for {field_name} is not a valid choice, "
                        f"must be one of {field_validator}"
                    )
            elif isinstance(field_validator, type):
                if not isinstance(field, field_validator):
                    raise TypeError(
                        f"Specified value for {field_name} is not of required type {field_validator}"
                    )

        self._fields.update(fields)

    def __str__(self):
        no_validator = super().__str__()
        if not self.validator:
            return no_validator
        else:
            out_str = io.StringIO()
            out_str.write(no_validator)
            out_str.write("\nWhere:\n")
            for field, value in self.validator.items():
                if isinstance(value, tuple):
                    out_str.write(f"\t{field} is >= {value[0]} and <= {value[1]}\n")
                elif isinstance(value, list):
                    out_str.write(f"\t{field} is one of {value}\n")
                elif isinstance(value, type):
                    out_str.write(f"\t{field} is of type {value}\n")
            return out_str.getvalue()
