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
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
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

        fig_rm = go.Figure()

        # Línea de evolución del 1RM
        fig_rm.add_trace(go.Scatter(
            x=tendencia["fecha"],
            y=tendencia["rm_estimado"],
            mode="lines+markers",
            name="1RM estimado",
            line=dict(color="#1f77b4", width=2.5),
            marker=dict(size=8, color="#1f77b4"),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "1RM estimado: <b>%{y:.1f} kg</b><extra></extra>"
            ),
        ))

        # Línea de carga real utilizada
        fig_rm.add_trace(go.Scatter(
            x=tendencia["fecha"],
            y=tendencia["carga_kg"],
            mode="lines+markers",
            name="Carga utilizada",
            line=dict(color="#2ca02c", width=1.8, dash="dot"),
            marker=dict(size=6, color="#2ca02c"),
            hovertemplate=(
                "Carga: <b>%{y:.1f} kg</b><extra></extra>"
            ),
        ))

        fig_rm.update_layout(
            xaxis_title="",
            yaxis_title="Kilogramos (kg)",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=350,
            hovermode="x unified",
            xaxis=dict(tickformat="%d/%m"),
            legend=dict(orientation="h", y=-0.2, title=""),
            margin=dict(t=20, b=20, l=50, r=20),
        )

        st.plotly_chart(fig_rm, use_container_width=True)

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

        fig_vol = px.bar(
            vol_graf,
            x="semana",
            y="volumen_total_kg",
            color="ejercicio" if filtro_vol != "Todos" else None,
            text=vol_graf["volumen_total_kg"].apply(lambda x: f"{x:,.0f}"),
            labels={
                "semana":           "Semana",
                "volumen_total_kg": "Volumen (kg)",
                "ejercicio":        "Ejercicio",
            },
            title=f"Volumen semanal — {'Todos los ejercicios' if filtro_vol == 'Todos' else filtro_vol}",
            color_discrete_sequence=px.colors.qualitative.Safe,
        )
        fig_vol.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=340,
            xaxis=dict(tickformat="%d/%m"),
            xaxis_title="",
            legend=dict(orientation="h", y=-0.25, title=""),
            margin=dict(t=40, b=20, l=50, r=20),
        )
        fig_vol.update_traces(textposition="outside")
        st.plotly_chart(fig_vol, use_container_width=True)

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
            # Colorear según posición
            colores_pos = {
                "portero":       "#636EFA",
                "defensor":      "#00CC96",
                "mediocampista": "#EF553B",
                "delantero":     "#FFA15A",
            }

            fig_comp = px.bar(
                df_comp,
                x="rm_estimado",
                y="jugador",
                color="posicion",
                color_discrete_map=colores_pos,
                orientation="h",
                text=df_comp["rm_estimado"].apply(lambda x: f"{x:.1f} kg"),
                labels={
                    "rm_estimado": "1RM estimado (kg)",
                    "jugador":     "",
                    "posicion":    "Posición",
                },
                title=f"1RM estimado por jugador — {ejercicio_comp}",
            )

            # Línea vertical del promedio del equipo
            prom_equipo = df_comp["rm_estimado"].mean()
            fig_comp.add_vline(
                x=prom_equipo,
                line_dash="dash",
                line_color="#888",
                annotation_text=f"Prom. equipo: {prom_equipo:.1f} kg",
                annotation_position="top right",
                annotation_font=dict(size=11, color="#555"),
            )

            fig_comp.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=max(400, len(df_comp) * 28),
                xaxis_title="1RM estimado (kg)",
                legend=dict(orientation="h", y=-0.15, title=""),
                margin=dict(t=50, b=20, l=160, r=80),
            )
            fig_comp.update_traces(textposition="outside")
            st.plotly_chart(fig_comp, use_container_width=True)


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
