import time
import logging
from abc import ABC, abstractmethod

class BaseChecker(ABC):

    def __init__(self, name: str, logger: logging.Logger | None = None):
        self.name        = name
        self.logger      = logger or logging.getLogger(f"checker.{name}")
        self._running    = False
        self._start_time: float | None = None
        self._failures: list[dict] = []

    def start(self):
        """Arranca el checker."""
        self._failures   = []
        self._running    = True
        self._start_time = time.time()
        self.logger.debug(f"[{self.name}] started")
        self._on_start()

    def stop(self):
        """
        ESTE ES EL MÉTODO QUE BUSCA EL TESTER.
        Activa el flag de parada y ejecuta la limpieza específica.
        """
        if not self._running:
            return
            
        self._running = False
        self.logger.debug(f"[{self.name}] stopping...")
        self._on_stop()

    def failures(self) -> list[dict]:
        return list(self._failures)

    def _record_failure(self, reason: str):
        elapsed = time.time() - self._start_time if self._start_time else 0.0
        entry = {"reason": reason, "elapsed": elapsed}
        self._failures.append(entry)
        self.logger.warning(f"[{self.name}] FAILURE at {elapsed:.1f}s: {reason}")

    @abstractmethod
    def _on_start(self):
        """Implementado por la subclase."""
        pass

    @abstractmethod
    def _on_stop(self):
        """Implementado por la subclase."""
        pass
