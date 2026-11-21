"""All app settings live in one small JSON file that the Settings tab in the
app writes to - a doctor never has to open or edit this file by hand."""
import json
import os
from pathlib import Path

VERSION = "3.0.0"
ROOT = Path(__file__).parent
# Where settings, logs and your own library are kept. Default: next to the app.
# In Docker this is /data, so one volume keeps everything between restarts.
DATA_DIR = Path(os.environ.get("DATA_DIR") or ROOT)
SETTINGS_FILE = DATA_DIR / "user_settings.json"
SAMPLE_CASE = ROOT / "sample_case.txt"
LOG_DIR = DATA_DIR / "logs"
EVENTS_LOG = LOG_DIR / "events.jsonl"

# PUBLIC_MODE=1 is for a shared web server that strangers use: nothing is written to
# disk, each visitor's settings and API key live only in their own browser session,
# the personal library is switched off, and the app talks only to Groq or Gemini.
PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "").strip().lower() in ("1", "true", "yes")

# A host can provide keys as environment variables (never shown on the page).
ENV_KEYS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "ncbi": "NCBI_API_KEY"}


def api_key(settings: dict, name: str) -> str:
    """The visitor's own key if they entered one, otherwise the host's environment key."""
    return ((settings or {}).get(f"{name}_api_key") or os.environ.get(ENV_KEYS.get(name, ""), "") or "").strip()


def has_key(settings: dict, name: str) -> bool:
    return bool(api_key(settings, name))

DEFAULTS = {
    "provider": "groq",              # "groq" | "gemini" | "openai" | "ollama"
    "groq_api_key": "",
    "gemini_api_key": "",
    "openai_api_key": "",
    "openai_model": "gpt-5.6-luna",
    "openai_reasoning": "low",
    "groq_model": "openai/gpt-oss-120b",
    "gemini_model": "gemini-3.8-flash",
    "gemini_thinking": "low",
    "groq_vision_model": "qwen/qwen3.8-27b",
    "ollama_vision_model": "medgemma:4b",
    "speed": "balanced",              # "balanced" | "fast" (smaller, quicker cloud models)
    "knowledge_sources": ["local", "guidelines", "reviews", "pubmed", "europepmc", "casereports",
                          "medlineplus", "wikipedia"],   # which libraries the Evidence tab searches
    "per_source": 4,                  # passages kept per source and diagnosis
    "wikipedia_lang": "en",           # "en" | "ar"
    "form_mode": False,               # guided case form instead of one free-text box
    "auto_evidence": True,            # search PubMed for every diagnosis automatically, in parallel
    "ollama_model": "llama3.1",
    "ollama_url": os.environ.get("OLLAMA_URL") or "http://localhost:11434",
    "ollama_num_ctx": 16384,         # starting context window; the app GROWS it to fit a long case
    "ollama_auto_ctx": True,         # never let Ollama silently cut the start of a long case
    "ollama_num_predict": 0,         # 0 = NO answer-length limit. A repetition guard (not a cap)
                                     # stops a model that is stuck in a loop - see providers.py.
    "settings_version": 2,
    "language": os.environ.get("DEFAULT_LANGUAGE") if os.environ.get("DEFAULT_LANGUAGE") in ("en", "ar") else "en",   # interface language, switchable in the sidebar
    "ai_language": "auto",            # language the AI answers in: "auto" (same as the
                                      # interface) | "ar" | "en". A small local model can
                                      # reason well but have no usable Arabic - qwen2.5
                                      # slips into Chinese - so the two are separate.
    "department": "",                 # e.g. "Tropical Medicine", "Pediatrics" - from a dropdown in Settings
    "department_other": "",           # free text, used when department == "Other"
    "data_types": ["history_exam", "labs", "images", "tables"],  # which kinds of text the case may include
                                       # subset of: history_exam, labs, imaging_text,
                                       # pathology_text, discharge_summary
    "org_name": "",                   # department, hospital or conference name. Shown as a
                                      # wordmark above the title and in the printed report's
                                      # header. Empty = no wordmark (the plain title alone).
    "specialty_hint": "",             # extra free-text focus, e.g. "hepatology"
    "ncbi_api_key": "",               # optional, raises PubMed rate limit
    "max_differentials": 8,
    "custom_instructions": "",        # extra free-text rules a doctor can add
}

DEPARTMENTS = [
    "Internal Medicine", "Tropical / Infectious Disease", "Gastroenterology",
    "Cardiology", "Pulmonology", "Nephrology", "Hematology", "Neurology",
    "Pediatrics", "Obstetrics & Gynecology", "General Surgery",
    "Emergency Medicine", "Family Medicine", "Other",
]

DATA_TYPE_LABELS = {
    "history_exam": {"en": "History & physical exam", "ar": "التاريخ المرضي والفحص الإكلينيكي"},
    "labs": {"en": "Laboratory results (as text/numbers)", "ar": "نتائج التحاليل (كنص/أرقام)"},
    "imaging_text": {"en": "Imaging findings described in words",
                     "ar": "نتائج الأشعة موصوفة بالكلمات"},
    "images": {"en": "Uploaded images (X-ray, endoscopy, ECG, photos)",
               "ar": "صور مرفوعة (أشعة، مناظير، رسم قلب، صور)"},
    "tables": {"en": "Excel / CSV tables (labs, vitals, trends)",
               "ar": "جداول Excel / CSV (تحاليل، علامات حيوية)"},
    "slides": {"en": "PowerPoint case presentation (.pptx)",
               "ar": "عرض الحالة على PowerPoint (.pptx)"},
    "pathology_text": {"en": "Pathology / biopsy report text",
                       "ar": "نص تقرير الباثولوجي / عينة الخزعة"},
    "discharge_summary": {"en": "Discharge summary / course in hospital",
                          "ar": "ملخص الخروج / مسار الحالة بالمستشفى"},
}

DISCLAIMER_EN = ("Educational decision-support draft, generated by an AI "
                 "language model. It can be wrong or incomplete. It is not a "
                 "diagnosis and never replaces the treating physician's "
                 "judgment, local guidelines, or a specialist opinion.")
DISCLAIMER_AR = ("مخرج أولي من أداة مساعدة تعليمية بالذكاء الاصطناعي، وقد يكون "
                 "خاطئًا أو ناقصًا. هذا ليس تشخيصًا نهائيًا ولا يحل محل قرار "
                 "الطبيب المعالج أو البروتوكولات المحلية أو رأي الأخصائي.")

# Uploads are OPTIONAL: the app works from typed text alone, and can also read
# Excel/CSV, PDF, Word, PowerPoint and images (photos/scans) when a doctor has them.
UPLOAD_NOTE_EN = ("Optional: attach Excel/CSV, PDF, Word, PowerPoint (.pptx) or images "
                  "(X-ray, endoscopy, ECG, photos). A case presentation is read slide by "
                  "slide, and the pictures on its slides are read too. "
                  "No files? Just type or paste the case - that works fine on its own.")
UPLOAD_NOTE_AR = ("اختياري: أرفق Excel/CSV أو PDF أو Word أو PowerPoint (.pptx) أو صور "
                  "(أشعة، مناظير، رسم قلب). عرض الحالة يُقرأ شريحة بشريحة، وتُقرأ أيضًا "
                  "الصور الموجودة داخل الشرائح. "
                  "لا توجد ملفات؟ اكتب الحالة أو الصقها فقط - تعمل الأداة بالنص وحده.")
# kept for old imports
NO_IMAGES_NOTE_EN, NO_IMAGES_NOTE_AR = UPLOAD_NOTE_EN, UPLOAD_NOTE_AR


def default_settings() -> dict:
    s = dict(DEFAULTS)
    if os.environ.get("DEFAULT_PROVIDER") in ("groq", "gemini", "openai", "ollama"):
        s["provider"] = os.environ["DEFAULT_PROVIDER"]
    s["settings_version"] = 2
    return s


def load_settings() -> dict:
    s = default_settings()
    if SETTINGS_FILE.exists() and not PUBLIC_MODE:
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    # Version 2 removed the answer-length cap. An older settings file still carries
    # the old automatic 4096 (there was no control for it), so it is lifted once.
    if int(s.get("settings_version", 1)) < 2:
        if int(s.get("ollama_num_predict", 0) or 0) == 4096:
            s["ollama_num_predict"] = 0
        s["settings_version"] = 2
    return s


def save_settings(settings: dict) -> None:
    if PUBLIC_MODE:
        return                      # a shared server never stores anyone's settings or keys
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                             encoding="utf-8")


# --------------------------------------------------------------- model advice
# Free models worth knowing about, so a doctor picks from a list with plain-words
# advice instead of guessing a tag. Sizes are approximate downloads (GB). `ram` is
# the memory that makes the model comfortable; a smaller machine still runs it,
# just slower. Any other tag from ollama.com/library can be typed in too.
TEXT_MODELS = [
    {"tag": "qwen2.5:7b", "gb": 4.7, "ram": 8,
     "en": "Solid all-rounder, fast, good at following the JSON format. Weak Arabic - keep the AI answering in English.",
     "ar": "نموذج متوازن وسريع ويلتزم بالصيغة المطلوبة. عربيته ضعيفة - اجعل الإجابة بالإنجليزية."},
    {"tag": "qwen3:8b", "gb": 5.2, "ram": 8,
     "en": "Newer than qwen2.5, noticeably better at step-by-step clinical reasoning. The app switches its slow 'thinking' mode off.",
     "ar": "أحدث من qwen2.5 وأفضل في الاستدلال الإكلينيكي خطوة بخطوة. يوقف التطبيق وضع التفكير البطيء فيه."},
    {"tag": "llama3.1:8b", "gb": 4.9, "ar_ok": False, "ram": 8,
     "en": "Steady and predictable, good English medical writing, rarely loops.",
     "ar": "ثابت ويمكن الاعتماد عليه، كتابة طبية إنجليزية جيدة ونادراً ما يكرر نفسه."},
    {"tag": "gemma3:12b", "gb": 8.1, "ram": 16,
     "en": "Best quality of the free local models here and the best Arabic. Needs about 16 GB of memory.",
     "ar": "أفضل جودة بين النماذج المحلية هنا وأفضل عربية. يحتاج نحو 16 جيجا ذاكرة."},
    {"tag": "gemma3:4b", "gb": 3.3, "ram": 8,
     "en": "Small and quick, reads images too. Good for a modest laptop; less reliable on hard cases.",
     "ar": "صغير وسريع ويقرأ الصور أيضاً. مناسب للحاسوب المتواضع لكنه أقل دقة في الحالات الصعبة."},
    {"tag": "phi4:14b", "gb": 9.1, "ram": 16,
     "en": "Strong at reasoning for its size. English only, needs about 16 GB of memory.",
     "ar": "قوي في الاستدلال بالنسبة لحجمه. إنجليزي فقط ويحتاج نحو 16 جيجا ذاكرة."},
    {"tag": "medgemma:4b", "gb": 3.3, "ram": 8,
     "en": "Google's model trained on medical text AND medical images. Small enough for any laptop. A research model: verify its output.",
     "ar": "نموذج من Google مدرَّب على نصوص وصور طبية. صغير يعمل على أي حاسوب. نموذج بحثي: تحقق من مخرجاته."},
]

VISION_MODELS = [
    {"tag": "medgemma:4b", "gb": 3.3, "ram": 8,
     "en": "Best free choice for medical pictures (X-ray, skin, pathology, endoscopy). Trained on medical images.",
     "ar": "أفضل خيار مجاني للصور الطبية (أشعة، جلد، باثولوجي، مناظير). مدرَّب على صور طبية."},
    {"tag": "qwen2.5vl:7b", "gb": 6.0, "ram": 16,
     "en": "Sharpest at reading TEXT inside a picture (lab report photos, monitors, slides) and general photos.",
     "ar": "الأفضل في قراءة النص داخل الصورة (صور التحاليل والشاشات والشرائح) والصور العامة."},
    {"tag": "qwen2.5vl:3b", "gb": 3.2, "ram": 8,
     "en": "Lighter version of the above for small machines.",
     "ar": "نسخة أخف من السابق للأجهزة الصغيرة."},
    {"tag": "gemma3:12b", "gb": 8.1, "ram": 16,
     "en": "Good general vision plus the best Arabic; also a strong text model, so one download does both.",
     "ar": "رؤية عامة جيدة وأفضل عربية؛ وهو أيضاً نموذج نصي قوي فيكفي تنزيل واحد للاثنين."},
    {"tag": "llama3.2-vision", "gb": 7.8, "ram": 16,
     "en": "Heavy and older. Only if the others do not work for you.",
     "ar": "ثقيل وأقدم. استخدمه فقط إذا لم تنفع الخيارات الأخرى."},
    {"tag": "moondream", "gb": 1.7, "ram": 4,
     "en": "Tiny, works on very old computers. Basic descriptions only.",
     "ar": "صغير جداً ويعمل على الأجهزة القديمة. أوصاف بسيطة فقط."},
]

IMAGE_TYPE_LABELS = {
    "auto": {"en": "Not sure - detect it", "ar": "لا أعرف - اكتشفها تلقائياً"},
    "xray": {"en": "X-ray", "ar": "أشعة سينية (X-ray)"},
    "ct": {"en": "CT scan", "ar": "أشعة مقطعية (CT)"},
    "mri": {"en": "MRI", "ar": "رنين مغناطيسي (MRI)"},
    "ultrasound": {"en": "Ultrasound", "ar": "موجات صوتية (Ultrasound)"},
    "endoscopy": {"en": "Endoscopy / colonoscopy", "ar": "منظار / قولون"},
    "ecg": {"en": "ECG tracing", "ar": "رسم قلب (ECG)"},
    "pathology": {"en": "Pathology / microscope slide", "ar": "باثولوجي / شريحة مجهرية"},
    "skin": {"en": "Skin, wound or clinical photo", "ar": "صورة جلد أو جرح أو صورة إكلينيكية"},
    "fundus": {"en": "Retina (fundus) photo", "ar": "صورة قاع العين"},
    "document": {"en": "Photo of a lab report / document", "ar": "صورة تقرير تحاليل / مستند"},
    "other": {"en": "Other", "ar": "أخرى"},
}