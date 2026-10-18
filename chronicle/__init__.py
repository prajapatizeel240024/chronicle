"""Chronicle: a symptom log you can check. Synthetic data only. Not medical advice."""
from __future__ import annotations

import os
from pathlib import Path

NOT_MEDICAL_ADVICE = (
    "Synthetic data only. Chronicle is a demo of logging and evaluation, "
    "not medical advice. Talk to a clinician about real symptoms."
)


def load_env(path: str | Path = ".env", environ=None) -> None:
    """Copy KEY=VALUE lines from the local, git-ignored .env (template: .env.example) into the
    environment. A non-blank variable already set wins; in the file, the last line for a key wins
    (as in a shell); blank values count as unset, so the code's defaults apply."""
    environ = os.environ if environ is None else environ
    p = Path(path)
    if not p.is_file():
        return
    found = {}
    for line in p.read_text().splitlines():
        key, eq, value = line.strip().removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if not eq or not key or key.startswith("#"):
            continue
        q = value[:1]
        if q in ("'", '"') and q in value[1:]:
            value = value[1:value.index(q, 1)]      # quoted: keep everything inside the quotes
        else:
            value = value.split(" #", 1)[0].strip()  # unquoted: drop an inline comment
        found[key] = value
    for key, value in found.items():
        if value and not environ.get(key):
            environ[key] = value
