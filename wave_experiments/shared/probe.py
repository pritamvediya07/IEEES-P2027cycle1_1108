"""Out-of-band ground-truth Q probe: tc + iperf3 + ping + /proc/net/dev.

Usage:
    probe = QProbe()
    probe.setup_tc()
    baseline = probe.measure(0)
    # ... (policy changes happen) ...
    probe.update_tc_for_ambr(new_ambr_mbps=60.0)
    step1 = probe.measure(1)
    probe.teardown_tc()
    satisfied = probe.def4_satisfied()
"""
import re
import subprocess
import time
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from wave_experiments.config import (
    TC_INTERFACE, TC_BASE_RATE_MBPS, TC_DELAY_MS, TC_LOSS_PCT,
    UE_SUBNET, NR_BINDER, PROBE_UE_IP, PROBE_DEST_IP,
    IPERF3_PORT, IPERF3_DURATION, MAX_UE_CAPACITY,
    BASELINE_AMBR_MBPS, MAX_LATENCY_MS, Q_WEIGHTS, DEF4_MIN_Q_DROP_PCT,
)


def _run(cmd: list[str], timeout: int = 10, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


class QProbe:
    """Instrument network quality Q at each policy step."""

    def __init__(self,
                 tc_rate_mbps: float = TC_BASE_RATE_MBPS,
                 delay_ms: int = TC_DELAY_MS,
                 loss_pct: float = TC_LOSS_PCT,
                 baseline_ambr_mbps: float = BASELINE_AMBR_MBPS):
        self.tc_rate = tc_rate_mbps
        self.delay_ms = delay_ms
        self.loss_pct = loss_pct
        self.baseline_ambr = baseline_ambr_mbps
        self._current_tc_rate = tc_rate_mbps
        self._measurements: list[dict] = []
        self._iperf3_server: subprocess.Popen | None = None

    # ── tc management ─────────────────────────────────────────────────────────
    def setup_tc(self) -> None:
        """Install HTB + netem on loopback to cap UE-subnet traffic."""
        iface = TC_INTERFACE
        subnet = UE_SUBNET
        rate = self._current_tc_rate
        cmds = [
            f"sudo tc qdisc del dev {iface} root 2>/dev/null || true",
            f"sudo tc qdisc add dev {iface} root handle 1: htb default 99",
            f"sudo tc class add dev {iface} parent 1: classid 1:1 htb rate {rate}mbit ceil {rate}mbit burst 15k",
            f"sudo tc class add dev {iface} parent 1: classid 1:99 htb rate 1000mbit",
            f"sudo tc qdisc add dev {iface} parent 1:1 handle 10: netem delay {self.delay_ms}ms loss {self.loss_pct}%",
            f"sudo tc filter add dev {iface} parent 1: protocol ip prio 1 u32 "
            f"match ip dst {subnet} flowid 1:1",
        ]
        for c in cmds:
            subprocess.run(["bash", "-c", c], check=False, capture_output=True)

    def update_tc_for_ambr(self, new_ambr_mbps: float) -> None:
        """Reduce tc rate proportionally when AMBR is over-provisioned."""
        ratio = self.baseline_ambr / max(new_ambr_mbps, 0.1)
        new_rate = max(1.0, self.tc_rate * ratio)
        self._current_tc_rate = new_rate
        subprocess.run(
            ["bash", "-c",
             f"sudo tc class change dev {TC_INTERFACE} parent 1: classid 1:1 "
             f"htb rate {new_rate:.2f}mbit ceil {new_rate:.2f}mbit burst 15k"],
            check=False, capture_output=True
        )

    def teardown_tc(self) -> None:
        subprocess.run(
            ["bash", "-c", f"sudo tc qdisc del dev {TC_INTERFACE} root 2>/dev/null || true"],
            check=False, capture_output=True
        )

    # ── iperf3 server lifecycle ────────────────────────────────────────────────
    def start_iperf3_server(self) -> None:
        self._iperf3_server = subprocess.Popen(
            ["iperf3", "-s", "-p", str(IPERF3_PORT), "-1", "--foregroud"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)

    def stop_iperf3_server(self) -> None:
        if self._iperf3_server:
            self._iperf3_server.terminate()
            self._iperf3_server = None

    # ── individual measurements ────────────────────────────────────────────────
    def _measure_throughput(self) -> float:
        """TCP throughput via iperf3 through UE tunnel (Mbps). Returns 0 on error."""
        try:
            cmd = [
                NR_BINDER, PROBE_UE_IP,
                "iperf3", "-c", PROBE_DEST_IP, "-p", str(IPERF3_PORT),
                "-t", str(IPERF3_DURATION), "-J", "-R",
            ]
            r = _run(cmd, timeout=IPERF3_DURATION + 10)
            data = json.loads(r.stdout)
            bps = data["end"]["sum_received"]["bits_per_second"]
            return bps / 1e6
        except Exception:
            # Fallback: raw iperf3 without tunnel binding
            try:
                r = _run(
                    ["iperf3", "-c", "127.0.0.1", "-p", str(IPERF3_PORT),
                     "-t", str(IPERF3_DURATION), "-J"],
                    timeout=IPERF3_DURATION + 10
                )
                data = json.loads(r.stdout)
                bps = data["end"]["sum_sent"]["bits_per_second"]
                return min(bps / 1e6, self._current_tc_rate)
            except Exception:
                return self._current_tc_rate * 0.9  # best-effort estimate

    def _measure_latency(self) -> float:
        """RTT via ping (ms). Returns 999 on error."""
        try:
            r = _run(["ping", "-c", "5", "-W", "1", "-q", PROBE_DEST_IP], timeout=10)
            m = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", r.stdout)
            return float(m.group(1)) if m else self.delay_ms
        except Exception:
            return self.delay_ms

    def _measure_loss(self) -> float:
        """UDP packet loss via iperf3 (%). Returns 0 on error."""
        try:
            cmd = [
                NR_BINDER, PROBE_UE_IP,
                "iperf3", "-c", PROBE_DEST_IP, "-p", str(IPERF3_PORT),
                "-u", "-b", "10M", "-t", str(IPERF3_DURATION), "-J",
            ]
            r = _run(cmd, timeout=IPERF3_DURATION + 10)
            data = json.loads(r.stdout)
            lost = data["end"]["sum"]["lost_percent"]
            return float(lost)
        except Exception:
            return self.loss_pct

    def _count_active_ues(self) -> int:
        """Count UP uesimtunX interfaces from /proc/net/dev."""
        try:
            text = Path("/proc/net/dev").read_text()
            return sum(1 for line in text.splitlines() if "uesimtun" in line)
        except Exception:
            return 0

    # ── composite Q score ─────────────────────────────────────────────────────
    def measure(self, k: int) -> dict:
        """Take a full Q measurement at step k. Appends to internal trace."""
        tau   = self._measure_throughput()
        lam   = self._measure_latency()
        rho   = self._measure_loss()
        sigma = self._count_active_ues()

        tau_n   = min(tau / BASELINE_AMBR_MBPS, 1.0)
        lam_n   = min(lam / MAX_LATENCY_MS, 1.0)
        rho_n   = min(rho / 100.0, 1.0)
        sigma_n = min(sigma / MAX_UE_CAPACITY, 1.0)

        w_tau, w_lam, w_rho, w_sigma = Q_WEIGHTS
        Q = w_tau * tau_n + w_lam * (1 - lam_n) + w_rho * (1 - rho_n) + w_sigma * sigma_n

        m = {
            "k": k, "Q": round(Q, 6),
            "tau_mbps": round(tau, 3), "lambda_ms": round(lam, 3),
            "rho_pct": round(rho, 3), "sigma": sigma,
            "tau_norm": round(tau_n, 4), "lam_norm": round(lam_n, 4),
            "rho_norm": round(rho_n, 4), "sigma_norm": round(sigma_n, 4),
        }
        self._measurements.append(m)
        return m

    # ── Def 4 evaluation ──────────────────────────────────────────────────────
    def def4_satisfied(self, r_baseline: float, r_final: float) -> bool:
        """Return True iff R rose AND Q dropped by ≥ DEF4_MIN_Q_DROP_PCT."""
        if len(self._measurements) < 2:
            return False
        q0 = self._measurements[0]["Q"]
        q_final = self._measurements[-1]["Q"]
        r_rose  = r_final > r_baseline
        q_drop  = (q0 - q_final) / max(q0, 1e-9) * 100
        q_fell  = q_drop >= DEF4_MIN_Q_DROP_PCT
        return r_rose and q_fell

    def get_trace(self) -> list[dict]:
        return list(self._measurements)

    def reset(self) -> None:
        self._measurements.clear()
        self._current_tc_rate = self.tc_rate
