from __future__ import annotations

from qiskit.circuit.delay import Delay
from qiskit.circuit.gate import Instruction
from qiskit.circuit.library.standard_gates import (
    RZGate,
    U1Gate,
    PhaseGate,
)
from qiskit.converters import circuit_to_dag
from qiskit import QuantumCircuit
from qiskit.qasm2 import dumps

def is_fractional_gate(gate: Instruction) -> bool:
    """测试一个门是否是连续参数门

    Args:
        gate: 门的名称

    Returns:
        如果是连续参数门,返回True
    """
    exclude_list = (RZGate, PhaseGate, U1Gate, Delay)
    return len(gate.params) > 0 and not isinstance(gate, exclude_list)

def sort_instructions(inst:dict)-> dict:
    """
    对指令进行排序
    """
    indexs=[]
    steps=[]
    res=inst.copy()
    res["steps"].sort(key=lambda x:x["index"])
    tmp={}
    for step in res["steps"]:
        if step["index"] not in indexs:
            if len(tmp)>0:
                steps.append(tmp)
            indexs.append(step["index"])
            tmp={
                "index":step["index"],
            }
            del step["index"]
            tmp["gates"]=[step]
        else:
            del step["index"]
            tmp["gates"].append(step)
    if len(tmp)>0:
        steps.append(tmp)
    inst["steps"]=steps
    return inst

def convert_to_instructions(circuit: QuantumCircuit) -> dict:
    """
    从QuantumCircuit中提取指令并转换为特定的json格式
    """
    dag = circuit_to_dag(circuit)
    res={
        "quantum-num":0,
        "steps":[]
        }

    gates={
        "id":{
            "name":"id",
            "targets":[]
        },
        "h":{
            "name":"h",
            "targets":[]
        },
        "x":{
            "name":"x",
            "targets":[]
        },
        "sx":{
            "name":"sx",
            "root":"1/2",
            "targets":[]
        },
        "y":{
            "name":"y",
            "targets":[]
        },
        "sy":{
            "name":"sy",
            "root":"1/2",
            "targets":[]
        },
        "rz":{
            "name":"rz",
            "theta":1.5707963267948966,
            "targets":[]
        },
        "cz":{
            "name":"cz",
            "targets":[]
        },
        "measure":{
            "name":"measure",
            "targets":[],
            "bit":0,
            "cBit":0
        }
    }
    quantum_nums=[]
    for i, layer in enumerate(dag.layers()):
        for node in layer['graph'].op_nodes():
            if node.name == "barrier":
                continue
            tmp=gates[node.name].copy()
        
            tmp["targets"]=[q._index for q in node.qargs]
            tmp["index"]=i
            if node.name == "measure":
                tmp["bit"]=[q._index for q in node.cargs][0]
                tmp["cBit"]=[q._index for q in node.cargs][0]
            for q_index in tmp["targets"]:
                if q_index not in quantum_nums:
                    quantum_nums.append(q_index)
            if len(node.op.params)!=0:
                tmp['theta']=node.op.params[0]
            res['steps'].append(tmp)

    res["quantum-num"]=max(quantum_nums)+1 if len(quantum_nums)>0 else 0
    return sort_instructions(res)



def circuit_to_json_layers(circuit: QuantumCircuit):
    """
    将 QuantumCircuit 转为按时间步聚合的 JSON，使用 DAGCircuit 来确定 layer 序号
    """
    dag = circuit_to_dag(circuit)
    
    res = {
        "quantum-num": 0,
        "steps": []
    }

    # 根门 / 幂门映射
    root_gates = {
        "sx": 1/2, "sxdg": -1/2,
        "sy": 1/2, "sydg": -1/2,
        "s": 1/2, "sdg": -1/2,
        "t": 1/4, "tdg": -1/4
    }

    qubit_numbs=[]
    i=0
    # 使用 DAGCircuit 的 layers 方法
    for layer_idx, layer in enumerate(dag.layers()):
        gates_in_layer = []
        for node in layer['graph'].op_nodes():
            instr = node.op
            qubit_indices = [circuit.qubits.index(q) for q in node.qargs]
            for q in node.qargs:
                if circuit.qubits.index(q) not in qubit_numbs:
                    qubit_numbs.append(circuit.qubits.index(q))
            cargs = node.cargs

            if instr.name == "barrier":
                continue  # barrier 不占用层

            gate_dict = {"name": instr.name, "targets": qubit_indices}

            # 控制门处理
            if instr.name in ["cx", "cy", "ccx"]:
                gate_dict["controls"] = [{"target": circuit.qubits.index(node.qargs[0])}]
                if instr.name == "ccx":
                    gate_dict["controls"].append({"target": circuit.qubits.index(node.qargs[1])})
                    gate_dict["targets"] = [circuit.qubits.index(node.qargs[2])]
                else:
                    gate_dict["targets"] = qubit_indices[1:]
                if instr.params:
                    gate_dict["theta"] = float(instr.params[0])

            # 多比特交换门
            elif instr.name in ["swap", "cswap"]:
                if instr.name == "cswap":
                    gate_dict["controls"] = [{"target": circuit.qubits.index(node.qargs[0])}]
                    gate_dict["targets"] = qubit_indices[1:]
                else:
                    gate_dict["targets"] = qubit_indices

            # 测量 / 重置
            elif instr.name in ["measure", "reset"]:
                if instr.name == "measure":
                    # 获取 Clbit 所在的寄存器和寄存器内索引
                    for reg in circuit.cregs:
                        if cargs[0] in reg:
                            local_index = reg[:].index(cargs[0])
                            gate_dict["bit"] = local_index
                            gate_dict["cBit"] = local_index
                            gate_dict["cReg"] = reg.name  # 可选：保存寄存器名
                            break
                gate_dict["targets"] = qubit_indices

            # 根门处理
            elif instr.name in root_gates:
                gate_dict["root"] = root_gates[instr.name]

            # 单比特旋转门
            elif instr.params:
                gate_dict["theta"] = float(instr.params[0])

            gates_in_layer.append(gate_dict)

        if gates_in_layer:
            res["steps"].append({"index": layer_idx, "gates": gates_in_layer})
    qubit_numbs = list(qubit_numbs)        
    res["quantum-num"] = max(qubit_numbs)+1 if len(qubit_numbs)>0 else 0
    res['qubit_num']=len(qubit_numbs)
    res["measure-position"] = extract_measure_positions(res["steps"])

    return res


def extract_measure_positions(steps: list[dict]) -> list[int]:
    """从 payload 的 steps 中提取所有被测量的 qubit ID 列表。

    遍历所有 step 中的 gate，收集 measure / measure-* 测量门的 targets，
    返回去重且排序后的 qubit ID 列表。

    用于模拟器后端（如 FAS-CPU、SAS-CPU）提交任务时自动生成 measure-position 字段。

    Args:
        steps: payload 中的 steps 列表，每个元素包含 "gates" 子列表。

    Returns:
        排序后的被测量 qubit ID 列表，例如 [0, 1, 2, 3]。
    """
    positions: set[int] = set()
    for step in steps:
        for gate in step.get("gates", []):
            gate_name = gate.get("name", "")
            if gate_name == "measure" or gate_name.startswith("measure-"):
                positions.update(gate.get("targets", []))
    return sorted(positions)