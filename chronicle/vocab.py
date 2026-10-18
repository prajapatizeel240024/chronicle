"""Shared vocabulary: severity anchors, conditions, symptoms, meds, triggers."""
from __future__ import annotations

import re

# One 0-10 scale, written anchors. The answer key stores a RANGE around the
# intended value because two reasonable people disagree by a point or two.
SEVERITY_ANCHORS = {
    "0": "None.",
    "1-2": "Faint. Forgotten when busy.",
    "3-4": "Noticeable, but I do everything I planned.",
    "5-6": "Hard to ignore. I cut back on some activities.",
    "7-8": "Limits most activities. Mostly resting or lying down.",
    "9-10": "Unbearable. I cannot function; I would want urgent care.",
}

CONDITIONS: dict[str, dict] = {
    "pots": {"name": "POTS", "aliases": ["POTS"],
             "symptoms": ["dizziness", "palpitations", "fatigue", "brain_fog", "nausea"]},
    "eds": {"name": "EDS", "aliases": ["EDS", "Ehlers-Danlos"],
            "symptoms": ["joint_pain", "joint_subluxation", "muscle_pain", "fatigue"]},
    "migraine": {"name": "Migraine", "aliases": ["migraine"],
                 "symptoms": ["migraine", "nausea", "light_sensitivity", "headache"]},
    "endometriosis": {"name": "Endometriosis", "aliases": ["endo", "endometriosis"],
                      "symptoms": ["pelvic_pain", "nausea", "bloating", "fatigue", "back_pain"]},
    "ibs": {"name": "IBS", "aliases": ["IBS"],
            "symptoms": ["abdominal_pain", "bloating", "diarrhea", "constipation"]},
    "mecfs": {"name": "ME/CFS", "aliases": ["ME/CFS", "CFS"],
              "symptoms": ["fatigue", "post_exertional_malaise", "brain_fog",
                           "unrefreshing_sleep", "muscle_pain"]},
    "fibromyalgia": {"name": "Fibromyalgia", "aliases": ["fibro", "fibromyalgia"],
                     "symptoms": ["muscle_pain", "joint_pain", "fatigue", "brain_fog",
                                  "unrefreshing_sleep"]},
    "long_covid": {"name": "Long COVID", "aliases": ["long COVID"],
                   "symptoms": ["fatigue", "shortness_of_breath", "brain_fog",
                                "palpitations", "headache"]},
    "ra": {"name": "Rheumatoid arthritis", "aliases": ["RA"],
           "symptoms": ["joint_pain", "joint_stiffness", "fatigue"]},
    "gastroparesis": {"name": "Gastroparesis", "aliases": ["gastroparesis"],
                      "symptoms": ["nausea", "bloating", "abdominal_pain"]},
}

# canonical -> phrases a patient might use in plain (non-slang) text, plus sites.
SYMPTOMS: dict[str, dict] = {
    "dizziness": {"phrases": ["dizziness", "dizzy spells", "lightheadedness"], "sites": []},
    "palpitations": {"phrases": ["palpitations", "heart racing", "a fluttering heart"], "sites": []},
    "fatigue": {"phrases": ["fatigue", "exhaustion", "tiredness"], "sites": []},
    "brain_fog": {"phrases": ["brain fog", "foggy thinking"], "sites": []},
    "headache": {"phrases": ["headache", "head pain"], "sites": []},
    "migraine": {"phrases": ["migraine", "migraine attack"], "sites": []},
    "nausea": {"phrases": ["nausea", "queasiness"], "sites": []},
    "light_sensitivity": {"phrases": ["light sensitivity", "sensitivity to light"], "sites": []},
    "joint_pain": {"phrases": ["joint pain", "aching joints"],
                   "sites": ["knees", "hips", "wrists", "shoulders"]},
    "joint_subluxation": {"phrases": ["a subluxation", "a joint slipping out"],
                          "sites": ["shoulder", "hip", "knee"]},
    "joint_stiffness": {"phrases": ["joint stiffness", "morning stiffness"],
                        "sites": ["hands", "knees"]},
    "muscle_pain": {"phrases": ["muscle pain", "muscle aches"], "sites": ["legs", "back", "neck"]},
    "back_pain": {"phrases": ["back pain"], "sites": ["lower back"]},
    "pelvic_pain": {"phrases": ["pelvic pain"], "sites": ["pelvis"]},
    "abdominal_pain": {"phrases": ["abdominal pain", "stomach cramps"], "sites": ["lower abdomen"]},
    "bloating": {"phrases": ["bloating"], "sites": []},
    "diarrhea": {"phrases": ["diarrhea"], "sites": []},
    "constipation": {"phrases": ["constipation"], "sites": []},
    "post_exertional_malaise": {"phrases": ["post-exertional malaise", "a PEM crash"], "sites": []},
    "unrefreshing_sleep": {"phrases": ["unrefreshing sleep", "waking up unrefreshed"], "sites": []},
    "shortness_of_breath": {"phrases": ["shortness of breath", "breathlessness"], "sites": []},
    "tinnitus": {"phrases": ["ringing in my ears", "tinnitus"], "sites": []},
    "numbness_tingling": {"phrases": ["tingling in my fingers", "pins and needles"], "sites": []},
    "rash": {"phrases": ["a rash", "an itchy rash"], "sites": ["forearms", "chest"]},
}

# Everything the model may call a symptom; anything else is rejected in code.
SYMPTOM_NAMES = sorted(SYMPTOMS)

# Words the code will accept as aliases when a model returns a non-canonical name.
_SYNONYM_TO_CANON: dict[str, str] = {}
for _canon, _d in SYMPTOMS.items():
    _SYNONYM_TO_CANON[_canon] = _canon
    _SYNONYM_TO_CANON[_canon.replace("_", " ")] = _canon
    for _p in _d["phrases"]:
        _SYNONYM_TO_CANON[_p.lower()] = _canon
_SYNONYM_TO_CANON.update({
    "lightheaded": "dizziness", "dizzy": "dizziness", "vertigo": "dizziness",
    "pem": "post_exertional_malaise", "post exertional malaise": "post_exertional_malaise",
    "crash": "post_exertional_malaise", "heart racing": "palpitations",
    "tachycardia": "palpitations", "fogginess": "brain_fog", "cognitive fog": "brain_fog",
    "tired": "fatigue", "exhausted": "fatigue", "stomach pain": "abdominal_pain",
    "cramps": "abdominal_pain", "ringing in ears": "tinnitus", "shortness breath": "shortness_of_breath",
})


def canonical_symptom(name: str) -> str | None:
    key = re.sub(r"\s+", " ", name.strip().lower().replace("-", " ").replace("_", " "))
    if key in _SYNONYM_TO_CANON:
        return _SYNONYM_TO_CANON[key]
    return _SYNONYM_TO_CANON.get(key.replace(" ", "_"))


MEDS: dict[str, dict] = {
    "propranolol": {"brands": ["Inderal"], "doses": ["10 mg", "20 mg"]},
    "fludrocortisone": {"brands": ["Florinef"], "doses": ["0.1 mg"]},
    "midodrine": {"brands": ["ProAmatine"], "doses": ["5 mg"]},
    "sumatriptan": {"brands": ["Imitrex"], "doses": ["50 mg"]},
    "rizatriptan": {"brands": ["Maxalt"], "doses": ["10 mg"]},
    "topiramate": {"brands": ["Topamax"], "doses": ["25 mg"]},
    "naproxen": {"brands": ["Aleve"], "doses": ["220 mg"]},
    "norethindrone": {"brands": ["Aygestin"], "doses": ["5 mg"]},
    "dicyclomine": {"brands": ["Bentyl"], "doses": ["10 mg"]},
    "loperamide": {"brands": ["Imodium"], "doses": ["2 mg"]},
    "naltrexone": {"brands": ["Revia"], "doses": ["1.5 mg"]},
    "duloxetine": {"brands": ["Cymbalta"], "doses": ["30 mg"]},
    "pregabalin": {"brands": ["Lyrica"], "doses": ["75 mg"]},
    "gabapentin": {"brands": ["Neurontin"], "doses": ["300 mg"]},
    "methotrexate": {"brands": ["Trexall"], "doses": ["15 mg"], "immunosuppressant": True},
    "hydroxychloroquine": {"brands": ["Plaquenil"], "doses": ["200 mg"]},
    "adalimumab": {"brands": ["Humira"], "doses": ["40 mg"], "immunosuppressant": True},
    "azathioprine": {"brands": ["Imuran"], "doses": ["50 mg"], "immunosuppressant": True},
    "prednisone": {"brands": ["Deltasone"], "doses": ["5 mg"], "immunosuppressant": True},
    "ondansetron": {"brands": ["Zofran"], "doses": ["4 mg"]},
    "metoclopramide": {"brands": ["Reglan"], "doses": ["5 mg"]},
    "cetirizine": {"brands": ["Zyrtec"], "doses": ["10 mg"]},
}
IMMUNOSUPPRESSANTS = {m for m, d in MEDS.items() if d.get("immunosuppressant")}
BRAND_TO_GENERIC = {b.lower(): g for g, d in MEDS.items() for b in d["brands"]}


def normalize_med(name: str) -> str | None:
    """Brand or generic (any case) -> generic. Done in code, not by the model."""
    key = re.sub(r"[^a-z ]", "", name.lower()).strip()
    for token in [key] + key.split():
        if token in MEDS:
            return token
        if token in BRAND_TO_GENERIC:
            return BRAND_TO_GENERIC[token]
    return None


# Triggers: free text from the model -> tag, in code.
TRIGGER_KEYWORDS = {
    "standing": ["standing", "stood up", "got up", "stand up"],
    "heat": ["heat", "hot shower", "hot day", "hot weather", "warm"],
    "exertion": ["walk", "exercise", "chores", "grocery", "stairs", "exertion", "workout"],
    "poor_sleep": ["bad night", "slept badly", "didn't sleep", "short sleep", "poor sleep", "slept poorly"],
    "stress": ["stress", "deadline", "argument", "anxious"],
    "food": ["cheese", "coffee", "wine", "big meal", "dairy", "chocolate"],
    "period": ["period", "cycle", "menstrual"],
}
# Phrases the generator uses ("after ...") -> the tag the key stores.
TRIGGER_PHRASES = {
    "standing in the shower": "standing", "standing in line": "standing",
    "a long walk": "exertion", "the grocery run": "exertion",
    "a stressful deadline": "stress", "a hot day": "heat",
    "a bad night's sleep": "poor_sleep", "a big meal": "food", "my period starting": "period",
}


def normalize_trigger(text: str) -> str | None:
    t = text.lower()
    for tag, kws in TRIGGER_KEYWORDS.items():
        if any(k in t for k in kws):
            return tag
    return None


def norm_site(site: str | None) -> str | None:
    if not site:
        return None
    s = re.sub(r"\b(my|the|both|left|right)\b", "", site.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:-1] if s.endswith("s") and len(s) > 3 else s
