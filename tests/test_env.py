from pathlib import Path

from chronicle import load_env
from chronicle.app import bind_address


def test_load_env_parses_dotenv_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# a comment\n\nexport A=1\nB = 'two words'\nC=x  # note\nD=\"has # hash\"\nE=a=b\n"
                 "EMPTY=\nQUOTED_EMPTY=\"\"\nno_equals_sign\n#COMMENTED=1\nF=first\nF=last\n")
    env = {}
    load_env(f, env)
    assert env == {"A": "1", "B": "two words", "C": "x", "D": "has # hash", "E": "a=b", "F": "last"}


def test_load_env_never_overrides_a_set_variable(tmp_path):
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=from-file\nCHRONICLE_HOST=127.0.0.1\nCHRONICLE_PORT=8000\n")
    env = {"ANTHROPIC_API_KEY": "from-shell", "CHRONICLE_HOST": ""}  # blank counts as unset
    load_env(f, env)
    assert env == {"ANTHROPIC_API_KEY": "from-shell", "CHRONICLE_HOST": "127.0.0.1", "CHRONICLE_PORT": "8000"}


def test_load_env_without_a_file_is_a_no_op(tmp_path):
    env = {}
    load_env(tmp_path / "missing.env", env)
    assert env == {}


def test_env_example_lists_every_setting_and_carries_no_key():
    path = Path(__file__).parent.parent / ".env.example"
    assert "\nANTHROPIC_API_KEY=\n" in path.read_text()  # listed, and left blank
    env = {}
    load_env(path, env)
    assert env == {"CHRONICLE_HOST": "127.0.0.1", "CHRONICLE_PORT": "8000"}


def test_demo_binds_to_localhost_unless_told_otherwise(monkeypatch):
    monkeypatch.setenv("CHRONICLE_HOST", "")  # blank must not mean "every interface"
    monkeypatch.delenv("CHRONICLE_PORT", raising=False)
    assert bind_address() == ("127.0.0.1", 8000)
    monkeypatch.setenv("CHRONICLE_PORT", "8001")
    assert bind_address() == ("127.0.0.1", 8001)
