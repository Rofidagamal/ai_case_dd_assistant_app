# AI Case Differential-Diagnosis Assistant

A free, bilingual (English / العربية) teaching tool for physicians and trainees. Paste a clinical case, upload a picture, or upload a case presentation, and get a structured second opinion with sources to check.

> **Educational tool, not medical advice.** It can be wrong. It never replaces a clinician's judgement, a radiologist's report or local protocols. Never enter patient names or ID numbers.

## What it does

| Tab | What you do | What you get |
|---|---|---|
| **Case** | Type or paste a case, use the guided form, or upload Word / PDF / Excel / PowerPoint / images | Ranked differential diagnosis: for and against, "must exclude first" flags, confirmatory tests, red flags, missing information |
| **Identify** | Upload an X-ray, CT, endoscopy, ECG, pathology or skin photo (or type a term, drug or lab result) | A conversational reading: what it shows, what it suggests, possible causes, what to check next. Ask follow-up questions |
| **Management** | Upload a case deck or file, pick a working diagnosis | A structured management plan; if your deck asks "Management plan?", the answer slides are hidden so the AI plans first, then compares |
| **AI differential / Evidence** | | Per-diagnosis notes grounded in free sources, cited as [S1], [S2]... |
| **Settings** | Choose the AI engine, model, language, department | No code needed |

**Free knowledge sources:** PubMed (guidelines, systematic reviews, case reports), Europe PMC, MedlinePlus, Wikipedia, and your own protocols (PDF/Word/PowerPoint, searched offline).

**Free AI engines:** [Groq](https://console.groq.com) and [Google Gemini](https://aistudio.google.com/apikey) (free keys, rate-limited) or [Ollama](https://ollama.com) on your own computer (free, no limits, private).

## Quick start

### 1. Docker (recommended)

```bash
docker run -p 8501:8501 -e GROQ_API_KEY=your_free_key -v caseassistant:/data \
  ghcr.io/YOUR_GITHUB_NAME/ai-case-dd-assistant:latest
```
Open <http://localhost:8501>. No key yet? Start without `-e GROQ_API_KEY=...` and paste one in **Settings**.

With Docker Compose (optionally with a local Ollama):

```bash
cp .env.example .env          # add your free key(s)
docker compose up             # app only
docker compose --profile ollama up    # app + local Ollama (no limits)
docker compose exec ollama ollama pull qwen3:8b
```
Using Ollama that is already running on your computer? Set `OLLAMA_URL=http://host.docker.internal:11434` in `.env`.

### 2. Without Docker

```bash
pip install -r requirements.txt
streamlit run app.py
```
Windows: double-click `setup_windows.bat`, then `run_windows.bat`. Mac/Linux: `setup_mac_linux.sh`, then `run_mac_linux.sh`.

### 3. Free local AI (no limits)

Install [Ollama](https://ollama.com), then:
```bash
ollama pull qwen3:8b        # text, a good all-rounder
ollama pull medgemma:4b     # medical text + images (3.3 GB, research model - verify its output)
```
Pick the models in **Settings → AI engine**. `gemma3:12b` has the best Arabic but needs about 16 GB of RAM.

## Running it for other people (a shared web server)

Set `PUBLIC_MODE=1`. Then:
- nothing is saved on the server: no settings file, no activity log;
- each visitor's API key lives only in their own browser session, so everyone brings their own free Groq or Gemini key (or you set `GROQ_API_KEY` on the server and share its limits);
- the personal library and Ollama options are switched off, so visitors cannot reach your files or your network.

```bash
docker run -p 8501:8501 -e PUBLIC_MODE=1 ghcr.io/YOUR_GITHUB_NAME/ai-case-dd-assistant:latest
```
Free hosts that accept a Docker image or a Streamlit app: Hugging Face Spaces (Docker SDK; set `app_port: 8501`), Streamlit Community Cloud, Render. Free tiers sleep when idle. Put the host's terms and your own privacy notice in front of real users, and tell them never to enter patient identifiers: with Groq or Gemini the case text is sent to that company.

## Settings reference (environment variables)

| Variable | Meaning |
|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `NCBI_API_KEY` | Keys supplied by the host (never shown on the page) |
| `DEFAULT_PROVIDER` | `groq`, `gemini` or `ollama` |
| `DEFAULT_LANGUAGE` | `en` or `ar` |
| `OLLAMA_URL` | Where Ollama is running |
| `PUBLIC_MODE` | `1` for a shared server (see above) |
| `DATA_DIR` | Where settings, logs and your library are kept (`/data` in Docker) |
| `PORT` | Web port (default 8501) |

## Your own protocols

Put PDF, Word, PowerPoint, text or CSV files in the `knowledge_base/` folder (or in Docker, add them in **Settings → Knowledge sources**). They are searched offline and cited by file name and page. Not available in `PUBLIC_MODE`.

## Publish your own copy on GitHub

```bash
git init && git add . && git commit -m "First release"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_NAME/ai-case-dd-assistant.git
git push -u origin main
```
The included GitHub Action builds a multi-architecture Docker image and publishes it to GitHub Container Registry on every push to `main` and on version tags such as `v3.0.0`. After the first run, open the repository's **Packages**, open the package and set its visibility to **Public** so anyone can pull it without logging in.

## Tests

```bash
python tests/smoke_test.py     # runs offline with the AI mocked
```

## Limits and honesty

- Language models can sound confident and be wrong. Check every source.
- Small local models are weaker and may miss things in long cases; the app stops a model that loops and warns you.
- An image reading is a draft from one frame, not a radiology report.
- Dose ranges are off by default and, when switched on, must be checked against your formulary.
- Free cloud tiers have rate limits that the providers can change at any time.

## License

MIT, see [LICENSE](LICENSE). Provided as is, without warranty.

---

## بالعربية باختصار

أداة تعليمية مجانية للأطباء والطلاب: تكتب الحالة أو ترفع صورة أو عرضاً تقديمياً فتحصل على تشخيص تفريقي وخطة علاج ومصادر للتحقق. **ليست نصيحة طبية** ولا تغني عن الطبيب المعالج. لا تُدخل أسماء المرضى أو أرقام هويتهم.

التشغيل بدوكر: `docker run -p 8501:8501 -e GROQ_API_KEY=مفتاحك ghcr.io/YOUR_GITHUB_NAME/ai-case-dd-assistant:latest` ثم افتح `http://localhost:8501`. للحصول على مفتاح Groq مجاني: console.groq.com. لاستخدام الذكاء على حاسوبك بلا حدود ثبّت Ollama.

## Image reading quality

Small local vision models (for example a 4B model) can invent details. The prompt now forbids naming an organ without a visible landmark and fills the description before the summary, but the best readings come from a larger model: Groq (Llama 4 Scout) or Gemini 2.5 Flash, both free with a key. Always treat the reading as a draft.
