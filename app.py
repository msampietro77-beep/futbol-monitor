"""
app.py
======
Dashboard operativo diario para reunión de staff.

Cómo ejecutar:
  streamlit run app.py

Nota Streamlit Cloud:
  La base de datos no está en GitHub. Al iniciar por primera vez
  (o si el archivo no existe), se crea automáticamente con datos
  simulados ejecutando database.py.
"""

import os
import streamlit as st
import pandas as pd
from streamlit_echarts import st_echarts, JsCode
from datetime import date, timedelta


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
    h1 {margin-bottom: 0.2rem;}
    .stMetric label {font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# INICIALIZACIÓN AUTOMÁTICA DE LA BASE DE DATOS
# Se ejecuta solo si el archivo .db no existe (primer arranque
# en Streamlit Cloud o entorno nuevo sin la base de datos).
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futbol_monitoreo.db")

import database, sqlite3

if not os.path.exists(DB_PATH):
    # Primera vez: crear tablas + simular 90 días de datos
    with st.spinner("⏳ Primera ejecución: creando base de datos con datos simulados..."):
        database.inicializar_base_datos()
    st.success("✅ Base de datos creada correctamente. Cargando el sistema...")
    st.rerun()
else:
    # DB ya existe: garantizar que las tablas nuevas estén creadas
    # (CREATE TABLE IF NOT EXISTS e INSERT OR IGNORE son seguros de repetir)
    _conn = sqlite3.connect(DB_PATH)
    database.crear_tablas(_conn)
    database.insertar_protocolo_rtp(_conn)
    _conn.close()


# ============================================================
# IMPORTAR MÉTRICAS (después de garantizar que la DB existe)
# ============================================================

from metricas import (
    reporte_disponibilidad,
    resumen_acwr_plantel,
    cargar_lesiones_activas,
    calcular_acwr_ewma,
    cargar_wellness,
    cargar_jugadores,
    cargar_etapas_rtp,
    cargar_sesiones_rtp_jugador,
)


# ============================================================
# CARGA DE DATOS (caché 5 minutos)
# ============================================================

@st.cache_data(ttl=300)
def obtener_reporte():
    return reporte_disponibilidad()

@st.cache_data(ttl=300)
def obtener_acwr_snapshot():
    return resumen_acwr_plantel()

@st.cache_data(ttl=300)
def obtener_acwr_historico():
    return calcular_acwr_ewma()

@st.cache_data(ttl=300)
def obtener_wellness_historico():
    return cargar_wellness()

@st.cache_data(ttl=300)
def obtener_estado_rtp():
    """
    Construye el resumen RTP del plantel para el dashboard.
    Por cada jugador con sesiones RTP: etapa actual, último EVA, última confianza,
    días en rehabilitación y porcentaje de progreso en el protocolo.
    """
    jugadores  = cargar_jugadores()
    etapas     = cargar_etapas_rtp()
    n_etapas   = len(etapas)

    filas = []
    for _, jug in jugadores.iterrows():
        sesiones = cargar_sesiones_rtp_jugador(int(jug["id"]))
        if sesiones.empty:
            continue

        ultima     = sesiones.iloc[-1]
        primera    = sesiones.iloc[0]
        dias_rtp   = (sesiones["fecha"].max() - sesiones["fecha"].min()).days + 1
        pct_avance = round((int(ultima["etapa_orden"]) / n_etapas) * 100)

        filas.append({
            "jugador_id":      int(jug["id"]),
            "jugador":         jug["jugador"],
            "posicion":        jug["posicion"],
            "numero":          int(jug["numero"]),
            "etapa_orden":     int(ultima["etapa_orden"]),
            "etapa_nombre":    ultima["etapa_nombre"],
            "dias_rtp":        dias_rtp,
            "pct_avance":      pct_avance,
            "eva_ultimo":      ultima["eva_promedio"],
            "confianza_ultimo":ultima["confianza_promedio"],
            "ultima_sesion":   ultima["fecha"].strftime("%d/%m/%Y"),
            "avanza":          bool(ultima["avanza"]),
        })

    return pd.DataFrame(filas) if filas else pd.DataFrame()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("⚙️ Opciones")
    if st.button("🔄 Actualizar datos", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    posiciones = ["Todas", "portero", "defensor", "mediocampista", "delantero"]
    filtro_pos = st.selectbox("Filtrar semáforo por posición", posiciones)

    st.divider()
    st.caption("Sistema de Monitoreo de Rendimiento\nEQUIPOPHYSICAL")


# ============================================================
# CARGA INICIAL
# ============================================================

reporte     = obtener_reporte()
r           = reporte["resumen"]
acwr_df     = obtener_acwr_snapshot()
disponibles = reporte["disponibles"].copy()
lesionados  = reporte["lesionados"].copy()


# ============================================================
# HEADER
# ============================================================

col_titulo, col_fecha = st.columns([5, 1])
with col_titulo:
    st.title("⚽ Monitor de Rendimiento del Plantel")
with col_fecha:
    st.markdown(
        f"<p style='text-align:right; color:gray; padding-top:18px; font-size:1.1rem'>"
        f"📅 {r['fecha']}</p>",
        unsafe_allow_html=True,
    )


# ============================================================
# SECCIÓN 1: MÉTRICAS DEL PLANTEL
# ============================================================

disponibilidad_pct = round(r["disponibles"] / r["total_plantel"] * 100, 1)

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("👥 Plantel total",  r["total_plantel"])
c2.metric("✅ Disponibles",    r["disponibles"])
c3.metric("🚑 Lesionados",     r["lesionados"],
          delta=f"-{r['lesionados']}", delta_color="inverse")
c4.metric("📊 Disponibilidad", f"{disponibilidad_pct}%")
c5.metric("🔴 Roja",           r["alertas_rojas"],
          delta=None if r["alertas_rojas"] == 0 else f"{r['alertas_rojas']} activas",
          delta_color="inverse")
c6.metric("🟠 Naranja",        r["alertas_naranja"])
c7.metric("🟡 Amarilla",       r["alertas_amarillas"])

st.divider()


# ============================================================
# SECCIÓN 2: SEMÁFORO DE ALERTAS POR JUGADOR
# ============================================================

st.subheader("🚦 Estado del Plantel")

if filtro_pos != "Todas":
    disponibles = disponibles[disponibles["posicion"] == filtro_pos]

ICONO = {"ROJA": "🔴", "NARANJA": "🟠", "AMARILLA": "🟡", "VERDE": "🟢"}
COLOR_FONDO = {
    "ROJA":     "background-color:#FF4B4B; color:white; font-weight:bold; text-align:center",
    "NARANJA":  "background-color:#FF8C00; color:white; font-weight:bold; text-align:center",
    "AMARILLA": "background-color:#FFD700; color:black; font-weight:bold; text-align:center",
    "VERDE":    "background-color:#21C354; color:white; font-weight:bold; text-align:center",
}

semaforo = disponibles[[
    "numero", "jugador", "posicion",
    "tipo_sesion", "training_load",
    "acwr", "wellness_hoy",
    "alerta", "motivo",
]].copy()

semaforo.insert(0, " ", semaforo["alerta"].map(ICONO))
semaforo["training_load"] = semaforo["training_load"].fillna(0).astype(int)
semaforo = semaforo.rename(columns={
    "numero":        "#",
    "jugador":       "Jugador",
    "posicion":      "Posición",
    "tipo_sesion":   "Sesión hoy",
    "training_load": "Carga (UA)",
    "acwr":          "ACWR",
    "wellness_hoy":  "Wellness",
    "alerta":        "Alerta",
    "motivo":        "Detalle",
})

def _color_alerta_celda(val):
    return COLOR_FONDO.get(val, "")

def _color_acwr_celda(val):
    if pd.isna(val):
        return ""
    elif val < 0.8:
        return "background-color:#FFD700; color:black; font-weight:bold"
    elif val <= 1.3:
        return "background-color:#21C354; color:white; font-weight:bold"
    elif val <= 1.5:
        return "background-color:#FF8C00; color:white; font-weight:bold"
    else:
        return "background-color:#FF4B4B; color:white; font-weight:bold"

styled_semaforo = (
    semaforo.style
    .map(_color_alerta_celda, subset=["Alerta"])
    .map(_color_acwr_celda,   subset=["ACWR"])
    .format({"ACWR": "{:.2f}", "Wellness": "{:.1f}"}, na_rep="—")
    .hide(axis="index")
)

st.dataframe(styled_semaforo, width='stretch', height=500)

st.divider()


# --- Tema visual compartido (Inter + paleta EQUIPOPHYSICAL) ---
_EP_FONT    = "'Inter', 'Segoe UI', sans-serif"
_EP_TOOLTIP = {
    "backgroundColor": "#1e1e2e",
    "borderWidth": 0,
    "borderRadius": 8,
    "extraCssText": "box-shadow:0 4px 12px rgba(0,0,0,.25);",
    "textStyle": {"color": "#ffffff", "fontSize": 12, "fontFamily": "'Inter','Segoe UI',sans-serif"},
}
_EP_LEGEND = {
    "bottom": 0,
    "left": "center",
    "orient": "horizontal",
    "icon": "circle",
    "itemWidth": 8,
    "itemHeight": 8,
    "itemGap": 24,
    "textStyle": {"fontSize": 11, "color": "#888888", "fontFamily": "'Inter','Segoe UI',sans-serif"},
}
_EP_ANIM = {
    "backgroundColor": "transparent",
    "animation": True,
    "animationDuration": 800,
    "animationEasing": "cubicOut",
    "animationDurationUpdate": 0,
}

def _ep_gradient(top_color, bot_color):
    return {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
            "colorStops": [{"offset": 0, "color": top_color},
                           {"offset": 1, "color": bot_color}]}

# ============================================================
# SECCIÓN 3: EVOLUCIÓN ACWR — ÚLTIMOS 30 DÍAS
# ============================================================

st.subheader("📉 Evolución ACWR del Plantel — Últimos 30 días")

acwr_hist = obtener_acwr_historico()
fecha_max_a = acwr_hist["fecha"].max()
acwr_30d = acwr_hist[acwr_hist["fecha"] >= fecha_max_a - timedelta(days=29)].copy()

# Diccionario de alertas actuales por jugador_id para colorear líneas
alertas_disponibles = reporte["disponibles"][["jugador_id", "alerta"]].copy()
alertas_lesionados  = reporte["lesionados"][["jugador_id"]].copy()
alertas_lesionados["alerta"] = "ROJA"
alertas_todas = pd.concat([alertas_disponibles, alertas_lesionados], ignore_index=True)
alertas_dict  = dict(zip(alertas_todas["jugador_id"], alertas_todas["alerta"]))

# Colores EQUIPOPHYSICAL por nivel de alerta clínica
COLOR_LINEA_EC = {
    "ROJA":     "#d63031",
    "NARANJA":  "#F47920",
    "AMARILLA": "#e8a020",
    "VERDE":    "rgba(180,180,180,0.22)",  # gris tenue — contexto de fondo
}
GROSOR_LINEA_EC = {"ROJA": 2.5, "NARANJA": 2.5, "AMARILLA": 2.0, "VERDE": 0.8}

# Límite superior del eje Y con margen visual
y_max_acwr = round(max(2.2, float(acwr_30d["acwr"].max()) * 1.15), 2)

# Promedio diario del equipo
prom_diario = acwr_30d.groupby("fecha")["acwr"].mean().reset_index()

# Tooltip: filtra jugadores sin alerta (prefijo "_") para no saturar el popup
_acwr_tooltip = JsCode("""
function(params) {
    var date = params[0].axisValueLabel;
    var html = '<b>' + date + '</b><br/>';
    params.forEach(function(p) {
        if (!p.seriesName.startsWith('_')) {
            html += p.marker + ' ' + p.seriesName +
                    ': <b>' + p.value[1].toFixed(2) + '</b><br/>';
        }
    });
    return html;
}
""")

_series_acwr = []
_nombres_con_alerta = []

# ── Zonas de fondo (markArea en serie vacía invisible) ──────────────────
# Cada zona corresponde a un rango clínico del ACWR (Gabbett 2016)
_series_acwr.append({
    "type": "line",
    "data": [],
    "silent": True,
    "legendHoverLink": False,
    "markArea": {
        "silent": True,
        "label": {
            "show": True,
            "position": "insideTopLeft",
            "fontSize": 10,
            "color": "#898781",
        },
        "data": [
            [{"yAxis": 0,   "name": "Desentren.",
              "itemStyle": {"color": "rgba(232,160,32,0.07)"}},  {"yAxis": 0.8}],
            [{"yAxis": 0.8, "name": "Óptima",
              "itemStyle": {"color": "rgba(26,158,92,0.07)"}},   {"yAxis": 1.3}],
            [{"yAxis": 1.3, "name": "Precaución",
              "itemStyle": {"color": "rgba(244,121,32,0.08)"}},  {"yAxis": 1.5}],
            [{"yAxis": 1.5, "name": "Alto riesgo",
              "itemStyle": {"color": "rgba(214,48,49,0.07)"}},   {"yAxis": y_max_acwr}],
        ],
    },
})

# ── Una línea por jugador ────────────────────────────────────────────────
# Jugadores sin alerta usan prefijo "_" → aparecen en chart pero no en leyenda ni tooltip
for jugador_id, grupo in acwr_30d.groupby("jugador_id"):
    alerta = alertas_dict.get(jugador_id, "VERDE")
    nombre = grupo["jugador"].iloc[0]
    nombre_serie = nombre if alerta != "VERDE" else f"_{nombre}"
    data_pts = [
        [r["fecha"].strftime("%Y-%m-%d"), round(float(r["acwr"]), 3)]
        for _, r in grupo.sort_values("fecha").iterrows()
    ]
    _series_acwr.append({
        "name": nombre_serie,
        "type": "line",
        "data": data_pts,
        "smooth": 0.3,
        "symbol": "none",
        "lineStyle": {"color": COLOR_LINEA_EC[alerta], "width": GROSOR_LINEA_EC[alerta]},
        "itemStyle": {"color": COLOR_LINEA_EC[alerta]},
        "emphasis": {"disabled": alerta == "VERDE"},
    })
    if alerta != "VERDE":
        _nombres_con_alerta.append(nombre)

# ── Promedio del equipo (línea oscura destacada + markLine de referencia) ──
_series_acwr.append({
    "name": "📊 Promedio equipo",
    "type": "line",
    "data": [
        [r["fecha"].strftime("%Y-%m-%d"), round(float(r["acwr"]), 3)]
        for _, r in prom_diario.sort_values("fecha").iterrows()
    ],
    "smooth": 0.3,
    "symbol": "none",
    "z": 10,
    "lineStyle": {"color": "#3D3D3D", "width": 3.5},
    "itemStyle": {"color": "#3D3D3D"},
    # Umbrales clínicos como líneas punteadas (Gabbett 2016)
    "markLine": {
        "symbol": ["none", "none"],
        "silent": True,
        "lineStyle": {"type": "dashed", "width": 1.5},
        "label": {"position": "insideEndTop", "fontSize": 10},
        "data": [
            {"yAxis": 0.8,
             "lineStyle": {"color": "#C85E10"},
             "label": {"formatter": "0.8 — Límite inferior", "color": "#C85E10"}},
            {"yAxis": 1.3,
             "lineStyle": {"color": "#F47920"},
             "label": {"formatter": "1.3 — Precaución", "color": "#F47920"}},
            {"yAxis": 1.5,
             "lineStyle": {"color": "#d63031"},
             "label": {"formatter": "1.5 — Alto riesgo", "color": "#d63031"}},
        ],
    },
})

option_acwr = {
    **_EP_ANIM,
    "tooltip": {
        **_EP_TOOLTIP,
        "trigger": "axis",
        "axisPointer": {
            "type": "cross",
            "crossStyle": {"color": "#555"},
            "label": {"backgroundColor": "#3D3D3D"},
        },
        "formatter": _acwr_tooltip,
    },
    "legend": {
        **_EP_LEGEND,
        "data": _nombres_con_alerta + ["📊 Promedio equipo"],
    },
    "grid": {"top": 40, "bottom": 80, "left": 60, "right": 24, "containLabel": False},
    "xAxis": {
        "type": "time",
        "axisLabel": {"formatter": "{MM}/{dd}", "fontSize": 12, "color": "#666666", "fontFamily": _EP_FONT},
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "splitLine": {"show": False},
    },
    "yAxis": {
        "type": "value",
        "name": "ACWR",
        "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
        "min": 0,
        "max": y_max_acwr,
        "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "splitLine": {"lineStyle": {"color": "#f0f0f0", "type": "solid", "width": 1}},
    },
    "series": _series_acwr,
}

st_echarts(options=option_acwr, height="430px")

st.divider()


# ============================================================
# SECCIÓN 4: TABLA ACWR DEL PLANTEL
# ============================================================

st.subheader("📈 ACWR del Plantel — Snapshot del día")

col_graf, col_tabla = st.columns([1, 2])

with col_graf:
    conteo_zonas = acwr_df["zona"].value_counts().reset_index()
    conteo_zonas.columns = ["zona", "cantidad"]

    etiquetas = {
        "alto_riesgo":      "🔴 Alto riesgo",
        "precaucion":       "🟠 Precaución",
        "optima":           "🟢 Óptima",
        "desentrenamiento": "🟡 Desentren.",
        "sin datos":        "⚪ Sin datos",
    }
    colores_zona = {
        "🔴 Alto riesgo":   "#FF4B4B",
        "🟠 Precaución":    "#FF8C00",
        "🟢 Óptima":        "#21C354",
        "🟡 Desentren.":    "#FFD700",
        "⚪ Sin datos":     "#CCCCCC",
    }
    conteo_zonas["zona_label"] = conteo_zonas["zona"].map(etiquetas)

    # Semáforo del plantel — donut con distribución por zona ACWR
    # El anillo resalta la proporción de jugadores en cada estado clínico
    _colores_donut = {
        "alto_riesgo":      "#d63031",   # rojo EQUIPOPHYSICAL
        "precaucion":       "#F47920",   # naranja EQUIPOPHYSICAL
        "optima":           "#1a9e5c",   # verde alertas
        "desentrenamiento": "#e8a020",   # ámbar (zona sub-óptima)
        "sin datos":        "#c3c2b7",   # gris neutro
    }
    _donut_data = [
        {
            "name": etiquetas.get(r["zona"], r["zona"]),
            "value": int(r["cantidad"]),
            "itemStyle": {"color": _colores_donut.get(r["zona"], "#999")},
        }
        for _, r in conteo_zonas.iterrows()
    ]
    option_dist = {
        **_EP_ANIM,
        "title": {
            "text": "Distribución por zona ACWR",
            "textStyle": {"fontSize": 15, "color": "#3D3D3D", "fontWeight": "600", "fontFamily": _EP_FONT},
            "top": 5,
            "left": "center",
        },
        "tooltip": {
            **_EP_TOOLTIP,
            "trigger": "item",
            "formatter": "{b}: {c} jugadores ({d}%)",
        },
        "legend": {**_EP_LEGEND},
        "series": [{
            "type": "pie",
            "radius": ["42%", "68%"],
            "center": ["50%", "45%"],
            "data": _donut_data,
            "label": {"show": True, "formatter": "{c}", "fontSize": 14, "fontWeight": "bold", "fontFamily": _EP_FONT},
            "labelLine": {"show": False},
            "emphasis": {"scale": True, "scaleSize": 8},
            "itemStyle": {
                "borderRadius": 4,
                "borderColor": "#fff",
                "borderWidth": 2,
                "shadowBlur": 4,
                "shadowColor": "rgba(0,0,0,0.08)",
            },
        }],
    }
    st_echarts(options=option_dist, height="280px")

    st.markdown("""
    **Zonas ACWR:**
    - 🟡 `< 0.8` → Desentrenamiento
    - 🟢 `0.8 – 1.3` → Zona óptima
    - 🟠 `1.3 – 1.5` → Precaución
    - 🔴 `> 1.5` → Alto riesgo
    """)

with col_tabla:
    zona_labels = {
        "optima":           "✅ Óptima",
        "precaucion":       "⚠️ Precaución",
        "alto_riesgo":      "🚨 Alto riesgo",
        "desentrenamiento": "⬇️ Desentren.",
        "sin datos":        "—",
    }
    tabla_acwr = acwr_df[["numero", "jugador", "posicion",
                           "ewma_aguda", "ewma_cronica", "acwr", "zona"]].copy()
    tabla_acwr["zona"] = tabla_acwr["zona"].map(zona_labels).fillna("—")
    tabla_acwr = tabla_acwr.rename(columns={
        "numero":       "#",
        "jugador":      "Jugador",
        "posicion":     "Posición",
        "ewma_aguda":   "EWMA 7d",
        "ewma_cronica": "EWMA 28d",
        "acwr":         "ACWR",
        "zona":         "Zona",
    })

    styled_acwr = (
        tabla_acwr.style
        .map(_color_acwr_celda, subset=["ACWR"])
        .format({"ACWR": "{:.2f}", "EWMA 7d": "{:.0f}", "EWMA 28d": "{:.0f}"}, na_rep="—")
        .hide(axis="index")
    )
    st.dataframe(styled_acwr, width='stretch', height=420)

st.divider()


# ============================================================
# SECCIÓN 5: WELLNESS DEL EQUIPO — ÚLTIMOS 14 DÍAS
# ============================================================

st.subheader("💚 Wellness Promedio del Equipo — Últimos 14 días")

wellness_hist = obtener_wellness_historico()
fecha_max_w   = wellness_hist["fecha"].max()
wellness_14d  = wellness_hist[wellness_hist["fecha"] >= fecha_max_w - timedelta(days=13)].copy()

# Promedio diario del equipo
wellness_diario = (
    wellness_14d.groupby("fecha")["wellness_total"]
    .mean()
    .reset_index()
    .rename(columns={"wellness_total": "promedio"})
)

# Clasificar cada día según el nivel de bienestar
def _nivel_wellness(val):
    if val >= 3.5:
        return "Bueno  (≥3.5)"
    elif val >= 2.8:
        return "Regular  (2.8–3.5)"
    else:
        return "Bajo  (<2.8)"

wellness_diario["estado"] = wellness_diario["promedio"].apply(_nivel_wellness)

col_bien, col_det = st.columns([2, 1])

with col_bien:
    _GRAD_W = {
        "Bueno  (≥3.5)":      _ep_gradient("#1a9e5c", "rgba(26,158,92,0.40)"),
        "Regular  (2.8–3.5)": _ep_gradient("#F47920", "rgba(244,121,32,0.40)"),
        "Bajo  (<2.8)":       _ep_gradient("#d63031", "rgba(214,48,49,0.40)"),
    }
    _fechas_w = [r["fecha"].strftime("%d/%m") for _, r in wellness_diario.iterrows()]
    _barras_w = [
        {
            "value": round(float(r["promedio"]), 2),
            "itemStyle": {
                "color": _GRAD_W.get(r["estado"], _ep_gradient("#999999", "rgba(153,153,153,0.4)")),
                "borderRadius": [4, 4, 0, 0],
                "shadowBlur": 4,
                "shadowColor": "rgba(0,0,0,0.08)",
            },
        }
        for _, r in wellness_diario.iterrows()
    ]

    option_wellness = {
        **_EP_ANIM,
        "animationEasing": "elasticOut",
        "tooltip": {
            **_EP_TOOLTIP,
            "trigger": "axis",
            "formatter": JsCode("""
function(params) {
    var p = params[0];
    var estado = p.value >= 3.5 ? '✅ Bueno'
               : p.value >= 2.8 ? '⚠️ Regular'
               : '🔴 Bajo';
    return '<b>' + p.name + '</b><br/>' +
           'Wellness: <b>' + p.value.toFixed(2) + '</b><br/>' + estado;
}
"""),
        },
        "grid": {"top": 40, "bottom": 60, "left": 60, "right": 24},
        "xAxis": {
            "type": "category",
            "data": _fechas_w,
            "axisLabel": {"fontSize": 12, "color": "#666666", "rotate": 30, "fontFamily": _EP_FONT},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "name": "Wellness (1–5)",
            "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
            "min": 0,
            "max": 5.5,
            "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f0f0f0", "type": "solid", "width": 1}},
        },
        "series": [{
            "type": "bar",
            "data": _barras_w,
            "barMaxWidth": 42,
            "label": {
                "show": True,
                "position": "top",
                "formatter": JsCode("function(p){ return p.value.toFixed(2); }"),
                "fontSize": 11,
                "color": "#3D3D3D",
                "fontWeight": "bold",
                "fontFamily": _EP_FONT,
            },
            "markLine": {
                "symbol": ["none", "none"],
                "silent": True,
                "data": [
                    {
                        "yAxis": 3.5,
                        "lineStyle": {"type": "dashed", "color": "#1a9e5c", "width": 1.5},
                        "label": {"formatter": "3.5 — Óptimo", "color": "#1a9e5c", "position": "insideEndTop", "fontSize": 10},
                    },
                    {
                        "yAxis": 2.8,
                        "lineStyle": {"type": "dashed", "color": "#d63031", "width": 1.5},
                        "label": {"formatter": "2.8 — Umbral bajo", "color": "#d63031", "position": "insideEndTop", "fontSize": 10},
                    },
                ],
            },
        }],
    }

    st_echarts(options=option_wellness, height="360px")

with col_det:
    # Desglose por ítem de wellness (promedio de los últimos 14 días)
    items_wellness = ["fatiga", "calidad_sueno", "horas_sueno",
                      "dolor_muscular", "humor", "estres"]
    etiquetas_items = {
        "fatiga":         "😴 Fatiga",
        "calidad_sueno":  "🌙 Calidad sueño",
        "horas_sueno":    "⏰ Horas sueño",
        "dolor_muscular": "💪 Dolor muscular",
        "humor":          "😊 Humor",
        "estres":         "🧠 Estrés",
    }

    promedios_items = (
        wellness_14d[items_wellness].mean()
        .reset_index()
        .rename(columns={"index": "item", 0: "promedio"})
    )
    promedios_items.columns = ["item", "promedio"]
    promedios_items["Ítem"] = promedios_items["item"].map(etiquetas_items)
    promedios_items["Promedio"] = promedios_items["promedio"].round(2)

    # Nota: fatiga, dolor, estrés → más alto = peor
    promedios_items["Referencia"] = promedios_items["item"].apply(
        lambda x: "⚠️ más alto = peor" if x in ["fatiga", "dolor_muscular", "estres"] else "✅ más alto = mejor"
    )

    st.markdown("**Promedios por ítem (14d):**")
    st.dataframe(
        promedios_items[["Ítem", "Promedio", "Referencia"]],
        hide_index=True,
        width='stretch',
        height=280,
    )

    # Resumen del día más reciente
    wellness_hoy_prom = wellness_diario["promedio"].iloc[-1]
    estado_hoy = _nivel_wellness(wellness_hoy_prom)
    color_hoy = "#21C354" if "Bueno" in estado_hoy else ("#FF8C00" if "Regular" in estado_hoy else "#FF4B4B")
    st.markdown(
        f"<div style='background:{color_hoy}22; border-left:4px solid {color_hoy}; "
        f"padding:10px; border-radius:4px; margin-top:8px'>"
        f"<b>Hoy: {wellness_hoy_prom:.2f}</b> — {estado_hoy}</div>",
        unsafe_allow_html=True,
    )

st.divider()


# ============================================================
# SECCIÓN 6: JUGADORES NO DISPONIBLES (LESIONADOS)
# ============================================================

st.subheader("🚑 Jugadores No Disponibles")

if lesionados.empty:
    st.success("✅ No hay jugadores lesionados. Plantel completo disponible.")
else:
    hoy = pd.Timestamp(date.today())

    # Mostrar tarjetas en grilla de 3 columnas
    n_cols   = 3
    filas    = [lesionados.iloc[i:i+n_cols] for i in range(0, len(lesionados), n_cols)]

    for fila_df in filas:
        cols = st.columns(n_cols)
        for idx, (_, jug) in enumerate(fila_df.iterrows()):

            fecha_ini      = pd.Timestamp(jug.get("fecha_inicio", hoy))
            dias_baja      = int(jug.get("dias_baja", 0) or 0)
            dias_lesionado = max(0, (hoy - fecha_ini).days)
            dias_restantes = max(0, dias_baja - dias_lesionado)
            pct_recuper    = min(1.0, dias_lesionado / dias_baja) if dias_baja > 0 else 1.0

            # Color de la tarjeta según días restantes
            if dias_restantes == 0:
                borde_color = "#21C354"   # listo para volver
                estado_txt  = "Alta próxima"
            elif dias_restantes <= 7:
                borde_color = "#FF8C00"   # regresa pronto
                estado_txt  = f"Regresa en {dias_restantes}d"
            else:
                borde_color = "#FF4B4B"   # fuera por más tiempo
                estado_txt  = f"Regresa en {dias_restantes}d"

            with cols[idx]:
                with st.container(border=True):
                    # Nombre y posición
                    st.markdown(
                        f"<b style='font-size:1.05rem'>#{jug.get('numero','—')} "
                        f"{jug['jugador']}</b>",
                        unsafe_allow_html=True,
                    )
                    st.caption(jug.get("posicion", "").capitalize())

                    st.markdown(
                        f"🏥 **{str(jug.get('tipo_lesion','')).capitalize()}** "
                        f"— {jug.get('zona_corporal','')}"
                    )
                    st.markdown(f"📅 Inicio: `{fecha_ini.strftime('%d/%m/%Y')}`")

                    # Métricas de tiempo
                    m1, m2 = st.columns(2)
                    m1.metric("Días lesionado", dias_lesionado)
                    m2.metric("Días restantes", dias_restantes)

                    # Barra de progreso de recuperación
                    st.progress(
                        pct_recuper,
                        text=f"Recuperación: {int(pct_recuper * 100)}%",
                    )

                    # Estado final
                    st.markdown(
                        f"<div style='background:{borde_color}22; border-left:3px solid "
                        f"{borde_color}; padding:5px 8px; border-radius:3px; "
                        f"font-size:0.85rem; margin-top:4px'>{estado_txt}</div>",
                        unsafe_allow_html=True,
                    )

    # Resumen por tipo y zona corporal (si hay más de un lesionado)
    if len(lesionados) > 1:
        st.markdown(" ")
        col_a, col_b = st.columns(2)
        with col_a:
            resumen_tipo = (
                lesionados.groupby("tipo_lesion").size()
                .reset_index(name="Cantidad")
                .rename(columns={"tipo_lesion": "Tipo de lesión"})
            )
            st.markdown("**Por tipo de lesión:**")
            st.dataframe(resumen_tipo, hide_index=True, width='stretch')
        with col_b:
            resumen_zona = (
                lesionados.groupby("zona_corporal").size()
                .reset_index(name="Cantidad")
                .rename(columns={"zona_corporal": "Zona corporal"})
            )
            st.markdown("**Por zona corporal:**")
            st.dataframe(resumen_zona, hide_index=True, width='stretch')


# ============================================================
# SECCIÓN 7: ESTADO RTP DEL PLANTEL
# ============================================================

st.divider()
st.subheader("🏥 Estado Return to Play (RTP)")

rtp_df = obtener_estado_rtp()

if rtp_df.empty:
    st.info(
        "Sin jugadores en proceso de RTP. "
        "Los fisios registran las sesiones desde el módulo **RTP** en el menú lateral."
    )
else:
    # Métricas resumen RTP
    n_en_rtp   = len(rtp_df)
    n_avanzados = int((rtp_df["etapa_orden"] >= 5).sum())   # etapas 5 y 6 → cerca de volver
    eva_prom   = rtp_df["eva_ultimo"].mean()
    conf_prom  = rtp_df["confianza_ultimo"].mean()

    cr1, cr2, cr3, cr4 = st.columns(4)
    cr1.metric("🔄 Jugadores en RTP",        n_en_rtp)
    cr2.metric("🔜 Cerca de volver (E5-E6)", n_avanzados)
    cr3.metric("📊 EVA promedio plantel",
               f"{eva_prom:.1f}" if not pd.isna(eva_prom) else "—",
               help="Promedio de dolor (0-10) en última sesión. Menor es mejor.")
    cr4.metric("💪 Confianza promedio",
               f"{conf_prom:.1f}" if not pd.isna(conf_prom) else "—",
               help="Promedio de confianza en zona lesionada (0-10). Mayor es mejor.")

    st.markdown(" ")

    # Tarjetas por jugador en RTP
    n_cols  = 3
    filas_rtp = [rtp_df.iloc[i:i+n_cols] for i in range(0, len(rtp_df), n_cols)]

    COLORES_ETAPA = {
        1: "#888888",   # gris — reposo
        2: "#4A90D9",   # azul — movilidad
        3: "#F5A623",   # naranja — aeróbico
        4: "#F5A623",   # naranja — cambios dirección
        5: "#7ED321",   # verde claro — específico
        6: "#21C354",   # verde — listo
    }

    for fila_rtp in filas_rtp:
        cols_rtp = st.columns(n_cols)
        for idx, (_, jug_rtp) in enumerate(fila_rtp.iterrows()):

            color_etapa = COLORES_ETAPA.get(jug_rtp["etapa_orden"], "#888")
            pct         = jug_rtp["pct_avance"]

            # Color EVA: verde si bajo, rojo si alto
            eva_v  = jug_rtp["eva_ultimo"]
            conf_v = jug_rtp["confianza_ultimo"]
            color_eva  = "#21C354" if (not pd.isna(eva_v)  and eva_v  <= 3) else "#FF4B4B"
            color_conf = "#21C354" if (not pd.isna(conf_v) and conf_v >= 7) else "#FF8C00"

            with cols_rtp[idx]:
                with st.container(border=True):
                    # Nombre y posición
                    st.markdown(
                        f"<b style='font-size:1.05rem'>#{jug_rtp['numero']} "
                        f"{jug_rtp['jugador']}</b>",
                        unsafe_allow_html=True,
                    )
                    st.caption(jug_rtp["posicion"].capitalize())

                    # Etapa actual con color
                    st.markdown(
                        f"<div style='background:{color_etapa}22; border-left:3px solid "
                        f"{color_etapa}; padding:4px 8px; border-radius:3px; "
                        f"font-size:0.85rem; margin:4px 0'>"
                        f"<b>E{jug_rtp['etapa_orden']} — {jug_rtp['etapa_nombre']}</b>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # Barra de progreso del protocolo
                    st.progress(pct / 100, text=f"Protocolo: {pct}%")

                    # EVA y Confianza de la última sesión
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Días RTP", jug_rtp["dias_rtp"])

                    eva_txt  = f"{eva_v:.1f}"  if not pd.isna(eva_v)  else "—"
                    conf_txt = f"{conf_v:.1f}" if not pd.isna(conf_v) else "—"

                    mc2.metric("EVA", eva_txt)
                    mc3.metric("Conf.", conf_txt)

                    # Última sesión y estado de avance
                    estado_rtp = "✅ Aprobó avance" if jug_rtp["avanza"] else "🔄 Continúa etapa"
                    st.markdown(
                        f"<div style='font-size:0.8rem; color:gray; margin-top:4px'>"
                        f"Última sesión: {jug_rtp['ultima_sesion']} · {estado_rtp}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


# ============================================================
# PIE DE PÁGINA
# ============================================================

st.divider()
st.caption(
    f"⚽ Sistema de Monitoreo de Rendimiento · EQUIPOPHYSICAL · "
    f"Datos al {r['fecha']} · "
    f"ACWR por método EWMA (aguda 7d / crónica 28d)"
)
