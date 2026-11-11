"""Yiriwa Business visual theme for the Streamlit interface."""

from __future__ import annotations

from html import escape

import streamlit as st


def apply_yiriwa_theme() -> None:
    """Apply the dark, mobile-first Yiriwa Business design tokens."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

        :root {
            color-scheme: dark;
            --yb-bg: #05070c;
            --yb-surface: #0b0f1a;
            --yb-panel: #131a2b;
            --yb-line: rgba(255,255,255,.09);
            --yb-text: #f2f5fa;
            --yb-muted: #8a93a8;
            --yb-faint: #5f6a80;
            --yb-green: #00e5a0;
            --yb-green-soft: rgba(0,229,160,.10);
            --yb-coral: #ff5c72;
            --yb-blue: #4d8dff;
            --yb-violet: #8b5cf6;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background: var(--yb-bg);
            color: var(--yb-text);
            font-family: Inter, system-ui, sans-serif;
        }
        [data-testid="stAppViewContainer"] > .main {
            background:
              radial-gradient(900px 480px at 12% -5%, rgba(0,229,160,.075), transparent 60%),
              radial-gradient(900px 500px at 92% 8%, rgba(77,141,255,.07), transparent 62%),
              var(--yb-bg);
        }
        [data-testid="stHeader"] { background: rgba(5,7,12,.72); }
        [data-testid="stMainBlockContainer"] {
            max-width: 1480px;
            padding: 1.6rem clamp(1rem, 3vw, 2.8rem) 3.5rem;
        }
        [data-testid="stSidebar"] {
            background: rgba(11,15,26,.96);
            border-right: 1px solid var(--yb-line);
        }
        [data-testid="stSidebar"] > div:first-child { background: transparent; }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
            font-family: "Space Grotesk", Inter, sans-serif;
        }
        h1, h2, h3, h4, p, label, span, div { font-family: Inter, system-ui, sans-serif; }
        h1, h2, h3 { letter-spacing: -.025em; }
        h1, h2 { font-family: "Space Grotesk", Inter, sans-serif; }
        h1 { font-size: clamp(1.65rem, 3vw, 2.25rem); }
        h2 { font-size: 1.35rem; }
        h3 { font-size: 1.05rem; }
        [data-testid="stCaptionContainer"], .stCaption { color: var(--yb-muted); }

        .yb-brand {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
            padding: 1.1rem 1.25rem;
            margin: 0 0 1.2rem;
            border: 1px solid var(--yb-line);
            border-radius: 22px;
            background: linear-gradient(115deg, rgba(255,255,255,.055), rgba(255,255,255,.018));
            box-shadow: 0 18px 45px rgba(0,0,0,.16);
        }
        .yb-brand-main { display:flex; align-items:center; gap: .9rem; min-width: 220px; }
        .yb-mark {
            display:flex; align-items:center; justify-content:center; flex:none;
            width:48px; height:48px; border-radius:15px;
            color:#04150d; background:linear-gradient(135deg,#2bffb3,#00b37d);
            box-shadow:0 9px 24px rgba(0,229,160,.22);
        }
        .yb-brand-name {
            color:var(--yb-text); font:700 1.32rem "Space Grotesk",sans-serif;
            letter-spacing:-.04em; line-height:1.05;
        }
        .yb-brand-name span { color:var(--yb-green); }
        .yb-brand-sub { color:var(--yb-muted); font-size:.78rem; margin-top:.28rem; }
        .yb-brand-meta { display:flex; align-items:center; gap:.45rem; flex-wrap:wrap; }
        .yb-chip {
            display:inline-flex; align-items:center; gap:.35rem;
            padding:.42rem .72rem; border-radius:99px;
            border:1px solid var(--yb-line); background:rgba(255,255,255,.035);
            color:#c6cfdf; font-size:.7rem; font-weight:600;
        }
        .yb-chip-live { border-color:rgba(0,229,160,.28); color:#9ff6d6; background:var(--yb-green-soft); }

        [data-testid="stMetric"] {
            padding: 1rem 1.05rem;
            border: 1px solid var(--yb-line);
            border-radius: 19px;
            background: linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.02));
            min-height: 112px;
        }
        [data-testid="stMetricLabel"] { color:var(--yb-muted); font-size:.78rem; font-weight:600; }
        [data-testid="stMetricValue"] {
            color:var(--yb-text); font:700 clamp(1.25rem, 2vw, 1.8rem) "Space Grotesk",sans-serif;
            letter-spacing:-.03em;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color:var(--yb-line); border-radius:20px;
            background:rgba(255,255,255,.025);
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap:.35rem; border:1px solid var(--yb-line); border-radius:17px;
            padding:.38rem; background:rgba(11,15,26,.88);
            flex-wrap:wrap;
        }
        [data-testid="stTabs"] button[data-baseweb="tab"] {
            min-height:42px; padding:.55rem .9rem; border-radius:12px;
            color:var(--yb-muted); font-size:.82rem; font-weight:650;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color:#04150d !important; background:linear-gradient(135deg,#2bffb3,#00c98a);
        }
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background:transparent; }
        [data-testid="stTabs"] [data-baseweb="tab-border"] { background:transparent; }

        .stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
            min-height:42px; border-radius:13px; border:1px solid rgba(0,229,160,.24);
            color:#04150d; font-weight:700;
            background:linear-gradient(135deg,#2bffb3,#00c98a);
            box-shadow:0 7px 19px rgba(0,229,160,.13);
        }
        .stButton > button:hover, .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            border-color:rgba(0,229,160,.6); color:#04150d; filter:brightness(1.04);
        }
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input, [data-baseweb="select"] > div,
        [data-testid="stDateInput"] input {
            background:rgba(255,255,255,.045); border-color:var(--yb-line);
            color:var(--yb-text); border-radius:12px;
        }
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            border:1px solid var(--yb-line); border-radius:15px; overflow:hidden;
        }
        [data-testid="stAlert"] { border-radius:14px; }
        hr { border-color:var(--yb-line); }
        a { color:var(--yb-green); }
        [data-testid="stExpander"] {
            border:1px solid var(--yb-line); border-radius:15px; background:rgba(255,255,255,.02);
        }
        @media (max-width: 760px) {
            [data-testid="stMainBlockContainer"] { padding:1rem .8rem 2rem; }
            .yb-brand { padding:.9rem; border-radius:17px; }
            .yb-brand-meta { width:100%; }
            [data-testid="stTabs"] [data-baseweb="tab-list"] { flex-wrap:nowrap; overflow-x:auto; }
            [data-testid="stTabs"] button[data-baseweb="tab"] { white-space:nowrap; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header(
    *,
    user_name: str,
    workspace_name: str,
    role: str,
    company_name: str | None,
) -> None:
    """Render a compact branded header without trusting user-supplied HTML."""
    user = escape(user_name)
    workspace = escape(workspace_name)
    company = escape(company_name or "Aucune entreprise active")
    active_role = escape(role)
    st.markdown(
        f"""
        <header class="yb-brand">
          <div class="yb-brand-main">
            <div class="yb-mark" aria-hidden="true">
              <svg width="25" height="25" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                   stroke-linejoin="round">
                <path d="M4 17.5 10 11l4 4 6.5-7.5"></path>
                <path d="M15 7.5h5.5V13"></path>
              </svg>
            </div>
            <div>
              <div class="yb-brand-name">Yiriwa <span>Business</span></div>
              <div class="yb-brand-sub">Pilotage financier · PME et activités multi-sites</div>
            </div>
          </div>
          <div class="yb-brand-meta">
            <span class="yb-chip">Workspace · {workspace}</span>
            <span class="yb-chip">Entreprise · {company}</span>
            <span class="yb-chip">Rôle · {active_role}</span>
            <span class="yb-chip yb-chip-live">Connecté · {user}</span>
          </div>
        </header>
        """,
        unsafe_allow_html=True,
    )
