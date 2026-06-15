"""
pages/RTP.py
============
Módulo de Return to Play (RTP) — acceso exclusivo para fisioterapeutas.

Flujo de trabajo:
  1. El fisio ingresa la contraseña (configurada en Streamlit Secrets)
  2. Selecciona el jugador en proceso de RTP
  3. Registra la sesión: por cada drill → EVA (0-10) + Confianza (0-10)
  4. Decide si el jugador avanza de etapa
  5. La pestaña Seguimiento muestra la evolución gráfica

Protocolo de 6 etapas iterativo — drills configurables desde la DB.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sqlite3
import os
from datetime import date


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="RTP — Fisioterapia",
    page_icon="🏥",
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


# ── Funciones de lectura (sin depender de metricas.py) ──────

def cargar_jugadores():
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, nombre || ' ' || apellido AS jugador,
               posicion, numero_camiseta AS numero
        FROM jugadores
        ORDER BY posicion, numero_camiseta
    """, conn)
    conn.close()
    return df


def cargar_etapas_rtp():
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, orden, nombre, descripcion, eva_max, confianza_min
        FROM rtp_etapas WHERE activa = 1 ORDER BY orden
    """, conn)
    conn.close()
    return df


def cargar_drills_etapa(etapa_id):
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, nombre, descripcion
        FROM rtp_drills WHERE etapa_id = ? AND activo = 1 ORDER BY id
    """, conn, params=[etapa_id])
    conn.close()
    return df


def cargar_sesiones_rtp_jugador(jugador_id):
    conn = _conectar()
    df = pd.read_sql("""
        SELECT s.id AS sesion_id, s.fecha, s.etapa_id,
               e.orden AS etapa_orden, e.nombre AS etapa_nombre,
               e.eva_max, e.confianza_min,
               s.fisio, s.avanza, s.notas,
               COUNT(r.id) AS n_drills,
               ROUND(AVG(r.eva), 1) AS eva_promedio,
               ROUND(AVG(r.confianza), 1) AS confianza_promedio,
               MAX(r.eva) AS eva_max_sesion
        FROM rtp_sesiones s
        JOIN rtp_etapas e ON e.id = s.etapa_id
        LEFT JOIN rtp_resultados r ON r.sesion_id = s.id
        WHERE s.jugador_id = ?
        GROUP BY s.id ORDER BY s.fecha
    """, conn, params=[jugador_id], parse_dates=["fecha"])
    conn.close()
    return df


def cargar_resultados_sesion(sesion_id):
    conn = _conectar()
    df = pd.read_sql("""
        SELECT r.id, d.nombre AS drill, r.completado, r.eva, r.confianza, r.notas
        FROM rtp_resultados r
        JOIN rtp_drills d ON d.id = r.drill_id
        WHERE r.sesion_id = ? ORDER BY r.id
    """, conn, params=[sesion_id])
    conn.close()
    return df


def etapa_actual_jugador(jugador_id):
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("""
        SELECT s.etapa_id, e.orden, e.nombre, s.avanza
        FROM rtp_sesiones s
        JOIN rtp_etapas e ON e.id = s.etapa_id
        WHERE s.jugador_id = ?
        ORDER BY s.fecha DESC LIMIT 1
    """, (jugador_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"etapa_id": row[0], "orden": row[1], "nombre": row[2], "avanza": row[3]}


# ============================================================
# PUERTA DE CONTRASEÑA
# Solo pasa quien tenga la clave configurada en st.secrets.
# En Streamlit Cloud: Settings → Secrets → rtp_password = "clave"
# En local: .streamlit/secrets.toml → rtp_password = "clave"
# ============================================================

if "rtp_auth" not in st.session_state:
    st.session_state.rtp_auth = False

if not st.session_state.rtp_auth:
    st.title("🏥 Módulo RTP — Fisioterapia")
    st.divider()

    col_login, _ = st.columns([1, 2])
    with col_login:
        st.markdown("**Acceso restringido al equipo de fisioterapia.**")
        clave = st.text_input("Contraseña", type="password", key="input_clave")
        if st.button("Ingresar", type="primary", use_container_width=True):
            clave_correcta = st.secrets.get("rtp_password", "")
            if clave == clave_correcta and clave_correcta != "":
                st.session_state.rtp_auth = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")

    st.stop()   # nada más se ejecuta si no está autenticado


# ============================================================
# FUNCIONES DE GUARDADO EN DB
# ============================================================

def guardar_sesion_rtp(jugador_id, lesion_id, fecha_str, etapa_id,
                       fisio, avanza, notas, resultados_lista):
    """
    Inserta la sesión y sus resultados por drill.
    resultados_lista: lista de dicts con drill_id, eva, confianza, notas.
    """
    conn = _conectar()
    cur  = conn.cursor()

    cur.execute("""
        INSERT INTO rtp_sesiones
            (jugador_id, lesion_id, fecha, etapa_id, fisio, avanza, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (jugador_id, lesion_id, fecha_str, etapa_id,
          fisio, 1 if avanza else 0, notas))

    sesion_id = cur.lastrowid

    for r in resultados_lista:
        cur.execute("""
            INSERT INTO rtp_resultados
                (sesion_id, drill_id, completado, eva, confianza, notas)
            VALUES (?, ?, 1, ?, ?, ?)
        """, (sesion_id, r["drill_id"], r["eva"], r["confianza"], r.get("notas", "")))

    conn.commit()
    conn.close()
    return sesion_id


def insertar_drill(etapa_id, nombre, descripcion=""):
    """Agrega un nuevo drill a una etapa."""
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO rtp_drills (etapa_id, nombre, descripcion)
        VALUES (?, ?, ?)
    """, (etapa_id, nombre, descripcion))
    conn.commit()
    conn.close()


def desactivar_drill(drill_id):
    """Desactiva (oculta) un drill sin borrarlo de la DB."""
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("UPDATE rtp_drills SET activo = 0 WHERE id = ?", (drill_id,))
    conn.commit()
    conn.close()


# ============================================================
# CARGAR DATOS BÁSICOS
# ============================================================

jugadores_df = cargar_jugadores()
etapas_df    = cargar_etapas_rtp()

opciones_jug = {
    f"#{int(r['numero'])} {r['jugador']} ({r['posicion']})": int(r["id"])
    for _, r in jugadores_df.iterrows()
}


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("🏥 RTP — Fisioterapia")
    st.divider()

    if st.button("🔄 Actualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # Cerrar sesión
    if st.button("🔒 Cerrar sesión", use_container_width=True):
        st.session_state.rtp_auth = False
        st.rerun()

    st.divider()
    st.markdown("""
    **Escalas:**
    - **EVA dolor** → 0 = sin dolor · 10 = dolor máximo
    - **Confianza** → 0 = nula · 10 = total seguridad
    """)
    st.divider()
    st.caption("Módulo RTP · EQUIPOPHYSICAL")


# ============================================================
# HEADER
# ============================================================

st.title("🏥 Return to Play — Panel Fisioterapia")
st.caption(
    "Registro de sesiones de rehabilitación · "
    "EVA por drill + Confianza en zona lesionada"
)
st.divider()


# ============================================================
# PESTAÑAS
# ============================================================

tab_sesion, tab_seguimiento, tab_protocolo = st.tabs([
    "📋 Registrar sesión",
    "📈 Seguimiento del jugador",
    "⚙️ Protocolo / Drills",
])


# ============================================================
# PESTAÑA 1: REGISTRAR SESIÓN
# ============================================================

with tab_sesion:

    st.subheader("📋 Nueva sesión RTP")

    # ── Datos de la sesión ───────────────────────────────────
    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])

    with col_s1:
        jug_nombre = st.selectbox("Jugador", list(opciones_jug.keys()), key="sel_jug_rtp")
        jug_id     = opciones_jug[jug_nombre]

    with col_s2:
        fecha_ses = st.date_input("Fecha", value=date.today(), key="fecha_rtp")

    with col_s3:
        fisio_nombre = st.text_input("Fisioterapeuta", placeholder="Nombre del fisio")

    # Detectar etapa actual del jugador
    etapa_actual = etapa_actual_jugador(jug_id)

    if etapa_actual and etapa_actual["avanza"]:
        # Si en la última sesión se aprobó avance, sugerir la siguiente etapa
        etapa_sugerida_orden = min(etapa_actual["orden"] + 1, etapas_df["orden"].max())
    elif etapa_actual:
        etapa_sugerida_orden = etapa_actual["orden"]
    else:
        etapa_sugerida_orden = 1   # primer ingreso al protocolo

    # Selector de etapa (con sugerencia automática)
    opciones_etapas = {
        f"Etapa {int(r['orden'])} — {r['nombre']}": int(r["id"])
        for _, r in etapas_df.iterrows()
    }
    idx_sugerido = etapa_sugerida_orden - 1   # orden comienza en 1

    col_e1, col_e2 = st.columns([3, 1])
    with col_e1:
        etapa_sel_nombre = st.selectbox(
            "Etapa del protocolo",
            list(opciones_etapas.keys()),
            index=min(idx_sugerido, len(opciones_etapas) - 1),
            key="sel_etapa_rtp",
        )
        etapa_sel_id = opciones_etapas[etapa_sel_nombre]

    with col_e2:
        etapa_row = etapas_df[etapas_df["id"] == etapa_sel_id].iloc[0]
        st.markdown("<br>", unsafe_allow_html=True)
        st.info(f"EVA ≤ {int(etapa_row['eva_max'])} · Confianza ≥ {int(etapa_row['confianza_min'])}")

    # ID de lesión asociada (opcional — campo libre para vincular)
    lesion_id_input = st.number_input(
        "ID de lesión asociada (opcional — ver tabla Lesiones)",
        min_value=0, value=0, step=1,
        help="Ingresá el ID de la lesión de la tabla Lesiones. Dejá en 0 si no querés vincular.",
        key="lesion_id_rtp"
    )
    lesion_id = int(lesion_id_input) if lesion_id_input > 0 else None

    st.divider()

    # ── Drills de la etapa ───────────────────────────────────
    drills_df = cargar_drills_etapa(etapa_sel_id)

    if drills_df.empty:
        st.warning("Esta etapa no tiene drills configurados. Agregalos en la pestaña ⚙️ Protocolo.")
        st.stop()

    st.markdown(f"**Drills de la sesión — {etapa_sel_nombre}**")
    st.caption(
        "Completá EVA y Confianza para cada drill realizado. "
        "EVA 0 = sin dolor · Confianza 10 = seguridad total en la zona."
    )

    resultados = []
    todos_ok   = True

    for _, drill in drills_df.iterrows():
        with st.container(border=True):
            col_drill_nom, col_eva, col_conf, col_nota = st.columns([3, 1.5, 1.5, 2])

            with col_drill_nom:
                st.markdown(f"**{drill['nombre']}**")
                if drill.get("descripcion"):
                    st.caption(drill["descripcion"])

            with col_eva:
                eva_val = st.slider(
                    "EVA dolor",
                    min_value=0, max_value=10, value=0,
                    key=f"eva_{drill['id']}",
                    help="0 = sin dolor · 10 = dolor máximo",
                )
                # Colorear según umbral de la etapa
                color_eva = "#21C354" if eva_val <= etapa_row["eva_max"] else "#FF4B4B"
                st.markdown(
                    f"<div style='text-align:center; font-size:1.4rem; "
                    f"font-weight:bold; color:{color_eva}'>{eva_val}</div>",
                    unsafe_allow_html=True,
                )

            with col_conf:
                conf_val = st.slider(
                    "Confianza",
                    min_value=0, max_value=10, value=5,
                    key=f"conf_{drill['id']}",
                    help="0 = nula confianza · 10 = seguridad total",
                )
                color_conf = "#21C354" if conf_val >= etapa_row["confianza_min"] else "#FF8C00"
                st.markdown(
                    f"<div style='text-align:center; font-size:1.4rem; "
                    f"font-weight:bold; color:{color_conf}'>{conf_val}</div>",
                    unsafe_allow_html=True,
                )

            with col_nota:
                nota_drill = st.text_input(
                    "Observación",
                    placeholder="Opcional...",
                    key=f"nota_{drill['id']}",
                    label_visibility="collapsed",
                )
                st.caption("Observación del drill")

            # Verificar si cumple criterios de la etapa
            if eva_val > etapa_row["eva_max"] or conf_val < etapa_row["confianza_min"]:
                todos_ok = False

            resultados.append({
                "drill_id":  int(drill["id"]),
                "eva":       eva_val,
                "confianza": conf_val,
                "notas":     nota_drill,
            })

    st.divider()

    # ── Resumen de la sesión ─────────────────────────────────
    eva_prom  = sum(r["eva"]       for r in resultados) / len(resultados)
    conf_prom = sum(r["confianza"] for r in resultados) / len(resultados)

    col_res1, col_res2, col_res3 = st.columns(3)
    col_res1.metric("EVA promedio sesión",      f"{eva_prom:.1f} / 10",
                    delta="OK" if eva_prom <= etapa_row["eva_max"] else "⚠️ Sobre umbral",
                    delta_color="normal" if eva_prom <= etapa_row["eva_max"] else "inverse")
    col_res2.metric("Confianza promedio sesión", f"{conf_prom:.1f} / 10",
                    delta="OK" if conf_prom >= etapa_row["confianza_min"] else "⚠️ Bajo umbral",
                    delta_color="normal" if conf_prom >= etapa_row["confianza_min"] else "inverse")
    col_res3.metric("Drills completados",         len(resultados))

    # Criterio de avance sugerido automáticamente
    if todos_ok:
        st.success(
            f"✅ Todos los drills cumplen los criterios de la etapa "
            f"(EVA ≤ {int(etapa_row['eva_max'])} · Confianza ≥ {int(etapa_row['confianza_min'])}). "
            f"El jugador puede avanzar de etapa a criterio clínico del fisio."
        )
    else:
        st.warning(
            f"⚠️ Algún drill no cumple los criterios (EVA ≤ {int(etapa_row['eva_max'])} · "
            f"Confianza ≥ {int(etapa_row['confianza_min'])}). "
            f"Revisar antes de avanzar de etapa."
        )

    # ── Decisión clínica del fisio ───────────────────────────
    st.divider()
    col_dec1, col_dec2 = st.columns([2, 2])

    with col_dec1:
        avanza = st.checkbox(
            "✅ Autorizo avance a la siguiente etapa",
            value=todos_ok,
            help="Decisión clínica del fisio — independiente del criterio automático.",
        )

    with col_dec2:
        notas_ses = st.text_area(
            "Notas de la sesión",
            placeholder="Observaciones generales, contexto, plan para próxima sesión...",
            height=80,
            key="notas_sesion",
        )

    # ── Botón guardar ────────────────────────────────────────
    st.markdown(" ")
    col_btn, col_aviso = st.columns([1, 3])

    with col_btn:
        guardar = st.button(
            "💾 Guardar sesión",
            type="primary",
            use_container_width=True,
            key="btn_guardar_rtp",
        )

    with col_aviso:
        st.markdown("<br>", unsafe_allow_html=True)
        if not fisio_nombre:
            st.warning("⚠️ Completá el nombre del fisioterapeuta antes de guardar.")

    if guardar:
        if not fisio_nombre:
            st.error("❌ El nombre del fisioterapeuta es obligatorio.")
        else:
            try:
                sid = guardar_sesion_rtp(
                    jugador_id    = jug_id,
                    lesion_id     = lesion_id,
                    fecha_str     = str(fecha_ses),
                    etapa_id      = etapa_sel_id,
                    fisio         = fisio_nombre,
                    avanza        = avanza,
                    notas         = notas_ses,
                    resultados_lista = resultados,
                )
                etapa_sig = etapas_df[etapas_df["orden"] == etapa_row["orden"] + 1]
                msg_avance = (
                    f"Avance aprobado → **{etapa_sig.iloc[0]['nombre']}**."
                    if avanza and not etapa_sig.empty
                    else "Continúa en la etapa actual."
                )
                st.success(
                    f"✅ Sesión #{sid} guardada — "
                    f"{jug_nombre.split('(')[0].strip()} · "
                    f"{fecha_ses.strftime('%d/%m/%Y')} · "
                    f"{etapa_sel_nombre}. {msg_avance}"
                )
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")


# ============================================================
# PESTAÑA 2: SEGUIMIENTO DEL JUGADOR
# ============================================================

with tab_seguimiento:

    st.subheader("📈 Seguimiento RTP por jugador")

    jug_seg_nombre = st.selectbox(
        "Jugador",
        list(opciones_jug.keys()),
        key="sel_jug_seg",
    )
    jug_seg_id = opciones_jug[jug_seg_nombre]

    sesiones_df = cargar_sesiones_rtp_jugador(jug_seg_id)

    if sesiones_df.empty:
        st.info(f"Sin sesiones RTP registradas para {jug_seg_nombre.split('(')[0].strip()}.")
    else:
        # Métricas resumen
        n_ses      = len(sesiones_df)
        etapa_hoy  = sesiones_df.iloc[-1]["etapa_nombre"]
        orden_hoy  = int(sesiones_df.iloc[-1]["etapa_orden"])
        dias_rtp   = (sesiones_df["fecha"].max() - sesiones_df["fecha"].min()).days + 1
        eva_ultima = sesiones_df.iloc[-1]["eva_promedio"]
        conf_ultima= sesiones_df.iloc[-1]["confianza_promedio"]

        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        col_m1.metric("Etapa actual",    f"{orden_hoy} / 6")
        col_m2.metric("Etapa",           etapa_hoy[:20])
        col_m3.metric("Días en RTP",     dias_rtp)
        col_m4.metric("EVA última ses.", f"{eva_ultima:.1f}" if pd.notna(eva_ultima) else "—")
        col_m5.metric("Conf. última ses.", f"{conf_ultima:.1f}" if pd.notna(conf_ultima) else "—")

        st.divider()

        # ── Gráfico EVA y Confianza por sesión ───────────────
        st.markdown("**Evolución de EVA y Confianza por sesión:**")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=sesiones_df["fecha"],
            y=sesiones_df["eva_promedio"],
            name="EVA promedio",
            mode="lines+markers",
            line=dict(color="#FF4B4B", width=2.5),
            marker=dict(size=9),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>EVA: %{y:.1f}<extra></extra>",
        ))

        fig.add_trace(go.Scatter(
            x=sesiones_df["fecha"],
            y=sesiones_df["confianza_promedio"],
            name="Confianza promedio",
            mode="lines+markers",
            line=dict(color="#21C354", width=2.5),
            marker=dict(size=9),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Confianza: %{y:.1f}<extra></extra>",
        ))

        # Líneas de umbral por etapa (última etapa activa)
        eva_umbral  = int(sesiones_df.iloc[-1]["eva_max"])
        conf_umbral = int(sesiones_df.iloc[-1]["confianza_min"])

        fig.add_hline(
            y=eva_umbral, line_dash="dot", line_color="#FF4B4B", line_width=1.5,
            annotation_text=f"EVA máx etapa: {eva_umbral}",
            annotation_position="right",
            annotation_font=dict(size=10, color="#FF4B4B"),
        )
        fig.add_hline(
            y=conf_umbral, line_dash="dot", line_color="#21C354", line_width=1.5,
            annotation_text=f"Conf. mín etapa: {conf_umbral}",
            annotation_position="right",
            annotation_font=dict(size=10, color="#21C354"),
        )

        # Sombrear cambios de etapa
        etapas_vistas = sesiones_df.drop_duplicates("etapa_id", keep="first")
        for _, et in etapas_vistas.iterrows():
            fig.add_vline(
                x=et["fecha"],
                line_dash="dash",
                line_color="#888",
                line_width=1,
                annotation_text=f"E{int(et['etapa_orden'])}",
                annotation_position="top",
                annotation_font=dict(size=9, color="#555"),
            )

        fig.update_layout(
            xaxis_title="",
            yaxis_title="Puntaje (0–10)",
            yaxis=dict(range=[0, 10.5]),
            xaxis=dict(tickformat="%d/%m"),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=380,
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.2),
            margin=dict(t=20, b=20, l=50, r=130),
        )

        st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # ── Línea de tiempo de etapas ────────────────────────
        st.markdown("**Progresión por etapas:**")

        for orden in range(1, 7):
            ses_etapa = sesiones_df[sesiones_df["etapa_orden"] == orden]
            etapa_info= etapas_df[etapas_df["orden"] == orden]

            if etapa_info.empty:
                continue

            nombre_etapa = etapa_info.iloc[0]["nombre"]

            if ses_etapa.empty:
                icono, color, detalle = "⬜", "#ccc", "Sin iniciar"
            elif ses_etapa["avanza"].any():
                n_dias = len(ses_etapa)
                icono, color = "✅", "#21C354"
                detalle = f"{n_dias} sesión(es) · Alta: {ses_etapa.iloc[-1]['fecha'].strftime('%d/%m/%Y')}"
            else:
                n_dias = len(ses_etapa)
                icono, color = "🔄", "#FF8C00"
                detalle = f"{n_dias} sesión(es) · En curso"

            st.markdown(
                f"<div style='border-left:4px solid {color}; padding:6px 12px; "
                f"margin-bottom:6px; border-radius:3px; background:{color}15'>"
                f"<b>{icono} Etapa {orden} — {nombre_etapa}</b>"
                f"<span style='color:gray; font-size:0.85rem; margin-left:12px'>{detalle}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Historial de sesiones ────────────────────────────
        with st.expander("📋 Historial de sesiones"):
            hist = sesiones_df[[
                "fecha", "etapa_orden", "etapa_nombre",
                "eva_promedio", "confianza_promedio",
                "n_drills", "avanza", "fisio", "notas"
            ]].copy()
            hist["fecha"]  = hist["fecha"].dt.strftime("%d/%m/%Y")
            hist["avanza"] = hist["avanza"].map({1: "✅ Avanzó", 0: "🔄 Continúa"})
            hist = hist.rename(columns={
                "fecha":               "Fecha",
                "etapa_orden":         "E#",
                "etapa_nombre":        "Etapa",
                "eva_promedio":        "EVA prom.",
                "confianza_promedio":  "Conf. prom.",
                "n_drills":            "Drills",
                "avanza":              "Estado",
                "fisio":               "Fisio",
                "notas":               "Notas",
            })
            st.dataframe(hist, hide_index=True, use_container_width=True, height=300)


# ============================================================
# PESTAÑA 3: PROTOCOLO / DRILLS
# ============================================================

with tab_protocolo:

    st.subheader("⚙️ Protocolo RTP — Etapas y Drills")
    st.caption("Visualizá el protocolo actual y agregá o desactivá drills por etapa.")

    for _, etapa in etapas_df.iterrows():
        drills = cargar_drills_etapa(int(etapa["id"]))

        with st.expander(
            f"Etapa {int(etapa['orden'])} — {etapa['nombre']}  "
            f"| EVA ≤ {int(etapa['eva_max'])} · Confianza ≥ {int(etapa['confianza_min'])}"
        ):
            if etapa.get("descripcion"):
                st.caption(etapa["descripcion"])

            if drills.empty:
                st.info("Sin drills configurados para esta etapa.")
            else:
                for _, drill in drills.iterrows():
                    col_d, col_btn_d = st.columns([5, 1])
                    with col_d:
                        st.markdown(f"- **{drill['nombre']}**")
                        if drill.get("descripcion"):
                            st.caption(f"  {drill['descripcion']}")
                    with col_btn_d:
                        if st.button(
                            "🗑 Quitar",
                            key=f"del_drill_{drill['id']}",
                            help="Desactivar drill (no se borra de la DB)",
                        ):
                            desactivar_drill(int(drill["id"]))
                            st.success(f"Drill '{drill['nombre']}' desactivado.")
                            st.rerun()

            st.divider()

            # Formulario para agregar drill nuevo
            col_add1, col_add2, col_add3 = st.columns([2, 2, 1])
            with col_add1:
                nuevo_nombre = st.text_input(
                    "Nombre del nuevo drill",
                    key=f"new_drill_nom_{etapa['id']}",
                )
            with col_add2:
                nueva_desc = st.text_input(
                    "Descripción (opcional)",
                    key=f"new_drill_desc_{etapa['id']}",
                )
            with col_add3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button(
                    "➕ Agregar",
                    key=f"btn_add_drill_{etapa['id']}",
                    use_container_width=True,
                ):
                    if nuevo_nombre:
                        insertar_drill(int(etapa["id"]), nuevo_nombre, nueva_desc)
                        st.success(f"Drill '{nuevo_nombre}' agregado a Etapa {int(etapa['orden'])}.")
                        st.rerun()
                    else:
                        st.warning("Escribí el nombre del drill.")


# ============================================================
# PIE DE PÁGINA
# ============================================================

st.divider()
st.caption(
    "🏥 Módulo RTP · EQUIPOPHYSICAL · "
    "EVA: escala visual analógica 0-10 · "
    "Confianza: percepción de seguridad en la zona lesionada 0-10"
)
