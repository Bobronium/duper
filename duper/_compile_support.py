# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types


def check_compiled(*, recheck: bool = False) -> bool:
    """Check if the package is running from compiled modules."""
    test_module: types.ModuleType

    if "duper._compile_test" in sys.modules:
        import duper._compile_test_2

        test_module = duper._compile_test_2  # noqa: SLF001
    elif "duper._compile_test_2" not in sys.modules:
        import duper._compile_test

        test_module = duper._compile_test  # noqa: SLF001
    else:
        raise RuntimeError(f"{check_compiled.__name__} allowed be called only once.")

    compiled_test_module_file = test_module.__file__ or ""
    compiled = compiled_test_module_file.endswith(".so")

    should_uncompile = os.getenv("DUPER_NO_COMPILED")
    if should_uncompile and not compiled:
        return False
    if not should_uncompile and not compiled:
        if not recheck and recompile(Path(compiled_test_module_file).parent):
            return check_compiled(recheck=True)
        if not os.getenv("DUPER_NO_COMPILED_WARNING"):
            warnings.warn(
                "duper is not compiled, duper.deepcopy won't be much faster "
                "while duper.deepcopies will be significantly slower on compilation phase."
                " Reconstruction will still be much faster.",
                stacklevel=4,
            )
        return False
    if not should_uncompile and compiled:
        return True

    uncompile(Path(compiled_test_module_file).parent)

    return check_compiled(recheck=True)


def recompile(package_path: Path) -> bool:
    moved_extensions_file = package_path / ".moved_extensions"
    try:
        moved: list[str] = moved_extensions_file.read_text().splitlines()
    except FileNotFoundError:
        return False

    for file in moved:
        shutil.move(file, file.replace(".so.bak", ".so"))
    moved_extensions_file.unlink()
    return True


def uncompile(package_path: Path) -> None:
    file: Path
    moved: list[str] = []
    for file in package_path.rglob("*.so"):
        moved.append(destination := str(file.parent / (file.name + ".bak")))
        shutil.move(file, destination)
    (package_path / ".moved_extensions").write_text("\n".join(moved))


COMPILED = check_compiled()
