import numpy as np

from behavauth.features import keystroke_features
from behavauth.realdata import CMU_KEYS, _balabit_session, _events


def test_cmu_timings_become_class_only_key_events():
    rep = {f"H.{k}": 0.1 for k in CMU_KEYS}
    rep.update({f"DD.{a}.{b}": 0.25 for a, b in zip(CMU_KEYS, CMU_KEYS[1:])})
    ev = _events(rep, 0.0)
    assert len(ev) == 2 * len(CMU_KEYS)
    assert {e["k"] for e in ev} == {"letter", "digit", "shift", "other"}  # no characters kept
    f = keystroke_features(ev)
    assert np.isclose(f["dwell_mean"], 100.0) and np.isclose(f["dd_mean"], 250.0)


def test_balabit_rows_map_to_pointer_events(tmp_path):
    p = tmp_path / "session_1"
    p.write_text("record timestamp,client timestamp,button,state,x,y\n"
                 "0.0,0.0,NoButton,Move,10,20\n0.0,0.016,Left,Pressed,11,20\n"
                 "0.0,0.1,Left,Released,11,20\n0.0,0.2,NoButton,Scroll,11,20\n0.0,0.3,NoButton,Move,65535,65535\n")
    ev = _balabit_session(p)
    assert [e["type"] for e in ev] == ["mm", "md", "mu"] and ev[1]["t"] == 16.0
