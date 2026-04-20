import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import joblib
import warnings
warnings.filterwarnings('ignore')
import json
import os
import uuid
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'aquawatch-ahmedabad-secret-2024')

# ─────────────────────────────────────────
# FILE PATHS
# ─────────────────────────────────────────
NETWORK_FILE  = os.path.join(os.path.dirname(__file__), 'ahmedabad_network.json') # UPDATED
DB_FILE       = os.path.join(os.path.dirname(__file__), 'network_live.db')
DISPATCH_FILE = os.path.join(os.path.dirname(__file__), 'dispatches.json')
USERS_DB      = os.path.join(os.path.dirname(__file__), 'users.db')
MODEL_FILE    = os.path.join(os.path.dirname(__file__), 'model.pkl')
EXCEL_FILE    = os.path.join(os.path.dirname(__file__), 'TS-PS10.xlsx')

# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────
def init_users_db():
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        conn.commit()

init_users_db()

# ─────────────────────────────────────────
# MODEL LOADER
# ─────────────────────────────────────────
anomaly_model = classify_model = label_encoder = None
anomaly_features = classify_features = nrw_classes = None
df = None

def load_model_and_data():
    global anomaly_model, classify_model, label_encoder
    global anomaly_features, classify_features, nrw_classes, df

    if os.path.exists(MODEL_FILE):
        print("Loading model...")
        bundle          = joblib.load(MODEL_FILE)
        anomaly_model   = bundle['anomaly_model']
        classify_model  = bundle['classify_model']
        label_encoder   = bundle['label_encoder']
        anomaly_features  = bundle['anomaly_features']
        classify_features = bundle['classify_features']
        nrw_classes     = bundle['nrw_classes']
        print(f"Model loaded. NRW classes: {nrw_classes}")
    else:
        print("⚠️  model.pkl not found — /predict endpoint disabled.")

    if os.path.exists(EXCEL_FILE):
        print("Loading dataset...")
        df = pd.read_excel(EXCEL_FILE)
        df['nrw_type'] = df['nrw_type'].str.strip().str.lower()
        df['demand_peak_flag'] = df['demand_peak_flag'].fillna(0)
        df['estimated_loss_liters'] = df['estimated_loss_liters'].fillna(0)
        df['pressure_deviation']  = df['expected_pressure_bar'] - df['pressure_bar']
        df['deviation_pct']       = (df['pressure_deviation'] / df['expected_pressure_bar']) * 100
        df['flow_pressure_ratio'] = df['flow_lpm'] / (df['pressure_bar'] + 0.001)
        df['zone_encoded']        = df['zone'].str.extract('(\d+)').astype(int)
        print(f"Dataset loaded. {len(df)} rows ready.")
    else:
        print("⚠️  TS-PS10.xlsx not found — Excel-based endpoints will return empty data.")

load_model_and_data()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def get_urgency(loss, nrw_type):
    if nrw_type == 'pipe_burst': return 'HIGH'
    if loss > 5000: return 'HIGH'
    if loss > 1000: return 'MEDIUM'
    return 'LOW'

def get_urgency_color(urgency):
    return {'HIGH': '#ef4444', 'MEDIUM': '#f59e0b', 'LOW': '#22c55e'}.get(urgency, '#22c55e')

def get_nrw_color(nrw_type):
    return {
        'pipe_burst':   '#ff5252',
        'slow_seepage': '#f6c94e',
        'illegal_tap':  '#b07ff5',
        'meter_tamper': '#ff8c42',
        'none':         '#4ecb7a'
    }.get(nrw_type, '#4ecb7a')

def generate_message(nrw_type, zone, segment_id, loss, urgency, lat, lon):
    labels = {'pipe_burst': 'Pipe Burst', 'slow_seepage': 'Slow Seepage',
              'illegal_tap': 'Illegal Tap', 'meter_tamper': 'Meter Tampering', 'none': 'Normal'}
    label = labels.get(nrw_type, nrw_type)
    return (f"ALERT: {label} detected at {segment_id} ({zone}). "
            f"Location: {lat:.4f}N, {lon:.4f}E. "
            f"Estimated loss: {int(loss):,} litres/hr. "
            f"Urgency: {urgency}. Dispatch field team immediately.")

# ─────────────────────────────────────────
# DISPATCH LOG
# ─────────────────────────────────────────
def load_dispatches():
    if os.path.exists(DISPATCH_FILE):
        with open(DISPATCH_FILE, 'r') as f:
            return json.load(f)
    return []

def save_dispatches(records):
    with open(DISPATCH_FILE, 'w') as f:
        json.dump(records, f, indent=2)

# ─────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────
@app.route('/')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        with sqlite3.connect(USERS_DB) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = c.fetchone()
            if user and check_password_hash(user[2], password):
                session['logged_in'] = True
                session['username']  = username
                return redirect(url_for('home'))
            else:
                error = 'Invalid username or password. Please try again.'
    return render_template('login.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            with sqlite3.connect(USERS_DB) as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM users WHERE username = ?", (username,))
                if c.fetchone():
                    error = "Username already exists. Please choose a different one."
                else:
                    hashed_pw = generate_password_hash(password)
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
                    conn.commit()
                    return redirect(url_for('login'))
    return render_template('signup.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────
# ENDPOINT 1 — POST /predict
# ─────────────────────────────────────────
@app.route('/predict', methods=['POST'])
def predict():
    if anomaly_model is None:
        return jsonify({'error': 'Model not loaded'}), 503
    try:
        data = request.get_json()
        pressure   = float(data.get('pressure_bar', 0))
        flow       = float(data.get('flow_lpm', 0))
        expected   = float(data.get('expected_pressure_bar', 0))
        zone_str   = str(data.get('zone', 'Z1'))
        sensor_id  = str(data.get('sensor_id', 'S00'))
        peak_flag  = int(data.get('demand_peak_flag', 0))
        segment_id = str(data.get('segment_id', 'SEG-000'))
        lat        = float(data.get('latitude', 23.0225))
        lon        = float(data.get('longitude', 72.5714))

        deviation     = expected - pressure
        deviation_pct = (deviation / expected * 100) if expected != 0 else 0
        flow_ratio    = flow / (pressure + 0.001)
        zone_enc      = int(zone_str.replace('Z', ''))

        anomaly_row = pd.DataFrame([{
            'pressure_bar': pressure, 'flow_lpm': flow,
            'expected_pressure_bar': expected, 'pressure_deviation': deviation,
            'deviation_pct': deviation_pct, 'flow_pressure_ratio': flow_ratio,
            'zone_encoded': zone_enc, 'demand_peak_flag': peak_flag
        }])

        anomaly_pred  = int(anomaly_model.predict(anomaly_row)[0])
        anomaly_proba = anomaly_model.predict_proba(anomaly_row)[0]
        anomaly_conf  = round(float(max(anomaly_proba)), 4)

        nrw_type = 'none'
        classify_conf = 0.0
        estimated_loss = 0.0

        if anomaly_pred == 1 and df is not None:
            matching = df[(df['zone'] == zone_str) & (df['anomaly'] == 1)]['estimated_loss_liters']
            estimated_loss = float(matching.mean()) if len(matching) > 0 else 0.0

            classify_row = pd.DataFrame([{
                'pressure_bar': pressure, 'flow_lpm': flow,
                'expected_pressure_bar': expected, 'pressure_deviation': deviation,
                'deviation_pct': deviation_pct, 'flow_pressure_ratio': flow_ratio,
                'zone_encoded': zone_enc, 'demand_peak_flag': peak_flag,
                'estimated_loss_liters': estimated_loss
            }])
            classify_pred  = classify_model.predict(classify_row)[0]
            classify_proba = classify_model.predict_proba(classify_row)[0]
            classify_conf  = round(float(max(classify_proba)), 4)
            nrw_type       = label_encoder.inverse_transform([classify_pred])[0]

        urgency = get_urgency(estimated_loss, nrw_type)
        message = generate_message(nrw_type, zone_str, segment_id, estimated_loss, urgency, lat, lon)

        return jsonify({
            'anomaly': anomaly_pred, 'anomaly_confidence': anomaly_conf,
            'nrw_type': nrw_type, 'nrw_type_confidence': classify_conf,
            'urgency': urgency, 'urgency_color': get_urgency_color(urgency),
            'nrw_color': get_nrw_color(nrw_type),
            'estimated_loss_liters': round(estimated_loss, 2),
            'segment_id': segment_id, 'zone': zone_str,
            'sensor_id': sensor_id, 'latitude': lat, 'longitude': lon, 'message': message
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 2 — GET /live  (Excel fallback)
# ─────────────────────────────────────────
@app.route('/live', methods=['GET'])
def live():
    if os.path.exists(DB_FILE):
        return live_sqlite_internal()
    if df is None:
        return jsonify([])
    try:
        last50 = df.tail(50).copy()
        last50['timestamp'] = last50['timestamp'].astype(str)
        last50['nrw_color'] = last50['nrw_type'].apply(get_nrw_color)
        records = last50[[
            'timestamp', 'sensor_id', 'zone', 'segment_id',
            'pressure_bar', 'expected_pressure_bar', 'flow_lpm',
            'anomaly', 'nrw_type', 'nrw_color',
            'estimated_loss_liters', 'demand_peak_flag', 'latitude', 'longitude'
        ]].to_dict(orient='records')
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 3 — GET /stats
# ─────────────────────────────────────────
@app.route('/stats', methods=['GET'])
def stats():
    if os.path.exists(DB_FILE):
        return stats_sqlite_internal()
    if df is None:
        return jsonify({'total_rows':0,'total_anomalies':0,'total_loss_liters':0,'sensors_online':0,'active_zones':25,'nrw_breakdown':{}})
    try:
        total_rows      = len(df)
        total_anomalies = int(df['anomaly'].sum())
        total_loss      = float(df['estimated_loss_liters'].sum())
        sensors_online  = int(df['sensor_id'].nunique())
        nrw_breakdown   = df[df['anomaly'] == 1]['nrw_type'].value_counts().to_dict()
        return jsonify({
            'total_rows': total_rows, 'total_anomalies': total_anomalies,
            'total_loss_liters': round(total_loss, 2), 'sensors_online': sensors_online,
            'active_zones': 25, 'nrw_breakdown': nrw_breakdown
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 4 — GET /alerts
# ─────────────────────────────────────────
@app.route('/alerts', methods=['GET'])
def alerts():
    if os.path.exists(DB_FILE):
        return alerts_sqlite_internal()
    if df is None:
        return jsonify([])
    try:
        anomalies = df[df['anomaly'] == 1].copy()
        anomalies['timestamp'] = anomalies['timestamp'].astype(str)
        anomalies['urgency']   = anomalies.apply(lambda r: get_urgency(r['estimated_loss_liters'], r['nrw_type']), axis=1)
        anomalies['urgency_color'] = anomalies['urgency'].apply(get_urgency_color)
        anomalies['nrw_color']     = anomalies['nrw_type'].apply(get_nrw_color)
        records = anomalies[[
            'timestamp', 'sensor_id', 'zone', 'segment_id',
            'pressure_bar', 'expected_pressure_bar', 'flow_lpm',
            'nrw_type', 'nrw_color', 'urgency', 'urgency_color',
            'estimated_loss_liters', 'latitude', 'longitude'
        ]].tail(200).to_dict(orient='records')
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 5 — GET /zone-summary
# ─────────────────────────────────────────
@app.route('/zone-summary', methods=['GET'])
def zone_summary():
    # Colors expanded to support the 25 zones in the new city network
    colors = { 
        'Z1': '#38b4f0', 'Z2': '#f6c94e', 'Z3': '#4ecb7a', 'Z4': '#ff8c42', 'Z5': '#b07ff5',
        'Z6': '#ff5252', 'Z7': '#42d4f4', 'Z8': '#bfef45', 'Z9': '#fabebe', 'Z10': '#469990',
        'Z11': '#e6beff', 'Z12': '#9A6324', 'Z13': '#fffac8', 'Z14': '#800000', 'Z15': '#aaffc3',
        'Z16': '#808000', 'Z17': '#ffd8b1', 'Z18': '#000075', 'Z19': '#a9a9a9', 'Z20': '#ffffff',
        'Z21': '#3cb44b', 'Z22': '#ffe119', 'Z23': '#4363d8', 'Z24': '#f58231', 'Z25': '#911eb4'
    }
    zones_list = [f'Z{i}' for i in range(1, 26)]
    result = []

    if os.path.exists(DB_FILE):
        try:
            with sqlite3.connect(DB_FILE) as conn:
                c = conn.cursor()
                for zone in zones_list:
                    c.execute('''
                        SELECT SUM(t.estimated_loss_liters), SUM(t.anomaly)
                        FROM telemetry t
                        INNER JOIN (
                            SELECT segment_id, MAX(timestamp) as max_ts FROM telemetry GROUP BY segment_id
                        ) latest ON t.segment_id = latest.segment_id AND t.timestamp = latest.max_ts
                        WHERE t.zone = ?
                    ''', (zone,))
                    row = c.fetchone()
                    # Only append if there's data for this zone (keeps the UI clean)
                    if row[0] is not None or row[1] is not None:
                        result.append({'zone': zone, 'total_loss': round(float(row[0] or 0), 2),
                                       'total_anomalies': int(row[1] or 0), 'color': colors.get(zone, '#38b4f0')})
            return jsonify(result)
        except Exception as e:
            pass  # fall through to Excel

    if df is not None:
        for zone in zones_list:
            zone_df = df[df['zone'] == zone]
            if not zone_df.empty:
                result.append({'zone': zone,
                               'total_loss': round(float(zone_df['estimated_loss_liters'].sum()), 2),
                               'total_anomalies': int(zone_df['anomaly'].sum()),
                               'color': colors.get(zone, '#38b4f0')})
    return jsonify(result)

# ─────────────────────────────────────────
# ENDPOINT 6 — POST /dispatch
# ─────────────────────────────────────────
@app.route('/dispatch', methods=['POST'])
def dispatch():
    try:
        data           = request.get_json()
        zone           = str(data.get('zone', 'Z1'))
        segment_id     = str(data.get('segment_id', 'SEG-000'))
        nrw_type       = str(data.get('nrw_type', 'none'))
        urgency        = str(data.get('urgency', 'LOW'))
        estimated_loss = float(data.get('estimated_loss_liters', 0))
        lat            = float(data.get('latitude', 23.0225))
        lon            = float(data.get('longitude', 72.5714))
        work_order_id  = str(uuid.uuid4())[:8].upper()

        # Try WhatsApp if configured
        message_sid = None
        wa_error    = None
        try:
            from whatsapp import send_whatsapp_alert, build_whatsapp_message, get_crew_phone
            message    = build_whatsapp_message(nrw_type, zone, segment_id, urgency, estimated_loss, lat, lon, work_order_id)
            crew_phone = get_crew_phone(zone)
            result     = send_whatsapp_alert(to_number=crew_phone, message=message)
            message_sid = result.get('message_sid')
            if not result['success']:
                wa_error = result.get('error')
        except ImportError:
            # whatsapp.py not present — dispatch still succeeds, just no SMS
            crew_phone = 'NOT_CONFIGURED'
            message    = generate_message(nrw_type, zone, segment_id, estimated_loss, urgency, lat, lon)

        dispatch_record = {
            'work_order_id': work_order_id, 'timestamp': datetime.utcnow().isoformat(),
            'zone': zone, 'segment_id': segment_id, 'nrw_type': nrw_type,
            'urgency': urgency, 'estimated_loss_liters': estimated_loss,
            'latitude': lat, 'longitude': lon,
            'status': 'SENT' if not wa_error else 'FAILED',
            'confirmed_at': None
        }
        dispatches = load_dispatches()
        dispatches.append(dispatch_record)
        save_dispatches(dispatches)

        return jsonify({'success': True, 'work_order_id': work_order_id,
                        'message_sid': message_sid, 'error': wa_error})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 7 — POST /confirm  (Twilio webhook)
# ─────────────────────────────────────────
@app.route('/confirm', methods=['POST'])
def confirm():
    try:
        body        = request.form.get('Body', '').strip().upper()
        from_number = request.form.get('From', '').replace('whatsapp:', '')
        if body.startswith('DONE'):
            parts = body.split()
            work_order_id = parts[1] if len(parts) > 1 else None
            if work_order_id:
                dispatches = load_dispatches()
                for record in dispatches:
                    if record['work_order_id'] == work_order_id:
                        record['status']       = 'CONFIRMED'
                        record['confirmed_at'] = datetime.utcnow().isoformat()
                        record['confirmed_by'] = from_number
                        break
                save_dispatches(dispatches)
        return ('<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                200, {'Content-Type': 'text/xml'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 8 — GET /work-orders
# ─────────────────────────────────────────
@app.route('/work-orders', methods=['GET'])
def work_orders():
    try:
        dispatches = sorted(load_dispatches(), key=lambda x: x['timestamp'], reverse=True)
        return jsonify(dispatches)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 9 — POST /false-positive
# ─────────────────────────────────────────
@app.route('/false-positive', methods=['POST'])
def false_positive():
    try:
        data = request.get_json()
        segment_id = data.get('segment_id', '')
        print(f"False positive reported: {segment_id}")
        return jsonify({'success': True, 'segment_id': segment_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 10 — GET /network-topology
# ─────────────────────────────────────────
@app.route('/network-topology', methods=['GET'])
def network_topology():
    try:
        if not os.path.exists(NETWORK_FILE):
            return jsonify({'error': f'{os.path.basename(NETWORK_FILE)} not found. Run: python generate_ahmedabad_network.py'}), 404
        with open(NETWORK_FILE, 'r') as f:
            topology = json.load(f)
        return jsonify(topology)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# SQLITE INTERNAL HELPERS
# ─────────────────────────────────────────
def live_sqlite_internal():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''
                SELECT t.* FROM telemetry t
                INNER JOIN (
                    SELECT segment_id, MAX(timestamp) as max_ts
                    FROM telemetry GROUP BY segment_id
                ) latest ON t.segment_id = latest.segment_id AND t.timestamp = latest.max_ts
                ORDER BY t.zone, t.segment_id
            ''')
            rows = c.fetchall()
        records = []
        for row in rows:
            records.append({
                'timestamp': row['timestamp'], 'segment_id': row['segment_id'],
                'sensor_id': row['segment_id'], 'zone': row['zone'],
                'pressure_bar': row['pressure_bar'], 'expected_pressure_bar': 4.0,
                'flow_lpm': row['flow_lpm'], 'anomaly': row['anomaly'],
                'nrw_type': row['nrw_type'], 'nrw_color': get_nrw_color(row['nrw_type']),
                'estimated_loss_liters': row['estimated_loss_liters'],
                'demand_peak_flag': 0,
                'latitude': row['latitude'], 'longitude': row['longitude']
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def stats_sqlite_internal():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute('''
                SELECT SUM(t.anomaly), SUM(t.estimated_loss_liters),
                       COUNT(*), COUNT(DISTINCT t.zone), COUNT(DISTINCT t.segment_id)
                FROM telemetry t
                INNER JOIN (
                    SELECT segment_id, MAX(timestamp) as max_ts FROM telemetry GROUP BY segment_id
                ) latest ON t.segment_id = latest.segment_id AND t.timestamp = latest.max_ts
            ''')
            row = c.fetchone()
            c.execute('''
                SELECT t.nrw_type, COUNT(*) FROM telemetry t
                INNER JOIN (
                    SELECT segment_id, MAX(timestamp) as max_ts FROM telemetry GROUP BY segment_id
                ) latest ON t.segment_id = latest.segment_id AND t.timestamp = latest.max_ts
                WHERE t.anomaly = 1 GROUP BY t.nrw_type
            ''')
            nrw_breakdown = {r[0]: r[1] for r in c.fetchall()}
        return jsonify({
            'total_rows': int(row[2] or 0), 'total_anomalies': int(row[0] or 0),
            'total_loss_liters': round(float(row[1] or 0), 2),
            'sensors_online': int(row[4] or 0), 
            'active_zones': int(row[3] or 0), # Now dynamically counts the actual number of active zones!
            'nrw_breakdown': nrw_breakdown
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def alerts_sqlite_internal():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''
                SELECT t.* FROM telemetry t
                INNER JOIN (
                    SELECT segment_id, MAX(timestamp) as max_ts FROM telemetry GROUP BY segment_id
                ) latest ON t.segment_id = latest.segment_id AND t.timestamp = latest.max_ts
                WHERE t.anomaly = 1
                ORDER BY t.estimated_loss_liters DESC
            ''')
            rows = c.fetchall()
        records = []
        for row in rows:
            nrw     = row['nrw_type']
            loss    = row['estimated_loss_liters']
            urgency = get_urgency(loss, nrw)
            records.append({
                'timestamp': row['timestamp'], 'segment_id': row['segment_id'],
                'sensor_id': row['segment_id'], 'zone': row['zone'],
                'pressure_bar': row['pressure_bar'], 'expected_pressure_bar': 4.0,
                'flow_lpm': row['flow_lpm'], 'nrw_type': nrw,
                'nrw_color': get_nrw_color(nrw), 'urgency': urgency,
                'urgency_color': get_urgency_color(urgency),
                'estimated_loss_liters': loss, 'demand_peak_flag': 0,
                'latitude': row['latitude'], 'longitude': row['longitude']
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*55)
    print("  AQUAWATCH NRW SERVER")
    print("  URL: http://localhost:5000")
    print("  Make sure to run generate_ahmedabad_network.py first!")
    print("  Then run iot_simulator.py in another terminal.")
    print("="*55 + "\n")
    app.run(debug=True, port=5000)