"""Grounding in real literature using NCBI PubMed - completely free, no
account needed (an optional free NCBI API key just raises the rate limit).
This is what lets the app answer from 'accurate resources' instead of only
the model's memory: for each candidate diagnosis we actually search PubMed
and only let the model cite what came back.

Speed: one search call + ONE fetch call per diagnosis (title, journal, year
and the full abstract all come back together), and all diagnoses are searched
in parallel through a shared rate limiter that respects NCBI's limits.
"""
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

import config

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_http = requests.Session()
_lock = threading.Lock()
_last = [0.0]
_cache: dict = {}


def _throttle(settings):
    """NCBI allows ~3 requests/s without a key, ~10/s with one."""
    gap = 0.11 if config.api_key(settings, "ncbi") else 0.36
    with _lock:
        wait = _last[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _get(endpoint, settings, **params):
    key = config.api_key(settings, "ncbi")
    if key:
        params["api_key"] = key
    for attempt in range(3):
        _throttle(settings)
        r = _http.get(f"{BASE}/{endpoint}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(1.0 + attempt)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def search_ids(query: str, settings: dict | None, max_results: int) -> list[str]:
    r = _get("esearch.fcgi", settings, db="pubmed", term=query,
             retmax=max_results, sort="relevance", retmode="json")
    return r.json().get("esearchresult", {}).get("idlist", [])


def fetch_articles(ids: list[str], settings: dict | None) -> list[dict]:
    """One call -> [{pmid,title,journal,year,url,abstract}, ...]"""
    if not ids:
        return []
    r = _get("efetch.fcgi", settings, db="pubmed", id=",".join(ids),
             retmode="xml", rettype="abstract")
    root = ET.fromstring(r.content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()).strip(". ") \
            if art.find(".//ArticleTitle") is not None else ""
        journal = art.findtext(".//Journal/Title") or ""
        year = (art.findtext(".//JournalIssue/PubDate/Year")
                or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4])
        paras = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            txt = "".join(ab.itertext()).strip()
            paras.append(f"{label}: {txt}" if label else txt)
        out.append({"pmid": pmid, "title": title, "journal": journal, "year": year,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "abstract": "\n".join(paras)})
    order = {p: i for i, p in enumerate(ids)}
    out.sort(key=lambda a: order.get(a["pmid"], 99))
    return out


def evidence_for_diagnosis(diagnosis: str, case_keywords: str = "",
                           settings: dict | None = None, max_results: int = 4) -> list[dict]:
    """Search PubMed for a diagnosis in the context of the case's key features;
    falls back to the diagnosis alone if the combined query is too narrow."""
    ck = (diagnosis, case_keywords, max_results)
    if ck in _cache:
        return _cache[ck]
    query = f"({diagnosis}) AND ({case_keywords})" if case_keywords else diagnosis
    ids = search_ids(query, settings, max_results)
    if not ids and case_keywords:
        ids = search_ids(diagnosis, settings, max_results)
    hits = fetch_articles(ids, settings)
    _cache[ck] = hits
    return hits


def evidence_for_many(items: list[tuple], settings: dict | None = None,
                      max_results: int = 4, workers: int = 4) -> dict:
    """items: [(diagnosis, search_terms), ...] -> {diagnosis: hits}.
    A failure for one diagnosis never blocks the others."""
    def one(it):
        dx, terms = it
        try:
            return dx, evidence_for_diagnosis(dx, terms, settings, max_results)
        except Exception:
            return dx, None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return {dx: hits for dx, hits in ex.map(one, items) if hits is not None}
