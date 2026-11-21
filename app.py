"""AI Case Differential-Diagnosis Assistant (Streamlit).
Run:  streamlit run app.py
Everything a doctor needs to change - API key, provider, department, data
types, language, house rules - is in the Settings tab. Nothing here needs to
be edited by hand.
"""
import html
import json
import os
import re as _re
import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

import config
import files
import prompts
import knowledge
import providers
from logger import log_event

def _stretch() -> dict:
    """Streamlit 1.50 replaced use_container_width=True with width="stretch"; older
    versions only know the old spelling. One helper keeps both working."""
    try:
        v = tuple(int(x) for x in st.__version__.split(".")[:2])
    except Exception:
        v = (0, 0)
    return {"width": "stretch"} if v >= (1, 50) else {"use_container_width": True}


STRETCH = _stretch()

st.set_page_config(page_title="AI Case Differential Assistant", page_icon="🩺",
                   layout="wide", initial_sidebar_state="expanded")

def load_s() -> dict:
    """Settings: a file on this computer normally; on a shared server (PUBLIC_MODE)
    only this visitor's browser session, so nobody can see or change anyone else's."""
    if config.PUBLIC_MODE:
        if "_s" not in st.session_state:
            st.session_state["_s"] = config.default_settings()
            if st.session_state["_s"].get("provider") == "ollama":
                st.session_state["_s"]["provider"] = "groq"
        return dict(st.session_state["_s"])
    return config.load_settings()


def save_s(s: dict) -> None:
    if config.PUBLIC_MODE:
        st.session_state["_s"] = dict(s)
    else:
        save_s(s)


settings = load_s()


def _auto_engine(s: dict):
    """If the saved engine is a cloud one with no key, but Ollama is running on this
    computer with a model installed, use Ollama instead of showing an error.
    Returns (settings, name_of_the_engine_it_replaced_or_None)."""
    p = s.get("provider", "groq")
    if config.PUBLIC_MODE or p == "ollama" or config.has_key(s, p):
        return s, None
    try:
        if providers.ollama_version(s) and providers.list_ollama_models_detailed(s):
            return {**s, "provider": "ollama"}, p
    except Exception:
        pass
    return s, None


settings, AUTO_FROM = _auto_engine(settings)
LANG = settings.get("language", "ar") if settings.get("language") in ("ar", "en") else "en"
RTL = LANG == "ar"
# The language the AI WRITES in, separate from the interface language: a small
# local model may reason well but have no usable Arabic (qwen2.5 slips into
# Chinese), so a doctor can keep an Arabic interface and English AI output.
AI_LANG = settings.get("ai_language", "auto")
if AI_LANG not in ("ar", "en"):
    AI_LANG = LANG


def tr(en: str, ar: str) -> str:
    return ar if RTL else en


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# Material Symbols geometry - the same icon family Streamlit itself uses for a
# widget's icon= parameter, so a glyph in markup we inject matches a glyph
# Streamlit draws. Inlined rather than loaded as a font: no extra request, no
# flash of the ligature text before it resolves, and it prints reliably.
ICON_PATHS = {
    "warning": "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z",
    "open_in_new": ("M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7z"
                    "M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"),
}


def icon(name: str, label: str = "") -> str:
    """One icon as inline SVG. fill=currentColor, so it takes the colour and
    size of the text it sits in and needs no palette of its own. An icon that
    repeats a nearby word is decoration, so each one here has a job: `warning`
    is the non-colour cue for a must-exclude diagnosis (colour alone fails a
    red-green colour-blind reader), `open_in_new` says a link leaves the app."""
    return (f"<svg class='ic' viewBox='0 0 24 24' role='img' aria-label='{html.escape(label)}' "
            f"focusable='false'><path d='{ICON_PATHS[name]}'/></svg>")


def bidi(x) -> str:
    """Isolate a Latin run (a model name, a file name, a PMID) that sits inside
    Arabic text, so the Arabic around it keeps its order and the Latin keeps
    its own. U+2068/U+2069 are the Unicode isolate marks: unlike an HTML <bdi>
    they also work in a widget label or a caption, where no HTML is rendered."""
    return f"⁨{x}⁩"


def model_label() -> str:
    """The model that will actually answer, so nobody has to guess whether the
    next answer takes two seconds on the cloud or a minute on this laptop."""
    prov = settings.get("provider", "groq")
    if prov == "ollama":
        return settings.get("ollama_model") or "?"
    if prov == "gemini":
        return settings.get("gemini_model") or "?"
    if prov == "openai":
        return settings.get("openai_model") or "?"
    return settings.get("groq_model") or "?"


# ====================================================================== style
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&family=Inter:wght@400;500;600;700&display=swap');
/* One brand colour (--deep) and a neutral ramp. Colour is spent only where it
   carries clinical meaning: --red for a must-exclude diagnosis, --amber for a
   caution panel. Likelihood is a word, so it does not also need a hue. */
:root{--ink:#16302E;--deep:#0B4F4A;--line:#D9E2E0;--card:#FFFFFF;--bg:#F8FAFA;
 --tint:#EFF4F3;--muted:#5B7370;--amber:#8A5B00;--amber-bg:#FDF6E7;--amber-line:#EBDCB8;
 --red:#B3301D;--red-bg:#FCF1EF;--red-line:#E8C9C2}
.stApp,.stApp p,.stApp label,.stApp li,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,.stApp input,.stApp textarea,.stApp button,.stApp a{font-family:'Inter','Cairo',system-ui,sans-serif}
.stApp{color:var(--ink)}
.stApp{background:var(--bg)}
#MainMenu,footer,header[data-testid="stHeader"]{visibility:hidden;height:0}
.block-container{padding-top:1.2rem;padding-bottom:4rem;max-width:1180px}
section[data-testid="stSidebar"]{background:var(--deep)}
section[data-testid="stSidebar"] *{color:#E9F2F0 !important}
section[data-testid="stSidebar"] .stRadio label,section[data-testid="stSidebar"] p{font-size:.9rem}
.side-brand{font-weight:800;font-size:1.15rem;letter-spacing:.2px;margin-bottom:.2rem}
.side-sub{opacity:.75;font-size:.8rem;margin-bottom:1rem}
.wordmark{font-size:.82rem;font-weight:700;color:var(--deep);text-transform:none;
 border-bottom:1px solid var(--line);padding-bottom:.45rem;margin-bottom:.7rem}
.apptitle{margin:.1rem 0 .15rem;padding:0;font-size:1.6rem;font-weight:700;color:var(--deep)}
.appsub{margin:0 0 1rem;color:var(--muted);font-size:.93rem;max-width:860px}
.disclaimer{background:var(--amber-bg);border:1px solid var(--amber-line);color:var(--amber);
 border-radius:8px;padding:.65rem 1rem;font-size:.85rem;margin-bottom:1.1rem}
.stTabs [data-baseweb="tab-list"]{gap:.35rem;background:#fff;padding:.3rem;border-radius:8px;
 border:1px solid var(--line)}
.stTabs [data-baseweb="tab"]{border-radius:6px;padding:.5rem 1rem;font-weight:600;height:auto}
.stTabs [aria-selected="true"]{background:var(--deep)}
.stTabs [aria-selected="true"],.stTabs [aria-selected="true"] *{color:#fff !important}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:1.1rem 1.3rem;
 margin:1rem 0}
.card h3{margin:.1rem 0 .4rem;font-size:1.08rem;font-weight:700}
/* a must-exclude diagnosis is the one thing on this page that earns a colour */
.card.dx{border-inline-start:4px solid var(--line)}
.card.dx.must{border-inline-start-color:var(--red);background:var(--red-bg)}
.dx-head{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap}
.rank{background:var(--deep);color:#fff;border-radius:50%;width:2rem;height:2rem;display:inline-flex;
 align-items:center;justify-content:center;font-weight:700;flex:none}
.dx-name{font-weight:700;font-size:1.08rem}
.chip{display:inline-block;border-radius:999px;padding:.12rem .65rem;font-size:.74rem;font-weight:700;
 background:var(--tint);color:var(--deep);margin-inline-end:.3rem;border:1px solid var(--line)}
.chip.must{background:var(--red);color:#fff;border-color:var(--red)}
.chip.ev{background:#fff;color:var(--muted)}
.meter{height:4px;background:var(--line);margin:.6rem 0 .8rem;overflow:hidden}
.meter>i{display:block;height:100%;background:var(--deep)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:760px){.two{grid-template-columns:1fr}}
.lbl{font-size:.72rem;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-weight:700;margin-bottom:.2rem}
.card ul{margin:.1rem 0 .3rem;padding-inline-start:1.1rem}
.card li{margin:.12rem 0;font-size:.93rem}
.test{background:var(--tint);border-radius:6px;padding:.55rem .8rem;margin-top:.5rem;font-size:.92rem}
.alert{background:var(--red-bg);border:1px solid var(--red-line);color:var(--red);border-radius:8px;padding:.8rem 1rem;margin:.8rem 0}
.note{background:#fff;border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:.8rem 0}
/* Icons size themselves from the text they sit in and inherit its colour, so
   they never need a palette entry and never go stale against the theme. */
.ic{width:1em;height:1em;fill:currentColor;vertical-align:-.13em;flex:none}
.chip .ic{margin-inline-end:.3em;width:.95em;height:.95em}
.art a .ic{margin-inline-start:.3em;width:.85em;height:.85em;opacity:.65}
.art a{font-weight:700;color:var(--deep);text-decoration:none}
.art a:hover{text-decoration:underline}
.art a:hover .ic{opacity:1}
.art .meta{color:var(--muted);font-size:.8rem}
.imgfind{background:#fff;border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:.8rem 0}
div.stButton>button{border-radius:6px;font-weight:600;border:1px solid var(--line);padding:.5rem 1.1rem}
div.stButton>button[kind="primary"],div.stDownloadButton>button[kind="primary"]{background:var(--deep);color:#fff;border:1px solid var(--deep)}
div.stButton>button:hover{border-color:var(--deep);color:var(--deep)}
div.stButton>button[kind="primary"],div.stButton>button[kind="primary"] *,div.stDownloadButton>button[kind="primary"] *{color:#fff !important}
div.stButton>button[kind="primary"]:hover{filter:brightness(1.12)}
.stTextArea textarea,.stTextInput input{border-radius:6px}
[data-testid="stFileUploader"] section{border-radius:8px;border:1px solid var(--line);background:#fff}
[data-testid="stExpander"]{border-radius:8px;border:1px solid var(--line);background:#fff}
.empty{text-align:center;color:var(--muted);padding:2.2rem 1rem}

/* knowledge-source cards and the image reader reuse .card/.chip/.lbl; these are the only additions */
.card.art{padding:.7rem 1rem;margin:.5rem 0 .2rem}
.card.art .chip{margin-inline-end:.4rem}
.stTabs [data-baseweb="tab-panel"]{padding-top:1rem}
[data-testid="stImage"] img{border-radius:8px;border:1px solid var(--line)}

/* ---------------------------------------------------------------- printing
   What a doctor keeps on paper: the differential as a plain document, no app
   chrome, nothing tinted, nothing split across a page break, and every link
   written out so a citation is still a citation on paper. For the whole case
   in one document (summary + differential + evidence together), use the
   Report button instead - a tab only prints what is on screen. */
@media print{
  @page{margin:16mm 14mm}
  section[data-testid="stSidebar"],.stTabs [data-baseweb="tab-list"],
  [data-testid="stFileUploader"],div.stButton,div.stDownloadButton,
  [data-testid="stToolbar"],[data-testid="stStatusWidget"],[data-testid="stHeader"],
  .stTextArea,.stCheckbox,.empty{display:none !important}
  .stApp{background:#fff !important}
  .block-container{max-width:none !important;padding:0 !important}
  .card,.note,.alert,.imgfind,.test,.disclaimer{box-shadow:none !important;
   background:#fff !important;border:1px solid #9AA8A6 !important;break-inside:avoid}
  .card.dx.must{border-inline-start:4px solid #000 !important}
  .chip{border:1px solid #666 !important;background:#fff !important;color:#000 !important}
  .chip.must{font-weight:700}
  /* the must-exclude mark must survive a black-and-white print, where the red
     border and red chip it normally rides on are gone */
  .ic{fill:#000 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .meter{display:none !important}
  .rank{background:#000 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h3,h4,.dx-head{break-after:avoid}
  .art a{color:#000 !important}
  .art a[href]:after{content:" (" attr(href) ")";font-size:.72em;color:#444;word-break:break-all}
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
RTL_CSS = """
<style>
/* 1. Right-to-left layout for the page and the sidebar. 'start' instead of
   'right' so a block that resolves to LTR is not dragged to the wrong edge. */
.block-container,section[data-testid="stSidebar"]>div{direction:rtl;text-align:start}

/* 2. Dropdown menus, tooltips and toasts are rendered by Streamlit into
   portals attached to <body>, outside .block-container, so they need the
   direction set on them explicitly or they stay left-to-right. */
div[data-baseweb="popover"],div[data-baseweb="menu"],div[data-baseweb="tooltip"],
div[data-baseweb="select"] ul,[role="tooltip"],[role="listbox"],
[data-testid="stTooltipContent"],[data-testid="stToast"],[data-testid="stNotification"]
 {direction:rtl;text-align:start}

/* 3. The important one: let every paragraph choose its own direction from its
   first strong character. Arabic reads right-to-left, English left-to-right,
   in the same page - so a full stop, a parenthesis or a unit like 1600 IU/L
   stays attached to the words it belongs to instead of jumping to the far
   end. This is what keeps a mixed Arabic/English case readable, and it is
   needed because the interface language and the AI's language are separate. */
.stApp p,.stApp li,.stApp label,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,
.stApp textarea,.stApp input,.stApp .stMarkdown,[data-testid="stMarkdownContainer"],
.card,.dx-name,.test,.note,.alert,.imgfind,.lbl,.disclaimer,.appsub,.empty
 {unicode-bidi:plaintext;text-align:start}

/* 4. Blocks that are always English (PubMed records, the raw text pulled out
   of an uploaded file, abstracts) are pinned left-to-right as whole blocks. */
.art,.art *,.stApp pre,.stApp code,.stApp [data-testid="stText"]
 {direction:ltr;text-align:left;unicode-bidi:isolate}

/* 5. Arabic typeface */
.stApp,.stApp p,.stApp label,.stApp li,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,
.stApp input,.stApp textarea,.stApp button,.stApp a{font-family:'Cairo','Inter',sans-serif}
</style>
"""
if RTL:
    st.markdown(RTL_CSS, unsafe_allow_html=True)

# --------------------------------------------------------------- session state
for k, v in (("dd_result", None), ("evidence", {}), ("notes", {}), ("kb_errors", {}),
             ("img_results", []), ("txt_results", []), ("mgmt", None), ("mgmt_cmp", None), ("mgmt_src", []), ("img_notes", {}), ("img_count", 0), ("file_note", "")):
    st.session_state.setdefault(k, v)

# ===================================================================== sidebar
with st.sidebar:
    st.markdown(f"<div class='side-brand'>{tr('Case DD Assistant', 'مساعد التشخيص التفريقي')}</div>"
                f"<div class='side-sub'>{tr('Teaching & second-opinion tool', 'أداة تعليمية ورأي ثانٍ')}</div>",
                unsafe_allow_html=True)
    new_lang = st.radio("Language / اللغة", ["ar", "en"], index=["ar", "en"].index(LANG), horizontal=True,
                        format_func=lambda x: {"ar": "العربية", "en": "English"}[x])
    if new_lang != LANG:
        save_s({**settings, "language": new_lang})
        st.rerun()
    ai_opts = ["auto", "ar", "en"]
    new_ai_lang = st.radio(
        tr("AI writes in", "لغة إجابة الذكاء"), ai_opts,
        index=ai_opts.index(settings.get("ai_language", "auto") if settings.get("ai_language") in ai_opts else "auto"),
        horizontal=True,
        format_func=lambda x: {"auto": tr("same", "نفسها"), "ar": "العربية", "en": "English"}[x],
        help=tr("Small local models often have weak Arabic and slip into another "
                "language. Choose English here to keep this interface Arabic while "
                "the AI answers in English.",
                "النماذج المحلية الصغيرة عربيتها ضعيفة وقد تنزلق إلى لغة أخرى. "
                "اختر English ليبقى هذا الواجهة بالعربية وتأتي إجابة الذكاء بالإنجليزية."))
    if new_ai_lang != settings.get("ai_language", "auto"):
        save_s({**settings, "ai_language": new_ai_lang})
        st.rerun()
    dep_name = settings.get("department_other") if settings.get("department") == "Other" else settings.get("department")
    prov_label = {"groq": "Groq", "gemini": "Gemini", "openai": "OpenAI", "ollama": "Ollama (local)"}[settings.get("provider", "groq")]
    st.markdown("---")
    st.markdown(
        f"{tr('Model', 'النموذج')}: **{bidi(esc(prov_label) + ' · ' + esc(model_label()))}**  \n"
        f"{tr('Department', 'القسم')}: **{bidi(esc(dep_name or tr('not set', 'غير محدد')))}**",
        unsafe_allow_html=True)
    st.caption(tr("Change these in the Settings tab.", "يمكن تغييرها من تبويب الإعدادات."))
    if config.PUBLIC_MODE:
        st.info(tr("Shared demo: do not enter patient names or ID numbers. Your text is sent to the AI provider you choose (Groq, Gemini or OpenAI). "
                   "Nothing is saved on this server.",
                   "نسخة مشتركة: لا تُدخل أسماء المرضى أو أرقام هويتهم. يُرسل نصك إلى مزوّد الذكاء الذي تختاره (Groq أو Gemini أو OpenAI). "
                   "لا يُحفظ شيء على هذا الخادم."))
    st.caption(f"v{config.VERSION} · MIT · " + tr("teaching tool, not medical advice", "أداة تعليمية وليست نصيحة طبية"))

# ====================================================================== header
org = (settings.get("org_name") or "").strip()
if org:
    # A wordmark says who this belongs to. One line, brand colour, a hairline
    # under it - the way an institution puts its name on a document, rather
    # than a picture competing with the title underneath.
    st.markdown(f"<div class='wordmark'>{bidi(esc(org)) if RTL else esc(org)}</div>",
                unsafe_allow_html=True)
st.markdown(f"<h1 class='apptitle'>{tr('Differential-Diagnosis Assistant', 'مساعد التشخيص التفريقي')}</h1>"
            f"<p class='appsub'>{tr('Enter a case as text or attach a file (Word, PowerPoint, PDF, Excel, images); the differential is returned ranked, with evidence from PubMed, guidelines and your own library for each diagnosis.', 'أدخل الحالة كنص أو أرفق ملفاً (Word، PowerPoint، PDF، Excel، صور)؛ يُعاد التشخيص التفريقي مرتباً مع أدلة من PubMed والإرشادات ومكتبتك لكل تشخيص.')}</p>",
            unsafe_allow_html=True)
st.markdown(f"<div class='disclaimer'>⚠️ {esc(config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN)}</div>",
            unsafe_allow_html=True)

if AUTO_FROM:
    nm_ = {"groq": "Groq", "gemini": "Gemini", "openai": "OpenAI"}.get(AUTO_FROM, AUTO_FROM)
    cA, cB = st.columns([4, 1], vertical_alignment="center")
    cA.info(tr(f"No {nm_} key is set, so the app is using Ollama on this computer (free, no limits). ",
               f"لا يوجد مفتاح {nm_}، لذا يستخدم التطبيق Ollama على هذا الحاسوب (مجاني بلا حدود). "))
    if cB.button(tr("Keep Ollama", "ابقَ على Ollama"), key="keep_ollama"):
        save_s(settings)
        st.rerun()

prov = settings.get("provider")
if prov != "ollama" and not config.has_key(settings, prov):
    st.info(tr("No API key set yet. Open the Settings tab to add one (2 minutes).",
               "لم يتم إدخال مفتاح API بعد. اذهب إلى تبويب الإعدادات لإضافته (دقيقتان)."))

PROV_OPTIONS = ["groq", "gemini", "openai"] if config.PUBLIC_MODE else ["groq", "gemini", "openai", "ollama"]

tab1, tab_img, tab_mg, tab2, tab3, tab5 = st.tabs([
    tr("Case", "الحالة"), tr("Identify", "ما هذا؟"), tr("Management", "خطة العلاج"), tr("AI differential", "التشخيص التفريقي"),
    tr("Evidence", "الأدلة والمصادر"), tr("Settings", "الإعدادات")])

# Load the local model into memory in the background, once per browser session,
# so the first real answer does not also pay the model's start-up time.
if settings.get("provider") == "ollama" and not st.session_state.get("_preloaded"):
    st.session_state["_preloaded"] = True
    providers.preload_ollama(settings)


# ===================================================================== helpers
def build_system_prompt(has_images: bool) -> str:
    return (prompts.differential_prompt(settings.get("max_differentials", 8)) + "\n"
            + prompts.lang_rule(AI_LANG) + "\n"
            + prompts.department_rule(settings.get("department", ""), settings.get("department_other", ""),
                                      settings.get("specialty_hint", "")) + "\n"
            + prompts.data_types_rule(settings.get("data_types", []), has_images) + "\n"
            + prompts.custom_rule(settings.get("custom_instructions", "")))


def dedupe_dd(res: dict) -> dict:
    """Small models sometimes list the same diagnosis twice - keep the first, renumber."""
    seen, out = set(), []
    for d in res.get("differential", []) or []:
        k = " ".join(str(d.get("diagnosis", "")).lower().split())
        if k and k not in seen:
            seen.add(k)
            out.append(d)
    for i, d in enumerate(out, 1):
        d["rank"] = i
    res["differential"] = out
    return res


def ul(items):
    items = [i for i in (items or []) if i]
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else "<ul><li>—</li></ul>"


# ------------------------------------------------- engine check + vision help
def engine_status() -> dict:
    """Is the chosen AI engine ready, in words a doctor can act on?
    -> {"ok": bool, "lines": [(state, text)]}  state: ok | bad | opt"""
    p = settings.get("provider", "groq")
    lines = []
    if p == "ollama":
        ver = providers.ollama_version(settings)
        det = providers.list_ollama_models_detailed(settings)
        names = [m["name"] for m in det]
        if not ver:
            lines.append(("bad", tr("Ollama is not running. Open the Ollama app on this computer (look for its icon), then reload this page.",
                                    "Ollama غير شغّال. افتح تطبيق Ollama على هذا الحاسوب (ابحث عن أيقونته) ثم أعد تحميل الصفحة.")))
        else:
            lines.append(("ok", tr(f"Ollama {ver} is running", f"Ollama {bidi(ver)} شغّال")))
            want = settings.get("ollama_model", "")
            have = want in names or f"{want}:latest" in names
            if have:
                lines.append(("ok", tr(f"Text model ready: {want}", f"نموذج النص جاهز: {bidi(want)}")))
            elif names:
                lines.append(("ok", tr(f"'{want}' is not installed, so the app will use '{names[0]}' instead (change it in Settings).",
                                       f"النموذج {bidi(want)} غير مثبّت، لذا سيستخدم التطبيق {bidi(names[0])} (غيّره من الإعدادات).")))
            else:
                lines.append(("bad", tr(f"No model is installed yet. Open Settings -> AI engine -> 'Download a model' and get '{want or 'qwen3:8b'}'.",
                                        f"لا يوجد أي نموذج مثبّت. افتح الإعدادات ← محرك الذكاء ← «تنزيل نموذج» ونزّل {bidi(want or 'qwen3:8b')}.")))
            vis = [n for n in names if providers.is_vision_model(settings, n)]
            if vis:
                lines.append(("ok", tr("Image reading ready: " + ", ".join(vis[:3]),
                                       "قراءة الصور جاهزة: " + bidi(", ".join(vis[:3])))))
            else:
                lines.append(("opt", tr("Image reading is optional and not set up. Settings -> AI engine -> download 'medgemma:4b' (3.3 GB).",
                                        "قراءة الصور اختيارية وغير مفعّلة. الإعدادات ← محرك الذكاء ← نزّل medgemma:4b (3.3 جيجا).")))
    else:
        has_key = config.has_key(settings, p)
        nm = {"groq": "Groq", "gemini": "Gemini", "openai": "OpenAI"}[p]
        lines.append(("ok" if has_key else "bad",
                      tr(f"{nm} key is set", f"مفتاح {nm} موجود") if has_key else
                      tr(f"No {nm} key yet: open Settings -> AI engine and paste a free key (2 minutes).",
                         f"لا يوجد مفتاح {nm}: افتح الإعدادات ← محرك الذكاء والصق مفتاحاً مجانياً (دقيقتان).")))
    if not config.PUBLIC_MODE:
        n_lib = len(knowledge.library_files())
        lines.append(("ok" if n_lib else "opt",
                      tr(f"Your library has {n_lib} file(s) the AI can quote", f"مكتبتك فيها {n_lib} ملف يمكن للذكاء الاقتباس منها")
                      if n_lib else tr("Tip: add your own guidelines or protocols (PDF/Word) in Settings -> Knowledge sources.",
                                       "نصيحة: أضف إرشاداتك أو بروتوكولاتك (PDF/Word) من الإعدادات ← مصادر المعرفة.")))
    return {"ok": not any(s == "bad" for s, _ in lines), "lines": lines}


def show_engine_status(key: str):
    st_ = engine_status()
    if st_["ok"]:
        with st.expander(tr("Ready - setup check", "جاهز - فحص الإعداد"), expanded=False, icon=":material/check_circle:"):
            for s, t in st_["lines"]:
                st.markdown(("- " if s != "bad" else "- **") + t + ("**" if s == "bad" else ""))
    else:
        with st.expander(tr("Needs one more step - setup check", "تحتاج خطوة أخيرة - فحص الإعداد"),
                         expanded=True, icon=":material/build:"):
            for s, t in st_["lines"]:
                (st.error if s == "bad" else st.markdown)(t if s == "bad" else "- " + t)


def vision_setup_panel(key: str, allow_skip=None):
    """What to do when Ollama has no image-reading model. Three plain options."""
    st.markdown(f"<div class='alert'><b>{tr('Reading images needs an image model, and Ollama has none yet.', 'قراءة الصور تحتاج نموذج صور وOllama ليس لديه أي نموذج منها.')}</b><br>"
                f"{tr('Pick one option:', 'اختر أحد الخيارات:')}</div>", unsafe_allow_html=True)
    if providers.ollama_is_old(settings):
        st.warning(tr(f"Your Ollama (version {providers.ollama_version(settings)}) is old and cannot run most image models "
                      "(error 'unknown model architecture'). Download the latest from ollama.com/download, install it over the old one, "
                      "restart Ollama, then use option B. Or choose 'moondream' below, which works on old versions.",
                      f"إصدار Ollama لديك ({bidi(providers.ollama_version(settings))}) قديم ولا يشغّل أغلب نماذج الصور. "
                      "حمّل أحدث إصدار من ollama.com/download وثبّته فوق القديم وأعد تشغيل Ollama ثم استخدم الخيار ب. أو اختر moondream فهو يعمل على الإصدارات القديمة."))
    cols = st.columns(3 if allow_skip else 2)
    ci = 0
    if allow_skip:
        with cols[0]:
            st.markdown(tr("**A. Continue without the images** (uses the typed text and files only)",
                           "**أ. أكمل بدون الصور** (بالنص والملفات فقط)"))
            if st.button(tr("Generate without images", "أنشئ بدون الصور"), key=f"{key}_noimg"):
                allow_skip()
        ci = 1
    with cols[ci]:
        st.markdown(tr("**B. Download an image model** (one time, free, stays on this computer)",
                       "**ب. نزّل نموذج صور** (مرة واحدة، مجاني، يبقى على هذا الحاسوب)"))
        tags = [m["tag"] for m in config.VISION_MODELS]
        vm = st.selectbox(tr("Model", "النموذج"), tags, key=f"{key}_vm",
                          format_func=lambda t: next(f"{m['tag']} · ~{m['gb']} GB" for m in config.VISION_MODELS if m["tag"] == t))
        info = next(m for m in config.VISION_MODELS if m["tag"] == vm)
        st.caption(info["ar" if RTL else "en"] + tr(f" (comfortable with ~{info['ram']} GB of memory)", f" (مريح مع نحو {info['ram']} جيجا ذاكرة)"))
        if st.button(tr("Download now", "نزّل الآن"), key=f"{key}_dl"):
            bar, txt = st.progress(0.0), st.empty()
            try:
                for status_txt, frac in providers.pull_ollama_model(settings, vm):
                    txt.caption(status_txt)
                    if frac is not None:
                        bar.progress(frac)
                save_s({**settings, "ollama_vision_model": vm})
                st.session_state[f"{key}_need"] = False
                st.success(tr("Downloaded and selected. Press the button again.", "تم التنزيل والاختيار. اضغط الزر مرة أخرى."))
            except providers.ProviderError as e:
                st.error(str(e))
    with cols[-1]:
        st.markdown(tr("**C. Use Gemini** (free, reads images, nothing to install)",
                       "**ج. استخدم Gemini** (مجاني، يقرأ الصور، بلا تثبيت)"))
        st.caption(tr("Settings -> AI engine -> Gemini -> paste a free key from aistudio.google.com/apikey.",
                      "الإعدادات ← محرك الذكاء ← Gemini ← الصق مفتاحاً مجانياً من aistudio.google.com/apikey."))


def image_model_label() -> str:
    """The model that will read the picture (may differ from the text model)."""
    p = settings.get("provider", "groq")
    if p == "ollama":
        try:
            return providers._resolve_ollama_model(settings, vision=True)
        except providers.ProviderError:
            return settings.get("ollama_vision_model", "?")
    return (settings.get("groq_vision_model") if p == "groq" else settings.get("openai_model") if p == "openai" else settings.get("gemini_model")) or "?"


REPORT_CSS = """
@page{size:A4;margin:16mm 14mm}
*{box-sizing:border-box}
body{font:11.5pt/1.55 'Segoe UI',Inter,system-ui,sans-serif;color:#111;margin:0;
 max-width:190mm;padding:8mm 0}
h1{font-size:16pt;margin:0 0 .2rem}
h2{font-size:12.5pt;margin:1.1rem 0 .3rem;break-after:avoid}
.prov{font-size:9pt;color:#444;border-bottom:1px solid #999;padding-bottom:.5rem;margin-bottom:.8rem}
.prov b{color:#111}
.disc{border:1px solid #BBB;background:#FAFAFA;padding:.5rem .7rem;font-size:9pt;margin:0 0 1rem}
.sum{border:1px solid #BBB;padding:.6rem .8rem;margin-bottom:1rem}
.dx{border:1px solid #BBB;border-left:4px solid #BBB;padding:.6rem .8rem;margin:.6rem 0;break-inside:avoid}
.dx.must{border-left-color:#000}
.dx-h{font-weight:700;font-size:11.5pt;margin-bottom:.2rem}
.tag{display:inline-block;border:1px solid #666;border-radius:3px;padding:0 .35rem;
 font-size:8.5pt;font-weight:700;margin-inline-start:.35rem;vertical-align:.08rem}
.ic{width:1em;height:1em;fill:currentColor;vertical-align:-.13em;margin-inline-end:.25em}
.wordmark{font-size:9.5pt;font-weight:700;color:#111;border-bottom:1px solid #999;
 padding-bottom:.3rem;margin-bottom:.5rem}
.lbl{font-size:8.5pt;letter-spacing:0;color:#555;font-weight:700;margin-top:.45rem}
ul{margin:.15rem 0 .2rem;padding-inline-start:1.1rem}
li{margin:.08rem 0}
.test{background:#F4F6F6;padding:.35rem .6rem;margin-top:.45rem;font-size:10.5pt}
.refs{font-size:9.5pt;margin-top:.45rem}
.refs a{color:#000;text-decoration:none}
.refs .u{color:#555;font-size:8.5pt;word-break:break-all}
.note{border:1px dashed #999;padding:.4rem .6rem;margin-top:.45rem;font-size:10pt}
.foot{margin-top:1.4rem;border-top:1px solid #999;padding-top:.5rem;font-size:8.5pt;color:#444}
/* The report carries Arabic headings around English diagnoses and English
   around Arabic lab text, so each paragraph picks its own direction - the same
   rule the app itself uses, for the same reason. */
h1,h2,p,li,.dx-h,.test,.note,.refs,.lbl,.prov,.disc,.foot{unicode-bidi:plaintext;text-align:start}
.refs .u{unicode-bidi:isolate;direction:ltr}
@media screen{body{margin:0 auto;padding:10mm 8mm}}
"""


def report_html(res, evidence, notes, provenance: dict) -> str:
    """One self-contained document: provenance, disclaimer, case summary, the
    ranked differential with its evidence, and what is still missing. Opens in
    any browser and prints to A4 - the thing that goes in the patient's folder
    or into a teaching file, which a tab on screen cannot produce because the
    summary, the differential and the evidence live on different tabs."""
    s = res.get("case_summary", {})
    rtl = RTL

    def lst(items):
        items = [i for i in (items or []) if i]
        return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else "<p>—</p>"

    L = (lambda en, ar: ar if rtl else en)
    p = [f"<!doctype html><html lang='{'ar' if rtl else 'en'}' dir='{'rtl' if rtl else 'ltr'}'>"
         f"<head><meta charset='utf-8'/><title>{esc(L('Differential diagnosis', 'التشخيص التفريقي'))}</title>"
         f"<style>{REPORT_CSS}</style></head><body>"]
    org = (provenance.pop("_org", "") or "").strip()
    if org:
        p.append(f"<div class='wordmark'>{esc(org)}</div>")
    p += [f"<h1>{esc(L('Differential diagnosis - educational draft', 'التشخيص التفريقي - مسودة تعليمية'))}</h1>",
         "<div class='prov'>"
         + " &#160;·&#160; ".join(
             f"<b>{esc(k)}:</b> {esc(v)}" for k, v in provenance.items() if v) +
         "</div>",
         f"<div class='disc'>{esc(config.DISCLAIMER_AR if rtl else config.DISCLAIMER_EN)}</div>"]

    if s:
        p.append(f"<div class='sum'><h2 style='margin-top:0'>{esc(L('Case summary', 'ملخص الحالة'))}</h2>"
                 f"<p>{esc(s.get('one_line'))}</p>"
                 f"<div class='lbl'>{esc(L('Key positive findings', 'نتائج مهمة موجودة'))}</div>{lst(s.get('key_positive_findings'))}"
                 f"<div class='lbl'>{esc(L('Negative / missing', 'نتائج سلبية أو ناقصة'))}</div>{lst(s.get('key_negative_or_missing'))}</div>")
    if res.get("red_flags_now"):
        p.append(f"<div class='disc'><b>{esc(L('Red flags needing action now', 'علامات خطر تحتاج تدخلاً فورياً'))}:</b> "
                 + esc(" · ".join(res["red_flags_now"])) + "</div>")
    if res.get("image_findings"):
        p.append(f"<h2>{esc(L('Image findings (draft - verify)', 'ما ظهر في الصور (مسودة - تحقق)'))}</h2>{lst(res['image_findings'])}")

    p.append(f"<h2>{esc(L('Ranked differential', 'التشخيص التفريقي المرتب'))}</h2>")
    for d in res.get("differential", []):
        dx = d.get("diagnosis")
        mt = L("MUST EXCLUDE", "يجب استبعاده أولاً")
        must = (f"<span class='tag'>{icon('warning', mt)}{esc(mt)}</span>") if d.get("must_exclude_first") else ""
        p.append(f"<div class='dx{' must' if d.get('must_exclude_first') else ''}'>"
                 f"<div class='dx-h'>{esc(d.get('rank'))}. {esc(dx)}"
                 f"<span class='tag'>{esc(d.get('likelihood'))}</span>{must}</div>"
                 f"<div class='lbl'>{esc(L('Supporting', 'يدعمه'))}</div>{lst(d.get('supporting_findings'))}"
                 f"<div class='lbl'>{esc(L('Arguing against', 'ضده'))}</div>{lst(d.get('arguing_against'))}"
                 f"<div class='test'><b>{esc(L('Confirmatory test', 'فحص للتأكيد'))}:</b> {esc(d.get('confirmatory_test'))}</div>")
        n = notes.get(dx)
        if n and n.get("grounded_assessment"):
            kp = "".join(f"<li>{esc(x)}</li>" for x in (n.get("key_points") or []) if x)
            p.append(f"<div class='note'><b>{esc(L('Evidence note', 'ملاحظة مدعومة بالأدلة'))}:</b> {esc(n['grounded_assessment'])}"
                     + (f"<ul>{kp}</ul>" if kp else "") + "</div>")
        hits = evidence.get(dx) or []
        if hits:
            p.append(f"<div class='refs'><div class='lbl'>{esc(L('Sources', 'المصادر'))}</div><ol>")
            for n_, h in enumerate(hits, 1):
                lab = knowledge.SOURCES[h["source"]]["ar" if rtl else "en"]
                tail = f"<br/><span class='u'>{esc(h['url'])}</span>" if h.get("url") else ""
                p.append(f"<li>S{n_} · {esc(lab)} · {esc(h['title'])} — {esc(h['journal'])}"
                         f"{', ' + esc(h['year']) if h.get('year') else ''} ({esc(h['ref'])}){tail}</li>")
            p.append("</ol></div>")
        p.append("</div>")

    if res.get("missing_information"):
        p.append(f"<h2>{esc(L('Worth asking or ordering', 'يستحق السؤال عنه أو طلبه'))}</h2>{lst(res['missing_information'])}")
    if res.get("uncertainty_note"):
        p.append(f"<h2>{esc(L('Uncertainty', 'عدم اليقين'))}</h2><p>{esc(res['uncertainty_note'])}</p>")
    p.append(f"<div class='foot'>{esc(config.DISCLAIMER_AR if rtl else config.DISCLAIMER_EN)}</div>")
    p.append("</body></html>")
    return "".join(p)


def report_markdown(res, evidence, notes) -> str:
    s = res.get("case_summary", {})
    out = [f"# {s.get('one_line', 'Case')}", "", "> " + (config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN), ""]
    for d in res.get("differential", []):
        out += [f"## {d.get('rank')}. {d.get('diagnosis')}" + ("  — MUST EXCLUDE" if d.get("must_exclude_first") else ""),
                f"*Likelihood: {d.get('likelihood')}*", "", "**Supporting**"]
        out += [f"- {x}" for x in d.get("supporting_findings", [])]
        out += ["", "**Arguing against**"] + [f"- {x}" for x in d.get("arguing_against", [])]
        out += ["", f"**Confirmatory test:** {d.get('confirmatory_test', '')}", ""]
        n = notes.get(d.get("diagnosis"))
        if n:
            out += [f"**Evidence note:** {n.get('grounded_assessment', '')}", ""]
        for h in evidence.get(d.get("diagnosis"), []) or []:
            lab = knowledge.SOURCES[h["source"]]["en"]
            out.append(f"- {lab}: " + (f"[{h['title']}]({h['url']})" if h.get("url") else h["title"])
                       + f" — {h['journal']}{', ' + h['year'] if h.get('year') else ''} ({h['ref']})")
        out.append("")
    if res.get("image_findings"):
        out += ["## Image findings"] + [f"- {x}" for x in res["image_findings"]] + [""]
    if res.get("missing_information"):
        out += ["## Worth asking / ordering"] + [f"- {x}" for x in res["missing_information"]]
    return "\n".join(out)


# ============================================================ TAB 1 - case
def compose_form() -> str:
    """The guided form: one box per part of a clinical history, joined into the
    case text the AI reads. For a doctor who thinks in headings, not paragraphs."""
    c1, c2, c3 = st.columns([1, 1, 2])
    age = c1.text_input(tr("Age", "العمر"), key="f_age", placeholder=tr("e.g. 37 years", "مثال: ٣٧ سنة"))
    sex = c2.selectbox(tr("Sex", "الجنس"), ["", tr("Male", "ذكر"), tr("Female", "أنثى")], key="f_sex")
    cc = c3.text_input(tr("Main complaint and how long", "الشكوى الرئيسية ومدتها"), key="f_cc",
                       placeholder=tr("e.g. fever for 5 days", "مثال: حرارة منذ ٥ أيام"))
    hpi = st.text_area(tr("History of the present illness", "تاريخ المرض الحالي"), key="f_hpi", height=120)
    pmh = st.text_area(tr("Past history, medicines, allergies, family and social history", "التاريخ المرضي السابق والأدوية والحساسية والتاريخ العائلي والاجتماعي"),
                       key="f_pmh", height=90)
    v1, v2 = st.columns([1, 2])
    vit = v1.text_area(tr("Vital signs", "العلامات الحيوية"), key="f_vit", height=100,
                       placeholder=tr("Temp, pulse, BP, RR, SpO2", "الحرارة، النبض، الضغط، التنفس، التشبع"))
    exam = v2.text_area(tr("Examination", "الفحص الإكلينيكي"), key="f_exam", height=100)
    l1, l2 = st.columns(2)
    labs = l1.text_area(tr("Labs (paste numbers with units)", "التحاليل (الصق الأرقام مع الوحدات)"), key="f_labs", height=120)
    img = l2.text_area(tr("Imaging / pathology findings in words", "نتائج الأشعة / الباثولوجي بالكلمات"), key="f_img", height=120)
    other = st.text_area(tr("Anything else", "أي شيء آخر"), key="f_other", height=70)
    rows = [("Age", age), ("Sex", sex), ("Main complaint", cc), ("History of present illness", hpi),
            ("Past history / medicines / allergies / family / social", pmh), ("Vital signs", vit),
            ("Examination", exam), ("Laboratory results", labs), ("Imaging / pathology", img), ("Other", other)]
    return "\n".join(f"{k}: {v.strip()}" for k, v in rows if v and v.strip())


with tab1:
    show_engine_status("case")
    entry = st.radio(tr("How do you want to enter the case?", "كيف تريد إدخال الحالة؟"), ["text", "form"],
                     horizontal=True, key="entry_mode",
                     format_func=lambda x: {"text": tr("Write or paste it", "اكتبها أو الصقها"),
                                            "form": tr("Fill in a guided form", "املأ نموذجاً موجَّهاً")}[x])
    left, right = st.columns([3, 2], gap="large")
    with left:
        if entry == "text":
            def _toggle_sample():
                if st.session_state.get("use_sample") and config.SAMPLE_CASE.exists():
                    st.session_state["case_text"] = config.SAMPLE_CASE.read_text(encoding="utf-8")
                else:
                    st.session_state["case_text"] = ""
            st.checkbox(tr("Load the sample case (dengue/DIC, for testing)",
                           "تحميل حالة تجريبية (حمى الضنك / DIC، للتجربة)"),
                        key="use_sample", on_change=_toggle_sample)
            case_text = st.text_area(
                tr("Case: history, examination, labs, imaging - paste everything you have",
                   "الحالة: التاريخ المرضي والفحص والتحاليل والتصوير - الصق كل ما لديك"),
                height=330, key="case_text",
                placeholder=tr("De-identified please: a 37-year-old man with fever for 5 days...",
                               "بدون بيانات تعريفية من فضلك: رجل عمره ٣٧ سنة، حرارة منذ ٥ أيام..."))
        else:
            case_text = compose_form()
        st.caption(tr("Never type the patient's name, national ID or other identifiers - and crop them out of images.",
                      "لا تكتب اسم المريض أو رقمه القومي أو أي بيانات تعريفية - واقصّها من الصور."))
    with right:
        st.markdown(f"##### {tr('Attach files (optional)', 'أرفق ملفات (اختياري)')}")
        st.caption(tr(config.UPLOAD_NOTE_EN, config.UPLOAD_NOTE_AR))
        uploads = st.file_uploader(tr("Drop files here", "اسحب الملفات هنا"), type=files.ALL_EXT,
                                   accept_multiple_files=True, label_visibility="collapsed")
        proc = files.process_uploads(uploads) if uploads else {"text": "", "images": [], "image_names": [],
                                                              "tables": {}, "notes": []}
        for n in proc["notes"]:
            st.warning(n)
        if proc["images"]:
            cols = st.columns(min(3, len(proc["images"])))
            for i, ((_, b), nm) in enumerate(zip(proc["images"], proc["image_names"])):
                cols[i % len(cols)].image(b, caption=bidi(nm), **STRETCH)
        for nm, sheets in proc["tables"].items():
            for sh, df in sheets.items():
                with st.expander(f"{bidi(f'{nm} · {sh}')} ({len(df)} {tr('rows', 'صف')})",
                                 icon=":material/table_chart:"):
                    st.dataframe(df, **STRETCH, height=240)
        if proc["text"]:
            with st.expander(tr("Text the AI will read from your files", "النص الذي سيقرؤه الذكاء من ملفاتك"),
                              icon=":material/description:"):
                st.text(proc["text"])
        if proc["images"]:
            st.info(tr("Images are read by a vision model (Settings -> AI engine). "
                       "AI image reading is a draft - verify it yourself. For a closer look at ONE image, use the Identify tab.",
                       "تُقرأ الصور بنموذج رؤية (الإعدادات ← محرك الذكاء). قراءة الذكاء للصور مسودة - تحقق منها بنفسك. لفحص أدق لصورة واحدة استخدم تبويب الصور."))
        # findings the doctor chose to carry over from the Identify tab
        if st.session_state.img_notes:
            with st.expander(tr(f"Image findings added from the Identify tab ({len(st.session_state.img_notes)})",
                                f"نتائج صور أُضيفت من تبويب الصور ({len(st.session_state.img_notes)})"),
                             icon=":material/add_photo_alternate:", expanded=True):
                for k_, v_ in list(st.session_state.img_notes.items()):
                    st.text(v_)
                    if st.button(tr("Remove", "إزالة"), key=f"rmnote_{k_}"):
                        st.session_state.img_notes.pop(k_, None)
                        st.rerun()

    extra_notes = "\n\n".join(st.session_state.img_notes.values())
    full_text = "\n\n".join(x for x in (case_text.strip(), proc["text"], extra_notes) if x)
    ready = len(full_text) >= 40 or bool(proc["images"])
    # the department and the model are shown once, in the sidebar

    def run_dd(imgs):
        with st.status(tr("Working...", "جارٍ العمل..."), expanded=True) as status:
            try:
                st.write(tr("Reasoning over the case" + (" and images" if imgs else ""),
                            "تحليل الحالة" + (" والصور" if imgs else "")))
                ph = st.empty()

                def prog(n, secs):
                    rate = n / secs if secs > 0.5 else 0
                    ph.caption(tr(f"Writing: {n} tokens · {secs:.0f}s" + (f" · {rate:.1f} tokens/s" if rate else ""),
                                  f"جارٍ الكتابة: {n} رمز · {secs:.0f} ث" + (f" · {rate:.1f} رمز/ث" if rate else "")))
                res = providers.ask_json(build_system_prompt(bool(imgs)),
                                         f"CASE:\n{full_text or '(see attached images)'}", settings,
                                         images=imgs, on_progress=prog)
                ph.empty()
                st.session_state.dd_result = dedupe_dd(res)
                res = st.session_state.dd_result
                if res.pop("_truncated", None):
                    st.warning(tr(
                        f"The local model got stuck repeating itself and was stopped, so this list is incomplete "
                        f"({len(res.get('differential', []))} diagnoses recovered). A long case "
                        f"(Word/PowerPoint) needs a bigger model: Settings -> AI engine -> download 'qwen3:8b' "
                        f"or 'gemma3:12b', or use a free Groq / Gemini key.",
                        f"علِق النموذج المحلي في تكرار نفسه فأُوقف، لذا القائمة غير مكتملة "
                        f"(تم إنقاذ {len(res.get('differential', []))} تشخيصات). الحالة الطويلة "
                        f"(Word/PowerPoint) تحتاج نموذجاً أكبر: الإعدادات ← محرك الذكاء ← نزّل qwen3:8b "
                        f"أو gemma3:12b، أو استخدم مفتاح Groq / Gemini المجاني."))
                st.session_state.evidence, st.session_state.notes, st.session_state.kb_errors = {}, {}, {}
                st.session_state.need_vision = False
                if settings.get("auto_evidence", True):
                    srcs = [s for s in settings.get("knowledge_sources", knowledge.DEFAULT_SOURCES) if s in knowledge.SOURCES]
                    st.write(tr(f"Looking up every diagnosis in {len(srcs)} knowledge sources, in parallel",
                                f"البحث عن كل تشخيص في {len(srcs)} مصادر معرفة بالتوازي"))
                    items = [(d["diagnosis"], d.get("search_terms", "")) for d in res.get("differential", [])
                             if d.get("diagnosis")]
                    try:
                        ev, errs = knowledge.gather_many(items, settings)
                        st.session_state.evidence, st.session_state.kb_errors = ev, errs
                    except Exception as e:
                        st.write(f"{tr('Knowledge sources', 'مصادر المعرفة')}: {e}")
                log_event(action="generate_dd", provider=settings.get("provider"),
                          n_chars=len(full_text), n_images=len(imgs or []), n_files=len(uploads or []))
                status.update(label=tr("Done - open the AI differential tab", "تم - افتح تبويب التشخيص التفريقي"),
                              state="complete", expanded=False)
                # The finish signal. A local model can take a minute, so this says
                # plainly that it ended and what came back - a mark that carries
                # the result is more use than one that only celebrates.
                n_dx = len(res.get("differential", []))
                n_ref = sum(len(v or []) for v in st.session_state.evidence.values())
                fin = time.strftime("%H:%M")
                st.toast(tr(f"Differential ready - {n_dx} diagnoses",
                            f"التشخيص التفريقي جاهز - {n_dx} تشخيصات"),
                         icon=":material/check_circle:")
                st.success(tr(f"Finished at {fin}. {n_dx} diagnoses, {n_ref} passages from the knowledge sources. "
                              f"Open the 'AI differential' tab above.",
                              f"انتهى في {bidi(fin)}. {n_dx} تشخيصات و{n_ref} مقطعاً من مصادر المعرفة. "
                              f"افتح تبويب «التشخيص التفريقي» أعلاه."),
                           icon=":material/check_circle:")
                st.balloons()   # the animation that says the run is over
            except providers.MissingVisionModel:
                st.session_state.need_vision = True
                status.update(label=tr("An image-reading model is needed", "مطلوب نموذج لقراءة الصور"), state="error")
            except providers.ProviderError as e:
                status.update(label=tr("Something went wrong", "حدث خطأ"), state="error")
                st.error(str(e))
                # log failures too: otherwise a failed run leaves no trace at all
                log_event(action="generate_dd_failed", provider=settings.get("provider"),
                          n_chars=len(full_text), n_images=len(imgs or []),
                          n_files=len(uploads or []), error=str(e)[:300])

    if st.button(tr("Generate differential", "أنشئ التشخيص التفريقي"), disabled=not ready, type="primary", key="go_dd"):
        st.session_state.need_vision = False
        run_dd(proc["images"] or None)
    if ready:
        who = bidi(f"{prov_label} · {model_label()}")
        st.caption(tr(f"Will be answered by {who}", f"سيجيب عليها {who}"))
    else:
        st.caption(tr("The button turns on once there is a case to read: write at least "
                      "40 characters, or attach a file or an image.",
                      "يعمل الزر بمجرد وجود حالة لقراءتها: اكتب 40 حرفاً على الأقل، "
                      "أو أرفق ملفاً أو صورة."))

    if st.session_state.get("need_vision") and proc["images"]:
        vision_setup_panel("case", allow_skip=lambda: run_dd(None))


# ============================================================ TAB - images
def _list_html(items):
    return ul(items)


def add_img_to_case(i: int):
    """Button callback: carry one image reading into the Case tab as text."""
    items = st.session_state.get("img_results", [])
    if i >= len(items):
        return
    it = items[i]
    r, w = it["res"], it["res"].get("what_is_it") or {}
    lines = [f"IMAGE FINDINGS - {it['name']} ({' / '.join(x for x in (w.get('modality'), w.get('body_part_or_subject')) if x)}), AI draft, verify:"]
    if r.get("headline"):
        lines.append(r["headline"].replace("**", ""))
    for t_, bl_ in image_sections(r)[:2]:
        lines.append(f"{t_}:" if t_ else "")
        lines += [f"- {b_.replace('**', '')}" for b_ in bl_]
    if r.get("extracted_text"):
        lines.append("Text read from the image:\n" + r["extracted_text"])
    st.session_state.img_notes[f"{it['name']}#{i}"] = "\n".join(lines)


def image_report_html(it: dict) -> str:
    r, w = it["res"], it["res"].get("what_is_it") or {}
    L = (lambda en, ar: ar if RTL else en)

    def lst(items):
        items = [x for x in (items or []) if x]
        return "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>" if items else "<p>-</p>"
    import base64 as _b64
    img = f"<img style='max-width:100%;max-height:90mm' src='data:{it['mime']};base64,{_b64.b64encode(it['bytes']).decode()}'/>"
    return (f"<!doctype html><html lang='{'ar' if RTL else 'en'}' dir='{'rtl' if RTL else 'ltr'}'><head><meta charset='utf-8'/>"
            f"<title>{esc(L('Image reading', 'قراءة صورة'))}</title><style>{REPORT_CSS}</style></head><body>"
            f"<h1>{esc(L('Image reading - educational draft', 'قراءة صورة - مسودة تعليمية'))}</h1>"
            f"<div class='prov'><b>{esc(L('Model', 'النموذج'))}:</b> {esc(it.get('model') or (prov_label + ' · ' + image_model_label()))} &#160;·&#160; "
            f"<b>{esc(L('File', 'الملف'))}:</b> {esc(it['name'])} &#160;·&#160; {esc(time.strftime('%Y-%m-%d %H:%M'))}</div>"
            f"<div class='disc'>{esc(config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN)}</div>{img}"
            f"<h2>{esc(' · '.join(x for x in (w.get('modality'), w.get('body_part_or_subject'), w.get('view_or_technique')) if x) or L('What it is', 'ما هي الصورة'))}</h2>"
            f"<p>{md_bold(r.get('headline') or w.get('plain_description'))}</p>"
            + "".join(f"<h2>{n}. {md_bold(t)}</h2>" + (lst(bl) if bl else "") for n, (t, bl) in enumerate(image_sections(r), 1))
            + (f"<h2>{esc(L('Text read from the image', 'النص المقروء من الصورة'))}</h2><pre style='white-space:pre-wrap'>{esc(r.get('extracted_text'))}</pre>" if r.get("extracted_text") else "")
            + f"<h2>{esc(L('Limitations', 'حدود القراءة'))}</h2><p>{esc(r.get('limitations'))}</p>"
            f"<div class='foot'>{esc(config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN)}</div></body></html>")


# ------------------------------------------------------------ management helpers


def split_answer_slides(text: str):
    """A teaching deck often asks 'Management Plan?' on one slide and shows what was
    done on the slides after it. -> (visible_text, hidden_answer_text, question_slide_no)
    so the AI can propose its own plan first. (text, "", None) if there is no such slide."""
    heads = list(_re.finditer(r"^--- Slide (\d+) ---\s*$", text, _re.M))
    q_re = _re.compile(r"^(management|treatment|therapy|plan|what (is|would|do|should)[^\n]*)[^\n]{0,40}\?\s*$", _re.I)
    for k, h in enumerate(heads[:-1]):
        body = text[h.end(): heads[k + 1].start()].strip()
        if body and len(body) < 120 and q_re.match(body.splitlines()[0].strip()):
            cut = heads[k + 1].start()
            nxt = text.find("=== FILE:", cut)
            end = nxt if nxt != -1 else len(text)
            return text[:cut].rstrip() + ("\n\n" + text[end:] if nxt != -1 else ""), text[cut:end].strip(), int(h.group(1))
    return text, "", None


def management_report_html(m: dict, cmp_: dict, sources: list, prov: dict) -> str:
    L = (lambda en, ar: ar if RTL else en)
    sev = m.get("severity") or {}
    th = "".join(f"<li><b>{esc(t.get('phase'))}</b> - <b>{esc(t.get('treatment'))}</b><br>{esc(t.get('how_to_give'))}"
                 f"<br><i>{esc(t.get('rationale'))}</i>" + (f"<br>{esc(L('Monitor', 'المتابعة'))}: {esc(t.get('monitoring'))}" if t.get("monitoring") else "")
                 + "</li>" for t in (m.get("medical_therapy") or []) if isinstance(t, dict))
    fu = "".join(f"<li><b>{esc(x.get('when'))}</b>: {esc(x.get('what'))}</li>" for x in (m.get("monitoring_and_followup") or []) if isinstance(x, dict))
    nu = m.get("nutrition") or {}
    src = "".join(f"<li>{esc(s.get('title'))} - {esc(s.get('journal'))} {esc(s.get('year'))} ({esc(s.get('ref'))})</li>" for s in sources)
    cmp_html = ""
    if cmp_:
        rows = "".join(f"<li><b>{esc(d.get('topic'))}</b>: AI - {esc(d.get('ai_plan'))}; deck - {esc(d.get('deck_plan'))}<br><i>{esc(d.get('comment'))}</i></li>"
                       for d in (cmp_.get("differences") or []) if isinstance(d, dict))
        cmp_html = (f"<h2>{esc(L('Compared with the plan in the presentation', 'مقارنة مع الخطة في العرض'))}</h2>"
                    f"<h3>{esc(L('Agree', 'اتفاق'))}</h3>{ul(cmp_.get('agreements'))}<h3>{esc(L('Differences', 'اختلافات'))}</h3><ul>{rows}</ul>"
                    f"<h3>{esc(L('Teaching points', 'نقاط تعليمية'))}</h3>{ul(cmp_.get('teaching_points'))}")
    pv = " &#160;·&#160; ".join(f"<b>{esc(k)}:</b> {esc(v)}" for k, v in prov.items() if v)
    return (f"<!doctype html><html lang='{'ar' if RTL else 'en'}' dir='{'rtl' if RTL else 'ltr'}'><head><meta charset='utf-8'/>"
            f"<title>{esc(L('Management plan', 'خطة العلاج'))}</title><style>{REPORT_CSS}</style></head><body>"
            f"<h1>{esc(L('Management plan - educational draft', 'خطة العلاج - مسودة تعليمية'))}</h1><div class='prov'>{pv}</div>"
            f"<div class='disc'>{esc(config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN)}</div>"
            f"<div class='sum'><b>{esc(m.get('working_diagnosis'))}</b><br>{esc(sev.get('classification'))} - {esc(sev.get('assessment'))}</div>"
            f"<h2>{esc(L('Immediate actions', 'إجراءات فورية'))}</h2>{ul(m.get('immediate_actions'))}"
            f"<h2>{esc(L('Investigations to complete', 'فحوص مطلوبة'))}</h2>{ul(m.get('investigations_to_complete'))}"
            f"<h2>{esc(L('Medical therapy', 'العلاج الدوائي'))}</h2><ul>{th}</ul>"
            f"<h2>{esc(L('Nutrition', 'التغذية'))}</h2>{ul(nu.get('plan'))}<p>{esc(nu.get('energy_target'))} {esc(nu.get('referral'))}</p>"
            f"<h2>{esc(L('Follow-up', 'المتابعة'))}</h2><ul>{fu}</ul>"
            f"<h2>{esc(L('Escalate if', 'تصعيد إذا'))}</h2>{ul(m.get('escalation_criteria'))}"
            f"<h2>{esc(L('If not responding', 'إذا لم يستجب'))}</h2>{ul(m.get('if_not_responding'))}"
            f"<h2>{esc(L('Surgical considerations', 'اعتبارات جراحية'))}</h2><p>{esc(m.get('surgical_considerations'))}</p>"
            f"<h2>{esc(L('Preventive care', 'رعاية وقائية'))}</h2>{ul(m.get('preventive_care'))}"
            f"<h2>{esc(L('Patient education', 'تثقيف المريض'))}</h2>{ul(m.get('patient_education'))}"
            + cmp_html + (f"<h2>{esc(L('Guideline sources to check', 'مصادر إرشادية للمراجعة'))}</h2><ul>{src}</ul>" if src else "")
            + f"<p><i>{esc(m.get('uncertainty_note'))}</i></p>"
            f"<div class='foot'>{esc(config.DISCLAIMER_AR if RTL else config.DISCLAIMER_EN)}</div></body></html>")


def render_management(m: dict):
    sev = m.get("severity") or {}
    adm = sev.get("needs_admission")
    chip = (f"<span class='chip must'>{tr('Admission suggested', 'يُقترح التنويم')}</span>" if adm
            else f"<span class='chip'>{tr('Outpatient may be possible', 'قد يكفي العلاج الخارجي')}</span>") if adm is not None else ""
    st.markdown(f"<div class='card'><div class='lbl'>{tr('Working diagnosis', 'التشخيص العامل')}</div><h3>{esc(m.get('working_diagnosis'))}</h3>"
                f"{ul(m.get('diagnosis_basis'))}<div class='lbl'>{tr('Severity', 'الشدة')}</div>"
                f"<p><b>{esc(sev.get('classification'))}</b> - {esc(sev.get('assessment'))}</p>{chip}"
                f"<p style='color:var(--muted)'>{esc(sev.get('why'))}</p></div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown(f"<div class='card'><div class='lbl'>{tr('Do now', 'افعل الآن')}</div>{ul(m.get('immediate_actions'))}"
                    f"<div class='lbl'>{tr('Investigations to complete', 'فحوص مطلوبة')}</div>{ul(m.get('investigations_to_complete'))}</div>",
                    unsafe_allow_html=True)
    with c2:
        nu = m.get("nutrition") or {}
        st.markdown(f"<div class='card'><div class='lbl'>{tr('Nutrition', 'التغذية')}</div>{ul(nu.get('plan'))}"
                    + (f"<div class='test'><b>{tr('Energy target', 'هدف الطاقة')}:</b> {esc(nu.get('energy_target'))}</div>" if nu.get("energy_target") else "")
                    + (f"<p style='color:var(--muted)'>{esc(nu.get('referral'))}</p>" if nu.get("referral") else "") + "</div>",
                    unsafe_allow_html=True)
    th = "".join(f"<li><span class='chip ev'>{esc(t.get('phase'))}</span> <b>{esc(t.get('treatment'))}</b><br>{esc(t.get('how_to_give'))}<br>"
                 f"<span style='color:var(--muted)'>{esc(t.get('rationale'))}"
                 + (f" · {tr('Monitor', 'المتابعة')}: {esc(t.get('monitoring'))}" if t.get("monitoring") else "") + "</span></li>"
                 for t in (m.get("medical_therapy") or []) if isinstance(t, dict))
    st.markdown(f"<div class='card'><div class='lbl'>{tr('Medical therapy', 'العلاج الدوائي')}</div><ul>{th or '<li>-</li>'}</ul></div>", unsafe_allow_html=True)
    fu = "".join(f"<li><b>{esc(x.get('when'))}</b>: {esc(x.get('what'))}</li>" for x in (m.get("monitoring_and_followup") or []) if isinstance(x, dict))
    c3, c4 = st.columns(2, gap="large")
    with c3:
        st.markdown(f"<div class='card'><div class='lbl'>{tr('Follow-up', 'المتابعة')}</div><ul>{fu or '<li>-</li>'}</ul></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='alert'><b>{tr('Escalate if', 'صعّد إذا')}:</b> " + " · ".join(esc(x) for x in (m.get("escalation_criteria") or [])) + "</div>"
                    f"<div class='card'><div class='lbl'>{tr('If not responding', 'إذا لم يستجب')}</div>{ul(m.get('if_not_responding'))}</div>",
                    unsafe_allow_html=True)
    with st.expander(tr("Surgery, prevention and patient education", "الجراحة والوقاية وتثقيف المريض")):
        st.markdown(f"**{tr('Surgical considerations', 'اعتبارات جراحية')}:** {m.get('surgical_considerations', '')}")
        st.markdown(f"**{tr('Preventive care', 'رعاية وقائية')}**")
        for x in m.get("preventive_care") or []:
            st.markdown(f"- {x}")
        st.markdown(f"**{tr('Patient education', 'تثقيف المريض')}**")
        for x in m.get("patient_education") or []:
            st.markdown(f"- {x}")
    if m.get("uncertainty_note"):
        st.caption(m["uncertainty_note"])


def render_text_result(t: dict):
    r = t["res"]
    st.markdown(f"<div class='card'><div class='lbl'>{tr('You asked', 'سؤالك')}: {esc(t['q'][:200])}</div>"
                f"<div class='lbl'>{tr('What is this?', 'ما هذا؟')}</div><h3>{esc(r.get('what_is_it'))}</h3>"
                f"<p>{esc(r.get('plain_explanation'))}</p></div>", unsafe_allow_html=True)
    if r.get("red_flags"):
        st.markdown(f"<div class='alert'><b>{tr('Needs attention', 'يحتاج انتباهاً')}:</b> "
                    + " · ".join(esc(x) for x in r["red_flags"]) + "</div>", unsafe_allow_html=True)
    rel = r.get("related_conditions") or []
    rl = "".join(f"<li><b>{esc(x.get('name'))}</b> - {esc(x.get('why'))}</li>" for x in rel if isinstance(x, dict))
    st.markdown(f"<div class='card'><div class='lbl'>{tr('Key points', 'نقاط مهمة')}</div>{ul(r.get('key_points'))}"
                + (f"<div class='test'><b>{tr('Why it matters clinically', 'أهميته الإكلينيكية')}:</b> {esc(r.get('clinical_relevance'))}</div>" if r.get("clinical_relevance") else "")
                + (f"<div class='lbl' style='margin-top:.6rem'>{tr('Related conditions', 'حالات مرتبطة')}</div><ul>{rl}</ul>" if rl else "")
                + (f"<div class='lbl'>{tr('Suggested next steps', 'الخطوات المقترحة')}</div>{ul(r.get('suggested_next_steps'))}" if r.get("suggested_next_steps") else "")
                + "</div>", unsafe_allow_html=True)
    if r.get("limitations"):
        st.caption(r["limitations"])


def md_bold(s) -> str:
    """Escape, then turn **word** into <b>word</b> (the model marks the key finding this way)."""
    return _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(s))


def _desc_title(r: dict) -> str:
    w = r.get("what_is_it") or {}
    m = " ".join(str(w.get(k) or "") for k in ("modality", "body_part_or_subject", "view_or_technique")).lower()
    pairs = [(("endoscop", "colonoscop", "gastroscop", "egd", "منظار"), ("Endoscopic description", "وصف المنظار")),
             (("x-ray", "xray", "radiograph", "ct", "mri", "computed", "magnetic", "أشعة"), ("Radiological description", "الوصف الشعاعي")),
             (("ecg", "ekg", "electrocardio"), ("ECG description", "وصف رسم القلب")),
             (("patholog", "histol", "microscop", "biopsy", "smear"), ("Microscopic description", "الوصف المجهري")),
             (("ultrasound", "sonograph", "echo"), ("Ultrasound description", "وصف الموجات فوق الصوتية")),
             (("skin", "wound", "rash", "lesion", "photograph", "جلد"), ("Description of the lesion", "وصف الآفة"))]
    for keys, (en, ar) in pairs:
        if any(k in m for k in keys):
            return tr(en, ar)
    return tr("Description", "الوصف")


def image_sections(r: dict):
    """-> [(title, [bullets])]. Built from fixed keys, so the headings are always the same
    and a small model only has to fill lists. Older results with 'sections' still work."""
    def L(v):
        return [str(x).strip() for x in (v or []) if x and str(x).strip()] if isinstance(v, list) else ([str(v)] if v else [])
    out = []
    if r.get("description") or r.get("suggests") or r.get("possible_causes") or r.get("next_steps"):
        out.append((_desc_title(r), L(r.get("description"))))
        out.append((tr("What it suggests", "ماذا قد يعني"), L(r.get("suggests"))))
        pc = []
        for c in (r.get("possible_causes") or []):
            if isinstance(c, dict) and c.get("name"):
                pc.append(f"**{str(c['name']).strip()}**" + (f" - {str(c.get('why')).strip()}" if c.get("why") else ""))
            elif isinstance(c, str) and c.strip():
                pc.append(c.strip())
        out.append((tr("Possible causes, given the context", "أسباب محتملة بحسب المعطيات"), pc))
        out.append((tr("What to check or do next", "ما الذي يُفحص أو يُفعل بعد ذلك"), L(r.get("next_steps"))))
        if L(r.get("cannot_tell")):
            out.append((tr("What this image cannot tell", "ما لا تُظهره هذه الصورة"), L(r.get("cannot_tell"))))
        kept = [(t, b) for t, b in out if b]
        return [(f"{n}. {t}", b) for n, (t, b) in enumerate(kept, 1)]
    for s_ in r.get("sections") or []:
        if isinstance(s_, dict):
            bl = [str(x) for x in (s_.get("bullets") or []) if x]
            if s_.get("title") or bl:
                out.append((str(s_.get("title") or ""), bl))
    return out


def render_image_result(i: int, it: dict):
    r = it["res"]
    w = r.get("what_is_it") or {}
    c_img, c_txt = st.columns([2, 3], gap="large")
    with c_img:
        st.image(it["bytes"], caption=bidi(it["name"]), **STRETCH)
    with c_txt:
        title = " · ".join(esc(x) for x in (w.get("modality"), w.get("body_part_or_subject"), w.get("view_or_technique")) if x)
        q = r.get("image_quality") or {}
        qchip = ""
        if q:
            qchip = (f"<span class='chip'>{tr('Image quality: good enough', 'جودة الصورة: كافية')}</span>" if q.get("adequate", True)
                     else f"<span class='chip must'>{tr('Image quality: limited', 'جودة الصورة: محدودة')}</span>")
        head = r.get("headline") or w.get("plain_description") or ""
        st.markdown(f"<div class='card'><div class='lbl'>{title or tr('What is this?', 'ما هذه الصورة؟')}</div>"
                    f"<p style='font-size:1.08rem;line-height:1.7;margin:.3rem 0 .5rem'>{md_bold(head)}</p>{qchip}</div>", unsafe_allow_html=True)
        if r.get("urgent_findings"):
            st.markdown(f"<div class='alert'><b>{tr('Needs attention now', 'يحتاج انتباهاً فورياً')}:</b> "
                        + " · ".join(esc(x) for x in r["urgent_findings"]) + "</div>", unsafe_allow_html=True)
        secs = image_sections(r)
        if secs:
            body = "".join(f"<h4 style='margin:.9rem 0 .25rem;color:var(--deep)'>{n}. {md_bold(t)}</h4>"
                           + ("<ul style='margin:.2rem 0'>" + "".join(f"<li style='margin:.2rem 0;line-height:1.6'>{md_bold(b_)}</li>" for b_ in bl) + "</ul>" if bl else "")
                           for n, (t, bl) in enumerate(secs, 1))
            st.markdown(f"<div class='card'>{body}</div>", unsafe_allow_html=True)
        if q.get("issues"):
            with st.expander(tr("Image quality notes", "ملاحظات جودة الصورة")):
                for x in q["issues"]:
                    st.markdown(f"- {x}")
        if r.get("answer_to_question"):
            st.markdown(f"<div class='note'><b>{tr('Your question', 'سؤالك')}:</b> {esc(it.get('question'))}<br>{md_bold(r['answer_to_question'])}</div>",
                        unsafe_allow_html=True)
        if r.get("extracted_text"):
            st.markdown(f"<div class='lbl'>{tr('Text read from the image (check every number)', 'النص المقروء من الصورة (راجع كل رقم)')}</div>",
                        unsafe_allow_html=True)
            st.code(r["extracted_text"], language=None)
        if r.get("limitations"):
            st.caption(r["limitations"])
        if r.get("_truncated"):
            st.warning(tr("The model was stopped part-way, so this reading may be incomplete.",
                          "أُوقف النموذج في منتصف القراءة فقد تكون ناقصة."))
        for q_, a_ in it.get("followups", []):
            st.markdown(f"<div class='note'><b>{esc(q_)}</b><br>{esc(a_.get('answer'))}"
                        + (f"<br><span style='color:var(--muted)'>{esc(a_.get('caveat'))}</span>" if a_.get("caveat") else "") + "</div>",
                        unsafe_allow_html=True)
        fq = st.text_input(tr("Ask about this image", "اسأل عن هذه الصورة"), key=f"fq_{i}",
                           placeholder=tr("e.g. Is there free air under the diaphragm?", "مثال: هل يوجد هواء حر تحت الحجاب الحاجز؟"))
        b1, b2, b3 = st.columns(3)
        if b1.button(tr("Ask", "اسأل"), key=f"fqb_{i}", disabled=len(fq.strip()) < 3):
            with st.spinner(tr("Looking again...", "أنظر مرة أخرى...")):
                try:
                    ans = providers.ask_json(prompts.IMAGE_FOLLOWUP + "\n" + prompts.lang_only(AI_LANG),
                                             f"EARLIER READING:\n{json.dumps({k: v for k, v in r.items() if not k.startswith('_')}, ensure_ascii=False)}\n\nQUESTION: {fq.strip()}",
                                             settings, images=[(it["mime"], it["bytes"])])
                    it.setdefault("followups", []).append((fq.strip(), ans))
                    st.rerun()
                except providers.ProviderError as e:
                    st.error(str(e))
        b2.button(tr("Add to the case", "أضفها إلى الحالة"), key=f"addc_{i}", on_click=add_img_to_case, args=(i,),
                  help=tr("Copies these findings into the Case tab so the differential can use them.",
                          "ينسخ هذه النتائج إلى تبويب الحالة ليستفيد منها التشخيص التفريقي."))
        b3.download_button(tr("Report", "تقرير"), image_report_html(it), key=f"imrep_{i}",
                           file_name=f"image_{time.strftime('%Y%m%d_%H%M')}_{i + 1}.html", mime="text/html",
                           icon=":material/download:")


with tab_img:
    st.markdown(f"### {tr('Image reader', 'قارئ الصور')}")
    st.caption(tr("Upload X-rays, CT, endoscopy, ECG, pathology slides, skin photos or even a photo of a lab report. "
                  "The AI says what the image is, what it shows, and what to consider. Run on your own computer with Ollama it is free and has no limits. "
                  "It is a reading aid for a clinician - never a diagnosis.",
                  "ارفع أشعة أو مقطعية أو مناظير أو رسم قلب أو شرائح باثولوجي أو صور جلد أو حتى صورة تقرير تحاليل. "
                  "يقول الذكاء ما هي الصورة وما الذي تُظهره وما الذي يجب التفكير فيه. إذا شغّلته على حاسوبك عبر Ollama فهو مجاني بلا حدود. "
                  "هو أداة مساعدة للقراءة للطبيب - وليس تشخيصاً."))
    show_engine_status("img")
    mode = st.radio(tr("What do you want to identify?", "ماذا تريد أن تعرف؟"), ["image", "text"], horizontal=True, key="idmode",
                    format_func=lambda x: {"image": tr("A picture (X-ray, ECG, skin, endoscopy, lab report...)", "صورة (أشعة، رسم قلب، جلد، منظار، تقرير...)"),
                                           "text": tr("Words (a term, drug, lab result, symptom, report text...)", "كلمات (مصطلح، دواء، نتيجة تحليل، عَرَض، نص تقرير...)")}[x])
    if mode == "text":
        tq = st.text_area(tr("Paste or type it here", "الصقه أو اكتبه هنا"), height=140, key="id_text",
                          placeholder=tr("e.g. 'ANA 1:640 speckled, anti-dsDNA positive' or 'what is Murphy's sign?'",
                                         "مثال: ANA 1:640 speckled مع anti-dsDNA موجب  أو  ما هي علامة Murphy؟"))
        if st.button(tr("What is this?", "ما هذا؟"), type="primary", disabled=len(tq.strip()) < 2, key="go_txt"):
            with st.spinner(tr("Thinking...", "جارٍ التفكير...")):
                try:
                    r_ = providers.ask_json(prompts.IDENTIFY_TEXT + "\n" + prompts.lang_only(AI_LANG), tq.strip(), settings)
                    st.session_state.txt_results.insert(0, {"q": tq.strip(), "res": r_})
                    log_event(action="identify_text", provider=settings.get("provider"))
                except providers.ProviderError as e:
                    st.error(str(e))
        for t_ in st.session_state.txt_results:
            render_text_result(t_)
        if st.session_state.txt_results and st.button(tr("Clear", "امسح"), key="clr_txt"):
            st.session_state.txt_results = []
            st.rerun()
    if mode == "image":
        li, ri = st.columns([2, 3], gap="large")
        with li:
            up_key = f"img_up_{st.session_state.get('img_up_n', 0)}"
            img_files = st.file_uploader(tr("Choose one or more images", "اختر صورة أو أكثر"), key=up_key,
                                         type=sorted(e.lstrip(".") for e in files.IMAGE_EXT), accept_multiple_files=True)
            itype = st.selectbox(tr("What kind of image is it?", "ما نوع الصورة؟"), prompts.IMAGE_TYPES,
                                 format_func=lambda x: config.IMAGE_TYPE_LABELS[x][LANG])
            ictx = st.text_area(tr("Clinical context (optional)", "السياق الإكلينيكي (اختياري)"), height=90, key="img_ctx",
                                placeholder=tr("e.g. 60-year-old, 3 days of cough and fever", "مثال: عمره ٦٠ سنة، سعال وحرارة منذ ٣ أيام"))
            iq = st.text_input(tr("A specific question (optional)", "سؤال محدد (اختياري)"), key="img_q",
                               placeholder=tr("e.g. Is there a pleural effusion?", "مثال: هل يوجد انصباب جنبي؟"))
            hires = st.checkbox(tr("High detail (slower, better for small findings)", "تفاصيل عالية (أبطأ، أفضل للموجودات الصغيرة)"), key="img_hires")
            who_img = bidi(image_model_label())
            st.caption(tr(f"Image model: {who_img}", f"نموذج الصور: {who_img}"))
            go_img = st.button(tr("Read the image(s)", "اقرأ الصور"), type="primary", disabled=not img_files, key="go_img")
        with ri:
            if go_img and img_files:
                out, bar, info = [], st.progress(0.0), st.empty()
                for k, f in enumerate(img_files):
                    try:
                        mime, jpg = files.prepare_image(f.getvalue(), 2800 if hires else 1600)
                    except Exception as e:
                        st.warning(f"{bidi(f.name)}: {e}")
                        continue
                    label = tr(f"Reading image {k + 1} of {len(img_files)}: {f.name}", f"قراءة الصورة {k + 1} من {len(img_files)}: {f.name}")

                    def prog(n, secs, _l=label):
                        info.caption(f"{_l} · " + tr(f"{n} tokens · {secs:.0f}s", f"{n} رمز · {secs:.0f} ث"))
                    info.caption(label)
                    user_txt = ("CLINICAL CONTEXT: " + (ictx.strip() or "none given") +
                                "\nQUESTION: " + (iq.strip() or "none - just say what this is and what it shows"))
                    try:
                        res = providers.ask_json(prompts.image_prompt(itype) + "\n" + prompts.lang_only(AI_LANG),
                                                 user_txt, settings, images=[(mime, jpg)], on_progress=prog)
                        out.append({"name": f.name, "mime": mime, "bytes": jpg, "res": res, "question": iq.strip(), "followups": [],
                                    "model": f"{prov_label} · {image_model_label()}"})
                        log_event(action="read_image", provider=settings.get("provider"), type=itype)
                    except providers.MissingVisionModel:
                        st.session_state.need_vision_img = True
                        break
                    except providers.ProviderError as e:
                        st.error(f"{bidi(f.name)}: {e}")
                    bar.progress((k + 1) / len(img_files))
                info.empty()
                bar.empty()
                if out:
                    st.session_state.img_results = out
                    st.session_state.need_vision_img = False
                    st.toast(tr(f"{len(out)} image(s) read", f"تمت قراءة {len(out)} صورة"), icon=":material/check_circle:")
            if st.session_state.get("need_vision_img"):
                vision_setup_panel("img")
            if not st.session_state.img_results and not st.session_state.get("need_vision_img"):
                st.markdown(f"<div class='empty'>{tr('Choose an image on the left and press Read. The result appears here.', 'اختر صورة من اليسار واضغط اقرأ. تظهر النتيجة هنا.')}</div>",
                            unsafe_allow_html=True)
        for i, it in enumerate(st.session_state.img_results):
            st.markdown("---")
            render_image_result(i, it)
        if st.session_state.img_results:
            if st.button(tr("Clear all results", "امسح كل النتائج"), key="clr_img"):
                st.session_state.img_results = []
                st.session_state["img_up_n"] = st.session_state.get("img_up_n", 0) + 1
                st.rerun()


# ============================================================ TAB - MANAGEMENT
with tab_mg:
    st.markdown(f"### {tr('Management plan', 'خطة العلاج')}")
    st.caption(tr("Uses the case from the Case tab (typed text, Word, PowerPoint, PDF, Excel and any image findings you added). "
                  "The AI proposes a plan; the treating physician decides.",
                  "تستخدم الحالة من تبويب الحالة (النص وWord وPowerPoint وPDF وExcel ونتائج الصور المضافة). "
                  "الذكاء يقترح خطة والطبيب المعالج هو من يقرر."))
    show_engine_status("mg")
    vis_text, hidden_text, q_slide = split_answer_slides(full_text)
    if not full_text.strip():
        st.markdown(f"<div class='empty'>{tr('Enter or upload the case in the Case tab first.', 'أدخل الحالة أو ارفعها في تبويب الحالة أولاً.')}</div>",
                    unsafe_allow_html=True)
    else:
        hide = False
        if hidden_text:
            hide = st.checkbox(tr(f"Slide {q_slide} asks 'Management plan?'. Hide the slides after it (the answer) so the AI makes its own plan",
                                  f"الشريحة {q_slide} تسأل «خطة العلاج؟». أخفِ الشرائح بعدها (الإجابة) ليضع الذكاء خطته بنفسه"),
                               value=True, key="mg_hide")
        dd_list = [d["diagnosis"] for d in (st.session_state.dd_result or {}).get("differential", []) if d.get("diagnosis")]
        auto_lbl = tr("Let the AI decide from the case", "دع الذكاء يقرر من الحالة")
        pick = st.selectbox(tr("Working diagnosis", "التشخيص العامل"), [auto_lbl] + dd_list + [tr("Type my own...", "أكتب تشخيصي...")], key="mg_dx")
        own_dx = st.text_input(tr("Your working diagnosis", "تشخيصك العامل"), key="mg_own") if pick == tr("Type my own...", "أكتب تشخيصي...") else ""
        m1, m2 = st.columns(2)
        care = m1.selectbox(tr("Care setting", "مكان الرعاية"), ["any", "outpatient clinic", "emergency department", "inpatient ward", "ICU"],
                            format_func=lambda x: {"any": tr("Not specified", "غير محدد"), "outpatient clinic": tr("Outpatient clinic", "عيادة خارجية"),
                                                   "emergency department": tr("Emergency", "الطوارئ"), "inpatient ward": tr("Inpatient ward", "قسم داخلي"),
                                                   "ICU": tr("ICU", "عناية مركزة")}[x], key="mg_care")
        doses = m2.checkbox(tr("Include usual adult dose ranges (check your formulary)", "اذكر المدى المعتاد لجرعات البالغين (راجع دليلك الدوائي)"), key="mg_doses")
        extra = st.text_area(tr("Anything that changes the plan (optional)", "ما يغيّر الخطة (اختياري)"), height=70, key="mg_extra",
                             placeholder=tr("e.g. pregnant, limited drug availability, kidney disease, patient prefers to avoid injections",
                                            "مثال: حامل، أدوية غير متوفرة، مرض كلوي، المريض يفضل تجنب الحقن"))
        who_m = bidi(f"{prov_label} · {model_label()}")
        st.caption(tr(f"Will be answered by {who_m}", f"سيجيب عليها {who_m}"))
        if st.button(tr("Propose a management plan", "اقترح خطة علاج"), type="primary", key="go_mg"):
            case_for_ai = vis_text if (hidden_text and hide) else full_text
            dxs_ = own_dx.strip() if own_dx.strip() else ("" if pick == auto_lbl else pick)
            user_ = ("CASE:\n" + case_for_ai + ("\n\nWORKING DIAGNOSIS TO MANAGE: " + dxs_ if dxs_ else "")
                     + ("\n\nEXTRA CONSIDERATIONS: " + extra.strip() if extra.strip() else ""))
            sysm = (prompts.management_prompt(doses, care) + "\n" + prompts.lang_only(AI_LANG) + "\n"
                    + prompts.department_rule(settings.get("department", ""), settings.get("department_other", ""), settings.get("specialty_hint", "")))
            with st.status(tr("Working...", "جارٍ العمل..."), expanded=True) as stt:
                ph = st.empty()

                def prog_m(n, secs):
                    ph.caption(tr(f"Writing: {n} tokens · {secs:.0f}s", f"جارٍ الكتابة: {n} رمز · {secs:.0f} ث"))
                try:
                    imgs_ = proc["images"] or None
                    m_ = providers.ask_json(sysm, user_, settings, images=imgs_, on_progress=prog_m)
                    ph.empty()
                    st.session_state.mgmt, st.session_state.mgmt_cmp = m_, None
                    st.session_state["mgmt_hidden"] = hidden_text if (hidden_text and hide) else ""
                    st.write(tr("Looking up guidelines for the working diagnosis", "البحث عن إرشادات للتشخيص العامل"))
                    try:
                        recs, errs_ = knowledge.gather(m_.get("working_diagnosis") or dxs_ or "", (m_.get("search_terms") or "") + " management guideline",
                                                       settings, selected=[s for s in ("guidelines", "reviews", "medlineplus", "local") if s in knowledge.SOURCES])
                        st.session_state.mgmt_src = recs
                    except Exception:
                        st.session_state.mgmt_src = []
                    log_event(action="management_plan", provider=settings.get("provider"))
                    stt.update(label=tr("Done", "تم"), state="complete", expanded=False)
                except providers.MissingVisionModel:
                    stt.update(label=tr("An image-reading model is needed. Remove the pictures or set one up in Settings.", "مطلوب نموذج صور. احذف الصور أو جهّزه من الإعدادات."), state="error")
                except providers.ProviderError as e:
                    stt.update(label=tr("Something went wrong", "حدث خطأ"), state="error")
                    st.error(str(e))
        m_res = st.session_state.mgmt
        if m_res:
            if m_res.get("_truncated"):
                st.warning(tr("The model was stopped part-way, so this plan may be incomplete. A bigger model or a free Groq/Gemini key gives fuller plans.",
                              "أُوقف النموذج في منتصف الكتابة فقد تكون الخطة ناقصة. نموذج أكبر أو مفتاح Groq/Gemini المجاني يعطي خططاً أكمل."))
            render_management(m_res)
            hid = st.session_state.get("mgmt_hidden", "")
            if hid:
                if st.button(tr("Compare with the plan in the presentation", "قارن مع الخطة في العرض"), key="go_cmp"):
                    with st.spinner(tr("Comparing...", "جارٍ المقارنة...")):
                        try:
                            clean = {k: v for k, v in m_res.items() if not k.startswith("_")}
                            st.session_state.mgmt_cmp = providers.ask_json(
                                prompts.MANAGEMENT_COMPARE + "\n" + prompts.lang_only(AI_LANG),
                                "(A) AI PLAN:\n" + json.dumps(clean, ensure_ascii=False) + "\n\n(B) PLAN FROM THE PRESENTATION (slides after the question):\n" + hid, settings)
                        except providers.ProviderError as e:
                            st.error(str(e))
                c_ = st.session_state.mgmt_cmp
                if c_:
                    rows = "".join(f"<li><b>{esc(d.get('topic'))}</b><br>{tr('AI', 'الذكاء')}: {esc(d.get('ai_plan'))}<br>{tr('Presentation', 'العرض')}: {esc(d.get('deck_plan'))}<br>"
                                   f"<span style='color:var(--muted)'>{esc(d.get('comment'))}</span></li>" for d in (c_.get("differences") or []) if isinstance(d, dict))
                    st.markdown(f"<div class='card'><div class='lbl'>{tr('Agree', 'اتفاق')}</div>{ul(c_.get('agreements'))}"
                                f"<div class='lbl'>{tr('Differences', 'اختلافات')}</div><ul>{rows or '<li>-</li>'}</ul>"
                                f"<div class='lbl'>{tr('Only in the presentation', 'في العرض فقط')}</div>{ul(c_.get('only_in_deck'))}"
                                f"<div class='lbl'>{tr('Only in the AI plan', 'في خطة الذكاء فقط')}</div>{ul(c_.get('only_in_ai_plan'))}"
                                f"<div class='lbl'>{tr('Teaching points', 'نقاط تعليمية')}</div>{ul(c_.get('teaching_points'))}</div>", unsafe_allow_html=True)
            srcs_ = st.session_state.mgmt_src or []
            if srcs_:
                with st.expander(tr(f"Guidelines and reviews to check this plan against ({len(srcs_)})", f"إرشادات ومراجعات لمراجعة الخطة عليها ({len(srcs_)})"),
                                 icon=":material/menu_book:"):
                    st.caption(tr("Found for the working diagnosis. The plan above was written by the AI from general knowledge and is NOT quoted from these - open them to verify.",
                                  "وُجدت للتشخيص العامل. الخطة أعلاه كتبها الذكاء من معرفته العامة وليست مقتبسة من هذه المصادر - افتحها للتحقق."))
                    for s_ in srcs_:
                        lab = knowledge.SOURCES.get(s_["source"], {}).get("ar" if RTL else "en", s_["source"])
                        st.markdown(f"- **{bidi(s_.get('title', ''))}** · {bidi(s_.get('journal', ''))} {s_.get('year', '')} · {lab}"
                                    + (f" · [{tr('open', 'فتح')}]({s_['url']})" if s_.get("url") else ""))
            prov_m = {"_org": settings.get("org_name", ""), tr("Generated", "تاريخ الإنشاء"): bidi(time.strftime("%Y-%m-%d %H:%M")),
                      tr("Model", "النموذج"): bidi(f"{prov_label} · {model_label()}")}
            st.download_button(tr("Download report", "تنزيل التقرير"),
                               management_report_html(m_res, st.session_state.mgmt_cmp, srcs_, {k: v for k, v in prov_m.items() if k != "_org"}),
                               file_name=f"management_{time.strftime('%Y%m%d_%H%M')}.html", mime="text/html", icon=":material/download:", key="dl_mg")


# ============================================================ TAB 2 - DD
with tab2:
    res = st.session_state.dd_result
    if not res:
        st.markdown(f"<div class='empty'>{tr('Generate a differential in the first tab.', 'أنشئ التشخيص التفريقي من التبويب الأول.')}</div>",
                    unsafe_allow_html=True)
    else:
        s = res.get("case_summary", {})
        st.markdown(f"<div class='card'><div class='lbl'>{tr('Case summary', 'ملخص الحالة')}</div>"
                    f"<h3>{esc(s.get('one_line'))}</h3><div class='two'>"
                    f"<div><div class='lbl'>{tr('Key positive findings', 'نتائج مهمة موجودة')}</div>{ul(s.get('key_positive_findings'))}</div>"
                    f"<div><div class='lbl'>{tr('Negative / missing', 'نتائج سلبية / ناقصة')}</div>{ul(s.get('key_negative_or_missing'))}</div>"
                    f"</div></div>", unsafe_allow_html=True)
        if res.get("image_findings"):
            st.markdown(f"<div class='imgfind'><div class='lbl'>{tr('Image findings (draft - verify)', 'ما ظهر في الصور (مسودة - تحقق)')}</div>{ul(res['image_findings'])}</div>",
                        unsafe_allow_html=True)
        if res.get("red_flags_now"):
            st.markdown(f"<div class='alert'><b>{tr('Red flags needing action now', 'علامات خطر تحتاج تدخلاً فورياً')}:</b> "
                        + " · ".join(esc(x) for x in res["red_flags_now"]) + "</div>", unsafe_allow_html=True)

        top = st.columns([4, 1])
        top[0].markdown(f"### {tr('Ranked differential', 'التشخيص التفريقي المرتب')}")
        n_refs = sum(len(v or []) for v in st.session_state.evidence.values())
        prov = {"_org": settings.get("org_name", ""),
                tr("Generated", "تاريخ الإنشاء"): bidi(time.strftime("%Y-%m-%d %H:%M")),
                tr("Model", "النموذج"): bidi(f"{prov_label} · {model_label()}"),
                tr("Department", "القسم"): bidi(dep_name) if dep_name else tr("not set", "غير محدد"),
                tr("Passages from sources", "مقاطع من المصادر"): str(n_refs) if n_refs else tr("none retrieved", "لم تُسترجع")}
        top[1].download_button(
            tr("Report", "تقرير"),
            report_html(res, st.session_state.evidence, st.session_state.notes, prov),
            file_name=f"differential_{time.strftime('%Y%m%d_%H%M')}.html",
            mime="text/html",
            icon=":material/download:",
            help=tr("A one-file document: summary, differential and PubMed evidence together. "
                    "Open it and print or save as PDF.",
                    "مستند واحد: الملخص والتشخيص التفريقي وأدلة PubMed معاً. "
                    "افتحه ثم اطبعه أو احفظه PDF."))
        pct = {"high": 88, "moderate": 58, "low": 28}
        for d in res.get("differential", []):
            lk = d.get("likelihood", "low")
            must = bool(d.get("must_exclude_first"))
            n_ev = len(st.session_state.evidence.get(d.get("diagnosis"), []) or [])
            must_txt = tr("MUST EXCLUDE", "يجب استبعاده أولاً")
            chips = (f"<span class='chip must'>{icon('warning', must_txt)}{esc(must_txt)}</span>" if must else "") + \
                f"<span class='chip {esc(lk)}'>{esc(lk)}</span>" + \
                (f"<span class='chip ev'>{n_ev} {tr('sources', 'مصادر')}</span>" if n_ev else "")
            st.markdown(
                f"<div class='card dx {'must' if must else esc(lk)}'><div class='dx-head'>"
                f"<span class='rank'>{esc(d.get('rank'))}</span><span class='dx-name'>{esc(d.get('diagnosis'))}</span>{chips}</div>"
                f"<div class='meter'><i style='width:{pct.get(lk, 28)}%'></i></div><div class='two'>"
                f"<div><div class='lbl'>{tr('Supporting', 'يدعمه')}</div>{ul(d.get('supporting_findings'))}</div>"
                f"<div><div class='lbl'>{tr('Arguing against', 'ضده')}</div>{ul(d.get('arguing_against'))}</div></div>"
                f"<div class='test'><b>{tr('Confirmatory test', 'فحص للتأكيد')}:</b> {esc(d.get('confirmatory_test'))}</div></div>",
                unsafe_allow_html=True)
        if res.get("uncertainty_note"):
            st.caption(res["uncertainty_note"])
        if res.get("missing_information"):
            st.markdown(f"<div class='note'><b>{tr('Worth asking / ordering', 'معلومات ينقصنا طلبها')}:</b> "
                        + " · ".join(esc(x) for x in res["missing_information"]) + "</div>", unsafe_allow_html=True)

# ============================================================ TAB 3 - evidence
def src_label(k: str) -> str:
    return knowledge.SOURCES[k]["ar" if RTL else "en"]


with tab3:
    res = st.session_state.dd_result
    if not res:
        st.markdown(f"<div class='empty'>{tr('Generate a differential first.', 'أنشئ التشخيص التفريقي أولاً.')}</div>",
                    unsafe_allow_html=True)
    else:
        dxs = [(d["diagnosis"], d.get("search_terms", "")) for d in res.get("differential", []) if d.get("diagnosis")]
        default_src = [s for s in settings.get("knowledge_sources", knowledge.DEFAULT_SOURCES) if s in knowledge.SOURCES]
        st.markdown(f"### {tr('Where the answers come from', 'من أين تأتي الأدلة')}")
        st.caption(tr("Every source below is free. Guidelines and reviews outrank single articles; MedlinePlus and Wikipedia are background only. "
                      "Add your own documents under Settings -> Knowledge sources.",
                      "كل المصادر أدناه مجانية. الإرشادات والمراجعات أعلى درجة من المقالات المفردة؛ وMedlinePlus وويكيبيديا للخلفية فقط. "
                      "أضف مستنداتك الخاصة من الإعدادات ← مصادر المعرفة."))
        chosen = st.multiselect(tr("Sources to search", "المصادر التي يُبحث فيها"), list(knowledge.SOURCES), default=default_src,
                                key="ev_sources", format_func=src_label)
        have = st.session_state.evidence
        label = (tr(f"Search again in these {len(chosen)} sources", f"ابحث مجدداً في هذه المصادر ({len(chosen)})")
                 if have else tr(f"Search {len(dxs)} diagnoses in {len(chosen)} sources", f"ابحث عن {len(dxs)} تشخيصات في {len(chosen)} مصادر"))
        if st.button(label, type="primary", disabled=not chosen or not dxs):
            with st.spinner(tr("Searching all sources in parallel...", "البحث في كل المصادر بالتوازي...")):
                ev, errs = knowledge.gather_many(dxs, settings, selected=chosen)
            st.session_state.evidence, st.session_state.kb_errors, st.session_state.notes = ev, errs, {}
            st.rerun()
        errs = st.session_state.get("kb_errors") or {}
        if errs:
            st.warning(tr("Some sources did not answer (usually no internet, or the site is busy). The others are shown. ",
                          "بعض المصادر لم تُجب (غالباً لا يوجد إنترنت أو الموقع مشغول). تُعرض المصادر الأخرى. ")
                       + " · ".join(f"{bidi(k)}: {bidi(v[:70])}" for k, v in errs.items()))
        for i_dx, (dx, _) in enumerate(dxs):
            hits = st.session_state.evidence.get(dx)
            if hits is None:
                continue
            st.markdown(f"### {esc(dx)}")
            if not hits:
                st.caption(tr("Nothing found in the chosen sources - try a broader term or add more sources.",
                              "لا شيء في المصادر المختارة - جرّب مصطلحاً أوسع أو أضف مصادر."))
                continue
            counts = {}
            for h in hits:
                counts[h["source"]] = counts.get(h["source"], 0) + 1
            st.markdown("".join(f"<span class='chip ev'>{esc(src_label(k))} {n}</span>" for k, n in counts.items()),
                        unsafe_allow_html=True)
            for n_, h in enumerate(hits, 1):
                grade_bg = h["source"] in ("medlineplus", "wikipedia")
                title_html = (f"<a href='{esc(h['url'])}' target='_blank' rel='noopener'>{esc(h['title'])}"
                              f"{icon('open_in_new', tr('opens in a new tab', 'يفتح في تبويب جديد'))}</a>") if h.get("url") else f"<b>{esc(h['title'])}</b>"
                meta = " · ".join(esc(x) for x in (h.get("journal"), h.get("year"), h.get("ref")) if x)
                st.markdown(f"<div class='card art'><span class='chip'>S{n_}</span><span class='chip ev'>{esc(src_label(h['source']))}"
                            f"{(' · ' + tr('background', 'خلفية')) if grade_bg else ''}</span>{title_html}"
                            f"<div class='meta'>{meta}</div></div>", unsafe_allow_html=True)
                if h.get("abstract"):
                    with st.expander(tr("Full text of this passage", "النص الكامل لهذا المقطع")):
                        st.write(h["abstract"])
            note = st.session_state.notes.get(dx)
            if not note and st.button(tr("Write a note from these sources", "اكتب ملاحظة من هذه المصادر"), key=f"gn_{i_dx}"):
                prompt_user = (f"DIAGNOSIS: {dx}\n\nCASE SUMMARY: {(res.get('case_summary') or {}).get('one_line', '')}\n\n"
                               f"PASSAGES:\n{knowledge.format_for_llm(hits)}")
                ph = st.empty()

                def prog(n, secs):
                    ph.caption(tr(f"Writing: {n} tokens · {secs:.0f}s", f"جارٍ الكتابة: {n} رمز · {secs:.0f} ث"))
                with st.spinner(tr("Reading the passages and writing the note...", "قراءة المقاطع وكتابة الملاحظة...")):
                    try:
                        st.session_state.notes[dx] = providers.ask_json(
                            prompts.GROUNDED_NOTE + "\n" + prompts.lang_only(AI_LANG),
                            prompt_user, settings, on_progress=prog)
                        st.rerun()
                    except providers.ProviderError as e:
                        st.error(str(e))
            if note:
                kp = note.get("key_points") or []
                st.markdown(f"<div class='note'><b>{tr('Note from the sources', 'ملاحظة من المصادر')}</b><br>{esc(note.get('grounded_assessment'))}"
                            + (ul(kp) if kp else "") +
                            f"<div class='meta' style='color:var(--muted);font-size:.8rem;margin-top:.4rem'>{tr('S1, S2... match the numbered passages above.', 'S1 وS2... تطابق المقاطع المرقّمة أعلاه.')}</div></div>",
                            unsafe_allow_html=True)
                if note.get("snippets_insufficient"):
                    st.warning(tr("The retrieved sources were not enough for this case - try searching: ",
                                  "المصادر المسترجعة لا تكفي لهذه الحالة - جرّب: ") + str(note.get("what_to_search_next", "")))


# =============================================================== TAB - settings
def model_guide_picker(kind: str, installed: list, key: str, url: str):
    """Browse the free-model guide, read plain advice, download in one click."""
    guide = config.TEXT_MODELS if kind == "text" else config.VISION_MODELS
    tags = [m["tag"] for m in guide]
    inst = set(installed) | {n.split(":latest")[0] for n in installed}

    def lab(t):
        m = next(x for x in guide if x["tag"] == t)
        return f"{t}  ·  ~{m['gb']} GB  ·  " + (tr("installed", "مثبّت") if t in inst else tr("not installed", "غير مثبّت"))
    pick = st.selectbox(tr("Free models worth knowing (pick one to read about it)", "نماذج مجانية مهمة (اختر واحداً لتقرأ عنه)"),
                        tags, key=f"{key}_guide", format_func=lab)
    m = next(x for x in guide if x["tag"] == pick)
    st.info(m["ar" if RTL else "en"] + "  " + tr(f"Comfortable with about {m['ram']} GB of memory.",
                                                 f"مريح مع نحو {m['ram']} جيجا ذاكرة."))
    other = st.text_input(tr("...or type any other model name from ollama.com/library", "...أو اكتب أي اسم نموذج آخر من ollama.com/library"),
                          key=f"{key}_other", placeholder="qwen3:8b")
    target = other.strip() or pick
    if st.button(tr(f"Download {target}", f"نزّل {target}"), key=f"{key}_pull", disabled=target in inst):
        bar, txt = st.progress(0.0), st.empty()
        try:
            for status_, frac in providers.pull_ollama_model({"ollama_url": url}, target):
                txt.caption(status_)
                if frac is not None:
                    bar.progress(frac)
            st.success(tr(f"Downloaded {target}. Reload this page, then pick it in the list above and press Save.",
                          f"تم تنزيل {target}. أعد تحميل الصفحة ثم اخترْه من القائمة أعلاه واضغط حفظ."))
        except providers.ProviderError as e:
            st.error(str(e))


def key_note(name: str):
    own = bool(settings.get(f"{name}_api_key"))
    if os.environ.get(config.ENV_KEYS[name]) and not own:
        st.caption(tr("This server already has a key, so you can leave this empty - or paste your own to use your own limits.",
                      "هذا الخادم لديه مفتاح بالفعل، فيمكنك ترك الخانة فارغة - أو الصق مفتاحك لاستخدام حدودك أنت."))
    elif config.PUBLIC_MODE:
        st.caption(tr("Your key stays in this browser session only. It is not saved on the server and disappears when you close the tab.",
                      "يبقى مفتاحك في جلسة المتصفح هذه فقط. لا يُحفظ على الخادم ويختفي عند إغلاق التبويب."))
    st.caption(tr("Get a free key in 2 minutes: " + ("console.groq.com" if name == "groq" else "aistudio.google.com/apikey"),
                  "احصل على مفتاح مجاني خلال دقيقتين: " + ("console.groq.com" if name == "groq" else "aistudio.google.com/apikey")))


with tab5:
    st.markdown(f"## {tr('Settings (no coding needed)', 'الإعدادات (بدون أي كود)')}")
    st.caption(tr("Change anything here and press Save at the bottom.", "غيّر ما تريد هنا ثم اضغط حفظ في الأسفل."))

    with st.expander(tr("AI engine", "محرك الذكاء الاصطناعي"), expanded=True):
        provider = st.selectbox(
            tr("Where should the AI run?", "أين يعمل الذكاء الاصطناعي؟"),
            PROV_OPTIONS, index=PROV_OPTIONS.index(settings.get("provider", "groq")) if settings.get("provider", "groq") in PROV_OPTIONS else 0,
            format_func=lambda p: {"groq": tr("Groq - free cloud, very fast, needs internet and a free key",
                                              "Groq - سحابة مجانية سريعة جداً، تحتاج إنترنت ومفتاحاً مجانياً"),
                                   "gemini": tr("Google Gemini - free cloud, reads images well, needs a free key",
                                                "Google Gemini - سحابة مجانية، تقرأ الصور جيداً، تحتاج مفتاحاً مجانياً"),
                                   "openai": tr("OpenAI (ChatGPT models) - paid per use with your own key, strong at images",
                                                "OpenAI (نماذج ChatGPT) - مدفوع حسب الاستخدام بمفتاحك الخاص، قوي في الصور"),
                                   "ollama": tr("Ollama - on THIS computer: private, free, no limits, works offline",
                                                "Ollama - على هذا الحاسوب: خاص ومجاني بلا حدود ويعمل بدون إنترنت")}[p])
        if provider != settings.get("provider", "groq"):
            st.warning(tr("You changed the engine but have not saved yet. Scroll to the bottom and press Save settings - until then the app keeps using the old one.",
                          "غيّرت المحرك ولم تحفظ بعد. انزل إلى الأسفل واضغط حفظ - إلى ذلك الحين يبقى التطبيق على المحرك القديم."))
        speed = st.radio(tr("Speed (cloud only)", "السرعة (للسحابة فقط)"), ["balanced", "fast"], horizontal=True,
                         index=["balanced", "fast"].index(settings.get("speed", "balanced")),
                         format_func=lambda x: {"balanced": tr("Balanced (best quality)", "متوازن (أفضل جودة)"),
                                                "fast": tr("Fast (smaller cloud model)", "سريع (نموذج سحابي أصغر)")}[x])
        auto_ev = st.checkbox(tr("Look up every diagnosis in the knowledge sources automatically (parallel, adds a few seconds)",
                                 "ابحث تلقائياً عن كل تشخيص في مصادر المعرفة (بالتوازي)"),
                              value=bool(settings.get("auto_evidence", True)))
        groq_key = groq_model = groq_vision = gemini_key = gemini_model = openai_key = openai_model = ""
        openai_reason = "low"
        gemini_think = "low"
        ollama_url = ollama_model = ollama_vision = ""
        ollama_num_ctx, ollama_num_predict, ollama_auto_ctx = 16384, 0, True
        if provider == "groq":
            groq_key = st.text_input("Groq API key", value=settings.get("groq_api_key", ""), type="password")
            key_note("groq")
            groq_model = st.text_input("Groq model (text)", value=settings.get("groq_model", "openai/gpt-oss-120b"))
            groq_vision = st.text_input(tr("Groq vision model (used when images are attached)", "نموذج الرؤية في Groq (للصور)"),
                                        value=settings.get("groq_vision_model", "qwen/qwen3.8-27b"))
            st.caption(tr("Groq's free plan has a daily allowance, so it is not unlimited. For no limit at all choose Ollama.",
                          "الخطة المجانية في Groq لها حد يومي فليست بلا حدود. لبلا حدود اختر Ollama."))
        elif provider == "gemini":
            gemini_key = st.text_input("Gemini API key", value=settings.get("gemini_api_key", ""), type="password")
            key_note("gemini")
            gemini_model = st.text_input(tr("Gemini model (reads text and images)", "نموذج Gemini (يقرأ النص والصور)"),
                                         value=settings.get("gemini_model", "gemini-3.8-flash"))
            _lv = ["low", "medium", "high", "minimal"]
            gemini_think = st.selectbox(
                tr("Thinking depth (low = fast, high = slower and more careful)", "عمق التفكير (low أسرع، high أبطأ وأدق)"),
                _lv, index=_lv.index(settings.get("gemini_thinking", "low")) if settings.get("gemini_thinking", "low") in _lv else 0)
            st.caption(tr("Gemini's free plan has per-minute and daily limits, so it is not unlimited. For no limit at all choose Ollama.",
                          "الخطة المجانية في Gemini لها حدود في الدقيقة واليوم فليست بلا حدود. لبلا حدود اختر Ollama."))
        elif provider == "openai":
            openai_key = st.text_input("OpenAI API key", value=settings.get("openai_api_key", ""), type="password")
            key_note("openai")
            openai_model = st.text_input(tr("OpenAI model (reads text and images)", "نموذج OpenAI (يقرأ النص والصور)"),
                                         value=settings.get("openai_model", "gpt-5.6-luna"))
            _ol = ["low", "medium", "high", "none"]
            openai_reason = st.selectbox(
                tr("Reasoning effort (low = fast and cheap, high = slower and more careful)", "جهد التفكير (low أسرع وأرخص، high أبطأ وأدق)"),
                _ol, index=_ol.index(settings.get("openai_reasoning", "low")) if settings.get("openai_reasoning", "low") in _ol else 0)
            st.warning(tr("The OpenAI API is not free: you pay per use from your own OpenAI account (about a few cents per image on the small model). "
                          "Create a key at platform.openai.com/api-keys and add a little credit under Billing.",
                          "واجهة OpenAI ليست مجانية: تدفع حسب الاستخدام من حسابك. أنشئ مفتاحاً من platform.openai.com/api-keys وأضف رصيداً صغيراً من Billing."))
        else:
            ollama_url = st.text_input("Ollama address", value=settings.get("ollama_url", "http://localhost:11434"))
            det = providers.list_ollama_models_detailed({"ollama_url": ollama_url})
            installed = [m["name"] for m in det]
            gb = {m["name"]: m["gb"] for m in det}
            cur_model = settings.get("ollama_model", "qwen2.5:7b")
            cur_vis = settings.get("ollama_vision_model", "medgemma:4b")
            if installed:
                st.success(tr(f"Ollama is running with {len(installed)} model(s) installed.",
                              f"Ollama شغّال وفيه {len(installed)} نموذج مثبّت."))
                ollama_model = st.selectbox(tr("Model that writes the differential", "النموذج الذي يكتب التشخيص التفريقي"), installed,
                                            index=installed.index(cur_model) if cur_model in installed else 0,
                                            format_func=lambda n: f"{n}  ·  {gb.get(n, '?')} GB")
                vis_installed = [n for n in installed if providers.is_vision_model({"ollama_url": ollama_url}, n)]
                vis_opts = vis_installed + ([cur_vis] if cur_vis not in vis_installed else [])
                ollama_vision = st.selectbox(tr("Model that reads images", "النموذج الذي يقرأ الصور"), vis_opts,
                                             index=vis_opts.index(cur_vis),
                                             format_func=lambda n: n + ("" if n in vis_installed else "  (" + tr("not installed", "غير مثبّت") + ")"))
            else:
                st.warning(tr("Ollama is not running, or no model is installed yet. Open the Ollama app, then "
                              "pick a model below and press Download.",
                              "Ollama غير شغّال أو لا يوجد نموذج مثبّت. افتح تطبيق Ollama ثم اختر نموذجاً من الأسفل واضغط تنزيل."))
                ollama_model = st.text_input(tr("Text model name", "اسم نموذج النص"), value=cur_model)
                ollama_vision = st.text_input(tr("Image model name", "اسم نموذج الصور"), value=cur_vis)
            tm, vm_ = st.tabs([tr("Get a text model", "نموذج للنصوص"), tr("Get an image model", "نموذج للصور")])
            with tm:
                model_guide_picker("text", installed, "mgt", ollama_url)
            with vm_:
                model_guide_picker("vision", installed, "mgv", ollama_url)
            st.markdown(f"**{tr('Limits', 'الحدود')}**")
            ollama_num_predict = st.number_input(
                tr("Longest answer allowed, in tokens (0 = no limit, recommended)", "أطول إجابة مسموحة بالرموز (0 = بلا حد، موصى به)"),
                min_value=0, max_value=1000000, step=1024, value=int(settings.get("ollama_num_predict", 0) or 0),
                help=tr("A repetition guard stops a model that is stuck in a loop, so a limit is not needed to protect you from one.",
                        "حارس التكرار يوقف النموذج العالق في حلقة، فلا حاجة لحد لحمايتك من ذلك."))
            ollama_auto_ctx = st.checkbox(
                tr("Grow the memory window automatically so a long case is never cut off (recommended)",
                   "كبّر نافذة الذاكرة تلقائياً حتى لا تُقصّ الحالة الطويلة أبداً (موصى به)"),
                value=bool(settings.get("ollama_auto_ctx", True)))
            ollama_num_ctx = st.number_input(
                tr("Starting memory window in tokens (a bigger window uses more RAM)", "نافذة الذاكرة المبدئية بالرموز (الأكبر تستهلك ذاكرة أكثر)"),
                min_value=2048, max_value=1048576, step=4096, value=int(settings.get("ollama_num_ctx", 16384)))

    with st.expander(tr("Knowledge sources", "مصادر المعرفة"), expanded=False):
        st.caption(tr("Where the Evidence tab looks things up. All free. Untick any you do not want.",
                      "الأماكن التي يبحث فيها تبويب الأدلة. كلها مجانية. ألغِ ما لا تريده."))
        ks_cols = st.columns(2)
        chosen_src = []
        for n_, (k_, meta_) in enumerate(knowledge.SOURCES.items()):
            with ks_cols[n_ % 2]:
                if st.checkbox(meta_["ar" if RTL else "en"], key=f"ks_{k_}",
                               value=k_ in settings.get("knowledge_sources", knowledge.DEFAULT_SOURCES)):
                    chosen_src.append(k_)
                st.caption(meta_["desc"]["ar" if RTL else "en"])
        per_source = st.slider(tr("Passages kept per source, per diagnosis", "عدد المقاطع من كل مصدر لكل تشخيص"), 1, 10,
                               int(settings.get("per_source", 4)))
        wiki_lang = st.selectbox(tr("Wikipedia language", "لغة ويكيبيديا"), ["en", "ar"],
                                 index=["en", "ar"].index(settings.get("wikipedia_lang", "en")),
                                 format_func=lambda x: {"en": "English", "ar": "العربية"}[x])
        if not config.PUBLIC_MODE:
            st.markdown("---")
            st.markdown(f"**{tr('My library: your own guidelines and protocols', 'مكتبتي: إرشاداتك وبروتوكولاتك الخاصة')}**")
            st.caption(tr("Drop in PDF, Word, PowerPoint, text or CSV files (a hospital protocol, a WHO/CDC/NICE/society guideline, "
                          "lecture notes). The app searches them on this computer, offline, and quotes the best passages with the file name and page. "
                          "Nothing is uploaded anywhere and there is no size limit.",
                          "ضع ملفات PDF أو Word أو PowerPoint أو نصية أو CSV (بروتوكول المستشفى، إرشادات WHO/CDC/NICE/الجمعيات العلمية، "
                          "محاضرات). يبحث التطبيق فيها على هذا الحاسوب بدون إنترنت ويقتبس أفضل المقاطع مع اسم الملف والصفحة. "
                          "لا يُرفع شيء لأي مكان ولا يوجد حد للحجم."))
            lib_key = f"lib_up_{st.session_state.get('lib_n', 0)}"
            new_lib = st.file_uploader(tr("Add files to your library", "أضف ملفات إلى مكتبتك"), key=lib_key,
                                       type=sorted(e.lstrip(".") for e in knowledge.LIBRARY_EXT), accept_multiple_files=True)
            if new_lib and st.button(tr(f"Add {len(new_lib)} file(s)", f"أضف {len(new_lib)} ملف"), key="lib_add"):
                for f_ in new_lib:
                    knowledge.add_to_library(f_.name, f_.getvalue())
                st.session_state["lib_n"] = st.session_state.get("lib_n", 0) + 1
                st.rerun()
            lib = knowledge.library_files()
            if lib:
                stats = knowledge.library_stats()
                st.caption(tr(f"{stats['files']} file(s), {stats['chunks']} searchable passages. Folder: knowledge_base/",
                              f"{stats['files']} ملف، {stats['chunks']} مقطع قابل للبحث. المجلد: knowledge_base/"))
                for p_ in lib:
                    r1, r2 = st.columns([5, 1])
                    r1.markdown(f"{bidi(p_.name)} · {p_.stat().st_size / 1024:.0f} KB")
                    if r2.button(tr("Remove", "حذف"), key=f"rmlib_{p_.name}"):
                        knowledge.remove_from_library(p_.name)
                        st.rerun()
            else:
                st.caption(tr("The library is empty.", "المكتبة فارغة."))

    with st.expander(tr("Your department and your data", "قسمك ونوع بياناتك"), expanded=False):
        st.caption(tr("This is what 'customize' means: tell the app who you are and what kind of data you work with.",
                      "هذا هو المقصود بـ'التخصيص': أخبر الأداة بقسمك ونوع بياناتك."))
        cur_dep = settings.get("department", "") or config.DEPARTMENTS[0]
        department = st.selectbox(tr("Department", "القسم"), config.DEPARTMENTS,
                                  index=config.DEPARTMENTS.index(cur_dep) if cur_dep in config.DEPARTMENTS else len(config.DEPARTMENTS) - 1)
        department_other = ""
        if department == "Other":
            department_other = st.text_input(tr("Name your department", "اكتب اسم القسم"), value=settings.get("department_other", ""))
        dt_options = list(config.DATA_TYPE_LABELS.keys())
        data_types = st.multiselect(tr("What kinds of data does your case usually include?", "ما أنواع البيانات التي تحتويها حالتك عادة؟"),
                                    dt_options, default=[d for d in settings.get("data_types", []) if d in dt_options],
                                    format_func=lambda d: config.DATA_TYPE_LABELS[d][LANG])
        st.caption(tr(config.UPLOAD_NOTE_EN, config.UPLOAD_NOTE_AR))

    with st.expander(tr("Advanced", "متقدم")):
        org_name = st.text_input(
            tr("Your department, hospital or conference name (shown above the title and on the report)",
               "اسم القسم أو المستشفى أو المؤتمر (يظهر فوق العنوان وفي التقرير)"),
            value=settings.get("org_name", ""),
            placeholder=tr("e.g. Department of Tropical Medicine", "مثال: قسم طب المناطق الحارة"),
            help=tr("Leave empty for no wordmark.", "اتركه فارغاً لإخفاء الاسم."))
        specialty = st.text_input(tr("Extra focus beyond the department (optional) - e.g. 'hepatology, liver cases'",
                                     "تركيز إضافي (اختياري)"), value=settings.get("specialty_hint", ""))
        max_dd = st.slider(tr("Maximum number of differential items", "أقصى عدد للتشخيصات"), 3, 12, settings.get("max_differentials", 8))
        custom = st.text_area(tr("Extra house rules for the AI (plain language)", "قواعد إضافية للذكاء الاصطناعي"),
                              value=settings.get("custom_instructions", ""), height=100,
                              help="E.g. 'Always consider malaria even without travel history'.")
        ncbi_key = st.text_input(tr("Optional free NCBI API key (makes PubMed about 3x faster, not required)", "مفتاح NCBI مجاني اختياري (يجعل PubMed أسرع نحو ٣ مرات)"),
                                 value=settings.get("ncbi_api_key", ""), type="password")

    b1, b2 = st.columns(2)
    if b1.button(tr("Save settings", "حفظ"), type="primary"):
        ns = dict(settings)
        ns.update(provider=provider, speed=speed, auto_evidence=auto_ev, specialty_hint=specialty,
                  max_differentials=max_dd, custom_instructions=custom, ncbi_api_key=ncbi_key,
                  department=department, department_other=department_other, data_types=data_types,
                  org_name=org_name.strip(), knowledge_sources=chosen_src, per_source=per_source,
                  wikipedia_lang=wiki_lang)
        if provider == "groq":
            ns.update(groq_api_key=groq_key, groq_model=groq_model, groq_vision_model=groq_vision)
        elif provider == "gemini":
            ns.update(gemini_api_key=gemini_key, gemini_model=gemini_model, gemini_thinking=gemini_think)
        elif provider == "openai":
            ns.update(openai_api_key=openai_key, openai_model=openai_model, openai_reasoning=openai_reason)
        else:
            ns.update(ollama_url=ollama_url, ollama_model=ollama_model, ollama_vision_model=ollama_vision,
                      ollama_num_ctx=int(ollama_num_ctx), ollama_num_predict=int(ollama_num_predict),
                      ollama_auto_ctx=bool(ollama_auto_ctx))
        save_s(ns)
        st.success(tr("Saved.", "تم الحفظ."))
        st.rerun()
    if b2.button(tr("Test connection", "اختبار الاتصال")):
        try:
            st.success(providers.test_connection(settings))
        except providers.ProviderError as e:
            st.error(str(e))