"""
app.py
======
Dashboard operativo diario para reunión de staff.

Cómo ejecutar:
  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from metricas import (
    reporte_disponibilidad,
    resumen_acwr_plantel,
    cargar_lesiones_activas,
    calcular_acwr_ewma,
    cargar_wellness,
)


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

# Colores y grosores por nivel de alerta
COLOR_LINEA = {
    "ROJA":     "#FF4B4B",
    "NARANJA":  "#FF8C00",
    "AMARILLA": "#D4A800",
    "VERDE":    "#CCCCCC",
}
GROSOR_LINEA = {"ROJA": 2.5, "NARANJA": 2.5, "AMARILLA": 2.0, "VERDE": 0.8}
OPACIDAD     = {"ROJA": 1.0, "NARANJA": 1.0, "AMARILLA": 0.9, "VERDE": 0.30}

fig_evol = go.Figure()

# Zonas de fondo coloreadas (de abajo hacia arriba)
y_max_acwr = max(2.2, float(acwr_30d["acwr"].max()) * 1.15)
fig_evol.add_hrect(y0=0,    y1=0.8,       fillcolor="#FFD700", opacity=0.07, line_width=0,
                   annotation_text="Desentren.", annotation_position="top left",
                   annotation_font=dict(size=10, color="#999"))
fig_evol.add_hrect(y0=0.8,  y1=1.3,       fillcolor="#21C354", opacity=0.07, line_width=0,
                   annotation_text="Óptima", annotation_position="top left",
                   annotation_font=dict(size=10, color="#999"))
fig_evol.add_hrect(y0=1.3,  y1=1.5,       fillcolor="#FF8C00", opacity=0.09, line_width=0,
                   annotation_text="Precaución", annotation_position="top left",
                   annotation_font=dict(size=10, color="#999"))
fig_evol.add_hrect(y0=1.5,  y1=y_max_acwr, fillcolor="#FF4B4B", opacity=0.07, line_width=0,
                   annotation_text="Alto riesgo", annotation_position="top left",
                   annotation_font=dict(size=10, color="#999"))

# Líneas individuales por jugador
for jugador_id, grupo in acwr_30d.groupby("jugador_id"):
    alerta  = alertas_dict.get(jugador_id, "VERDE")
    nombre  = grupo["jugador"].iloc[0]
    visible = True if alerta != "VERDE" else "legendonly"

    fig_evol.add_trace(go.Scatter(
        x=grupo["fecha"],
        y=grupo["acwr"],
        mode="lines",
        name=nombre,
        line=dict(color=COLOR_LINEA[alerta], width=GROSOR_LINEA[alerta]),
        opacity=OPACIDAD[alerta],
        showlegend=(alerta != "VERDE"),
        hovertemplate=f"<b>{nombre}</b><br>ACWR: %{{y:.2f}}<br>%{{x|%d/%m/%Y}}<extra></extra>",
    ))

# Promedio del equipo (línea negra gruesa)
prom_diario = acwr_30d.groupby("fecha")["acwr"].mean().reset_index()
fig_evol.add_trace(go.Scatter(
    x=prom_diario["fecha"],
    y=prom_diario["acwr"],
    mode="lines",
    name="📊 Promedio equipo",
    line=dict(color="#1a1a2e", width=3.5),
    hovertemplate="<b>Promedio equipo</b><br>ACWR: %{y:.2f}<br>%{x|%d/%m/%Y}<extra></extra>",
))

# Líneas de referencia punteadas
for y_val, label, color in [
    (0.8, "0.8 — Límite inferior", "#B8860B"),
    (1.3, "1.3 — Zona precaución", "#FF6600"),
    (1.5, "1.5 — Alto riesgo",     "#CC0000"),
]:
    fig_evol.add_hline(
        y=y_val, line_dash="dot", line_color=color, line_width=1.5,
        annotation_text=label, annotation_position="right",
        annotation_font=dict(size=11, color=color),
    )

fig_evol.update_layout(
    xaxis_title="",
    yaxis_title="ACWR",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    height=430,
    hovermode="x unified",
    yaxis=dict(range=[0, y_max_acwr]),
    xaxis=dict(tickformat="%d/%m"),
    legend=dict(
        title="Jugadores con alerta",
        orientation="v", x=1.01, y=1,
        font=dict(size=11),
    ),
    margin=dict(t=30, b=20, l=50, r=180),
)

st.plotly_chart(fig_evol, width='stretch')

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

    fig_dist = px.bar(
        conteo_zonas, x="zona_label", y="cantidad",
        color="zona_label", color_discrete_map=colores_zona,
        text="cantidad", title="Distribución por zona ACWR",
    )
    fig_dist.update_layout(
        showlegend=False, xaxis_title="", yaxis_title="Jugadores",
        plot_bgcolor="rgba(0,0,0,0)", height=280,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    fig_dist.update_traces(textposition="outside")
    st.plotly_chart(fig_dist, width='stretch')

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
    fig_wellness = px.bar(
        wellness_diario,
        x="fecha", y="promedio",
        color="estado",
        color_discrete_map={
            "Bueno  (≥3.5)":      "#21C354",
            "Regular  (2.8–3.5)": "#FF8C00",
            "Bajo  (<2.8)":       "#FF4B4B",
        },
        text=wellness_diario["promedio"].apply(lambda x: f"{x:.2f}"),
        title="Wellness diario del equipo",
        labels={"fecha": "", "promedio": "Wellness (1–5)", "estado": "Estado"},
    )
    fig_wellness.add_hline(
        y=3.5, line_dash="dash", line_color="#21C354", line_width=1.5,
        annotation_text="3.5 — Umbral óptimo",
        annotation_position="right",
        annotation_font=dict(size=11, color="#21C354"),
    )
    fig_wellness.add_hline(
        y=2.8, line_dash="dash", line_color="#FF4B4B", line_width=1.5,
        annotation_text="2.8 — Umbral bajo",
        annotation_position="right",
        annotation_font=dict(size=11, color="#FF4B4B"),
    )
    fig_wellness.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=360,
        yaxis=dict(range=[0, 5.5]),
        xaxis=dict(tickformat="%d/%m"),
        legend=dict(orientation="h", y=-0.25, title=""),
        margin=dict(t=40, b=20, l=50, r=120),
    )
    fig_wellness.update_traces(textposition="outside")
    st.plotly_chart(fig_wellness, width='stretch')

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
# PIE DE PÁGINA
# ============================================================

st.divider()
st.caption(
    f"⚽ Sistema de Monitoreo de Rendimiento · EQUIPOPHYSICAL · "
    f"Datos al {r['fecha']} · "
    f"ACWR por método EWMA (aguda 7d / crónica 28d)"
)
