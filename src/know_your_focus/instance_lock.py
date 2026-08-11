from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType


class InstanceLockError(RuntimeError):
    """Raised when another tracker process owns the data directory."""


class InstanceLock:
    """Hold a non-blocking process lock for one data directory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._descriptor: int | None = None

    def acquire(self) -> None:
        if self._descriptor is not None:
            return

        try:
            import fcntl
        except ImportError as error:
            raise InstanceLockError("process locking is not available on this platform") from error

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                os.close(descriptor)
                raise InstanceLockError(
                    "Know Your Focus is already running for this data directory"
                ) from error
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
        except InstanceLockError:
            raise
        except OSError as error:
            raise InstanceLockError(f"cannot create process lock {self._path}: {error}") from error
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return

        self._descriptor = None
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


def data_directory_lock(data_dir: Path) -> InstanceLock:
    return InstanceLock(data_dir / ".know-your-focus.lock")
