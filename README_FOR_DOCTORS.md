# AI Case Differential-Diagnosis Assistant — for doctors, no coding needed

## What this app does
You paste a case (history, exam, labs, imaging). The app asks an AI model
for a ranked differential diagnosis — like the "ChatGPT DD" slides you have
seen in case discussions: each diagnosis with the findings that support it,
the findings against it, whether it must be excluded first, and a
confirmatory test. You can then:
- search PubMed for real articles about each diagnosis in this case,
- ask the AI to write a note using ONLY what those articles actually say,
- compare the AI's list against your own differential.

**This is a teaching / second-opinion tool. It never replaces your clinical
judgment, your supervisor, or local guidelines.**

## Files are optional - typing alone always works
You can paste a case as text, and you can ALSO attach files in tab 1:
- **Excel / CSV** (labs, vitals, trends) - every sheet is read.
- **PDF / Word / text** reports - the text is read (a scanned PDF has no text:
  save its pages as pictures and attach those).
- **PowerPoint (.pptx)** case presentations - read slide by slide: the bullets,
  the tables, the numbers behind a chart and the speaker notes. The X-ray /
  endoscopy / ECG pictures sitting on the slides are pulled out and read by the
  vision model too (logos and tiny icons are ignored; up to 16 pictures per
  deck). An old `.ppt` file cannot be read: open it in PowerPoint and use
  File -> Save As -> `.pptx` first.
- **Images** - X-ray, CT, endoscopy, ECG, wound or skin photos (PNG/JPG/WEBP).
  They are read by a "vision" model: Groq and Gemini do it for free; with
  Ollama you need a vision model (Settings -> Download model -> `llama3.2-vision`).
  The AI's image reading is a draft - always check it yourself. Images are
  shrunk automatically so answers come back faster.
No files at all? Just type the case - nothing else is needed.

## Before you start: protect patient privacy
Never type the patient's name, national ID, exact admission date, or
anything else that identifies them - and crop names/IDs out of images and
spreadsheets before attaching them. Use "a 37-year-old man" the way the
sample case does. If your provider is a cloud service (Groq or Gemini
below), the case text leaves your computer; keep it de-identified.

## Step 1 — Install Python (one time only)
If you don't already have Python:
- Windows: go to python.org/downloads, download, run the installer, and
  **tick "Add python.exe to PATH"** before clicking Install.
- Mac: Python is usually already installed. If not, go to python.org/downloads.

## Step 2 — Prepare the app (one time only)
- **Windows:** double-click `setup_windows.bat`. A black window opens,
  installs a few things, and closes. This can take a few minutes.
- **Mac/Linux:** open Terminal in this folder and run `bash setup_mac_linux.sh`.

## Step 3 — Get a free AI key (one time only, 2 minutes)
Pick ONE of these. You do not need a credit card.
1. **Groq (recommended, fast, free):** go to console.groq.com, sign up,
   open "API Keys", create a key, and copy it.
2. **Google Gemini (free tier):** go to aistudio.google.com/apikey, sign in
   with a Google account, create a key, and copy it.
3. **Ollama (fully local — nothing ever leaves your computer, no account
   needed, but needs a reasonably strong computer):** install the free app
   from ollama.com, open a terminal and run `ollama pull llama3.1`, then
   leave the Ollama app running in the background.

## Step 4 — Run the app
- **Windows:** double-click `run_windows.bat`.
- **Mac/Linux:** run `./run_mac_linux.sh`.
A browser tab opens with the app. Keep the black/terminal window open while
you use it; closing it stops the app.

## Step 5 — First-time setup inside the app
1. Open the **⚙️ Settings** tab.
2. Choose your provider (Groq / Gemini / Ollama) and paste the free key
   from Step 3, or the Ollama address if you chose that.
3. Choose your **department** (e.g. Tropical Medicine, Pediatrics, Cardiology
   — pick "Other" to type your own) and tick the **kinds of text** your
   cases usually include (history & exam, labs, imaging findings described
   in words, pathology text, discharge summaries). This is the main way you
   customize the app — see below.
4. Choose the AI's reply language (Arabic or English).
5. Press **Save settings**, then **Test connection** to confirm it works.

## Using the app
1. **Tab 1 — New case:** paste the case, or tick the sample case to try the
   app immediately. Press "Generate AI differential".
2. **Tab 2 — AI differential:** read the ranked list. Diagnoses marked
   "MUST EXCLUDE" are dangerous-but-treatable conditions the AI flags even
   if less likely. Press "Find PubMed evidence" on any diagnosis.
3. **Tab 3 — Evidence:** real PubMed articles for that diagnosis, with
   links. Press "Write a grounded note" to get a short summary that only
   uses what those specific articles say — if they don't really support the
   diagnosis, the app says so instead of guessing.
4. **Tab 4 — Compare with mine:** type your own differential and see where
   you and the AI agree or disagree, and whether either of you may have
   missed a dangerous diagnosis.

## How to customize it (all inside the Settings tab — no file to edit)
"Customize" mainly means two dropdowns in Settings:
- **Department:** pick from a list (Internal Medicine, Tropical/Infectious
  Disease, Pediatrics, Cardiology, Surgery, Emergency Medicine, and more —
  or "Other" to type your own, e.g. "Hepatobiliary Surgery"). The AI then
  leans toward diagnoses common in that department, without ever dropping a
  dangerous diagnosis from outside it.
- **Type of data:** tick which kinds of text your cases usually contain —
  history & exam, labs, imaging findings in words, pathology text,
  discharge summaries. A pediatrics team working from labs and exam notes
  only would tick just those two; a tropical-medicine ward with lots of
  imaging-in-words cases would tick that too. No image files involved either
  way.

Also in Settings:
- **Extra focus:** a short free-text add-on beyond the department, e.g.
  "hepatology, liver cases."
- **House rules:** type plain-language rules, e.g. "Always consider malaria
  even without travel history" or "Use WHO terminology." The AI follows
  these on every case.
- **Number of differentials:** 3 to 12 items.
- **Language:** Arabic or English output at any time.

Switching department or data type takes seconds and needs no restart — a
general-medicine ward and a pediatrics ward can each keep their own
`user_settings.json` by copying the whole app folder once per department.

## Speed
- Settings -> Speed -> **Fast** uses a smaller cloud model (answers in a few seconds).
- PubMed is searched for all diagnoses at the same time, automatically.
- With Ollama the model stays loaded in memory, so the second case is much faster.
- Repeating the same question is instant (answers are remembered while the app is open).

## If something goes wrong
- "No API key set" → open Settings, pick a provider, paste the key, Save.
- "Could not reach Ollama" → open the Ollama app first, then retry.
- "model 'llama3.1' not found" (Ollama) → the model was never downloaded.
  Open Settings, type `llama3.1` under "Download a new model" and press
  **Download model** (or run `ollama pull llama3.1` once in a terminal). The
  app now also picks any model you already have installed automatically.
- Your whole case is always sent, however long. The local model's ANSWER is
  capped (4096 tokens, Settings file `ollama_num_predict`) because a small
  model sometimes starts repeating itself and would otherwise write for a
  quarter of an hour and produce nothing usable.
- **A Word or PowerPoint case gives no differential (or "the reply was not
  valid JSON")** → a file case is 5-15x longer than a typed paragraph, and a
  small local model (3-billion-parameter ones like `qwen2.5vl:3b`,
  `moondream`) cannot hold the whole answer format together over that much
  text: it starts repeating a phrase until it runs out of room. Fix, best
  first: (1) install a proper text model - `ollama pull qwen2.5:7b` in a
  terminal, then choose it in Settings as the text model, and keep the small
  vision model only for images; (2) or paste a free Groq key in Settings, which
  reads a long case easily; (3) or paste only the key slides instead of the
  whole file. If some diagnoses were recovered, the app shows them with a
  "list is incomplete" warning rather than throwing them away.
- The AI reply looks cut off or wrong → press the button again; language
  models occasionally make a formatting mistake.
- PubMed tab shows no results → the search term may be too narrow; this is
  normal for rare conditions.

## Where things are saved
- `user_settings.json` in this folder stores your provider, key and
  preferences on this computer only. Do not share this file if it has a key
  in it.
- `logs/events.jsonl` records that you generated a differential or a
  comparison (no patient data), useful if you want to track how often the
  tool is used in training sessions.

## A note on "accurate resources"
The AI's first answer comes from its general training, like any language
model — it can be wrong. The PubMed step (tab 3) is what grounds the
answer in real, citable articles: the app actually searches PubMed and only
asks the AI to summarize what it finds, flagging when the evidence found is
not actually relevant. Always still check the original article before
relying on a claim.


## New: Images tab and more sources
Open the **Images** tab, upload a picture, choose its type (or "detect it"), optionally add context or a question, and press Read. The result says what the image is, what it shows, and what to consider. It is a reading aid, never a diagnosis - confirm with a radiologist or specialist. Add your hospital protocols as PDF/Word files in Settings > Knowledge sources so answers cite your own guidelines. Never include patient names or IDs in text or images.
