"""
pages/Carga_GPS.py
===================
Módulo de carga externa (datos GPS). Dos formas de cargar datos:

  Tab 1 — Importar CSV KSport: sube el export del GPS (separado por ';').
          El plantel de la base es simulado (nombres inventados) pero el
          CSV trae nombres reales, así que el matcheo de jugador usa:
            1. Mapeo guardado de importaciones anteriores (exacto).
            2. Fuzzy matching por apellido (thefuzz), sin importar el
               orden nombre/apellido ni tildes o mayúsculas.
            3. Si no hay match confiable, lo elige el preparador a mano
               en la previsualización — y esa corrección se guarda para
               la próxima vez.
          La fila "Team Average" que trae KSport se ignora sola.

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
from thefuzz import fuzz

from metricas import cargar_jugadores, cargar_carga_externa
import auth
from styles import apply_styles

# Umbral de confianza (0-100) del fuzzy matching por apellido.
# Por debajo de esto, el jugador queda "sin match" y se pide corrección manual.
UMBRAL_FUZZY_APELLIDO = 80


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
#
# Orden de prioridad:
#   1. Mapeo guardado (csv_player_mapping) — importaciones anteriores
#      donde el preparador ya corrigió este mismo nombre a mano.
#   2. Fuzzy matching por apellido (thefuzz) — el CSV de KSport trae
#      nombres reales ("Benítez", "Fernández") que no coinciden con el
#      plantel simulado, así que comparamos cada palabra del nombre
#      contra el apellido de cada jugador, con similitud aproximada.
#   3. Sin match → lo resuelve el preparador a mano en la previsualización.
# ============================================================

def _normalizar_texto(s):
    """minúsculas, sin tildes, sin espacios de más — para comparar nombres."""
    s = str(s).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _es_team_average(nombre_csv):
    """KSport agrega una fila de resumen del equipo que hay que ignorar."""
    objetivo = _normalizar_texto(nombre_csv)
    return "average" in objetivo or objetivo in ("team", "total", "")


def _matchear_por_apellido(nombre_csv, jugadores_df, umbral=UMBRAL_FUZZY_APELLIDO):
    """
    Fuzzy matching por apellido usando thefuzz. Prueba CADA palabra del
    nombre del CSV (no solo la última) contra el apellido de cada
    jugador del plantel, así funciona sin importar si KSport exporta
    "Nombre Apellido", "Apellido Nombre" o "Apellido, Nombre".
    Retorna (jugador_id o None, confianza 0-100). Si el mejor puntaje
    queda por debajo del umbral, retorna jugador_id=None pero igual
    informa el puntaje del candidato más cercano (para mostrarlo en la
    previsualización como referencia).
    """
    palabras_csv = [p.strip(",.") for p in _normalizar_texto(nombre_csv).split()]
    palabras_csv = [p for p in palabras_csv if p]
    if not palabras_csv:
        return None, 0

    mejor_id, mejor_score = None, 0
    for _, jug in jugadores_df.iterrows():
        apellido_jug = _normalizar_texto(jug["apellido"])
        for palabra in palabras_csv:
            score = fuzz.ratio(palabra, apellido_jug)
            if score > mejor_score:
                mejor_score, mejor_id = score, int(jug["id"])

    if mejor_score >= umbral:
        return mejor_id, mejor_score
    return None, mejor_score


def cargar_mapeo_csv():
    """Carga el mapeo nombre_csv → jugador_id aprendido en importaciones anteriores."""
    conn = _conectar()
    try:
        df = pd.read_sql("SELECT nombre_csv, jugador_id FROM csv_player_mapping", conn)
    except Exception:
        df = pd.DataFrame(columns=["nombre_csv", "jugador_id"])
    conn.close()
    return df


def guardar_mapeo_csv(nombre_csv_original, jugador_id):
    """
    Guarda (o actualiza) el mapeo nombre_csv → jugador_id para que la
    próxima importación de KSport con ese mismo nombre matchee sola.
    """
    conn = _conectar()
    nombre_normalizado = _normalizar_texto(nombre_csv_original)
    conn.execute("""
        INSERT INTO csv_player_mapping (nombre_csv, nombre_csv_original, jugador_id, fecha_actualizacion)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(nombre_csv) DO UPDATE SET
            jugador_id = excluded.jugador_id,
            fecha_actualizacion = excluded.fecha_actualizacion
    """, (nombre_normalizado, nombre_csv_original, jugador_id))
    conn.commit()
    conn.close()


def _resolver_match(nombre_csv, jugadores_df, mapeo_dict):
    """
    Resuelve el jugador_id de un nombre del CSV siguiendo el orden de
    prioridad: mapeo guardado → fuzzy por apellido → sin match.
    Retorna (jugador_id o None, confianza 0-100, origen).
    origen: "mapeo" | "apellido" | "sin_match"
    """
    nombre_normalizado = _normalizar_texto(nombre_csv)

    if nombre_normalizado in mapeo_dict:
        return mapeo_dict[nombre_normalizado], 100, "mapeo"

    jug_id, score = _matchear_por_apellido(nombre_csv, jugadores_df)
    if jug_id is not None:
        return jug_id, score, "apellido"

    return None, score, "sin_match"


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

_COLOR_ESTADO = {
    # estado: (color de texto/borde, color de fondo)
    "automatico": ("#1a9e5c", "rgba(26,158,92,0.15)"),
    "manual":     ("#e8a020", "rgba(232,160,32,0.15)"),
    "sin_match":  ("#d63031", "rgba(214,48,49,0.15)"),
}

_ETIQUETA_ORIGEN = {
    "mapeo":     "mapeo guardado",
    "apellido":  "apellido",
    "sin_match": "sin match",
}


def _badge_estado(texto, estado):
    color, fondo = _COLOR_ESTADO.get(estado, ("#888888", "rgba(136,136,136,0.15)"))
    return (
        f'<div style="background:{fondo}; border-left:3px solid {color}; '
        f'color:{color}; padding:5px 10px; border-radius:0 4px 4px 0; '
        f'font-weight:600; font-size:0.85rem;">{texto}</div>'
    )


with tab_csv:
    st.markdown('<div class="ep-section-title">Importar sesión desde CSV</div>', unsafe_allow_html=True)
    st.caption(
        "El archivo debe venir separado por punto y coma (;), tal como lo exporta KSport. "
        "Los decimales se leen con coma (formato europeo). La fila 'Team Average' se ignora sola."
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
        else:
            df_csv = df_csv.rename(columns=MAPEO_COLUMNAS_KSPORT)

            # Ignorar la fila de resumen "Team Average" que trae KSport
            df_csv = df_csv[~df_csv["player_csv"].apply(_es_team_average)].reset_index(drop=True)

            if df_csv.empty:
                st.warning("El archivo no tiene filas de jugadores (solo la fila de resumen del equipo, si la tenía).")
            else:
                id_a_nombre = {
                    int(row["id"]): f"#{int(row['numero'])} {row['jugador']}"
                    for _, row in jugadores_df.iterrows()
                }
                nombre_a_id = {v: k for k, v in id_a_nombre.items()}
                opciones_nombres = ["(sin match)"] + sorted(id_a_nombre.values())

                # Identificador del archivo subido, para saber si es uno nuevo
                # (si es el mismo, no queremos pisar las correcciones manuales
                # que el preparador ya hizo en esta sesión).
                id_archivo = f"{archivo.name}_{archivo.size}"

                if st.session_state.get("gps_archivo_id") != id_archivo:
                    mapeo_df = cargar_mapeo_csv()
                    mapeo_dict = dict(zip(mapeo_df["nombre_csv"], mapeo_df["jugador_id"]))

                    matches = []
                    for idx, fila_csv in df_csv.iterrows():
                        nombre_csv = fila_csv["player_csv"]
                        jug_id, score, origen = _resolver_match(nombre_csv, jugadores_df, mapeo_dict)
                        matches.append({
                            "idx_csv": idx,
                            "nombre_csv": nombre_csv,
                            "jugador_id": jug_id,
                            "score": score,
                            "estado": "sin_match" if jug_id is None else "automatico",
                            "origen": origen,
                        })

                    st.session_state["gps_matches"] = matches
                    st.session_state["gps_archivo_id"] = id_archivo

                matches = st.session_state["gps_matches"]

                n_auto = sum(1 for m in matches if m["estado"] == "automatico")
                n_sin_match = sum(1 for m in matches if m["estado"] == "sin_match")
                st.info(
                    f"{len(matches)} jugador(es) en el CSV — {n_auto} matcheados automáticamente, "
                    f"{n_sin_match} necesitan corrección manual."
                )

                st.markdown("**Revisión antes de importar** — corregí el jugador si el match automático está mal:")

                enc = st.columns([2.2, 2.2, 1, 2.2])
                enc[0].markdown("**Nombre en CSV**")
                enc[1].markdown("**Jugador matcheado**")
                enc[2].markdown("**Confianza**")
                enc[3].markdown("**Corregir**")

                for i, m in enumerate(matches):
                    c1, c2, c3, c4 = st.columns([2.2, 2.2, 1, 2.2])
                    c1.write(m["nombre_csv"])

                    nombre_actual = id_a_nombre.get(m["jugador_id"], "(sin match)")
                    texto_badge = nombre_actual if m["jugador_id"] is not None else "Sin match"
                    if m["estado"] == "automatico":
                        texto_badge += f" · {_ETIQUETA_ORIGEN[m['origen']]}"
                    c2.markdown(_badge_estado(texto_badge, m["estado"]), unsafe_allow_html=True)

                    c3.write(f"{m['score']}%")

                    indice_actual = (
                        opciones_nombres.index(nombre_actual) if nombre_actual in opciones_nombres else 0
                    )
                    opcion_elegida = c4.selectbox(
                        " ", opciones_nombres, index=indice_actual,
                        key=f"sel_match_gps_{i}", label_visibility="collapsed",
                    )
                    id_elegido = nombre_a_id.get(opcion_elegida)

                    if id_elegido != m["jugador_id"]:
                        # El preparador corrigió (o completó) el match a mano
                        matches[i]["jugador_id"] = id_elegido
                        matches[i]["estado"] = "sin_match" if id_elegido is None else "manual"
                        matches[i]["score"] = 100 if id_elegido is not None else m["score"]

                st.session_state["gps_matches"] = matches

                n_sin_match_final = sum(1 for m in matches if m["jugador_id"] is None)

                if st.button("Importar sesión", type="primary", use_container_width=True):
                    filas_validas = [m for m in matches if m["jugador_id"] is not None]

                    if not filas_validas:
                        st.error("Ningún jugador quedó matcheado. Revisá la columna 'Corregir'.")
                    else:
                        filas_finales = []
                        n_mapeos_guardados = 0
                        for m in filas_validas:
                            fila_original = df_csv.loc[m["idx_csv"]]
                            datos = {c: fila_original.get(c) for c in COLUMNAS_METRICAS_KSPORT}
                            datos["jugador_id"] = m["jugador_id"]
                            datos["jugador_csv"] = m["nombre_csv"]
                            filas_finales.append(datos)

                            # Solo se guarda el mapeo cuando el preparador corrigió
                            # el match a mano — el automático no hace falta guardarlo.
                            if m["estado"] == "manual":
                                guardar_mapeo_csv(m["nombre_csv"], m["jugador_id"])
                                n_mapeos_guardados += 1

                        n_guardados = guardar_carga_externa(
                            pd.DataFrame(filas_finales), str(fecha_import), tipo_import, "csv_ksport"
                        )
                        st.cache_data.clear()

                        # Limpiar el estado para permitir una nueva importación limpia
                        del st.session_state["gps_matches"]
                        del st.session_state["gps_archivo_id"]

                        st.success(
                            f"{n_guardados} jugador(es) importados correctamente para el "
                            f"{fecha_import.strftime('%d/%m/%Y')}."
                        )
                        if n_mapeos_guardados:
                            st.caption(
                                f"Se guardaron {n_mapeos_guardados} corrección(es) de nombre — "
                                "la próxima vez van a matchear solas."
                            )
                        if n_sin_match_final:
                            st.warning(
                                f"{n_sin_match_final} jugador(es) del CSV quedaron sin importar por falta de match."
                            )
                        st.rerun()


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
