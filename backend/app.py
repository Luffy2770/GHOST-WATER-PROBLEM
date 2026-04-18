import pandas as pd
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────
# LOAD MODEL + DATASET ON STARTUP
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