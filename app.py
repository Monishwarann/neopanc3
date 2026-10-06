import os
import json
import urllib.request
import pickle
import numpy as np
import joblib
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from database import User, SensorReading, Questionnaire, ScreeningLog, db
from firebase_admin import auth
from functools import wraps
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pancreatic_risk_secret_key_135')

def verify_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        id_token = request.headers.get('Authorization')
        if not id_token:
            return jsonify({'message': 'Authorization token required'}), 401
        try:
            if id_token.startswith('Bearer '):
                id_token = id_token.split('Bearer ')[1]
            decoded_token = auth.verify_id_token(id_token)
            request.user = decoded_token
        except Exception as e:
            return jsonify({'message': 'Invalid token', 'error': str(e)}), 401
        return f(*args, **kwargs)
    return decorated_function

# Global variables for model and scaler
model = None
scaler = None
predictions_cache = {}

def load_ai_model():
    global model, scaler
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'model.pkl')
    scaler_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'scaler.pkl')
    
    if os.path.exists(model_path) and os.path.exists(scaler_path):
        try:
            model = joblib.load(model_path)
            scaler = joblib.load(scaler_path)
            print("AI Model and Scaler loaded successfully.")
        except Exception as e:
            print(f"Error loading AI model: {e}. Fallback to rule-based evaluation will be used.")
    else:
        print("AI model pickle files not found. Using fallback rule-based risk prediction.")



# UI Dashboard Route
@app.route('/')
def home():
    return render_template('index.html')

# API: Auth Routes
@app.route('/api/auth/register', methods=['POST'])
@verify_token
def register():
    data = request.get_json()
    uid = request.user['uid']
    email = request.user.get('email', data.get('email'))
    username = data.get('username', email.split('@')[0])
    
    User.create(uid=uid, username=username, email=email)
    return jsonify({'message': 'Registration successful', 'user_id': uid}), 201

@app.route('/api/auth/login', methods=['POST'])
@verify_token
def login():
    uid = request.user['uid']
    user = User.get_by_uid(uid)
    if not user:
        return jsonify({'message': 'User not found in database'}), 404
        
    return jsonify({
        'message': 'Login successful',
        'user_id': uid,
        'username': user.get('username'),
        'email': user.get('email')
    }), 200

# API: Profile Routes
@app.route('/api/profile/<user_id>', methods=['GET'])
@verify_token
def get_profile(user_id):
    if request.user['uid'] != user_id:
        return jsonify({'message': 'Unauthorized'}), 403
    user = User.get_by_uid(user_id)
    if not user:
        return jsonify({'message': 'User not found'}), 404
    return jsonify(user), 200

@app.route('/api/profile/<user_id>', methods=['PUT'])
@verify_token
def update_profile(user_id):
    if request.user['uid'] != user_id:
        return jsonify({'message': 'Unauthorized'}), 403
    data = request.get_json()
    if not data:
        return jsonify({'message': 'No data provided'}), 400
    success = User.update_profile(user_id, data)
    if success:
        return jsonify({'message': 'Profile updated successfully'}), 200
    return jsonify({'message': 'Failed to update profile'}), 500


# API: Telemetry Route (ESP32 Post / Web Simulator Post)
@app.route('/api/telemetry', methods=['POST'])
def save_telemetry():
    data = request.get_json()
    if not data or 'user_id' not in data:
        return jsonify({'message': 'User ID required'}), 400
        
    reading_id = SensorReading.create(
        user_id=data['user_id'],
        tds_raw=int(data.get('tds_raw', 0)),
        tds_voltage=float(data.get('tds_voltage', 0.0)),
        mq_raw=int(data.get('mq_raw', 0)),
        mq_voltage=float(data.get('mq_voltage', 0.0)),
        ph_raw=int(data.get('ph_raw', 0)),
        ph_voltage=float(data.get('ph_voltage', 0.0)),
        ph_value=float(data.get('ph_value', data.get('ph_voltage', 0.0)))
    )
    
    return jsonify({'message': 'Sensor reading saved successfully', 'id': reading_id}), 201

@app.route('/api/telemetry/latest/<user_id>', methods=['GET'])
def get_latest_telemetry(user_id):
    reading = SensorReading.get_latest(user_id)
    if not reading:
        return jsonify({'error': 'No real telemetry data available'}), 404
        
    return jsonify({
        'tds_raw': reading.get('tds_raw', 0),
        'tds_voltage': reading.get('tds_voltage', 0.0),
        'mq_raw': reading.get('mq_raw', 0),
        'mq_voltage': reading.get('mq_voltage', 0.0),
        'ph_raw': reading.get('ph_raw', 0),
        'ph_voltage': reading.get('ph_voltage', 0.0),
        'ph_value': reading.get('ph_value', reading.get('ph_voltage', 0.0)),
        'timestamp': reading.get('timestamp')
    }), 200

# Helper: PCRI Index Calculation
def calculate_pcri(tds_score, mq_score, ph_score, ai_score):
    pcri = (0.25 * tds_score) + (0.25 * mq_score) + (0.20 * ph_score) + (0.30 * ai_score)
    return round(max(0.0, min(100.0, pcri)), 1)

# API: Evaluate screening risk
@app.route('/api/predict', methods=['POST'])
def predict_risk():
    global model, scaler
    data = request.get_json()
    if not data or 'user_id' not in data:
        return jsonify({'message': 'User ID required'}), 400
        
    user_id = data['user_id']
    
    # 1. Fetch clinical survey values
    age = int(data.get('age', 40))
    bmi = float(data.get('bmi', 24.5))
    smoking = int(data.get('smoking_history', 0))
    alcohol = int(data.get('alcohol_consumption', 0))
    diabetes = int(data.get('diabetes', 0))
    family_history = int(data.get('family_history', 0))
    weight_loss = int(data.get('weight_loss', 0))
    pain = int(data.get('abdominal_pain', 0))
    appetite = int(data.get('appetite_changes', 0))
    jaundice = int(data.get('jaundice', 0))
    
    # Save the survey values
    Questionnaire.create(
        user_id=user_id, age=age, bmi=bmi, smoking=smoking,
        alcohol=alcohol, diabetes=diabetes, family_history=family_history,
        weight_loss=weight_loss, pain=pain, appetite=appetite, jaundice=jaundice
    )
    
    # 2. Get latest sensor reading (or fall back to passed telemetry parameters)
    latest_sensor = SensorReading.get_latest(user_id)
    
    tds_voltage = float(data.get('tds_voltage', latest_sensor.get('tds_voltage', 0.0) if latest_sensor else 0.0))
    mq_voltage = float(data.get('mq_voltage', latest_sensor.get('mq_voltage', 0.0) if latest_sensor else 0.0))
    ph_voltage = float(data.get('ph_voltage', latest_sensor.get('ph_voltage', 0.0) if latest_sensor else 0.0))
    ph_value = float(data.get('ph_value', latest_sensor.get('ph_value', ph_voltage) if latest_sensor else ph_voltage))
    
    # 3. Calculate individual PCRI Components
    tds_score = min(100.0, (tds_voltage / 3.3) * 100.0)
    mq_score = min(100.0, (mq_voltage / 3.3) * 100.0)
    ph_dev = abs(ph_value - 7.0) if ph_value > 0 else abs(ph_voltage - 1.65)
    ph_score = min(100.0, (ph_dev / 3.5) * 100.0)

    # 4. Predict via Machine Learning Model (RandomForest)
    ai_confidence = 50.0
    predicted_risk_class = 0
    ai_score = 15.0
    
    if model is None or scaler is None:
        load_ai_model()
        
    if model is not None and scaler is not None:
        try:
            feature_names = getattr(scaler, 'feature_names_in_', None)
            if feature_names is not None:
                row_dict = {}
                for f in feature_names:
                    if f in ['tds_voltage', 'tds_raw']: row_dict[f] = float(tds_voltage)
                    elif f in ['mq_voltage', 'mq_raw']: row_dict[f] = float(mq_voltage)
                    elif f in ['ph_voltage', 'ph_raw']: row_dict[f] = float(ph_voltage)
                    elif f in ['ph_value', 'saliva_ph']: row_dict[f] = float(ph_value)
                    elif f in ['saliva_ec']: row_dict[f] = float(tds_voltage)
                    elif f in ['mq135_ppm']: row_dict[f] = float(tds_voltage * 20)
                    elif f in ['mq3_ppm']: row_dict[f] = float(mq_voltage * 10)
                    elif f in ['mq7_ppm']: row_dict[f] = float(ph_voltage * 5)
                    elif f == 'age': row_dict[f] = float(age)
                    elif f == 'bmi': row_dict[f] = float(bmi)
                    elif f == 'smoking_history': row_dict[f] = float(smoking)
                    elif f == 'alcohol_consumption': row_dict[f] = float(alcohol)
                    elif f == 'diabetes': row_dict[f] = float(diabetes)
                    elif f == 'family_history': row_dict[f] = float(family_history)
                    elif f == 'weight_loss': row_dict[f] = float(weight_loss)
                    elif f == 'abdominal_pain': row_dict[f] = float(pain)
                    elif f == 'appetite_changes': row_dict[f] = float(appetite)
                    elif f == 'jaundice': row_dict[f] = float(jaundice)
                    else: row_dict[f] = 0.0
                query_df = pd.DataFrame([row_dict], columns=feature_names)
                scaled_input = scaler.transform(query_df)
                
                predicted_risk_class = int(model.predict(scaled_input)[0])
                prob = model.predict_proba(scaled_input)[0]
                
                val = float(prob[predicted_risk_class])
                if val > 1.0:
                    val = val / 100.0
                val = min(max(val, 0.0), 1.0)
                ai_confidence = round(val * 100, 2)
                
                ai_score = (prob[2] + 0.5 * prob[1]) * 100.0
                if ai_score > 100.0:
                    ai_score = ai_score / 100.0
            
        except Exception as e:
            print(f"AI Prediction error: {e}. Fallback used.")
            ai_score = 15.0
            if age > 60: ai_score += 15.0
            if diabetes: ai_score += 15.0
            if jaundice: ai_score += 35.0
            if family_history: ai_score += 20.0
            ai_score = min(ai_score, 100.0)
            ai_confidence = 100.0
    else:
        ai_score = 15.0
        if age > 60: ai_score += 15.0
        if diabetes: ai_score += 15.0
        if jaundice: ai_score += 35.0
        if family_history: ai_score += 20.0
        ai_score = min(ai_score, 100.0)
        ai_confidence = 100.0
        
    # Final combined score
    pcri_score = calculate_pcri(tds_score, mq_score, ph_score, ai_score)
    
    # Categorize Risk
    if pcri_score <= 40.0:
        risk_level = 'Low'
        rec = "Screening indicates low risk. Maintain healthy diet (high fiber, low saturated fats), regular exercise, and avoid smoking. Repeat screening in 6 months for preventive tracking."
    elif pcri_score <= 70.0:
        risk_level = 'Moderate'
        rec = "Screening suggests moderate risk profile. Recommend consultation with a healthcare provider to review metabolic panels, dietary adjustments, and active blood sugar tracking. Repeat screening in 3 months."
    else:
        risk_level = 'High'
        rec = "Screening reveals high risk indicators. Immediate clinical consultation is strongly recommended. Suggest discussing blood markers (CA19-9), abdominal ultrasound or MRI scans, and pancreatic enzyme assessments with a specialist."
    # Save the Screening Log
    log_id = ScreeningLog.create(
        user_id=user_id,
        pcri_score=pcri_score,
        risk_level=risk_level,
        ai_confidence=ai_confidence,
        recommendations=rec
    )
    
    # Generate fallback ID and save to cache if Realtime Database write failed
    if not log_id:
        import uuid
        log_id = "fb_" + str(uuid.uuid4())[:8]
        
    predictions_cache[log_id] = {
        'id': log_id,
        'user_id': user_id,
        'pcri_score': pcri_score,
        'risk_level': risk_level,
        'ai_confidence': ai_confidence,
        'recommendations': rec,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    return jsonify({
        'log_id': log_id,
        'pcri_score': pcri_score,
        'risk_level': risk_level,
        'ai_confidence': ai_confidence,
        'recommendations': rec,
        'components': {
            'tds_voltage_score': round(tds_score, 1),
            'mq_voltage_score': round(mq_score, 1),
            'ph_score': round(ph_score, 1),
            'ai_prediction_score': round(ai_score, 1)
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200

# API: Get User Statistics
@app.route('/api/stats/<user_id>', methods=['GET'])
def get_user_stats(user_id):
    try:
        user_data = User.get_by_uid(user_id)
        if not user_data:
            return jsonify({'error': 'User not found'}), 404
            
        created_at = user_data.get('created_at', datetime.utcnow().isoformat())
        last_active = user_data.get('last_active', created_at)
        
        # Update last_active on stats fetch
        try:
            User.update_profile(user_id, {'last_active': datetime.utcnow().isoformat()})
        except Exception:
            pass
        
        # Fetch all screening logs for this user
        logs = ScreeningLog.get_by_user(user_id, limit=1000)
        
        total_tests = len(logs)
        positive_predictions = sum(1 for log in logs if log.get('risk_level') == 'High')
        negative_predictions = total_tests - positive_predictions
        
        avg_confidence = 0.0
        if total_tests > 0:
            avg_confidence = sum(log.get('ai_confidence', 0.0) for log in logs) / total_tests
            
        logs.sort(key=lambda d: d.get('timestamp', ''), reverse=True)
        last_prediction_date = logs[0].get('timestamp') if total_tests > 0 else None
        last_prediction_result = logs[0].get('risk_level') if total_tests > 0 else None
        
        # Fetch last sensor reading time
        latest_sensor = SensorReading.get_latest(user_id)
        last_sensor_reading = latest_sensor.get('timestamp') if latest_sensor else None
        
        return jsonify({
            'total_tests': total_tests,
            'positive_predictions': positive_predictions,
            'negative_predictions': negative_predictions,
            'average_confidence': round(avg_confidence, 1),
            'last_prediction_date': last_prediction_date,
            'last_prediction_result': last_prediction_result,
            'last_sensor_reading': last_sensor_reading,
            'account_created_date': created_at,
            'last_active_date': last_active
        }), 200
    except Exception as e:
        print(f"Error fetching user stats: {e}")
        # Return fallback stats so the frontend dashboard doesn't crash or error out
        now_str = datetime.utcnow().isoformat()
        return jsonify({
            'total_tests': 0,
            'positive_predictions': 0,
            'negative_predictions': 0,
            'average_confidence': 0.0,
            'last_prediction_date': None,
            'last_prediction_result': None,
            'last_sensor_reading': None,
            'account_created_date': now_str,
            'last_active_date': now_str,
            'fallback': True,
            'error_details': str(e)
        }), 200

# API: Live prediction for dashboard (no DB writes)
@app.route('/api/predict/live/<user_id>', methods=['GET'])
def predict_live(user_id):
    global model, scaler
    
    # 1. Get latest sensor reading
    latest_sensor = SensorReading.get_latest(user_id)
    if not latest_sensor:
        return jsonify({'error': 'No real telemetry data available'}), 404
        
    tds_voltage = float(latest_sensor.get('tds_voltage', 0.0))
    mq_voltage = float(latest_sensor.get('mq_voltage', 0.0))
    ph_voltage = float(latest_sensor.get('ph_voltage', 0.0))
    ph_value = float(latest_sensor.get('ph_value', ph_voltage))
    
    # 2. Fetch clinical survey values from user profile
    profile = {}
    try:
        user_data = User.get_by_uid(user_id)
        if user_data:
            profile = user_data
    except Exception as e:
        print(f"Error fetching user profile in predict_live: {e}")
        
    age = int(profile.get('age', 40))
    
    smoking = 0
    diabetes = 0
    jaundice = 0
    weight_loss = 0
    family_history = 0
    
    # 3. Calculate individual PCRI Components
    tds_score = min(100.0, (tds_voltage / 3.3) * 100.0)
    mq_score = min(100.0, (mq_voltage / 3.3) * 100.0)
    ph_dev = abs(ph_value - 7.0) if ph_value > 0 else abs(ph_voltage - 1.65)
    ph_score = min(100.0, (ph_dev / 3.5) * 100.0)

    # 4. Predict via Machine Learning Model (RandomForest)
    ai_confidence = 50.0
    predicted_risk_class = 0
    ai_score = 15.0
    
    if model is None or scaler is None:
        load_ai_model()
        
    if model is not None and scaler is not None:
        try:
            feature_names = getattr(scaler, 'feature_names_in_', None)
            if feature_names is not None:
                row_dict = {}
                for f in feature_names:
                    if f in ['tds_voltage', 'tds_raw']: row_dict[f] = float(tds_voltage)
                    elif f in ['mq_voltage', 'mq_raw']: row_dict[f] = float(mq_voltage)
                    elif f in ['ph_voltage', 'ph_raw']: row_dict[f] = float(ph_voltage)
                    elif f in ['ph_value', 'saliva_ph']: row_dict[f] = float(ph_value)
                    elif f in ['saliva_ec']: row_dict[f] = float(tds_voltage)
                    elif f in ['mq135_ppm']: row_dict[f] = float(tds_voltage * 20)
                    elif f in ['mq3_ppm']: row_dict[f] = float(mq_voltage * 10)
                    elif f in ['mq7_ppm']: row_dict[f] = float(ph_voltage * 5)
                    elif f == 'age': row_dict[f] = float(age)
                    elif f == 'bmi': row_dict[f] = float(profile.get('bmi', 24.5))
                    elif f == 'smoking_history': row_dict[f] = float(smoking)
                    elif f == 'alcohol_consumption': row_dict[f] = float(profile.get('alcohol_consumption', 0))
                    elif f == 'diabetes': row_dict[f] = float(diabetes)
                    elif f == 'family_history': row_dict[f] = float(family_history)
                    elif f == 'weight_loss': row_dict[f] = float(weight_loss)
                    elif f == 'abdominal_pain': row_dict[f] = float(profile.get('abdominal_pain', 0))
                    elif f == 'appetite_changes': row_dict[f] = float(profile.get('appetite_changes', 0))
                    elif f == 'jaundice': row_dict[f] = float(jaundice)
                    else: row_dict[f] = 0.0
                query_df = pd.DataFrame([row_dict], columns=feature_names)
                scaled_input = scaler.transform(query_df)
                
                predicted_risk_class = int(model.predict(scaled_input)[0])
                prob = model.predict_proba(scaled_input)[0]
                
                ai_confidence = round(float(prob[predicted_risk_class]) * 100, 2)
                ai_score = (prob[2] + 0.5 * prob[1]) * 100.0
            
        except Exception as e:
            print(f"AI Live Prediction error: {e}")
            ai_score = 15.0
            if age > 60: ai_score += 15.0
            ai_score = min(ai_score, 100.0)
            ai_confidence = 100.0
    else:
        ai_score = 15.0
        if age > 60: ai_score += 15.0
        ai_score = min(ai_score, 100.0)
        ai_confidence = 100.0
        
    pcri_score = calculate_pcri(tds_score, mq_score, ph_score, ai_score)
    
    if pcri_score <= 40.0:
        risk_level = 'Low'
    elif pcri_score <= 70.0:
        risk_level = 'Moderate'
    else:
        risk_level = 'High'
        
    # Note: No ScreenLog or Questionnaire is saved here.
    
    return jsonify({
        'pcri_score': pcri_score,
        'risk_level': risk_level,
        'ai_confidence': ai_confidence,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200

# Feature names in the exact order used for the new RandomForest AI model
FEATURES = [
    'age',
    'bmi',
    'smoking_history',
    'alcohol_consumption',
    'diabetes',
    'family_history',
    'weight_loss',
    'abdominal_pain',
    'appetite_changes',
    'jaundice',
    'mq135_ppm',
    'mq3_ppm',
    'mq7_ppm',
    'saliva_ph',
    'saliva_ec'
]

# Class labels
LABELS = {
    0: "Healthy",
    1: "Benign",
    2: "Pancreatic Cancer"
}

@app.route("/predict", methods=["POST"])
def predict():
    try:
        # Read JSON data
        data = request.get_json()

        # Check if JSON exists
        if data is None:
            return jsonify({
                "error": "No JSON data received."
            }), 400

        # Check for missing features
        missing_features = [feature for feature in FEATURES if feature not in data]

        if missing_features:
            return jsonify({
                "error": "Missing required features.",
                "missing_features": missing_features
            }), 400

        # Create DataFrame from input
        query_df = pd.DataFrame([data])

        # Ensure columns are in the correct order
        query_df = query_df[FEATURES]

        # Make prediction
        if model is None or scaler is None:
            return jsonify({
                "error": "AI model is not loaded on the server."
            }), 500

        scaled_input = scaler.transform(query_df)
        prediction = model.predict(scaled_input)
        predicted_class = int(prediction[0])

        # Predict probabilities if available
        probabilities = None
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(scaled_input)[0].tolist()

        # Return response
        return jsonify({
            "prediction": predicted_class,
            "prediction_label": LABELS.get(predicted_class, "Unknown"),
            "probabilities": probabilities,
            "message": "Prediction successful"
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

# API: Historical trend
@app.route('/api/history/<user_id>', methods=['GET'])
def get_history(user_id):
    history = ScreeningLog.get_by_user(user_id)
    return jsonify(history), 200

# API: Generate and download screening report PDF
@app.route('/api/generate-pdf/<log_id>', methods=['GET', 'POST'])
def generate_pdf(log_id):
    if request.method == 'POST':
        log = request.get_json() or {}
    else:
        log = ScreeningLog.get_by_id(log_id)
        if not log:
            log = predictions_cache.get(log_id)
            
    if not log: return jsonify({'error': 'No log found'}), 404
    
    user_id = log.get('user_id') or log.get('userId')
    user = User.get_by_uid(user_id) or {'username': 'Unknown', 'email': 'Unknown'}
    
    # Just grab latest for PDF
    sensors = log.get('sensors') or SensorReading.get_latest(user_id) or {}
    survey = log.get('survey') or Questionnaire.get_latest(user_id) or {}
    
    # Safe date and time parsing
    log_ts_str = log.get('timestamp') or log.get('predictionTimestamp') or datetime.utcnow().isoformat()
    log_ts_str = log_ts_str.replace('Z', '')
    if '.' in log_ts_str:
        log_ts_str = log_ts_str.split('.')[0]
    try:
        log_dt = datetime.fromisoformat(log_ts_str)
    except Exception:
        log_dt = datetime.utcnow()
        
    timezone_name = log.get('timezone', 'UTC')
    device_tz_offset = log.get('deviceTimeZoneOffset', '+00:00')
    
    # Generated Date & Time (Current Server / Device time)
    gen_dt = datetime.now()
    gen_date_str = gen_dt.strftime('%d %B %Y')
    gen_time_str = gen_dt.strftime('%I:%M:%S %p')
    
    # Prediction Date & Time
    pred_date_str = log_dt.strftime('%d %B %Y')
    pred_time_str = log_dt.strftime('%I:%M:%S %p')
    
    pdf_filename = f"PCRI_Report_Log_{log.get('id', 'new')}.pdf"
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    story = []
    
    # Styling
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=12
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.gray,
        spaceAfter=20
    )
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=colors.HexColor('#2563EB'),
        spaceBefore=12,
        spaceAfter=8,
        borderPadding=2
    )
    body_style = styles['Normal']
    alert_style = ParagraphStyle(
        'Alert',
        parent=styles['Normal'],
        fontSize=11,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )
    
    # Document Header
    story.append(Paragraph("PANCREATIC CANCER RISK ASSESSMENT REPORT", title_style))
    story.append(Paragraph(f"AI-driven Multi-Sensor Early Screening System • Generated on: {gen_date_str} {gen_time_str}", subtitle_style))
    story.append(Spacer(1, 10))
    
    # Patient Info Table
    info_data = [
        [Paragraph("<b>Patient Username:</b>", body_style), Paragraph(user.get('username', 'N/A'), body_style),
         Paragraph("<b>Email:</b>", body_style), Paragraph(user.get('email', 'N/A'), body_style)],
        [Paragraph("<b>Age:</b>", body_style), Paragraph(str(survey.get('age', 'N/A')) if survey else "N/A", body_style),
         Paragraph("<b>BMI:</b>", body_style), Paragraph(str(survey.get('bmi', 'N/A')) if survey else "N/A", body_style)]
    ]
    info_table = Table(info_data, colWidths=[120, 130, 100, 150])
    info_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB'))
    ]))
    story.append(info_table)
    story.append(Spacer(1, 15))
    
    # Screening Summary (Colored risk box)
    risk_color = '#EF4444' if log.get('risk_level', 'Low') == 'High' else ('#F59E0B' if log.get('risk_level', 'Low') == 'Moderate' else '#10B981')
    risk_summary_data = [
        [Paragraph(f"PCRI SCORE: {log.get('pcri_score', 0)} / 100", alert_style), 
         Paragraph(f"RISK LEVEL: {log.get('risk_level', 'Low').upper()}", alert_style),
         Paragraph(f"AI CONFIDENCE: {log.get('ai_confidence', 0)}%", alert_style)]
    ]
    risk_table = Table(risk_summary_data, colWidths=[160, 170, 170])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(risk_color)),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))
    story.append(risk_table)
    story.append(Spacer(1, 15))
    
    # Biomarker Reading
    story.append(Paragraph("Biomarker and Sensor Readings", section_style))
    sensor_data = [
        [Paragraph("<b>Physical Sensor Channel</b>", body_style), Paragraph("<b>Raw ADC Value</b>", body_style), Paragraph("<b>Voltage Reading</b>", body_style)],
        [Paragraph("TDS Sensor (GPIO 32)", body_style), Paragraph(f"{sensors.get('tds_raw', '--') if sensors else '--'}", body_style), Paragraph(f"{sensors.get('tds_voltage', '--') if sensors else '--'} V", body_style)],
        [Paragraph("MQ Gas Sensor (GPIO 33)", body_style), Paragraph(f"{sensors.get('mq_raw', '--') if sensors else '--'}", body_style), Paragraph(f"{sensors.get('mq_voltage', '--') if sensors else '--'} V", body_style)],
        [Paragraph("pH Sensor (GPIO 34)", body_style), Paragraph(f"{sensors.get('ph_raw', '--') if sensors else '--'}", body_style), Paragraph(f"{sensors.get('ph_voltage', '--') if sensors else '--'} V", body_style)]
    ]
    sensor_table = Table(sensor_data, colWidths=[200, 150, 150])
    sensor_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')])
    ]))
    story.append(sensor_table)
    story.append(Spacer(1, 15))
    
    # Clinical Symptoms Checklist
    story.append(Paragraph("Clinical Risk Checklist", section_style))
    def yes_no(val):
        return "Yes" if val == 1 else "No"
    
    symp_data = [
        [Paragraph("<b>Risk Metric</b>", body_style), Paragraph("<b>Status</b>", body_style),
         Paragraph("<b>Risk Metric</b>", body_style), Paragraph("<b>Status</b>", body_style)],
        [Paragraph("Smoking History", body_style), Paragraph(yes_no(survey.get('smoking_history', 0)) if survey else "No", body_style),
         Paragraph("Diabetes History", body_style), Paragraph(yes_no(survey.get('diabetes', 0)) if survey else "No", body_style)],
        [Paragraph("Family Cancer History", body_style), Paragraph(yes_no(survey.get('family_history', 0)) if survey else "No", body_style),
         Paragraph("Unexplained Weight Loss", body_style), Paragraph(yes_no(survey.get('weight_loss', 0)) if survey else "No", body_style)],
        [Paragraph("Abdominal Pain (Back-radiating)", body_style), Paragraph(yes_no(survey.get('abdominal_pain', 0)) if survey else "No", body_style),
         Paragraph("Jaundice (Skin/Eye Yellowing)", body_style), Paragraph(yes_no(survey.get('jaundice', 0)) if survey else "No", body_style)]
    ]
    symp_table = Table(symp_data, colWidths=[160, 90, 160, 90])
    symp_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB'))
    ]))
    story.append(symp_table)
    story.append(Spacer(1, 15))
    
    # Recommendations
    story.append(Paragraph("Clinical Recommendations", section_style))
    story.append(Paragraph(log.get('recommendations', ''), body_style))
    story.append(Spacer(1, 15))
    
    # Report Metadata Block
    story.append(Paragraph("Report Verification & System Timestamps", section_style))
    meta_data = [
        [Paragraph("<b>Report Number:</b>", body_style), Paragraph(str(log.get('id') or log_id), body_style),
         Paragraph("<b>Local Time Zone:</b>", body_style), Paragraph(f"{timezone_name} ({device_tz_offset})", body_style)],
        [Paragraph("<b>Prediction Date:</b>", body_style), Paragraph(pred_date_str, body_style),
         Paragraph("<b>Prediction Time:</b>", body_style), Paragraph(pred_time_str, body_style)],
        [Paragraph("<b>Generated Date:</b>", body_style), Paragraph(gen_date_str, body_style),
         Paragraph("<b>Generated Time:</b>", body_style), Paragraph(gen_time_str, body_style)]
    ]
    meta_table = Table(meta_data, colWidths=[120, 130, 120, 130])
    meta_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('PADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F4F6'))
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))
    
    # Disclaimer
    story.append(Paragraph("<b>Disclaimer:</b> This system is designed as an AI-driven, multi-sensor early non-invasive screening aid for estimating risk metrics. It does not replace a clinical diagnosis. Pancreatic cancer screenings must be confirmed using standard hospital pathology tests (MRI, CT Scan, biopsy, and serum CA19-9 tests) under a physician's guidance.", ParagraphStyle('Disc', parent=body_style, fontSize=8, textColor=colors.HexColor('#4B5563'))))
    
    # Build Document
    doc.build(story)
    
    return send_file(pdf_path, as_attachment=True)

def keep_alive():
    import urllib.request
    import time
    time.sleep(30)
    url = os.environ.get('RENDER_EXTERNAL_URL', 'https://neopanc3.onrender.com')
    ping_url = f"{url.rstrip('/')}/api/status"
    print(f"Starting keep-alive background thread pinging: {ping_url}")
    while True:
        try:
            req = urllib.request.Request(ping_url, headers={'User-Agent': 'NeoPanc-KeepAlive'})
            with urllib.request.urlopen(req, timeout=10) as response:
                print(f"Keep-alive ping to {ping_url} status: {response.status}")
        except Exception as e:
            print(f"Keep-alive ping failed: {e}")
        time.sleep(300)

import threading
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    # Initial load of AI model
    load_ai_model()
    
    # Retrieve port dynamically for cloud environments
    port = int(os.environ.get('PORT', 5000))
    # Turn off debug mode in production to ensure safety
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
