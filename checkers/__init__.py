"""
checkers/__init__.py

Exporta todos los checkers y un registry para instanciarlos por nombre
desde el config.yaml sin necesidad de importarlos manualmente en el tester.

Añadir un checker nuevo:
  1. Crear checkers/mi_checker.py  con la clase MiChecker(BaseChecker)
  2. Añadir una línea aquí:  "MiChecker": MiChecker
"""

from .base_checker         import BaseChecker
from .always_pass_checker  import AlwaysPassChecker
from .always_fail_checker  import AlwaysFailChecker

# ── Registry nombre → clase ────────────────────────────────────────────────
# El tester usa este dict para instanciar checkers desde config.yaml
REGISTRY: dict[str, type[BaseChecker]] = {
    "AlwaysPassChecker" : AlwaysPassChecker,
    "AlwaysFailChecker" : AlwaysFailChecker,
}


def build_checkers(checker_configs: list[dict], logger) -> list[BaseChecker]:
    """
    Instancia una lista de checkers a partir de la sección 'checkers'
    del config.yaml.

    Cada entrada del config tiene al menos:
        type: NombreDeLaClase
        (resto de parámetros opcionales que se pasarán como kwargs)

    Ejemplo de config:
        checkers:
          - type: AlwaysPassChecker
          - type: AlwaysFailChecker
    """
    instances = []
    for cfg in checker_configs:
        checker_type = cfg.get("type")
        if not checker_type:
            logger.warning("Checker sin campo 'type' en config — ignorado.")
            continue

        cls = REGISTRY.get(checker_type)
        if cls is None:
            logger.warning(f"Checker desconocido '{checker_type}' — ignorado.")
            continue

        # Pasamos todos los parámetros del config excepto 'type'
        kwargs = {k: v for k, v in cfg.items() if k != "type"}
        instance = cls(logger=logger, **kwargs)
        instances.append(instance)
        logger.debug(f"Checker instanciado: {checker_type}")

    return instances
