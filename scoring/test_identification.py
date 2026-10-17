"""Identification coverage: is a friendly drone within identification range of a hostile?"""

import unittest

from scoring.identification import identification


def obj(object_id, kind, rows):
    return {"id": object_id, "kind": kind, "samples": rows}


def truth(*objects):
    return {"objects": list(objects)}


class TestIdentification(unittest.TestCase):
    def test_a_drone_that_stays_in_range_covers_all_steps_with_no_delay(self):
        hostile = obj("H1", "hostile", [[0.0, 100.0, 0.0, 0.0, 0.0], [10.0, 100.0, 0.0, 0.0, 0.0]])
        drone = obj("F1", "friendly", [[0.0, 150.0, 0.0, 0.0, 0.0], [10.0, 150.0, 0.0, 0.0, 0.0]])
        covered, delay = identification(truth(hostile, drone), {"F1": 80.0})
        self.assertEqual((covered, delay), (1.0, 0.0))

    def test_a_drone_that_arrives_late_gives_a_delay_and_part_coverage(self):
        hostile = obj("H1", "hostile", [[0.0, 0.0, 0.0, 0.0, 0.0], [10.0, 0.0, 0.0, 0.0, 0.0]])
        drone = obj("F1", "friendly", [[0.0, 500.0, 0.0, -50.0, 0.0], [10.0, 0.0, 0.0, -50.0, 0.0]])    # arrives at the end
        covered, delay = identification(truth(hostile, drone), {"F1": 100.0})
        self.assertAlmostEqual(delay, 8.0, delta=0.5)
        self.assertGreater(covered, 0.0)
        self.assertLess(covered, 0.5)

    def test_a_hostile_never_covered_counts_its_whole_time_and_a_drone_out_of_the_list_does_not_count(self):
        hostile = obj("H1", "hostile", [[0.0, 0.0, 0.0, 0.0, 0.0], [10.0, 0.0, 0.0, 0.0, 0.0]])
        near = obj("X9", "friendly", [[0.0, 5.0, 0.0, 0.0, 0.0], [10.0, 5.0, 0.0, 0.0, 0.0]])
        covered, delay = identification(truth(hostile, near), {"F1": 100.0})
        self.assertEqual((covered, delay), (0.0, 10.0))

    def test_the_warmup_is_skipped(self):
        hostile = obj("H1", "hostile", [[0.0, 0.0, 0.0, 0.0, 0.0], [10.0, 0.0, 0.0, 0.0, 0.0]])
        drone = obj("F1", "friendly", [[0.0, 900.0, 0.0, 0.0, 0.0], [5.0, 900.0, 0.0, 0.0, 0.0], [5.5, 0.0, 0.0, 0.0, 0.0],
                                       [10.0, 0.0, 0.0, 0.0, 0.0]])
        covered, delay = identification(truth(hostile, drone), {"F1": 100.0}, warmup_s=5.0)
        self.assertLess(delay, 1.5)


if __name__ == "__main__":
    unittest.main()
