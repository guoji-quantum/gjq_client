# GJQ-Client

`gjq-client` is the Python SDK for CETC International Cornerstone Quantum Industry (Suzhou) Co., Ltd. (CETC-ICQ) Cloud Platform, providing Qiskit 2.0 integration with real quantum hardware.

## Project Structure

```
src/gjq_client/
├── __init__.py                # Public API exports
├── _version.py                # Version info
├── gjq_runtime/               # Runtime service module
│   ├── gjq_runtime_service.py # Service entry (auth, backend discovery)
│   ├── sampler.py             # Sampler primitive
│   ├── estimator.py           # Estimator primitive
│   └── runtime_job.py         # Job status tracking
├── client/                    # Auth & communication module
│   ├── client_parameters.py   # JWT lifecycle management
│   ├── auth.py                # Auth header injection
│   ├── session.py             # HTTP retry session
│   ├── runtime.py             # REST API client
│   └── rest/                  # REST adapter layer
├── backend/                   # Backend models
│   ├── gjq_backend.py         # GJQBackend (BackendV2)
│   ├── backend_configuration.py
│   └── backend_properties.py
└── utils/                     # Utilities
    ├── exceptions.py          # Exception classes
    ├── backend_converter.py   # Configuration → Target
    ├── backend_decoder.py     # Server data decoder
    └── generate_preset_pass_manager.py
```

## 📦 Installation

Requirements: `Python >= 3.10`, `Qiskit >= 2.0.0`

**ONLY Qiskit 2.0+ SUPPORT NOW**

```bash
# Install via PyPI
pip install gjq-client

# Or install from source
pip install .
```

## 🚀 Quick Start

```python
from qiskit import QuantumCircuit
from gjq_client import GJQRuntimeService, Sampler, generate_preset_pass_manager

# 1. Authenticate and initialize RuntimeService
#    (API key required on first use, cached automatically afterwards.
#     Obtain your key from tiangongqs.com/cloud)
service = GJQRuntimeService(api_key="YOUR_API_KEY")

# 2. Select a quantum backend
backend = service.backend("target_quantum_machine")
# Or pick the least busy backend:
# backend = service.least_busy()

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

## 📄 License

Apache License 2.0
