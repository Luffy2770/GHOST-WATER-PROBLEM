import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, accuracy_score
import joblib
import warnings
warnings.filterwarnings('ignore')

print("="*50)
print("  NRW DETECTION SYSTEM - MODEL TRAINING")
print("="*50)

# ─────────────────────────────────────────
# STEP 1 - LOAD DATA
# ─────────────────────────────────────────
print("\n[1/6] Loading dataset...")
df = pd.read_excel("TS-PS10.xlsx")
print(f"      Loaded {len(df)} rows, {len(df.columns)} columns")

# ─────────────────────────────────────────
# STEP 2 - CLEAN DATA
# ─────────────────────────────────────────
print("\n[2/6] Cleaning data...")

# drop rows where key columns are missing
df = df.dropna(subset=[
    'pressure_bar',
    'flow_lpm',
    'expected_pressure_bar',
    'anomaly',
    'nrw_type'
])

# fill remaining nulls with 0
df['demand_peak_flag'] = df['demand_peak_flag'].fillna(0)
df['estimated_loss_liters'] = df['estimated_loss_liters'].fillna(0)

# clean nrw_type — strip spaces, lowercase
df['nrw_type'] = df['nrw_type'].str.strip().str.lower()

print(f"      Clean rows remaining: {len(df)}")
print(f"      NRW types found: {df['nrw_type'].unique().tolist()}")
print(f"      Anomaly distribution:\n{df['anomaly'].value_counts().to_string()}")

# ─────────────────────────────────────────
# STEP 3 - FEATURE ENGINEERING
# ─────────────────────────────────────────
print("\n[3/6] Engineering features...")

# pressure deviation from expected
df['pressure_deviation'] = df['expected_pressure_bar'] - df['pressure_bar']

# percentage deviation
df['deviation_pct'] = (df['pressure_deviation'] / df['expected_pressure_bar']) * 100

# flow to pressure ratio
df['flow_pressure_ratio'] = df['flow_lpm'] / (df['pressure_bar'] + 0.001)

# encode zone (Z1, Z2, Z3 → 1, 2, 3)
df['zone_encoded'] = df['zone'].str.extract(r'(\d+)').astype(int)

print("      Features created:")
print("        pressure_deviation, deviation_pct, flow_pressure_ratio, zone_encoded")

# ─────────────────────────────────────────
# STEP 4 - TRAIN ANOMALY DETECTION MODEL
# ─────────────────────────────────────────
print("\n[4/6] Training anomaly detection model...")

# features used for anomaly detection
anomaly_features = [
    'pressure_bar',
    'flow_lpm',
    'expected_pressure_bar',
    'pressure_deviation',
    'deviation_pct',
    'flow_pressure_ratio',
    'zone_encoded',
    'demand_peak_flag'
]

X_anomaly = df[anomaly_features]
y_anomaly = df['anomaly'].astype(int)

X_train_a, X_test_a, y_train_a, y_test_a = train_test_split(
    X_anomaly, y_anomaly, test_size=0.2, random_state=42
)

anomaly_model = RandomForestClassifier(
    n_estimators=100,
    random_state=42,
    class_weight='balanced'
)
anomaly_model.fit(X_train_a, y_train_a)

anomaly_preds = anomaly_model.predict(X_test_a)
anomaly_accuracy = accuracy_score(y_test_a, anomaly_preds)
print(f"      Anomaly Detection Accuracy: {anomaly_accuracy*100:.2f}%")

# ─────────────────────────────────────────
# STEP 5 - TRAIN NRW CLASSIFICATION MODEL
# ─────────────────────────────────────────
print("\n[5/6] Training NRW classification model...")

# only train classifier on actual anomaly rows
df_anomaly = df[df['anomaly'] == 1].copy()
print(f"      Anomaly rows for classifier: {len(df_anomaly)}")
print(f"      Class distribution:\n{df_anomaly['nrw_type'].value_counts().to_string()}")

# features for classification
classify_features = [
    'pressure_bar',
    'flow_lpm',
    'expected_pressure_bar',
    'pressure_deviation',
    'deviation_pct',
    'flow_pressure_ratio',
    'zone_encoded',
    'demand_peak_flag',
    'estimated_loss_liters'
]

# encode nrw_type labels
label_encoder = LabelEncoder()
df_anomaly['nrw_type_encoded'] = label_encoder.fit_transform(df_anomaly['nrw_type'])

X_classify = df_anomaly[classify_features]
y_classify = df_anomaly['nrw_type_encoded']

X_train_c, X_test_c, y_train_c, y_test_c = train_test_split(
    X_classify, y_classify, test_size=0.2, random_state=42
)

classify_model = RandomForestClassifier(
    n_estimators=100,
    random_state=42,
    class_weight='balanced'
)
classify_model.fit(X_train_c, y_train_c)

classify_preds = classify_model.predict(X_test_c)
classify_accuracy = accuracy_score(y_test_c, classify_preds)
print(f"      NRW Classification Accuracy: {classify_accuracy*100:.2f}%")
print(f"\n      Classification Report:")
print(classification_report(
    y_test_c,
    classify_preds,
    target_names=label_encoder.classes_
))

# ─────────────────────────────────────────
# STEP 6 - SAVE EVERYTHING
# ─────────────────────────────────────────
print("\n[6/6] Saving model...")

model_bundle = {
    'anomaly_model':    anomaly_model,
    'classify_model':   classify_model,
    'label_encoder':    label_encoder,
    'anomaly_features': anomaly_features,
    'classify_features': classify_features,
    'nrw_classes':      label_encoder.classes_.tolist()
}

joblib.dump(model_bundle, 'model.pkl')
print("      Saved: model.pkl")

print("\n" + "="*50)
print("  TRAINING COMPLETE")
print(f"  Anomaly Accuracy:  {anomaly_accuracy*100:.2f}%")
print(f"  Classify Accuracy: {classify_accuracy*100:.2f}%")
print(f"  NRW Types:         {label_encoder.classes_.tolist()}")
print("  model.pkl is ready for app.py")
print("="*50)