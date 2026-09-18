#!/usr/bin/env python3
"""GNU Radio multi-UE ZMQ broker for srsRAN — the official architecture.

WHY GNU RADIO AND NOT THE PURE-PYTHON BROKER
---------------------------------------------
srsRAN's ZMQ radio is REQ/REP only, so one gNB serves exactly one peer and a
broker is mandatory for n > 1. srsRAN's own documentation solves this with a
GNU Radio flowgraph, and inspecting OAIC's known-working 5-UE flowgraph
(OAIC_FIVE_UEs.grc) confirms the block set:

    6 x zeromq_req_source      connects, pulls from srsRAN's REP endpoint
    6 x zeromq_rep_sink        binds,    serves srsRAN's REQ
    1 x blocks_add_xx          uplink combiner (superposition at the antenna)
    2 x blocks_throttle        sample pacing
    N x blocks_multiply_const  per-branch gain

Our hand-written Python broker used the same topology and passed a mock test,
but never drove the real gNB: it lacked GNU Radio's sample pacing and its
protocol handling, and the gNB's transmit FSM never advanced. Rather than keep
reverse-engineering the lockstep behaviour, use the supported implementation.

TOPOLOGY (srsRAN Project docs port scheme)

    DOWNLINK   gNB tx :2000 (bind REP)
                 -> req_source connect localhost:2000
                 -> throttle
                 -> fan-out to rep_sink bind *:2100, *:2200, *:2300, ...
                 -> UE_i rx connect localhost:(2100 + 100*i)

    UPLINK     UE_i tx :(2101 + 100*i) (bind REP)
                 -> req_source connect localhost:(2101 + 100*i)
                 -> add_vcc  (sum of all UEs)
                 -> throttle
                 -> rep_sink bind *:2001
                 -> gNB rx connect localhost:2001

STARTUP ORDER MATTERS. srsRAN's docs are explicit: EPC -> gNB -> UEs -> broker
LAST. "The UE will not connect until the broker has been started." Our earlier
attempts started the broker first, which is the opposite.

Usage:
    python3 gr_broker.py --n-ue 4 --srate 23.04e6
"""
from __future__ import annotations

import argparse
import signal
import sys

try:
    from gnuradio import gr, blocks, zeromq
except ImportError:
    sys.exit("ERROR: GNU Radio not installed.\n"
             "  sudo apt install -y gnuradio gnuradio-dev python3-packaging")

GNB_TX = 2000       # gNB binds REP here  -> we req_source connect
GNB_RX = 2001       # gNB connects REQ    -> we rep_sink bind
UE_RX_BASE = 2100   # UE i connects REQ to 2100+100i  -> we rep_sink bind
UE_TX_BASE = 2101   # UE i binds REP on   2101+100i   -> we req_source connect

TIMEOUT_MS = 100
HWM = -1            # ZMQ high-water mark: -1 = default


class MultiUeBroker(gr.top_block):
    def __init__(self, n_ue: int, srate: float, gain: float = 1.0,
                 slow_down_ratio: float = 1.0):
        gr.top_block.__init__(self, "srsRAN multi-UE ZMQ broker")
        self.n_ue = n_ue
        cplx = gr.sizeof_gr_complex
        # srsRAN docs: the Throttle rate is samp_rate / slow_down_ratio. Raising the
        # ratio passes samples more slowly, giving gNB and UEs more time per sample
        # (lower CPU). Their default is 4. We start at 1 (real time) because this host
        # has 128 cores, and raise it only if late/underflow markers appear.
        thr_rate = srate / max(slow_down_ratio, 1e-9)
        self.thr_rate = thr_rate

        # ── downlink: one gNB stream fanned out to every UE ────────────────
        dl_src = zeromq.req_source(cplx, 1, f"tcp://localhost:{GNB_TX}",
                                   TIMEOUT_MS, False, HWM)
        dl_thr = blocks.throttle(cplx, thr_rate, True)
        self.connect(dl_src, dl_thr)
        for i in range(n_ue):
            port = UE_RX_BASE + 100 * i
            sink = zeromq.rep_sink(cplx, 1, f"tcp://*:{port}", TIMEOUT_MS, False, HWM)
            g = blocks.multiply_const_cc(gain)
            self.connect(dl_thr, g, sink)          # GNU Radio copies on fan-out

        # ── uplink: sum every UE, hand the sum to the gNB ──────────────────
        adder = blocks.add_vcc(1)
        for i in range(n_ue):
            port = UE_TX_BASE + 100 * i
            src = zeromq.req_source(cplx, 1, f"tcp://localhost:{port}",
                                    TIMEOUT_MS, False, HWM)
            g = blocks.multiply_const_cc(gain)
            self.connect(src, g, (adder, i))
        ul_thr = blocks.throttle(cplx, thr_rate, True)
        ul_sink = zeromq.rep_sink(cplx, 1, f"tcp://*:{GNB_RX}", TIMEOUT_MS, False, HWM)
        self.connect(adder, ul_thr, ul_sink)

    def describe(self) -> str:
        L = [f"gNB  DL src  connect localhost:{GNB_TX}",
             f"gNB  UL sink bind    *:{GNB_RX}"]
        for i in range(self.n_ue):
            L.append(f"ue{i+1} DL sink bind    *:{UE_RX_BASE + 100*i}   "
                     f"UL src connect localhost:{UE_TX_BASE + 100*i}")
        return "\n".join("  " + x for x in L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--srate", type=float, default=23.04e6)
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--slow-down-ratio", type=float, default=1.0,
                    help="srsRAN docs default is 4; throttle = srate/ratio")
    a = ap.parse_args()

    tb = MultiUeBroker(a.n_ue, a.srate, a.gain, a.slow_down_ratio)
    print(f"[gr-broker] {a.n_ue} UEs @ {a.srate/1e6:.2f} Msps  "
          f"throttle {tb.thr_rate/1e6:.2f} Msps (slow_down_ratio={a.slow_down_ratio})")
    print(tb.describe(), flush=True)

    def stop(*_):
        print("\n[gr-broker] stopping", flush=True)
        tb.stop(); tb.wait(); sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    tb.start()
    print("[gr-broker] running", flush=True)
    tb.wait()


if __name__ == "__main__":
    main()
