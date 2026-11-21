"""Starts the real app with the AI mocked and clicks through the main paths.
Runs offline: python tests/smoke_test.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PUBLIC_MODE"] = "1"          # nothing is written to disk
os.environ.setdefault("GROQ_API_KEY", "test-key")

from streamlit.testing.v1 import AppTest  # noqa: E402

import knowledge  # noqa: E402
import providers  # noqa: E402

DD = {"case_summary": {"one_line": "x", "key_positive_findings": [], "key_negative_or_missing": []},
      "differential": [{"rank": 1, "diagnosis": "Dengue fever", "must_exclude_first": False, "likelihood": "high",
                        "supporting_findings": ["fever"], "arguing_against": [], "confirmatory_test": "NS1", "search_terms": "dengue"}],
      "image_findings": [], "red_flags_now": [], "missing_information": [], "uncertainty_note": ""}


def fake_ask(system, user, settings, images=None, use_cache=True, on_progress=None):
    return json.loads(json.dumps(DD))


providers.ask_json = fake_ask
knowledge.gather_many = lambda items, settings, selected=None, workers=3: ({d: [] for d, _ in items}, {})

for lang in ("en", "ar"):
    os.environ["DEFAULT_LANGUAGE"] = lang
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert len(at.tabs) >= 6, "tabs missing"
    at.text_area(key="case_text").set_value("35-year-old woman, fever for 5 days, platelets 40")
    at.run()
    at.button(key="go_dd").click().run()
    assert not at.exception, at.exception
    assert any("Dengue fever" in m.value for m in at.markdown), "differential not shown"
    print(lang, "ok")

assert not (ROOT / "user_settings.json").exists(), "public mode must not write settings"
print("smoke test passed")
