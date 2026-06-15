"""
metricas.py
===========
Motor de cálculo del sistema de monitoreo de rendimiento.

Funciones principales:
  calcular_acwr_ewma()       → ACWR diario por método EWMA para todo el plantel
  calcular_baseline_plantel()→ Baseline individual de carga y wellness
  calcular_alertas_hoy()     → Panel de alertas con prioridad roja/naranja/amarilla/verde
  reporte_disponibilidad()   → Resumen operativo diario del plantel
  evolucion_jugador()        → Historial de un jugador para gráficos

Cómo usar:
  python metricas.py          ← muestra un reporte de prueba en consola
"""

import sqlite3
import os
import numpy as np
import pandas as pd
from datetime import timedelta

# Ruta de la base de datos (mismo directorio que este script)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futbol_monitoreo.db")


# ============================================================
# UMBRALES PARA EL SISTEMA DE ALERTAS
# Basados en literatura científica de monitoreo de carga
# ============================================================

# ACWR (Acute:Chronic Workload Ratio)
ACWR_VERDE_MIN   = 0.8   # por debajo → riesgo de desentrenamiento
ACWR_VERDE_MAX   = 1.3   # zona óptima: 0.8 – 1.3
ACWR_NARANJA_MAX = 1.5   # zona de precaución: 1.3 – 1.5
                          # por encima de 1.5 → zona de alto riesgo

# Wellness total (escala 1-5, donde 5 = bienestar perfecto)
WELLNESS_ROJO    = 2.0   # < 2.0   → crítico
WELLNESS_NARANJA = 2.5   # 2.0–2.5 → bajo
WELLNESS_AMARILLO = 3.0  # 2.5–3.0 → moderado

# Caída de wellness respecto al baseline personal
WELLNESS_CAIDA_NARANJA = -1.0  # cayó ≥ 1.0 punto vs su promedio de 28 días


# ============================================================
# CARGA DE DATOS DESDE LA BASE DE DATOS
# ============================================================

def _conectar():
    """Abre y retorna una conexión a la base de datos."""
    return sqlite3.connect(DB_PATH)


def cargar_carga_interna():
    """
    Carga toda la tabla carga_interna con nombre del jugador y posición.
    Los días de descanso (training_load NULL) se reemplazan por 0.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            ci.jugador_id,
            j.nombre || ' ' || j.apellido  AS jugador,
            j.posicion,
            j.numero_camiseta               AS numero,
            ci.fecha,
            ci.tipo_sesion,
            ci.rpe,
            ci.minutos,
            COALESCE(ci.training_load, 0)   AS training_load
        FROM carga_interna ci
        JOIN jugadores j ON j.id = ci.jugador_id
        ORDER BY ci.jugador_id, ci.fecha
    """, conn, parse_dates=["fecha"])
    conn.close()
    return df


def cargar_wellness():
    """Carga toda la tabla wellness con nombre del jugador y posición."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            w.jugador_id,
            j.nombre || ' ' || j.apellido  AS jugador,
            j.posicion,
            w.fecha,
            w.fatiga,
            w.calidad_sueno,
            w.horas_sueno,
            w.dolor_muscular,
            w.humor,
            w.estres,
            w.wellness_total
        FROM wellness w
        JOIN jugadores j ON j.id = w.jugador_id
        ORDER BY w.jugador_id, w.fecha
    """, conn, parse_dates=["fecha"])
    conn.close()
    return df


def cargar_lesiones_activas():
    """
    Carga solo las lesiones activas (activo = 1).
    Estos jugadores NO están disponibles para entrenar ni competir.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            l.jugador_id,
            j.nombre || ' ' || j.apellido  AS jugador,
            j.posicion,
            l.fecha_inicio,
            l.fecha_fin,
            l.tipo_lesion,
            l.zona_corporal,
            l.dias_baja
        FROM lesiones l
        JOIN jugadores j ON j.id = l.jugador_id
        WHERE l.activo = 1
    """, conn)
    conn.close()
    return df


def cargar_jugadores():
    """Carga la lista completa del plantel."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, nombre, apellido,
               nombre || ' ' || apellido AS jugador,
               posicion, numero_camiseta AS numero
        FROM jugadores
        ORDER BY posicion, numero_camiseta
    """, conn)
    conn.close()
    return df


def cargar_carga_interna_fecha(fecha_str):
    """Carga los registros de carga interna de UNA fecha específica."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT jugador_id, tipo_sesion, rpe, minutos, training_load
        FROM carga_interna
        WHERE fecha = ?
    """, conn, params=[fecha_str])
    conn.close()
    return df


def cargar_lesiones_todas():
    """Carga el historial completo de lesiones (activas e inactivas)."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            l.id,
            l.jugador_id,
            j.nombre || ' ' || j.apellido AS jugador,
            j.posicion,
            l.fecha_inicio,
            l.fecha_fin,
            l.tipo_lesion,
            l.zona_corporal,
            l.dias_baja,
            l.activo
        FROM lesiones l
        JOIN jugadores j ON j.id = l.jugador_id
        ORDER BY l.activo DESC, l.fecha_inicio DESC
    """, conn)
    conn.close()
    return df


# ============================================================
# CÁLCULO DE ACWR POR MÉTODO EWMA
# ============================================================

def calcular_acwr_ewma(df_carga=None):
    """
    Calcula el ACWR diario para todos los jugadores usando EWMA.

    Fórmula EWMA:
      EWMA_t = λ × Carga_t + (1 - λ) × EWMA_(t-1)
      donde λ = 2 / (N + 1)

    - EWMA aguda   (span=7 días):  λ = 0.25
    - EWMA crónica (span=28 días): λ ≈ 0.069
    - ACWR = EWMA aguda / EWMA crónica

    Zonas de referencia:
      < 0.8           → desentrenamiento (amarillo)
      0.8 – 1.3       → zona óptima (verde)
      1.3 – 1.5       → precaución (naranja)
      > 1.5           → alto riesgo (rojo)

    Retorna DataFrame con columna 'acwr' y columnas de EWMA.
    """
    if df_carga is None:
        df_carga = cargar_carga_interna()

    grupos = []

    for jugador_id, grupo in df_carga.groupby("jugador_id"):
        g = grupo.sort_values("fecha").copy()

        # EWMA aguda (carga de los últimos ~7 días con decaimiento exponencial)
        g["ewma_aguda"] = (
            g["training_load"].ewm(span=7, min_periods=1).mean().round(1)
        )

        # EWMA crónica (carga de los últimos ~28 días con decaimiento exponencial)
        g["ewma_cronica"] = (
            g["training_load"].ewm(span=28, min_periods=1).mean().round(1)
        )

        # ACWR: evitar división por cero en los primeros días sin historia
        g["acwr"] = np.where(
            g["ewma_cronica"] > 0,
            (g["ewma_aguda"] / g["ewma_cronica"]).round(3),
            np.nan
        )

        grupos.append(g)

    return pd.concat(grupos, ignore_index=True)


def zona_acwr(acwr):
    """
    Clasifica un valor de ACWR en su zona de riesgo.
    Útil para colorear gráficos y tablas.
    """
    if pd.isna(acwr):
        return "sin datos"
    elif acwr < ACWR_VERDE_MIN:
        return "desentrenamiento"
    elif acwr <= ACWR_VERDE_MAX:
        return "optima"
    elif acwr <= ACWR_NARANJA_MAX:
        return "precaucion"
    else:
        return "alto_riesgo"


# ============================================================
# BASELINE INDIVIDUAL POR JUGADOR
# ============================================================

def calcular_baseline_plantel(df_carga=None, df_wellness=None):
    """
    Calcula el punto de referencia personal de cada jugador
    usando los últimos 28 días de datos.

    Incluye:
      carga_baseline_28d    → promedio de training_load (últimos 28 días)
      wellness_baseline_28d → promedio de wellness_total (últimos 28 días)
      wellness_hoy          → último valor registrado de wellness
      wellness_delta        → diferencia wellness_hoy vs baseline
                              (negativo = empeoró respecto a su promedio)
      ítems individuales de wellness del último día
    """
    if df_carga is None:
        df_carga = cargar_carga_interna()
    if df_wellness is None:
        df_wellness = cargar_wellness()

    fecha_max  = df_carga["fecha"].max()
    fecha_28d  = fecha_max - timedelta(days=27)  # ventana de 28 días inclusive

    # --- Baseline de carga ---
    carga_28 = (
        df_carga[df_carga["fecha"] >= fecha_28d]
        .groupby("jugador_id")["training_load"]
        .mean()
        .reset_index()
        .rename(columns={"training_load": "carga_baseline_28d"})
    )

    # --- Baseline de wellness ---
    wellness_28 = (
        df_wellness[df_wellness["fecha"] >= fecha_28d]
        .groupby("jugador_id")["wellness_total"]
        .mean()
        .reset_index()
        .rename(columns={"wellness_total": "wellness_baseline_28d"})
    )

    # --- Último registro de wellness (snapshot de hoy) ---
    cols_items = ["jugador_id", "fecha", "wellness_total",
                  "fatiga", "calidad_sueno", "horas_sueno",
                  "dolor_muscular", "humor", "estres"]

    wellness_ultimo = (
        df_wellness.sort_values("fecha")
        .groupby("jugador_id")
        .last()
        .reset_index()
        [cols_items]
        .rename(columns={"wellness_total": "wellness_hoy", "fecha": "fecha_wellness"})
    )

    # --- Unir todo ---
    baseline = (
        carga_28
        .merge(wellness_28,   on="jugador_id", how="left")
        .merge(wellness_ultimo, on="jugador_id", how="left")
    )

    # Cuánto cambió el wellness respecto a su propia línea base
    baseline["wellness_delta"] = (
        baseline["wellness_hoy"] - baseline["wellness_baseline_28d"]
    ).round(2)

    return baseline.round(2)


# ============================================================
# SISTEMA DE ALERTAS
# ============================================================

def _nivel_alerta(acwr, wellness_hoy, wellness_delta, lesionado):
    """
    Determina el nivel de alerta para UN jugador.

    Lógica por capas (la más grave gana):
      ROJA    → lesión activa  |  ACWR > 1.5  |  wellness < 2.0
      NARANJA → ACWR 1.3–1.5  |  wellness 2.0–2.5  |  caída ≥ 1.0 vs baseline
      AMARILLA→ ACWR < 0.8    |  wellness 2.5–3.0
      VERDE   → sin problemas
    """
    motivos = []

    # ── ALERTA ROJA ──────────────────────────────────────────
    if lesionado:
        motivos.append("Lesión activa")
    if pd.notna(acwr) and acwr > ACWR_NARANJA_MAX:
        motivos.append(f"ACWR muy alto ({acwr:.2f})")
    if pd.notna(wellness_hoy) and wellness_hoy < WELLNESS_ROJO:
        motivos.append(f"Wellness crítico ({wellness_hoy:.1f})")
    if motivos:
        return "ROJA", " | ".join(motivos)

    # ── ALERTA NARANJA ───────────────────────────────────────
    if pd.notna(acwr) and ACWR_VERDE_MAX < acwr <= ACWR_NARANJA_MAX:
        motivos.append(f"ACWR elevado ({acwr:.2f})")
    if pd.notna(wellness_hoy) and WELLNESS_ROJO <= wellness_hoy < WELLNESS_NARANJA:
        motivos.append(f"Wellness bajo ({wellness_hoy:.1f})")
    if pd.notna(wellness_delta) and wellness_delta <= WELLNESS_CAIDA_NARANJA:
        motivos.append(f"Caída de wellness ({wellness_delta:+.1f} pts vs baseline)")
    if motivos:
        return "NARANJA", " | ".join(motivos)

    # ── ALERTA AMARILLA ──────────────────────────────────────
    if pd.notna(acwr) and acwr < ACWR_VERDE_MIN:
        motivos.append(f"ACWR bajo, posible desentrenamiento ({acwr:.2f})")
    if pd.notna(wellness_hoy) and WELLNESS_NARANJA <= wellness_hoy < WELLNESS_AMARILLO:
        motivos.append(f"Wellness moderado ({wellness_hoy:.1f})")
    if motivos:
        return "AMARILLA", " | ".join(motivos)

    # ── VERDE ────────────────────────────────────────────────
    return "VERDE", "Sin alertas"


def calcular_alertas_hoy(fecha=None):
    """
    Genera el panel completo de alertas para todos los jugadores.
    Si no se indica fecha, usa el último día con datos disponibles.

    Retorna DataFrame con columnas:
      jugador, posicion, numero, tipo_sesion, training_load,
      acwr, ewma_aguda, ewma_cronica,
      wellness_hoy, wellness_baseline_28d, wellness_delta,
      fatiga, calidad_sueno, horas_sueno, dolor_muscular, humor, estres,
      alerta, motivo

    Orden: ROJA → NARANJA → AMARILLA → VERDE
    """
    df_carga    = cargar_carga_interna()
    df_wellness = cargar_wellness()
    df_lesiones = cargar_lesiones_activas()

    # Calcular ACWR para todo el historial
    df_acwr = calcular_acwr_ewma(df_carga)

    # Fecha de referencia
    if fecha is None:
        fecha_ref = df_acwr["fecha"].max()
    else:
        fecha_ref = pd.Timestamp(fecha)

    # ACWR del día específico (incluimos "fecha" para que esté disponible en panel)
    acwr_dia = (
        df_acwr[df_acwr["fecha"] == fecha_ref]
        [["jugador_id", "jugador", "posicion", "numero",
          "fecha", "tipo_sesion", "training_load",
          "ewma_aguda", "ewma_cronica", "acwr"]]
        .copy()
    )

    # Baseline con último wellness
    baseline = calcular_baseline_plantel(df_carga, df_wellness)

    # Set de IDs con lesión activa
    ids_lesionados = set(df_lesiones["jugador_id"].tolist())

    # Unir ACWR del día con baseline de wellness
    panel = acwr_dia.merge(baseline, on="jugador_id", how="left")

    # Asignar nivel de alerta a cada jugador
    niveles, motivos_lista = [], []
    for _, fila in panel.iterrows():
        nivel, motivo = _nivel_alerta(
            acwr          = fila.get("acwr"),
            wellness_hoy  = fila.get("wellness_hoy"),
            wellness_delta= fila.get("wellness_delta"),
            lesionado     = fila["jugador_id"] in ids_lesionados
        )
        niveles.append(nivel)
        motivos_lista.append(motivo)

    panel["alerta"] = niveles
    panel["motivo"] = motivos_lista

    # Ordenar por prioridad de alerta
    ORDEN = {"ROJA": 0, "NARANJA": 1, "AMARILLA": 2, "VERDE": 3}
    panel["_orden"] = panel["alerta"].map(ORDEN)
    panel = panel.sort_values("_orden").drop(columns="_orden")

    return panel.reset_index(drop=True)


# ============================================================
# REPORTE DIARIO DE DISPONIBILIDAD
# ============================================================

def reporte_disponibilidad(fecha=None):
    """
    Genera el reporte operativo diario del plantel.

    Retorna un diccionario con:
      resumen     → dict con conteos (total, disponibles, lesionados, alertas)
      disponibles → DataFrame de jugadores aptos con su nivel de alerta
      lesionados  → DataFrame de jugadores fuera con info de lesión
      fecha       → string formateado (DD/MM/YYYY)
    """
    panel     = calcular_alertas_hoy(fecha)
    lesiones  = cargar_lesiones_activas()

    ids_lesionados = set(lesiones["jugador_id"].tolist())

    disponibles = panel[~panel["jugador_id"].isin(ids_lesionados)].copy()
    lesionados  = panel[panel["jugador_id"].isin(ids_lesionados)].copy()

    # Agregar detalles de lesión a los no disponibles
    if not lesionados.empty and not lesiones.empty:
        lesionados = lesionados.merge(
            lesiones[["jugador_id", "tipo_lesion", "zona_corporal",
                       "fecha_inicio", "dias_baja"]],
            on="jugador_id", how="left"
        )

    fecha_str = panel["fecha"].iloc[0].strftime("%d/%m/%Y") if not panel.empty else "—"

    resumen = {
        "fecha"            : fecha_str,
        "total_plantel"    : len(panel),
        "disponibles"      : len(disponibles),
        "lesionados"       : len(lesionados),
        "alertas_rojas"    : int((disponibles["alerta"] == "ROJA").sum()),
        "alertas_naranja"  : int((disponibles["alerta"] == "NARANJA").sum()),
        "alertas_amarillas": int((disponibles["alerta"] == "AMARILLA").sum()),
        "sin_alertas"      : int((disponibles["alerta"] == "VERDE").sum()),
    }

    return {
        "resumen"    : resumen,
        "disponibles": disponibles,
        "lesionados" : lesionados,
        "fecha"      : fecha_str,
    }


# ============================================================
# HISTORIAL DE UN JUGADOR (para gráficos del dashboard)
# ============================================================

def evolucion_jugador(jugador_id):
    """
    Retorna el historial completo de carga y wellness para UN jugador.
    Incluye ACWR calculado día a día.
    Usado por los gráficos de evolución en el dashboard.
    """
    df_carga    = cargar_carga_interna()
    df_wellness = cargar_wellness()

    carga_j    = df_carga[df_carga["jugador_id"] == jugador_id].sort_values("fecha").copy()
    wellness_j = df_wellness[df_wellness["jugador_id"] == jugador_id].sort_values("fecha")

    # Calcular ACWR
    carga_j["ewma_aguda"]   = carga_j["training_load"].ewm(span=7,  min_periods=1).mean().round(1)
    carga_j["ewma_cronica"] = carga_j["training_load"].ewm(span=28, min_periods=1).mean().round(1)
    carga_j["acwr"] = np.where(
        carga_j["ewma_cronica"] > 0,
        (carga_j["ewma_aguda"] / carga_j["ewma_cronica"]).round(3),
        np.nan
    )

    # Unir con wellness
    evolucion = carga_j.merge(
        wellness_j[["jugador_id", "fecha", "wellness_total",
                    "fatiga", "calidad_sueno", "dolor_muscular",
                    "humor", "estres", "horas_sueno"]],
        on=["jugador_id", "fecha"],
        how="left"
    )

    return evolucion


# ============================================================
# RESUMEN ACWR DEL PLANTEL (para gráfico de semáforo grupal)
# ============================================================

def resumen_acwr_plantel():
    """
    Retorna el ACWR del último día disponible para todos los jugadores.
    Incluye la zona de riesgo ('optima', 'precaucion', 'alto_riesgo', etc.)
    Útil para el gráfico de semáforo grupal en el dashboard.
    """
    df_acwr = calcular_acwr_ewma()
    fecha_max = df_acwr["fecha"].max()

    ultimo = (
        df_acwr[df_acwr["fecha"] == fecha_max]
        [["jugador_id", "jugador", "posicion", "numero",
          "acwr", "ewma_aguda", "ewma_cronica"]]
        .copy()
    )

    ultimo["zona"] = ultimo["acwr"].apply(zona_acwr)
    return ultimo.sort_values("acwr", ascending=False).reset_index(drop=True)


# ============================================================
# FUNCIONES DE FUERZA Y GYM
# ============================================================

def cargar_fuerza_jugador(jugador_id):
    """
    Carga todas las sesiones de fuerza de UN jugador.
    Incluye nombre del jugador y posición.
    Retorna DataFrame ordenado por fecha.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            f.id,
            f.jugador_id,
            j.nombre || ' ' || j.apellido  AS jugador,
            j.posicion,
            f.fecha,
            f.ejercicio,
            f.series,
            f.repeticiones,
            f.carga_kg,
            f.rpe,
            f.rm_estimado,
            f.notas
        FROM fuerza f
        JOIN jugadores j ON j.id = f.jugador_id
        WHERE f.jugador_id = ?
        ORDER BY f.fecha, f.ejercicio
    """, conn, params=[jugador_id], parse_dates=["fecha"])
    conn.close()
    return df


def cargar_fuerza_plantel():
    """
    Carga todas las sesiones de fuerza del plantel completo.
    Útil para reportes grupales y comparativas.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            f.jugador_id,
            j.nombre || ' ' || j.apellido  AS jugador,
            j.posicion,
            f.fecha,
            f.ejercicio,
            f.series,
            f.repeticiones,
            f.carga_kg,
            f.rpe,
            f.rm_estimado
        FROM fuerza f
        JOIN jugadores j ON j.id = f.jugador_id
        ORDER BY f.fecha, f.jugador_id
    """, conn, parse_dates=["fecha"])
    conn.close()
    return df


def calcular_volumen_sesion(df_fuerza):
    """
    Calcula el volumen de entrenamiento por sesión (fecha) y por ejercicio.

    Fórmula:  Volumen = Series × Repeticiones × Carga (kg)
    También conocido como 'Tonnage' o 'Volumen de carga total'.

    Retorna el mismo DataFrame con la columna 'volumen_kg' agregada.
    """
    df = df_fuerza.copy()
    # Volumen = series × repeticiones × kg → unidades arbitrarias de carga total
    df["volumen_kg"] = df["series"] * df["repeticiones"] * df["carga_kg"]
    df["volumen_kg"] = df["volumen_kg"].round(1)
    return df


def tendencia_rm_por_ejercicio(jugador_id, ejercicio=None):
    """
    Calcula la evolución del 1RM estimado (fórmula de Epley) a lo largo del tiempo
    para un jugador. Permite filtrar por ejercicio específico.

    La fórmula de Epley estima el peso máximo que podría levantarse 1 sola vez:
      1RM ≈ carga × (1 + repeticiones / 30)

    Parámetros:
      jugador_id : int — ID del jugador
      ejercicio  : str o None — si se pasa, filtra solo ese ejercicio

    Retorna DataFrame con columnas: fecha, ejercicio, rm_estimado, carga_kg, rpe
    """
    df = cargar_fuerza_jugador(jugador_id)

    if df.empty:
        return df

    if ejercicio:
        df = df[df["ejercicio"] == ejercicio]

    # Tomar el RM máximo por fecha y ejercicio
    # (en una sesión puede haber varias series, tomamos el mejor intento del día)
    tendencia = (
        df.groupby(["fecha", "ejercicio"])
        .agg(
            rm_estimado = ("rm_estimado", "max"),
            carga_kg    = ("carga_kg",    "max"),
            rpe         = ("rpe",         "mean"),
        )
        .reset_index()
        .sort_values(["ejercicio", "fecha"])
    )
    tendencia["rpe"] = tendencia["rpe"].round(1)

    return tendencia


def resumen_volumen_semanal(jugador_id):
    """
    Agrupa el volumen de entrenamiento por semana y por ejercicio.

    Útil para monitorear progresión de la carga de fuerza semana a semana.
    Retorna DataFrame con: semana (fecha del lunes), ejercicio, volumen_total_kg,
    sesiones (días entrenados), series_total, reps_total.
    """
    df = cargar_fuerza_jugador(jugador_id)

    if df.empty:
        return df

    df = calcular_volumen_sesion(df)

    # Truncar la fecha al inicio de la semana (lunes)
    df["semana"] = df["fecha"].dt.to_period("W").dt.start_time

    resumen = (
        df.groupby(["semana", "ejercicio"])
        .agg(
            volumen_total_kg = ("volumen_kg",    "sum"),
            sesiones         = ("fecha",         "nunique"),
            series_total     = ("series",        "sum"),
            reps_total       = ("repeticiones",  "sum"),
            rm_max           = ("rm_estimado",   "max"),
        )
        .reset_index()
        .sort_values(["semana", "ejercicio"])
    )
    resumen["volumen_total_kg"] = resumen["volumen_total_kg"].round(1)

    return resumen


def snapshot_fuerza_plantel():
    """
    Para cada jugador y cada ejercicio, retorna el último RM estimado registrado.
    Permite comparar el nivel actual de fuerza en todo el plantel.

    Retorna DataFrame con: jugador, posicion, ejercicio, rm_estimado, fecha, carga_kg
    """
    df = cargar_fuerza_plantel()

    if df.empty:
        return df

    # Último registro por jugador y ejercicio
    ultimo = (
        df.sort_values("fecha")
        .groupby(["jugador_id", "jugador", "posicion", "ejercicio"])
        .last()
        .reset_index()
        [["jugador_id", "jugador", "posicion", "ejercicio",
          "fecha", "carga_kg", "rm_estimado", "rpe"]]
    )

    return ultimo.sort_values(["ejercicio", "rm_estimado"], ascending=[True, False])


# ============================================================
# FUNCIONES RTP (Return to Play)
# ============================================================

def cargar_etapas_rtp():
    """Carga las etapas del protocolo RTP ordenadas."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, orden, nombre, descripcion, eva_max, confianza_min, activa
        FROM rtp_etapas
        WHERE activa = 1
        ORDER BY orden
    """, conn)
    conn.close()
    return df


def cargar_drills_etapa(etapa_id):
    """Carga los drills activos de una etapa específica."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT id, nombre, descripcion
        FROM rtp_drills
        WHERE etapa_id = ? AND activo = 1
        ORDER BY id
    """, conn, params=[etapa_id])
    conn.close()
    return df


def cargar_sesiones_rtp_jugador(jugador_id):
    """
    Carga el historial completo de sesiones RTP de un jugador.
    Incluye el nombre de la etapa y el promedio de EVA y confianza de la sesión.
    """
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            s.id           AS sesion_id,
            s.fecha,
            s.etapa_id,
            e.orden        AS etapa_orden,
            e.nombre       AS etapa_nombre,
            e.eva_max,
            e.confianza_min,
            s.fisio,
            s.avanza,
            s.notas,
            COUNT(r.id)                    AS n_drills,
            ROUND(AVG(r.eva), 1)           AS eva_promedio,
            ROUND(AVG(r.confianza), 1)     AS confianza_promedio,
            MAX(r.eva)                     AS eva_max_sesion
        FROM rtp_sesiones s
        JOIN rtp_etapas e ON e.id = s.etapa_id
        LEFT JOIN rtp_resultados r ON r.sesion_id = s.id
        WHERE s.jugador_id = ?
        GROUP BY s.id
        ORDER BY s.fecha
    """, conn, params=[jugador_id], parse_dates=["fecha"])
    conn.close()
    return df


def cargar_resultados_sesion(sesion_id):
    """Carga el detalle de cada drill de una sesión RTP."""
    conn = _conectar()
    df = pd.read_sql("""
        SELECT
            r.id,
            d.nombre       AS drill,
            r.completado,
            r.eva,
            r.confianza,
            r.notas
        FROM rtp_resultados r
        JOIN rtp_drills d ON d.id = r.drill_id
        WHERE r.sesion_id = ?
        ORDER BY r.id
    """, conn, params=[sesion_id])
    conn.close()
    return df


def etapa_actual_jugador(jugador_id):
    """
    Retorna la etapa RTP actual del jugador (la de su última sesión).
    Si no tiene sesiones devuelve None.
    """
    conn = _conectar()
    cur  = conn.cursor()
    cur.execute("""
        SELECT s.etapa_id, e.orden, e.nombre, s.avanza
        FROM rtp_sesiones s
        JOIN rtp_etapas e ON e.id = s.etapa_id
        WHERE s.jugador_id = ?
        ORDER BY s.fecha DESC
        LIMIT 1
    """, (jugador_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"etapa_id": row[0], "orden": row[1], "nombre": row[2], "avanza": row[3]}


# ============================================================
# PRUEBA RÁPIDA EN CONSOLA
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  REPORTE DIARIO DE DISPONIBILIDAD DEL PLANTEL")
    print("=" * 60)

    reporte = reporte_disponibilidad()
    r = reporte["resumen"]

    print(f"\n  Fecha           : {r['fecha']}")
    print(f"  Total plantel   : {r['total_plantel']} jugadores")
    print(f"  Disponibles     : {r['disponibles']}")
    print(f"  Lesionados      : {r['lesionados']}")
    print(f"\n  Alertas en disponibles:")
    print(f"    ROJA     → {r['alertas_rojas']}")
    print(f"    NARANJA  → {r['alertas_naranja']}")
    print(f"    AMARILLA → {r['alertas_amarillas']}")
    print(f"    VERDE    → {r['sin_alertas']}")

    print("\n" + "-" * 60)
    print("  ALERTAS ACTIVAS (jugadores disponibles)")
    print("-" * 60)

    con_alerta = reporte["disponibles"]
    con_alerta = con_alerta[con_alerta["alerta"] != "VERDE"]

    if con_alerta.empty:
        print("  Sin alertas activas hoy.")
    else:
        for _, fila in con_alerta.iterrows():
            print(f"  [{fila['alerta']:8s}] {fila['jugador']:<25}  {fila['motivo']}")

    print("\n" + "-" * 60)
    print("  FUERA DE JUEGO (lesionados)")
    print("-" * 60)

    lesionados = reporte["lesionados"]
    if lesionados.empty:
        print("  Sin lesionados activos.")
    else:
        for _, fila in lesionados.iterrows():
            lesion = f"{fila.get('tipo_lesion', '')} – {fila.get('zona_corporal', '')}"
            print(f"  {fila['jugador']:<25}  {lesion:<30}  {fila.get('dias_baja', '?')} días")

    print()
    print("-" * 60)
    print("  ACWR PLANTEL (últimos valores)")
    print("-" * 60)

    acwr_df = resumen_acwr_plantel()
    for _, fila in acwr_df.iterrows():
        acwr_val = f"{fila['acwr']:.2f}" if pd.notna(fila["acwr"]) else "  —  "
        print(f"  #{fila['numero']:<3} {fila['jugador']:<25}  ACWR: {acwr_val}  [{fila['zona']}]")

    print("\n" + "=" * 60 + "\n")
