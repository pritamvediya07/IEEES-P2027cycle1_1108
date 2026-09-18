# NWDAF PALA — Full Network Run Guide

Complete step-by-step commands to bring up the entire 5G testbed with NWDAF analytics,
10 UEs, continuous traffic, and the PALA Streamlit UI.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Ubuntu Host                              │
│                                                                 │
│  ┌─────────────────────┐    ┌──────────────────────────────┐   │
│  │   Open5GS 5G Core   │    │     UERANSIM (Simulated RAN) │   │
│  │  (systemd services) │    │                              │   │
│  │  NRF  AMF  SMF  UPF │◄──►│  nr-gnb  ──►  nr-ue (x10)  │   │
│  │  AUSf UDM UDR  PCF  │    │                              │   │
│  │  SCP  NSSF          │    │  uesimtun0  10.45.0.16       │   │
│  └────────┬────────────┘    │  uesimtun1  10.45.0.17       │   │
│           │ ogstun          │  ...                          │   │
│           │ 10.45.0.1       │  uesimtun9  10.45.0.25       │   │
│           │                 └──────────────────────────────┘   │
│  ┌────────▼────────────┐                                        │
│  │   NWDAF + PALA  │    ┌──────────────────────────────┐   │
│  │  MongoDB            │    │    Traffic Generator          │   │
│  │  Collector (5s)     │    │  server.py  (port 7654)       │   │
│  │  5 Tools            │◄───│  run_all_ues.py (10 clients)  │   │
│  │  Streamlit UI :8501 │    │  nr-binder (5G GTP tunnel)    │   │
│  └─────────────────────┘    └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Traffic path for each UE:**
`nr-binder` → `uesimtunX` → gNB (SCTP/NGAP) → AMF → SMF → UPF (`ogstun`) → NAT → server

---

## Prerequisites (one-time check)

These must already be set up. Verify with:

```bash
# MongoDB running
systemctl is-active mongod

# Open5GS 5G SA core services running (all should print "active")
systemctl is-active open5gs-nrfd open5gs-amfd open5gs-smfd open5gs-upfd \
  open5gs-ausfd open5gs-udmd open5gs-udrd open5gs-pcfd open5gs-scpd open5gs-nssfd

# Ollama running with llama3.1
systemctl is-active ollama
ollama list | grep llama3.1
```

If any Open5GS service is not active, start it:
```bash
sudo systemctl start open5gs-nrfd open5gs-amfd open5gs-smfd open5gs-upfd \
  open5gs-ausfd open5gs-udmd open5gs-udrd open5gs-pcfd open5gs-scpd open5gs-nssfd
```

---

## Step 1 — Start the gNB (Radio Access Node)

**Open a new terminal (Terminal 1). Keep it running.**

```bash
cd /path/to/pala-artifact/UERANSIM
sudo build/nr-gnb -c config/open5gs-gnb.yaml
```

**Wait for:**
```
[ngap] [info] NG Setup procedure is successful
```

**What this does:**  
Starts the simulated 5G base station (gNodeB). It connects to the Open5GS AMF over SCTP on `127.0.0.5:38412` and completes the NG Setup handshake. All UE registrations and PDU sessions go through this process.

---

## Step 2 — Cache sudo credentials (one-time, same terminal as UEs)

**Open a new terminal (Terminal 2).**

```bash
cd /path/to/pala-artifact/UERANSIM
sudo -v
```

Enter your password once. This caches the sudo token for 15 minutes so the 10 backgrounded UE processes (which have no TTY) can use `sudo -n` without being stopped.

---

## Step 3 — Start all 10 UEs

Still in **Terminal 2**, run each command. The UEs start in the background and immediately begin registration with the 5G core.

```bash
sudo -n build/nr-ue -c config/ue1.yaml  > /tmp/ue1.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue2.yaml  > /tmp/ue2.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue3.yaml  > /tmp/ue3.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue4.yaml  > /tmp/ue4.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue5.yaml  > /tmp/ue5.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue6.yaml  > /tmp/ue6.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue7.yaml  > /tmp/ue7.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue8.yaml  > /tmp/ue8.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue9.yaml  > /tmp/ue9.log  2>&1 &
```
```bash
sudo -n build/nr-ue -c config/ue10.yaml > /tmp/ue10.log 2>&1 &
```

**Verify all 10 tunnels are UP:**
```bash
ip link show | grep uesimtun
```

Expected output — all 10 interfaces UP:
```
126: uesimtun0: <POINTOPOINT,...,UP,LOWER_UP> ...
127: uesimtun1: <POINTOPOINT,...,UP,LOWER_UP> ...
...
135: uesimtun9: <POINTOPOINT,...,UP,LOWER_UP> ...
```

Check a UE log if any tunnel is missing:
```bash
tail -20 /tmp/ue3.log
```
Look for: `PDU Session establishment is successful` and `uesimtunX is up`.

**UE → Tunnel IP mapping:**

| Config     | IMSI                | Tunnel     | UE IP       |
|------------|---------------------|------------|-------------|
| ue1.yaml   | 999700000000001     | uesimtun0  | 10.45.0.16  |
| ue2.yaml   | 999700000000002     | uesimtun1  | 10.45.0.17  |
| ue3.yaml   | 999700000000003     | uesimtun2  | 10.45.0.18  |
| ue4.yaml   | 999700000000004     | uesimtun3  | 10.45.0.19  |
| ue5.yaml   | 999700000000005     | uesimtun4  | 10.45.0.20  |
| ue6.yaml   | 999700000000006     | uesimtun5  | 10.45.0.21  |
| ue7.yaml   | 999700000000007     | uesimtun6  | 10.45.0.22  |
| ue8.yaml   | 999700000000008     | uesimtun7  | 10.45.0.23  |
| ue9.yaml   | 999700000000009     | uesimtun8  | 10.45.0.24  |
| ue10.yaml  | 999700000000010     | uesimtun9  | 10.45.0.25  |

**What this does:**  
Each `nr-ue` process simulates one 5G phone. It performs full NAS registration (Authentication, Security Mode, Registration Accept) with the AMF, then establishes a PDU Session through the SMF+UPF, which creates the `uesimtunX` TUN interface assigned a 5G IP from the `10.45.0.0/24` pool.

---

## Step 4 — Start the Traffic Server

**Open a new terminal (Terminal 3). Keep it running.**

```bash
cd /path/to/pala-artifact
python3 traffic/server.py
```

**Wait for:**
```
=== 5G Traffic Server listening on port 7654 ===
    Waiting for UE connections...
```

**What this does:**  
A multi-threaded TCP server that accepts simultaneous connections from all 10 UE clients. Each connection is handled in its own thread. Files received from each UE are saved to `traffic/received/`. The server runs indefinitely, handling each new file transfer as UEs continuously reconnect.

---

## Step 5 — Start Continuous 10-UE Traffic

**Open a new terminal (Terminal 4). Keep it running.**

```bash
cd /path/to/pala-artifact
python3 traffic/run_all_ues.py
```

**Stop with Ctrl+C** (cleanly kills all 10 UE client processes).

**What this does:**  
Launches 10 subprocesses simultaneously, one per UE. Each subprocess runs `nr-binder <UE_IP>` which uses `LD_PRELOAD` to hijack Python's network sockets and force all TCP connections through the corresponding `uesimtunX` 5G tunnel interface. Each UE client cycles continuously through 5 file types:

| File                  | Size   | Simulates                          |
|-----------------------|--------|------------------------------------|
| `test_image.jpg`      | 82 KB  | Image / video frame upload         |
| `model_gradients.bin` | 41 KB  | Federated learning gradient push   |
| `ue_metrics.csv`      | 1.8 KB | UE KPI telemetry report            |
| `kpi_report.json`     | 1.5 KB | NWDAF analytics payload            |
| `policy_update.txt`   | 0.9 KB | PCF policy push notification       |

Traffic path per transfer:  
`Python client` → `nr-binder (LD_PRELOAD)` → `uesimtunX` → `gNB (GTP-U)` → `UPF (ogstun)` → `NAT (MASQUERADE)` → `server.py`

---

## Step 6 — Start NWDAF + PALA UI

**Open a new terminal (Terminal 5). Keep it running.**

```bash
cd /path/to/pala-artifact
source .venv/bin/activate
python start.py
```

Open browser at: **http://localhost:8501**  
Or from another machine: **http://<host-ip>:8501**

**What this does:**  
1. Checks MongoDB and Ollama are reachable  
2. Starts the NWDAF **Collector** in a background thread — every 5 seconds it queries Open5GS MongoDB and `/proc/net/dev` to record `active_ue_count`, SMF sessions, UPF throughput, memory/CPU metrics into the `nwdaf_analytics` database  
3. Launches the **Streamlit UI** — a web interface where you type natural language intents and the PALA (Llama 3.1 via Ollama) calls the 5 NWDAF tools to fulfill them

---

## Health Checks

Run these anytime to verify everything is healthy:

```bash
# All 10 tunnels UP
ip link show | grep uesimtun | wc -l
```

```bash
# Latest NWDAF data (should show active_ue_count: 10, fresh timestamp)
mongosh --quiet --eval \
  "db = db.getSiblingDB('nwdaf_analytics'); \
   db.upf_metrics.find({},{active_ue_count:1,timestamp:1,_id:0}) \
   .sort({timestamp:-1}).limit(1).toArray()"
```

```bash
# Files being received through 5G tunnels
ls -lt /path/to/pala-artifact/traffic/received/ | head -15
```

```bash
# UE log check (replace N with UE number 1-10)
tail -5 /tmp/ue1.log
```

```bash
# Traffic processes alive
ps aux | grep "nr-binder\|nr-ue\|nr-gnb" | grep -v grep
```

---

## Stopping Everything

```bash
# Stop UE traffic clients (Terminal 4)
Ctrl+C   # in run_all_ues.py terminal

# Stop traffic server (Terminal 3)
Ctrl+C   # in server.py terminal

# Stop NWDAF + Streamlit (Terminal 5)
Ctrl+C   # in start.py terminal

# Stop all 10 UEs
sudo pkill -9 -f "nr-ue"

# Stop gNB (Terminal 1)
Ctrl+C   # in nr-gnb terminal
```

---

## Example PALA Intents to Try

Once the Streamlit UI is open, paste any of these into the intent box:

```
Predict memory utilization % for the internet slice based on 500 recent values.
```
```
Show me the current session count and any KPI anomalies in the last hour.
```
```
What are the active PDU sessions on the internet DNN?
```
```
Monitor the active_ue_count metric and alert me if it exceeds 8.
```
```
Increase the data rate for the internet slice by 20% from now until 30 minutes from now.
```

---

## File Reference

```
marcus/
├── start.py                        # Entry point: starts collector + Streamlit
├── UERANSIM/
│   ├── build/
│   │   ├── nr-gnb                  # gNB binary
│   │   ├── nr-ue                   # UE binary
│   │   └── nr-binder               # Socket binder (forces traffic into 5G tunnel)
│   └── config/
│       ├── open5gs-gnb.yaml        # gNB config (MCC=999, MNC=70, AMF=127.0.0.5)
│       ├── ue1.yaml  .. ue10.yaml  # Per-UE configs (IMSI, K, OPc)
│       └── traffic.sh              # (legacy) simple ping script
├── traffic/
│   ├── server.py                   # Multi-client file receiver (port 7654)
│   ├── run_all_ues.py              # Launches all 10 UE clients
│   ├── continuous_client.py        # Per-UE continuous file sender (via nr-binder)
│   ├── client.py                   # One-shot client (manual use)
│   ├── files/                      # Files sent as traffic
│   │   ├── test_image.jpg
│   │   ├── model_gradients.bin
│   │   ├── ue_metrics.csv
│   │   ├── kpi_report.json
│   │   └── policy_update.txt
│   └── received/                   # Files received through 5G tunnels
├── agent/
│   ├── agent.py                    # PALA ReAct loop (Ollama + tools)
│   └── streamlit_app.py            # Web UI
├── collector/
│   └── collector.py                # NWDAF metrics collector (5s interval)
├── tools/                          # 5 NWDAF tools callable by PALA
│   ├── kpi_analyzer.py
│   ├── feasibility_checker.py
│   ├── policy_manager.py
│   ├── session_manager.py
│   └── monitoring_manager.py
└── config/
    ├── settings.py                 # All constants (AMBR limits, DB names, etc.)
    └── db.py                       # MongoDB connection pool
```
