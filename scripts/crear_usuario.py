"""
Crea un usuario desde la consola (útil para el primer administrador o si se
perdió el acceso):

    python -m scripts.crear_usuario "Nombre Apellido" correo@empresa.com "Administrador del Sistema"

Pide la contraseña sin mostrarla. Roles válidos: los de src/shared/roles.py.
"""
import getpass
import sys

from src.api.modules.identity.seguridad import ClaveDebilError
from src.api.modules.identity.servicio import OperacionNoPermitidaError, ServicioIdentidad
from src.shared.database import init_db
from src.shared.roles import ROLES


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        print("Roles: " + " | ".join(ROLES))
        return 1
    nombre, email, rol = sys.argv[1:]
    clave = getpass.getpass("Contraseña: ")
    if clave != getpass.getpass("Repita la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1
    init_db()
    try:
        usuario = ServicioIdentidad().crear_usuario(nombre, email, rol, clave)
    except (OperacionNoPermitidaError, ClaveDebilError) as e:
        print(f"No se creó el usuario: {e}")
        return 1
    print(f"Usuario creado: {usuario['email']} ({usuario['rol']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
