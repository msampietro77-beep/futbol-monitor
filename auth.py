"""
auth.py
=======
Sistema de login y control de acceso por roles.

Cómo funciona:
  1. app.py y cada page llaman a `exigir_acceso("NombreDePagina")`
     apenas después de `st.set_page_config(...)`.
  2. Si nadie inició sesión, se muestra la pantalla de login y se corta
     la ejecución con `st.stop()`.
  3. Si el usuario inició sesión pero su rol no tiene permiso sobre esa
     página, se muestra un mensaje de acceso denegado y se corta la
     ejecución.
  4. Si tiene permiso, se dibuja el panel de usuario (rol + botón de
     cerrar sesión) en el sidebar y la página sigue su curso normal.

La sesión se guarda en `st.session_state`, por lo que se mantiene activa
mientras el usuario navega entre páginas (Streamlit comparte
session_state entre app.py y todo pages/).

Nota importante: Streamlit arma el menú lateral de navegación
automáticamente a partir de los archivos en pages/, y ese menú
lista TODAS las páginas para TODOS los usuarios (no hay forma de
ocultar páginas del menú sin reescribir la navegación con
st.navigation). Por eso el control de acceso se hace bloqueando el
CONTENIDO de la página cuando el rol no tiene permiso, tal como ya
hacía el módulo RTP con su contraseña.
"""

import hashlib
import streamlit as st


# ============================================================
# USUARIOS DE PRUEBA
# Las contraseñas se guardan hasheadas (SHA-256), nunca en texto
# plano, aunque el valor real de prueba es el indicado en el
# comentario de cada usuario.
# ============================================================

def _hash(password):
    """Convierte una contraseña en su hash SHA-256 (hexadecimal)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


USUARIOS = {
    "director": {
        "password_hash": _hash("dir2026"),          # contraseña: dir2026
        "rol": "director",
        "nombre": "Director de Salud y Rendimiento",
    },
    "medico": {
        "password_hash": _hash("med2026"),          # contraseña: med2026
        "rol": "medico",
        "nombre": "Médico del Plantel",
    },
    "kinesiologo": {
        "password_hash": _hash("kine2026"),         # contraseña: kine2026
        "rol": "kinesiologo",
        "nombre": "Kinesiólogo",
    },
    "preparador": {
        "password_hash": _hash("prep2026"),         # contraseña: prep2026
        "rol": "preparador",
        "nombre": "Preparador Físico",
    },
}


# ============================================================
# ROLES Y PÁGINAS PERMITIDAS
# La clave de cada página es el nombre del archivo en pages/
# (sin extensión), y "Dashboard" identifica a app.py.
# ============================================================

PAGINAS_POR_ROL = {
    "director": [
        "Dashboard", "Front_Desk", "Wellness_Diario", "Carga_Gym",
        "Epidemiologia", "RTP", "ML_Riesgo", "Perfil_Jugador",
    ],
    "medico": [
        "RTP", "Epidemiologia", "Wellness_Diario", "Perfil_Jugador",
    ],
    "kinesiologo": [
        "Wellness_Diario", "RTP", "Epidemiologia", "Perfil_Jugador",
    ],
    "preparador": [
        "Dashboard", "Front_Desk", "Carga_Gym", "Perfil_Jugador",
    ],
    # El módulo de nutrición todavía no existe — el rol queda
    # definido para cuando se agregue esa página.
    "nutricion": [],
}

# Páginas donde el rol solo puede VER datos, no cargarlos.
# Se usa dentro de cada page con `auth.es_solo_lectura("NombrePagina")`
# para deshabilitar los formularios de carga.
SOLO_LECTURA = {
    "medico": ["Wellness_Diario"],
}

# Nombres legibles de cada rol para mostrar en pantalla
ROLES_LEGIBLES = {
    "director": "Director de Salud y Rendimiento",
    "medico": "Médico",
    "kinesiologo": "Kinesiólogo",
    "preparador": "Preparador Físico",
    "nutricion": "Nutrición",
}

# Nombres legibles de cada página para los mensajes de acceso denegado
PAGINAS_LEGIBLES = {
    "Dashboard": "Dashboard",
    "Front_Desk": "Front Desk",
    "Wellness_Diario": "Wellness Diario",
    "Carga_Gym": "Carga Gym",
    "Epidemiologia": "Epidemiología",
    "RTP": "RTP",
    "ML_Riesgo": "Riesgo de Lesión (ML)",
    "Perfil_Jugador": "Perfil de Jugador",
}


# ============================================================
# FUNCIONES DE SESIÓN
# ============================================================

def esta_logueado():
    """True si hay un usuario con sesión activa."""
    return st.session_state.get("auth_usuario") is not None


def rol_actual():
    """Rol del usuario logueado, o None si no hay sesión."""
    return st.session_state.get("auth_rol")


def usuario_actual():
    """Usuario (login) actual, o None si no hay sesión."""
    return st.session_state.get("auth_usuario")


def tiene_acceso(pagina):
    """True si el rol actual puede ver la página indicada."""
    rol = rol_actual()
    if rol is None:
        return False
    return pagina in PAGINAS_POR_ROL.get(rol, [])


def es_solo_lectura(pagina):
    """True si el rol actual solo puede ver (no cargar) datos en esa página."""
    rol = rol_actual()
    return pagina in SOLO_LECTURA.get(rol, [])


def cerrar_sesion():
    """Borra la sesión activa y recarga la app en la pantalla de login."""
    for clave in ("auth_usuario", "auth_rol", "auth_nombre"):
        st.session_state.pop(clave, None)
    st.rerun()


# ============================================================
# PANTALLA DE LOGIN
# ============================================================

def mostrar_login():
    """Dibuja el formulario de inicio de sesión y detiene la ejecución."""
    col_vacia_izq, col_form, col_vacia_der = st.columns([1, 1.4, 1])
    with col_form:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("## ⚽ Monitor de Rendimiento del Plantel")
        st.markdown("#### Iniciar sesión")
        st.caption("Sistema de Monitoreo de Rendimiento · EQUIPOPHYSICAL")

        with st.form("form_login"):
            usuario = st.text_input("Usuario", placeholder="ej: director")
            clave = st.text_input("Contraseña", type="password")
            enviar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)

        if enviar:
            datos = USUARIOS.get(usuario.strip().lower())
            if datos is not None and datos["password_hash"] == _hash(clave):
                st.session_state["auth_usuario"] = usuario.strip().lower()
                st.session_state["auth_rol"] = datos["rol"]
                st.session_state["auth_nombre"] = datos["nombre"]
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")

        with st.expander("👥 Usuarios de prueba"):
            st.markdown(
                "- `director` / `dir2026`\n"
                "- `medico` / `med2026`\n"
                "- `kinesiologo` / `kine2026`\n"
                "- `preparador` / `prep2026`"
            )
    st.stop()


# ============================================================
# PANEL DE USUARIO EN EL SIDEBAR
# ============================================================

def mostrar_panel_usuario_sidebar():
    """Muestra el rol activo y el botón de cerrar sesión en el sidebar."""
    with st.sidebar:
        st.divider()
        st.caption(f"👤 **{st.session_state.get('auth_nombre', '')}**")
        st.caption(f"Rol activo: **{ROLES_LEGIBLES.get(rol_actual(), rol_actual())}**")
        if st.button("🚪 Cerrar sesión", use_container_width=True, key="btn_cerrar_sesion"):
            cerrar_sesion()


# ============================================================
# GATE PRINCIPAL — llamar al inicio de cada página
# ============================================================

def exigir_acceso(pagina):
    """
    Control de acceso de una página. Debe llamarse justo después de
    `st.set_page_config(...)`.

    - Si no hay sesión activa: muestra el login y detiene la ejecución.
    - Si el rol no tiene permiso sobre `pagina`: muestra el error y
      detiene la ejecución.
    - Si tiene permiso: dibuja el panel de usuario en el sidebar y
      la página continúa normalmente.
    """
    if not esta_logueado():
        mostrar_login()
        return  # mostrar_login ya corta con st.stop(), esto es solo defensivo

    if not tiene_acceso(pagina):
        rol = rol_actual()
        st.error(
            f"🔒 No tenés permiso para acceder al módulo "
            f"**{PAGINAS_LEGIBLES.get(pagina, pagina)}** con el rol "
            f"**{ROLES_LEGIBLES.get(rol, rol)}**."
        )
        paginas_permitidas = [
            PAGINAS_LEGIBLES.get(p, p) for p in PAGINAS_POR_ROL.get(rol, [])
        ]
        if paginas_permitidas:
            st.info("Módulos disponibles para tu rol: " + ", ".join(paginas_permitidas))
        else:
            st.warning("Tu rol todavía no tiene módulos asignados en el sistema.")
        mostrar_panel_usuario_sidebar()
        st.stop()

    mostrar_panel_usuario_sidebar()
