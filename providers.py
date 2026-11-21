"""One function to call whichever free LLM provider the doctor picked in
Settings. All three options below have a free tier / are free to run:

- Ollama:  fully local and private (nothing leaves the computer), needs the
  free Ollama app installed and a model downloaded once. Best for real patient
  data, but needs ~8-16 GB RAM for a usable model.
- Groq:    free cloud API, very fast, generous free daily limit. Needs a
  free account at console.groq.com. Nothing to install.
- Gemini:  Google AI Studio free tier. Needs a free key at
  aistudio.google.com/apikey. Nothing to install.

Only de-identified case text should ever be sent to a cloud provider
(Groq/Gemini). Ollama keeps everything on the doctor's own machine.

The full input is always sent and no answer-length limit is set for any
provider (no max_tokens, no maxOutputTokens, num_predict -1). The one
protection the LOCAL model keeps is a REPETITION GUARD instead of a length cap:
a small model fed a long case can fall into a loop ("the same sentence again
and again") and, with no limit, would keep writing for a quarter of an hour.
The reply is streamed, so the app sees the loop begin, stops it within seconds,
and salvages whatever the model had already finished (_salvage_json) - the
doctor keeps every diagnosis that was completed, with a note that the list is
partial. A long answer that is NOT looping is never interrupted.
"""
import base64
import config
import copy
import hashlib
import json
import re
import threading
import time

import requests


class ProviderError(RuntimeError):
    pass


class MissingVisionModel(ProviderError):
    """Ollama has no image-capable model installed."""


_http = requests.Session()   # re-uses connections: faster repeated calls
_cache: dict = {}            # identical question -> instant answer


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


BAD_JSON = ("The AI reply was not valid JSON. Try again, "
            "or switch to a larger model in Settings.")


def _salvage_json(text: str) -> dict:
    """Rescue a reply that was cut off in the middle (a small local model that
    kept generating until it ran out of room). Everything the model DID finish
    is still useful to the doctor, so close the open string/array/object and
    parse the prefix, dropping the half-written last item.
    Raises ProviderError when nothing usable can be recovered."""
    start = text.find("{")
    if start == -1:
        raise ProviderError(BAD_JSON)
    s = text[start:]

    # Walk the text tracking nesting, so we know what is still open at the cut.
    stack, in_str, esc, last_safe = [], False, False, None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:                      # a complete top-level object
                last_safe = i
        elif ch == "," and len(stack) <= 2:
            last_safe = i                      # end of a whole list item / field

    if last_safe is not None and not stack:    # already complete somewhere
        try:
            return json.loads(s[:last_safe + 1])
        except json.JSONDecodeError:
            pass

    # Cut back to the last finished item, then close what is still open.
    for cut in (last_safe, len(s) - 1):
        if cut is None:
            continue
        head = s[:cut].rstrip().rstrip(",")
        depth, in_str, esc = [], False, False
        for ch in head:                        # recompute what is open at the cut
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                depth.append("}" if ch == "{" else "]")
            elif ch in "}]" and depth:
                depth.pop()
        candidate = head + ('"' if in_str else "") + "".join(reversed(depth))
        try:
            out = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(out, dict) and out:
            return out
    raise ProviderError(BAD_JSON)


def _strip_to_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return _salvage_json(text)                 # cut off mid-reply: keep what finished


# ----------------------------------------------------------------- Groq
GROQ_TEXT = "openai/gpt-oss-120b"
GROQ_VISION = "qwen/qwen3.8-27b"
GROQ_FAST = "openai/gpt-oss-20b"
# models Groq has shut down -> silently use the current ones
GROQ_RETIRED = {"llama-3.3-70b-versatile": GROQ_TEXT, "llama-3.1-8b-instant": GROQ_FAST,
                "meta-llama/llama-4-scout-17b-16e-instruct": GROQ_VISION,
                "meta-llama/llama-4-maverick-17b-128e-instruct": GROQ_VISION,
                "qwen/qwen3-32b": GROQ_TEXT, "qwen/qwen3.6-27b": GROQ_VISION}
GEMINI_FAST = "gemini-2.5-flash-lite"


def _groq_model(settings, images):
    if images:
        m = settings.get("groq_vision_model") or GROQ_VISION
    elif settings.get("speed") == "fast":
        m = GROQ_FAST
    else:
        m = settings.get("groq_model") or GROQ_TEXT
    return GROQ_RETIRED.get(m, m)


def _call_groq(system, user, settings, images=None):
    key = config.api_key(settings, "groq")
    if not key:
        raise ProviderError("No Groq API key set. Go to Settings and paste a "
                            "free key from console.groq.com.")
    if images and len(images) > 5:
        raise ProviderError(f"Groq reads at most 5 images at once ({len(images)} attached). "
                            "Remove some, or switch to Gemini in Settings.")
    content = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": f"data:{m};base64,{_b64(b)}"}}
            for m, b in images]
    body = {"model": _groq_model(settings, images), "temperature": 0.2,
            # no max_tokens -> the model's own maximum applies
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}]}
    hdr = {"Authorization": f"Bearer {key}"}
    url = "https://api.groq.com/openai/v1/chat/completions"
    r = _http.post(url, headers=hdr, json=body, timeout=600)
    if r.status_code == 400 and "response_format" in r.text:
        body.pop("response_format")
        r = _http.post(url, headers=hdr, json=body, timeout=600)
    if r.status_code in (400, 404) and "model" in r.text and body["model"] not in (GROQ_TEXT, GROQ_VISION):
        body["model"] = GROQ_VISION if images else GROQ_TEXT      # chosen model gone -> current default
        r = _http.post(url, headers=hdr, json=body, timeout=600)
    if r.status_code != 200:
        hint = ""
        if r.status_code == 404:
            hint = (" -- Groq no longer offers this model to your key. In Settings use "
                    f"'{GROQ_VISION if images else GROQ_TEXT}', or see console.groq.com/docs/models.")
        raise ProviderError(f"Groq error {r.status_code}: {r.text}{hint}")
    return r.json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------- Gemini
def _call_gemini(system, user, settings, images=None):
    key = config.api_key(settings, "gemini")
    if not key:
        raise ProviderError("No Gemini API key set. Go to Settings and paste a "
                            "free key from aistudio.google.com/apikey.")
    model = settings.get("gemini_model", "gemini-2.5-flash")
    if model.startswith("gemini-1.5"):      # retired by Google -> upgrade silently
        model = "gemini-2.5-flash"
    if settings.get("speed") == "fast":
        model = GEMINI_FAST
    parts = [{"text": user}] + [{"inlineData": {"mimeType": m, "data": _b64(b)}}
                                for m, b in (images or [])]
    r = _http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        # no maxOutputTokens -> the model's own maximum applies
        json={"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"role": "user", "parts": parts}],
              "generationConfig": {"temperature": 0.2,
                                   "responseMimeType": "application/json"}},
        timeout=600)
    if r.status_code != 200:
        raise ProviderError(f"Gemini error {r.status_code}: {r.text}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise ProviderError(f"Gemini returned no text: {json.dumps(data)}")


# --------------------------------------------------------------- Ollama
def _ollama_url(settings: dict) -> str:
    return settings.get("ollama_url", "http://localhost:11434").rstrip("/")


def list_ollama_models(settings: dict) -> list:
    """Chat models installed in Ollama (embedding models excluded).
    Returns [] if Ollama is not reachable."""
    try:
        r = _http.get(f"{_ollama_url(settings)}/api/tags", timeout=10)
        if r.status_code != 200:
            return []
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except requests.exceptions.RequestException:
        return []
    return [n for n in names if n and "embed" not in n.lower()]


def list_ollama_models_detailed(settings: dict) -> list:
    """[{'name', 'gb'}] for every installed chat model (embedding models excluded)."""
    try:
        r = _http.get(f"{_ollama_url(settings)}/api/tags", timeout=10)
        if r.status_code != 200:
            return []
        return [{"name": m.get("name", ""), "gb": round(m.get("size", 0) / 1e9, 1)}
                for m in r.json().get("models", [])
                if m.get("name") and "embed" not in m.get("name", "").lower()]
    except requests.exceptions.RequestException:
        return []


def preload_ollama(settings: dict, vision: bool = False) -> None:
    """Load the model into memory in the background so the first real answer
    does not also pay the model's start-up time. Silent if Ollama is not there."""
    def go():
        try:
            m = _resolve_ollama_model(settings, vision=vision)
            _http.post(f"{_ollama_url(settings)}/api/generate",
                       json={"model": m, "keep_alive": "30m"}, timeout=300)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def pull_ollama_model(settings: dict, name: str):
    """Generator that downloads a model, yielding (status_text, fraction|None).
    Used by the Settings tab's 'Download model' button."""
    try:
        with _http.post(f"{_ollama_url(settings)}/api/pull",
                           json={"name": name, "stream": True},
                           stream=True, timeout=None) as r:
            if r.status_code != 200:
                raise ProviderError(f"Ollama error {r.status_code}: {r.text}")
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if "error" in d:
                    raise ProviderError(OLD_MSG if "architecture" in d["error"] else f"Ollama: {d['error']}")
                frac = None
                if d.get("total"):
                    frac = min(1.0, d.get("completed", 0) / d["total"])
                yield d.get("status", ""), frac
    except requests.exceptions.ConnectionError:
        raise ProviderError("Could not reach Ollama. Open the Ollama app first.")


VISION_HINTS = ("vision", "llava", "qwen2.5vl", "qwen2-vl", "qwen3-vl", "minicpm-v", "gemma3",
                "gemma4", "medgemma", "moondream", "bakllava", "granite3.2-vision",
                "mistral-small3", "llama4", "qwen3.5", "-vl")
_vision_cache: dict = {}


def is_vision_model(settings: dict, name: str) -> bool:
    """Can this installed model read images? Ollama knows (it lists a 'vision'
    capability for the model); a name hint is only the fallback for an old
    Ollama that does not report capabilities. Asking beats guessing: new
    vision models appear all the time and no fixed list of names keeps up."""
    key = (_ollama_url(settings), name)
    if key in _vision_cache:
        return _vision_cache[key]
    ans = None
    try:
        r = _http.post(f"{_ollama_url(settings)}/api/show", json={"model": name, "name": name}, timeout=10)
        if r.status_code == 200 and "capabilities" in r.json():
            ans = "vision" in r.json()["capabilities"]
    except requests.exceptions.RequestException:
        pass
    if ans is None:
        ans = any(h in name.lower() for h in VISION_HINTS)
    _vision_cache[key] = ans
    return ans


OLD_MSG = ("Your Ollama app is too old for this model ('unknown model architecture'). "
           "Fix: download the latest Ollama from ollama.com/download, install it over the old one, "
           "restart it, then try again. Or pick a model that works on older versions "
           "(Settings -> Download model -> moondream).")


def ollama_version(settings) -> str:
    try:
        return _http.get(f"{_ollama_url(settings)}/api/version", timeout=5).json().get("version", "")
    except Exception:
        return ""


def ollama_is_old(settings, minimum=(0, 7, 0)) -> bool:
    v = ollama_version(settings)
    try:
        return tuple(int(x) for x in v.split("-")[0].split(".")[:3]) < minimum
    except Exception:
        return False


def _resolve_ollama_model(settings, vision=False):
    """Use the chosen model if installed; otherwise fall back to a similar or
    any installed model so a wrong name never blocks the doctor."""
    key = "ollama_vision_model" if vision else "ollama_model"
    wanted = (settings.get(key) or ("llama3.2-vision" if vision else "llama3.1")).strip()
    installed = list_ollama_models(settings)
    if vision:
        pool = [n for n in installed if is_vision_model(settings, n)]
        if not pool:
            if not installed:
                return wanted
            raise MissingVisionModel(
                "Reading images needs a vision model in Ollama and none is installed. "
                f"Open Settings and press 'Download model' for '{wanted}', or run: "
                f"ollama pull {wanted}")
        installed = pool
    if not installed:
        return wanted  # the real call will give the precise error
    if wanted in installed:
        return wanted
    if f"{wanted}:latest" in installed:
        return f"{wanted}:latest"
    base = wanted.split(":")[0]
    for n in installed:
        if n.split(":")[0] == base:
            return n
    return installed[0]


LOOPED_MSG = (
    "The local model '{model}' got stuck repeating itself, so the answer was stopped{saved}. "
    "Small models do this on a long case (a Word file or a PowerPoint deck is many times "
    "longer than a typed paragraph). Fix, best first: (1) use a bigger text model - Settings "
    "-> Download model, e.g. 'qwen3:8b' or 'llama3.1:8b' - and pick it; (2) or use a free cloud "
    "key (Settings -> Groq or Gemini), which reads long cases easily; (3) or shorten the "
    "case - paste the key slides instead of the whole file.")


def _is_looping(text: str) -> bool:
    """True when the reply ends in the same block of text repeated 4 times."""
    t = text[-3000:]
    if len(t) < 240:
        return False
    for p in range(30, len(t) // 4 + 1):
        blk = t[-p:]
        if t[-2 * p:-p] == blk and t[-3 * p:-2 * p] == blk and t[-4 * p:-3 * p] == blk:
            return True
    return False


def _strip_think(text: str) -> str:
    """Reasoning models (qwen3, deepseek-r1) put their working in <think> tags."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return re.sub(r"^.*?</think>", "", text, flags=re.S) if "</think>" in text else text


def _ollama_ctx(settings, system, user, n_images) -> int:
    """The context window actually requested. Ollama silently cuts the START of a
    prompt that does not fit - the case itself would be lost without any error -
    so the window grows to fit this input plus room for a full answer."""
    configured = int(settings.get("ollama_num_ctx", 16384))
    if not settings.get("ollama_auto_ctx", True):
        return configured
    est = int((len(system) + len(user)) / 2.6) + 1500 * n_images + 4096
    return min(131072, max(configured, -(-est // 1024) * 1024))


def _call_ollama(system, user, settings, images=None, on_progress=None):
    url = _ollama_url(settings)
    model = _resolve_ollama_model(settings, vision=bool(images))
    num_ctx = _ollama_ctx(settings, system, user, len(images or []))
    limit = int(settings.get("ollama_num_predict", 0) or 0)   # 0 = no limit
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = [_b64(b) for _, b in images]
    body = {"model": model, "stream": True, "format": "json",
            "keep_alive": "30m",   # keep the model in memory: next answers start instantly
            "options": {"temperature": 0.2, "num_predict": limit if limit > 0 else -1,
                        "num_ctx": num_ctx,
                        # discourage the repetition loop small models fall into
                        "repeat_penalty": 1.15, "repeat_last_n": 256},
            "messages": [{"role": "system", "content": system}, msg]}
    if "qwen3" in model.lower():
        body["think"] = False        # answer directly: thinking only adds minutes
    try:
        r = _http.post(f"{url}/api/chat", json=body, stream=True, timeout=(15, None))
    except requests.exceptions.ConnectionError:
        raise ProviderError("Could not reach Ollama. Make sure the Ollama app "
                            "is running on this computer (see Settings).")
    if r.status_code != 200:
        text = r.text
        if r.status_code == 404 and "not found" in text.lower():
            raise ProviderError(
                f"The model '{model}' is not installed in Ollama. Fix: open Settings "
                f"and press 'Download model', or run this once in a terminal: "
                f"ollama pull {model}")
        if "unknown model architecture" in text:
            raise ProviderError(OLD_MSG)
        raise ProviderError(f"Ollama error {r.status_code}: {text}")

    pieces, n, t0, looped, done_reason, eval_count = [], 0, time.time(), False, None, None
    try:
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if "error" in d:
                raise ProviderError(OLD_MSG if "architecture" in d["error"]
                                    else f"Ollama error: {d['error']}")
            piece = (d.get("message") or {}).get("content", "")
            if piece:
                pieces.append(piece)
                n += 1
                if on_progress and n % 6 == 0:
                    on_progress(n, time.time() - t0)
                if n % 48 == 0 and _is_looping("".join(pieces[-1500:])):
                    looped = True
                    break
            if d.get("done"):
                done_reason, eval_count = d.get("done_reason"), d.get("eval_count")
                break
    except requests.exceptions.RequestException as e:
        raise ProviderError(f"Ollama stopped responding in the middle of the answer: {e}")
    finally:
        r.close()
    if on_progress:
        on_progress(n, time.time() - t0)
    content = _strip_think("".join(pieces))

    if looped or done_reason == "length":
        # keep whatever the model completed; if nothing is usable, say exactly why
        try:
            out = _salvage_json(content)
        except ProviderError:
            raise ProviderError(LOOPED_MSG.format(model=model, saved=""))
        if out:
            out["_truncated"] = len(out.get("differential", []) or []) or 1
            return json.dumps(out, ensure_ascii=False)
        raise ProviderError(LOOPED_MSG.format(model=model, saved=""))
    return content


_CALLERS = {"groq": _call_groq, "gemini": _call_gemini, "ollama": _call_ollama}


def ask_json(system: str, user: str, settings: dict, images=None, use_cache=True,
             on_progress=None) -> dict:
    """Call the configured provider and parse its reply as JSON.
    images:      optional list of (mime, bytes) for a vision model.
    on_progress: optional fn(tokens_so_far, seconds) - the local model streams, so
                 the app can show that it is working and how fast."""
    provider = settings.get("provider", "groq")
    fn = _CALLERS.get(provider)
    if fn is None:
        raise ProviderError(f"Unknown provider '{provider}'.")
    h = hashlib.sha256()
    for part in (provider, json.dumps({k: settings.get(k) for k in (
            "groq_model", "groq_vision_model", "gemini_model", "ollama_model",
            "ollama_vision_model", "speed", "ollama_num_predict")}), system, user):
        h.update(str(part).encode())
    for _, b in images or []:
        h.update(b)
    ck = h.hexdigest()
    use_cache = use_cache and not config.PUBLIC_MODE      # shared server: keep nobody's case in memory
    if use_cache and ck in _cache:
        return copy.deepcopy(_cache[ck])
    try:
        if provider == "ollama":
            text = fn(system, user, settings, images or None, on_progress)
        else:
            text = fn(system, user, settings, images or None)
    except requests.exceptions.RequestException as e:
        raise ProviderError(f"Network problem: {e}")
    out = _strip_to_json(text)
    if use_cache and not out.get("_truncated"):
        _cache[ck] = copy.deepcopy(out)
    return out


def test_connection(settings: dict) -> str:
    """Used by the Settings tab's 'Test connection' button."""
    out = ask_json("Respond with ONLY this JSON: {\"ok\": true}", "ping", settings, use_cache=False)
    if out.get("ok"):
        return "Connected successfully."
    raise ProviderError("Unexpected reply from the provider.")
