#!/usr/bin/env python3
"""Per-UE AMBR enforcement — declared stand-in for the TS 29.244 QER.

WHY THIS EXISTS
---------------
Gate E0.1 measured that Open5GS does not police Session-AMBR on the data plane:
with the subscriber's AMBR set to 5 Mbps a single UE still achieved ~54 Mbps.
The value is provisioned and signalled, but no QER polices it at the UPF.

The spec (§3, E0.1) prescribes the remedy: install an explicit enforcement
point and DECLARE it in the paper, worded as

    "AMBR is enforced at the UPF by a per-UE HTB class on the tunnel interface,
     configured from the subscriber's Session-AMBR. Open5GS does not implement
     QER-based rate enforcement, so this stands in for the QER an operator UPF
     applies under TS 29.244. The enforcement point is per-UE and is the only
     place the agent's policy value acts; the shared bottleneck is at the air
     interface and is independent of it."

THE CONSTRAINT THAT MAKES THE SCIENCE VALID (spec §0)
-----------------------------------------------------
The previous testbed was circular because the thing that enforced AMBR and the
thing that created the bottleneck were the same knob: raising AMBR lowered link
capacity, so "AMBR degrades quality" was imposed, not observed.

Here they are strictly separated:

  * ENFORCEMENT  = per-UE HTB class ceiling on ogstun, set from that UE's AMBR.
                   Varies with agent action. This is the policy variable.
  * BOTTLENECK   = the srsRAN MAC scheduler over a finite PRB pool (C ~= 52 Mbps
                   measured). FIXED for the whole campaign. Nothing here touches it.

ROOT_RATE is deliberately far above C so the HTB root can never bind. If it
ever did, this module would itself become the bottleneck and reintroduce the
exact defect we are removing. `assert_not_bottleneck()` checks that.

Usage:
    from srsran.ambr_enforcer import AmbrEnforcer
    e = AmbrEnforcer(); e.setup()
    e.set_ue_ambr("10.45.0.17", 20)     # cap this UE at 20 Mbps downlink
    e.teardown()
"""
from __future__ import annotations

import subprocess
import sys

IFACE = "ogstun"          # UPF-side tunnel: egress here == downlink to UEs
ROOT_RATE_MBIT = 10000    # 10 Gbps — ~190x the measured C; must never bind
DEFAULT_CLASS = 9999


def _tc(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-n", "/usr/sbin/tc", *args],
                          capture_output=True, text=True, check=check)


class AmbrEnforcer:
    """Per-UE downlink rate enforcement via HTB classes on the UPF tunnel."""

    def __init__(self, iface: str = IFACE, root_rate_mbit: int = ROOT_RATE_MBIT):
        self.iface = iface
        self.root_rate = root_rate_mbit
        self._classes: dict[str, int] = {}      # ue_ip -> classid minor

    # ── lifecycle ──────────────────────────────────────────────────────────
    def setup(self) -> None:
        """Install the HTB root. Idempotent."""
        _tc("qdisc", "del", "dev", self.iface, "root")
        _tc("qdisc", "add", "dev", self.iface, "root", "handle", "1:",
            "htb", "default", str(DEFAULT_CLASS), check=True)
        # root class: enormous, so it is never the constraint
        _tc("class", "add", "dev", self.iface, "parent", "1:", "classid", "1:1",
            "htb", "rate", f"{self.root_rate}mbit", "ceil", f"{self.root_rate}mbit",
            check=True)
        # default class for anything unmatched — also unconstrained
        _tc("class", "add", "dev", self.iface, "parent", "1:1",
            "classid", f"1:{DEFAULT_CLASS}",
            "htb", "rate", f"{self.root_rate}mbit", "ceil", f"{self.root_rate}mbit")
        self._classes.clear()

    def teardown(self) -> None:
        _tc("qdisc", "del", "dev", self.iface, "root")
        self._classes.clear()

    # ── per-UE enforcement ─────────────────────────────────────────────────
    def _minor(self, ue_ip: str) -> int:
        """Stable classid minor from the UE address (last octet, offset to avoid 1)."""
        return 100 + int(ue_ip.split(".")[-1])

    def set_ue_ambr(self, ue_ip: str, mbps: float) -> bool:
        """Cap this UE's DOWNLINK at `mbps`. Creates the class on first call.

        Only this UE's ceiling changes. The root rate is never touched, so the
        shared bottleneck is unaffected — that separation is the whole point.
        """
        minor = self._minor(ue_ip)
        cid = f"1:{minor}"
        rate = f"{max(mbps, 0.1):.3f}mbit"

        if ue_ip not in self._classes:
            r = _tc("class", "add", "dev", self.iface, "parent", "1:1", "classid", cid,
                    "htb", "rate", rate, "ceil", rate, "burst", "32k")
            if r.returncode != 0 and "exists" not in (r.stderr or ""):
                print(f"[ambr] class add failed for {ue_ip}: {r.stderr.strip()}", file=sys.stderr)
                return False
            # match on DESTINATION address: egress on ogstun is downlink to the UE
            f = _tc("filter", "add", "dev", self.iface, "parent", "1:", "protocol", "ip",
                    "prio", "1", "u32", "match", "ip", "dst", f"{ue_ip}/32", "flowid", cid)
            if f.returncode != 0:
                print(f"[ambr] filter add failed for {ue_ip}: {f.stderr.strip()}", file=sys.stderr)
                return False
            self._classes[ue_ip] = minor
        else:
            r = _tc("class", "change", "dev", self.iface, "parent", "1:1", "classid", cid,
                    "htb", "rate", rate, "ceil", rate, "burst", "32k")
            if r.returncode != 0:
                print(f"[ambr] class change failed for {ue_ip}: {r.stderr.strip()}", file=sys.stderr)
                return False
        return True

    def clear_ue(self, ue_ip: str) -> None:
        if ue_ip in self._classes:
            _tc("class", "del", "dev", self.iface, "classid", f"1:{self._classes[ue_ip]}")
            del self._classes[ue_ip]

    # ── integrity ──────────────────────────────────────────────────────────
    def assert_not_bottleneck(self, measured_C_mbps: float) -> None:
        """Fail loudly if the enforcement layer could ever be the constraint.

        If the HTB root were comparable to C, this module would shape aggregate
        capacity and the AMBR->harm link would become circular again — the exact
        defect this rebuild exists to remove.
        """
        if self.root_rate < measured_C_mbps * 10:
            raise AssertionError(
                f"HTB root {self.root_rate} Mbit is not >=10x the measured "
                f"C={measured_C_mbps} Mbps. The enforcement layer could act as a "
                f"bottleneck, which would reintroduce the circularity."
            )

    def show(self) -> str:
        return _tc("-s", "class", "show", "dev", self.iface).stdout


if __name__ == "__main__":
    e = AmbrEnforcer()
    if len(sys.argv) > 1 and sys.argv[1] == "teardown":
        e.teardown(); print("HTB removed from", IFACE)
    else:
        e.setup(); print(f"HTB installed on {IFACE}, root {ROOT_RATE_MBIT} Mbit")
        for ip, mb in [(a.split("=")[0], float(a.split("=")[1])) for a in sys.argv[1:] if "=" in a]:
            print(f"  {ip} -> {mb} Mbps :", e.set_ue_ambr(ip, mb))
        print(e.show()[:800])
