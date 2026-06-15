"""
pages/Front_Desk.py
===================
Central diaria de carga de datos para el staff.

Cada área del cuerpo técnico entra aquí a registrar sus datos del día:
  🏃 Carga Interna → RPE + minutos + tipo de sesión por jugador
  🏥 Lesiones      → registrar nueva lesión / dar de alta
  📋 Estado del día → qué áreas completaron la carga de hoy

Las áreas con página propia (Wellness y Fuerza/Gym) tienen acceso directo
desde el panel de estado.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, timedelta

from metricas import (
    cargar_jugadores,
    cargar_carga_interna_fecha,
    cargar_lesiones_activas,
    cargar_lesiones_todas,
    cargar_wellness,
)


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Front Desk",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
    .stMetric label {font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONEXIÓN A BASE DE DATOS
# ============================================================

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "futbol_monitoreo.db"
)

def _conectar():
    return sqlite3.connect(DB_PATH)


# ============================================================
# CONSTANTES
# ============================================================

TIPOS_SESION = ["entrenamiento", "partido", "regenerativo", "gym", "descanso"]

TIPOS_LESION  = ["muscular", "ligamentosa", "contusión", "sobrecarga", "tendinopatía"]
ZONAS_CUERPO  = [
    "isquiotibiales", "cuádriceps", "gemelo", "aductor",
    "tobillo", "rodilla", "muslo", "pie", "lumbar", "aquiles",
    "hombro", "cadera", "ingle", "columna", "otro",
]

# Color por nivel de completitud
def _color_completitud(pct):
    if pct == 100:
        return "#21C354"
    elif pct >= 50:
        return "#FF8C00"
    else:
        return "#FF4B4B"


# ============================================================
# FUNCIONES DE GUARDAR EN DB
# ============================================================

def guardar_carga_interna(filas_df, fecha_str):
    """
    Inserta o reemplaza los registros de carga interna para la fecha dada.
    training_load = RPE × minutos (NULL si es descanso).
    """
    conn = _conectar()
    cur  = conn.cursor()

    registros = []
    for _, row in filas_df.iterrows():
        tipo    = str(row["Tipo de sesión"])
        rpe     = int(row["RPE"])     if tipo != "descanso" else None
        minutos = int(row["Minutos"]) if tipo != "descanso" else None
        tl      = rpe * minutos       if (rpe and minutos) else None

        registros.append((
            int(row["jugador_id"]),
            fecha_str,
            tipo,
            rpe,
            minutos,
            tl,
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO carga_interna
            (jugador_id, fecha, tipo_sesion, rpe, minutos, training_load)
        VALUES (?, ?, ?, ?, ?, ?)
    """, registros)
    conn.commit()
    conn.close()
    return len(registros)


def registrar_lesion(jugador_id, fecha_inicio_str, tipo, zona, dias_baja, notas=""):
    """Inserta una nueva lesión activa en la tabla lesiones."""
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO lesiones
            (jugador_id, fecha_inicio, fecha_fin, tipo_lesion,
             zona_corporal, dias_baja, activo)
        VALUES (?, ?, NULL, ?, ?, ?, 1)
    """, (jugador_id, fecha_inicio_str, tipo, zona, dias_baja))
    conn.commit()
    conn.close()


def dar_alta_lesion(lesion_id, fecha_alta_str):
    """
    Marca una lesión como resuelta (activo = 0) y registra la fecha de alta.
    """
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE lesiones
        SET activo = 0, fecha_fin = ?
        WHERE id = ?
    """, (fecha_alta_str, lesion_id))
    conn.commit()
    conn.close()


# ============================================================
# FUNCIÓN: CONSTRUIR FORMULARIO DE CARGA INTERNA
# ============================================================

def construir_form_carga(jugadores_df, hoy_df, ayer_df, filtro_pos):
    """
    Arma la tabla editable de carga interna.

    Prioridad de pre-relleno: datos de hoy > datos de ayer > valores por defecto.
    Si ya hay datos de hoy → columna ✓ = ✅ (ya guardado).
    """
    DEFECTO_TIPO = "entrenamiento"
    DEFECTO_RPE  = 6
    DEFECTO_MIN  = 75

    if filtro_pos != "Todos":
        jugadores_df = jugadores_df[jugadores_df["posicion"] == filtro_pos].copy()

    hoy_idx  = hoy_df.set_index("jugador_id").to_dict("index")  if not hoy_df.empty  else {}
    ayer_idx = ayer_df.set_index("jugador_id").to_dict("index") if not ayer_df.empty else {}

    filas = []
    for _, jug in jugadores_df.iterrows():
        jid = int(jug["id"])

        if jid in hoy_idx:
            src         = hoy_idx[jid]
            ya_guardado = True
        elif jid in ayer_idx:
            src         = ayer_idx[jid]
            ya_guardado = False
        else:
            src         = {}
            ya_guardado = False

        tipo = src.get("tipo_sesion", DEFECTO_TIPO)
        rpe  = int(src.get("rpe")     or DEFECTO_RPE)
        mins = int(src.get("minutos") or DEFECTO_MIN)

        filas.append({
            "jugador_id":     jid,
            "#":              int(jug["numero"]),
            "Jugador":        jug["jugador"],
            "Pos.":           jug["posicion"][:3].upper(),
            "✓":              "✅" if ya_guardado else "⬜",
            "Tipo de sesión": tipo,
            "RPE":            rpe  if tipo != "descanso" else 0,
            "Minutos":        mins if tipo != "descanso" else 0,
        })

    return pd.DataFrame(filas)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("📋 Front Desk")
    st.divider()

    fecha_sel = st.date_input("📅 Fecha de trabajo", value=date.today())
    fecha_str  = str(fecha_sel)
    fecha_ayer = str(fecha_sel - timedelta(days=1))

    st.divider()

    filtro_pos = st.radio(
        "Grupo de jugadores",
        ["Todos", "portero", "defensor", "mediocampista", "delantero"],
        captions=["25", "4", "8", "8", "5"],
    )

    st.divider()

    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption("Sistema de Monitoreo · EQUIPOPHYSICAL")


# ============================================================
# CARGA DE DATOS
# ============================================================

jugadores_df    = cargar_jugadores()
hoy_carga_df    = cargar_carga_interna_fecha(fecha_str)
ayer_carga_df   = cargar_carga_interna_fecha(fecha_ayer)
lesiones_act_df = cargar_lesiones_activas()
lesiones_all_df = cargar_lesiones_todas()

# Wellness de hoy (para el panel de estado)
wellness_df      = cargar_wellness()
wellness_hoy_df  = wellness_df[wellness_df["fecha"] == pd.Timestamp(fecha_str)] if not wellness_df.empty else pd.DataFrame()

n_total = len(jugadores_df)

# Completitud de cada área hoy
pct_carga   = round(len(hoy_carga_df) / n_total * 100) if n_total > 0 else 0
pct_wellness = round(len(wellness_hoy_df) / n_total * 100) if n_total > 0 else 0
n_activas   = len(lesiones_act_df)


# ============================================================
# HEADER
# ============================================================

col_tit, col_fec = st.columns([5, 1])
with col_tit:
    st.title("📋 Front Desk — Carga Diaria")
    st.caption(
        f"Central de ingreso de datos para el staff · "
        f"**{fecha_sel.strftime('%A %d de %B de %Y').capitalize()}**"
    )
with col_fec:
    st.markdown(
        f"<p style='text-align:right; color:gray; padding-top:18px; font-size:1.1rem'>"
        f"📅 {fecha_sel.strftime('%d/%m/%Y')}</p>",
        unsafe_allow_html=True,
    )


# ============================================================
# PANEL DE ESTADO — COMPLETITUD DEL DÍA
# ============================================================

st.subheader("📊 Estado de carga del día")

col_a, col_b, col_c, col_d = st.columns(4)

# --- Carga Interna ---
color_ci = _color_completitud(pct_carga)
with col_a:
    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:bold'>🏃 Carga Interna</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size:2rem; font-weight:bold; color:{color_ci}'>"
            f"{pct_carga}%</div>",
            unsafe_allow_html=True,
        )
        st.progress(pct_carga / 100)
        st.caption(f"{len(hoy_carga_df)} / {n_total} jugadores cargados")
        if pct_carga == 100:
            st.success("✅ Completo")
        elif pct_carga > 0:
            st.warning("⏳ En proceso")
        else:
            st.error("❌ Sin cargar")

# --- Wellness ---
color_w = _color_completitud(pct_wellness)
with col_b:
    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:bold'>💚 Wellness</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size:2rem; font-weight:bold; color:{color_w}'>"
            f"{pct_wellness}%</div>",
            unsafe_allow_html=True,
        )
        st.progress(pct_wellness / 100)
        st.caption(f"{len(wellness_hoy_df)} / {n_total} jugadores cargados")
        if pct_wellness == 100:
            st.success("✅ Completo")
        elif pct_wellness > 0:
            st.warning("⏳ En proceso")
        else:
            st.error("❌ Sin cargar")

# --- Lesiones activas ---
with col_c:
    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:bold'>🏥 Lesiones activas</div>",
            unsafe_allow_html=True,
        )
        color_les = "#FF4B4B" if n_activas > 0 else "#21C354"
        st.markdown(
            f"<div style='font-size:2rem; font-weight:bold; color:{color_les}'>"
            f"{n_activas}</div>",
            unsafe_allow_html=True,
        )
        st.caption("jugadores fuera de juego")
        if n_activas == 0:
            st.success("✅ Plantel completo")
        else:
            nombres = lesiones_act_df["jugador"].tolist()[:3]
            st.warning(f"⚠️ {', '.join(nombres)}" + (" y más..." if n_activas > 3 else ""))

# --- Fuerza/Gym ---
with col_d:
    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:bold'>🏋️ Fuerza / Gym</div>",
            unsafe_allow_html=True,
        )
        # Ver si hay sesiones de gym en carga_interna para hoy
        n_gym_hoy = len(hoy_carga_df[hoy_carga_df["tipo_sesion"] == "gym"]) if not hoy_carga_df.empty else 0
        color_gym = "#21C354" if n_gym_hoy > 0 else "#888"
        st.markdown(
            f"<div style='font-size:2rem; font-weight:bold; color:{color_gym}'>"
            f"{n_gym_hoy}</div>",
            unsafe_allow_html=True,
        )
        st.caption("jugadores con sesión de gym hoy")
        if n_gym_hoy > 0:
            st.info(f"📋 Ver detalles en **Carga Gym**")
        else:
            st.caption("Sin sesión de gym programada")

st.divider()


# ============================================================
# PESTAÑAS DE INGRESO
# ============================================================

tab_carga, tab_lesiones, tab_historial = st.tabs([
    "🏃 Carga Interna",
    "🏥 Lesiones",
    "📜 Historial de lesiones",
])


# ============================================================
# PESTAÑA 1: CARGA INTERNA
# ============================================================

with tab_carga:

    st.subheader("🏃 Carga interna diaria")
    st.caption(
        "Ingresá el tipo de sesión, RPE y duración en minutos para cada jugador. "
        "El training load (RPE × minutos) se calcula automáticamente."
    )

    # Referencia rápida de RPE
    with st.expander("📖 Referencia RPE (1-10)"):
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            st.markdown("""
            **Zona baja (1–4)**
            - 1-2 → Muy liviano / recuperación
            - 3-4 → Fácil, conversación fluida
            """)
        with col_r2:
            st.markdown("""
            **Zona media (5–7)**
            - 5-6 → Moderado, algo difícil
            - 7   → Duro pero sostenible
            """)
        with col_r3:
            st.markdown("""
            **Zona alta (8–10)**
            - 8-9 → Muy duro, cerca del límite
            - 10  → Máximo esfuerzo posible
            """)

    # Construir el formulario
    df_form_carga = construir_form_carga(
        jugadores_df, hoy_carga_df, ayer_carga_df, filtro_pos
    )

    # Configuración de columnas del editor
    config_carga = {
        "jugador_id":     st.column_config.NumberColumn(disabled=True, width="small"),
        "#":              st.column_config.NumberColumn("N°", disabled=True, width=45),
        "Jugador":        st.column_config.TextColumn("Jugador", disabled=True, width=180),
        "Pos.":           st.column_config.TextColumn("Pos.", disabled=True, width=55),
        "✓":              st.column_config.TextColumn("Hoy", disabled=True, width=45),
        "Tipo de sesión": st.column_config.SelectboxColumn(
                              "🎯 Tipo de sesión",
                              options=TIPOS_SESION,
                              required=True,
                              width=145,
                          ),
        "RPE":            st.column_config.NumberColumn(
                              "💢 RPE",
                              min_value=0, max_value=10, step=1,
                              help="0 = descanso · 1-10 = escala de esfuerzo percibido",
                              width=70,
                          ),
        "Minutos":        st.column_config.NumberColumn(
                              "⏱ Minutos",
                              min_value=0, max_value=180, step=5,
                              width=90,
                          ),
    }

    df_editado_carga = st.data_editor(
        df_form_carga,
        column_config=config_carga,
        column_order=["#", "Jugador", "Pos.", "✓", "Tipo de sesión", "RPE", "Minutos"],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=f"editor_carga_{fecha_str}_{filtro_pos}",
    )

    # Vista previa del training load
    df_prev_carga = df_editado_carga.copy()
    df_prev_carga["Training Load"] = df_prev_carga.apply(
        lambda r: int(r["RPE"] * r["Minutos"]) if r["Tipo de sesión"] != "descanso" and r["RPE"] > 0 else 0,
        axis=1
    )

    # Métricas rápidas de la sesión
    n_descansando = int((df_prev_carga["Tipo de sesión"] == "descanso").sum())
    n_partido     = int((df_prev_carga["Tipo de sesión"] == "partido").sum())
    tl_promedio   = df_prev_carga[df_prev_carga["Tipo de sesión"] != "descanso"]["Training Load"].mean()
    tl_max        = df_prev_carga["Training Load"].max()

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("🛋 En descanso",       n_descansando)
    col_m2.metric("⚽ En partido",         n_partido)
    col_m3.metric("📊 TL promedio equipo", f"{tl_promedio:.0f} UA" if not pd.isna(tl_promedio) else "—")
    col_m4.metric("🔝 TL máximo",          f"{tl_max:.0f} UA")

    # Previsualización con colores de training load
    def _color_tl(val):
        if pd.isna(val) or val == 0:
            return ""
        elif val < 300:
            return "background-color:#d4edda; color:#155724"   # verde → carga baja
        elif val < 500:
            return "background-color:#fff3cd; color:#856404"   # amarillo → carga media
        elif val < 700:
            return "background-color:#ffe5cc; color:#7a3c00"   # naranja → carga alta
        else:
            return "background-color:#f8d7da; color:#721c24"   # rojo → carga muy alta

    st.markdown("**Vista previa — Training Load (RPE × Minutos):**")
    cols_prev = ["#", "Jugador", "Pos.", "Tipo de sesión", "RPE", "Minutos", "Training Load"]

    styled_carga = (
        df_prev_carga[cols_prev].style
        .map(_color_tl, subset=["Training Load"])
        .format({"Training Load": "{:.0f}"})
        .hide(axis="index")
    )
    st.dataframe(styled_carga, use_container_width=True, height=350)

    # Botón guardar
    st.markdown(" ")
    col_btn_c, col_info_c = st.columns([1, 3])

    with col_btn_c:
        guardar_carga = st.button(
            "💾 Guardar carga interna",
            type="primary",
            use_container_width=True,
            key="btn_guardar_carga",
        )

    with col_info_c:
        st.markdown("<br>", unsafe_allow_html=True)
        n_ya = int((df_editado_carga["✓"] == "✅").sum())
        n_tot_form = len(df_editado_carga)
        if n_ya > 0:
            st.info(f"ℹ️ {n_ya} jugadores ya tienen datos para hoy — se sobreescribirán con los valores actuales.")
        else:
            st.info(f"📋 Se guardarán {n_tot_form} registros para el {fecha_sel.strftime('%d/%m/%Y')}.")

    if guardar_carga:
        try:
            n_guardados = guardar_carga_interna(df_editado_carga, fecha_str)
            st.cache_data.clear()
            st.success(
                f"✅ **{n_guardados} registros de carga interna guardados** "
                f"para el {fecha_sel.strftime('%d/%m/%Y')}. "
                f"El Dashboard y las métricas ACWR ya se actualizaron."
            )
            tl_alto = df_prev_carga[df_prev_carga["Training Load"] >= 700]
            if not tl_alto.empty:
                st.warning(
                    f"⚠️ {len(tl_alto)} jugador(es) con Training Load ≥ 700 UA: "
                    f"{', '.join(tl_alto['Jugador'].tolist()[:4])}. Revisar carga."
                )
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error al guardar: {e}")


# ============================================================
# PESTAÑA 2: LESIONES
# ============================================================

with tab_lesiones:

    col_les_nueva, col_les_alta = st.columns([1, 1])

    # ── NUEVA LESIÓN ─────────────────────────────────────────
    with col_les_nueva:
        st.subheader("🆕 Registrar nueva lesión")

        # Opciones de jugadores sin lesión activa actualmente
        ids_lesionados = set(lesiones_act_df["jugador_id"].tolist()) if not lesiones_act_df.empty else set()

        opciones_jug = {
            f"#{int(r['numero'])} {r['jugador']} ({r['posicion']})": int(r["id"])
            for _, r in jugadores_df.iterrows()
        }

        jug_les_nombre = st.selectbox(
            "Jugador lesionado",
            list(opciones_jug.keys()),
            key="sel_jug_lesion",
        )
        jug_les_id = opciones_jug[jug_les_nombre]

        # Aviso si el jugador ya tiene lesión activa
        if jug_les_id in ids_lesionados:
            st.warning("⚠️ Este jugador ya tiene una lesión activa registrada.")

        col_li1, col_li2 = st.columns(2)
        with col_li1:
            tipo_les = st.selectbox("Tipo de lesión", TIPOS_LESION, key="tipo_les")
        with col_li2:
            zona_les = st.selectbox("Zona corporal",  ZONAS_CUERPO, key="zona_les")

        col_li3, col_li4 = st.columns(2)
        with col_li3:
            fecha_les = st.date_input(
                "Fecha de ocurrencia",
                value=date.today(),
                key="fecha_les",
            )
        with col_li4:
            dias_baja = st.number_input(
                "Días de baja estimados",
                min_value=1,
                max_value=365,
                value=7,
                step=1,
                key="dias_baja",
            )

        fecha_alta_estimada = fecha_les + timedelta(days=int(dias_baja))
        st.info(f"📅 Alta estimada: **{fecha_alta_estimada.strftime('%d/%m/%Y')}**")

        st.divider()

        guardar_lesion = st.button(
            "🏥 Registrar lesión",
            type="primary",
            use_container_width=True,
            key="btn_nueva_lesion",
        )

        if guardar_lesion:
            try:
                registrar_lesion(
                    jugador_id      = jug_les_id,
                    fecha_inicio_str= str(fecha_les),
                    tipo            = tipo_les,
                    zona            = zona_les,
                    dias_baja       = int(dias_baja),
                )
                st.cache_data.clear()
                st.success(
                    f"✅ Lesión registrada: **{jug_les_nombre.split('(')[0].strip()}** — "
                    f"{tipo_les} en {zona_les}. "
                    f"Baja estimada: {dias_baja} días."
                )
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")

    # ── DAR DE ALTA ───────────────────────────────────────────
    with col_les_alta:
        st.subheader("✅ Dar de alta")

        if lesiones_act_df.empty:
            st.success("✅ No hay jugadores con lesión activa. Plantel completo.")
        else:
            hoy_ts = pd.Timestamp(date.today())

            for _, les in lesiones_act_df.iterrows():
                fecha_ini   = pd.Timestamp(les["fecha_inicio"])
                dias_baja_v = int(les["dias_baja"] or 0)
                dias_pasados= max(0, (hoy_ts - fecha_ini).days)
                dias_rest   = max(0, dias_baja_v - dias_pasados)

                # Color de la tarjeta según estado de recuperación
                if dias_rest == 0:
                    borde = "#21C354"
                    estado_txt = "✅ Alta médica disponible"
                elif dias_rest <= 5:
                    borde = "#FF8C00"
                    estado_txt = f"🔜 Regresa en {dias_rest} días"
                else:
                    borde = "#FF4B4B"
                    estado_txt = f"❌ {dias_rest} días restantes"

                with st.container(border=True):
                    col_info_les, col_btn_alta = st.columns([3, 1])

                    with col_info_les:
                        st.markdown(
                            f"**#{les.get('jugador_id','—')} {les['jugador']}** "
                            f"<span style='color:gray;font-size:0.85rem'>"
                            f"({les.get('posicion','').capitalize()})</span>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"🏥 {str(les['tipo_lesion']).capitalize()} — {les['zona_corporal']} &nbsp;|&nbsp; "
                            f"📅 Desde {pd.Timestamp(les['fecha_inicio']).strftime('%d/%m/%Y')} &nbsp;|&nbsp; "
                            f"⏱ Día {dias_pasados} / {dias_baja_v}",
                            unsafe_allow_html=True,
                        )
                        st.progress(
                            min(1.0, dias_pasados / dias_baja_v) if dias_baja_v > 0 else 1.0,
                            text=estado_txt,
                        )

                    with col_btn_alta:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button(
                            "✅ Alta",
                            key=f"alta_{les['jugador_id']}_{les['fecha_inicio']}",
                            use_container_width=True,
                            type="primary" if dias_rest == 0 else "secondary",
                        ):
                            dar_alta_lesion(int(les["id"]), str(date.today()))
                            st.cache_data.clear()
                            st.success(
                                f"✅ **{les['jugador']}** dado de alta el "
                                f"{date.today().strftime('%d/%m/%Y')}."
                            )
                            st.rerun()


# ============================================================
# PESTAÑA 3: HISTORIAL DE LESIONES
# ============================================================

with tab_historial:

    st.subheader("📜 Historial completo de lesiones")

    if lesiones_all_df.empty:
        st.info("Sin lesiones registradas.")
    else:
        # Filtros
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            filtro_estado = st.selectbox(
                "Estado",
                ["Todas", "Activas", "Resueltas"],
                key="filtro_estado_his",
            )
        with col_f2:
            filtro_tipo_les = st.selectbox(
                "Tipo de lesión",
                ["Todas"] + sorted(lesiones_all_df["tipo_lesion"].unique().tolist()),
                key="filtro_tipo_his",
            )
        with col_f3:
            filtro_pos_les = st.selectbox(
                "Posición",
                ["Todas", "portero", "defensor", "mediocampista", "delantero"],
                key="filtro_pos_his",
            )

        # Aplicar filtros
        df_hist_les = lesiones_all_df.copy()

        if filtro_estado == "Activas":
            df_hist_les = df_hist_les[df_hist_les["activo"] == 1]
        elif filtro_estado == "Resueltas":
            df_hist_les = df_hist_les[df_hist_les["activo"] == 0]

        if filtro_tipo_les != "Todas":
            df_hist_les = df_hist_les[df_hist_les["tipo_lesion"] == filtro_tipo_les]

        if filtro_pos_les != "Todas":
            df_hist_les = df_hist_les[df_hist_les["posicion"] == filtro_pos_les]

        # Formato para mostrar
        df_mostrar = df_hist_les[[
            "jugador", "posicion", "tipo_lesion", "zona_corporal",
            "fecha_inicio", "fecha_fin", "dias_baja", "activo"
        ]].copy()

        df_mostrar["activo"] = df_mostrar["activo"].map({1: "🔴 Activa", 0: "✅ Resuelta"})
        df_mostrar = df_mostrar.rename(columns={
            "jugador":      "Jugador",
            "posicion":     "Posición",
            "tipo_lesion":  "Tipo",
            "zona_corporal":"Zona",
            "fecha_inicio": "Inicio",
            "fecha_fin":    "Alta",
            "dias_baja":    "Días baja",
            "activo":       "Estado",
        })

        st.dataframe(df_mostrar, hide_index=True, use_container_width=True, height=420)

        # Resumen estadístico
        st.divider()
        st.markdown("**Resumen:**")
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Total registradas",    len(lesiones_all_df))
        col_s2.metric("Activas actualmente",  int(lesiones_all_df["activo"].sum()))
        col_s3.metric(
            "Promedio días de baja",
            f"{lesiones_all_df['dias_baja'].mean():.1f} días"
        )
        tipo_mas_comun = lesiones_all_df["tipo_lesion"].value_counts().index[0]
        col_s4.metric("Tipo más frecuente", tipo_mas_comun.capitalize())


# ============================================================
# PIE DE PÁGINA
# ============================================================

st.divider()
st.caption(
    f"📋 Front Desk · EQUIPOPHYSICAL · "
    f"Datos al {fecha_sel.strftime('%d/%m/%Y')} · "
    f"Carga interna: {pct_carga}% · Wellness: {pct_wellness}% · "
    f"Lesiones activas: {n_activas}"
)
