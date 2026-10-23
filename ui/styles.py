"""Professional academic styling for the Streamlit UI."""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:wght@600;700&display=swap');

html, body, [class*="css"]  {
  font-family: "Source Sans 3", "Segoe UI", sans-serif;
}
.stApp {
  background: linear-gradient(180deg, #eef2f6 0%, #f4f1ea 220px);
}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.hero {
  background: #13293d;
  color: #f4f1ea;
  padding: 1.4rem 1.6rem 1.2rem;
  border-radius: 14px;
  margin-bottom: 1.1rem;
  border: 1px solid #0c1b28;
}
.hero h1 {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.7rem;
  margin: 0 0 .35rem 0;
  color: #f4f1ea;
}
.hero p { margin: 0; color: #d5dee8; line-height: 1.45; }

.badge {
  display: inline-block;
  padding: .15rem .55rem;
  border-radius: 999px;
  font-size: .75rem;
  font-weight: 700;
  letter-spacing: .02em;
  margin-right: .35rem;
}
.badge-ok { background: #d7eee0; color: #14532d; }
.badge-warn { background: #fde7c7; color: #7c4a03; }
.badge-err { background: #f8d0d0; color: #7f1d1d; }
.badge-info { background: #d7e6f5; color: #1e4d7b; }
.badge-in { background: #d7eee0; color: #14532d; }
.badge-out { background: #f8d0d0; color: #7f1d1d; }
.badge-partial { background: #fde7c7; color: #7c4a03; }
.badge-uncertain { background: #e5e7eb; color: #374151; }

.card {
  background: #fff;
  border: 1px solid #d7d2c8;
  border-radius: 12px;
  padding: 1rem 1.1rem;
  margin-bottom: .85rem;
  box-shadow: 0 1px 2px rgba(19,41,61,.04);
}
.q-head {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.15rem;
  color: #13293d;
  margin-bottom: .3rem;
}
.subtle { color: #5b6573; font-size: .9rem; }
.confidential {
  border-left: 4px solid #c9a227;
  padding: .6rem .9rem;
  background: #fff8e8;
  border-radius: 0 8px 8px 0;
  margin: .6rem 0 1rem;
}
</style>
"""


def inject() -> None:
    import streamlit as st

    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    import streamlit as st

    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'
