"""
pages/Perfil_Jugador.py
========================
Vista de riesgo del plantel y perfil individual por jugador.

Dos pestañas:
  1. Vista de equipo → scatter ACWR (eje X) vs Wellness (eje Y), un punto
     por jugador, con cuadrantes coloreados según la zona de riesgo ACWR
     (Gabbett 2016) — la misma clasificación que ya usa el Dashboard.
  2. Perfil individual → radar de 6 dimensiones (wellness, carga, ACWR,
     fuerza, sueño, estrés) comparando al jugador seleccionado contra el
     promedio del plantel.

Todas las dimensiones del radar se normalizan a una escala 0-100 donde
más alto siempre significa "mejor" (o "más cerca del rango óptimo" en
el caso de ACWR), para que las 6 puntas sean comparables entre sí.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from streamlit_echarts import st_echarts, JsCode

import auth
from metricas import (
    cargar_jugadores,
    resumen_acwr_plantel,
    calcular_baseline_plantel,
    snapshot_fuerza_plantel,
)


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Perfil de Jugador",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.exigir_acceso("Perfil_Jugador")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)


# --- Tema visual EQUIPOPHYSICAL (mismo bloque que el resto del proyecto) ---
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


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("🧭 Perfil de Jugador")
    if st.button("🔄 Actualizar datos", width='stretch'):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Sistema de Monitoreo de Rendimiento\nEQUIPOPHYSICAL")


# ============================================================
# CARGA DE DATOS (caché 5 minutos)
# ============================================================

@st.cache_data(ttl=300)
def _cargar_datos():
    jugadores = cargar_jugadores()
    acwr      = resumen_acwr_plantel()
    baseline  = calcular_baseline_plantel()
    fuerza    = snapshot_fuerza_plantel()
    return jugadores, acwr, baseline, fuerza

jugadores_df, acwr_df, baseline_df, fuerza_df = _cargar_datos()


# ============================================================
# PREPARAR TABLA BASE: un jugador por fila con todas las métricas
# ============================================================

def _indice_fuerza_por_jugador(fuerza_df):
    """
    Cada ejercicio tiene una escala de peso distinta (no es lo mismo
    un press banca que un curl de bíceps), así que no se puede promediar
    el rm_estimado directamente entre ejercicios.

    Se calcula un índice relativo: rm_estimado del jugador / rm_estimado
    promedio del plantel PARA ESE MISMO ejercicio. Un jugador "en el
    promedio" en todos sus ejercicios da índice ≈ 1.0.
    """
    if fuerza_df.empty:
        return pd.DataFrame(columns=["jugador_id", "fuerza_indice"])

    df = fuerza_df.copy()
    promedio_por_ejercicio = df.groupby("ejercicio")["rm_estimado"].transform("mean")
    df["rm_relativo"] = df["rm_estimado"] / promedio_por_ejercicio

    return (
        df.groupby("jugador_id")["rm_relativo"]
        .mean()
        .reset_index()
        .rename(columns={"rm_relativo": "fuerza_indice"})
    )


fuerza_idx_df = _indice_fuerza_por_jugador(fuerza_df)

datos = (
    jugadores_df[["id", "jugador", "posicion", "numero"]]
    .rename(columns={"id": "jugador_id"})
    .merge(acwr_df[["jugador_id", "acwr", "zona"]], on="jugador_id", how="left")
    .merge(
        baseline_df[["jugador_id", "wellness_hoy", "calidad_sueno", "estres",
                      "carga_baseline_28d"]],
        on="jugador_id", how="left",
    )
    .merge(fuerza_idx_df, on="jugador_id", how="left")
)


# ============================================================
# NORMALIZACIÓN 0-100 (más alto = mejor / más cerca del óptimo)
# ============================================================

def _normalizar_minmax(serie):
    """Escala una serie al rango 0-100 según el mínimo y máximo del plantel."""
    minimo, maximo = serie.min(), serie.max()
    if pd.isna(minimo) or pd.isna(maximo) or maximo == minimo:
        return pd.Series([50.0] * len(serie), index=serie.index)
    return ((serie - minimo) / (maximo - minimo) * 100).round(1)


def _normalizar_escala_1_5(serie, invertir=False):
    """Convierte una escala 1-5 a 0-100. invertir=True cuando 1=mejor."""
    valor = serie.clip(1, 5)
    if invertir:
        valor = 6 - valor
    return ((valor - 1) / 4 * 100).round(1)


def _normalizar_acwr(serie):
    """
    Puntúa qué tan cerca está el ACWR del centro de la zona óptima (1.05).
    100 = exactamente en el centro óptimo · 0 = a 0.67 puntos o más de distancia.
    """
    distancia = (serie - 1.05).abs()
    score = (100 - distancia * 150).clip(lower=0, upper=100)
    return score.round(1)


datos["score_wellness"] = _normalizar_escala_1_5(datos["wellness_hoy"])
datos["score_carga"]    = _normalizar_minmax(datos["carga_baseline_28d"])
datos["score_acwr"]     = _normalizar_acwr(datos["acwr"])
datos["score_fuerza"]   = _normalizar_minmax(datos["fuerza_indice"])
datos["score_sueno"]    = _normalizar_escala_1_5(datos["calidad_sueno"])
datos["score_estres"]   = _normalizar_escala_1_5(datos["estres"], invertir=True)

DIMENSIONES_RADAR = [
    ("score_wellness", "Wellness"),
    ("score_carga",    "Carga"),
    ("score_acwr",     "ACWR"),
    ("score_fuerza",   "Fuerza"),
    ("score_sueno",    "Sueño"),
    ("score_estres",   "Estrés"),
]

promedio_equipo = {col: round(float(datos[col].mean()), 1) for col, _ in DIMENSIONES_RADAR}


# ============================================================
# HEADER
# ============================================================

st.title("🧭 Perfil de Jugador y Mapa de Riesgo")
st.caption(
    "Vista de equipo (ACWR vs Wellness) y perfil individual de 6 dimensiones "
    "comparado contra el promedio del plantel."
)
st.divider()

tab_equipo, tab_individual = st.tabs(["📊 Vista de equipo (riesgo)", "👤 Perfil individual"])


# ============================================================
# TAB 1 — SCATTER PLOT: ACWR vs WELLNESS
# ============================================================

with tab_equipo:
    st.subheader("🎯 Mapa de Riesgo del Plantel — ACWR vs Wellness")
    st.caption(
        "Cada punto es un jugador. El color de fondo marca la zona clínica de "
        "ACWR (Gabbett 2016); las líneas punteadas marcan los umbrales de wellness."
    )

    _colores_zona = {
        "alto_riesgo":      "#d63031",
        "precaucion":       "#F47920",
        "optima":           "#1a9e5c",
        "desentrenamiento": "#e8a020",
        "sin datos":        "#999999",
    }

    scatter_df = datos.dropna(subset=["acwr", "wellness_hoy"]).copy()

    _scatter_data = [
        {
            "value": [round(float(row["acwr"]), 2), round(float(row["wellness_hoy"]), 2)],
            "name": row["jugador"],
            "posicion": row["posicion"],
            "numero": int(row["numero"]),
            "itemStyle": {
                "color": _colores_zona.get(row["zona"], "#999999"),
                "borderColor": "#fff",
                "borderWidth": 1,
                "shadowBlur": 3,
                "shadowColor": "rgba(0,0,0,0.15)",
            },
        }
        for _, row in scatter_df.iterrows()
    ]

    _tooltip_scatter = JsCode("""
function (p) {
    var d = p.data;
    return '<b>#' + d.numero + ' ' + d.name + '</b> (' + d.posicion + ')<br/>' +
           'ACWR: <b>' + d.value[0].toFixed(2) + '</b><br/>' +
           'Wellness: <b>' + d.value[1].toFixed(2) + '</b>';
}
""")

    y_max_scatter = max(5.5, float(scatter_df["wellness_hoy"].max()) + 0.3) if not scatter_df.empty else 5.5
    x_max_scatter = max(2.2, float(scatter_df["acwr"].max()) * 1.1) if not scatter_df.empty else 2.2

    option_scatter = {
        **_EP_ANIM,
        "tooltip": {**_EP_TOOLTIP, "formatter": _tooltip_scatter},
        "grid": {"top": 30, "bottom": 50, "left": 60, "right": 30},
        "xAxis": {
            "type": "value",
            "name": "ACWR",
            "min": 0,
            "max": x_max_scatter,
            "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
            "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "name": "Wellness",
            "min": 1,
            "max": y_max_scatter,
            "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
            "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
        },
        "series": [
            {
                # Serie invisible: solo dibuja las zonas de fondo del ACWR
                "type": "scatter",
                "data": [],
                "silent": True,
                "markArea": {
                    "silent": True,
                    "label": {"show": True, "position": "insideTop", "fontSize": 10, "color": "#898781"},
                    "data": [
                        [{"xAxis": 0,   "name": "Desentren.", "itemStyle": {"color": "rgba(232,160,32,0.07)"}}, {"xAxis": 0.8}],
                        [{"xAxis": 0.8, "name": "Óptima",     "itemStyle": {"color": "rgba(26,158,92,0.07)"}},  {"xAxis": 1.3}],
                        [{"xAxis": 1.3, "name": "Precaución", "itemStyle": {"color": "rgba(244,121,32,0.08)"}}, {"xAxis": 1.5}],
                        [{"xAxis": 1.5, "name": "Alto riesgo","itemStyle": {"color": "rgba(214,48,49,0.07)"}},  {"xAxis": x_max_scatter}],
                    ],
                },
                "markLine": {
                    "symbol": ["none", "none"],
                    "silent": True,
                    "lineStyle": {"type": "dashed", "width": 1.2, "color": "#aaaaaa"},
                    "label": {"fontSize": 10, "color": "#888888"},
                    "data": [
                        {"yAxis": 3.5, "label": {"formatter": "Wellness óptimo (3.5)"}},
                        {"yAxis": 2.8, "label": {"formatter": "Wellness bajo (2.8)"}},
                    ],
                },
            },
            {
                "type": "scatter",
                "symbolSize": 16,
                "data": _scatter_data,
            },
        ],
    }

    st_echarts(options=option_scatter, height="480px")

    st.markdown("""
    **Zonas ACWR (fondo):** 🟡 desentrenamiento `<0.8` · 🟢 óptima `0.8–1.3` ·
    🟠 precaución `1.3–1.5` · 🔴 alto riesgo `>1.5`
    """)


# ============================================================
# TAB 2 — RADAR INDIVIDUAL
# ============================================================

with tab_individual:
    st.subheader("🧭 Radar de 6 Dimensiones — Jugador vs Promedio del Equipo")

    opciones_jugadores = {
        f"#{int(row['numero'])} {row['jugador']} ({row['posicion']})": int(row["jugador_id"])
        for _, row in datos.sort_values(["posicion", "numero"]).iterrows()
    }
    jugador_sel_nombre = st.selectbox(
        "Seleccionar jugador", list(opciones_jugadores.keys()), key="sel_jugador_perfil"
    )
    jugador_sel_id = opciones_jugadores[jugador_sel_nombre]

    fila_jugador = datos[datos["jugador_id"] == jugador_sel_id].iloc[0]

    valores_jugador = [float(fila_jugador[col]) if pd.notna(fila_jugador[col]) else 0.0
                        for col, _ in DIMENSIONES_RADAR]
    valores_equipo  = [promedio_equipo[col] for col, _ in DIMENSIONES_RADAR]

    indicadores = [{"name": etiqueta, "min": 0, "max": 100} for _, etiqueta in DIMENSIONES_RADAR]

    option_radar = {
        **_EP_ANIM,
        "tooltip": {**_EP_TOOLTIP, "trigger": "item"},
        "legend": {**_EP_LEGEND, "data": [fila_jugador["jugador"], "Promedio del equipo"]},
        "radar": {
            "indicator": indicadores,
            "center": ["50%", "50%"],
            "radius": "65%",
            "splitNumber": 4,
            "axisName": {"color": "#3D3D3D", "fontSize": 12, "fontFamily": _EP_FONT},
            "splitLine": {"lineStyle": {"color": "#e6e6e6"}},
            "splitArea": {"areaStyle": {"color": ["#fafafa", "#f4f4f4"]}},
            "axisLine": {"lineStyle": {"color": "#dddddd"}},
        },
        "series": [{
            "type": "radar",
            "data": [
                {
                    "value": valores_jugador,
                    "name": fila_jugador["jugador"],
                    "areaStyle": {"color": "rgba(244,121,32,0.25)"},
                    "lineStyle": {"color": "#F47920", "width": 2.5},
                    "itemStyle": {"color": "#F47920"},
                },
                {
                    "value": valores_equipo,
                    "name": "Promedio del equipo",
                    "areaStyle": {"color": "rgba(61,61,61,0.08)"},
                    "lineStyle": {"color": "#3D3D3D", "width": 1.8, "type": "dashed"},
                    "itemStyle": {"color": "#3D3D3D"},
                },
            ],
        }],
    }

    col_radar, col_tabla = st.columns([2, 1])

    with col_radar:
        st_echarts(options=option_radar, height="420px")

    with col_tabla:
        st.markdown(f"**Detalle — {fila_jugador['jugador']}**")
        tabla_detalle = pd.DataFrame({
            "Dimensión": [etiqueta for _, etiqueta in DIMENSIONES_RADAR],
            "Jugador": valores_jugador,
            "Equipo": valores_equipo,
        })
        tabla_detalle["Diferencia"] = (tabla_detalle["Jugador"] - tabla_detalle["Equipo"]).round(1)
        st.dataframe(
            tabla_detalle.style.format({"Jugador": "{:.0f}", "Equipo": "{:.0f}", "Diferencia": "{:+.0f}"}),
            hide_index=True, width='stretch', height=250,
        )
        st.caption(
            "Escala 0-100 · más alto = mejor (en ACWR, más cerca del centro "
            "de la zona óptima 0.8–1.3)."
        )
