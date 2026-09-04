"""
pages/Carga_GPS.py
===================
Módulo de carga externa (datos GPS). Dos formas de cargar datos:

  Tab 1 — Importar CSV KSport: sube el export del GPS (separado por ';'),
          matchea automáticamente el nombre de cada jugador contra el
          plantel, muestra una previsualización editable (por si algún
          match automático está mal) y guarda todo al confirmar.

  Tab 2 — Carga manual: formulario con las métricas core, para los días
          en que no hay datos de GPS disponibles.

Métricas derivadas (se calculan solas al guardar, no vienen del CSV):
  distancia_relativa         = Distance / Minutes
  ratio_hsr                  = D_SHI / Distance × 100
  indice_carga_neuromuscular = (Num Acc HI + Num Dec HI) / Minutes
  imbalance_flag             = 1 si |Imbalance| > 10 %
"""

import sys
import os
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import sqlite3
from datetime import date

from metricas import cargar_jugadores, cargar_carga_externa
import auth
from styles import apply_styles


# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Carga GPS",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_styles()

auth.exigir_acceso("Carga_GPS")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer    {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
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
# MAPEO DE COLUMNAS DEL CSV DE KSPORT
# Nombres exactos tal como los exporta KSport (separador ';')
# → nombre de columna interno en la tabla carga_externa.
# ============================================================

MAPEO_COLUMNAS_KSPORT = {
    "Player":         "player_csv",
    "Minutes":        "minutes",
    "Distance":       "distance",
    "Drel":           "drel",
    "D_SHI":          "d_shi",
    "D_20-25 km/h":   "d_20_25_kmh",
    "D >25 km/h":     "d_25_kmh",
    "D_>30 km/h":     "d_30_kmh",
    "SMax (kmh)":     "smax_kmh",
    "D_AccHI":        "d_acchi",
    "D_DecHI":        "d_dechi",
    "D ACC >4":       "d_acc_4",
    "D DEC >-4":      "d_dec_4",
    "DecHI_Index":    "dechi_index",
    "Dec>-4_Index":   "dec_4_index",
    "RPE":            "rpe",
    "UA":             "ua",
    "D MP <20 w/kg":  "d_mp_20wkg",
    "D_MPHI":         "d_mphi",
    "D_MP >55":       "d_mp_55",
    "Num Sprint":     "num_sprint",
    "Amax":           "amax",
    "Num Acc HI":     "num_acc_hi",
    "Num Dec HI":     "num_dec_hi",
    "Num Acc >4":     "num_acc_4",
    "Num Dec >-4":    "num_dec_4",
    "EEE Kcal":       "eee_kcal",
    "EEE AI Kcal":    "eee_ai_kcal",
    "Imbalance":      "imbalance",
}

# Todas las columnas numéricas de KSport (sin "Player")
COLUMNAS_METRICAS_KSPORT = [v for k, v in MAPEO_COLUMNAS_KSPORT.items() if k != "Player"]


# ============================================================
# MATCHEO AUTOMÁTICO DE JUGADOR (nombre del CSV → plantel)
# ============================================================

def _normalizar_texto(s):
    """minúsculas, sin tildes, sin espacios de más — para comparar nombres."""
    s = str(s).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _matchear_jugador(nombre_csv, jugadores_df):
    """
    Compara el nombre tal como viene en el CSV contra "nombre apellido"
    de cada jugador del plantel (sin importar tildes, mayúsculas ni el
    orden de las palabras). Retorna (jugador_id o None, confianza 0-100).
    """
    objetivo = _normalizar_texto(nombre_csv)
    palabras_objetivo = set(objetivo.split())
    if not palabras_objetivo:
        return None, 0

    mejor_id, mejor_score = None, 0
    for _, jug in jugadores_df.iterrows():
        nombre_completo = _normalizar_texto(f"{jug['nombre']} {jug['apellido']}")
        if objetivo == nombre_completo:
            return int(jug["id"]), 100

        palabras_jugador = set(nombre_completo.split())
        interseccion = palabras_objetivo & palabras_jugador
        score = round(len(interseccion) / max(len(palabras_objetivo), len(palabras_jugador)) * 100)
        if score > mejor_score:
            mejor_score, mejor_id = score, int(jug["id"])

    return mejor_id, mejor_score


# ============================================================
# GUARDAR EN carga_externa (calcula las métricas derivadas)
# ============================================================

def guardar_carga_externa(filas, fecha_str, tipo_sesion, origen):
    """
    Guarda o sobreescribe (INSERT OR REPLACE) los registros de carga
    externa para la fecha indicada. `filas` es un DataFrame con una fila
    por jugador: columna 'jugador_id' obligatoria, el resto de las
    columnas de COLUMNAS_METRICAS_KSPORT son opcionales (si faltan,
    quedan NULL — es lo esperado en la carga manual, que solo llena
    las métricas core).
    """
    conn = _conectar()
    cur = conn.cursor()

    registros = []
    for _, fila in filas.iterrows():
        valores = {}
        for col in COLUMNAS_METRICAS_KSPORT:
            v = fila.get(col)
            valores[col] = float(v) if pd.notna(v) else None

        minutes    = valores["minutes"]
        distance   = valores["distance"]
        d_shi      = valores["d_shi"]
        num_acc_hi = valores["num_acc_hi"]
        num_dec_hi = valores["num_dec_hi"]
        imbalance  = valores["imbalance"]

        # ── Métricas derivadas ──────────────────────────────
        distancia_relativa = round(distance / minutes, 1) if minutes else None
        ratio_hsr = round(d_shi / distance * 100, 2) if distance and d_shi is not None else None
        indice_carga_neuromuscular = (
            round((num_acc_hi + num_dec_hi) / minutes, 2)
            if minutes and num_acc_hi is not None and num_dec_hi is not None
            else None
        )
        imbalance_flag = 1 if (imbalance is not None and abs(imbalance) > 10) else 0

        jugador_csv = fila.get("jugador_csv")

        registros.append((
            int(fila["jugador_id"]), fecha_str, tipo_sesion, origen,
            str(jugador_csv) if jugador_csv not in (None, "") else None,
            *[valores[c] for c in COLUMNAS_METRICAS_KSPORT],
            distancia_relativa, ratio_hsr, indice_carga_neuromuscular, imbalance_flag,
        ))

    columnas_sql = ", ".join(COLUMNAS_METRICAS_KSPORT)
    placeholders = ", ".join(["?"] * (5 + len(COLUMNAS_METRICAS_KSPORT) + 4))

    cur.executemany(f"""
        INSERT OR REPLACE INTO carga_externa
            (jugador_id, fecha, tipo_sesion, origen, jugador_csv,
             {columnas_sql},
             distancia_relativa, ratio_hsr, indice_carga_neuromuscular, imbalance_flag)
        VALUES ({placeholders})
    """, registros)

    conn.commit()
    conn.close()
    return len(registros)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Carga GPS")
    if st.button("Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Sistema de Monitoreo de Rendimiento\nEQUIPOPHYSICAL")


# ============================================================
# HEADER
# ============================================================

st.markdown('<div class="ep-badge ep-badge-performance">Performance</div>', unsafe_allow_html=True)
st.markdown('<div class="ep-section-title" style="font-size:1.4rem;">Carga Externa — GPS</div>', unsafe_allow_html=True)
st.caption("Importá el export de KSport o cargá las métricas core a mano cuando no haya GPS disponible.")
st.divider()

jugadores_df = cargar_jugadores()

tab_csv, tab_manual = st.tabs(["Importar CSV KSport", "Carga manual"])


# ============================================================
# TAB 1 — IMPORTAR CSV KSPORT
# ============================================================

with tab_csv:
    st.markdown('<div class="ep-section-title">Importar sesión desde CSV</div>', unsafe_allow_html=True)
    st.caption(
        "El archivo debe venir separado por punto y coma (;), tal como lo exporta KSport. "
        "Los decimales se leen con coma (formato europeo)."
    )

    col_fecha, col_tipo = st.columns([1, 2])
    with col_fecha:
        fecha_import = st.date_input("Fecha de la sesión", value=date.today(), key="fecha_gps_csv")
    with col_tipo:
        tipo_import = st.radio(
            "Tipo de sesión", ["entrenamiento", "partido"],
            horizontal=True, key="tipo_gps_csv",
        )

    archivo = st.file_uploader("Subir CSV de KSport", type=["csv"], key="uploader_gps")

    if archivo is not None:
        try:
            df_csv = pd.read_csv(archivo, sep=";", decimal=",", encoding="utf-8")
        except UnicodeDecodeError:
            archivo.seek(0)
            df_csv = pd.read_csv(archivo, sep=";", decimal=",", encoding="latin-1")

        df_csv.columns = [c.strip() for c in df_csv.columns]

        columnas_faltantes = [c for c in MAPEO_COLUMNAS_KSPORT if c not in df_csv.columns]
        if columnas_faltantes:
            st.error(
                "El CSV no tiene el formato esperado de KSport. Faltan estas columnas: "
                + ", ".join(columnas_faltantes)
            )
        elif df_csv.empty:
            st.warning("El archivo no tiene filas de datos.")
        else:
            df_csv = df_csv.rename(columns=MAPEO_COLUMNAS_KSPORT)

            # ── Matcheo automático + previsualización editable ──────
            id_a_nombre = {
                int(row["id"]): f"#{int(row['numero'])} {row['jugador']}"
                for _, row in jugadores_df.iterrows()
            }
            nombre_a_id = {v: k for k, v in id_a_nombre.items()}
            opciones_nombres = ["(sin match)"] + sorted(id_a_nombre.values())

            filas_preview = []
            for idx, fila_csv in df_csv.iterrows():
                jug_id, score = _matchear_jugador(fila_csv["player_csv"], jugadores_df)
                nombre_sugerido = id_a_nombre.get(jug_id, "(sin match)") if score >= 60 else "(sin match)"
                filas_preview.append({
                    "idx_csv":          idx,
                    "Jugador CSV":      fila_csv["player_csv"],
                    "Jugador plantel":  nombre_sugerido,
                    "Confianza %":      score,
                    "Minutos":          fila_csv.get("minutes"),
                    "Distancia (m)":    fila_csv.get("distance"),
                    "D_SHI (m)":        fila_csv.get("d_shi"),
                    "RPE":              fila_csv.get("rpe"),
                    "Imbalance (%)":    fila_csv.get("imbalance"),
                })

            preview_df = pd.DataFrame(filas_preview)
            n_sin_match = int((preview_df["Jugador plantel"] == "(sin match)").sum())

            if n_sin_match:
                st.warning(
                    f"{n_sin_match} jugador(es) del CSV no se pudieron matchear automáticamente. "
                    "Corregilos en la columna 'Jugador plantel' antes de importar."
                )
            else:
                st.success(f"Los {len(preview_df)} jugadores del CSV se matchearon automáticamente con el plantel.")

            st.markdown("**Revisión antes de importar** — corregí el jugador si el match automático está mal:")

            preview_editado = st.data_editor(
                preview_df,
                column_config={
                    "Jugador CSV":     st.column_config.TextColumn(disabled=True),
                    "Jugador plantel": st.column_config.SelectboxColumn(options=opciones_nombres, required=True),
                    "Confianza %":     st.column_config.NumberColumn(disabled=True),
                    "Minutos":         st.column_config.NumberColumn(disabled=True, format="%.0f"),
                    "Distancia (m)":   st.column_config.NumberColumn(disabled=True, format="%.0f"),
                    "D_SHI (m)":       st.column_config.NumberColumn(disabled=True, format="%.0f"),
                    "RPE":             st.column_config.NumberColumn(disabled=True, format="%.1f"),
                    "Imbalance (%)":   st.column_config.NumberColumn(disabled=True, format="%.1f"),
                },
                column_order=["Jugador CSV", "Jugador plantel", "Confianza %",
                              "Minutos", "Distancia (m)", "D_SHI (m)", "RPE", "Imbalance (%)"],
                hide_index=True,
                width="stretch",
                key="editor_preview_gps",
            )

            if st.button("Importar sesión", type="primary", use_container_width=True):
                filas_validas = preview_editado[preview_editado["Jugador plantel"] != "(sin match)"]
                n_invalidas = len(preview_editado) - len(filas_validas)

                if filas_validas.empty:
                    st.error("Ningún jugador quedó matcheado. Revisá la columna 'Jugador plantel'.")
                else:
                    filas_finales = []
                    for _, fila_prev in filas_validas.iterrows():
                        fila_original = df_csv.loc[fila_prev["idx_csv"]]
                        datos = {c: fila_original.get(c) for c in COLUMNAS_METRICAS_KSPORT}
                        datos["jugador_id"] = nombre_a_id[fila_prev["Jugador plantel"]]
                        datos["jugador_csv"] = fila_prev["Jugador CSV"]
                        filas_finales.append(datos)

                    n_guardados = guardar_carga_externa(
                        pd.DataFrame(filas_finales), str(fecha_import), tipo_import, "csv_ksport"
                    )
                    st.cache_data.clear()
                    st.success(
                        f"{n_guardados} jugador(es) importados correctamente para el "
                        f"{fecha_import.strftime('%d/%m/%Y')}."
                    )
                    if n_invalidas:
                        st.warning(f"{n_invalidas} jugador(es) del CSV quedaron sin importar por falta de match.")


# ============================================================
# TAB 2 — CARGA MANUAL
# ============================================================

with tab_manual:
    st.markdown('<div class="ep-section-title">Carga manual — métricas core</div>', unsafe_allow_html=True)
    st.caption("Para los días en que no hay datos de GPS disponibles.")

    opciones_manual = {
        f"#{int(row['numero'])} {row['jugador']} ({row['posicion']})": int(row["id"])
        for _, row in jugadores_df.sort_values(["posicion", "numero"]).iterrows()
    }

    col_jug, col_fecha_m = st.columns(2)
    with col_jug:
        jugador_sel_nombre = st.selectbox("Jugador", list(opciones_manual.keys()), key="jugador_manual_gps")
    with col_fecha_m:
        fecha_manual = st.date_input("Fecha", value=date.today(), key="fecha_gps_manual")

    tipo_manual = st.radio(
        "Tipo de sesión", ["entrenamiento", "partido"],
        horizontal=True, key="tipo_gps_manual",
    )

    with st.form("form_carga_manual_gps"):
        c1, c2, c3 = st.columns(3)
        minutos_m    = c1.number_input("Minutos", min_value=0.0, step=1.0)
        distancia_m  = c2.number_input("Distancia total (m)", min_value=0.0, step=10.0)
        d_shi_m      = c3.number_input("D_SHI — alta intensidad (m)", min_value=0.0, step=10.0)

        c4, c5, c6 = st.columns(3)
        smax_m       = c4.number_input("Velocidad máxima (km/h)", min_value=0.0, step=0.1)
        num_sprint_m = c5.number_input("Cantidad de sprints", min_value=0.0, step=1.0)
        imbalance_m  = c6.number_input("Imbalance (%)", step=0.1, help="Puede ser negativo (lado dominante).")

        c7, c8 = st.columns(2)
        rpe_m = c7.number_input("RPE de la sesión (0-10)", min_value=0.0, max_value=10.0, step=1.0)
        ua_m  = c8.number_input("UA (RPE × minutos)", min_value=0.0, step=10.0)

        guardar_manual = st.form_submit_button("Guardar carga manual", type="primary", use_container_width=True)

    if guardar_manual:
        jugador_id_manual = opciones_manual[jugador_sel_nombre]
        fila_manual = pd.DataFrame([{
            "jugador_id": jugador_id_manual,
            "minutes":    minutos_m    if minutos_m    > 0 else None,
            "distance":   distancia_m  if distancia_m  > 0 else None,
            "d_shi":      d_shi_m      if d_shi_m      > 0 else None,
            "smax_kmh":   smax_m       if smax_m       > 0 else None,
            "num_sprint": num_sprint_m if num_sprint_m > 0 else None,
            "imbalance":  imbalance_m,
            "rpe":        rpe_m        if rpe_m        > 0 else None,
            "ua":         ua_m         if ua_m         > 0 else None,
        }])

        guardar_carga_externa(fila_manual, str(fecha_manual), tipo_manual, "manual")
        st.cache_data.clear()
        st.success(
            f"Carga manual guardada para {jugador_sel_nombre} — {fecha_manual.strftime('%d/%m/%Y')}."
        )
