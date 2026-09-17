"""
reset_jugadores.py
===================
Sincroniza una base YA EXISTENTE (con los 25 jugadores viejos, simulados
o de una corrida anterior) con los nombres reales que están en
`database.JUGADORES` — manteniendo cada fila (mismo id, posición y
número de camiseta), solo cambia nombre/apellido.

Nota: en una base NUEVA no hace falta correr este script — alcanza con
`python database.py`, porque `JUGADORES` en database.py ya tiene los
nombres reales. Este script es para las bases que ya estaban creadas
antes de ese cambio (por ejemplo, la que tenías corriendo local).

Fuente de los nombres reales (ver database.py, lista JUGADORES):
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
  sabés qué jugador real va en qué puesto, reordená la lista JUGADORES
  en database.py antes de correr este script.

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

import database  # reutiliza JUGADORES y las funciones de simulación ya existentes

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futbol_monitoreo.db")


def reset_jugadores():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    ids = [fila[0] for fila in cur.execute("SELECT id FROM jugadores ORDER BY id").fetchall()]

    if len(ids) != len(database.JUGADORES):
        conn.close()
        raise SystemExit(
            f"La base tiene {len(ids)} jugadores pero database.JUGADORES tiene "
            f"{len(database.JUGADORES)}. Revisá la lista antes de continuar."
        )

    print("Renombrando jugadores (se mantiene id, posición y número)...")
    for jugador_id, jug in zip(ids, database.JUGADORES):
        cur.execute(
            "UPDATE jugadores SET nombre = ?, apellido = ? WHERE id = ?",
            (jug["nombre"], jug["apellido"], jugador_id),
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
