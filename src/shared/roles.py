"""
Matriz de roles y permisos (RF-002), según la Tabla 61 y la Tabla 27 del documento
de trabajo de grado.

Tres perfiles usan el sistema, con funciones separadas a propósito:
- Analista Comercial: registra el portafolio, gestiona las alertas de vigilancia,
  radica y sigue procesos, mantiene sus perfiles de búsqueda, carga documentos al
  expediente, solicita análisis y revisa y aprueba los requisitos extraídos.
  Consulta la decisión comercial, pero no la registra.
- Gerente Comercial: consulta portafolio, oportunidades, análisis y resultados,
  puede solicitar un análisis y es el único que registra la decisión comercial.
  Consulta los requisitos extraídos, pero no los aprueba.
- Administrador del Sistema: gestiona usuarios y roles y consulta el diagnóstico.
  No tiene acceso a la revisión de requisitos ni a la decisión comercial, y no
  solicita análisis: solo los consulta.

La API es la que hace cumplir esta matriz; la interfaz solo oculta lo que el rol
no puede usar.
"""
from typing import Dict, FrozenSet, List

ANALISTA = "Analista Comercial"
GERENTE = "Gerente Comercial"
ADMINISTRADOR = "Administrador del Sistema"

ROLES: List[str] = [ANALISTA, GERENTE, ADMINISTRADOR]


class Permiso:
    PORTAFOLIO_VER = "portafolio:ver"
    PORTAFOLIO_GESTIONAR = "portafolio:gestionar"  # Agregar, retirar y publicar versiones (A, B)
    PORTAFOLIO_EDITAR = "portafolio:editar"  # Modificar una capacidad (E)
    VIGILANCIA_VER = "vigilancia:ver"
    VIGILANCIA_GESTIONAR = "vigilancia:gestionar"
    ANALISIS_SOLICITAR = "analisis:solicitar"
    ANALISIS_VER = "analisis:ver"
    REQUISITOS_APROBAR = "requisitos:aprobar"
    RESULTADOS_VER = "resultados:ver"
    DECISION_REGISTRAR = "decision:registrar"
    REGLAS_VER = "reglas:ver"
    REGLAS_PROPONER = "reglas:proponer"  # Doble control: propone el administrador...
    REGLAS_CONFIRMAR = "reglas:confirmar"  # ...y confirma la gerencia comercial
    USUARIOS_GESTIONAR = "usuarios:gestionar"
    DIAGNOSTICO_VER = "diagnostico:ver"  # Incluye el consumo de inferencia (Tabla 61: telemetría)
    CUOTA_AMPLIAR = "cuota:ampliar"  # RN-10: la cuota la amplía el responsable autorizado
    BITACORA_VER = "bitacora:ver"  # Tabla 61: la consultan el Gerente y el Administrador
    # Perfiles de búsqueda (RF-015): cada quien sobre los suyos; el alcance lo resuelve el servidor.
    PERFILES_VER = "perfiles:ver"  # C
    PERFILES_EDITAR = "perfiles:editar"  # E (incluye activar y desactivar)
    PERFILES_GESTIONAR = "perfiles:gestionar"  # A, B
    # Expediente documental y carga manual (RF-021, RF-022): el gerente no tiene acceso.
    EXPEDIENTE_VER = "expediente:ver"  # C
    EXPEDIENTE_CARGAR = "expediente:cargar"  # E, A, solo en las oportunidades asignadas al analista
    # Notificaciones (RF-016, RF-017, RF-020), misma fila de la Tabla 61 que los perfiles: cada
    # quien consulta las suyas; el canal y la frecuencia los editan el analista y el administrador.
    NOTIFICACIONES_VER = "notificaciones:ver"
    NOTIFICACIONES_CONFIGURAR = "notificaciones:configurar"
    # Carpetas, notas, responsable y exportación (RF-040, RF-041). Tabla 61: analista C, E, A, B;
    # gerente C, E, A; administrador C. Las carpetas son siempre las del propio usuario.
    ORGANIZACION_VER = "organizacion:ver"  # C, incluida la exportación a CSV
    ORGANIZACION_EDITAR = "organizacion:editar"  # E, A: carpetas, notas y responsable
    ORGANIZACION_BORRAR = "organizacion:borrar"  # B: borrar carpetas y notas propias


TODOS: FrozenSet[str] = frozenset(
    valor for nombre, valor in vars(Permiso).items() if nombre.isupper()
)

# Las consultas (VER) las tienen los tres roles; las operaciones se reparten sin solaparse.
MATRIZ: Dict[str, FrozenSet[str]] = {
    ANALISTA: frozenset({
        Permiso.PORTAFOLIO_VER,
        Permiso.PORTAFOLIO_GESTIONAR,
        Permiso.PORTAFOLIO_EDITAR,
        Permiso.REGLAS_VER,
        Permiso.VIGILANCIA_VER,
        Permiso.VIGILANCIA_GESTIONAR,
        Permiso.ANALISIS_SOLICITAR,
        Permiso.ANALISIS_VER,
        Permiso.REQUISITOS_APROBAR,
        Permiso.RESULTADOS_VER,
        Permiso.PERFILES_VER,
        Permiso.PERFILES_EDITAR,
        Permiso.PERFILES_GESTIONAR,
        Permiso.EXPEDIENTE_VER,
        Permiso.EXPEDIENTE_CARGAR,
        Permiso.NOTIFICACIONES_VER,
        Permiso.NOTIFICACIONES_CONFIGURAR,
        Permiso.ORGANIZACION_VER,
        Permiso.ORGANIZACION_EDITAR,
        Permiso.ORGANIZACION_BORRAR,
    }),
    GERENTE: frozenset({
        Permiso.PORTAFOLIO_VER,
        Permiso.VIGILANCIA_VER,
        Permiso.ANALISIS_SOLICITAR,
        Permiso.ANALISIS_VER,
        Permiso.RESULTADOS_VER,
        Permiso.DECISION_REGISTRAR,
        Permiso.REGLAS_VER,
        Permiso.REGLAS_CONFIRMAR,
        Permiso.BITACORA_VER,
        Permiso.PERFILES_VER,
        Permiso.NOTIFICACIONES_VER,
        Permiso.ORGANIZACION_VER,
        Permiso.ORGANIZACION_EDITAR,
    }),
    ADMINISTRADOR: frozenset({
        Permiso.PORTAFOLIO_VER,
        Permiso.PORTAFOLIO_EDITAR,
        Permiso.REGLAS_VER,
        Permiso.REGLAS_PROPONER,
        Permiso.VIGILANCIA_VER,
        Permiso.ANALISIS_VER,
        Permiso.RESULTADOS_VER,
        Permiso.USUARIOS_GESTIONAR,
        Permiso.DIAGNOSTICO_VER,
        Permiso.CUOTA_AMPLIAR,
        Permiso.BITACORA_VER,
        Permiso.PERFILES_VER,
        Permiso.PERFILES_EDITAR,
        Permiso.EXPEDIENTE_VER,
        Permiso.NOTIFICACIONES_VER,
        Permiso.NOTIFICACIONES_CONFIGURAR,
        Permiso.ORGANIZACION_VER,
    }),
}

# Pantalla con la que abre la interfaz para cada rol (Tabla 27).
PANTALLA_INICIAL: Dict[str, str] = {
    ANALISTA: "Portafolio",
    GERENTE: "Resultados",
    ADMINISTRADOR: "Usuarios",
}


def permisos_de(roles: List[str]) -> FrozenSet[str]:
    """Unión de permisos de los roles indicados. Un rol desconocido no concede nada."""
    concedidos: set = set()
    for rol in roles or []:
        concedidos |= MATRIZ.get(rol, frozenset())
    return frozenset(concedidos)


def tiene_permiso(usuario: dict, permiso: str) -> bool:
    roles = usuario.get("roles") or ([usuario["rol"]] if usuario.get("rol") else [])
    return permiso in permisos_de(roles)
