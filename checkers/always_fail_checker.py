"""
checkers/always_fail_checker.py

Checker de prueba que siempre detecta un fallo.
Útil para verificar que el pipeline de reporte y movimiento de bags
funciona correctamente ante un fallo real.
"""

from .base_checker import BaseChecker


class AlwaysFailChecker(BaseChecker):

    def __init__(self, logger=None):
        super().__init__(name="AlwaysFailChecker", logger=logger)

    def _on_start(self):
        self.logger.info(f"[{self.name}] running — will always FAIL")

    def _on_stop(self):
        # Registramos el fallo en stop() porque este checker
        # no tiene callback asíncrono: simplemente falla siempre al cerrar.
        self._record_failure("AlwaysFailChecker: fallo inyectado para testing del pipeline.")
