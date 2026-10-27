# GJQ-Client

`gjq-client` is the Python SDK for CETC International Cornerstone Quantum Industry
(Suzhou) Co., Ltd. (CETC-ICQ) Cloud Platform. It provides access to quantum hardware
and cloud simulators through Qiskit 2.3, with optional PennyLane integration.

## What's New in 0.2.1

- **Richer Estimator observables:** MPS and Guoji08 support finite real
  coefficients, multi-qubit Pauli words, identity terms, and named Hamiltonian
  sums.

- **PennyLane results and gradients:** Sampling results follow the requested
  wire order, with corrected MPS Pauli-sum variance gradients and transpiled
  measurement mapping.

- **Session queries:** List active Sessions and retrieve Session details and
  related jobs by ID and backend name.

See the [0.2.1 changelog](https://github.com/guoji-quantum/gjq_client/blob/main/docs/Changelog%20v0.2.1.md) for details.

## 📦 Installation

Requirements: `Python >= 3.12`, `Qiskit == 2.3.0`, `qiskit-ibm-runtime == 0.45.0`,
`cryptography >= 48.0.0`

This release requires Qiskit 2.3.0. The optional PennyLane integration requires
`PennyLane >= 0.45.1, < 0.46` and `pennylane-qiskit == 0.45.0`.
The installation commands below install the required dependencies automatically.

```bash
# Install via PyPI
pip install gjq-client

# Or install from a local source checkout (run in the repository root)
pip install .

# Optional PennyLane integration
pip install "gjq-client[pennylane]"
```

## 🚀 Quick Start

Replace `YOUR_API_KEY` with your platform API key and `target_quantum_machine`
with a backend name returned by `service.list_backends()`.

Use an available `FAS-CPU` or `FAS-GPU` backend to run this example as written.
`MPS` requires `options['simulator_config']` (see below); `SAS-CPU` and `SAS-GPU`
require `amplitude_index` when running a task.

```python
from qiskit import QuantumCircuit
from gjq_client import GJQRuntimeService, Sampler, generate_preset_pass_manager

# 1. Authenticate and initialize RuntimeService
#    (API key required on first use, cached automatically afterwards.
#     Obtain your key from tiangongqs.com/cloud)
service = GJQRuntimeService(api_key="YOUR_API_KEY")

# 2. Select a quantum backend
backend = service.backend("target_quantum_machine")

# 3. Build a quantum circuit
qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)
qc.measure_all()

# 4. Transpile the circuit for the target backend
pm = generate_preset_pass_manager(backend=backend, optimization_level=2)
transpiled_qc = pm.run(qc)

# 5. Submit the job and retrieve results
sampler = Sampler(backend=backend)
job = sampler.run(transpiled_qc, shots=1024)

result = job.result()
print("Measurement results:", result.get("counts"))
```

## Session: Exclusive Backend Resources

Use a Session to run related jobs with exclusive backend resources while the
Session is active. Choose a backend whose `job_mode` includes `session` in
`service.list_backends()`.

The example below reuses `backend` and `transpiled_qc` from Quick Start. Run it
with a Session-capable backend; the backend-specific settings above still apply:

```python
from gjq_client import Sampler, Session

session = Session(backend=backend, max_time=3600)
session_id = session.session_id
sampler = Sampler(mode=session)

for shots in (512, 1024):
    result = sampler.run(transpiled_qc, shots=shots).result(timeout=300)
    print(result["counts"])

# Query the same Session later by its ID and backend name.
print(service.session_detail(session_id, backend.name))
print(service.session_tasks(session_id, backend.name))

# The Session remains available for later jobs until it is closed or expires.
# Release its backend resources explicitly when no more jobs will be submitted.
session.close()
```

`max_time` is specified in seconds and still limits the Session lifetime. Creating
a Session directly keeps it open across subsequent code until `close()` or
`cancel()` is called, or the lifetime expires. If automatic cleanup at the end of
a code block is preferred, use `with Session(...) as session`; leaving that block
closes the Session. You can also use `Estimator(mode=session)` for expectation-value
jobs. `service.list_sessions()` returns the current user's pending and active
Sessions.

## MPS Simulator: Up to 1,000 Qubits

The Matrix Product State (MPS) simulator supports circuits with
**2 to 1,000 qubits**. Select the `MPS` backend and choose a simulation preset.
This example creates a 10-qubit GHZ state:

```python
from qiskit import QuantumCircuit
from gjq_client import GJQRuntimeService, Sampler

service = GJQRuntimeService(api_key="YOUR_API_KEY")
backend = service.backend("MPS")

circuit = QuantumCircuit(10)
circuit.h(0)
for qubit in range(9):
    circuit.cx(qubit, qubit + 1)
circuit.measure_all()

options = {
    "simulator_config": {
        "preset": "fast",
        "runtime": {"num_gpus": 1},
    }
}
sampler = Sampler(backend=backend, options=options)
result = sampler.run(circuit, shots=1024).result(timeout=300)
print("Counts:", result["counts"])
print("Probabilities:", result["probabilities"])
```

Use `fast`, `balanced`, or `accurate` to choose a speed/accuracy tradeoff;
`expert` is available for custom settings. MPS performance and accuracy depend
on circuit depth and entanglement, so the 1,000-qubit capacity does not imply
that every circuit of that size is practical. MPS Sampler results expose integer
shot frequencies in `counts` and retain the normalized distribution separately
in `probabilities`.
MPS Sampler requires positive `shots`; MPS Estimator also accepts `shots=0`.

MPS Estimator accepts finite real coefficients, multi-qubit Pauli words, identity
terms, and Hamiltonians expressed as Pauli sums. A multi-term `SparsePauliOp` is
submitted as one observable and its aggregate expectation is returned as
`result["evs"]["observable"]`. To request several independent expectation values,
pass a named observable list; each list entry keeps its supplied result name.

The Estimator example below reuses `backend` and `options` from the MPS example.

```python
from qiskit.quantum_info import SparsePauliOp
from gjq_client import Estimator

bell = QuantumCircuit(2)
bell.h(0)
bell.cx(0, 1)

estimator = Estimator(backend=backend, options=options)
hamiltonian = SparsePauliOp.from_list([("ZZ", 0.5), ("XI", 0.8)])
result = estimator.run(bell, observable=hamiltonian, shots=0).result(timeout=300)
print("Hamiltonian expectation:", result["evs"]["observable"])
```

## PennyLane Integration

Install the optional dependency with `pip install "gjq-client[pennylane]"`.
Then use the `gjq` device to run a PennyLane QNode on an available FAS backend or
quantum hardware. For MPS, use the replacement device definition below:

```python
import pennylane as qml
from pennylane import numpy as np
from gjq_client import GJQRuntimeService

service = GJQRuntimeService(api_key="YOUR_API_KEY")
backend = service.backend("target_quantum_machine")
dev = qml.device("gjq", wires=2, backend=backend, timeout=300)

@qml.set_shots(1024)
@qml.qnode(dev, diff_method="parameter-shift")
def circuit(theta):
    qml.RY(theta, wires=0)
    qml.CNOT(wires=[0, 1])
    return qml.expval(qml.Z(1))

theta = np.array(0.5, requires_grad=True)
print("Expectation value:", circuit(theta))
print("Gradient:", qml.grad(circuit)(theta))
```

To run the same QNode on MPS, replace the device definition above with:

```python
dev = qml.device(
    "gjq",
    wires=2,
    backend=service.backend("MPS"),
    options={
        "simulator_config": {
            "preset": "fast",
            "runtime": {"num_gpus": 1},
        }
    },
    timeout=300,
)
```

For Session execution, create the device with `mode=session` instead of
`backend=backend`, and call the QNode inside the Session's `with` block.
PennyLane execution requires positive, finite shots and supports `expval`,
`var`, `probs`, `sample`, and `counts`. The `SAS-CPU` and `SAS-GPU`
single-amplitude backends are not supported by the PennyLane device.

Computational-basis `counts`, `sample`, and `probs` follow the `wires` order
requested by each PennyLane measurement. For example, with `wires=[0, 1]`, the
leftmost count bit represents wire 0. Raw Runtime counts retain Qiskit's
little-endian convention.

## 🔐 PQC Encrypted Channel

When you need quantum-safe encryption for all API communication, enable PQC mode:

```python
from gjq_client import GJQRuntimeService

# Enable PQC transport with ML-KEM768 key exchange and AES-256-GCM encryption
service = GJQRuntimeService(
    api_key="YOUR_API_KEY",
    pqc=True
)
```

A local [PQC Gateway](https://github.com/guoji-quantum/gjq_client) must be running.
The SDK routes every request (authentication, backend queries, task submission,
result retrieval) through the Gateway's AES-256-GCM encrypted proxy channel.

**How it works:** The SDK performs a 2-step handshake
(`GET /cert` → `POST /handshake`) to negotiate an ephemeral AES-256 session key via
ML-KEM768 key encapsulation. All subsequent API calls are encrypted with AES-256-GCM
and proxied through the Gateway, which decrypts, forwards to the real cloud
backend, and encrypts the response.

**Security:** The server certificate fingerprint is pinned on the client side —
any mismatch is rejected immediately (equivalent to TLS certificate-chain
verification failure).

## Changelog

- [Version 0.2.1](https://github.com/guoji-quantum/gjq_client/blob/main/docs/Changelog%20v0.2.1.md)

- [Version 0.2.0](https://github.com/guoji-quantum/gjq_client/blob/main/docs/Changelog%20v0.2.0.md)

- [Version 0.1.1](https://github.com/guoji-quantum/gjq_client/blob/main/docs/Changelog%20v0.1.1.md)

## 📬 Contact

- **Email:** <quantumcloud@tgqs.net>

- **Issues:** [Submit an issue](https://github.com/guoji-quantum/gjq_client/issues/new)

## 📄 License

Apache License 2.0
