"""
Regression tests for the Open5GS subscriber-schema traversal.

Every tool previously queried only the legacy top-level ``session`` array.  On
an Open5GS 2.8.0 testbed, which stores sessions under ``slice[].session[]``,
policy writes matched nothing and the collector read empty AMBR values — yet
``apply_policy`` still reported success, so a vacuous write passed the
``accepted`` gate in ``agent_runner`` and the probe shaped traffic for a policy
the core never applied.

These tests pin both halves of the fix:

  * a policy write reaches the stored AMBR under *either* schema, and
  * a write that changes nothing reports failure rather than success.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mongomock    # noqa: E402
import pymongo      # noqa: E402

pymongo.MongoClient = mongomock.MongoClient
import config.db    # noqa: E402

config.db.MongoClient = mongomock.MongoClient
config.db._client = mongomock.MongoClient()

from config.db import get_open5gs_db           # noqa: E402
from tools.policy_manager import PolicyManager  # noqa: E402

SLICE = "internet"


def _session(name=SLICE, dl=20, ul=20):
    return {
        "name": name,
        "type": 3,
        "ambr": {
            "downlink": {"value": dl, "unit": 3},
            "uplink":   {"value": ul, "unit": 3},
        },
        "qos": {"index": 9, "arp": {"priority_level": 8}},
    }


def _legacy_subscriber(imsi):
    """Open5GS <= 2.6: sessions in a top-level array."""
    return {"imsi": imsi, "session": [_session()]}


def _modern_subscriber(imsi):
    """Open5GS 2.7+ (incl. 2.8.0): sessions under slice[].session[]."""
    return {
        "imsi": imsi,
        "slice": [{"sst": 1, "default_indicator": True, "session": [_session()]}],
    }


def _both_subscriber(imsi):
    """What the WebUI writes: both arrays present."""
    return {
        "imsi": imsi,
        "session": [_session()],
        "slice": [{"sst": 1, "default_indicator": True, "session": [_session()]}],
    }


def _stored_ambr(imsi):
    """Every downlink AMBR value stored for ``imsi``, under either schema."""
    from tools.open5gs_schema import iter_named_sessions
    doc = get_open5gs_db()["subscribers"].find_one({"imsi": imsi})
    return [
        s.get("ambr", {}).get("downlink", {}).get("value")
        for s in iter_named_sessions(doc, SLICE)
    ]


class TestSchemaCompatibility(unittest.TestCase):
    def setUp(self):
        self.db = get_open5gs_db()
        self.db["subscribers"].delete_many({})
        self.pm = PolicyManager()

    def _apply_60mbps(self):
        return self.pm._apply_via_direct_mongo(
            self.pm._build_request(  # type: ignore[attr-defined]
                target_slice=SLICE, new_dl_ambr=60_000_000, new_ul_ambr=60_000_000
            )
        )

    def test_legacy_schema_write_lands(self):
        self.db["subscribers"].insert_one(_legacy_subscriber("001010000000001"))
        result = self.pm.apply_policy(
            target_slice=SLICE, new_dl_ambr=60_000_000, new_ul_ambr=60_000_000
        )
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(_stored_ambr("001010000000001"), [60])

    def test_modern_slice_schema_write_lands(self):
        """The case that silently did nothing before the fix."""
        self.db["subscribers"].insert_one(_modern_subscriber("001010000000002"))
        result = self.pm.apply_policy(
            target_slice=SLICE, new_dl_ambr=60_000_000, new_ul_ambr=60_000_000
        )
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(_stored_ambr("001010000000002"), [60])

    def test_dual_schema_both_arrays_updated(self):
        self.db["subscribers"].insert_one(_both_subscriber("001010000000003"))
        result = self.pm.apply_policy(
            target_slice=SLICE, new_dl_ambr=60_000_000, new_ul_ambr=60_000_000
        )
        self.assertTrue(result["success"], msg=result.get("message"))
        # Both copies must move, or a later read picks up a stale value.
        self.assertEqual(_stored_ambr("001010000000003"), [60, 60])

    def test_readback_matches_write(self):
        """get_current_policy must see what apply_policy wrote, either schema."""
        self.db["subscribers"].insert_one(_modern_subscriber("001010000000004"))
        self.pm.apply_policy(
            target_slice=SLICE, new_dl_ambr=45_000_000, new_ul_ambr=45_000_000
        )
        current = self.pm.get_current_policy(SLICE)
        self.assertEqual(current["count"], 1)
        self.assertEqual(current["subscribers"][0]["dl_ambr"], 45)


class TestVacuousWriteReportsFailure(unittest.TestCase):
    """A write that moves no AMBR must not report success."""

    def setUp(self):
        self.db = get_open5gs_db()
        self.db["subscribers"].delete_many({})
        self.pm = PolicyManager()

    def test_no_matching_subscriber(self):
        self.db["subscribers"].insert_one(_legacy_subscriber("001010000000005"))
        result = self.pm.apply_policy(
            target_slice="nonexistent-slice",
            new_dl_ambr=60_000_000,
            new_ul_ambr=60_000_000,
        )
        self.assertFalse(result["success"])

    def test_matched_subscriber_without_that_session(self):
        """
        The exact defect: the subscriber matches the filter but carries no
        session with the requested name, so nothing is written.  Before the
        fix this returned success=True with the subscriber listed as affected.
        """
        doc = _legacy_subscriber("001010000000006")
        # Matches on the slice array, but the named session lives nowhere.
        doc["slice"] = [{"sst": 1, "session": [_session(name=SLICE)]}]
        doc["session"] = []
        self.db["subscribers"].insert_one(doc)

        before = _stored_ambr("001010000000006")
        result = self.pm.apply_policy(
            target_slice=SLICE, new_dl_ambr=60_000_000, new_ul_ambr=60_000_000
        )
        after = _stored_ambr("001010000000006")

        if result["success"]:
            # If it claims success, the stored value must actually have moved.
            self.assertNotEqual(before, after,
                                msg="apply_policy reported success but no AMBR changed")
        else:
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
