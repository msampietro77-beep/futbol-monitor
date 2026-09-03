"""
styles.py
=========
Sistema de estilos unificado — Dark mode EQUIPOPHYSICAL.

Cómo usar: al inicio de app.py y de cada page (después de
st.set_page_config), importar y llamar:

    from styles import apply_styles
    apply_styles()

Esto inyecta el CSS oscuro con acentos naranja en toda la página.
"""

import streamlit as st

CSS = """
<style>
/* FONDO Y ESTRUCTURA */
.main { background-color: #0f1117; }
.block-container {
    padding: 2rem 2.5rem;
    max-width: 1200px;
}

/* SIDEBAR */
section[data-testid="stSidebar"] {
    background-color: #161824;
    border-right: 1px solid #2d3148;
}

/* TÍTULOS DE SECCIÓN con barra naranja */
.ep-section-title {
    border-left: 3px solid #F47920;
    padding-left: 12px;
    font-size: 1rem;
    font-weight: 600;
    color: #f0f2f6;
    letter-spacing: 0.3px;
    margin-bottom: 1rem;
    font-family: 'Inter', sans-serif;
}

/* BADGE DE ÁREA */
.ep-badge {
    display: inline-block;
    background: #F47920;
    color: white;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 3px 10px;
    border-radius: 2px;
    margin-bottom: 8px;
}

.ep-badge-medico    { background: #2d6a9f; }
.ep-badge-performance { background: #F47920; }
.ep-badge-nutricion { background: #1a9e5c; }

/* CARDS */
.ep-card {
    background: #1e2130;
    border: 1px solid #2d3148;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 16px;
}

/* MÉTRICAS — número en naranja */
[data-testid="stMetricValue"] {
    color: #F47920;
    font-weight: 700;
    font-size: 2rem;
}
[data-testid="stMetricLabel"] {
    color: #8b92a8;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* TABLAS */
[data-testid="stDataFrame"] {
    border: 1px solid #2d3148;
    border-radius: 6px;
    overflow: hidden;
}
thead tr th {
    background-color: #161824 !important;
    color: #8b92a8 !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid #2d3148 !important;
}
tbody tr:hover td {
    background-color: #252840 !important;
}

/* ALERTAS sin emojis */
.ep-alerta-roja {
    background: rgba(214, 48, 49, 0.12);
    border-left: 3px solid #d63031;
    padding: 12px 16px;
    border-radius: 0 6px 6px 0;
    margin-bottom: 8px;
}
.ep-alerta-naranja {
    background: rgba(244, 121, 32, 0.12);
    border-left: 3px solid #F47920;
    padding: 12px 16px;
    border-radius: 0 6px 6px 0;
    margin-bottom: 8px;
}
.ep-alerta-verde {
    background: rgba(26, 158, 92, 0.12);
    border-left: 3px solid #1a9e5c;
    padding: 12px 16px;
    border-radius: 0 6px 6px 0;
    margin-bottom: 8px;
}

/* BOTONES */
.stButton > button {
    background: #F47920;
    color: white;
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.5px;
    padding: 8px 20px;
    transition: background 0.2s;
}
.stButton > button:hover {
    background: #C85E10;
}

/* SELECTBOX Y INPUTS */
[data-testid="stSelectbox"] > div,
[data-testid="stTextInput"] > div > div {
    background: #1e2130;
    border: 1px solid #2d3148;
    border-radius: 4px;
    color: #f0f2f6;
}

/* DIVIDER */
hr {
    border-color: #2d3148;
    margin: 24px 0;
}

/* SCROLLBAR */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0f1117; }
::-webkit-scrollbar-thumb {
    background: #2d3148;
    border-radius: 3px;
}
</style>
"""


def apply_styles():
    """Inyecta el CSS del sistema de diseño oscuro EQUIPOPHYSICAL."""
    st.markdown(CSS, unsafe_allow_html=True)
