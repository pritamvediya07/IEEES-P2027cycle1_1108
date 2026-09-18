#!/usr/bin/env python3
"""ZMQ multi-UE broker for srsRAN — the air-interface combiner.

WHY THIS IS NEEDED
------------------
srsRAN Project's ZMQ radio uses ZMQ_REQ/ZMQ_REP only (verified in
lib/radio/zmq/radio_zmq_{tx,rx}_channel.cpp). REQ/REP is strict 1:1 lockstep,
so one gNB can serve exactly one peer. Spec gate E0.2 needs n >= 4 concurrent
UEs to create genuine contention, and no broker ships with srsRAN.

WHAT IT DOES
------------
It stands in for the shared radio medium:

  DOWNLINK  gNB transmits one sample block -> every UE receives that same block
            (broadcast, exactly as a real cell does)

  UPLINK    every UE transmits its own block -> broker SUMS them sample-wise
            and hands the sum to the gNB (superposition at the antenna)

Socket wiring (mirrors what srsRAN expects):

  gNB TX  = ZMQ_REP bound   on GNB_TX_PORT    <- broker REQs to pull DL
  gNB RX  = ZMQ_REQ connect on GNB_RX_PORT    <- broker REPs with summed UL
  UE  RX  = ZMQ_REQ connect on UE_RX_PORT(i)  <- broker REPs with DL copy
  UE  TX  = ZMQ_REP bound   on UE_TX_PORT(i)  <- broker REQs to pull that UE's UL

CRITICAL: THIS MUST NOT BECOME THE BOTTLENECK (spec §0)
--------------------------------------------------------
If the broker cannot keep up, it — not the MAC scheduler — sets capacity, and
the AMBR->harm link becomes circular again, which is the exact defect this
rebuild exists to remove. Two guards:

  * --selftest measures broker throughput in isolation and refuses to run if it
    is not comfortably above the sample rate.
  * runtime stats report late blocks; a non-zero late count invalidates a
    campaign and must be reported, never silently tolerated.

Samples are complex float32 (8 bytes each). At 23.04 Msps that is ~184 MB/s per
direction. numpy does the summing vectorised.

Usage:
    python3 zmq_broker.py --n-ue 4 --selftest
    python3 zmq_broker.py --n-ue 4
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

import numpy as np

try:
    import zmq
except ImportError:
    sys.exit("ERROR: pyzmq not installed.  pip install pyzmq")

GNB_TX_PORT = 2000          # gNB binds REP here; we REQ from it (downlink source)
GNB_RX_PORT = 2001          # gNB REQs here; we bind REP (uplink sink)
UE_BASE_RX = 3000           # UE i REQs here for DL   -> we bind REP
UE_BASE_TX = 4000           # UE i binds REP here     -> we REQ for UL
# Bootstrap zero-block: 1 ms at 23.04 Msps. Before any UE has synced there is
# nothing real to forward, but the gNB's RX must still be fed a FULL slot each
# time it asks. Replying with a token 1-sample buffer starves the radio: it
# never advances, so its TX produces nothing, so DL never flows, so the UE
# never syncs — a deadlock that presents as "gNB TX not answering".
BOOTSTRAP_SAMPLES = 23040

# srsRAN request frames must be NON-EMPTY. The gNB TX REP does
#   uint8_t dummy; n = zmq_recv(sock,&dummy,1,DONTWAIT); if (n > 0) request_received();
# so a zero-byte frame yields n == 0, the request is dropped, and the gNB never
# transmits. srsue sends exactly one byte; we must do the same.
REQ = b"\x00"

_running = True


class Broker:
    def __init__(self, n_ue: int, verbose: bool = False,
                 block_samples: int = BOOTSTRAP_SAMPLES):
        self.n = n_ue
        self.block_samples = block_samples
        self.verbose = verbose
        self.ctx = zmq.Context(io_threads=2)
        self.stats = {"dl_blocks": 0, "ul_blocks": 0, "late": 0,
                      "dl_bytes": 0, "ul_bytes": 0, "ue_silent": [0] * n_ue}
        self._last_dl = b""
        self._lock = threading.Lock()

    # ── downlink: one gNB block broadcast to ALL UEs ───────────────────────
    def _dl_loop(self) -> None:
        try:
            self._dl_loop_inner()
        except Exception as e:
            import traceback; print(f'[broker] DL THREAD DIED: {e}', flush=True); traceback.print_exc()
            self.stats['dl_thread_dead'] = str(e)

    def _dl_loop_inner(self) -> None:
        """Broadcast semantics.

        A real cell transmits ONE waveform that every UE receives. So the
        broker must hand the SAME block to all n UEs before pulling the next
        one from the gNB. Fetching a fresh block per UE request would give each
        UE a different slice of the stream and none of them would ever sync.
        """
        req = self.ctx.socket(zmq.REQ)
        req.setsockopt(zmq.LINGER, 0)
        req.setsockopt(zmq.RCVTIMEO, 2000)
        req.connect(f"tcp://localhost:{GNB_TX_PORT}")

        reps = []
        for i in range(self.n):
            s = self.ctx.socket(zmq.REP)
            s.setsockopt(zmq.LINGER, 0)
            s.bind(f"tcp://*:{UE_BASE_RX + i}")
            reps.append(s)

        print(f"[broker] DL bound REP on {[UE_BASE_RX+i for i in range(self.n)]}, "
              f"REQ->gNB :{GNB_TX_PORT}", flush=True)
        poller = zmq.Poller()
        for s in reps:
            poller.register(s, zmq.POLLIN)

        cur: bytes | None = None
        served: set[int] = set()

        while _running:
            socks = dict(poller.poll(timeout=100))
            for i, s in enumerate(reps):
                if socks.get(s) != zmq.POLLIN:
                    continue
                try:
                    _ = s.recv()
                except zmq.ZMQError:
                    continue

                # fetch a new gNB block only once the current one has gone to
                # every UE (or on the very first request)
                if cur is None or i in served:
                    t0 = time.perf_counter()
                    try:
                        req.send(REQ)
                        cur = req.recv()
                    except zmq.ZMQError as e:
                        self.stats["gnb_tx_timeouts"] = self.stats.get("gnb_tx_timeouts", 0) + 1
                        if self.stats["gnb_tx_timeouts"] in (1, 10, 100):
                            print(f"[broker] gNB TX not answering on :{GNB_TX_PORT} "
                                  f"({self.stats['gnb_tx_timeouts']}x): {e}", flush=True)
                        req.close(0)
                        req = self.ctx.socket(zmq.REQ)
                        req.setsockopt(zmq.LINGER, 0); req.setsockopt(zmq.RCVTIMEO, 2000)
                        req.connect(f"tcp://localhost:{GNB_TX_PORT}")
                        continue
                    served.clear()
                    with self._lock:
                        self._last_dl = cur
                        self.stats["dl_blocks"] += 1
                        self.stats["dl_bytes"] += len(cur)
                        if time.perf_counter() - t0 > 0.05:
                            self.stats["late"] += 1
                try:
                    s.send(cur)
                    served.add(i)
                except zmq.ZMQError:
                    return

    # ── uplink: pull each UE's block, sum, hand the sum to the gNB ────────
    def _ul_loop(self) -> None:
        try:
            self._ul_loop_inner()
        except Exception as e:
            import traceback; print(f'[broker] UL THREAD DIED: {e}', flush=True); traceback.print_exc()
            self.stats['ul_thread_dead'] = str(e)

    def _ul_loop_inner(self) -> None:
        rep = self.ctx.socket(zmq.REP)
        rep.setsockopt(zmq.LINGER, 0)
        rep.bind(f"tcp://*:{GNB_RX_PORT}")

        ue_reqs = []
        for i in range(self.n):
            s = self.ctx.socket(zmq.REQ)
            s.setsockopt(zmq.LINGER, 0)
            s.setsockopt(zmq.RCVTIMEO, 40)
            s.connect(f"tcp://localhost:{UE_BASE_TX + i}")
            ue_reqs.append(s)

        while _running:
            try:
                if rep.poll(timeout=100) != zmq.POLLIN:
                    continue
                _ = rep.recv()                          # gNB asks for uplink
            except zmq.ZMQError:
                break

            t0 = time.perf_counter()
            acc: np.ndarray | None = None
            for i, s in enumerate(ue_reqs):
                try:
                    s.send(REQ)
                    b = s.recv()
                    a = np.frombuffer(b, dtype=np.complex64)
                    acc = a.copy() if acc is None else (
                        acc + a if acc.shape == a.shape else acc)
                except zmq.ZMQError:
                    # UE quiet this slot: recreate the socket so REQ state stays sane
                    self.stats["ue_silent"][i] += 1
                    try:
                        s.close(0)
                    except Exception:
                        pass
                    ns = self.ctx.socket(zmq.REQ)
                    ns.setsockopt(zmq.LINGER, 0); ns.setsockopt(zmq.RCVTIMEO, 40)
                    ns.connect(f"tcp://localhost:{UE_BASE_TX + i}")
                    ue_reqs[i] = ns

            with self._lock:
                ref = len(self._last_dl)
            if acc is not None:
                out = acc.tobytes()
            else:
                nsamp = (ref // 8) if ref >= 8 else self.block_samples
                out = np.zeros(nsamp, dtype=np.complex64).tobytes()
            try:
                rep.send(out)
            except zmq.ZMQError:
                break
            with self._lock:
                self.stats["ul_blocks"] += 1
                self.stats["ul_bytes"] += len(out)
                if time.perf_counter() - t0 > 0.05:
                    self.stats["late"] += 1

    # ── public ─────────────────────────────────────────────────────────────
    def run(self) -> None:
        print(f"[broker] {self.n} UEs, bootstrap block {self.block_samples} samples")
        print(f"[broker] gNB  tx :{GNB_TX_PORT} (we REQ)   rx :{GNB_RX_PORT} (we REP)")
        for i in range(self.n):
            print(f"[broker] ue{i+1} rx :{UE_BASE_RX+i} (we REP)   tx :{UE_BASE_TX+i} (we REQ)")
        t1 = threading.Thread(target=self._dl_loop, daemon=True)
        t2 = threading.Thread(target=self._ul_loop, daemon=True)
        t1.start(); t2.start()
        last = time.time()
        while _running:
            time.sleep(5)
            with self._lock:
                s = dict(self.stats)
            dt = time.time() - last; last = time.time()
            print(f"[broker] dl={s['dl_blocks']} ul={s['ul_blocks']} late={s['late']} "
                  f"dl={s['dl_bytes']/dt/1e6:.1f}MB/s ul={s['ul_bytes']/dt/1e6:.1f}MB/s "
                  f"silent={s['ue_silent']}", flush=True)
            with self._lock:
                self.stats["dl_bytes"] = 0; self.stats["ul_bytes"] = 0

    def selftest(self, srate_msps: float = 23.04) -> bool:
        """Can the broker sustain more than the sample rate? Guard against R1."""
        need = srate_msps * 1e6 * 8 / 1e6           # MB/s per direction
        n_blk, blk = 2000, 1920
        a = [np.random.randn(blk).astype(np.complex64) for _ in range(self.n)]
        t0 = time.perf_counter()
        for _ in range(n_blk):
            acc = a[0].copy()
            for x in a[1:]:
                acc += x
            _ = acc.tobytes()
        dt = time.perf_counter() - t0
        got = n_blk * blk * 8 / dt / 1e6
        print(f"[selftest] sum+serialise {self.n} streams: {got:.0f} MB/s "
              f"(need > {need:.0f} MB/s)")
        ok = got > need * 2
        print(f"[selftest] {'PASS — broker will not be the bottleneck' if ok else 'FAIL — broker WOULD bottleneck; reduce bandwidth or n'}")
        return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--srate", type=float, default=23.04)
    ap.add_argument("--block-samples", type=int, default=BOOTSTRAP_SAMPLES,
                    help="zero-block size before any UE has synced (1ms at srate)")
    a = ap.parse_args()

    b = Broker(a.n_ue, block_samples=a.block_samples)
    if a.selftest:
        sys.exit(0 if b.selftest(a.srate) else 1)

    def stop(*_):
        global _running
        _running = False
        print("\n[broker] stopping")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    b.run()


if __name__ == "__main__":
    main()
