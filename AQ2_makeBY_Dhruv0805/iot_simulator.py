"""
iot_simulator.py
────────────────
Simulates IoT sensors writing telemetry data every 10 seconds.
Reads ahmedabad_network.json for node positions, writes to network_live.db.
"""

import sqlite3
import json
import time
import random
import os
from datetime import datetime, timezone

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DB_FILE      = os.path.join(BASE_DIR, 'network_live.db')
NETWORK_FILE = os.path.join(BASE_DIR, 'ahmedabad_network.json')

# Adjusted anomaly chance for ~2500 hand-drawn pipes
ANOMALY_CHANCE = 0.005

ANOMALY_TYPES = [
    ('pipe_burst',   (0.5,  2.0),  (500, 900),  (8000, 25000)),
    ('slow_seepage', (3.2,  3.7),  (130, 160),  (500,   2000)),
    ('illegal_tap',  (3.0,  3.6),  (150, 250),  (1000,  5000)),
    ('meter_tamper', (3.9,  4.5),  (5,    20),  (200,   1000)),
]


def setup_database(conn):
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    c.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp              TEXT,
            segment_id             TEXT,
            zone                   TEXT,
            pressure_bar           REAL,
            flow_lpm               REAL,
            anomaly                INTEGER,
            nrw_type               TEXT,
            estimated_loss_liters  REAL,
            latitude               REAL,
            longitude              REAL
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_segment_time ON telemetry (segment_id, timestamp DESC)')
    conn.commit()


def load_network_nodes():
    if not os.path.exists(NETWORK_FILE):
        print(f"❌ {NETWORK_FILE} not found! Run generate_network.py first.")
        return []

    with open(NETWORK_FILE, 'r') as f:
        data = json.load(f)

    nodes = []
    # Force mapping to match backend CSV zones
    zone_map = {
        'ZONE_BLUE': 'Z1',
        'ZONE_YELLOW': 'Z2',
        'ZONE_GREEN': 'Z3'
    }

    for zone_key, segments in data.get('zones', {}).items():
        zone_str = zone_map.get(zone_key, 'Z1')
        for seg in segments:
            nodes.append({
                'segment_id': seg['id'],
                'zone':       zone_str,
                'lat':        seg['lat'],
                'lon':        seg['lon'],
            })

    print(f"✅ Loaded {len(nodes)} custom nodes from {os.path.basename(NETWORK_FILE)}")
    return nodes


def generate_telemetry(conn, nodes):
    c = conn.cursor()
    current_time = datetime.now(timezone.utc).isoformat()
    records = []

    for node in nodes:
        pressure = round(random.uniform(3.8, 4.2), 2)
        flow     = round(random.uniform(100, 120), 2)
        anomaly, loss = 0, 0.0
        nrw_type = 'none'

        if random.random() < ANOMALY_CHANCE:
            anomaly_def = random.choice(ANOMALY_TYPES)
            nrw_type    = anomaly_def[0]
            pressure    = round(random.uniform(*anomaly_def[1]), 2)
            flow        = round(random.uniform(*anomaly_def[2]), 2)
            loss        = round(random.uniform(*anomaly_def[3]), 2)
            anomaly     = 1

        records.append((
            current_time, node['segment_id'], node['zone'], pressure, flow,
            anomaly, nrw_type, loss, node['lat'], node['lon']
        ))

    c.executemany('''
        INSERT INTO telemetry
            (timestamp, segment_id, zone, pressure_bar, flow_lpm,
             anomaly, nrw_type, estimated_loss_liters, latitude, longitude)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', records)
    conn.commit()

    anomaly_count = sum(1 for r in records if r[5] == 1)
    print(f"📡 [{current_time[:19]}] {len(records)} readings | {anomaly_count} anomalies")


def prune_old_data(conn):
    c = conn.cursor()
    c.execute('DELETE FROM telemetry WHERE id NOT IN (SELECT id FROM telemetry ORDER BY timestamp DESC LIMIT 500000)')
    conn.commit()


if __name__ == '__main__':
    print("🚀 AQUAWATCH IoT SIMULATOR STARTING\n")
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    setup_database(conn)

    nodes = load_network_nodes()
    if not nodes:
        conn.close()
        exit(1)

    tick = 0
    try:
        while True:
            generate_telemetry(conn, nodes)
            tick += 1
            if tick % 50 == 0:
                prune_old_data(conn)
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped.")
        conn.close()