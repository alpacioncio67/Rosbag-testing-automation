"""
checkers/always_pass_checker.py

Checker de prueba que nunca detecta fallos.
Útil para verificar que el pipeline de checkers funciona correctamente
cuando todo está bien.
"""

from .base_checker import BaseChecker


class AlwaysPassChecker(BaseChecker):

    def __init__(self, logger=None):
        super().__init__(name="AlwaysPassChecker", logger=logger)

    def _on_start(self):
        self.logger.info(f"[{self.name}] running — will always PASS")

    def _on_stop(self):
        # No hay nada que limpiar
        pass
    # failures() devuelve [] → sin fallos → PASS
