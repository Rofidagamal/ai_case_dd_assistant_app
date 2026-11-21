"""The knowledge base: every place the app can look something up, behind one
call. All sources are free and need no account:

  pubmed        PubMed, everything (NCBI E-utilities)
  guidelines    PubMed, practice guidelines only
  reviews       PubMed, systematic reviews and meta-analyses only
  casereports   PubMed, published case reports (the closest match to a case
                presentation: "has anyone described a patient like this?")
  europepmc     Europe PMC: PubMed + preprints + open-access papers
  medlineplus   MedlinePlus (US National Library of Medicine): reviewed
                plain-language summaries of diseases
  wikipedia     Wikipedia intro: background only, graded lowest on purpose
  local         YOUR OWN LIBRARY: PDF / Word / PowerPoint / text files you put
                in the knowledge_base folder (hospital protocols, WHO / CDC /
                NICE / society guidelines, lecture notes). Searched offline
                with BM25 ranking, so it is free, private and has no limit.

Every record has the same shape, so the Evidence tab and the grounded-note
prompt do not care where a passage came from:
  {source, ref, title, journal, year, url, abstract}
`abstract` holds the full passage text; nothing is cut short.
"""
import html
import math
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

import config

import pubmed

ROOT = Path(__file__).parent
LIBRARY_DIR = config.DATA_DIR / "knowledge_base"
LIBRARY_EXT = {".pdf", ".docx", ".txt", ".md", ".pptx", ".csv"}

_http = requests.Session()
_http.headers["User-Agent"] = "CaseDDAssistant/2.0 (educational clinical decision-support tool)"

# order = how specific a record's label is, and how it is ranked on screen
SOURCES = {
    "local":       {"en": "My library",              "ar": "مكتبتي",                 "grade": 0,
                    "desc": {"en": "Your own PDF / Word / PowerPoint files (offline, private)",
                             "ar": "ملفاتك الخاصة PDF / Word / PowerPoint (بدون إنترنت وخاصة)"}},
    "guidelines":  {"en": "Guidelines",              "ar": "الإرشادات الطبية",        "grade": 1,
                    "desc": {"en": "PubMed practice guidelines", "ar": "إرشادات الممارسة الإكلينيكية من PubMed"}},
    "reviews":     {"en": "Reviews & meta-analyses", "ar": "مراجعات وتحليلات تجميعية", "grade": 2,
                    "desc": {"en": "PubMed systematic reviews and meta-analyses",
                             "ar": "المراجعات المنهجية والتحليلات التجميعية من PubMed"}},
    "pubmed":      {"en": "PubMed",                  "ar": "PubMed",                 "grade": 3,
                    "desc": {"en": "PubMed, all article types", "ar": "PubMed بكل أنواع المقالات"}},
    "europepmc":   {"en": "Europe PMC",              "ar": "Europe PMC",             "grade": 3,
                    "desc": {"en": "PubMed + preprints + open-access papers",
                             "ar": "PubMed مع النسخ الأولية والأبحاث المفتوحة"}},
    "casereports": {"en": "Case reports",            "ar": "تقارير حالات",            "grade": 4,
                    "desc": {"en": "Published case reports - 'has a patient like this been described?'",
                             "ar": "تقارير حالات منشورة - هل وُصف مريض مثل هذا؟"}},
    "medlineplus": {"en": "MedlinePlus",             "ar": "MedlinePlus",            "grade": 5,
                    "desc": {"en": "Reviewed plain-language disease summaries (US NLM)",
                             "ar": "ملخصات مراجَعة مبسّطة للأمراض (المكتبة الطبية الأمريكية)"}},
    "wikipedia":   {"en": "Wikipedia",               "ar": "ويكيبيديا",               "grade": 6,
                    "desc": {"en": "Background only - lowest evidence grade",
                             "ar": "معلومات خلفية فقط - أدنى درجة موثوقية"}},
}
DEFAULT_SOURCES = ["local", "guidelines", "reviews", "pubmed", "europepmc", "casereports",
                   "medlineplus", "wikipedia"]
if config.PUBLIC_MODE:                      # one shared folder would be visible to every visitor
    SOURCES.pop("local", None)
    DEFAULT_SOURCES = [s for s in DEFAULT_SOURCES if s != "local"]
PUBMED_KINDS = ["guidelines", "reviews", "casereports", "pubmed"]   # most specific first
PUBMED_FILTERS = {
    "guidelines": " AND (guideline[pt] OR practice guideline[pt])",
    "reviews": " AND (systematic review[pt] OR meta-analysis[pt])",
    "casereports": " AND case reports[pt]",
    "pubmed": "",
}


# ------------------------------------------------------------------- helpers
def strip_tags(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def latin_term(text: str) -> str:
    """The English part of a diagnosis. The model is told to keep English names
    in parentheses after the Arabic term, and every outside source is English,
    so 'حمى الضنك (Dengue fever)' is searched as 'Dengue fever'."""
    m = re.findall(r"\(([^()]*[A-Za-z][^()]*)\)", text or "")
    if m:
        return m[0].strip()
    if re.search(r"[A-Za-z]", text or ""):
        return " ".join(re.findall(r"[A-Za-z][A-Za-z0-9\-'/ ]*", text)).strip()
    return (text or "").strip()


def _rec(source, ref, title, journal, year, url, text):
    return {"source": source, "ref": ref, "title": title, "journal": journal,
            "year": str(year or ""), "url": url, "abstract": text or ""}


# --------------------------------------------------------------- PubMed group
def _pubmed_group(dx, terms, kinds, per, settings):
    """All PubMed-based sources with ONE fetch call for every article found."""
    base = f"({dx}) AND ({terms})" if terms else dx
    ids_by_kind = {}
    for kind in [k for k in PUBMED_KINDS if k in kinds]:
        flt = PUBMED_FILTERS[kind]
        ids = pubmed.search_ids(f"({base}){flt}", settings, per)
        if not ids and terms:
            ids = pubmed.search_ids(f"({dx}){flt}", settings, per)
        ids_by_kind[kind] = ids
    union = list(dict.fromkeys(i for ids in ids_by_kind.values() for i in ids))
    arts = {a["pmid"]: a for a in pubmed.fetch_articles(union, settings)}
    out, seen = [], set()
    for kind, ids in ids_by_kind.items():
        for pid in ids:
            a = arts.get(pid)
            if a and pid not in seen:
                seen.add(pid)
                out.append(_rec(kind, f"PMID {pid}", a["title"], a["journal"], a["year"],
                                a["url"], a["abstract"]))
    return out


# ----------------------------------------------------------------- Europe PMC
def _europepmc(dx, terms, per, settings):
    q = f"({dx}) AND ({terms})" if terms else dx
    r = _http.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                  params={"query": q, "resultType": "core", "pageSize": per * 2,
                          "format": "json", "sort": "RELEVANCE"}, timeout=30)
    r.raise_for_status()
    out = []
    for x in r.json().get("resultList", {}).get("result", []):
        text = strip_tags(x.get("abstractText", ""))
        if not text:
            continue
        src, rid = x.get("source", "MED"), x.get("id", "")
        pmid = x.get("pmid")
        title = strip_tags(x.get("title", "")).rstrip(".")
        if src == "PPR":
            title = "[Preprint, not peer-reviewed] " + title
        ref = f"PMID {pmid}" if pmid else f"EuropePMC {src}:{rid}"
        journal = x.get("journalTitle") or (x.get("journalInfo") or {}).get("journal", {}).get("title", "") \
            or ("Preprint" if src == "PPR" else "")
        out.append(_rec("europepmc", ref, title, journal, x.get("pubYear", ""),
                        f"https://europepmc.org/article/{src}/{rid}", text))
        if len(out) >= per:
            break
    return out


# ----------------------------------------------------------------- MedlinePlus
def _medlineplus(dx, per, settings):
    r = _http.get("https://wsearch.nlm.nih.gov/ws/query",
                  params={"db": "healthTopics", "term": latin_term(dx), "retmax": per,
                          "rettype": "brief"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for doc in root.iter("document"):
        c = {x.get("name"): "".join(x.itertext()) for x in doc.findall("content")}
        title, text = strip_tags(c.get("title", "")), strip_tags(c.get("FullSummary") or c.get("snippet", ""))
        if title and text:
            out.append(_rec("medlineplus", "MedlinePlus", title, "MedlinePlus (US NLM)", "",
                            doc.get("url", ""), text))
    return out[:per]


# ------------------------------------------------------------------ Wikipedia
def _wikipedia(dx, per, settings):
    lang = settings.get("wikipedia_lang", "en")
    q = latin_term(dx) if lang == "en" else dx
    r = _http.get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": q,
        "gsrlimit": per, "prop": "extracts|info", "exintro": 1, "explaintext": 1,
        "inprop": "url", "redirects": 1}, timeout=30)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {})
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        if p.get("extract"):
            out.append(_rec("wikipedia", f"Wikipedia ({lang})", p.get("title", ""), "Wikipedia", "",
                            p.get("fullurl", ""), p["extract"].strip()))
    return out


# ---------------------------------------------------------- local library: BM25
_lib_lock = threading.Lock()
_index = {"sig": None, "chunks": [], "df": Counter(), "avgdl": 1.0}


def library_files() -> list[Path]:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in LIBRARY_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() in LIBRARY_EXT)


def add_to_library(name: str, data: bytes) -> Path:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    p = LIBRARY_DIR / Path(name).name
    p.write_bytes(data)
    return p


def remove_from_library(name: str) -> None:
    p = LIBRARY_DIR / Path(name).name
    if p.exists():
        p.unlink()


def _tok(s: str) -> list[str]:
    return re.findall(r"\w+", (s or "").lower())


def _pages(path: Path) -> list[tuple[str, str]]:
    """[(page label, text)] for one library file."""
    ext = path.suffix.lower()
    data = path.read_bytes()
    if ext == ".pdf":
        from pypdf import PdfReader
        import io
        rd = PdfReader(io.BytesIO(data))
        return [(f"p.{i}", (pg.extract_text() or "")) for i, pg in enumerate(rd.pages, 1)]
    import files
    if ext == ".pptx":
        return [("", files.read_slides(path.name, data)["text"])]
    return [("", files.read_doc(path.name, data))]


def _chunks_of(text: str, size=1100, overlap=150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}".strip()
        else:
            if cur:
                out.append(cur)
            while len(p) > size:                         # one huge paragraph
                out.append(p[:size])
                p = p[size - overlap:]
            cur = p
    if cur:
        out.append(cur)
    return out


def _build_index():
    files_ = library_files()
    sig = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files_)
    with _lib_lock:
        if _index["sig"] == sig:
            return
        chunks, df = [], Counter()
        for p in files_:
            try:
                for label, text in _pages(p):
                    for ch in _chunks_of(text):
                        toks = _tok(ch)
                        if len(toks) < 8:
                            continue
                        chunks.append({"file": p.name, "page": label, "text": ch,
                                       "tf": Counter(toks), "len": len(toks)})
                        df.update(set(toks))
            except Exception:
                continue                                  # one unreadable file never blocks the rest
        _index.update(sig=sig, chunks=chunks, df=df,
                      avgdl=(sum(c["len"] for c in chunks) / len(chunks)) if chunks else 1.0)


def library_stats() -> dict:
    _build_index()
    return {"files": len(library_files()), "chunks": len(_index["chunks"])}


def _local(query: str, per: int, settings) -> list[dict]:
    _build_index()
    chunks, df, avgdl = _index["chunks"], _index["df"], _index["avgdl"]
    if not chunks:
        return []
    n, k1, b = len(chunks), 1.5, 0.75
    q = [t for t in set(_tok(query)) if len(t) > 2]
    scored = []
    for c in chunks:
        s = 0.0
        for t in q:
            f = c["tf"].get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * c["len"] / avgdl))
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    out, used = [], Counter()
    for s, c in scored:
        if used[c["file"]] >= 2:                          # spread across documents
            continue
        used[c["file"]] += 1
        label = f"{c['file']} {c['page']}".strip()
        out.append(_rec("local", f"LOCAL {label}", label, c["file"], "", "", c["text"]))
        if len(out) >= per:
            break
    return out


# ---------------------------------------------------------------------- public
def gather(dx: str, terms: str, settings: dict, selected=None, per: int | None = None):
    """-> (records, {source: error message}). A source that fails never blocks
    the others: the doctor still gets everything that did answer."""
    selected = [s for s in (selected or settings.get("knowledge_sources") or DEFAULT_SOURCES)
                if s in SOURCES]
    per = per or int(settings.get("per_source", 4))
    en_dx, en_terms = latin_term(dx), (terms or "").strip()
    jobs = {}
    pm_kinds = [k for k in PUBMED_KINDS if k in selected]
    if pm_kinds:
        jobs["pubmed"] = lambda: _pubmed_group(en_dx, en_terms, pm_kinds, per, settings)
    if "europepmc" in selected:
        jobs["europepmc"] = lambda: _europepmc(en_dx, en_terms, per, settings)
    if "medlineplus" in selected:
        jobs["medlineplus"] = lambda: _medlineplus(dx, per, settings)
    if "wikipedia" in selected:
        jobs["wikipedia"] = lambda: _wikipedia(dx, per, settings)
    if "local" in selected:
        jobs["local"] = lambda: _local(f"{dx} {terms} {en_dx}", per, settings)
    errors, recs = {}, []

    def run(item):
        name, fn = item
        try:
            return name, fn(), None
        except Exception as e:
            return name, [], str(e)[:200]
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
        for name, got, err in ex.map(run, jobs.items()):
            recs += got
            if err:
                errors[name] = err
    # drop a Europe PMC copy of something PubMed already returned
    seen, uniq = set(), []
    for r in sorted(recs, key=lambda r: SOURCES[r["source"]]["grade"]):
        key = r["ref"] if r["ref"].startswith("PMID") else (r["source"], r["title"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq, errors


def gather_many(items: list[tuple], settings: dict, selected=None, workers: int = 3):
    """items: [(diagnosis, search_terms)] -> ({diagnosis: [records]}, {source: error})."""
    errors_all, result = {}, {}

    def one(it):
        dx, terms = it
        try:
            return dx, *gather(dx, terms, settings, selected)
        except Exception as e:
            return dx, [], {"all": str(e)[:200]}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for dx, recs, errs in ex.map(one, items):
            result[dx] = recs
            errors_all.update(errs)
    return result, errors_all


def format_for_llm(records: list[dict]) -> str:
    """Numbered passages the model must cite as (S1), (S2)... Nothing is cut."""
    parts = []
    for i, r in enumerate(records, 1):
        label = SOURCES[r["source"]]["en"]
        head = f"[S{i}] ({label} · {r['ref']}) {r['title']}"
        if r.get("year"):
            head += f" - {r['year']}"
        parts.append(f"{head}\n{r['abstract']}")
    return "\n\n".join(parts)
