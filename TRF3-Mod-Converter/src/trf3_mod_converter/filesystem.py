"""Filesystem guards and bounded retries for transient Windows file locks."""
import errno
import os
import stat
import time
from pathlib import Path


def linked(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


_RENAME_RETRY_DELAYS = (0.05, 0.10, 0.20, 0.40, 0.80)


def replace_with_retry(source: Path | str, destination: Path | str) -> None:
    """Keep atomic replacement, retrying only transient Windows file locks."""
    for attempt in range(len(_RENAME_RETRY_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if (getattr(error, 'winerror', None) not in (5, 32, 33)
                    or attempt == len(_RENAME_RETRY_DELAYS)):
                raise
            time.sleep(_RENAME_RETRY_DELAYS[attempt])


def rename_with_retry(source: Path | str, destination: Path | str) -> Path:
    """Rename without replacing a destination, retrying Windows lock errors.

    Callers retain responsibility for workspace/path guards. Only Windows
    access-denied/sharing/lock violations (5, 32, 33) are retried, with six
    attempts and at most 1.55 seconds of backoff. The original final exception
    is retained. Existing destinations, including dangling links, are rejected;
    an existing Windows case-only alias of the source is allowed.
    """
    source, destination = Path(source), Path(destination)
    for attempt in range(len(_RENAME_RETRY_DELAYS) + 1):
        try:
            try:
                destination.lstat()
            except FileNotFoundError:
                pass
            else:
                source_name = os.path.abspath(source)
                destination_name = os.path.abspath(destination)
                if source_name == destination_name and source.samefile(destination):
                    return destination
                case_only = (os.name == 'nt'
                             and source_name.casefold() == destination_name.casefold()
                             and source.samefile(destination))
                if not case_only:
                    raise FileExistsError(errno.EEXIST, 'Rename destination already exists', str(destination))
            return source.rename(destination)
        except PermissionError as error:
            if (getattr(error, 'winerror', None) not in (5, 32, 33)
                    or attempt == len(_RENAME_RETRY_DELAYS)):
                raise
            time.sleep(_RENAME_RETRY_DELAYS[attempt])
