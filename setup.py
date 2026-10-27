"""Package the public SDK with its released Windows x64 extension modules."""

from pathlib import Path
import sys
import sysconfig

from setuptools import Distribution, setup
from setuptools.command.sdist import sdist
from wheel.bdist_wheel import bdist_wheel


if (
    sys.implementation.name != "cpython"
    or sys.version_info < (3, 12)
    or sysconfig.get_platform() != "win-amd64"
):
    raise RuntimeError(
        "This checkout requires Windows x64 and CPython 3.12 or later. "
        "On other platforms, install the matching gjq-client release from PyPI."
    )

client_dir = Path(__file__).resolve().parent / "src" / "gjq_client" / "client"
protected_modules = ("backend_url_config", "client_parameters", "runtime")
source_suffixes = {".py", ".pyc", ".pyo", ".c", ".cpp", ".pyx", ".pdb"}
for module in protected_modules:
    if not (client_dir / f"{module}.pyd").is_file():
        raise RuntimeError(f"Required released extension module is missing: {module}.pyd")
    for candidate in client_dir.rglob(f"{module}.*"):
        if candidate.suffix in source_suffixes:
            raise RuntimeError(f"Protected source or build artifact must be removed: {candidate.name}")


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


class PrecompiledWheel(bdist_wheel):
    def finalize_options(self):
        self.py_limited_api = "cp312"
        self.plat_name = "win_amd64"
        super().finalize_options()


class NoSourceDistribution(sdist):
    def run(self):
        raise RuntimeError(
            "Source distributions are not supported by this binary-backed checkout. "
            "Build a Windows x64 wheel instead."
        )


setup(
    distclass=BinaryDistribution,
    cmdclass={"bdist_wheel": PrecompiledWheel, "sdist": NoSourceDistribution},
    zip_safe=False,
)
