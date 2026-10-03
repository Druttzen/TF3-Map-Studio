"""Detect links, including Windows junctions on Python 3.10 and 3.11."""
import stat
from pathlib import Path


def linked(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
