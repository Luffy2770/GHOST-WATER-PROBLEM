import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import joblib
import warnings
warnings.filterwarnings('ignore')
import json
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'super-secret-default-key')

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        conn.commit()

init_db() # Run this once when the app starts
# ----------------------
# ─────────────────────────────────────────
# MODEL AND DATA SET LODEDER
# ─────────────────────────────────────────
print("Loading model...")
bundle          = joblib.load('model.pkl')
anomaly_model   = bundle['anomaly_model']
classify_model  = bundle['classify_model']
label_encoder   = bundle['label_encoder']
anomaly_features  = bundle['anomaly_features']
classify_features = bundle['classify_features']
nrw_classes     = bundle['nrw_classes']
print(f"Model loaded. NRW classes: {nrw_classes}")

print("Loading dataset...")
df = pd.read_excel('TS-PS10.xlsx')
df['nrw_type'] = df['nrw_type'].str.strip().str.lower()
df['demand_peak_flag'] = df['demand_peak_flag'].fillna(0)
df['estimated_loss_liters'] = df['estimated_loss_liters'].fillna(0)

# engineer features on the dataset too (needed for /live and /alerts)
df['pressure_deviation']   = df['expected_pressure_bar'] - df['pressure_bar']
df['deviation_pct']        = (df['pressure_deviation'] / df['expected_pressure_bar']) * 100
df['flow_pressure_ratio']  = df['flow_lpm'] / (df['pressure_bar'] + 0.001)
df['zone_encoded']         = df['zone'].str.extract('(\d+)').astype(int)
print(f"Dataset loaded. {len(df)} rows ready.")

# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────
def get_urgency(loss, nrw_type):
    if nrw_type == 'pipe_burst':
        return 'HIGH'
    if loss > 5000:
        return 'HIGH'
    if loss > 1000:
        return 'MEDIUM'
    return 'LOW'

def get_urgency_color(urgency):
    colors = {'HIGH': '#ef4444', 'MEDIUM': '#f59e0b', 'LOW': '#22c55e'}
    return colors.get(urgency, '#22c55e')

def get_nrw_color(nrw_type):
    colors = {
        'pipe_burst':   '#ef4444',
        'slow_seepage': '#f59e0b',
        'illegal_tap':  '#a855f7',
        'meter_tamper': '#f97316',
        'none':         '#22c55e'
    }
    return colors.get(nrw_type, '#22c55e')

def generate_message(nrw_type, zone, segment_id, loss, urgency, lat, lon):
    type_labels = {
        'pipe_burst':   'Pipe Burst',
        'slow_seepage': 'Slow Seepage',
        'illegal_tap':  'Illegal Tap',
        'meter_tamper': 'Meter Tampering',
        'none':         'Normal'
    }
    label = type_labels.get(nrw_type, nrw_type)
    return (
        f"ALERT: {label} detected at {segment_id} ({zone}). "
        f"Location: {lat:.4f}N, {lon:.4f}E. "
        f"Estimated loss: {int(loss):,} litres/hr. "
        f"Urgency: {urgency}. Dispatch field team immediately."
    )

# ─────────────────────────────────────────
# DISPATCH LOG  (in-memory + persisted to dispatches.json)
# ─────────────────────────────────────────
DISPATCH_FILE = 'dispatches.json'

def load_dispatches():
    if os.path.exists(DISPATCH_FILE):
        with open(DISPATCH_FILE, 'r') as f:
            return json.load(f)
    return []

def save_dispatches(records):
    with open(DISPATCH_FILE, 'w') as f:
        json.dump(records, f, indent=2)

# --- ADD THIS NEW ROUTE ---
@app.route('/')
def home():
    return render_template('index.html')
# --------------------------

@app.route('/')
def home():
    # Check if the user is logged in
    if not session.get('logged_in'):
        # If not, redirect them to the login page
        return redirect(url_for('login'))
    
    # If they are logged in, show the main dashboard
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = c.fetchone()
            
            # user[2] is the hashed password from the database
            if user and check_password_hash(user[2], password):
                session['logged_in'] = True
                session['username'] = username # Optional: store the username to display it later
                return redirect(url_for('home'))
            else:
                error = 'Invalid username or password. Please try again.'
                
    return render_template('login.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            # Check if the username already exists
            c.execute("SELECT * FROM users WHERE username = ?", (username,))
            if c.fetchone():
                error = "Username already exists. Please choose a different one."
            else:
                # Hash the password and save the new user
                hashed_pw = generate_password_hash(password)
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
                conn.commit()
                return redirect(url_for('login'))
                
    return render_template('signup.html', error=error)

@app.route('/logout')
def logout():
    # Remove the logged_in flag from the session
    session.pop('logged_in', None)
    return redirect(url_for('login'))
# ─────────────────────────────────────────
# ENDPOINT 1 — POST /predict
# Frontend sends sensor reading, gets prediction back
# ─────────────────────────────────────────
@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()

        # extract inputs
        pressure     = float(data.get('pressure_bar', 0))
        flow         = float(data.get('flow_lpm', 0))
        expected     = float(data.get('expected_pressure_bar', 0))
        zone_str     = str(data.get('zone', 'Z1'))
        sensor_id    = str(data.get('sensor_id', 'S00'))
        peak_flag    = int(data.get('demand_peak_flag', 0))
        segment_id   = str(data.get('segment_id', 'SEG-000'))
        lat          = float(data.get('latitude', 23.0225))
        lon          = float(data.get('longitude', 72.5714))

        # engineer features
        deviation     = expected - pressure
        deviation_pct = (deviation / expected * 100) if expected != 0 else 0
        flow_ratio    = flow / (pressure + 0.001)
        zone_enc      = int(zone_str.replace('Z', ''))

        # build feature row for anomaly model
        anomaly_row = pd.DataFrame([{
            'pressure_bar':          pressure,
            'flow_lpm':              flow,
            'expected_pressure_bar': expected,
            'pressure_deviation':    deviation,
            'deviation_pct':         deviation_pct,
            'flow_pressure_ratio':   flow_ratio,
            'zone_encoded':          zone_enc,
            'demand_peak_flag':      peak_flag
        }])

        # run anomaly prediction
        anomaly_pred  = int(anomaly_model.predict(anomaly_row)[0])
        anomaly_proba = anomaly_model.predict_proba(anomaly_row)[0]
        anomaly_conf  = round(float(max(anomaly_proba)), 4)

        # if anomaly — run classifier
        nrw_type     = 'none'
        classify_conf = 0.0

        if anomaly_pred == 1:
            # find a matching row in dataset for estimated_loss
            matching = df[
                (df['zone'] == zone_str) &
                (df['anomaly'] == 1)
            ]['estimated_loss_liters']
            estimated_loss = float(matching.mean()) if len(matching) > 0 else 0.0

            classify_row = pd.DataFrame([{
                'pressure_bar':          pressure,
                'flow_lpm':              flow,
                'expected_pressure_bar': expected,
                'pressure_deviation':    deviation,
                'deviation_pct':         deviation_pct,
                'flow_pressure_ratio':   flow_ratio,
                'zone_encoded':          zone_enc,
                'demand_peak_flag':      peak_flag,
                'estimated_loss_liters': estimated_loss
            }])

            classify_pred  = classify_model.predict(classify_row)[0]
            classify_proba = classify_model.predict_proba(classify_row)[0]
            classify_conf  = round(float(max(classify_proba)), 4)
            nrw_type       = label_encoder.inverse_transform([classify_pred])[0]
        else:
            estimated_loss = 0.0

        urgency = get_urgency(estimated_loss, nrw_type)
        message = generate_message(nrw_type, zone_str, segment_id, estimated_loss, urgency, lat, lon)

        return jsonify({
            'anomaly':                 anomaly_pred,
            'anomaly_confidence':      anomaly_conf,
            'nrw_type':                nrw_type,
            'nrw_type_confidence':     classify_conf,
            'urgency':                 urgency,
            'urgency_color':           get_urgency_color(urgency),
            'nrw_color':               get_nrw_color(nrw_type),
            'estimated_loss_liters':   round(estimated_loss, 2),
            'segment_id':              segment_id,
            'zone':                    zone_str,
            'sensor_id':               sensor_id,
            'latitude':                lat,
            'longitude':               lon,
            'message':                 message
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# ENDPOINT 2 — GET /live
# Returns last 50 sensor readings for live monitor page
# ─────────────────────────────────────────
@app.route('/live', methods=['GET'])
def live():
    try:
        last50 = df.tail(50).copy()
        last50['timestamp'] = last50['timestamp'].astype(str)
        last50['nrw_color'] = last50['nrw_type'].apply(get_nrw_color)

        records = last50[[
            'timestamp', 'sensor_id', 'zone', 'segment_id',
            'pressure_bar', 'expected_pressure_bar', 'flow_lpm',
            'anomaly', 'nrw_type', 'nrw_color',
            'estimated_loss_liters', 'demand_peak_flag',
            'latitude', 'longitude'
        ]].to_dict(orient='records')

        return jsonify(records)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# ENDPOINT 3 — GET /stats
# Returns summary stats for dashboard stat cards
# ─────────────────────────────────────────
@app.route('/stats', methods=['GET'])
def stats():
    try:
        total_rows      = len(df)
        total_anomalies = int(df['anomaly'].sum())
        total_loss      = float(df['estimated_loss_liters'].sum())
        sensors_online  = int(df['sensor_id'].nunique())

        zone_summary = {}
        for zone in ['Z1', 'Z2', 'Z3']:
            zone_df = df[df['zone'] == zone]
            zone_summary[zone] = {
                'total_loss':      round(float(zone_df['estimated_loss_liters'].sum()), 2),
                'total_anomalies': int(zone_df['anomaly'].sum()),
                'sensors':         int(zone_df['sensor_id'].nunique())
            }

        nrw_breakdown = df[df['anomaly'] == 1]['nrw_type'].value_counts().to_dict()

        return jsonify({
            'total_rows':       total_rows,
            'total_anomalies':  total_anomalies,
            'total_loss_liters': round(total_loss, 2),
            'sensors_online':   sensors_online,
            'active_zones':     3,
            'zone_summary':     zone_summary,
            'nrw_breakdown':    nrw_breakdown
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# ENDPOINT 4 — GET /alerts
# Returns all anomaly rows for map pins + alerts table
# ─────────────────────────────────────────
@app.route('/alerts', methods=['GET'])
def alerts():
    try:
        anomalies = df[df['anomaly'] == 1].copy()
        anomalies['timestamp'] = anomalies['timestamp'].astype(str)
        anomalies['urgency']   = anomalies.apply(
            lambda r: get_urgency(r['estimated_loss_liters'], r['nrw_type']), axis=1
        )
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
# Returns loss per zone for pie chart
# ─────────────────────────────────────────
@app.route('/zone-summary', methods=['GET'])
def zone_summary():
    try:
        result = []
        colors = {'Z1': '#3b82f6', 'Z2': '#a855f7', 'Z3': '#14b8a6'}

        for zone in ['Z1', 'Z2', 'Z3']:
            zone_df = df[df['zone'] == zone]
            result.append({
                'zone':            zone,
                'total_loss':      round(float(zone_df['estimated_loss_liters'].sum()), 2),
                'total_anomalies': int(zone_df['anomaly'].sum()),
                'color':           colors[zone]
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────
# ENDPOINT 6 — POST /dispatch   ← NEW
# Sends WhatsApp work order to the zone's field crew
# ─────────────────────────────────────────
@app.route('/dispatch', methods=['POST'])
def dispatch():
    try:
        from whatsapp import send_whatsapp_alert, build_whatsapp_message, get_crew_phone

        data           = request.get_json()
        zone           = str(data.get('zone', 'Z1'))
        segment_id     = str(data.get('segment_id', 'SEG-000'))
        nrw_type       = str(data.get('nrw_type', 'none'))
        urgency        = str(data.get('urgency', 'LOW'))
        estimated_loss = float(data.get('estimated_loss_liters', 0))
        lat            = float(data.get('latitude', 23.0225))
        lon            = float(data.get('longitude', 72.5714))

        work_order_id = str(uuid.uuid4())[:8].upper()

        message = build_whatsapp_message(
            nrw_type       = nrw_type,
            zone           = zone,
            segment_id     = segment_id,
            urgency        = urgency,
            estimated_loss = estimated_loss,
            lat            = lat,
            lon            = lon,
            work_order_id  = work_order_id
        )

        crew_phone = get_crew_phone(zone)
        result = send_whatsapp_alert(to_number=crew_phone, message=message)

        dispatch_record = {
            'work_order_id':         work_order_id,
            'timestamp':             datetime.utcnow().isoformat(),
            'zone':                  zone,
            'segment_id':            segment_id,
            'nrw_type':              nrw_type,
            'urgency':               urgency,
            'estimated_loss_liters': estimated_loss,
            'latitude':              lat,
            'longitude':             lon,
            'crew_phone':            crew_phone,
            'message_sid':           result.get('message_sid'),
            'status':                'SENT' if result['success'] else 'FAILED',
            'whatsapp_error':        result.get('error'),
            'confirmed_at':          None
        }

        dispatches = load_dispatches()
        dispatches.append(dispatch_record)
        save_dispatches(dispatches)

        status_code = 200 if result['success'] else 500
        return jsonify({
            'success':        result['success'],
            'work_order_id':  work_order_id,
            'message_sid':    result.get('message_sid'),
            'message_sent':   message,
            'crew_phone':     crew_phone,
            'error':          result.get('error')
        }), status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# ENDPOINT 7 — POST /confirm   ← NEW
# Twilio webhook — called when field crew replies "DONE <work_order_id>"
# ─────────────────────────────────────────
@app.route('/confirm', methods=['POST'])
def confirm():
    try:
        body          = request.form.get('Body', '').strip().upper()
        from_number   = request.form.get('From', '').replace('whatsapp:', '')

        if body.startswith('DONE'):
            parts = body.split()
            work_order_id = parts[1] if len(parts) > 1 else None

            if work_order_id:
                dispatches = load_dispatches()
                updated    = False
                for record in dispatches:
                    if record['work_order_id'] == work_order_id:
                        record['status']       = 'CONFIRMED'
                        record['confirmed_at'] = datetime.utcnow().isoformat()
                        record['confirmed_by'] = from_number
                        updated = True
                        break
                if updated:
                    save_dispatches(dispatches)
                    return (
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        '<Response>'
                        f'<Message>✅ Work order #{work_order_id} marked CONFIRMED. Thank you!</Message>'
                        '</Response>'
                    ), 200, {'Content-Type': 'text/xml'}

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response></Response>'
        ), 200, {'Content-Type': 'text/xml'}

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# ENDPOINT 8 — GET /work-orders   ← NEW
# Returns dispatch log for the frontend
# ─────────────────────────────────────────
@app.route('/work-orders', methods=['GET'])
def work_orders():
    try:
        dispatches = load_dispatches()
        dispatches_sorted = sorted(dispatches, key=lambda x: x['timestamp'], reverse=True)
        return jsonify(dispatches_sorted)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# RUN SERVER
# ─────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*50)
    print("  NRW API SERVER STARTING")
    print("  URL: http://localhost:5000")
    print("  Endpoints:")
    print("    POST http://localhost:5000/predict")
    print("    GET  http://localhost:5000/live")
    print("    GET  http://localhost:5000/stats")
    print("    GET  http://localhost:5000/alerts")
    print("    GET  http://localhost:5000/zone-summary")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)


# mid-night case
# Invoke-RestMethod -Method Post -Uri http://localhost:5000/predict -ContentType "application/json" -Body '{"pressure_bar": 2.8, "flow_lpm": 150, "expected_pressure_bar": 3.5, "zone": "Z1", "sensor_id": "S12", "demand_peak_flag": 0, "segment_id": "SEG-012"}'
#
# meter freezz
# Invoke-RestMethod -Method Post -Uri http://localhost:5000/predict -ContentType "application/json" -Body '{"pressure_bar": 4.0, "flow_lpm": 5, "expected_pressure_bar": 4.0, "zone": "Z2", "sensor_id": "S44", "demand_peak_flag": 1, "segment_id": "SEG-044"}'
#
# blow off case
# Invoke-RestMethod -Method Post -Uri http://localhost:5000/predict -ContentType "application/json" -Body '{"pressure_bar": 0.5, "flow_lpm": 900, "expected_pressure_bar": 4.5, "zone": "Z3", "sensor_id": "VALVE-FLUSH-01", "demand_peak_flag": 0, "segment_id": "SEG-SCOUR-99", "estimated_loss_liters": 25000}'