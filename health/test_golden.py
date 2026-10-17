import json

import pytest

from health.golden import PATH, build


def test_the_shared_cases_file_matches_the_code():
    """Fails when the health code changes without `python -m health.golden` being run."""
    def same(actual, expected):
        if isinstance(expected, float):
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12)
        elif isinstance(expected, dict):
            assert actual.keys() == expected.keys()
            for key in expected:
                same(actual[key], expected[key])
        elif isinstance(expected, list):
            assert len(actual) == len(expected)
            for a, b in zip(actual, expected):
                same(a, b)
        else:
            assert actual == expected
    same(json.loads(PATH.read_text(encoding="utf-8")), json.loads(json.dumps(build())))
