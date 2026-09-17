"""
pages/Epidemiologia.py
======================
Panel de epidemiología de lesiones del plantel.

Estándar: IOC Consensus Statement on Injury Surveillance
(Fuller et al., 2006) — adoptado por UEFA y FIFA.

Métricas bajo este estándar:
  - Incidencia  = (N lesiones / Horas-atleta de exposición) × 1000
  - Severidad   = días de baja promedio por lesión
  - Carga lesional = incidencia × severidad  (días perdidos / 1000 HA)
  - Horas-atleta (HA) = suma de minutos individuales de todos los jugadores / 60
"""

import streamlit as st
import pandas as pd
from streamlit_echarts import st_echarts, JsCode
import sqlite3
import sys
import os

# Permite importar auth.py y styles.py, que están un directorio arriba (raíz del proyecto)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
from styles import apply_styles

# ── Tema visual EQUIPOPHYSICAL ─────────────────────────────────
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
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Epidemiología",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_styles()

auth.exigir_acceso("Epidemiologia")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONEXIÓN A BASE DE DATOS
# El archivo está en el directorio padre de pages/
# ============================================================

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "futbol_monitoreo.db"
)

def _conectar():
    return sqlite3.connect(DB_PATH)


# ============================================================
# CARGA DE DATOS
# ============================================================

@st.cache_data(ttl=300)
def cargar_todas_lesiones():
    """
    Carga TODAS las lesiones (activas y recuperadas).
    Enriquece con el tipo de sesión del día de la lesión
    para distinguir contexto entrenamiento vs partido.
    """
    conn = _conectar()

    lesiones = pd.read_sql("""
        SELECT
            l.id,
            l.jugador_id,
            TRIM(j.nombre || ' ' || j.apellido)  AS jugador,
            j.posicion,
            j.numero_camiseta               AS numero,
            l.fecha_inicio,
            l.fecha_fin,
            l.tipo_lesion,
            l.zona_corporal,
            l.dias_baja,
            l.activo
        FROM lesiones l
        JOIN jugadores j ON j.id = l.jugador_id
        ORDER BY l.fecha_inicio
    """, conn, parse_dates=["fecha_inicio", "fecha_fin"])

    # Buscar el tipo de sesión del día en que ocurrió cada lesión
    sesiones = pd.read_sql("""
        SELECT jugador_id, fecha, tipo_sesion
        FROM carga_interna
        WHERE tipo_sesion IS NOT NULL
    """, conn)

    conn.close()

    # Convertir fecha a string para el merge
    lesiones["fecha_str"] = lesiones["fecha_inicio"].dt.strftime("%Y-%m-%d")
    sesiones["fecha_str"] = sesiones["fecha"].astype(str)

    lesiones = lesiones.merge(
        sesiones[["jugador_id", "fecha_str", "tipo_sesion"]],
        on=["jugador_id", "fecha_str"],
        how="left",
    )

    # Contexto: Partido vs Entrenamiento
    lesiones["contexto"] = lesiones["tipo_sesion"].apply(
        lambda x: "Partido" if x == "partido" else "Entrenamiento"
    )

    return lesiones


@st.cache_data(ttl=300)
def cargar_exposicion():
    """
    Calcula las horas-atleta (HA) de exposición totales y por contexto.
    Estándar IOC/UEFA/FIFA: suma de todos los minutos individuales / 60.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            tipo_sesion,
            SUM(minutos) AS total_minutos
        FROM carga_interna
        WHERE minutos IS NOT NULL
        GROUP BY tipo_sesion
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def cargar_decisiones_rtp():
    """
    Última decisión RTP registrada por lesión (APTO / APTO_CONDICIONADO /
    NO_APTO). Si una lesión todavía no tiene evaluaciones cargadas por el
    fisio, simplemente no aparece acá (se completa como "Sin evaluar").
    """
    conn = _conectar()
    try:
        df = pd.read_sql("""
            SELECT lesion_id, decision, fecha
            FROM rtp_evaluaciones
            ORDER BY fecha
        """, conn)
    except Exception:
        df = pd.DataFrame(columns=["lesion_id", "decision", "fecha"])
    conn.close()

    if df.empty:
        return df
    return df.sort_values("fecha").groupby("lesion_id").last().reset_index()


# ============================================================
# CÁLCULO DE MÉTRICAS EPIDEMIOLÓGICAS (IOC STANDARD)
# ============================================================

def calcular_metricas(lesiones_df, exposicion_df):
    """
    Calcula todas las métricas bajo el estándar IOC Consensus Statement.

    Fórmulas:
      Incidencia  = (N / HA) × 1000
      Severidad   = mean(dias_baja)
      Carga lesional = incidencia × severidad
      Tasa re-lesión = lesiones recurrentes / total × 100
    """
    # ── Exposición ────────────────────────────────────────────
    ha_total      = exposicion_df["total_minutos"].sum() / 60
    ha_partido    = exposicion_df.loc[
        exposicion_df["tipo_sesion"] == "partido", "total_minutos"
    ].sum() / 60
    ha_entreno    = ha_total - ha_partido

    # ── Lesiones ──────────────────────────────────────────────
    n_total       = len(lesiones_df)
    n_partido     = (lesiones_df["contexto"] == "Partido").sum()
    n_entreno     = n_total - n_partido

    dias_baja_total = lesiones_df["dias_baja"].sum()
    severidad_media = lesiones_df["dias_baja"].mean()

    # ── Incidencia por 1000 HA ────────────────────────────────
    inc_total   = (n_total   / ha_total)   * 1000 if ha_total   > 0 else 0
    inc_partido = (n_partido / ha_partido) * 1000 if ha_partido > 0 else 0
    inc_entreno = (n_entreno / ha_entreno) * 1000 if ha_entreno > 0 else 0

    # ── Carga lesional (injury burden) ────────────────────────
    # = días de baja por 1000 HA de exposición
    carga_lesional = (dias_baja_total / ha_total) * 1000 if ha_total > 0 else 0

    # ── Tasa de re-lesión ─────────────────────────────────────
    # Definición: mismo jugador, misma zona corporal, ≥2 lesiones
    recurrencias = (
        lesiones_df.groupby(["jugador_id", "zona_corporal"])
        .size()
        .reset_index(name="n")
    )
    n_relesiones = int(recurrencias[recurrencias["n"] > 1]["n"].sub(1).sum())
    tasa_relesion = (n_relesiones / n_total * 100) if n_total > 0 else 0

    return {
        "n_total":         n_total,
        "n_partido":       int(n_partido),
        "n_entreno":       int(n_entreno),
        "ha_total":        round(ha_total, 1),
        "ha_partido":      round(ha_partido, 1),
        "ha_entreno":      round(ha_entreno, 1),
        "dias_baja_total": int(dias_baja_total),
        "severidad_media": round(severidad_media, 1),
        "inc_total":       round(inc_total, 2),
        "inc_partido":     round(inc_partido, 2),
        "inc_entreno":     round(inc_entreno, 2),
        "carga_lesional":  round(carga_lesional, 1),
        "tasa_relesion":   round(tasa_relesion, 1),
        "n_relesiones":    n_relesiones,
    }


def calcular_disponibilidad():
    """
    Disponibilidad = jugadores SIN lesión activa hoy / total del plantel × 100.

    Nota: la columna que marca una lesión en curso en la tabla
    `lesiones` se llama `activo` (1 = en curso, 0 = recuperado) — no
    `en_curso`. Ya filtra por `activo = 1`, así que un jugador
    recuperado (`activo = 0`) correctamente NO cuenta como lesionado.
    """
    conn = _conectar()
    total = pd.read_sql("SELECT COUNT(*) AS n FROM jugadores", conn)["n"].iloc[0]
    lesionados = pd.read_sql(
        "SELECT COUNT(DISTINCT jugador_id) AS n FROM lesiones WHERE activo = 1", conn
    )["n"].iloc[0]
    conn.close()

    total = int(total)
    lesionados = int(lesionados)
    disponibles = total - lesionados
    pct = round(disponibles / total * 100, 1) if total > 0 else 0
    return {"total": total, "disponibles": disponibles, "lesionados": lesionados, "pct": pct}


def calcular_disponibilidad_historica(lesiones_df, dias=30):
    """
    Reconstruye la disponibilidad día por día de los últimos `dias` días
    a partir de los rangos de fecha de las lesiones que ya están en la
    base (fecha_inicio → fecha_fin, o hasta hoy si la lesión sigue en
    curso). No hace falta simular una tabla aparte: la variación diaria
    sale sola de las lesiones ya cargadas, que tienen fechas de inicio
    repartidas en los últimos 90 días.
    """
    conn = _conectar()
    total = int(pd.read_sql("SELECT COUNT(*) AS n FROM jugadores", conn)["n"].iloc[0])
    conn.close()

    hoy = pd.Timestamp.today().normalize()
    fechas = [hoy - pd.Timedelta(days=i) for i in range(dias - 1, -1, -1)]

    # Fin efectivo de cada lesión: la fecha de alta real, o "hoy" si sigue en curso
    fin_efectivo = lesiones_df["fecha_fin"].fillna(hoy)

    filas = []
    for fecha in fechas:
        en_curso_ese_dia = lesiones_df[
            (lesiones_df["fecha_inicio"] <= fecha) & (fin_efectivo >= fecha)
        ]["jugador_id"].nunique()
        disponibles = total - en_curso_ese_dia
        pct = round(disponibles / total * 100, 1) if total > 0 else 0
        filas.append({"fecha": fecha, "pct": pct, "lesionados": int(en_curso_ese_dia)})

    return pd.DataFrame(filas)


def calcular_tendencia_carga_lesional(lesiones_df):
    """
    Compara la carga lesional (días de baja / 1000 HA) de los últimos
    30 días contra los 30 días anteriores, para saber si la tendencia
    es a la suba o a la baja.
    """
    conn = _conectar()
    hoy = pd.Timestamp.today().normalize()
    ventanas = {
        "actual": (hoy - pd.Timedelta(days=29), hoy),
        "previa": (hoy - pd.Timedelta(days=59), hoy - pd.Timedelta(days=30)),
    }

    valores = {}
    for clave, (desde, hasta) in ventanas.items():
        ha_df = pd.read_sql(
            "SELECT SUM(minutos) AS total FROM carga_interna WHERE fecha BETWEEN ? AND ?",
            conn, params=[str(desde.date()), str(hasta.date())],
        )
        ha = (ha_df["total"].iloc[0] or 0) / 60

        dias_baja = lesiones_df[
            (lesiones_df["fecha_inicio"] >= desde) & (lesiones_df["fecha_inicio"] <= hasta)
        ]["dias_baja"].sum()

        valores[clave] = (dias_baja / ha * 1000) if ha > 0 else 0

    conn.close()
    delta = round(valores["actual"] - valores["previa"], 1)
    return delta


def _nivel_incidencia(inc_total):
    """
    Semáforo de incidencia total: verde <3, naranja 3-6, rojo >6
    (lesiones / 1000 horas-atleta).
    """
    if inc_total < 3:
        return "CONTROLADA", "#1a9e5c"
    elif inc_total <= 6:
        return "MODERADA", "#F47920"
    else:
        return "CRÍTICA", "#d63031"


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Epidemiología")
    if st.button("Actualizar datos", width='stretch'):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption(
        "Estándar: IOC Consensus Statement\n"
        "Fuller et al., 2006\n"
        "Adoptado por UEFA y FIFA"
    )
    st.divider()
    st.caption("Sistema de Monitoreo de Rendimiento\nEQUIPOPHYSICAL")


# ============================================================
# CARGA INICIAL
# ============================================================

lesiones_df   = cargar_todas_lesiones()
exposicion_df = cargar_exposicion()
m             = calcular_metricas(lesiones_df, exposicion_df)
disp          = calcular_disponibilidad()
delta_carga   = calcular_tendencia_carga_lesional(lesiones_df)
disp_hist_df  = calcular_disponibilidad_historica(lesiones_df, dias=30)


# ============================================================
# HEADER
# ============================================================

st.title("Epidemiología de Lesiones")
st.caption(
    "Estándar IOC Consensus Statement · Fuller et al., 2006 · "
    "Métricas por 1000 horas-atleta (HA) de exposición"
)
st.divider()


# ============================================================
# SECCIÓN 1: MÉTRICAS — 3 NIVELES DE JERARQUÍA
# Nivel 1: KPIs críticos (grandes) · Nivel 2: contexto (medianos)
# Nivel 3: detalle técnico (colapsado, para el staff que lo necesita)
# ============================================================

st.markdown('<div class="ep-badge ep-badge-medico">Medico</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title">Indicadores Epidemiológicos Principales</div>', unsafe_allow_html=True)

# ── HERO: Disponibilidad — el KPI protagonista de la página ─
# Va arriba de todo, antes incluso del semáforo de situación
# general, porque es el número que más le importa al staff técnico
# de un vistazo: "¿con cuántos jugadores contamos hoy?"
st.markdown(f"""
<div class="ep-card" style="text-align:center; padding:28px 24px;">
    <div style="color:#8b92a8; font-size:0.85rem; text-transform:uppercase; letter-spacing:1.5px;">
        Disponibilidad del plantel
    </div>
    <div style="color:#F47920; font-size:3.4rem; font-weight:700; margin:8px 0 2px 0;">
        {disp['pct']}%
    </div>
    <div style="color:#8b92a8; font-size:0.95rem;">
        {disp['disponibles']} de {disp['total']} jugadores disponibles
    </div>
</div>
""", unsafe_allow_html=True)

col_gauge, col_hist = st.columns([1, 1.6])

with col_gauge:
    # Gauge semicircular: aguja principal (valor actual) + aguja fina
    # estática en 90% que marca el objetivo del plantel.
    option_disp_gauge = {
        **_EP_ANIM,
        "series": [
            {
                "type": "gauge",
                "startAngle": 180, "endAngle": 0,
                "min": 0, "max": 100,
                "radius": "95%",
                "center": ["50%", "75%"],
                "progress": {"show": False},
                "axisLine": {
                    "lineStyle": {
                        "width": 16,
                        "color": [
                            [0.75, "#d63031"],   # rojo    0-75 %
                            [0.90, "#F47920"],   # naranja 75-90 %
                            [1.00, "#1a9e5c"],   # verde   90-100 %
                        ],
                    },
                },
                "pointer": {"itemStyle": {"color": "#f0f2f6"}, "width": 5, "length": "55%"},
                "anchor": {"show": True, "size": 10, "itemStyle": {"color": "#f0f2f6"}},
                "axisTick": {"distance": -16, "length": 4, "lineStyle": {"color": "#161824", "width": 1}},
                "splitLine": {"distance": -16, "length": 14, "lineStyle": {"color": "#161824", "width": 2}},
                "axisLabel": {
                    "distance": 20, "fontSize": 10, "color": "#8b92a8", "fontFamily": _EP_FONT,
                    "formatter": "{value}",
                },
                "title": {"show": False},
                "detail": {"show": False},
                "data": [{"value": disp["pct"]}],
            },
            {
                # Marca de objetivo (90 %): aguja fina y estática, sin anillo propio
                "type": "gauge",
                "startAngle": 180, "endAngle": 0,
                "min": 0, "max": 100,
                "radius": "95%",
                "center": ["50%", "75%"],
                "pointer": {"show": True, "length": "68%", "width": 2, "itemStyle": {"color": "#8b92a8"}},
                "anchor": {"show": False},
                "axisLine": {"show": False},
                "axisTick": {"show": False},
                "splitLine": {"show": False},
                "axisLabel": {"show": False},
                "progress": {"show": False},
                "title": {"show": False},
                "detail": {"show": False},
                "data": [{"value": 90}],
            },
        ],
    }
    st_echarts(options=option_disp_gauge, height="200px")
    st.markdown(
        "<p style='text-align:center; color:#8b92a8; font-size:0.8rem; margin-top:-10px;'>"
        "Objetivo: 90 % (aguja gris)</p>",
        unsafe_allow_html=True,
    )

with col_hist:
    # Evolución diaria de la disponibilidad — últimos 30 días
    _fechas_disp = [f.strftime("%d/%m") for f in disp_hist_df["fecha"]]

    option_disp_hist = {
        **_EP_ANIM,
        "tooltip": {
            **_EP_TOOLTIP,
            "trigger": "axis",
            "formatter": JsCode("""
function (params) {
    var p = params[0];
    return '<b>' + p.axisValueLabel + '</b><br/>' +
           'Disponibilidad: <b>' + p.value.toFixed(1) + '%</b><br/>' +
           'Jugadores lesionados: <b>' + p.data.lesionados + '</b>';
}
"""),
        },
        "grid": {"top": 20, "bottom": 40, "left": 45, "right": 20},
        "xAxis": {
            "type": "category",
            "data": _fechas_disp,
            "axisLabel": {"fontSize": 10, "color": "#8b92a8", "rotate": 30, "fontFamily": _EP_FONT},
            "axisLine": {"show": False}, "axisTick": {"show": False}, "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value", "min": 0, "max": 100,
            "axisLabel": {"color": "#8b92a8", "fontSize": 10, "fontFamily": _EP_FONT, "formatter": "{value}%"},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#2d3148", "width": 1}},
        },
        "series": [{
            "type": "line",
            "data": [
                {"value": r["pct"], "lesionados": r["lesionados"]}
                for _, r in disp_hist_df.iterrows()
            ],
            "smooth": 0.2,
            "symbol": "circle", "symbolSize": 5,
            "lineStyle": {"color": "#F47920", "width": 2.5},
            "itemStyle": {"color": "#F47920"},
            "areaStyle": {"color": "#F47920", "opacity": 0.15},
            "markLine": {
                "symbol": ["none", "none"],
                "silent": True,
                "lineStyle": {"type": "dashed", "color": "#8b92a8", "width": 1.5},
                "label": {"formatter": "Objetivo 90%", "color": "#8b92a8", "fontSize": 10},
                "data": [{"yAxis": 90}],
            },
            "markArea": {
                "silent": True,
                "itemStyle": {"color": "rgba(214,48,49,0.10)"},
                "data": [[{"yAxis": 0}, {"yAxis": 75}]],
            },
        }],
    }
    st_echarts(options=option_disp_hist, height="220px")
    st.caption("Evolución de la disponibilidad — últimos 30 días")

st.divider()

# ── Semáforo de estado general ──────────────────────────────
# Mismo umbral que el KPI de incidencia (nivel 1), para que la
# etiqueta de arriba y el número de abajo siempre cuenten la misma
# historia clínica.
nivel_txt, nivel_color = _nivel_incidencia(m["inc_total"])
st.markdown(f"""
<div style="background:{nivel_color}1A; border:2px solid {nivel_color}; border-radius:8px;
            padding:14px 20px; text-align:center; margin-bottom:20px;">
    <span style="color:#8b92a8; font-size:0.75rem; letter-spacing:1px; text-transform:uppercase;">
        Situación epidemiológica
    </span><br>
    <span style="color:{nivel_color}; font-size:1.7rem; font-weight:700; letter-spacing:1px;">
        {nivel_txt}
    </span>
</div>
""", unsafe_allow_html=True)


def _kpi_card(etiqueta, valor, color_valor, subtexto, color_subtexto="#8b92a8"):
    """Card grande de Nivel 1 — un número protagonista con su contexto abajo."""
    return f"""
    <div class="ep-card" style="text-align:center;">
        <div style="color:#8b92a8; font-size:0.78rem; text-transform:uppercase; letter-spacing:1px;">
            {etiqueta}
        </div>
        <div style="color:{color_valor}; font-size:2.5rem; font-weight:700; margin:6px 0;">
            {valor}
        </div>
        <div style="color:{color_subtexto}; font-size:0.82rem;">
            {subtexto}
        </div>
    </div>
    """


# ── NIVEL 1: KPIs críticos restantes ─────────────────────────
# (la disponibilidad ya se mostró arriba, como hero de la página)
col_kpi2, col_kpi3 = st.columns(2)

with col_kpi2:
    st.markdown(_kpi_card(
        "Incidencia total",
        f"{m['inc_total']}",
        nivel_color,
        "lesiones / 1000 horas-atleta",
    ), unsafe_allow_html=True)

with col_kpi3:
    color_tendencia = "#d63031" if delta_carga > 0 else "#1a9e5c" if delta_carga < 0 else "#8b92a8"
    signo = "+" if delta_carga > 0 else ""
    st.markdown(_kpi_card(
        "Carga lesional",
        f"{m['carga_lesional']}",
        "#F47920",
        f"Tendencia 30d: {signo}{delta_carga}",
        color_subtexto=color_tendencia,
    ), unsafe_allow_html=True)

st.divider()

# ── NIVEL 2: Contexto ────────────────────────────────────────
st.markdown('<div class="ep-section-title" style="font-size:0.9rem;">Contexto</div>', unsafe_allow_html=True)

col_ctx1, col_ctx2, col_ctx3, col_ctx4 = st.columns(4)

with col_ctx1:
    col_ctx1.metric("Total lesiones", m["n_total"])
    col_ctx1.caption(f"{m['dias_baja_total']} días de baja totales")

with col_ctx2:
    # Ratio visual Partido vs Entrenamiento — barra proporcional en CSS puro
    total_ctx = max(m["n_partido"] + m["n_entreno"], 1)
    pct_partido = round(m["n_partido"] / total_ctx * 100)
    st.markdown("**Partido vs Entrenamiento**")
    st.markdown(f"""
    <div style="display:flex; height:10px; border-radius:5px; overflow:hidden; margin:6px 0;">
        <div style="width:{pct_partido}%; background:#F47920;"></div>
        <div style="width:{100 - pct_partido}%; background:#2d6a9f;"></div>
    </div>
    <div style="font-size:0.78rem; color:#8b92a8;">
        <span style="color:#F47920;">●</span> Partido: {m['n_partido']} &nbsp;
        <span style="color:#2d6a9f;">●</span> Entreno: {m['n_entreno']}
    </div>
    """, unsafe_allow_html=True)

with col_ctx3:
    col_ctx3.metric("Severidad media", f"{m['severidad_media']} días")
    col_ctx3.caption("días de baja por lesión")

with col_ctx4:
    col_ctx4.metric("Tasa de re-lesión", f"{m['tasa_relesion']} %")
    col_ctx4.caption(f"{m['n_relesiones']} re-lesión(es) registradas")

st.divider()

# ── NIVEL 3: Detalle técnico (colapsado) ────────────────────
with st.expander("Ver indicadores completos"):
    d1, d2, d3 = st.columns(3)
    d1.metric("Horas-atleta totales",   f"{m['ha_total']:,.0f} HA")
    d2.metric("Horas-atleta en partido", f"{m['ha_partido']:,.0f} HA")
    d3.metric("Horas-atleta en entreno", f"{m['ha_entreno']:,.0f} HA")

    st.markdown(" ")

    e1, e2 = st.columns(2)
    e1.metric("Incidencia en partido", f"{m['inc_partido']}")
    e1.caption("lesiones / 1000 horas-atleta")
    e2.metric("Incidencia en entreno", f"{m['inc_entreno']}")
    e2.caption("lesiones / 1000 horas-atleta")

    st.markdown(" ")
    st.markdown("""
    | Indicador | Referencia UEFA (élite) | Tu plantel |
    |---|---|---|
    | Incidencia total | 6 – 9 / 1000 HA | **{:.2f}** |
    | Incidencia partido | 25 – 35 / 1000 HA | **{:.2f}** |
    | Incidencia entreno | 3 – 6 / 1000 HA | **{:.2f}** |
    | Severidad media | 15 – 25 días | **{:.1f} días** |
    | Carga lesional | 100 – 200 días/1000 HA | **{:.1f}** |
    | Tasa re-lesión | 10 – 20 % | **{:.1f} %** |

    *Fuller CW et al. Consensus statement on injury definitions and data collection
    procedures in studies of football (soccer) injuries. Br J Sports Med, 2006.*
    """.format(
        m["inc_total"], m["inc_partido"], m["inc_entreno"],
        m["severidad_media"], m["carga_lesional"], m["tasa_relesion"]
    ))

st.divider()


# ============================================================
# SECCIÓN 2: LESIONES POR ZONA CORPORAL Y TIPO (STACKED BAR)
# ============================================================

st.markdown('<div class="ep-badge ep-badge-medico">Medico</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title">Distribución por Zona Corporal y Tipo de Lesión</div>', unsafe_allow_html=True)

col_zona, col_tipo = st.columns([3, 2])

with col_zona:
    # Datos para el gráfico apilado
    lesiones_zona = (
        lesiones_df.groupby(["zona_corporal", "tipo_lesion"])
        .size()
        .reset_index(name="n_lesiones")
    )

    # Ordenar zonas por total de lesiones (de mayor a menor)
    orden_zonas = (
        lesiones_zona.groupby("zona_corporal")["n_lesiones"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    COLORES_TIPO = {
        "muscular":     "#E74C3C",
        "ligamentosa":  "#3498DB",
        "contusión":    "#F39C12",
        "sobrecarga":   "#9B59B6",
        "tendinopatía": "#1ABC9C",
        "ósea":         "#95A5A6",
    }

    # Pivotar para obtener series por tipo_lesion × zona_corporal
    _pivot_zona = lesiones_zona.pivot_table(
        index="tipo_lesion", columns="zona_corporal",
        values="n_lesiones", fill_value=0,
    )
    _series_zona = []
    for tipo, color in COLORES_TIPO.items():
        if tipo in _pivot_zona.index:
            _series_zona.append({
                "name": tipo, "type": "bar", "stack": "zona",
                "data": [int(_pivot_zona.loc[tipo, z]) if z in _pivot_zona.columns else 0
                         for z in orden_zonas],
                "itemStyle": {"color": color},
                "label": {"show": True, "formatter": JsCode(
                    "function(p){ return p.value > 0 ? p.value : ''; }"
                )},
            })

    option_zona = {
        **_EP_ANIM,
        "tooltip": {**_EP_TOOLTIP, "trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {**_EP_LEGEND, "data": list(COLORES_TIPO.keys())},
        "grid": {"top": 40, "bottom": 80, "left": 50, "right": 24},
        "xAxis": {
            "type": "category", "data": orden_zonas,
            "axisLabel": {"fontSize": 12, "color": "#666666", "fontFamily": _EP_FONT, "rotate": 30},
            "axisLine": {"show": False}, "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value", "name": "Nº de lesiones",
            "nameTextStyle": {"color": "#888888", "fontSize": 11, "fontFamily": _EP_FONT},
            "axisLabel": {"color": "#666666", "fontSize": 12, "fontFamily": _EP_FONT},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
        },
        "series": _series_zona,
    }
    st_echarts(options=option_zona, height="380px")

with col_tipo:
    # Tabla resumen por tipo de lesión con severidad media
    resumen_tipo = (
        lesiones_df.groupby("tipo_lesion")
        .agg(
            n_lesiones   =("id",       "count"),
            dias_baja_total=("dias_baja", "sum"),
            severidad_media=("dias_baja", "mean"),
        )
        .reset_index()
        .sort_values("n_lesiones", ascending=False)
    )
    resumen_tipo.columns = ["Tipo", "N lesiones", "Días totales", "Severidad media (días)"]
    resumen_tipo["Severidad media (días)"] = resumen_tipo["Severidad media (días)"].round(1)

    st.markdown("**Resumen por tipo:**")
    st.dataframe(resumen_tipo, hide_index=True, width='stretch', height=200)

    # Gráfico de dona — proporción de tipos
    conteo_tipo = lesiones_df["tipo_lesion"].value_counts().reset_index()
    conteo_tipo.columns = ["tipo", "cantidad"]

    _dona_data = [
        {"name": r["tipo"], "value": int(r["cantidad"]),
         "itemStyle": {"color": COLORES_TIPO.get(r["tipo"], "#999")}}
        for _, r in conteo_tipo.iterrows()
    ]
    option_dona = {
        **_EP_ANIM,
        "title": {
            "text": "Proporción por tipo",
            "textStyle": {"fontSize": 13, "color": "#3D3D3D", "fontWeight": "600", "fontFamily": _EP_FONT},
            "top": 4, "left": "center",
        },
        "tooltip": {**_EP_TOOLTIP, "trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "series": [{
            "type": "pie", "radius": ["40%", "65%"], "center": ["50%", "58%"],
            "data": _dona_data,
            "label": {"show": True, "formatter": "{b}\n{d}%", "fontSize": 10, "fontFamily": _EP_FONT},
            "labelLine": {"length": 8, "length2": 6},
            "itemStyle": {"borderColor": "#fff", "borderWidth": 2,
                          "shadowBlur": 4, "shadowColor": "rgba(0,0,0,0.08)"},
        }],
    }
    st_echarts(options=option_dona, height="260px")

st.divider()


# ============================================================
# SECCIÓN 3: EVOLUCIÓN TEMPORAL DE LESIONES POR MES
# ============================================================

st.markdown('<div class="ep-badge ep-badge-medico">Medico</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title">Evolución Temporal de Lesiones</div>', unsafe_allow_html=True)

# Agregar columna de mes
lesiones_df["mes"] = (
    lesiones_df["fecha_inicio"]
    .dt.to_period("M")
    .dt.to_timestamp()
)

# Contar lesiones por mes y contexto
por_mes_contexto = (
    lesiones_df.groupby(["mes", "contexto"])
    .size()
    .reset_index(name="n_lesiones")
)

# Total por mes para la línea acumulada
por_mes_total = (
    lesiones_df.groupby("mes")
    .size()
    .reset_index(name="n_lesiones")
    .sort_values("mes")
)
por_mes_total["acumuladas"] = por_mes_total["n_lesiones"].cumsum()

_meses_str  = [m.strftime("%b %Y") for m in por_mes_total["mes"]]

def _mes_data(contexto):
    d = por_mes_contexto[por_mes_contexto["contexto"] == contexto].set_index("mes")
    return [int(d.loc[m, "n_lesiones"]) if m in d.index else 0
            for m in por_mes_total["mes"]]

option_tiempo = {
    **_EP_ANIM,
    "tooltip": {**_EP_TOOLTIP, "trigger": "axis", "axisPointer": {"type": "shadow"}},
    "legend": {**_EP_LEGEND, "data": ["Partido", "Entrenamiento", "Acumulado"]},
    "grid": {"top": 40, "bottom": 80, "left": 55, "right": 55},
    "xAxis": {
        "type": "category", "data": _meses_str,
        "axisLabel": {"fontSize": 12, "color": "#666666", "fontFamily": _EP_FONT, "rotate": 30},
        "axisLine": {"show": False}, "axisTick": {"show": False},
    },
    "yAxis": [
        {
            "type": "value", "name": "Lesiones/mes",
            "nameTextStyle": {"color": "#888888", "fontSize": 10, "fontFamily": _EP_FONT},
            "axisLabel": {"color": "#666666", "fontSize": 11, "fontFamily": _EP_FONT},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f0f0f0", "width": 1}},
        },
        {
            "type": "value", "name": "Acumuladas",
            "nameTextStyle": {"color": "#888888", "fontSize": 10, "fontFamily": _EP_FONT},
            "axisLabel": {"color": "#666666", "fontSize": 11, "fontFamily": _EP_FONT},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "splitLine": {"show": False},
            "position": "right",
        },
    ],
    "series": [
        {
            "name": "Partido", "type": "bar", "yAxisIndex": 0,
            "data": _mes_data("Partido"),
            "itemStyle": {"color": "#E74C3C", "borderRadius": [4, 4, 0, 0]},
        },
        {
            "name": "Entrenamiento", "type": "bar", "yAxisIndex": 0,
            "data": _mes_data("Entrenamiento"),
            "itemStyle": {"color": "#3498DB", "borderRadius": [4, 4, 0, 0]},
        },
        {
            "name": "Acumulado", "type": "line", "yAxisIndex": 1,
            "data": por_mes_total["acumuladas"].tolist(),
            "symbol": "circle", "symbolSize": 7,
            "lineStyle": {"color": "#2C3E50", "width": 2.5},
            "itemStyle": {"color": "#2C3E50"},
        },
    ],
}
st_echarts(options=option_tiempo, height="400px")

# Mini-métricas del gráfico
c1, c2, c3 = st.columns(3)
mes_pico = por_mes_total.loc[por_mes_total["n_lesiones"].idxmax()]
c1.metric("Mes con más lesiones",
          mes_pico["mes"].strftime("%B %Y"),
          f"{int(mes_pico['n_lesiones'])} lesiones")
c2.metric("Ratio partido/entreno",
          f"{m['n_partido']} / {m['n_entreno']}",
          f"Partido: {m['inc_partido']} vs Entreno: {m['inc_entreno']} /1000HA")
c3.metric("Promedio mensual",
          f"{por_mes_total['n_lesiones'].mean():.1f} lesiones/mes")

st.divider()


# ============================================================
# SECCIÓN 4: TABLA COMPLETA DE LESIONES
# ============================================================

st.markdown('<div class="ep-badge ep-badge-medico">Medico</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title">Registro Completo de Lesiones</div>', unsafe_allow_html=True)

# Preparar tabla para mostrar
tabla = lesiones_df[[
    "numero", "jugador", "posicion",
    "fecha_inicio", "fecha_fin",
    "tipo_lesion", "zona_corporal",
    "contexto", "dias_baja", "activo",
]].copy()

tabla["fecha_inicio"] = tabla["fecha_inicio"].dt.strftime("%d/%m/%Y")
tabla["fecha_fin"]    = tabla["fecha_fin"].apply(
    lambda x: x.strftime("%d/%m/%Y") if pd.notna(x) else "En baja"
)
tabla["activo"] = tabla["activo"].map({1: "En baja", 0: "Recuperado"})

tabla = tabla.rename(columns={
    "numero":       "#",
    "jugador":      "Jugador",
    "posicion":     "Posición",
    "fecha_inicio": "Fecha inicio",
    "fecha_fin":    "Alta / Estado",
    "tipo_lesion":  "Tipo",
    "zona_corporal":"Zona",
    "contexto":     "Contexto",
    "dias_baja":    "Días baja",
    "activo":       "Estado",
})

# Colorear filas según estado
def _color_estado_fila(row):
    if row["Estado"] == "En baja":
        return ["background-color:#fff0f0"] * len(row)
    else:
        return ["background-color:#f0fff4"] * len(row)

styled_tabla = (
    tabla.style
    .apply(_color_estado_fila, axis=1)
    .hide(axis="index")
)

st.dataframe(styled_tabla, width='stretch', height=420)

# Exportar nota
st.caption(
    f"Total: {m['n_total']} lesiones · {m['n_relesiones']} re-lesiones · "
    f"{m['dias_baja_total']} días de baja totales"
)

st.divider()


# ============================================================
# SECCIÓN 5: RECORRIDO DE LESIONES (SANKEY)
# Flujo: Lesión Tipo Zona corporal Decisión RTP Disponibilidad
# ============================================================

st.markdown('<div class="ep-badge ep-badge-medico">Medico</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title">Recorrido de las Lesiones</div>', unsafe_allow_html=True)
st.caption(
    "Cada lesión fluye de izquierda a derecha: tipo de lesión zona corporal "
    "última decisión RTP registrada estado de disponibilidad actual."
)

decisiones_rtp = cargar_decisiones_rtp()

flujo = lesiones_df[["id", "tipo_lesion", "zona_corporal", "activo"]].copy()

if not decisiones_rtp.empty:
    flujo = flujo.merge(
        decisiones_rtp[["lesion_id", "decision"]],
        left_on="id", right_on="lesion_id", how="left",
    )
else:
    flujo["decision"] = None

ETIQUETAS_DECISION = {
    "APTO":              "RTP: Apto",
    "APTO_CONDICIONADO": "RTP: Apto condic.",
    "NO_APTO":           "RTP: No apto",
}
flujo["rtp_label"] = flujo["decision"].map(ETIQUETAS_DECISION).fillna("RTP: Sin evaluar")
flujo["tipo_label"] = "Tipo: " + flujo["tipo_lesion"].astype(str)
flujo["zona_label"] = "Zona: " + flujo["zona_corporal"].astype(str)
flujo["disponible_label"] = flujo["activo"].map({0: "Disponible", 1: "No disponible"})
flujo["raiz"] = "Lesiones"


def _contar_enlaces(df, columna_origen, columna_destino):
    """Cuenta cuántas lesiones fluyen de un nodo a otro (un enlace del Sankey)."""
    return (
        df.groupby([columna_origen, columna_destino])
        .size()
        .reset_index(name="value")
        .rename(columns={columna_origen: "source", columna_destino: "target"})
    )


enlaces_sankey = pd.concat([
    _contar_enlaces(flujo, "raiz",       "tipo_label"),
    _contar_enlaces(flujo, "tipo_label", "zona_label"),
    _contar_enlaces(flujo, "zona_label", "rtp_label"),
    _contar_enlaces(flujo, "rtp_label",  "disponible_label"),
], ignore_index=True)


def _color_nodo_sankey(nombre):
    if nombre == "Lesiones":
        return "#3D3D3D"
    if nombre.startswith("Tipo: "):
        return "#F47920"
    if nombre.startswith("Zona: "):
        return "#2d6a9f"
    if nombre == "RTP: Apto":
        return "#1a9e5c"
    if nombre == "RTP: Apto condic.":
        return "#e8a020"
    if nombre == "RTP: No apto":
        return "#d63031"
    if nombre == "RTP: Sin evaluar":
        return "#999999"
    if nombre == "Disponible":
        return "#1a9e5c"
    if nombre == "No disponible":
        return "#d63031"
    return "#cccccc"


_nodos_unicos = pd.unique(enlaces_sankey[["source", "target"]].values.ravel())
_nodos_sankey = [
    {"name": n, "itemStyle": {"color": _color_nodo_sankey(n)}}
    for n in _nodos_unicos
]
_links_sankey = [
    {"source": row["source"], "target": row["target"], "value": int(row["value"])}
    for _, row in enlaces_sankey.iterrows()
]

option_sankey = {
    **_EP_ANIM,
    "tooltip": {
        **_EP_TOOLTIP,
        "trigger": "item",
        "formatter": JsCode("""
function (p) {
    if (p.dataType === 'edge') {
        return p.data.source + ' ' + p.data.target + '<br/><b>' + p.data.value + '</b> lesión(es)';
    }
    return '<b>' + p.name + '</b>';
}
"""),
    },
    "series": [{
        "type": "sankey",
        "layout": "none",
        "emphasis": {"focus": "adjacency"},
        "data": _nodos_sankey,
        "links": _links_sankey,
        "lineStyle": {"color": "gradient", "curveness": 0.5, "opacity": 0.35},
        "label": {"fontSize": 11, "fontFamily": _EP_FONT, "color": "#3D3D3D"},
        "nodeWidth": 16,
        "nodeGap": 12,
    }],
}

st_echarts(options=option_sankey, height="500px")

if decisiones_rtp.empty:
    st.info(
        "Todavía no hay evaluaciones cargadas en el módulo RTP — por eso "
        "todas las lesiones aparecen como **'RTP: Sin evaluar'**. Ese tramo se "
        "va completando a medida que los fisios cargan evaluaciones en RTP."
    )
