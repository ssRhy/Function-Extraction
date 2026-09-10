import json
import re
from pathlib import Path


def test_matcher_regression_sample_is_fixed_and_uses_stable_ids():
    path = Path(__file__).parent / "fixtures" / "matcher_regression_30.json"
    sample = json.loads(path.read_text(encoding="utf-8"))
    observations = sample["observations"]
    obs_ids = [item["obs_id"] for item in observations]
    assert len(obs_ids) == 30
    assert len(set(obs_ids)) == 30
    assert all(re.fullmatch(r"ST_[a-z0-9]+_obs_[a-f0-9]{12}", obs_id) for obs_id in obs_ids)
    assert set(sample["split_candidates"]).issubset(set(obs_ids))
