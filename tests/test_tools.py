# tests/test_tools.py
# Standalone tests for all 5 NWDAF tools.
#
# These tests verify each tool works correctly WITHOUT requiring:
#   - A running Open5GS instance
#   - Ollama or the LLM
#   - A real UERANSIM setup
#
# They run against an in-memory MongoDB (mongomock): no MongoDB server is contacted, and
# nothing in a real open5gs / nwdaf_analytics database is read, written or deleted.
#
# Run:  python -m pytest tests/test_tools.py -v
#       python tests/test_tools.py            (without pytest)

import sys
import os
import json
import random
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# In-memory MongoDB for every test. This must run before any project module imports
# pymongo.MongoClient: the tests seed and clear collections, and must never reach a real
# database (a developer machine running Open5GS has one on localhost).
import mongomock    # noqa: E402
import pymongo      # noqa: E402

pymongo.MongoClient = mongomock.MongoClient
import config.db    # noqa: E402

config.db.MongoClient = mongomock.MongoClient
config.db._client = mongomock.MongoClient()


# ── test data seeding ──────────────────────────────────────────────────────────

def seed_test_metrics(n: int = 300) -> None:
    """Insert synthetic UPF / SMF / PCF metrics for testing."""
    from config.db import get_nwdaf_db
    from config.settings import NWDAF_UPF_METRICS, NWDAF_SMF_METRICS, NWDAF_PCF_METRICS

    db = get_nwdaf_db()

    # Clear existing test data
    for col in [NWDAF_UPF_METRICS, NWDAF_SMF_METRICS, NWDAF_PCF_METRICS]:
        db[col].delete_many({})

    upf_docs, smf_docs, pcf_docs = [], [], []
    for i in range(n):
        ts = datetime.now(timezone.utc)
        mem = round(4.80 + random.gauss(0, 0.04), 4)
        ue  = random.randint(5, 10)

        upf_docs.append({
            "timestamp":        ts,
            "memory_util_pct":  mem,
            "active_ue_count":  ue,
            "total_rx_bytes":   random.randint(100_000, 10_000_000),
            "total_tx_bytes":   random.randint(100_000, 10_000_000),
            "active_bearers":   ue,
        })
        smf_docs.append({
            "timestamp":     ts,
            "session_count": ue,
            "sessions":      [],
        })
        pcf_docs.append({
            "timestamp":    ts,
            "policy_count": random.randint(1, 5),
            "policies":     [],
        })

    db[NWDAF_UPF_METRICS].insert_many(upf_docs)
    db[NWDAF_SMF_METRICS].insert_many(smf_docs)
    db[NWDAF_PCF_METRICS].insert_many(pcf_docs)
    print(f"[SEED] Inserted {n} test metric documents into nwdaf_analytics")


def seed_test_subscribers() -> None:
    """
    Insert synthetic Open5GS subscribers for session/policy tests.

    IMPORTANT: Uses IMSI prefix '00101' (MCC=001, MNC=01) which is a
    reserved/test MCC and will never collide with the real UERANSIM UEs
    (which use MCC=999, MNC=70, prefix '99970').
    """
    from config.db import get_open5gs_db
    db = get_open5gs_db()
    # Only delete our synthetic test subscribers — never touch real UEs
    db["subscribers"].delete_many({"imsi": {"$regex": "^00101"}})

    subs = []
    for i in range(1, 11):
        imsi = f"00101000000{i:04d}"   # 15 digits, e.g. 001010000000001
        subs.append({
            "imsi": imsi,
            "session": [
                {
                    "name":   "internet",
                    "type":   3,
                    "ambr":   {
                        "downlink": {"value": 1000, "unit": 3},
                        "uplink":   {"value": 1000, "unit": 3},
                    },
                    "qos":    {"index": 9, "arp": {"priority_level": 8}},
                },
                {
                    "name":   "streaming",
                    "type":   3,
                    "ambr":   {
                        "downlink": {"value": 200, "unit": 3},
                        "uplink":   {"value": 100, "unit": 3},
                    },
                    "qos":    {"index": 9, "arp": {"priority_level": 8}},
                },
            ],
        })
    db["subscribers"].insert_many(subs)
    print(f"[SEED] Inserted {len(subs)} test subscribers (prefix 00101) into open5gs")


# ── Tool 1: KPIAnalyzer ────────────────────────────────────────────────────────

class TestKPIAnalyzer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_test_metrics(300)

    def test_list_metrics(self):
        from tools.kpi_analyzer import KPIAnalyzer
        metrics = KPIAnalyzer().list_metrics()
        self.assertIn("memory_utilization", metrics)
        self.assertIn("session_count", metrics)
        print(f"  ✓ Available metrics: {metrics}")

    def test_analyze_no_ml(self):
        from tools.kpi_analyzer import KPIAnalyzer
        result = KPIAnalyzer().analyze("memory_utilization", n_samples=100, run_ml=False)
        self.assertNotIn("error", result)
        stats = result["stats"]
        self.assertGreater(stats["count"], 0)
        self.assertIn(stats["trend"], ("rising", "falling", "stable"))
        print(f"  ✓ Stats: mean={stats['mean']:.4f} trend={stats['trend']}")

    def test_analyze_with_ml(self):
        from tools.kpi_analyzer import KPIAnalyzer
        result = KPIAnalyzer().analyze("memory_utilization", n_samples=200, run_ml=True, forecast_steps=20)
        self.assertNotIn("error", result)
        ml = result.get("ml", {})
        self.assertIsNotNone(ml)
        self.assertIn("train_r2", ml)
        self.assertIn("test_r2",  ml)
        self.assertIn("plot_path", ml)
        self.assertEqual(len(ml["forecast"]), 20)
        print(f"  ✓ ML: train_r2={ml['train_r2']:.3f} test_r2={ml['test_r2']:.3f} plot={ml['plot_path']}")

    def test_invalid_metric(self):
        from tools.kpi_analyzer import KPIAnalyzer
        result = KPIAnalyzer().analyze("nonexistent_metric")
        self.assertIn("error", result)
        print(f"  ✓ Invalid metric correctly rejected: {result['error'][:60]}")


# ── Tool 2: FeasibilityChecker ────────────────────────────────────────────────

def _cleanup_test_subscribers() -> None:
    """Remove all synthetic test subscribers (prefix 00101) — never touches real UEs."""
    from config.db import get_open5gs_db
    result = get_open5gs_db()["subscribers"].delete_many({"imsi": {"$regex": "^00101"}})
    print(f"[CLEANUP] Removed {result.deleted_count} test subscribers (prefix 00101)")


# ── real subscriber snapshot ─────────────────────────────────────────────────
# The real UEs use MCC=999 MNC=70 (prefix 99970). Their full documents
# (including K, OPc, AMF security fields) must never be wiped by tests.
# If a test run somehow corrupts them, call _restore_real_subscribers().
_REAL_K   = "465B5CE8B199B49FAA5F0A2EE238A6BC"
_REAL_OPC = "E8ED289DEBA952E4283B54E88E6183CA"
_REAL_AMF = "8000"

def _restore_real_subscribers() -> None:
    """
    Rebuild the 10 real subscriber documents (IMSIs 999700000000001–10)
    from the known credentials in UERANSIM/config/open5gs-ue.yaml.
    Safe to call at any time — idempotent.
    """
    from config.db import get_open5gs_db

    def _make(imsi: str) -> dict:
        sess = {
            "name": "internet", "type": 3,
            "ambr": {
                "downlink": {"value": 1, "unit": 3},
                "uplink":   {"value": 1, "unit": 3},
            },
            "qos": {"index": 9, "arp": {"priority_level": 8,
                                         "pre_emption_capability": 1,
                                         "pre_emption_vulnerability": 1}},
            "pcc_rule": [],
        }
        return {
            "imsi": imsi,
            "security": {"k": _REAL_K, "op": None, "opc": _REAL_OPC,
                         "amf": _REAL_AMF, "sqn": 0},
            "ambr": {"downlink": {"value": 1, "unit": 3},
                     "uplink":   {"value": 1, "unit": 3}},
            "slice": [{"sst": 1, "default_indicator": True, "session": [sess]}],
            "session": [sess],
            "__v": 0,
        }

    db = get_open5gs_db()
    db["subscribers"].delete_many({"imsi": {"$regex": "^99970"}})
    subs = [_make(f"99970000000{i:04d}") for i in range(1, 11)]
    db["subscribers"].insert_many(subs)
    print(f"[RESTORE] Rebuilt {len(subs)} real subscriber documents (prefix 99970)")


class TestFeasibilityChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_test_metrics(10)
        seed_test_subscribers()

    def setUp(self):
        # Clear audit/cooldown records before every test so PolicyManager
        # audit records from earlier test classes don't trigger the 30s cooldown.
        from config.db import get_nwdaf_db
        from config.settings import NWDAF_SCHEDULED_TASKS
        get_nwdaf_db()[NWDAF_SCHEDULED_TASKS].delete_many({})

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_subscribers()

    def test_valid_ambr_increase(self):
        from tools.feasibility_checker import FeasibilityChecker
        result = FeasibilityChecker().check(
            action="increase_ambr",
            target_slice="streaming",
            new_dl_ambr=240_000_000,   # 240 Mbps (was 200, +20%)
            new_ul_ambr=120_000_000,
        )
        self.assertTrue(result["allowed"], msg=result.get("reason"))
        print(f"  ✓ Valid increase allowed: {result['reason']}")

    def test_exceeds_max_ambr(self):
        from tools.feasibility_checker import FeasibilityChecker
        result = FeasibilityChecker().check(
            action="increase_ambr",
            target_slice="internet",
            new_dl_ambr=2_000_000_000,  # 2 Gbps — over the 1 Gbps limit
        )
        self.assertFalse(result["allowed"])
        print(f"  ✓ Over-limit correctly blocked: {result['reason']}")

    def test_below_min_ambr(self):
        from tools.feasibility_checker import FeasibilityChecker
        result = FeasibilityChecker().check(
            action="decrease_ambr",
            target_slice="internet",
            new_dl_ambr=500,  # 500 bps — below 1 Mbps floor
        )
        self.assertFalse(result["allowed"])
        print(f"  ✓ Under-floor correctly blocked: {result['reason']}")

    def test_unknown_slice(self):
        from tools.feasibility_checker import FeasibilityChecker
        result = FeasibilityChecker().check(
            action="apply_policy",
            target_slice="nonexistent_slice_xyz",
            new_dl_ambr=100_000_000,
            new_ul_ambr=50_000_000,
        )
        self.assertFalse(result["allowed"])
        print(f"  ✓ Unknown slice blocked: {result['reason']}")

    def test_valid_imsi(self):
        from tools.feasibility_checker import FeasibilityChecker
        result = FeasibilityChecker().check(
            action="terminate_session",
            target_imsi="001010000000001",
        )
        self.assertTrue(result["allowed"])
        print(f"  ✓ Valid IMSI passed: {result['reason']}")


# ── Tool 3: PolicyManager ──────────────────────────────────────────────────────

class TestPolicyManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_test_subscribers()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_subscribers()

    def test_get_current_policy(self):
        from tools.policy_manager import PolicyManager
        result = PolicyManager().get_current_policy("streaming")
        self.assertIn("subscribers", result)
        self.assertGreater(result["count"], 0)
        sub = result["subscribers"][0]
        print(f"  ✓ Current streaming AMBR: DL={sub['dl_ambr']} Mbps UL={sub['ul_ambr']} Mbps")

    def test_apply_ambr_increase(self):
        from tools.policy_manager import PolicyManager
        result = PolicyManager().apply_policy(
            target_slice="streaming",
            new_dl_ambr=240_000_000,  # 240 Mbps
            new_ul_ambr=120_000_000,
            reason="Test +20% AMBR increase",
        )
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertGreater(len(result["affected_imsis"]), 0)
        print(f"  ✓ Policy applied to {len(result['affected_imsis'])} subscribers")

    def test_apply_revert(self):
        from tools.policy_manager import PolicyManager
        pm = PolicyManager()
        # Apply
        pm.apply_policy("streaming", 240_000_000, 120_000_000, reason="Test apply")
        # Revert
        result = pm.apply_policy("streaming", 200_000_000, 100_000_000, reason="Test revert")
        self.assertTrue(result["success"])
        # Verify
        current = pm.get_current_policy("streaming")
        sub = current["subscribers"][0]
        self.assertEqual(sub["dl_ambr"], 200)  # stored as Mbps
        print(f"  ✓ Policy reverted successfully: DL={sub['dl_ambr']} Mbps")


# ── Tool 4: SessionManager ────────────────────────────────────────────────────

class TestSessionManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_test_subscribers()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_subscribers()

    def test_list_all_sessions(self):
        from tools.session_manager import SessionManager
        result = SessionManager().list_sessions()
        self.assertIn("sessions", result)
        self.assertGreater(result["session_count"], 0)
        print(f"  ✓ Listed {result['session_count']} sessions")

    def test_list_filtered_sessions(self):
        from tools.session_manager import SessionManager
        result = SessionManager().list_sessions(dnn_filter="streaming")
        self.assertIn("sessions", result)
        for sess in result["sessions"]:
            self.assertEqual(sess["dnn"], "streaming")
        print(f"  ✓ Filtered streaming sessions: {result['session_count']}")

    def test_get_session(self):
        from tools.session_manager import SessionManager
        result = SessionManager().get_session("001010000000001")
        self.assertIn("sessions", result)
        self.assertGreater(result["count"], 0)
        print(f"  ✓ Session for 001010000000001: {result}")

    def test_validate_valid_qos(self):
        from tools.session_manager import SessionManager
        result = SessionManager().validate_qos_change(
            imsi="001010000000001",
            dnn="internet",
            new_qos_index=5,
        )
        self.assertTrue(result["allowed"])
        print(f"  ✓ Valid QoS change: {result['reason']}")

    def test_validate_invalid_qos(self):
        from tools.session_manager import SessionManager
        result = SessionManager().validate_qos_change(
            imsi="001010000000001",
            dnn="internet",
            new_qos_index=99,  # invalid
        )
        self.assertFalse(result["allowed"])
        print(f"  ✓ Invalid QoS blocked: {result['reason']}")

    def test_modify_qos(self):
        from tools.session_manager import SessionManager
        result = SessionManager().modify_session_qos(
            imsi="001010000000001",
            dnn="internet",
            new_qos_index=7,
        )
        self.assertTrue(result["success"])
        print(f"  ✓ QoS modified: {result['message']}")


# ── Tool 5: MonitoringManager ──────────────────────────────────────────────────

class TestMonitoringManager(unittest.TestCase):
    def test_schedule_policy_change(self):
        from tools.monitoring_manager import MonitoringManager
        result = MonitoringManager().schedule_policy_change(
            slice_name="streaming",
            action="increase_ambr",
            delta_pct=20.0,
            start_time="16:27",
            end_time="16:30",
            days=["MON", "TUE", "WED", "THU", "FRI"],
        )
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertIsNotNone(result["job_id_apply"])
        self.assertIsNotNone(result["job_id_revert"])
        print(f"  ✓ Scheduled: apply={result['job_id_apply']} revert={result['job_id_revert']}")

    def test_list_schedules(self):
        from tools.monitoring_manager import MonitoringManager
        MonitoringManager().schedule_policy_change(
            slice_name="internet", action="increase_ambr", delta_pct=10.0,
            start_time="09:00", end_time="09:30", days=["MON"],
        )
        result = MonitoringManager().list_schedules()
        self.assertIn("schedules", result)
        self.assertGreater(result["count"], 0)
        print(f"  ✓ Active schedules: {result['count']}")

    def test_parse_12h_time(self):
        from tools.monitoring_manager import _parse_time
        h, m = _parse_time("4:27 PM")
        self.assertEqual(h, 16)
        self.assertEqual(m, 27)
        h2, m2 = _parse_time("09:00")
        self.assertEqual(h2, 9)
        print(f"  ✓ Time parsing: '4:27 PM' → {h}:{m:02d}, '09:00' → {h2}:{m2:02d}")

    def test_days_to_cron(self):
        from tools.monitoring_manager import _days_to_cron
        expr = _days_to_cron(["MON", "WED", "FRI"])
        self.assertIn("0", expr)
        self.assertIn("4", expr)
        print(f"  ✓ Days → cron: ['MON','WED','FRI'] → '{expr}'")


# ── MCP dispatcher ─────────────────────────────────────────────────────────────

class TestMCPDispatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_test_metrics(50)
        seed_test_subscribers()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_subscribers()

    def test_list_available_tools(self):
        from mcp_server.server import _dispatch
        result = _dispatch("list_available_tools", {})
        self.assertIn("tools", result)
        names = [t["name"] for t in result["tools"]]
        self.assertIn("kpi_analyzer",       names)
        self.assertIn("feasibility_checker", names)
        self.assertIn("policy_manager",     names)
        self.assertIn("session_manager",    names)
        self.assertIn("monitoring_manager", names)
        print(f"  ✓ MCP tools advertised: {names}")

    def test_kpi_via_mcp(self):
        from mcp_server.server import _dispatch
        result = _dispatch("kpi_analyzer", {"metric": "active_ue_count", "run_ml": False})
        self.assertNotIn("error", result)
        print(f"  ✓ kpi_analyzer via MCP: count={result['stats']['count']}")

    def test_feasibility_via_mcp(self):
        from mcp_server.server import _dispatch
        result = _dispatch("feasibility_checker", {
            "action": "increase_ambr",
            "target_slice": "streaming",
            "new_dl_ambr": 240_000_000,
        })
        self.assertIn("allowed", result)
        print(f"  ✓ feasibility_checker via MCP: allowed={result['allowed']}")

    def test_unknown_tool(self):
        from mcp_server.server import _dispatch
        result = _dispatch("nonexistent_tool", {})
        self.assertIn("error", result)
        print(f"  ✓ Unknown tool error: {result['error']}")


# ── entry-point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("NWDAF PALA — Tool Test Suite")
    print("=" * 60 + "\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestKPIAnalyzer,
        TestFeasibilityChecker,
        TestPolicyManager,
        TestSessionManager,
        TestMonitoringManager,
        TestMCPDispatcher,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅  All tests passed!")
    else:
        print(f"❌  {len(result.failures)} failure(s), {len(result.errors)} error(s)")
    print("=" * 60)
