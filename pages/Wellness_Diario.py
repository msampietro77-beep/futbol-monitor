"""
pages/Wellness_Diario.py
========================
Formulario de carga diaria de wellness para el kinesiólogo.

Flujo de trabajo:
  1. Abre la página cada mañana
  2. Los 25 jugadores aparecen pre-cargados con los valores de ayer
  3. Modifica solo los que cambiaron
  4. Presiona "Guardar" — los datos aparecen inmediatamente en el Dashboard

Escala 1-5 para todos los ítems:
  Fatiga        → 1 = sin fatiga,   5 = muy fatigado   (más alto = peor)
  Calidad sueño → 1 = muy malo,     5 = excelente      (más alto = mejor)
  Horas sueño   → 1 = < 5 horas,   5 = > 9 horas      (más alto = mejor)
  Dolor musc.   → 1 = sin dolor,    5 = dolor severo   (más alto = peor)
  Humor         → 1 = muy malo,     5 = excelente      (más alto = mejor)
  Estrés        → 1 = muy bajo,     5 = muy alto       (más alto = peor)
"""

import streamlit as st
import pandas as pd
import sqlite3
import sys
import os
from datetime import date, timedelta

# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Wellness Diario",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Permite importar auth.py, que está un directorio arriba (raíz del proyecto)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

auth.exigir_acceso("Wellness_Diario")

# El médico puede VER esta página pero no cargar datos (solo lectura)
SOLO_LECTURA = auth.es_solo_lectura("Wellness_Diario")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
    /* Aumenta el tamaño de los inputs en la tabla editable */
    [data-testid="stDataEditor"] td { font-size: 0.95rem; }
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
# FUNCIONES DE DATOS
# ============================================================

def cargar_jugadores():
    """Carga el plantel completo ordenado por posición y número."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id AS jugador_id,
               nombre || ' ' || apellido AS jugador,
               posicion,
               numero_camiseta AS numero
        FROM jugadores
        ORDER BY
            CASE posicion
                WHEN 'portero'       THEN 1
                WHEN 'defensor'      THEN 2
                WHEN 'mediocampista' THEN 3
                WHEN 'delantero'     THEN 4
            END,
            numero_camiseta
    """, conn)
    conn.close()
    return df


def cargar_wellness_fecha(fecha_str):
    """Carga los registros de wellness de una fecha específica."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT jugador_id, fatiga, calidad_sueno, horas_sueno,
               dolor_muscular, humor, estres, wellness_total
        FROM wellness
        WHERE fecha = ?
    """, conn, params=[fecha_str])
    conn.close()
    return df


def guardar_wellness(filas, fecha_str):
    """
    Guarda o sobreescribe los registros de wellness para la fecha indicada.
    Usa INSERT OR REPLACE para manejar tanto inserciones nuevas como ediciones.
    Calcula wellness_total automáticamente antes de guardar.
    """
    conn = _conectar()
    cur  = conn.cursor()

    registros = []
    for _, row in filas.iterrows():
        fatiga         = int(row["Fatiga"])
        calidad_sueno  = int(row["Sueño calidad"])
        horas_sueno    = int(row["Sueño horas"])
        dolor_muscular = int(row["Dolor musc."])
        humor          = int(row["Humor"])
        estres         = int(row["Estrés"])

        # wellness_total: invierte los ítems negativos → más alto = mejor bienestar
        wellness_total = round(
            (
                (6 - fatiga)         +
                calidad_sueno        +
                horas_sueno          +
                (6 - dolor_muscular) +
                humor                +
                (6 - estres)
            ) / 6, 2
        )

        registros.append((
            int(row["jugador_id"]),
            fecha_str,
            fatiga, calidad_sueno, horas_sueno,
            dolor_muscular, humor, estres,
            wellness_total
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO wellness
            (jugador_id, fecha, fatiga, calidad_sueno, horas_sueno,
             dolor_muscular, humor, estres, wellness_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, registros)

    conn.commit()
    conn.close()
    return len(registros)


# ============================================================
# CONSTRUCCIÓN DEL DATAFRAME EDITABLE
# ============================================================

def construir_formulario(jugadores_df, wellness_hoy_df, wellness_ayer_df, filtro_pos):
    """
    Arma el DataFrame que se muestra en el editor.

    Lógica de pre-relleno:
      1. Si el jugador ya tiene datos hoy → usa esos datos (edición)
      2. Si tiene datos de ayer → los usa como punto de partida
      3. Si no hay datos anteriores → valor por defecto = 3
    """
    DEFECTO = 3

    # Filtrar por posición si corresponde
    if filtro_pos != "Todos":
        jugadores_df = jugadores_df[jugadores_df["posicion"] == filtro_pos].copy()

    # Índices para búsqueda rápida
    hoy_dict  = wellness_hoy_df.set_index("jugador_id").to_dict("index")  if not wellness_hoy_df.empty  else {}
    ayer_dict = wellness_ayer_df.set_index("jugador_id").to_dict("index") if not wellness_ayer_df.empty else {}

    filas = []
    for _, jug in jugadores_df.iterrows():
        jid = jug["jugador_id"]

        # Prioridad: hoy > ayer > defecto
        if jid in hoy_dict:
            src = hoy_dict[jid]
            ya_guardado = True
        elif jid in ayer_dict:
            src = ayer_dict[jid]
            ya_guardado = False
        else:
            src = {}
            ya_guardado = False

        filas.append({
            "jugador_id":   jid,
            "#":            int(jug["numero"]),
            "Jugador":      jug["jugador"],
            "Pos.":         jug["posicion"][:3].upper(),
            "✓":            "✅" if ya_guardado else "⬜",
            "Fatiga":       int(src.get("fatiga",         DEFECTO)),
            "Sueño calidad":int(src.get("calidad_sueno",  DEFECTO)),
            "Sueño horas":  int(src.get("horas_sueno",    DEFECTO)),
            "Dolor musc.":  int(src.get("dolor_muscular", DEFECTO)),
            "Humor":        int(src.get("humor",           DEFECTO)),
            "Estrés":       int(src.get("estres",          DEFECTO)),
        })

    return pd.DataFrame(filas)


def calcular_wellness_total(df):
    """Calcula wellness_total para previsualización (no se guarda en DB desde aquí)."""
    df = df.copy()
    df["Wellness"] = (
        (6 - df["Fatiga"])          +
        df["Sueño calidad"]         +
        df["Sueño horas"]           +
        (6 - df["Dolor musc."])     +
        df["Humor"]                 +
        (6 - df["Estrés"])
    ) / 6
    df["Wellness"] = df["Wellness"].round(2)
    return df


def color_wellness(val):
    """Colorea la columna Wellness según nivel."""
    if pd.isna(val):
        return ""
    elif val >= 3.5:
        return "background-color:#d4edda; color:#155724; font-weight:bold"
    elif val >= 2.8:
        return "background-color:#fff3cd; color:#856404; font-weight:bold"
    else:
        return "background-color:#f8d7da; color:#721c24; font-weight:bold"


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("📝 Wellness Diario")
    st.divider()

    # Selector de fecha (por defecto hoy)
    fecha_sel = st.date_input("📅 Fecha de carga", value=date.today())

    st.divider()

    # Filtro por posición para trabajar en grupos
    filtro_pos = st.radio(
        "Grupo de jugadores",
        ["Todos", "portero", "defensor", "mediocampista", "delantero"],
        captions=["25 jugadores", "4", "8", "8", "5"],
    )

    st.divider()
    st.caption(
        "💡 **Tip rápido:** Los valores se pre-cargan con los datos de ayer. "
        "Solo modificá lo que cambió."
    )
    st.divider()
    st.caption("Sistema de Monitoreo · EQUIPOPHYSICAL")


# ============================================================
# CARGA DE DATOS PARA LA FECHA SELECCIONADA
# ============================================================

fecha_str    = str(fecha_sel)
fecha_ayer   = str(fecha_sel - timedelta(days=1))

jugadores_df    = cargar_jugadores()
wellness_hoy_df = cargar_wellness_fecha(fecha_str)
wellness_ayer_df = cargar_wellness_fecha(fecha_ayer)

n_total         = len(jugadores_df)
n_completados   = len(wellness_hoy_df)
pct_completado  = round(n_completados / n_total * 100) if n_total > 0 else 0


# ============================================================
# HEADER
# ============================================================

col_tit, col_estado = st.columns([4, 2])
with col_tit:
    st.title("📝 Carga Diaria de Wellness")
    st.caption(f"Fecha: **{fecha_sel.strftime('%A %d de %B de %Y').capitalize()}**")
    if SOLO_LECTURA:
        st.info("👁️ **Modo solo lectura** — tu rol puede ver los datos pero no cargarlos.")

with col_estado:
    # Barra de progreso del día
    st.markdown("<br>", unsafe_allow_html=True)
    if n_completados == n_total:
        st.success(f"✅ Plantel completo cargado ({n_total}/{n_total})")
    elif n_completados > 0:
        st.warning(f"⏳ {n_completados} / {n_total} jugadores cargados hoy")
        st.progress(pct_completado / 100)
    else:
        st.info(f"📋 Sin datos para hoy — se pre-cargan valores de ayer")
        st.progress(0.0)


# ============================================================
# REFERENCIA DE ESCALA (expandible para no ocupar espacio)
# ============================================================

with st.expander("📖 Referencia de escala 1-5"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("""
        **😴 Fatiga** *(más alto = peor)*
        - 1 = Sin fatiga
        - 3 = Fatiga moderada
        - 5 = Muy fatigado

        **💪 Dolor muscular** *(más alto = peor)*
        - 1 = Sin dolor
        - 3 = Dolor moderado
        - 5 = Dolor severo
        """)
    with col_b:
        st.markdown("""
        **🌙 Calidad de sueño** *(más alto = mejor)*
        - 1 = Muy mala
        - 3 = Normal
        - 5 = Excelente

        **⏰ Horas de sueño** *(más alto = mejor)*
        - 1 = < 5 horas
        - 3 = 6–7 horas
        - 5 = > 9 horas
        """)
    with col_c:
        st.markdown("""
        **😊 Humor** *(más alto = mejor)*
        - 1 = Muy malo
        - 3 = Normal
        - 5 = Excelente

        **🧠 Estrés** *(más alto = peor)*
        - 1 = Sin estrés
        - 3 = Estrés moderado
        - 5 = Muy estresado
        """)

st.divider()


# ============================================================
# FORMULARIO PRINCIPAL — TABLA EDITABLE
# ============================================================

df_form = construir_formulario(
    jugadores_df, wellness_hoy_df, wellness_ayer_df, filtro_pos
)

# Configuración de columnas para el editor
column_config = {
    "jugador_id":    st.column_config.NumberColumn(disabled=True, width="small"),
    "#":             st.column_config.NumberColumn("N°", disabled=True, width=40),
    "Jugador":       st.column_config.TextColumn("Jugador", disabled=True, width=180),
    "Pos.":          st.column_config.TextColumn("Pos.", disabled=True, width=50),
    "✓":             st.column_config.TextColumn("Hoy", disabled=True, width=40),
    "Fatiga":        st.column_config.NumberColumn(
                         "😴 Fatiga", min_value=1, max_value=5, step=1,
                         help="1=sin fatiga · 5=muy fatigado  (más alto = peor)",
                         width=80),
    "Sueño calidad": st.column_config.NumberColumn(
                         "🌙 Sueño cal.", min_value=1, max_value=5, step=1,
                         help="1=muy malo · 5=excelente",
                         width=100),
    "Sueño horas":   st.column_config.NumberColumn(
                         "⏰ Sueño hs.", min_value=1, max_value=5, step=1,
                         help="1=<5h · 3=6-7h · 5=>9h",
                         width=100),
    "Dolor musc.":   st.column_config.NumberColumn(
                         "💪 Dolor", min_value=1, max_value=5, step=1,
                         help="1=sin dolor · 5=dolor severo  (más alto = peor)",
                         width=80),
    "Humor":         st.column_config.NumberColumn(
                         "😊 Humor", min_value=1, max_value=5, step=1,
                         help="1=muy malo · 5=excelente",
                         width=80),
    "Estrés":        st.column_config.NumberColumn(
                         "🧠 Estrés", min_value=1, max_value=5, step=1,
                         help="1=sin estrés · 5=muy estresado  (más alto = peor)",
                         width=80),
}

# Editor de datos — el corazón del formulario
df_editado = st.data_editor(
    df_form,
    column_config=column_config,
    column_order=["#", "Jugador", "Pos.", "✓",
                  "Fatiga", "Sueño calidad", "Sueño horas",
                  "Dolor musc.", "Humor", "Estrés"],
    hide_index=True,
    width='stretch',
    num_rows="fixed",           # no se pueden agregar/quitar filas
    disabled=SOLO_LECTURA,       # médico: solo puede ver, no editar
    key=f"editor_{fecha_str}_{filtro_pos}",
)


# ============================================================
# PREVISUALIZACIÓN DE WELLNESS TOTAL (antes de guardar)
# ============================================================

df_preview = calcular_wellness_total(df_editado)

st.markdown("**Vista previa del Wellness Total calculado:**")

preview_cols = ["#", "Jugador", "Pos.", "Fatiga", "Sueño calidad", "Sueño horas",
                "Dolor musc.", "Humor", "Estrés", "Wellness"]

styled_preview = (
    df_preview[preview_cols].style
    .map(color_wellness, subset=["Wellness"])
    .format({"Wellness": "{:.2f}"})
    .hide(axis="index")
)

st.dataframe(styled_preview, width='stretch', height=320)


# ============================================================
# BOTÓN DE GUARDADO
# ============================================================

st.markdown(" ")
col_btn, col_info = st.columns([1, 3])

with col_btn:
    guardar = st.button(
        "💾 Guardar wellness",
        type="primary",
        use_container_width=True,
        disabled=SOLO_LECTURA,
    )

with col_info:
    n_en_form = len(df_editado)
    alertas_bajas = int((df_preview["Wellness"] < 2.8).sum())

    if alertas_bajas > 0:
        st.warning(
            f"⚠️ {alertas_bajas} jugador(es) con Wellness < 2.8 — "
            f"revisar antes de guardar"
        )
    else:
        st.info(
            f"📋 Guardando {n_en_form} jugadores para el {fecha_sel.strftime('%d/%m/%Y')}. "
            f"Los datos actualizarán el Dashboard inmediatamente."
        )

# Ejecutar guardado
if guardar:
    try:
        # Validar que todos los valores estén en rango 1-5
        items = ["Fatiga", "Sueño calidad", "Sueño horas", "Dolor musc.", "Humor", "Estrés"]
        fuera_de_rango = []
        for item in items:
            invalidos = df_editado[
                (df_editado[item] < 1) | (df_editado[item] > 5)
            ]["Jugador"].tolist()
            if invalidos:
                fuera_de_rango.extend([f"{j} ({item})" for j in invalidos])

        if fuera_de_rango:
            st.error(
                f"❌ Valores fuera de rango (1-5) en: {', '.join(fuera_de_rango[:5])}. "
                f"Corregí antes de guardar."
            )
        else:
            n_guardados = guardar_wellness(df_editado, fecha_str)

            # Limpiar caché para que el Dashboard se actualice
            st.cache_data.clear()

            st.success(
                f"✅ **{n_guardados} registros guardados correctamente** para el "
                f"{fecha_sel.strftime('%d/%m/%Y')}. "
                f"El Dashboard ya refleja los nuevos datos."
            )

            # Mostrar resumen de alertas generado
            df_final = calcular_wellness_total(df_editado)
            rojos   = int((df_final["Wellness"] < 2.0).sum())
            naranjas = int(((df_final["Wellness"] >= 2.0) & (df_final["Wellness"] < 2.8)).sum())

            if rojos + naranjas > 0:
                st.warning(
                    f"🔴 {rojos} jugador(es) con Wellness crítico (<2.0)   "
                    f"🟠 {naranjas} jugador(es) con Wellness bajo (2.0–2.8)"
                )

            # Forzar recarga para reflejar el estado actualizado (✅ en columna Hoy)
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")


# ============================================================
# RESUMEN DEL DÍA (al pie, solo si ya hay datos guardados)
# ============================================================

if n_completados > 0:
    st.divider()
    st.subheader("📊 Resumen del día")

    wellness_hoy_df_fresh = cargar_wellness_fecha(fecha_str)

    col_res1, col_res2, col_res3, col_res4 = st.columns(4)

    col_res1.metric(
        "📋 Jugadores cargados",
        f"{n_completados} / {n_total}"
    )
    col_res2.metric(
        "💚 Wellness promedio",
        f"{wellness_hoy_df_fresh['wellness_total'].mean():.2f}"
    )
    col_res3.metric(
        "🔴 Wellness crítico (<2.0)",
        int((wellness_hoy_df_fresh["wellness_total"] < 2.0).sum())
    )
    col_res4.metric(
        "🟠 Wellness bajo (2.0–2.8)",
        int(
            ((wellness_hoy_df_fresh["wellness_total"] >= 2.0) &
             (wellness_hoy_df_fresh["wellness_total"] < 2.8)).sum()
        )
    )
