"""
reset_jugadores.py
===================
Reemplaza los 25 jugadores simulados de la base por nombres reales
extraídos de exports de KSport, manteniendo cada fila (mismo id,
posición y número de camiseta) — solo cambia nombre/apellido.

Fuente de los nombres:
  El archivo pedido originalmente (2026_09_03_Full_Training_Grupo_1.csv)
  no está en el equipo — se usó el "Full Training" más reciente que sí
  hay guardado, combinando sus dos grupos (25 jugadores en total,
  sin contar la fila "Team Average" que KSport agrega sola):

    2026_02_18_Full Training Grupo 1.csv  (10 jugadores)
    2026_02_18_Full Training Grupo 2.csv  (15 jugadores)

  Los CSV de KSport solo traen un identificador (apellido, a veces con
  una inicial para distinguir homónimos, ej. "Sánchez A."), no nombre
  de pila separado. Por eso ese texto se guarda completo en `apellido`
  y `nombre` queda vacío. Todo el sistema arma el nombre para mostrar
  con TRIM(nombre || ' ' || apellido), así que igual se ve prolijo.

  Los CSV de GPS no traen la posición de cada jugador, así que la
  asignación a las 25 filas (portero/defensor/mediocampista/delantero)
  es simplemente en el orden en que aparecen en los archivos — si
  sabés qué jugador real va en qué puesto, reordená APELLIDOS_REALES
  antes de correr el script.

Como el jugador_id NO cambia, todo el historial de lesiones sigue
siendo válido (las lesiones ya cargadas van a aparecer con el nombre
real del jugador que ocupa esa fila).

Después de renombrar, borra y regenera 90 días de wellness, carga
interna y fuerza — siguen siendo datos SIMULADOS (los CSV de KSport no
traen wellness ni carga histórica), solo que ahora con los jugadores
reales.

Cómo usar:
  python reset_jugadores.py
"""

import sqlite3
import os
import pandas as pd

import database  # reutiliza las funciones de simulación ya existentes

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futbol_monitoreo.db")


# ============================================================
# NOMBRES REALES (KSport, sin "Team Average"), 25 en total
# Orden: 4 porteros, 8 defensores, 8 mediocampistas, 5 delanteros
# (mismo orden de posiciones que ya tienen las 25 filas en la base)
# ============================================================

APELLIDOS_REALES = [
    # --- Porteros (4) ---
    "Benítez", "Fernández", "López L.", "Maldonado",
    # --- Defensores (8) ---
    "Morales", "Rigoni", "Sánchez A.", "Spörle",
    "Vázquez", "Zelarayán L.", "Castro T.", "Falcón",
    # --- Mediocampistas (8) ---
    "González Metilli", "Gutierrez", "Hernándes R.", "Longo",
    "Lucco J.", "Mavilla", "Melano", "Ocampo",
    # --- Delanteros (5) ---
    "Passerini", "Reyna", "Ricca", "Tulián", "Zelarayán G.",
]


def reset_jugadores():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    ids = [fila[0] for fila in cur.execute("SELECT id FROM jugadores ORDER BY id").fetchall()]

    if len(ids) != len(APELLIDOS_REALES):
        conn.close()
        raise SystemExit(
            f"La base tiene {len(ids)} jugadores pero hay {len(APELLIDOS_REALES)} "
            "nombres reales cargados en el script. Revisá APELLIDOS_REALES antes de continuar."
        )

    print("Renombrando jugadores (se mantiene id, posición y número)...")
    for jugador_id, apellido_real in zip(ids, APELLIDOS_REALES):
        cur.execute(
            "UPDATE jugadores SET nombre = '', apellido = ? WHERE id = ?",
            (apellido_real, jugador_id),
        )
    conn.commit()
    print(f"  [OK] {len(ids)} jugadores renombrados")

    print("Borrando wellness, carga interna y fuerza simulados anteriormente...")
    cur.execute("DELETE FROM wellness")
    cur.execute("DELETE FROM carga_interna")
    cur.execute("DELETE FROM fuerza")
    conn.commit()
    print("  [OK] Tablas vaciadas")

    print("Regenerando 90 días de datos simulados con los nombres nuevos...")
    jugadores_df = pd.read_sql("SELECT id, nombre, apellido, posicion FROM jugadores", conn)
    database.simular_carga_interna(conn, jugadores_df)
    database.simular_wellness(conn, jugadores_df)
    database.simular_fuerza(conn, jugadores_df)

    conn.close()
    print()
    print("Listo — el plantel ahora tiene los nombres reales de KSport.")
    print("Nota: las lesiones ya cargadas no se tocaron, así que van a")
    print("aparecer asociadas al jugador real que ahora ocupa esa fila.")


if __name__ == "__main__":
    reset_jugadores()
