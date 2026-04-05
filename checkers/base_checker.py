"""
checkers/base_checker.py

Contrato que deben cumplir todos los checkers.
Cada checker concreto hereda de esta clase e implementa:
  - _on_start()  → lógica de arranque  (suscripción al topic, etc.)
  - _on_stop()   → lógica de parada    (desuscripción, parar hilo, etc.)
  - _check()     → lógica de comprobación (llamada desde el callback ROS2
                   o, en checkers síncronos, desde stop())
"""

from abc import ABC, abstractmethod
import logging


class BaseChecker(ABC):

    def __init__(self, name: str, logger: logging.Logger | None = None):
        self.name     = name
        self.logger   = logger or logging.getLogger(f"checker.{name}")
        self._running  = False
        self._failures: list[str] = []

    # ── Interfaz pública ───────────────────────────────────────────────────

    def start(self):
        """Arranca el checker. Llamado justo antes de iniciar el bag play."""
        self._failures = []
        self._running  = True
        self.logger.debug(f"[{self.name}] started")
        self._on_start()

    def stop(self):
        """Para el checker. Llamado justo después de que el bag termine."""
        self._running = False
        self._on_stop()
        self.logger.debug(f"[{self.name}] stopped — {len(self._failures)} failure(s)")

    def failures(self) -> list[str]:
        """Devuelve la lista de fallos detectados (vacía = sin fallos)."""
        return list(self._failures)

    # ── Helpers para subclases ─────────────────────────────────────────────

    def _record_failure(self, reason: str):
        """Registra un fallo. Las subclases llaman a esto cuando detectan algo."""
        self._failures.append(reason)
        self.logger.warning(f"[{self.name}] FAILURE: {reason}")

    # ── Métodos que las subclases deben/pueden implementar ─────────────────

    @abstractmethod
    def _on_start(self):
        """Lógica específica de arranque (suscribirse a topic, etc.)."""
        ...

    @abstractmethod
    def _on_stop(self):
        """Lógica específica de parada (desuscribirse, join de hilo, etc.)."""
        ...
