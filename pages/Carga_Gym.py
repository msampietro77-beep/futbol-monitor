"""
pages/Carga_Gym.py
==================
Módulo de fuerza y gimnasio.

Dos pestañas:
  📊 Análisis individual → evolución del 1RM y volumen semanal por jugador
  🏋️ Registrar sesión   → formulario para ingresar una nueva sesión de gym

Conceptos clave:
  1RM estimado  : peso máximo que un jugador podría mover en 1 repetición
                  Fórmula de Epley: carga × (1 + repeticiones / 30)
  Volumen total : series × repeticiones × kg  (carga total movida en la sesión)
  RPE           : esfuerzo percibido 1-10 (Rate of Perceived Exertion)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from streamlit_echarts import st_echarts, JsCode
import sqlite3

# ── Tema visual EQUIPOPHYSICAL (espejo de app.py) ──────────────
_EP_FONT = "'Inter', 'Segoe UI', sans-serif"
_EP_TOOLTIP = {
    "backgroundColor": "#1e1e2e", "borderWidth": 0, "borderRadius": 8,
    "extraCssText": "box-shadow:0 4px 12px rgba(0,0,0,.25);",
    "textStyle": {"color": "#ffffff", "fontSize": 12, "fontFamily": "'Inter','Segoe UI',sans-serif"},
}
_EP_LEGEND = {
    "bottom": 0, "left": "center", "orient": "horizontal",
    "icon": "circle", "itemWidth": 8, "itemHeight": 8, "itemGap": 24,
    "textStyle": {"fontSize": 11, "color": "#888888", "fontFamily": "'Inter','Segoe UI',sans-serif"},
}
_EP_ANIM = {
    "backgroundColor": "transparent", "animation": True,
    "animationDuration": 800, "animationEasing": "cubicOut", "animationDurationUpdate": 0,
}

def _ep_gradient(top_color, bot_color):
    return {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
            "colorStops": [{"offset": 0, "color": top_color}, {"offset": 1, "color": bot_color}]}

def _ep_grad_h(left_color, right_color):
    return {"type": "linear", "x": 0, "y": 0, "x2": 1, "y2": 0,
            "colorStops": [{"offset": 0, "color": left_color}, {"offset": 1, "color": right_color}]}
from datetime import date, timedelta

from metricas import (
    cargar_jugadores,
    cargar_fuerza_jugador,
    tendencia_rm_por_ejercicio,
    resumen_volumen_semanal,
    snapshot_fuerza_plantel,
    calcular_volumen_sesion,
)


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Fuerza y Gym",
    page_icon="🏋️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONEXIÓN A BASE DE DATOS (para el formulario de ingreso)
# ============================================================

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "futbol_monitoreo.db"
)

def _conectar():
    return sqlite3.connect(DB_PATH)


# ============================================================
# LISTA DE EJERCICIOS DISPONIBLES
# Misma lista que en database.py para consistencia
# ============================================================

EJERCICIOS = [
    "Sentadilla",
    "Peso muerto rumano",
    "Hip thrust",
    "Press de banca",
    "Prensa de piernas",
    "Curl de isquiotibiales",
    "Extensión de rodilla",
    "Remo con barra",
]


# ============================================================
# FUNCIÓN: GUARDAR SESIÓN EN LA BASE DE DATOS
# ============================================================

def guardar_sesion(jugador_id, fecha_str, ejercicios_df):
    """
    Inserta los registros de la sesión de fuerza en la tabla 'fuerza'.
    Calcula el 1RM estimado automáticamente con la fórmula de Epley.
    Usa INSERT OR IGNORE para no duplicar si se guarda dos veces.
    """
    conn = _conectar()
    cur  = conn.cursor()

    registros = []
    for _, row in ejercicios_df.iterrows():
        carga_kg     = float(row["Carga (kg)"])
        repeticiones = int(row["Repeticiones"])
        series       = int(row["Series"])
        rpe          = int(row["RPE"])
        notas        = str(row.get("Notas", "") or "")

        # Fórmula de Epley para estimar el 1RM
        rm_estimado = round(carga_kg * (1 + repeticiones / 30), 1)

        registros.append((
            int(jugador_id),
            fecha_str,
            str(row["Ejercicio"]),
            series,
            repeticiones,
            carga_kg,
            rpe,
            rm_estimado,
            notas if notas else None,
        ))

    cur.executemany("""
        INSERT INTO fuerza
            (jugador_id, fecha, ejercicio, series, repeticiones,
             carga_kg, rpe, rm_estimado, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, registros)

    conn.commit()
    conn.close()
    return len(registros)


# ============================================================
# FUNCIÓN: CARGAR ÚLTIMA SESIÓN PARA PRE-RELLENAR EL FORMULARIO
# ============================================================

def ultima_sesion_jugador(jugador_id):
    """
    Carga la sesión más reciente del jugador como punto de partida
    para el nuevo ingreso. Ayuda a ver la progresión de carga.
    """
    df = cargar_fuerza_jugador(jugador_id)
    if df.empty:
        return None

    ultima_fecha = df["fecha"].max()
    ultima = df[df["fecha"] == ultima_fecha][
        ["ejercicio", "series", "repeticiones", "carga_kg", "rpe"]
    ].copy()
    return ultima, ultima_fecha


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("🏋️ Fuerza y Gym")
    st.divider()

    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("""
    **Métricas de esta sección:**
    - **1RM estimado** → máximo teórico en 1 rep (Epley)
    - **Volumen** → series × reps × kg
    - **RPE** → esfuerzo percibido (1-10)
    """)
    st.divider()
    st.caption("Sistema de Monitoreo · EQUIPOPHYSICAL")


# ============================================================
# HEADER
# ============================================================

st.title("🏋️ Módulo de Fuerza y Gym")
st.caption(
    "Seguimiento del 1RM estimado, volumen de entrenamiento y registro de sesiones "
    "de fuerza del plantel."
)

st.divider()


# ============================================================
# CARGAR DATOS CON CACHÉ
# ============================================================

@st.cache_data(ttl=300)
def obtener_jugadores():
    return cargar_jugadores()

@st.cache_data(ttl=300)
def obtener_snapshot():
    return snapshot_fuerza_plantel()


jugadores_df = obtener_jugadores()
snapshot_df  = obtener_snapshot()


# ============================================================
# PESTAÑAS PRINCIPALES
# ============================================================

tab_analisis, tab_registro = st.tabs([
    "📊 Análisis individual",
    "🏋️ Registrar sesión",
])


# ============================================================
# PESTAÑA 1: ANÁLISIS INDIVIDUAL
# ============================================================

with tab_analisis:

    # --- Selector de jugador ---
    opciones_jugadores = {
        f"#{int(row['numero'])} {row['jugador']} ({row['posicion']})": int(row["id"])
        for _, row in jugadores_df.iterrows()
    }

    col_sel, col_info = st.columns([2, 1])
    with col_sel:
        jugador_sel_nombre = st.selectbox(
            "Seleccionar jugador",
            list(opciones_jugadores.keys()),
            key="sel_jugador_analisis",
        )
    jugador_sel_id = opciones_jugadores[jugador_sel_nombre]

    # Cargar datos del jugador seleccionado
    df_jug = cargar_fuerza_jugador(jugador_sel_id)

    with col_info:
        st.markdown("<br>", unsafe_allow_html=True)
        if df_jug.empty:
            st.warning("Sin datos de fuerza para este jugador.")
            st.stop()
        else:
            n_sesiones   = df_jug["fecha"].nunique()
            ultima_fecha = df_jug["fecha"].max()
            st.metric("Sesiones registradas", n_sesiones)

    st.divider()

    # --- Métricas resumen del jugador ---
    df_vol = calcular_volumen_sesion(df_jug)

    rm_max_por_ejercicio = (
        df_vol.groupby("ejercicio")["rm_estimado"].max().reset_index()
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sesiones totales",    n_sesiones)
    c2.metric("Última sesión",       ultima_fecha.strftime("%d/%m/%Y"))
    c3.metric("Ejercicios distintos", df_vol["ejercicio"].nunique())
    c4.metric(
        "Volumen máximo en sesión",
        f"{df_vol.groupby('fecha')['volumen_kg'].sum().max():,.0f} kg",
    )

    st.divider()

    # --- Selector de ejercicio para el gráfico de tendencia ---
    ejercicios_disponibles = sorted(df_jug["ejercicio"].unique().tolist())

    col_ej1, col_ej2 = st.columns([2, 1])
    with col_ej1:
        ejercicio_sel = st.selectbox(
            "Ejercicio para análisis de tendencia",
            ejercicios_disponibles,
            key="sel_ejercicio",
        )

    # --- Gráfico 1: Evolución del 1RM estimado ---
    tendencia = tendencia_rm_por_ejercicio(jugador_sel_id, ejercicio_sel)

    if not tendencia.empty:
        st.subheader(f"📈 Evolución del 1RM estimado — {ejercicio_sel}")

        _fechas_rm = [f.strftime("%d/%m/%y") for f in tendencia["fecha"]]
        option_rm = {
            **_EP_ANIM,
            "tooltip": {
                **_EP_TOOLTIP, "trigger": "axis",
                "axisPointer": {"type": "cross", "crossStyle": {"color": "#555"}},
            },
            "legend": {**_EP_LEGEND, "data": ["1RM estimado", "Carga utilizada"]},
            "grid": {"top": 40, "bottom": 70, "left": 60, "right": 24},
            "xAxis": {
                "type": "category", "data": _fechas_rm,
                "axisLabel": {"fontSize": 12, "color": "#666666", "fontFamily": _EP_FONT, "rotate": 30},
                "axisLine": {"show": False}, "axisTick": {"show": False}, "splitLine": {"show": False},
            },
            "yAxis": {
                "type": "value", "name": "kg",
                "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
                "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
                "axisLine": {"show": False}, "axisTick": {"show": False},
                "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
            },
            "series": [
                {
                    "name": "1RM estimado", "type": "line",
                    "data": [round(float(v), 1) for v in tendencia["rm_estimado"]],
                    "symbol": "circle", "symbolSize": 8,
                    "lineStyle": {"color": "#2d6a9f", "width": 2.5},
                    "itemStyle": {"color": "#2d6a9f"},
                },
                {
                    "name": "Carga utilizada", "type": "line",
                    "data": [round(float(v), 1) for v in tendencia["carga_kg"]],
                    "symbol": "circle", "symbolSize": 6,
                    "lineStyle": {"color": "#1a9e5c", "width": 1.8, "type": "dashed"},
                    "itemStyle": {"color": "#1a9e5c"},
                },
            ],
        }
        st_echarts(options=option_rm, height="350px")

        # Resumen numérico del ejercicio
        col_rm1, col_rm2, col_rm3, col_rm4 = st.columns(4)
        col_rm1.metric("1RM inicial",   f"{tendencia['rm_estimado'].iloc[0]:.1f} kg")
        col_rm2.metric("1RM actual",    f"{tendencia['rm_estimado'].iloc[-1]:.1f} kg")
        delta_rm = tendencia["rm_estimado"].iloc[-1] - tendencia["rm_estimado"].iloc[0]
        col_rm3.metric(
            "Progresión total",
            f"{delta_rm:+.1f} kg",
            delta=f"{delta_rm/tendencia['rm_estimado'].iloc[0]*100:+.1f}%",
            delta_color="normal",
        )
        col_rm4.metric("RPE promedio", f"{tendencia['rpe'].mean():.1f} / 10")

    st.divider()

    # --- Gráfico 2: Volumen semanal por ejercicio ---
    st.subheader("📦 Volumen de entrenamiento semanal")

    vol_semanal = resumen_volumen_semanal(jugador_sel_id)

    if not vol_semanal.empty:
        # Filtrar por los ejercicios del selector (o todos)
        opciones_vol = ["Todos"] + sorted(vol_semanal["ejercicio"].unique().tolist())
        filtro_vol = st.selectbox(
            "Ejercicio para volumen semanal",
            opciones_vol,
            key="sel_vol_ejercicio",
        )
        if filtro_vol != "Todos":
            vol_graf = vol_semanal[vol_semanal["ejercicio"] == filtro_vol].copy()
        else:
            # Si se muestran todos: sumar volumen por semana
            vol_graf = (
                vol_semanal.groupby("semana")["volumen_total_kg"]
                .sum()
                .reset_index()
                .assign(ejercicio="Total")
            )

        def _fmt_semana(s):
            if hasattr(s, "strftime"):
                return s.strftime("%d/%m")
            if hasattr(s, "start_time"):
                return s.start_time.strftime("%d/%m")
            return str(s)[:10]

        _fechas_vol = [_fmt_semana(s) for s in vol_graf["semana"]]
        option_vol = {
            **_EP_ANIM,
            "tooltip": {**_EP_TOOLTIP, "trigger": "axis"},
            "title": {
                "text": f"Volumen semanal — {'Todos los ejercicios' if filtro_vol == 'Todos' else filtro_vol}",
                "textStyle": {"fontSize": 14, "color": "#3D3D3D", "fontWeight": "600", "fontFamily": _EP_FONT},
                "top": 4, "left": 0,
            },
            "grid": {"top": 50, "bottom": 70, "left": 70, "right": 24},
            "xAxis": {
                "type": "category", "data": _fechas_vol,
                "axisLabel": {"fontSize": 12, "color": "#666666", "fontFamily": _EP_FONT, "rotate": 30},
                "axisLine": {"show": False}, "axisTick": {"show": False}, "splitLine": {"show": False},
            },
            "yAxis": {
                "type": "value", "name": "Volumen (kg)",
                "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
                "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
                "axisLine": {"show": False}, "axisTick": {"show": False},
                "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
            },
            "series": [{
                "type": "bar", "barMaxWidth": 52,
                "data": [
                    {
                        "value": round(float(v), 0),
                        "itemStyle": {
                            "color": _ep_gradient("#F47920", "rgba(244,121,32,0.40)"),
                            "borderRadius": [4, 4, 0, 0],
                            "shadowBlur": 4, "shadowColor": "rgba(0,0,0,0.08)",
                        },
                    }
                    for v in vol_graf["volumen_total_kg"]
                ],
                "label": {
                    "show": True, "position": "top",
                    "formatter": JsCode("function(p){ return p.value.toLocaleString(); }"),
                    "fontSize": 11, "color": "#3D3D3D", "fontFamily": _EP_FONT,
                },
            }],
        }
        st_echarts(options=option_vol, height="340px")

    st.divider()

    # --- Tabla de historial completo ---
    with st.expander("📋 Historial completo de sesiones"):
        df_hist = calcular_volumen_sesion(df_jug).copy()
        df_hist["fecha"] = df_hist["fecha"].dt.strftime("%d/%m/%Y")
        df_hist = df_hist[[
            "fecha", "ejercicio", "series", "repeticiones",
            "carga_kg", "rpe", "rm_estimado", "volumen_kg",
        ]].rename(columns={
            "fecha":        "Fecha",
            "ejercicio":    "Ejercicio",
            "series":       "Series",
            "repeticiones": "Reps",
            "carga_kg":     "Carga (kg)",
            "rpe":          "RPE",
            "rm_estimado":  "1RM est. (kg)",
            "volumen_kg":   "Volumen (kg)",
        })
        st.dataframe(df_hist, hide_index=True, use_container_width=True, height=350)

    st.divider()

    # --- Comparativa del plantel: 1RM actual en un ejercicio ---
    st.subheader("👥 Comparativa del plantel — 1RM actual")

    ejercicio_comp = st.selectbox(
        "Ejercicio para comparar el plantel",
        EJERCICIOS,
        key="sel_comparativa",
    )

    if not snapshot_df.empty:
        df_comp = snapshot_df[
            snapshot_df["ejercicio"] == ejercicio_comp
        ].copy().sort_values("rm_estimado", ascending=True)

        if df_comp.empty:
            st.info("Sin datos de este ejercicio en el plantel.")
        else:
            prom_equipo = df_comp["rm_estimado"].mean()

            _GRAD_POS = {
                "portero":       _ep_grad_h("rgba(45,106,159,0.40)",  "#2d6a9f"),
                "defensor":      _ep_grad_h("rgba(26,158,92,0.40)",   "#1a9e5c"),
                "mediocampista": _ep_grad_h("rgba(214,48,49,0.40)",   "#d63031"),
                "delantero":     _ep_grad_h("rgba(244,121,32,0.40)",  "#F47920"),
            }
            _default_grad = _ep_grad_h("rgba(136,136,136,0.4)", "#888888")

            _barras_comp = [
                {
                    "value": round(float(row["rm_estimado"]), 1),
                    "itemStyle": {
                        "color": _GRAD_POS.get(row["posicion"], _default_grad),
                        "borderRadius": [0, 4, 4, 0],
                        "shadowBlur": 4, "shadowColor": "rgba(0,0,0,0.08)",
                    },
                }
                for _, row in df_comp.iterrows()
            ]

            option_comp = {
                **_EP_ANIM,
                "tooltip": {
                    **_EP_TOOLTIP, "trigger": "axis",
                    "axisPointer": {"type": "shadow"},
                    "formatter": JsCode("""
function(params) {
    var p = params[0];
    return '<b>' + p.name + '</b><br/>1RM: <b>' + p.value.toFixed(1) + ' kg</b>';
}
"""),
                },
                "grid": {"top": 40, "bottom": 40, "left": 160, "right": 90},
                "xAxis": {
                    "type": "value", "name": "1RM estimado (kg)",
                    "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
                    "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
                    "axisLine": {"show": False}, "axisTick": {"show": False},
                    "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
                },
                "yAxis": {
                    "type": "category",
                    "data": df_comp["jugador"].tolist(),
                    "axisLabel": {"color": "#3D3D3D", "fontSize": 11, "fontFamily": _EP_FONT},
                    "axisLine": {"show": False}, "axisTick": {"show": False},
                    "splitLine": {"show": False},
                },
                "series": [{
                    "type": "bar", "data": _barras_comp, "barMaxWidth": 28,
                    "label": {
                        "show": True, "position": "right",
                        "formatter": JsCode("function(p){ return p.value.toFixed(1)+' kg'; }"),
                        "fontSize": 11, "color": "#3D3D3D", "fontFamily": _EP_FONT,
                    },
                    "markLine": {
                        "symbol": ["none", "none"], "silent": True,
                        "data": [{
                            "xAxis": round(float(prom_equipo), 1),
                            "lineStyle": {"type": "dashed", "color": "#888888", "width": 1.5},
                            "label": {
                                "formatter": f"Prom: {prom_equipo:.1f} kg",
                                "color": "#555555", "fontSize": 10, "position": "end",
                            },
                        }],
                    },
                }],
            }
            st_echarts(options=option_comp, height=f"{max(400, len(df_comp) * 30 + 80)}px")


# ============================================================
# PESTAÑA 2: REGISTRAR SESIÓN
# ============================================================

with tab_registro:

    st.subheader("🏋️ Nueva sesión de gym")
    st.caption(
        "Ingresá los ejercicios de la sesión. "
        "El 1RM estimado se calcula automáticamente con la fórmula de Epley."
    )

    # --- Selector de jugador y fecha ---
    col_r1, col_r2 = st.columns(2)

    with col_r1:
        jugador_reg_nombre = st.selectbox(
            "Jugador",
            list(opciones_jugadores.keys()),
            key="sel_jugador_registro",
        )
        jugador_reg_id = opciones_jugadores[jugador_reg_nombre]

    with col_r2:
        fecha_reg = st.date_input(
            "Fecha de la sesión",
            value=date.today(),
            key="fecha_registro",
        )

    # Mostrar la última sesión como referencia
    resultado_ultima = ultima_sesion_jugador(jugador_reg_id)
    if resultado_ultima:
        ultima_df, ultima_fecha_dt = resultado_ultima
        with st.expander(
            f"📋 Última sesión registrada: {ultima_fecha_dt.strftime('%d/%m/%Y')}"
        ):
            ultima_mostrar = ultima_df.copy()
            ultima_mostrar.columns = ["Ejercicio", "Series", "Reps", "Carga (kg)", "RPE"]
            # Calcular 1RM para mostrar
            ultima_mostrar["1RM est. (kg)"] = (
                ultima_mostrar["Carga (kg)"] * (1 + ultima_mostrar["Reps"] / 30)
            ).round(1)
            st.dataframe(ultima_mostrar, hide_index=True, use_container_width=True)

    st.divider()

    # --- Tabla editable de ejercicios ---
    st.markdown("**Ejercicios de la sesión:**")
    st.caption(
        "Añadí los ejercicios realizados. "
        "RPE: esfuerzo percibido del 1 (sin esfuerzo) al 10 (máximo esfuerzo)."
    )

    # DataFrame inicial con 4 filas vacías para empezar
    df_inicial = pd.DataFrame({
        "Ejercicio":    [EJERCICIOS[0], EJERCICIOS[1], EJERCICIOS[2], EJERCICIOS[3]],
        "Series":       [3, 3, 3, 3],
        "Repeticiones": [8, 8, 8, 8],
        "Carga (kg)":   [60.0, 60.0, 60.0, 60.0],
        "RPE":          [7, 7, 7, 7],
        "Notas":        ["", "", "", ""],
    })

    config_cols = {
        "Ejercicio":    st.column_config.SelectboxColumn(
                            "Ejercicio",
                            options=EJERCICIOS,
                            required=True,
                            width=200,
                        ),
        "Series":       st.column_config.NumberColumn(
                            "Series",
                            min_value=1, max_value=10, step=1,
                            width=80,
                        ),
        "Repeticiones": st.column_config.NumberColumn(
                            "Reps",
                            min_value=1, max_value=30, step=1,
                            width=70,
                        ),
        "Carga (kg)":   st.column_config.NumberColumn(
                            "Carga (kg)",
                            min_value=0.0, max_value=500.0, step=2.5,
                            format="%.1f",
                            width=110,
                        ),
        "RPE":          st.column_config.NumberColumn(
                            "RPE (1-10)",
                            min_value=1, max_value=10, step=1,
                            help="1=sin esfuerzo · 5=esfuerzo moderado · 10=máximo esfuerzo",
                            width=90,
                        ),
        "Notas":        st.column_config.TextColumn(
                            "Notas",
                            width=200,
                        ),
    }

    df_sesion = st.data_editor(
        df_inicial,
        column_config=config_cols,
        hide_index=True,
        num_rows="dynamic",          # se pueden agregar filas nuevas
        use_container_width=True,
        key="editor_sesion",
    )

    # --- Vista previa con 1RM calculado ---
    if not df_sesion.empty:
        st.markdown("**Vista previa — 1RM estimado (Fórmula de Epley):**")

        df_preview_reg = df_sesion.copy()
        df_preview_reg["1RM est. (kg)"] = (
            df_preview_reg["Carga (kg)"] * (1 + df_preview_reg["Repeticiones"] / 30)
        ).round(1)
        df_preview_reg["Volumen (kg)"] = (
            df_preview_reg["Series"] * df_preview_reg["Repeticiones"] * df_preview_reg["Carga (kg)"]
        ).round(1)

        # Colorear el 1RM según RPE
        def _color_rpe(val):
            """Verde si RPE bajo, amarillo si medio, rojo si alto."""
            if pd.isna(val):
                return ""
            elif val <= 6:
                return "background-color:#d4edda; color:#155724"
            elif val <= 8:
                return "background-color:#fff3cd; color:#856404"
            else:
                return "background-color:#f8d7da; color:#721c24"

        cols_preview = ["Ejercicio", "Series", "Repeticiones",
                        "Carga (kg)", "RPE", "1RM est. (kg)", "Volumen (kg)"]

        styled_prev = (
            df_preview_reg[cols_preview].style
            .map(_color_rpe, subset=["RPE"])
            .format({
                "Carga (kg)":    "{:.1f}",
                "1RM est. (kg)": "{:.1f}",
                "Volumen (kg)":  "{:,.0f}",
            })
            .hide(axis="index")
        )
        st.dataframe(styled_prev, use_container_width=True)

        # Totales de la sesión
        col_tot1, col_tot2, col_tot3 = st.columns(3)
        col_tot1.metric(
            "Ejercicios en sesión",
            len(df_sesion),
        )
        col_tot2.metric(
            "Volumen total sesión",
            f"{df_preview_reg['Volumen (kg)'].sum():,.0f} kg",
        )
        col_tot3.metric(
            "RPE promedio sesión",
            f"{df_sesion['RPE'].mean():.1f} / 10",
        )

    st.divider()

    # --- Botón de guardado ---
    col_btn_r, col_aviso_r = st.columns([1, 3])

    with col_btn_r:
        guardar_reg = st.button(
            "💾 Guardar sesión",
            type="primary",
            use_container_width=True,
        )

    with col_aviso_r:
        st.markdown("<br>", unsafe_allow_html=True)
        st.info(
            f"Guardando sesión del **{fecha_reg.strftime('%d/%m/%Y')}** "
            f"para **{jugador_reg_nombre.split('(')[0].strip()}**."
        )

    # Ejecutar guardado
    if guardar_reg:
        if df_sesion.empty:
            st.error("❌ No hay ejercicios para guardar. Completá la tabla.")
        else:
            try:
                # Validar que no haya celdas vacías en columnas obligatorias
                vacias = df_sesion[
                    df_sesion["Ejercicio"].isna() |
                    df_sesion["Carga (kg)"].isna() |
                    df_sesion["Repeticiones"].isna()
                ]
                if not vacias.empty:
                    st.error("❌ Hay filas incompletas. Completá ejercicio, carga y repeticiones.")
                else:
                    n_guardados = guardar_sesion(
                        jugador_id  = jugador_reg_id,
                        fecha_str   = str(fecha_reg),
                        ejercicios_df = df_sesion,
                    )
                    # Limpiar caché para que los gráficos se actualicen
                    st.cache_data.clear()

                    st.success(
                        f"✅ **{n_guardados} ejercicios guardados** para "
                        f"{jugador_reg_nombre.split('(')[0].strip()} "
                        f"— {fecha_reg.strftime('%d/%m/%Y')}. "
                        f"Los gráficos ya reflejan los nuevos datos."
                    )

                    # Mostrar resumen post-guardado
                    rpe_prom = df_sesion["RPE"].mean()
                    if rpe_prom >= 9:
                        st.warning(
                            f"⚠️ RPE promedio muy alto ({rpe_prom:.1f}/10). "
                            f"Revisar carga para la próxima sesión."
                        )
                    elif rpe_prom >= 7.5:
                        st.info(
                            f"📊 RPE promedio: {rpe_prom:.1f}/10 — "
                            f"sesión de carga moderada-alta."
                        )

            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")


# ============================================================
# PIE DE PÁGINA
# ============================================================

st.divider()
st.caption(
    "🏋️ Módulo de Fuerza y Gym · EQUIPOPHYSICAL · "
    "1RM estimado por fórmula de Epley: carga × (1 + reps / 30)"
)
