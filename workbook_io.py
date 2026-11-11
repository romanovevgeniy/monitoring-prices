"""Атомарная замена Excel: ошибка записи не повреждает предыдущий файл."""
import os
from pathlib import Path
import tempfile


def atomic_save(workbook, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.stem + '-', suffix=destination.suffix,
                                     dir=destination.parent)
    os.close(fd)
    try:
        workbook.save(temporary)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
