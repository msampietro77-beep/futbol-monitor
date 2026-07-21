"""
pages/RTP.py
============
Módulo de Return to Play (RTP) — Pecci et al. (2026).
Acceso según rol: director, médico y kinesiólogo (ver auth.py).

Criterios clínicos por tipo de lesión:
  - Isquiotibiales: 8 criterios ponderados (pesos suman 100)
  - Aductores: 5 criterios ponderados (pesos suman 100)

Decisión automática por score ponderado:
  ≥ 85 %  →  APTO              (verde)
  70-84 % →  APTO CONDICIONADO (naranja)
  < 70 %  →  NO APTO           (rojo)
  Criterio bloqueante no cumplido → NO APTO automático
"""

import streamlit as st
import pandas as pd
import sqlite3
import sys
import os
import json
from datetime import date

# ── CONFIGURACIÓN ────────────────────────────────────────────

st.set_page_config(
    page_title="RTP — Return to Play",
    page_icon="🏥",
    layout="wide",
)

# Permite importar auth.py, que está un directorio arriba (raíz del proyecto)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

auth.exigir_acceso("RTP")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "futbol_monitoreo.db",
)

# ── FUNCIONES DE BASE DE DATOS (inline — sin importar metricas) ──

def _conectar():
    return sqlite3.connect(DB_PATH)


def cargar_lesionados_activos():
    """Jugadores con lesión activa (activo=1 en tabla lesiones)."""
    conn = _conectar()
    try:
        df = pd.read_sql(
            """
            SELECT l.id      AS lesion_id,
                   l.jugador_id,
                   j.nombre || ' ' || j.apellido AS jugador,
                   j.posicion,
                   j.numero_camiseta            AS numero,
                   l.tipo_lesion,
                   l.zona_corporal,
                   l.fecha_inicio,
                   COALESCE(l.dias_baja, 0)     AS dias_baja
            FROM   lesiones  l
            JOIN   jugadores j ON j.id = l.jugador_id
            WHERE  l.activo = 1
            ORDER  BY l.fecha_inicio
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def cargar_historial(jugador_id):
    conn = _conectar()
    try:
        df = pd.read_sql(
            """
            SELECT fecha, tipo_lesion, score_pct, decision, evaluador, notas
            FROM   rtp_evaluaciones
            WHERE  jugador_id = ?
            ORDER  BY fecha DESC
            """,
            conn,
            params=[jugador_id],
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def guardar_evaluacion(jugador_id, lesion_id, fecha_str, tipo_lesion,
                       criterios_json, score_pct, decision, evaluador, notas):
    conn = _conectar()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rtp_evaluaciones
            (jugador_id, lesion_id, fecha, tipo_lesion, criterios_json,
             score_pct, decision, evaluador, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (jugador_id, lesion_id, fecha_str, tipo_lesion,
         criterios_json, score_pct, decision, evaluador, notas),
    )
    conn.commit()
    conn.close()


# ── CRITERIOS POR TIPO DE LESIÓN (Pecci et al. 2026) ─────────

# tipo:
#   "slider_0_10" →  slider entero 0-10
#   "porcentaje"  →  número 0-100 con símbolo %
#   "si_no"       →  radio "Sí" / "No"         (umbral "Sí" para pasar)
#   "igual_dif"   →  radio "Igual" / "Diferente" (umbral "Igual" para pasar)
# bloqueante:
#   True → si falla, decisión final = NO APTO sin importar el score global

CRITERIOS = {
    "isquiotibiales": [
        {
            "id": "dolor_accion",
            "nombre": "Dolor en acción específica",
            "ref": "EVA debe ser 0 (sin dolor)",
            "tipo": "slider_0_10",
            "umbral": 0,
            "op": "<=",
            "bloqueante": True,
            "peso": 25,
        },
        {
            "id": "simetria_fuerza_flexext",
            "nombre": "Simetría fuerza flexores / extensores rodilla",
            "ref": "Debe ser ≥ 90 % vs lado sano",
            "tipo": "porcentaje",
            "umbral": 90,
            "op": ">=",
            "bloqueante": False,
            "peso": 20,
        },
        {
            "id": "rom_activo_rodilla",
            "nombre": "Rango de movimiento activo rodilla",
            "ref": "Debe ser ≥ 95 % vs lado sano",
            "tipo": "porcentaje",
            "umbral": 95,
            "op": ">=",
            "bloqueante": False,
            "peso": 10,
        },
        {
            "id": "slr_pasivo",
            "nombre": "Straight leg raise pasivo",
            "ref": "Igual al lado sano (sin déficit de tensión neural)",
            "tipo": "igual_dif",
            "umbral": "Igual",
            "op": "==",
            "bloqueante": True,
            "peso": 15,
        },
        {
            "id": "askling_h",
            "nombre": "Test Askling-H sin dolor",
            "ref": "Ejecución del test sin aparición de dolor",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 15,
        },
        {
            "id": "readiness",
            "nombre": "Readiness subjetiva del jugador",
            "ref": "Percepción de preparación ≥ 7 / 10",
            "tipo": "slider_0_10",
            "umbral": 7,
            "op": ">=",
            "bloqueante": False,
            "peso": 5,
        },
        {
            "id": "sesion_completa",
            "nombre": "Sesión completa con equipo",
            "ref": "Entrenamiento grupal completo sin restricciones",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 5,
        },
        {
            "id": "imagen_sin_edema",
            "nombre": "Imagen sin edema",
            "ref": "ECO / RMN sin señal de edema activo",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": False,
            "peso": 5,
        },
    ],
    "aductores": [
        {
            "id": "dolor_contraccion_resistida",
            "nombre": "Sin dolor en contracción resistida",
            "ref": "Isométrico aductor sin dolor",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 30,
        },
        {
            "id": "dolor_tareas_campo",
            "nombre": "Sin dolor en tareas de campo / agilidad",
            "ref": "Sprints, cambios de dirección y frenadas sin dolor",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 25,
        },
        {
            "id": "sesion_completa",
            "nombre": "Sesión completa con equipo",
            "ref": "Entrenamiento grupal completo sin restricciones",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 20,
        },
        {
            "id": "simetria_fuerza_aductora",
            "nombre": "Simetría fuerza aductora",
            "ref": "Debe ser ≥ 90 % vs lado sano",
            "tipo": "porcentaje",
            "umbral": 90,
            "op": ">=",
            "bloqueante": False,
            "peso": 20,
        },
        {
            "id": "readiness",
            "nombre": "Readiness subjetiva del jugador",
            "ref": "Percepción de preparación ≥ 7 / 10",
            "tipo": "slider_0_10",
            "umbral": 7,
            "op": ">=",
            "bloqueante": False,
            "peso": 5,
        },
    ],
    "tobillo": [
        {
            "id": "dolor_palpacion",
            "nombre": "Sin dolor en palpación de la zona lesionada",
            "ref": "Palpación directa sobre ligamento/zona sin dolor",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 20,
        },
        {
            "id": "dolor_acciones_campo",
            "nombre": "Sin dolor en acciones de campo",
            "ref": "Sprint, cambio de dirección y frenada sin dolor",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 25,
        },
        {
            "id": "rom_dorsiflexion",
            "nombre": "Rango de movimiento dorsiflexión",
            "ref": "Similar al lado sano (sin déficit funcional)",
            "tipo": "igual_dif",
            "umbral": "Igual",
            "op": "==",
            "bloqueante": False,
            "peso": 15,
        },
        {
            "id": "simetria_plantar_flexion",
            "nombre": "Simetría fuerza plantar flexión",
            "ref": "Debe ser ≥ 90 % vs lado sano",
            "tipo": "porcentaje",
            "umbral": 90,
            "op": ">=",
            "bloqueante": False,
            "peso": 20,
        },
        {
            "id": "sesion_completa",
            "nombre": "Sesión completa con equipo",
            "ref": "Al menos una sesión grupal completa sin restricciones",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": True,
            "peso": 10,
        },
        {
            "id": "readiness",
            "nombre": "Readiness subjetiva del jugador",
            "ref": "Percepción de preparación ≥ 7 / 10",
            "tipo": "slider_0_10",
            "umbral": 7,
            "op": ">=",
            "bloqueante": False,
            "peso": 5,
        },
        {
            "id": "imagen_sin_edema",
            "nombre": "Imagen sin edema",
            "ref": "ECO sin señal de edema activo en zona ligamentosa",
            "tipo": "si_no",
            "umbral": "Sí",
            "op": "==",
            "bloqueante": False,
            "peso": 5,
        },
    ],
}

# Mapeo zona_corporal → tipo de criterio
ZONA_A_TIPO = {
    "isquiotibiales": "isquiotibiales",
    "aductor":        "aductores",
    "ingle":          "aductores",
    "tobillo":        "tobillo",
    "ligamento":      "tobillo",
    "esguince":       "tobillo",
}

# ── CÁLCULO DE SCORE ─────────────────────────────────────────

def _pasa(criterio, valor):
    """Retorna True si el criterio está cumplido con el valor dado."""
    op, umbral = criterio["op"], criterio["umbral"]
    if op == "<=":
        return float(valor) <= float(umbral)
    if op == ">=":
        return float(valor) >= float(umbral)
    if op == "==":
        return str(valor) == str(umbral)
    return False


def calcular_score(criterios_lista, valores):
    """
    Retorna (score_pct, bloqueantes_ok, detalle).
    score_pct = suma de pesos de criterios cumplidos (total pesos = 100).
    bloqueantes_ok = False si algún criterio bloqueante falla.
    """
    puntos = 0.0
    bloqueantes_ok = True
    detalle = []
    for c in criterios_lista:
        valor = valores.get(c["id"])
        ok = _pasa(c, valor) if valor is not None else False
        if ok:
            puntos += c["peso"]
        elif c["bloqueante"]:
            bloqueantes_ok = False
        detalle.append({**c, "valor": valor, "pasa": ok})
    return puntos, bloqueantes_ok, detalle


def decision_texto(score_pct, bloqueantes_ok):
    if not bloqueantes_ok:
        return "NO_APTO"
    if score_pct >= 85:
        return "APTO"
    if score_pct >= 70:
        return "APTO_CONDICIONADO"
    return "NO_APTO"


# ── HELPERS DE DISPLAY ────────────────────────────────────────

def _badge_decision(decision):
    config = {
        "APTO":              ("🟢", "#1a7a3a", "APTO"),
        "APTO_CONDICIONADO": ("🟡", "#b35900", "APTO CONDICIONADO"),
        "NO_APTO":           ("🔴", "#8b0000", "NO APTO"),
    }
    emoji, color, label = config.get(decision, ("⚪", "#555", decision))
    st.markdown(
        f"""
        <div style="background:{color}22; border:2px solid {color};
                    border-radius:8px; padding:18px; text-align:center;
                    margin-top:8px;">
            <div style="font-size:2.8rem;">{emoji}</div>
            <div style="color:{color}; font-size:1.6rem; font-weight:700;
                        margin-top:4px;">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _badge_criterio(pasa, bloqueante, nombre, ref):
    if pasa:
        icono, color, fondo = "✅", "#1a7a3a", "#e8f5e9"
    elif bloqueante:
        icono, color, fondo = "⚠️", "#8b0000", "#ffeaea"
        nombre = f"BLOQUEANTE — {nombre}"
    else:
        icono, color, fondo = "❌", "#b35900", "#fff8e1"

    st.markdown(
        f"""
        <div style="background:{fondo}; border-left:4px solid {color};
                    border-radius:4px; padding:8px 12px; margin-bottom:6px;">
            <b style="color:{color};">{icono} {nombre}</b><br>
            <span style="color:#666; font-size:0.82rem;">{ref}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── FORMULARIO DE CRITERIOS ───────────────────────────────────

def _formulario_criterios(criterios_lista):
    """
    Renderiza los inputs de cada criterio.
    Retorna dict {id: valor}.
    """
    valores = {}
    for c in criterios_lista:
        prefijo = "⚠️ " if c["bloqueante"] else ""
        etiqueta = f"{prefijo}**{c['nombre']}**  \n*{c['ref']}*"

        if c["tipo"] == "slider_0_10":
            v = st.slider(etiqueta, 0, 10, value=0, key=f"rtp_{c['id']}")

        elif c["tipo"] == "porcentaje":
            v = st.number_input(
                etiqueta, min_value=0.0, max_value=100.0,
                value=0.0, step=0.5, format="%.1f",
                key=f"rtp_{c['id']}",
            )

        elif c["tipo"] == "si_no":
            v = st.radio(
                etiqueta, ["Sí", "No"],
                index=1, horizontal=True,
                key=f"rtp_{c['id']}",
            )

        elif c["tipo"] == "igual_dif":
            v = st.radio(
                etiqueta, ["Igual", "Diferente"],
                index=1, horizontal=True,
                key=f"rtp_{c['id']}",
            )

        else:
            v = None

        valores[c["id"]] = v
        st.divider()

    return valores


# ── PÁGINA PRINCIPAL ──────────────────────────────────────────

def main():
    st.title("🏥 Return to Play — Pecci et al. (2026)")

    lesionados = cargar_lesionados_activos()

    if lesionados.empty:
        st.info("No hay jugadores con lesión activa registrada.")
        return

    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🔍 Selección")

        opciones = {
            f"{row.jugador} — {row.zona_corporal} ({int(row.dias_baja)} días)": row
            for row in lesionados.itertuples()
        }
        sel_label = st.selectbox("Jugador lesionado activo", list(opciones.keys()))
        fila = opciones[sel_label]

        zona = (fila.zona_corporal or "").lower().strip()
        tipo_auto = ZONA_A_TIPO.get(zona)

        if tipo_auto:
            tipo_lesion = tipo_auto
            st.success(f"Protocolo: **{tipo_lesion.upper()}**")
        else:
            tipo_lesion = st.selectbox(
                "Seleccionar protocolo",
                list(CRITERIOS.keys()),
                format_func=str.upper,
            )
            st.warning(
                f"Zona '{fila.zona_corporal}' sin protocolo automático. "
                "Seleccioná el más adecuado."
            )

        fecha_eval = st.date_input("Fecha de evaluación", value=date.today())
        evaluador  = st.text_input("Evaluador", placeholder="Nombre del fisio")

    # ── Tabs ─────────────────────────────────────────────────
    tab_eval, tab_hist = st.tabs(["📋 Evaluación RTP", "📊 Historial"])

    # ── TAB 1: EVALUACIÓN ────────────────────────────────────
    with tab_eval:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Jugador",        fila.jugador)
        c2.metric("Posición",       fila.posicion)
        c3.metric("Zona lesionada", fila.zona_corporal)
        c4.metric("Días de baja",   int(fila.dias_baja))

        st.markdown(
            f"**Protocolo aplicado:** `{tipo_lesion.upper()}` — Pecci et al. (2026)  \n"
            f"Los criterios marcados con ⚠️ son **bloqueantes**: si alguno falla, "
            f"la decisión es **NO APTO** independientemente del score global."
        )
        st.divider()

        criterios_lista = CRITERIOS[tipo_lesion]
        col_form, col_sem = st.columns([3, 2])

        with col_form:
            st.markdown("#### Criterios clínicos")
            valores = _formulario_criterios(criterios_lista)

        with col_sem:
            st.markdown("#### Semáforo RTP")
            score_pct, bloqueantes_ok, detalle = calcular_score(criterios_lista, valores)
            decision = decision_texto(score_pct, bloqueantes_ok)

            color_score = (
                "#1a7a3a" if score_pct >= 85
                else "#b35900" if score_pct >= 70
                else "#8b0000"
            )
            pct_bar = min(int(score_pct), 100)

            st.markdown(
                f"""
                <div style="margin-bottom:6px;">
                  <span style="font-size:0.95rem; color:#555;">Score ponderado</span><br>
                  <span style="font-size:2.8rem; font-weight:700; color:{color_score};">
                    {score_pct:.0f}
                    <span style="font-size:1.2rem; font-weight:400;">/ 100</span>
                  </span>
                </div>
                <div style="background:#e0e0e0; border-radius:6px;
                            height:16px; margin-bottom:14px;">
                    <div style="width:{pct_bar}%; background:{color_score};
                                border-radius:6px; height:16px;"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            _badge_decision(decision)

            if not bloqueantes_ok:
                st.warning("⚠️ Criterio bloqueante no cumplido → NO APTO automático")

            st.markdown("---")
            st.markdown("**Detalle por criterio:**")
            for d in detalle:
                _badge_criterio(d["pasa"], d["bloqueante"], d["nombre"], d["ref"])

        st.divider()

        notas = st.text_area(
            "Notas clínicas (opcional)",
            placeholder="Observaciones adicionales del fisioterapeuta...",
            height=90,
        )

        if st.button("💾 Guardar evaluación", type="primary", use_container_width=True):
            if not evaluador.strip():
                st.error("Ingresá el nombre del evaluador antes de guardar.")
            else:
                criterios_guardados = {
                    d["id"]: {
                        "nombre":    d["nombre"],
                        "valor":     d["valor"],
                        "pasa":      d["pasa"],
                        "bloqueante": d["bloqueante"],
                        "peso":      d["peso"],
                    }
                    for d in detalle
                }
                guardar_evaluacion(
                    jugador_id    = int(fila.jugador_id),
                    lesion_id     = int(fila.lesion_id),
                    fecha_str     = fecha_eval.strftime("%Y-%m-%d"),
                    tipo_lesion   = tipo_lesion,
                    criterios_json= json.dumps(criterios_guardados, ensure_ascii=False),
                    score_pct     = round(score_pct, 1),
                    decision      = decision,
                    evaluador     = evaluador.strip(),
                    notas         = notas.strip(),
                )
                st.success(
                    f"✅ Evaluación guardada — **{fila.jugador}** — "
                    f"{fecha_eval} — **{decision}**"
                )

    # ── TAB 2: HISTORIAL ─────────────────────────────────────
    with tab_hist:
        st.markdown(f"#### Historial — {fila.jugador}")
        hist = cargar_historial(int(fila.jugador_id))

        if hist.empty:
            st.info("No hay evaluaciones registradas para este jugador.")
        else:
            def _color_decision(val):
                if val == "APTO":
                    return "background-color:#d4edda; color:#155724;"
                if val == "APTO_CONDICIONADO":
                    return "background-color:#fff3cd; color:#856404;"
                if val == "NO_APTO":
                    return "background-color:#f8d7da; color:#721c24;"
                return ""

            hist_display = hist.rename(columns={
                "fecha":       "Fecha",
                "tipo_lesion": "Tipo",
                "score_pct":   "Score (%)",
                "decision":    "Decisión",
                "evaluador":   "Evaluador",
                "notas":       "Notas",
            })
            st.dataframe(
                hist_display.style.applymap(_color_decision, subset=["Decisión"]),
                use_container_width=True,
                hide_index=True,
            )

            if len(hist) > 1:
                import plotly.graph_objects as go

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist["fecha"],
                    y=hist["score_pct"],
                    mode="lines+markers",
                    line=dict(color="#1f77b4", width=2),
                    marker=dict(size=10),
                    name="Score RTP",
                ))
                fig.add_hline(y=85, line_dash="dash", line_color="green",
                              annotation_text="APTO (85 %)")
                fig.add_hline(y=70, line_dash="dash", line_color="orange",
                              annotation_text="APTO CONDICIONADO (70 %)")
                fig.update_layout(
                    title="Evolución del score RTP",
                    xaxis_title="Fecha",
                    yaxis_title="Score (%)",
                    yaxis=dict(range=[0, 105]),
                    height=320,
                    margin=dict(l=20, r=20, t=40, b=20),
                )
                st.plotly_chart(fig, use_container_width=True)


# ── ENTRY POINT ───────────────────────────────────────────────

main()
