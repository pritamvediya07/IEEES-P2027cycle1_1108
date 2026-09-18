// MongoDB subscriber init script for Docker testbed
// Run via: mongosh mongodb://mongo-testbed:27017/open5gs init_subscribers.js
// Initializes 10 UEs matching UERANSIM config (MCC 999, MNC 70)
//
// Credentials match open5gs-ue.yaml:
//   key:    465B5CE8B199B49FAA5F0A2EE238A6BC
//   op:     E8ED289DEBA952E4283B54E88E6183CA (OPC)
//   APN:    internet / SST=1

const db = db.getSiblingDB('open5gs');

const BASE_IMSI = 999700000000001n;
const KEY       = '465b5ce8b199b49faa5f0a2ee238a6bc';
const OPC       = 'e8ed289deba952e4283b54e88e6183ca';

const DEFAULT_AMBR = {
  downlink: { value: 1, unit: 3 },   // 1 Gbps
  uplink:   { value: 1, unit: 3 },
};

const SLICE = {
  sst: 1,
  "default_indicator": true,
  "session": [{
    name: "internet",
    type: 3,
    "ambr": {
      downlink: { value: 1, unit: 3 },
      uplink:   { value: 1, unit: 3 },
    },
    "qos": {
      index: 9,
      arp: { priority_level: 8, pre_emption_capability: 1, pre_emption_vulnerability: 1 }
    }
  }]
};

let added = 0;
let skipped = 0;

for (let i = 0; i < 10; i++) {
  const imsi = String(BASE_IMSI + BigInt(i));
  const existing = db.subscribers.findOne({ imsi: imsi });
  if (existing) {
    print(`[skip] IMSI ${imsi} already exists`);
    skipped++;
    continue;
  }
  db.subscribers.insertOne({
    imsi:            imsi,
    msisdn:          [],
    imeisv:          [],
    "mme_host":      [],
    "mme_realm":     [],
    "purge_flag":    [],
    "security": {
      k:    KEY,
      amf:  "8000",
      op:   null,
      opc:  OPC,
    },
    "ambr":  DEFAULT_AMBR,
    "slice": [SLICE],
    "__v": 0,
  });
  print(`[add]  IMSI ${imsi}`);
  added++;
}

print(`\nDone: added=${added} skipped=${skipped}`);
