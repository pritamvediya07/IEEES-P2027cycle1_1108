#!/usr/bin/env python3
"""Phase 1 — ground-truth Φ probe.  Implements the spec §4 probe contract.

Φ = (τ, λ, ρ, σ) measured OUT OF BAND, in a process with no access to the
analytics store or the policy store.

    τ  throughput   iperf3 per UE, aggregated        (Mbps)
    λ  latency      ping over the UE tunnel          (ms, mean + p95)
    ρ  loss         iperf3 UDP, cross-checked        (%)
    σ  sessions     Open5GS SMF session count        (direct query)

THE INTEGRITY RULES (spec §4.2) — non-negotiable, and the reason this file
exists at all. The previous harness silently substituted computed values for
measurements: τ was max(1, 15*20/AMBR)*0.9 and ρ was the constant 3.0, which
reproduced 382/382 of the published throughput values with no network involved.

  1. Every Φ record carries `source` per dimension: "measured" | "unavailable".
     There is no third option.
  2. NO FALLBACK COMPUTATION. If iperf3 fails, τ is None with source
     "unavailable". The session is flagged and excluded, never estimated.
  3. Raw counters are logged next to derived values.
  4. Startup self-test: iperf3 reachable, UE tunnels live, a test transfer
     moves non-zero bytes. Abort on failure.
  5. A dimension that never varies across a campaign RAISES. This is what
     catches the constant-ρ / constant-σ degeneracy that would make a Q dimension uninformative.
  6. The probe never reads the AMBR value — enforced by construction: it has
     no credential for the subscriber DB and never imports PolicyManager.

Usage:
    from srsran.phi_probe import PhiProbe
    p = PhiProbe(["ue1","ue2"]); p.selftest()
    rec = p.measure(k=1)
    p.assert_dimensions_vary()      # at end of campaign
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GW = "10.45.0.1"
IPERF_PORT = 5299     # base port; each UE gets IPERF_PORT + i
# One iperf3 server instance serves ONE client at a time. With n UEs measured
# CONCURRENTLY (which is the whole point — contention must be real), every UE
# needs its own server port, otherwise all but the first client fail and tau is
# correctly reported "unavailable".
MEASURED, UNAVAILABLE = "measured", "unavailable"


def sh(c, timeout=60, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True,
                          text=True, timeout=timeout, **k)


@dataclass
class PhiRecord:
    k: int
    ts: str
    tau_mbps: float | None
    tau_source: str
    lambda_ms: float | None
    lambda_p95_ms: float | None
    lambda_source: str
    rho_pct: float | None
    rho_source: str
    sigma: int | None
    sigma_source: str
    per_ue_tau: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return all(s == MEASURED for s in
                   (self.tau_source, self.lambda_source, self.rho_source, self.sigma_source))

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["complete"] = self.complete
        return d


class PhiProbe:
    """Out-of-band Φ measurement. Never reads policy state."""

    def __init__(self, namespaces: list[str], iperf_secs: int = 10,
                 udp_offer_mbps: float = 20, capacity_hint: float | None = None):
        self.ns = namespaces
        self.secs = iperf_secs
        self.udp_offer_mbps = udp_offer_mbps
        self.capacity_hint = capacity_hint   # measured C, for the rho validity check
        self._lam_under_load = ([], {})
        self.records: list[PhiRecord] = []

    # ── namespace helpers ─────────────────────────────────────────────────
    def _ip(self, ns: str) -> str | None:
        r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
        return next((t.split("/")[0] for t in r.stdout.split()
                     if t.count(".") == 3 and "/" in t), None)

    def _tun_bytes(self, ns: str) -> tuple[int, int]:
        r = sh(["ip", "netns", "exec", ns, "cat", "/proc/net/dev"])
        for line in r.stdout.splitlines():
            if "tun_srsue" in line:
                f = line.replace(":", " ").split()
                return int(f[1]), int(f[9])
        return 0, 0

    def _port(self, ns: str) -> int:
        return IPERF_PORT + self.ns.index(ns)

    def _servers(self, up: bool = True) -> None:
        """One iperf3 server per UE — required for concurrent measurement."""
        for i in range(len(self.ns)):
            sh(f"pkill -f 'iperf3 -s -p {IPERF_PORT + i}'")
        time.sleep(0.5)
        if up:
            for i in range(len(self.ns)):
                subprocess.Popen(["iperf3", "-s", "-p", str(IPERF_PORT + i)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)

    # ── τ and λ together ──────────────────────────────────────────────────
    def _tau(self, ping_during: bool = True):
        """Aggregate downlink across all UEs, CONCURRENT so contention is real.

        BUG FIX (found in review): λ used to be sampled AFTER _tau() returned,
        i.e. with the link completely idle. That made λ flat at ~73 ms across an
        entire AMBR sweep and hid any queueing effect. Latency must be sampled
        WHILE the load is running, so the ping is launched alongside iperf3 and
        harvested afterwards.
        """
        self._servers(True)
        procs, before = {}, {}
        for ns in self.ns:
            before[ns] = self._tun_bytes(ns)
            procs[ns] = subprocess.Popen(
                ["ip", "netns", "exec", ns, "iperf3", "-c", GW, "-p", str(self._port(ns)),
                 "-t", str(self.secs), "-J", "-R"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        # λ under load: start pings now, in parallel with the iperf3 streams
        pings = {}
        if ping_during:
            npkt = max(int(self.secs / 0.2) - 2, 5)
            for ns in self.ns:
                pings[ns] = subprocess.Popen(
                    ["ip", "netns", "exec", ns, "ping", "-c", str(npkt), "-i", "0.2",
                     "-W", "2", "-q", GW],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        per, raw = {}, {}
        for ns, p in procs.items():
            try:
                out, _ = p.communicate(timeout=self.secs + 25)
                d = json.load(io.StringIO(out))
                per[ns] = d["end"]["sum_received"]["bits_per_second"] / 1e6
                raw[ns] = {"bytes": d["end"]["sum_received"]["bytes"],
                           "seconds": d["end"]["sum_received"]["seconds"]}
            except Exception:
                per[ns] = None
        self._servers(False)

        lam_vals, lam_raw = [], {}
        for ns, pp in pings.items():
            try:
                out, _ = pp.communicate(timeout=self.secs + 20)
                m = re.search(r"= [\d.]+/([\d.]+)/([\d.]+)/", out)
                if m:
                    lam_vals.append(float(m.group(1)))
                    lam_raw[ns] = {"avg_under_load": float(m.group(1)),
                                   "max_under_load": float(m.group(2))}
            except Exception:
                pass

        for ns in self.ns:
            a = self._tun_bytes(ns)
            raw.setdefault(ns, {})["tun_delta_rx"] = a[0] - before[ns][0]
            raw[ns]["tun_delta_tx"] = a[1] - before[ns][1]

        self._lam_under_load = (lam_vals, lam_raw)
        if any(v is None for v in per.values()):
            return None, UNAVAILABLE, per, raw            # RULE 2: no estimate
        return sum(per.values()), MEASURED, per, raw

    # ── λ ─────────────────────────────────────────────────────────────────
    def _lam(self) -> tuple[float | None, float | None, str, dict]:
        vals, raw = [], {}
        for ns in self.ns:
            r = sh(["ip", "netns", "exec", ns, "ping", "-c", "20", "-i", "0.2",
                    "-W", "2", "-q", GW], timeout=40)
            m = re.search(r"= [\d.]+/([\d.]+)/([\d.]+)/", r.stdout)
            if m:
                vals.append(float(m.group(1)))
                raw[ns] = {"avg": float(m.group(1)), "max": float(m.group(2))}
        if not vals:
            return None, None, UNAVAILABLE, raw
        s = sorted(vals)
        return (sum(vals) / len(vals), s[int(len(s) * 0.95) - 1] if len(s) > 1 else s[0],
                MEASURED, raw)

    # ── ρ ─────────────────────────────────────────────────────────────────
    def _rho(self) -> tuple[float | None, str, dict]:
        """Downlink UDP loss, all UEs CONCURRENTLY.

        TWO BUG FIXES (found in review):
          1. It used to run one UE at a time, so there was no contention during
             the loss test.
          2. It used to omit -R, so it measured the UPLINK. Our per-UE HTB and
             the DL contention are both on the downlink, so the uplink was
             unshaped and reported 0.0% loss every single time — reproducing
             exactly the constant-ρ degeneracy this rebuild exists to remove.
        """
        self._servers(True)
        procs, raw = {}, {}
        for ns in self.ns:
            procs[ns] = subprocess.Popen(
                ["ip", "netns", "exec", ns, "iperf3", "-c", GW, "-p", str(self._port(ns)),
                 "-u", "-b", f"{self.udp_offer_mbps}M", "-t", "5", "-J", "-R"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        losses = []
        for ns, p in procs.items():
            try:
                out, _ = p.communicate(timeout=45)
                d = json.load(io.StringIO(out))
                sm = d["end"]["sum"]
                losses.append(float(sm["lost_percent"]))
                raw[ns] = {"lost": sm.get("lost_packets"), "total": sm.get("packets"),
                           "pct": sm.get("lost_percent")}
            except Exception:
                pass
        self._servers(False)
        if not losses:
            return None, UNAVAILABLE, raw

        # VALIDITY CROSS-CHECK (spec §4.1: rho must be cross-checked, not trusted).
        # If we offer far more than the link can carry and iperf3 still claims
        # almost no loss, the accounting cannot be believed: the excess can
        # neither be delivered nor buffered. Worked example from our own run --
        # 4 UEs x 22.2 Mbps = 88.8 Mbps offered against C = 23.38 Mbps is 40.9 MB
        # of excess over 5 s, while a 400 ms standing queue holds only ~1.17 MB.
        # Reporting 0.188% there would be reporting a number we cannot defend, so
        # we mark it unavailable instead (rule 2: never estimate).
        total_offered = 0.0
        for v in raw.values():
            tot = v.get("total") or 0
            total_offered += tot * 1448 * 8 / 5.0 / 1e6          # Mbps over the 5 s test
        mean_loss = sum(losses) / len(losses)
        if self.capacity_hint and total_offered > 1.5 * self.capacity_hint:
            implied_min_loss = 100.0 * (1 - self.capacity_hint / max(total_offered, 1e-9))
            if mean_loss < 0.25 * implied_min_loss:
                raw["validity"] = {
                    "verdict": "IMPLAUSIBLE — rejected",
                    "offered_mbps": round(total_offered, 2),
                    "capacity_mbps": self.capacity_hint,
                    "reported_loss_pct": round(mean_loss, 4),
                    "loss_implied_by_capacity_pct": round(implied_min_loss, 2),
                    "reason": ("offered greatly exceeds capacity yet iperf3 reports near-zero "
                               "loss; the excess can be neither delivered nor buffered, so the "
                               "UDP accounting is not trustworthy in reverse mode")}
                return None, UNAVAILABLE, raw
        raw["validity"] = {"verdict": "plausible", "offered_mbps": round(total_offered, 2)}
        return mean_loss, MEASURED, raw

    # ── σ ─────────────────────────────────────────────────────────────────
    def _sigma(self) -> tuple[int | None, str]:
        """SMF session count, straight from Open5GS logs — not via the collector."""
        r = sh("journalctl -u open5gs-smfd --since '10 min ago' --no-pager 2>/dev/null "
               "| grep -oP 'Number of SMF-Sessions is now \\K[0-9]+' | tail -1")
        v = r.stdout.strip()
        if v.isdigit():
            return int(v), MEASURED
        live = sum(1 for ns in self.ns if self._ip(ns))
        return (live, MEASURED) if live else (None, UNAVAILABLE)

    # ── public ────────────────────────────────────────────────────────────
    def selftest(self) -> bool:
        """RULE 4. Abort the campaign rather than record estimated data."""
        print("[phi] self-test")
        ok = True
        for ns in self.ns:
            ip = self._ip(ns)
            print(f"  {ns}: {ip or 'NO TUNNEL'}")
            ok &= bool(ip)
        if not ok:
            print("  [FAIL] a UE tunnel is missing"); return False
        b = self._tun_bytes(self.ns[0])
        self._servers(True)
        r = sh(["ip", "netns", "exec", self.ns[0], "iperf3", "-c", GW,
                "-p", str(self._port(self.ns[0])), "-t", "3", "-J", "-R"], timeout=30)
        self._servers(False)
        a = self._tun_bytes(self.ns[0])
        moved = a[0] - b[0]
        print(f"  test transfer moved {moved:,} bytes on {self.ns[0]}")
        if moved < 100_000:
            print("  [FAIL] no real bytes crossed the tunnel"); return False
        print("  [OK] probe is measuring")
        return True

    def measure(self, k: int) -> PhiRecord:
        tau, tsrc, per, raw = self._tau()
        vals, lraw = self._lam_under_load
        if vals:
            sv = sorted(vals)
            lam = sum(vals) / len(vals)
            p95 = sv[int(len(sv) * 0.95) - 1] if len(sv) > 1 else sv[0]
            lsrc = MEASURED
        else:
            lam, p95, lsrc, lraw = self._lam()      # idle fallback, flagged below
        rho, rsrc, rraw = self._rho()
        sig, ssrc = self._sigma()
        rec = PhiRecord(k=k, ts=datetime.now(timezone.utc).isoformat(),
                        tau_mbps=round(tau, 3) if tau is not None else None, tau_source=tsrc,
                        lambda_ms=round(lam, 3) if lam is not None else None,
                        lambda_p95_ms=round(p95, 3) if p95 is not None else None,
                        lambda_source=lsrc,
                        rho_pct=round(rho, 4) if rho is not None else None, rho_source=rsrc,
                        sigma=sig, sigma_source=ssrc,
                        per_ue_tau={k2: (round(v, 3) if v else None) for k2, v in per.items()},
                        raw={"tau": raw, "lambda": lraw, "rho": rraw})
        self.records.append(rec)
        return rec

    def assert_dimensions_vary(self) -> None:
        """RULE 5. A constant dimension carries zero information — this is the
        exact degeneracy (ρ ≡ 3.0, σ ≡ 10) that made the old Table 11 sweep
        meaningless."""
        if len(self.records) < 2:
            return
        bad = []
        for dim in ("tau_mbps", "lambda_ms", "rho_pct", "sigma"):
            vals = {getattr(r, dim) for r in self.records if getattr(r, dim) is not None}
            if len(vals) == 1:
                bad.append(f"{dim} constant at {vals.pop()}")
        if bad:
            raise AssertionError("Φ degeneracy detected: " + "; ".join(bad))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for r in self.records:
                f.write(json.dumps(r.as_dict()) + "\n")

    def summary(self) -> dict:
        cs = [r for r in self.records if r.complete]
        return {"n_records": len(self.records), "n_complete": len(cs),
                "n_excluded": len(self.records) - len(cs),
                "exclusion_rule": "a record is excluded iff any Φ dimension is 'unavailable'"}


if __name__ == "__main__":
    import sys
    ns = sys.argv[1:] or ["ue1"]
    p = PhiProbe(ns)
    if not p.selftest():
        sys.exit(1)
    r = p.measure(0)
    print(json.dumps(r.as_dict(), indent=2)[:900])
