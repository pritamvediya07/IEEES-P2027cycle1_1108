#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  tc-setup.sh — Traffic Control Enforcement for PALA Testbed
#  Run as: sudo bash docker/testbed/scripts/tc-setup.sh
# ══════════════════════════════════════════════════════════════════════════════
#
#  Applies a 15 Mbps HTB cap + 40 ms delay on the loopback interface.
#  This enforces the ground-truth Q measurement environment described in
#  Section IV-B of the paper (τ baseline ≈ 13.5 Mbps, λ baseline ≈ 43 ms).
#
#  The cap ensures that AMBR policy changes have measurable effect on the
#  ground-truth quality metric Q, creating the reward hacking signal.
#
#  Idempotent: safe to run multiple times. Clears existing rules first.
#
#  Teardown:  sudo tc qdisc del dev lo root 2>/dev/null || true
# ══════════════════════════════════════════════════════════════════════════════

set -e

IFACE="lo"
RATE="15mbit"
DELAY="40ms"
LOSS="3%"

echo "[tc] Clearing existing rules on $IFACE..."
tc qdisc del dev "$IFACE" root 2>/dev/null || true

echo "[tc] Adding HTB root qdisc..."
tc qdisc add dev "$IFACE" root handle 1: htb default 10

echo "[tc] Adding 15 Mbps class..."
tc class add dev "$IFACE" parent 1: classid 1:10 htb rate "$RATE" burst 15k

echo "[tc] Adding netem (delay ${DELAY}, loss ${LOSS})..."
tc qdisc add dev "$IFACE" parent 1:10 handle 10: netem delay "$DELAY" loss "$LOSS"

echo "[tc] Verifying..."
tc qdisc show dev "$IFACE"
tc class show dev "$IFACE"

echo ""
echo "[tc] Done. Loopback capped at $RATE with ${DELAY} delay and ${LOSS} loss."
echo "     Expected baseline Q: τ≈13.5 Mbps, λ≈43 ms, ρ≈3%, Q≈0.85"
echo ""
echo "     To remove: sudo tc qdisc del dev lo root"
