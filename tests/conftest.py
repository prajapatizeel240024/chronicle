import pytest

from chronicle.dataset import load_all
from chronicle.extract import RawExtraction
from chronicle.gen import write_all


@pytest.fixture(scope="session")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    write_all(root)
    return root


@pytest.fixture(scope="session")
def patients(data_root):
    return load_all(data_root)


class OracleExtractor:
    """Returns the answer key as if it were a perfect model."""
    name = "oracle"

    def __init__(self, patients):
        self.by_msg = {}
        for p in patients:
            for t in p.events:
                self.by_msg.setdefault(t["msg_id"], []).append(t)

    def extract(self, msg, ctx):
        out = []
        for t in self.by_msg.get(msg.msg_id, []):
            out.append({"kind": t["kind"], "name": t["med_as_said"] if t["kind"] == "med" else t["name"],
                        "body_site": t["body_site"], "severity": t["severity"], "date_phrase": t["date"],
                        "negated": t["negated"], "subject": t["subject"], "reality": t["reality"],
                        "condition": t["condition"], "med_action": t["med_action"], "dose": t["dose"],
                        "triggers": [x.replace("_", " ") for x in t["triggers"]], "quote": t["quote"]})
        return RawExtraction(out)


@pytest.fixture(scope="session")
def oracle(patients):
    return OracleExtractor(patients)
