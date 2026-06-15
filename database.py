"""
database.py
===========
Crea la base de datos SQLite y simula 90 días de datos para el plantel.

Tablas:
  - jugadores      → plantel de 25 jugadores con posición y número
  - carga_interna  → RPE, minutos, training load y tipo de sesión
  - wellness       → 6 ítems de bienestar diario + wellness total
  - lesiones       → historial de lesiones con días de baja

Cómo usar:
  python database.py
"""

import sqlite3
import os
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

# Ruta del archivo de base de datos (mismo directorio que este script)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futbol_monitoreo.db")

# Período de simulación: hoy hacia atrás 90 días
FECHA_FIN   = datetime.today().date()
FECHA_INICIO = FECHA_FIN - timedelta(days=89)  # 90 días inclusive

# Semilla para que los datos simulados sean siempre iguales al re-ejecutar
random.seed(42)
np.random.seed(42)


# ============================================================
# DATOS DEL PLANTEL (25 JUGADORES)
# ============================================================

JUGADORES = [
    # --- 4 Porteros ---
    {"nombre": "Carlos",    "apellido": "Méndez",    "posicion": "portero",       "numero": 1},
    {"nombre": "Fabio",     "apellido": "Rossi",     "posicion": "portero",       "numero": 13},
    {"nombre": "Diego",     "apellido": "Vargas",    "posicion": "portero",       "numero": 26},
    {"nombre": "Andrés",    "apellido": "Pereira",   "posicion": "portero",       "numero": 33},
    # --- 8 Defensores ---
    {"nombre": "Lucas",     "apellido": "Fernández", "posicion": "defensor",      "numero": 2},
    {"nombre": "Martín",    "apellido": "González",  "posicion": "defensor",      "numero": 3},
    {"nombre": "Sebastián", "apellido": "Torres",    "posicion": "defensor",      "numero": 4},
    {"nombre": "Pablo",     "apellido": "Ramírez",   "posicion": "defensor",      "numero": 5},
    {"nombre": "Nicolás",   "apellido": "López",     "posicion": "defensor",      "numero": 6},
    {"nombre": "Emilio",    "apellido": "Castro",    "posicion": "defensor",      "numero": 12},
    {"nombre": "Rodrigo",   "apellido": "Suárez",    "posicion": "defensor",      "numero": 14},
    {"nombre": "Hernán",    "apellido": "Ortega",    "posicion": "defensor",      "numero": 15},
    # --- 8 Mediocampistas ---
    {"nombre": "Javier",    "apellido": "Morales",   "posicion": "mediocampista", "numero": 7},
    {"nombre": "Felipe",    "apellido": "Silva",     "posicion": "mediocampista", "numero": 8},
    {"nombre": "Ricardo",   "apellido": "Díaz",      "posicion": "mediocampista", "numero": 10},
    {"nombre": "Eduardo",   "apellido": "Ruiz",      "posicion": "mediocampista", "numero": 16},
    {"nombre": "Tomás",     "apellido": "Herrera",   "posicion": "mediocampista", "numero": 17},
    {"nombre": "Germán",    "apellido": "Navarro",   "posicion": "mediocampista", "numero": 18},
    {"nombre": "Cristian",  "apellido": "Vega",      "posicion": "mediocampista", "numero": 19},
    {"nombre": "Santiago",  "apellido": "Ramos",     "posicion": "mediocampista", "numero": 20},
    # --- 5 Delanteros ---
    {"nombre": "Alexis",    "apellido": "Muñoz",     "posicion": "delantero",     "numero": 9},
    {"nombre": "Bruno",     "apellido": "Acosta",    "posicion": "delantero",     "numero": 11},
    {"nombre": "Gabriel",   "apellido": "Reyes",     "posicion": "delantero",     "numero": 21},
    {"nombre": "Mateo",     "apellido": "Flores",    "posicion": "delantero",     "numero": 22},
    {"nombre": "Daniel",    "apellido": "Aguirre",   "posicion": "delantero",     "numero": 23},
]


# ============================================================
# PARÁMETROS DE CARGA POR TIPO DE SESIÓN
# Cada tipo define rango de RPE (1-10) y duración en minutos
# ============================================================

PARAMETROS_SESION = {
    "partido":       {"rpe_min": 7, "rpe_max": 9,  "min_min": 60,  "min_max": 95},
    "entrenamiento": {"rpe_min": 5, "rpe_max": 8,  "min_min": 60,  "min_max": 100},
    "regenerativo":  {"rpe_min": 2, "rpe_max": 4,  "min_min": 25,  "min_max": 45},
    "gym":           {"rpe_min": 5, "rpe_max": 7,  "min_min": 40,  "min_max": 65},
    "descanso":      {"rpe_min": 0, "rpe_max": 0,  "min_min": 0,   "min_max": 0},
}

# Factor de carga por posición (los mediocampistas acumulan más volumen)
FACTOR_POSICION = {
    "portero":       0.85,
    "defensor":      1.00,
    "mediocampista": 1.10,
    "delantero":     1.05,
}

# Tipos de lesión y zona corporal para la simulación
TIPOS_LESION = [
    ("muscular",     "isquiotibiales"),
    ("muscular",     "cuádriceps"),
    ("muscular",     "gemelo"),
    ("muscular",     "aductor"),
    ("ligamentosa",  "tobillo"),
    ("ligamentosa",  "rodilla"),
    ("contusión",    "muslo"),
    ("contusión",    "pie"),
    ("sobrecarga",   "lumbar"),
    ("tendinopatía", "aquiles"),
]


# ============================================================
# PASO 1: CREAR TABLAS
# ============================================================

def crear_tablas(conn):
    """Crea todas las tablas si no existen todavía."""
    cur = conn.cursor()

    # Jugadores del plantel
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jugadores (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre           TEXT    NOT NULL,
            apellido         TEXT    NOT NULL,
            posicion         TEXT    NOT NULL,
            numero_camiseta  INTEGER UNIQUE,
            fecha_creacion   TEXT    DEFAULT (date('now'))
        )
    """)

    # Registro diario de carga interna
    # training_load = RPE × minutos  (NULL cuando es día de descanso)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS carga_interna (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            jugador_id    INTEGER NOT NULL,
            fecha         TEXT    NOT NULL,
            tipo_sesion   TEXT    NOT NULL,
            rpe           INTEGER,
            minutos       INTEGER,
            training_load INTEGER,
            FOREIGN KEY (jugador_id) REFERENCES jugadores(id),
            UNIQUE (jugador_id, fecha)
        )
    """)

    # Registro diario de wellness  (escala 1-5 en todos los ítems)
    # wellness_total: promedio ajustado donde mayor = mejor bienestar
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wellness (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            jugador_id      INTEGER NOT NULL,
            fecha           TEXT    NOT NULL,
            fatiga          INTEGER NOT NULL,
            calidad_sueno   INTEGER NOT NULL,
            horas_sueno     INTEGER NOT NULL,
            dolor_muscular  INTEGER NOT NULL,
            humor           INTEGER NOT NULL,
            estres          INTEGER NOT NULL,
            wellness_total  REAL    NOT NULL,
            FOREIGN KEY (jugador_id) REFERENCES jugadores(id),
            UNIQUE (jugador_id, fecha)
        )
    """)

    # Historial de lesiones
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lesiones (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            jugador_id    INTEGER NOT NULL,
            fecha_inicio  TEXT    NOT NULL,
            fecha_fin     TEXT,
            tipo_lesion   TEXT    NOT NULL,
            zona_corporal TEXT    NOT NULL,
            dias_baja     INTEGER,
            activo        INTEGER DEFAULT 1,
            FOREIGN KEY (jugador_id) REFERENCES jugadores(id)
        )
    """)

    # Registro de sesiones de fuerza y gym
    # rm_estimado: calculado con fórmula de Epley (carga × (1 + reps/30))
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fuerza (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            jugador_id     INTEGER NOT NULL,
            fecha          TEXT    NOT NULL,
            ejercicio      TEXT    NOT NULL,
            series         INTEGER NOT NULL,
            repeticiones   INTEGER NOT NULL,
            carga_kg       REAL    NOT NULL,
            rpe            INTEGER NOT NULL,
            rm_estimado    REAL,
            notas          TEXT,
            FOREIGN KEY (jugador_id) REFERENCES jugadores(id)
        )
    """)

    # ── MÓDULO RTP ───────────────────────────────────────────

    # Etapas del protocolo de Return to Play
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtp_etapas (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            orden          INTEGER NOT NULL UNIQUE,
            nombre         TEXT    NOT NULL,
            descripcion    TEXT,
            eva_max        INTEGER DEFAULT 3,
            confianza_min  INTEGER DEFAULT 7,
            activa         INTEGER DEFAULT 1
        )
    """)

    # Drills disponibles por etapa
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtp_drills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            etapa_id    INTEGER NOT NULL,
            nombre      TEXT    NOT NULL,
            descripcion TEXT,
            activo      INTEGER DEFAULT 1,
            FOREIGN KEY (etapa_id) REFERENCES rtp_etapas(id)
        )
    """)

    # Sesiones RTP: una por día por jugador
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtp_sesiones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            jugador_id  INTEGER NOT NULL,
            lesion_id   INTEGER,
            fecha       TEXT    NOT NULL,
            etapa_id    INTEGER NOT NULL,
            fisio       TEXT,
            avanza      INTEGER DEFAULT 0,
            notas       TEXT,
            FOREIGN KEY (jugador_id) REFERENCES jugadores(id),
            FOREIGN KEY (etapa_id)   REFERENCES rtp_etapas(id)
        )
    """)

    # Resultados por drill dentro de cada sesión
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtp_resultados (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id   INTEGER NOT NULL,
            drill_id    INTEGER NOT NULL,
            completado  INTEGER DEFAULT 1,
            eva         INTEGER NOT NULL,
            confianza   INTEGER NOT NULL,
            notas       TEXT,
            FOREIGN KEY (sesion_id) REFERENCES rtp_sesiones(id),
            FOREIGN KEY (drill_id)  REFERENCES rtp_drills(id)
        )
    """)

    conn.commit()
    print("  [OK] Tablas creadas")


# ============================================================
# PASO RTP: INSERTAR PROTOCOLO BASE
# ============================================================

# Etapas del protocolo RTP con sus drills de arranque
PROTOCOLO_RTP = [
    {
        "orden": 1,
        "nombre": "Reposo / Control inflamatorio",
        "descripcion": "Reducir inflamación y dolor. Sin carga sobre la zona lesionada.",
        "eva_max": 2,
        "confianza_min": 5,
        "drills": [
            ("Crioterapia y compresión",        "10-15 min de hielo + compresión en zona lesionada"),
            ("Movilidad pasiva articular",       "Movilidad asistida sin dolor en arco libre"),
            ("Isométricos sin carga",            "Contracción sin movimiento articular, sin dolor"),
            ("Deambulación sin cojera",          "Caminar en plano sin compensaciones"),
        ]
    },
    {
        "orden": 2,
        "nombre": "Movilidad y activación",
        "descripcion": "Recuperar rango articular y activación muscular básica.",
        "eva_max": 3,
        "confianza_min": 6,
        "drills": [
            ("Bicicleta estática suave",         "15-20 min cadencia baja, sin resistencia"),
            ("Propiocepción estática",           "Apoyo monopodal sobre superficie estable 3×30s"),
            ("Movilidad activa completa",        "Arco completo sin asistencia, sin compensar"),
            ("Ejercicios de fuerza en piscina",  "Marcha y elevaciones en agua (descarga)"),
        ]
    },
    {
        "orden": 3,
        "nombre": "Aeróbico en línea recta",
        "descripcion": "Carga aeróbica progresiva sin cambios de dirección.",
        "eva_max": 2,
        "confianza_min": 7,
        "drills": [
            ("Trote suave 10 min",               "Ritmo conversacional, plano, superficie blanda"),
            ("Aceleración progresiva 60-70-80%", "3 repeticiones × 30m con recuperación completa"),
            ("Carrera hacia atrás (backpedal)",  "15m × 4 repeticiones a velocidad controlada"),
            ("Skipping y talones a glúteos",     "Coordinación sin impacto lateral, 3×20m"),
        ]
    },
    {
        "orden": 4,
        "nombre": "Cambios de dirección",
        "descripcion": "Introducir estrés lateral y multidireccional.",
        "eva_max": 2,
        "confianza_min": 7,
        "drills": [
            ("Cambios de dirección a 45°",       "Cono en T, 4 repeticiones a 70% velocidad"),
            ("Cambios de dirección a 90°",       "Illinois test modificado, 4 repeticiones"),
            ("Sprint con desaceleración",        "20m sprint + freno, 4 repeticiones"),
            ("Saltos bipodales en profundidad",  "Drop jump desde 30cm, aterrizaje controlado"),
        ]
    },
    {
        "orden": 5,
        "nombre": "Específico con pelota",
        "descripcion": "Reintroducir el balón en situaciones controladas.",
        "eva_max": 1,
        "confianza_min": 8,
        "drills": [
            ("Pases cortos y recepción",         "2 jugadores, 5-10m, sin presión, ambos perfiles"),
            ("Conducción y cambio de dirección", "Slalom a 80% con pelota"),
            ("Saltos monopodales con pelota",    "Cabeceo liviano desde punto fijo"),
            ("Remate de media distancia",        "Sin oposición, bola parada, 5 remates cada perfil"),
        ]
    },
    {
        "orden": 6,
        "nombre": "Entrenamiento grupal sin restricción",
        "descripcion": "Integración completa al grupo. Último paso antes de la competencia.",
        "eva_max": 0,
        "confianza_min": 9,
        "drills": [
            ("Rondo 4v1 / 5v2",                 "Participación sin restricción de contacto"),
            ("Juego reducido con presión",       "3v3 o 4v4 en espacio pequeño"),
            ("Situación de juego 11v11",         "Entrenamiento colectivo completo sin limitaciones"),
            ("Duelo 1v1",                        "Entrada al cuerpo autorizada por el fisio"),
        ]
    },
]


def insertar_protocolo_rtp(conn):
    """
    Inserta las etapas y drills base del protocolo RTP.
    Usa INSERT OR IGNORE para no duplicar si se reinicializa la DB.
    """
    cur = conn.cursor()

    for etapa in PROTOCOLO_RTP:
        cur.execute("""
            INSERT OR IGNORE INTO rtp_etapas
                (orden, nombre, descripcion, eva_max, confianza_min)
            VALUES (?, ?, ?, ?, ?)
        """, (
            etapa["orden"],
            etapa["nombre"],
            etapa["descripcion"],
            etapa["eva_max"],
            etapa["confianza_min"],
        ))

        # Obtener el id de la etapa recién insertada (o la existente)
        cur.execute("SELECT id FROM rtp_etapas WHERE orden = ?", (etapa["orden"],))
        etapa_id = cur.fetchone()[0]

        for (nombre_drill, desc_drill) in etapa["drills"]:
            cur.execute("""
                INSERT OR IGNORE INTO rtp_drills (etapa_id, nombre, descripcion)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM rtp_drills WHERE etapa_id = ? AND nombre = ?
                )
            """, (etapa_id, nombre_drill, desc_drill, etapa_id, nombre_drill))

    conn.commit()
    print(f"  [OK] Protocolo RTP: {len(PROTOCOLO_RTP)} etapas cargadas")


# ============================================================
# PASO 2: INSERTAR JUGADORES
# ============================================================

def insertar_jugadores(conn):
    """Inserta los 25 jugadores del plantel."""
    cur = conn.cursor()
    for j in JUGADORES:
        cur.execute("""
            INSERT OR IGNORE INTO jugadores (nombre, apellido, posicion, numero_camiseta)
            VALUES (?, ?, ?, ?)
        """, (j["nombre"], j["apellido"], j["posicion"], j["numero"]))
    conn.commit()
    print(f"  [OK] {len(JUGADORES)} jugadores insertados")


# ============================================================
# PASO 3: SIMULAR CARGA INTERNA
# ============================================================

def _tipo_sesion_del_dia(semana_num, dia_semana):
    """
    Determina el tipo de sesión según la lógica semanal de fútbol.
    dia_semana: 0=Lunes, 1=Martes, ..., 6=Domingo
    Cada 2 semanas hay partido el domingo.
    """
    tiene_partido = (semana_num % 2 == 0)

    if dia_semana == 0:   # Lunes → descanso o regenerativo post-esfuerzo
        return "regenerativo" if tiene_partido else "descanso"
    elif dia_semana == 1: # Martes → reactivación
        return random.choice(["entrenamiento", "gym"])
    elif dia_semana == 2: # Miércoles → carga alta
        return "entrenamiento"
    elif dia_semana == 3: # Jueves → carga media
        return random.choice(["entrenamiento", "gym"])
    elif dia_semana == 4: # Viernes → ajuste táctico
        return "entrenamiento"
    elif dia_semana == 5: # Sábado → activación o entrenamiento liviano
        return "regenerativo" if tiene_partido else "entrenamiento"
    else:                 # Domingo → partido o descanso
        return "partido" if tiene_partido else "descanso"


def simular_carga_interna(conn, jugadores_df):
    """Simula 90 días de carga interna para los 25 jugadores."""
    cur = conn.cursor()
    registros = []
    fechas = [FECHA_INICIO + timedelta(days=i) for i in range(90)]

    for _, jugador in jugadores_df.iterrows():
        factor_pos    = FACTOR_POSICION[jugador["posicion"]]
        factor_indiv  = random.uniform(0.88, 1.12)  # variación única por jugador

        for fecha in fechas:
            semana_num  = (fecha - FECHA_INICIO).days // 7
            dia_semana  = fecha.weekday()
            tipo        = _tipo_sesion_del_dia(semana_num, dia_semana)
            params      = PARAMETROS_SESION[tipo]

            if tipo == "descanso":
                rpe = minutos = training_load = None
            else:
                rpe = int(round(
                    np.clip(
                        np.random.uniform(params["rpe_min"], params["rpe_max"]) * factor_pos * factor_indiv,
                        1, 10
                    )
                ))
                minutos = int(round(
                    np.clip(
                        np.random.uniform(params["min_min"], params["min_max"]) * factor_pos * factor_indiv,
                        params["min_min"] * 0.7, params["min_max"] * 1.2
                    )
                ))
                training_load = rpe * minutos

            registros.append((jugador["id"], str(fecha), tipo, rpe, minutos, training_load))

    cur.executemany("""
        INSERT OR IGNORE INTO carga_interna
            (jugador_id, fecha, tipo_sesion, rpe, minutos, training_load)
        VALUES (?, ?, ?, ?, ?, ?)
    """, registros)
    conn.commit()
    print(f"  [OK] {len(registros)} registros de carga interna")


# ============================================================
# PASO 4: SIMULAR WELLNESS
# ============================================================

def _valor_1_5(media, baseline, factor_dia, ruido=0.5):
    """
    Genera un valor entero entre 1 y 5 con distribución normal.
    baseline: factor individual del jugador (0.8 a 1.0)
    factor_dia: penaliza lunes post-esfuerzo
    """
    v = np.random.normal(media * baseline * factor_dia, ruido)
    return int(np.clip(round(v), 1, 5))


def simular_wellness(conn, jugadores_df):
    """
    Simula 90 días de wellness para los 25 jugadores.

    Escala 1-5 para todos los ítems:
      fatiga        : 1=sin fatiga, 5=muy fatigado       (más alto = peor)
      calidad_sueno : 1=muy mala,   5=excelente          (más alto = mejor)
      horas_sueno   : 1=<5h,        5=>9h                (más alto = mejor)
      dolor_muscular: 1=sin dolor,  5=dolor severo       (más alto = peor)
      humor         : 1=muy malo,   5=excelente          (más alto = mejor)
      estres        : 1=muy bajo,   5=muy alto           (más alto = peor)

    wellness_total (1-5): invierte los ítems negativos antes de promediar
      → siempre se interpreta como: más alto = mejor bienestar general
    """
    cur = conn.cursor()
    registros = []
    fechas = [FECHA_INICIO + timedelta(days=i) for i in range(90)]

    for _, jugador in jugadores_df.iterrows():
        baseline = random.uniform(0.80, 1.00)  # personalidad base del jugador

        for fecha in fechas:
            # Los lunes post-partido el bienestar tiende a ser peor
            factor_dia = 0.85 if fecha.weekday() == 0 else 1.0

            fatiga         = _valor_1_5(3.0, baseline, factor_dia)
            calidad_sueno  = _valor_1_5(3.5, baseline, factor_dia)
            horas_sueno    = _valor_1_5(3.5, baseline, factor_dia)
            dolor_muscular = _valor_1_5(2.8, baseline, factor_dia)
            humor          = _valor_1_5(3.8, baseline, factor_dia)
            estres         = _valor_1_5(2.5, baseline, factor_dia)

            # wellness_total: invertimos fatiga, dolor y estrés (eran "malo si alto")
            # Resultado: escala 1-5 donde 5 = bienestar perfecto
            wellness_total = round(
                (
                    (6 - fatiga)         +   # invertido
                    calidad_sueno        +
                    horas_sueno          +
                    (6 - dolor_muscular) +   # invertido
                    humor                +
                    (6 - estres)             # invertido
                ) / 6, 2
            )

            registros.append((
                jugador["id"], str(fecha),
                fatiga, calidad_sueno, horas_sueno,
                dolor_muscular, humor, estres, wellness_total
            ))

    cur.executemany("""
        INSERT OR IGNORE INTO wellness
            (jugador_id, fecha, fatiga, calidad_sueno, horas_sueno,
             dolor_muscular, humor, estres, wellness_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, registros)
    conn.commit()
    print(f"  [OK] {len(registros)} registros de wellness")


# ============================================================
# PASO 5: SIMULAR LESIONES
# ============================================================

def simular_lesiones(conn, jugadores_df):
    """
    Simula entre 8 y 12 lesiones distribuidas en el plantel.
    Los días de baja varían según el tipo de lesión.
    """
    cur = conn.cursor()
    registros = []
    ids_jugadores = jugadores_df["id"].tolist()

    n_lesiones = random.randint(8, 12)

    for _ in range(n_lesiones):
        jugador_id  = random.choice(ids_jugadores)
        dias_offset = random.randint(5, 80)
        fecha_ini   = FECHA_INICIO + timedelta(days=dias_offset)
        tipo, zona  = random.choice(TIPOS_LESION)

        # Duración de baja según gravedad del tipo de lesión
        if tipo == "muscular":
            dias_baja = random.randint(7, 21)
        elif tipo == "ligamentosa":
            dias_baja = random.randint(14, 45)
        elif tipo == "contusión":
            dias_baja = random.randint(2, 7)
        else:  # sobrecarga, tendinopatía
            dias_baja = random.randint(5, 14)

        fecha_fin_calc = fecha_ini + timedelta(days=dias_baja)

        # Si ya pasó la fecha de alta → lesión resuelta
        if fecha_fin_calc <= FECHA_FIN:
            fecha_fin = str(fecha_fin_calc)
            activo = 0
        else:
            fecha_fin = None  # sigue lesionado hoy
            activo = 1

        registros.append((
            jugador_id,
            str(fecha_ini),
            fecha_fin,
            tipo, zona,
            dias_baja,
            activo
        ))

    cur.executemany("""
        INSERT INTO lesiones
            (jugador_id, fecha_inicio, fecha_fin, tipo_lesion, zona_corporal, dias_baja, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, registros)
    conn.commit()
    print(f"  [OK] {n_lesiones} lesiones simuladas")


# ============================================================
# PASO 6: SIMULAR SESIONES DE FUERZA
# ============================================================

# Ejercicios clave para fútbol con rangos de carga por posición (en kg)
# Cada entrada: (nombre, series, reps_min, reps_max, carga_base_kg)
EJERCICIOS_FUERZA = [
    ("Sentadilla",              4, 4, 8,  80),
    ("Peso muerto rumano",      3, 6, 10, 70),
    ("Hip thrust",              4, 6, 10, 90),
    ("Press de banca",          3, 6, 10, 60),
    ("Prensa de piernas",       3, 8, 12, 120),
    ("Curl de isquiotibiales",  3, 8, 12, 40),
    ("Extensión de rodilla",    3, 10, 15, 35),
    ("Remo con barra",          3, 8, 12, 50),
]

# Factor de carga por posición en ejercicios de fuerza
FACTOR_FUERZA_POSICION = {
    "portero":       0.95,
    "defensor":      1.00,
    "mediocampista": 0.92,
    "delantero":     0.97,
}


def simular_fuerza(conn, jugadores_df):
    """
    Simula sesiones de gimnasio para los 90 días.
    Solo se registran los días que tienen 'gym' en carga_interna.
    Cada sesión incluye 3 a 4 ejercicios elegidos al azar.
    El 1RM estimado usa la fórmula de Epley: carga × (1 + reps/30).
    """
    cur = conn.cursor()

    # Traer solo los días de gym de la tabla ya cargada
    dias_gym = pd.read_sql("""
        SELECT jugador_id, fecha
        FROM carga_interna
        WHERE tipo_sesion = 'gym'
    """, conn)

    registros = []

    for _, fila in dias_gym.iterrows():
        jugador_id = fila["jugador_id"]

        # Buscar posición del jugador
        posicion = jugadores_df.loc[
            jugadores_df["id"] == jugador_id, "posicion"
        ].values[0]

        factor_pos   = FACTOR_FUERZA_POSICION[posicion]
        factor_indiv = random.uniform(0.88, 1.12)  # variación personal del jugador

        # Elegir 3 o 4 ejercicios al azar para esa sesión
        ejercicios_sesion = random.sample(EJERCICIOS_FUERZA, k=random.randint(3, 4))

        for (ejercicio, series, reps_min, reps_max, carga_base) in ejercicios_sesion:

            repeticiones = random.randint(reps_min, reps_max)
            rpe          = random.randint(6, 9)

            # Carga ajustada por posición, individuo y RPE
            # A mayor RPE → más cerca del límite → carga más alta
            factor_rpe = 0.85 + (rpe - 6) * 0.05
            carga_kg   = round(
                carga_base * factor_pos * factor_indiv * factor_rpe, 1
            )

            # 1RM estimado con fórmula de Epley
            rm_estimado = round(carga_kg * (1 + repeticiones / 30), 1)

            registros.append((
                jugador_id,
                fila["fecha"],
                ejercicio,
                series,
                repeticiones,
                carga_kg,
                rpe,
                rm_estimado,
                None   # notas vacías en la simulación
            ))

    cur.executemany("""
        INSERT INTO fuerza
            (jugador_id, fecha, ejercicio, series, repeticiones,
             carga_kg, rpe, rm_estimado, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, registros)
    conn.commit()
    print(f"  [OK] {len(registros)} registros de fuerza simulados")


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def inicializar_base_datos():
    """Ejecuta todos los pasos en orden: tablas → jugadores → datos."""
    print()
    print("=" * 50)
    print("   SISTEMA DE MONITOREO DE RENDIMIENTO")
    print("   Inicializando base de datos...")
    print("=" * 50)
    print(f"   Período : {FECHA_INICIO}  →  {FECHA_FIN}  (90 días)")
    print(f"   Plantel  : {len(JUGADORES)} jugadores")
    print(f"   Archivo  : {DB_PATH}")
    print("=" * 50)
    print()

    conn = sqlite3.connect(DB_PATH)

    crear_tablas(conn)
    insertar_jugadores(conn)

    # Leer jugadores con sus IDs asignados por la BD
    jugadores_df = pd.read_sql("SELECT id, nombre, apellido, posicion FROM jugadores", conn)

    simular_carga_interna(conn, jugadores_df)
    simular_wellness(conn, jugadores_df)
    simular_lesiones(conn, jugadores_df)
    simular_fuerza(conn, jugadores_df)
    insertar_protocolo_rtp(conn)

    conn.close()

    print()
    print("=" * 50)
    print("   BASE DE DATOS LISTA PARA USAR")
    print("=" * 50)
    print()


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    inicializar_base_datos()
