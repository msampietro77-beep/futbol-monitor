"""
pages/ML_Riesgo.py
==================
Predicción de riesgo de lesión mediante Machine Learning.
Basado en Rebelo et al. (2026) y Gabbett (2016).

Modelo: Random Forest (300 árboles, class_weight='balanced').
Horizonte de predicción: 7 días.
Validación: TimeSeriesSplit cronológico con AUC-ROC.

IMPORTANTE: Herramienta de apoyo a la decisión clínica.
No reemplaza el juicio del médico ni del fisioterapeuta.
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import os
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score

# ── CONFIGURACIÓN ────────────────────────────────────────────

st.set_page_config(
    page_title="Riesgo de Lesión — ML",
    page_icon="🔬",
    layout="wide",
)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "futbol_monitoreo.db",
)

# ── FUNCIONES DE BASE DE DATOS (inline, sin importar metricas) ──

def _conectar():
    return sqlite3.connect(DB_PATH)


@st.cache_data(ttl=600)
def _cargar_carga():
    """Carga sesiones de entrenamiento con su training_load (RPE × minutos)."""
    conn = _conectar()
    df = pd.read_sql(
        """
        SELECT jugador_id, fecha, tipo_sesion,
               COALESCE(training_load, 0) AS tl
        FROM   carga_interna
        ORDER  BY jugador_id, fecha
        """,
        conn,
    )
    conn.close()
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


@st.cache_data(ttl=600)
def _cargar_wellness():
    """Carga el score de wellness diario (1-5, mayor = mejor bienestar)."""
    conn = _conectar()
    df = pd.read_sql(
        "SELECT jugador_id, fecha, wellness_total FROM wellness ORDER BY jugador_id, fecha",
        conn,
    )
    conn.close()
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


@st.cache_data(ttl=600)
def _cargar_lesiones():
    """Carga las fechas de inicio de cada lesión (para construir las etiquetas)."""
    conn = _conectar()
    df = pd.read_sql("SELECT jugador_id, fecha_inicio FROM lesiones", conn)
    conn.close()
    df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"])
    return df


@st.cache_data(ttl=600)
def _cargar_jugadores():
    conn = _conectar()
    df = pd.read_sql(
        "SELECT id, nombre || ' ' || apellido AS nombre, posicion FROM jugadores ORDER BY apellido",
        conn,
    )
    conn.close()
    return df


# ── DEFINICIÓN DE FEATURES ────────────────────────────────────

# Nombres de columnas usados internamente
FEATURES = [
    "acwr",
    "ewma_cronica",
    "carga_spike",
    "dias_consecutivos",
    "wellness_hoy",
    "tendencia_wellness",
    "dias_sin_descanso",
]

# Etiquetas legibles para mostrar en pantalla
NOMBRE_FEATURE = {
    "acwr":              "ACWR (carga aguda/crónica)",
    "ewma_cronica":      "Fatiga acumulada (EWMA 28d)",
    "carga_spike":       "Spike de carga vs media 28d",
    "dias_consecutivos": "Días consecutivos de entrenamiento",
    "wellness_hoy":      "Wellness de hoy (1-5)",
    "tendencia_wellness": "Tendencia wellness 7 días",
    "dias_sin_descanso": "Días entrenando en los últimos 7d",
}


# ── FEATURE ENGINEERING ──────────────────────────────────────

def _features_un_jugador(jug_id, carga_df, wellness_df):
    """
    Calcula las 7 features diarias para un jugador.
    Retorna un DataFrame indexado por fecha.
    """
    c = carga_df[carga_df["jugador_id"] == jug_id][["fecha", "tl"]].copy()
    if c.empty:
        return pd.DataFrame()

    c = c.sort_values("fecha").set_index("fecha")

    # Rellenar el rango completo de fechas (días sin sesión = 0 UA)
    idx_completo = pd.date_range(c.index.min(), c.index.max(), freq="D")
    c = c.reindex(idx_completo).fillna(0)

    # ── ACWR por método EWMA (Gabbett 2016) ──────────────────
    # Carga aguda = EWMA 7 días / Crónica = EWMA 28 días
    c["ewma_aguda"]   = c["tl"].ewm(span=7,  min_periods=1).mean()
    c["ewma_cronica"] = c["tl"].ewm(span=28, min_periods=1).mean()
    # Clippeamos entre 0.5–2.5 para evitar valores extremos con poca carga
    c["acwr"] = (c["ewma_aguda"] / (c["ewma_cronica"] + 1e-6)).clip(0.5, 2.5)

    # ── Spike de carga: UA de hoy vs media rolling 28d ───────
    media_28d = c["tl"].rolling(28, min_periods=1).mean()
    c["carga_spike"] = (c["tl"] / (media_28d + 1e-6)).clip(0, 5)

    # ── Días consecutivos de entrenamiento ───────────────────
    entrena = (c["tl"] > 0).astype(int).values
    consec  = np.zeros(len(entrena), dtype=int)
    for i in range(len(entrena)):
        consec[i] = (consec[i - 1] + 1 if i > 0 else 1) if entrena[i] else 0
    c["dias_consecutivos"] = consec

    # ── Días de entrenamiento en los últimos 7d ───────────────
    c["dias_sin_descanso"] = (c["tl"] > 0).rolling(7, min_periods=1).sum()

    # ── Wellness ─────────────────────────────────────────────
    w = wellness_df[wellness_df["jugador_id"] == jug_id][["fecha", "wellness_total"]].copy()
    if not w.empty:
        w = w.sort_values("fecha").set_index("fecha")
        # Forward-fill para días sin registro (p.ej. días de descanso)
        w = w.reindex(idx_completo, method="ffill")
        c["wellness_hoy"] = w["wellness_total"].fillna(3.0)
    else:
        c["wellness_hoy"] = 3.0  # valor neutral si no hay datos

    # Tendencia de wellness en los últimos 7 días
    # Pendiente positiva = mejorando; negativa = empeorando
    def _pendiente(serie):
        v = serie.dropna()
        if len(v) < 3:
            return 0.0
        return float(np.polyfit(np.arange(len(v)), v.values, 1)[0])

    c["tendencia_wellness"] = (
        c["wellness_hoy"].rolling(7, min_periods=3).apply(_pendiente, raw=False)
    )

    c["jugador_id"] = jug_id

    # Rellenar NaN residuales con 0 antes de retornar
    for col in FEATURES:
        c[col] = c[col].fillna(0)

    return (
        c[FEATURES + ["jugador_id"]]
        .reset_index()
        .rename(columns={"index": "fecha"})
    )


@st.cache_data(ttl=600)
def _features_todos(carga_df, wellness_df, jugadores_df):
    """Calcula features para todos los jugadores y los une en un solo DataFrame."""
    partes = [
        _features_un_jugador(jug_id, carga_df, wellness_df)
        for jug_id in jugadores_df["id"]
    ]
    partes = [p for p in partes if not p.empty]
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


def _crear_etiquetas(features_df, lesiones_df, horizonte=7):
    """
    Para cada (jugador_id, fecha) crea una etiqueta binaria:
    1 = hay una lesión que comienza en los próximos 'horizonte' días.
    Se hace con un merge para evitar loops lentos de Python.
    """
    # Cruzar cada observación con las lesiones del mismo jugador
    merged = features_df[["jugador_id", "fecha"]].merge(
        lesiones_df[["jugador_id", "fecha_inicio"]],
        on="jugador_id",
        how="left",
    )

    # Días entre la observación y el inicio de lesión
    delta = (merged["fecha_inicio"] - merged["fecha"]).dt.days

    # Es positivo si la lesión ocurre dentro del horizonte (pero no antes de hoy)
    merged["es_positivo"] = (delta > 0) & (delta <= horizonte)

    resultado = (
        merged.groupby(["jugador_id", "fecha"])["es_positivo"]
        .any()
        .reset_index()
    )

    features_con_label = features_df.merge(resultado, on=["jugador_id", "fecha"], how="left")
    features_con_label["es_positivo"] = (
        features_con_label["es_positivo"].fillna(False).astype(int)
    )
    return features_con_label["es_positivo"].values


# ── MODELO ML ────────────────────────────────────────────────

@st.cache_data(ttl=600)
def _entrenar_y_validar(_features_df, _lesiones_df):
    """
    Entrena el modelo final y valida con TimeSeriesSplit cronológico.
    Retorna (modelo, aucs, X_all, y_all, X_media, X_std).

    Los parámetros usan prefijo _ para que st.cache_data los hash
    correctamente cuando son DataFrames grandes.
    """
    if _features_df.empty:
        return None, [], None, None, None, None

    # Ordenar cronológicamente (requisito de TimeSeriesSplit)
    df = _features_df.sort_values(["fecha", "jugador_id"]).copy()
    y  = _crear_etiquetas(df, _lesiones_df)
    X  = df[FEATURES].values

    # Estadísticas para la explicabilidad posterior
    X_media = X.mean(axis=0)
    X_std   = X.std(axis=0) + 1e-6

    # Validación con 5 folds cronológicos
    tscv = TimeSeriesSplit(n_splits=5)
    aucs = []

    for train_idx, test_idx in tscv.split(X):
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]

        # Necesitamos al menos un positivo en el set de test para calcular AUC
        if y_te.sum() == 0:
            continue

        rf_fold = RandomForestClassifier(
            n_estimators=100,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        rf_fold.fit(X_tr, y_tr)
        prob = rf_fold.predict_proba(X_te)[:, 1]
        try:
            aucs.append(roc_auc_score(y_te, prob))
        except Exception:
            pass

    # Modelo final entrenado con todos los datos disponibles
    modelo_final = RandomForestClassifier(
        n_estimators=300,
        class_weight="balanced",
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )
    modelo_final.fit(X, y)

    return modelo_final, aucs, X, y, X_media, X_std


def _top_factores(modelo, x_jugador, X_media, X_std):
    """
    Calcula los 3 factores que más contribuyen al riesgo de un jugador.
    Combina importancia global del modelo con la desviación del jugador
    respecto a la media del plantel (aproximación local sin SHAP).
    """
    importancias  = modelo.feature_importances_
    desviaciones  = np.abs((x_jugador - X_media) / X_std)
    score_local   = importancias * desviaciones

    top_idx = np.argsort(score_local)[::-1][:3]
    return [
        {
            "nombre": NOMBRE_FEATURE[FEATURES[i]],
            "valor":  x_jugador[i],
            "media":  X_media[i],
            "score":  score_local[i],
        }
        for i in top_idx
    ]


# ── HELPERS DE VISUALIZACIÓN ─────────────────────────────────

def _color_riesgo(prob):
    """Retorna (hex_color, etiqueta) según nivel de riesgo."""
    if prob < 0.10:
        return "#1a7a3a", "RIESGO BAJO"
    if prob < 0.25:
        return "#b35900", "RIESGO MODERADO"
    return "#8b0000", "RIESGO ALTO"


def _badge_riesgo(prob):
    color, etiqueta = _color_riesgo(prob)
    pct = prob * 100
    st.markdown(
        f"""
        <div style="background:{color}22; border:2px solid {color};
                    border-radius:10px; padding:20px; text-align:center;">
            <div style="font-size:3rem; font-weight:700; color:{color};">
                {pct:.1f} %
            </div>
            <div style="color:{color}; font-size:1.25rem; font-weight:700;
                        letter-spacing:1px; margin-top:2px;">
                {etiqueta}
            </div>
            <div style="color:#666; font-size:0.82rem; margin-top:6px;">
                probabilidad estimada de lesión en los próximos 7 días
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _grafico_evolucion(fechas, probs, nombre):
    """Gráfico de línea con la evolución del riesgo en los últimos 14 días."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fechas,
        y=[p * 100 for p in probs],
        mode="lines+markers",
        line=dict(color="#1f77b4", width=2),
        marker=dict(size=9, color=[_color_riesgo(p)[0] for p in probs]),
        name="Riesgo (%)",
    ))
    fig.add_hrect(y0=0,  y1=10,  fillcolor="#1a7a3a", opacity=0.06, line_width=0)
    fig.add_hrect(y0=10, y1=25,  fillcolor="#f7c948", opacity=0.08, line_width=0)
    fig.add_hrect(y0=25, y1=100, fillcolor="#c0392b", opacity=0.06, line_width=0)
    fig.add_hline(y=25, line_dash="dash", line_color="#8b0000",
                  annotation_text="Umbral ALTO (25%)")
    fig.add_hline(y=10, line_dash="dash", line_color="#b35900",
                  annotation_text="Umbral MODERADO (10%)")
    fig.update_layout(
        title=f"Evolución del riesgo — {nombre}",
        xaxis_title="Fecha",
        yaxis_title="Riesgo (%)",
        yaxis=dict(range=[0, 100]),
        height=310,
        margin=dict(l=20, r=20, t=45, b=20),
    )
    return fig


def _grafico_importancias(modelo):
    """Barras horizontales con la importancia global de cada feature."""
    imp = pd.DataFrame({
        "feature": [NOMBRE_FEATURE[f] for f in FEATURES],
        "valor":   modelo.feature_importances_,
    }).sort_values("valor")

    fig = go.Figure(go.Bar(
        x=imp["valor"], y=imp["feature"],
        orientation="h",
        marker_color="#1f77b4",
    ))
    fig.update_layout(
        title="Importancia de features (modelo global)",
        xaxis_title="Importancia relativa",
        height=290,
        margin=dict(l=20, r=20, t=45, b=20),
    )
    return fig


def _grafico_heatmap(riesgo_df, jugadores_df):
    """Heatmap jugadores × días → nivel de riesgo (%)."""
    df = riesgo_df.merge(jugadores_df[["id", "nombre"]], left_on="jugador_id", right_on="id")
    df["dia"] = df["fecha"].dt.strftime("%d/%m")

    pivot = df.pivot_table(index="nombre", columns="dia", values="riesgo_pct", aggfunc="mean")

    # Ordenar columnas cronológicamente y filas por riesgo del último día
    col_order = sorted(pivot.columns, key=lambda s: pd.to_datetime(s, format="%d/%m", errors="coerce"))
    pivot = pivot[col_order]

    ultimo_dia = pivot.columns[-1]
    pivot = pivot.sort_values(ultimo_dia, ascending=False)

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[
            [0.00, "#1a7a3a"],
            [0.10, "#52b788"],
            [0.25, "#f7c948"],
            [0.50, "#e85d04"],
            [1.00, "#6e0000"],
        ],
        zmin=0, zmax=100,
        colorbar=dict(title="Riesgo (%)"),
        text=[
            [f"{v:.0f}%" if not np.isnan(v) else "" for v in row]
            for row in pivot.values
        ],
        texttemplate="%{text}",
        textfont={"size": 9},
    ))
    fig.update_layout(
        title="Heatmap de riesgo del plantel",
        xaxis=dict(side="top"),
        height=max(320, len(pivot) * 28 + 100),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


# ── PÁGINA PRINCIPAL ──────────────────────────────────────────

def main():
    st.title("🔬 Predicción de Riesgo de Lesión — ML")
    st.caption("Modelo: Random Forest · Basado en Rebelo et al. (2026) y Gabbett (2016)")

    # ── Carga de datos ────────────────────────────────────────
    carga_df     = _cargar_carga()
    wellness_df  = _cargar_wellness()
    lesiones_df  = _cargar_lesiones()
    jugadores_df = _cargar_jugadores()

    if carga_df.empty:
        st.error("Sin datos de carga interna en la base de datos.")
        return

    # ── Feature engineering (todos los jugadores) ─────────────
    with st.spinner("Calculando features de carga y wellness..."):
        features_df = _features_todos(carga_df, wellness_df, jugadores_df)

    if features_df.empty:
        st.error("No se pudieron calcular los features del modelo.")
        return

    # ── Entrenamiento y validación ────────────────────────────
    with st.spinner("Entrenando modelo Random Forest..."):
        modelo, aucs, X_all, y_all, X_media, X_std = _entrenar_y_validar(
            features_df, lesiones_df
        )

    if modelo is None:
        st.error("No hay datos suficientes para entrenar el modelo.")
        return

    # ── Predicciones para los últimos 14 días ─────────────────
    max_fecha    = features_df["fecha"].max()
    ventana_14d  = features_df[features_df["fecha"] >= max_fecha - pd.Timedelta(days=13)].copy()
    ventana_14d["riesgo_pct"] = modelo.predict_proba(ventana_14d[FEATURES].values)[:, 1] * 100

    # Predicción del día más reciente para ranking
    riesgo_hoy = (
        ventana_14d[ventana_14d["fecha"] == max_fecha]
        .merge(jugadores_df[["id", "nombre", "posicion"]], left_on="jugador_id", right_on="id")
        .sort_values("riesgo_pct", ascending=False)
    )

    # ── TABS ─────────────────────────────────────────────────
    tab_jugador, tab_equipo, tab_modelo = st.tabs(
        ["👤 Por jugador", "👥 Vista equipo", "🧠 Modelo y validación"]
    )

    # ────────────────────────────────────────────────────────
    # TAB 1 — POR JUGADOR
    # ────────────────────────────────────────────────────────
    with tab_jugador:
        opciones = dict(zip(riesgo_hoy["nombre"], riesgo_hoy["jugador_id"]))
        nombre_sel  = st.selectbox("Seleccionar jugador", list(opciones.keys()))
        jug_id_sel  = opciones[nombre_sel]

        fila_sel   = riesgo_hoy[riesgo_hoy["jugador_id"] == jug_id_sel].iloc[0]
        prob_hoy   = fila_sel["riesgo_pct"] / 100

        col_sem, col_fact = st.columns([1, 2])

        with col_sem:
            _badge_riesgo(prob_hoy)

        with col_fact:
            st.markdown("**Principales factores de riesgo**")
            x_jug = features_df[
                (features_df["jugador_id"] == jug_id_sel) &
                (features_df["fecha"] == max_fecha)
            ][FEATURES].values

            if len(x_jug) > 0:
                for i, f in enumerate(_top_factores(modelo, x_jug[0], X_media, X_std), 1):
                    dif   = f["valor"] - f["media"]
                    signo = "↑" if dif > 0 else "↓"
                    color = "#8b0000" if dif > 0 else "#1a7a3a"
                    st.markdown(
                        f"**{i}. {f['nombre']}**  \n"
                        f"Valor del jugador: `{f['valor']:.2f}` — "
                        f"media plantel: `{f['media']:.2f}` "
                        f"<span style='color:{color};font-weight:700;'>{signo}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Sin datos del jugador para la fecha más reciente.")

        # Gráfico de evolución del riesgo últimos 14 días
        st.divider()
        historial_jug = (
            ventana_14d[ventana_14d["jugador_id"] == jug_id_sel]
            .sort_values("fecha")
        )
        if not historial_jug.empty:
            st.plotly_chart(
                _grafico_evolucion(
                    historial_jug["fecha"].tolist(),
                    (historial_jug["riesgo_pct"] / 100).tolist(),
                    nombre_sel,
                ),
                use_container_width=True,
            )

    # ────────────────────────────────────────────────────────
    # TAB 2 — VISTA EQUIPO
    # ────────────────────────────────────────────────────────
    with tab_equipo:
        st.markdown("#### Ranking de riesgo del plantel")

        def _estilo_riesgo(v):
            if v >= 25:
                return "background-color:#f8d7da; color:#721c24; font-weight:700;"
            if v >= 10:
                return "background-color:#fff3cd; color:#856404; font-weight:700;"
            return "background-color:#d4edda; color:#155724;"

        tabla = riesgo_hoy[["nombre", "posicion", "riesgo_pct"]].copy()
        tabla.columns = ["Jugador", "Posición", "Riesgo (%)"]
        tabla["Riesgo (%)"] = tabla["Riesgo (%)"].round(1)

        st.dataframe(
            tabla.style.applymap(_estilo_riesgo, subset=["Riesgo (%)"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("#### Heatmap de riesgo — últimos 7 días")

        ventana_7d = features_df[
            features_df["fecha"] >= max_fecha - pd.Timedelta(days=6)
        ].copy()
        ventana_7d["riesgo_pct"] = (
            modelo.predict_proba(ventana_7d[FEATURES].values)[:, 1] * 100
        )
        st.plotly_chart(_grafico_heatmap(ventana_7d, jugadores_df), use_container_width=True)

    # ────────────────────────────────────────────────────────
    # TAB 3 — MODELO Y VALIDACIÓN
    # ────────────────────────────────────────────────────────
    with tab_modelo:
        st.markdown("#### Validación temporal — TimeSeriesSplit")

        col_auc, col_conf = st.columns([1, 2])

        with col_auc:
            if aucs:
                auc_medio = float(np.mean(aucs))
                color_auc = (
                    "#1a7a3a" if auc_medio >= 0.70
                    else "#b35900" if auc_medio >= 0.60
                    else "#8b0000"
                )
                st.markdown(
                    f"""
                    <div style="border:2px solid {color_auc}; border-radius:8px;
                                padding:18px; text-align:center;">
                        <div style="font-size:2.6rem; font-weight:700; color:{color_auc};">
                            {auc_medio:.3f}
                        </div>
                        <div style="color:#555; margin-top:4px;">
                            AUC-ROC medio ({len(aucs)} folds)
                        </div>
                        <div style="color:#888; font-size:0.82rem; margin-top:4px;">
                            {" / ".join(f"{a:.2f}" for a in aucs)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.caption("AUC = 1.0 → perfecto · AUC = 0.5 → azar")
            else:
                st.warning("Sin suficientes lesiones para calcular AUC válido.")

        with col_conf:
            n_pos   = int(y_all.sum()) if y_all is not None else 0
            n_total = len(y_all)       if y_all is not None else 0
            st.markdown(f"""
            **Configuración del modelo:**
            - Algoritmo: `RandomForestClassifier`
            - Árboles: 300 · `max_features='sqrt'`
            - Balanceo: `class_weight='balanced'`
            - Horizonte de predicción: 7 días
            - Validación: `TimeSeriesSplit` (5 folds cronológicos)

            **Datos de entrenamiento:**
            - Observaciones totales: **{n_total}**
            - Eventos positivos (lesión próxima): **{n_pos}** ({n_pos / max(n_total, 1) * 100:.1f} %)
            """)

        st.divider()
        st.markdown("#### Importancia de features")
        st.plotly_chart(_grafico_importancias(modelo), use_container_width=True)

        st.divider()
        st.warning(
            "⚠️ **Aviso clínico**  \n"
            "Este módulo es una herramienta de **apoyo a la decisión** basada en datos "
            "de carga y wellness. **No reemplaza el juicio clínico** del médico ni del "
            "fisioterapeuta.  \n"
            "Las predicciones tienen limitaciones inherentes al tamaño de la muestra, "
            "la calidad de los datos y la naturaleza multifactorial de las lesiones "
            "deportivas.  \n"
            "*Referencias: Rebelo et al. (2026); Gabbett TJ, BJSM (2016).*"
        )


# ── ENTRY POINT ───────────────────────────────────────────────

main()
