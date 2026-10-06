import os
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db, auth

# Initialize Firebase Admin SDK for Realtime Database
cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'serviceAccountKey.json')
database_url = os.environ.get('FIREBASE_DATABASE_URL') or 'https://neopanc-379bf-default-rtdb.asia-southeast1.firebasedatabase.app'

try:
    if not firebase_admin._apps:
        # Check if environment variable contains Firebase JSON
        firebase_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY') or os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_json:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
            print("Firebase Admin initialized via FIREBASE_SERVICE_ACCOUNT_KEY environment variable.")
        elif os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
            print("Firebase Admin initialized via serviceAccountKey.json.")
        else:
            firebase_admin.initialize_app(options={'databaseURL': database_url})
            print("Firebase Admin initialized via default credentials.")
except Exception as e:
    print(f"Failed to initialize Firebase Admin: {e}")

def _get_root_ref():
    """Returns root DB reference safely if Firebase is initialized."""
    try:
        return db.reference()
    except Exception as e:
        print(f"Error accessing Realtime Database reference: {e}")
        return None

class User:
    @staticmethod
    def create(uid, username, email):
        root = _get_root_ref()
        if not root: return None
        user_data = {
            'username': username,
            'email': email,
            'created_at': datetime.utcnow().isoformat()
        }
        try:
            db.reference(f'users/{uid}').update(user_data)
            return uid
        except Exception as e:
            print(f"Error creating user in RTDB: {e}")
            return None
        
    @staticmethod
    def get_by_uid(uid):
        root = _get_root_ref()
        if not root: return None
        try:
            data = db.reference(f'users/{uid}').get()
            if data and isinstance(data, dict):
                data_copy = dict(data)
                data_copy['id'] = uid
                return data_copy
        except Exception as e:
            print(f"Error getting user by uid from RTDB: {e}")
        return None

    @staticmethod
    def get_by_email(email):
        root = _get_root_ref()
        if not root: return None
        try:
            # Query by child 'email'
            snapshot = db.reference('users').order_by_child('email').equal_to(email).get()
            if snapshot and isinstance(snapshot, dict):
                for uid, user_record in snapshot.items():
                    if isinstance(user_record, dict):
                        user_copy = dict(user_record)
                        user_copy['id'] = uid
                        return user_copy
        except Exception as e:
            print(f"Error getting user by email from RTDB: {e}")
        return None

    @staticmethod
    def update_profile(uid, data):
        root = _get_root_ref()
        if not root: return False
        try:
            db.reference(f'users/{uid}').update(data)
            return True
        except Exception as e:
            print(f"Error updating profile in RTDB: {e}")
            return False

class SensorReading:
    @staticmethod
    def create(user_id, tds_raw=0, tds_voltage=0.0, mq_raw=0, mq_voltage=0.0, ph_raw=0, ph_voltage=0.0, ph_value=0.0):
        root = _get_root_ref()
        if not root: return None
        timestamp_str = datetime.utcnow().isoformat() + 'Z'
        data = {
            'user_id': str(user_id),
            'userId': str(user_id),
            'tds_raw': tds_raw,
            'tds_voltage': tds_voltage,
            'mq_raw': mq_raw,
            'mq_voltage': mq_voltage,
            'ph_raw': ph_raw,
            'ph_voltage': ph_voltage,
            'ph_value': ph_value,
            'ph': ph_value,
            'timestamp': timestamp_str
        }
        try:
            # 1. Update latest sensor reading for instantaneous O(1) query and real-time dashboard listeners
            db.reference(f'sensorData/{user_id}/latest').set(data)
            
            # 2. Append to user history with push ID
            hist_ref = db.reference(f'sensorData/{user_id}/history').push()
            reading_id = hist_ref.key
            data['id'] = reading_id
            hist_ref.set(data)
            
            # 3. Save to global sensor_readings for compatibility
            db.reference(f'sensor_readings/{reading_id}').set(data)
            return reading_id
        except Exception as e:
            print(f"Error creating sensor reading in RTDB: {e}")
            return None

    @staticmethod
    def get_latest(user_id):
        root = _get_root_ref()
        if not root: return None
        try:
            # Fast O(1) fetch from sensorData/{user_id}/latest
            latest = db.reference(f'sensorData/{user_id}/latest').get()
            if latest and isinstance(latest, dict):
                return latest

            # Fallback: check history limit to last
            history = db.reference(f'sensorData/{user_id}/history').order_by_child('timestamp').limit_to_last(1).get()
            if history and isinstance(history, dict):
                for key, val in history.items():
                    if isinstance(val, dict):
                        val_copy = dict(val)
                        val_copy['id'] = key
                        return val_copy
            return None
        except Exception as e:
            print(f"Error fetching latest reading from RTDB: {e}")
            return None

class Questionnaire:
    @staticmethod
    def create(user_id, age, bmi, smoking, alcohol, diabetes, family_history, weight_loss, pain, appetite, jaundice):
        root = _get_root_ref()
        if not root: return None
        data = {
            'user_id': str(user_id),
            'userId': str(user_id),
            'age': age,
            'bmi': bmi,
            'smoking_history': smoking,
            'alcohol_consumption': alcohol,
            'diabetes': diabetes,
            'family_history': family_history,
            'weight_loss': weight_loss,
            'abdominal_pain': pain,
            'appetite_changes': appetite,
            'jaundice': jaundice,
            'timestamp': datetime.utcnow().isoformat()
        }
        try:
            # Save latest
            db.reference(f'questionnaires/{user_id}/latest').set(data)
            # Push to history
            push_ref = db.reference(f'questionnaires/{user_id}/history').push()
            data['id'] = push_ref.key
            push_ref.set(data)
            return push_ref.key
        except Exception as e:
            print(f"Error creating questionnaire in RTDB: {e}")
            return None
        
    @staticmethod
    def get_latest(user_id):
        root = _get_root_ref()
        if not root: return None
        try:
            latest = db.reference(f'questionnaires/{user_id}/latest').get()
            if latest and isinstance(latest, dict):
                return latest
            hist = db.reference(f'questionnaires/{user_id}/history').order_by_child('timestamp').limit_to_last(1).get()
            if hist and isinstance(hist, dict):
                for key, val in hist.items():
                    if isinstance(val, dict):
                        return val
            return None
        except Exception as e:
            print(f"Error fetching questionnaire from RTDB: {e}")
            return None

class ScreeningLog:
    @staticmethod
    def create(user_id, pcri_score, risk_level, ai_confidence, recommendations):
        root = _get_root_ref()
        if not root: return None
        try:
            log_ref = db.reference('screening_logs').push()
            log_id = log_ref.key
            now_iso = datetime.utcnow().isoformat()
            data = {
                'id': log_id,
                'log_id': log_id,
                'reportId': log_id,
                'user_id': str(user_id),
                'userId': str(user_id),
                'pcri_score': pcri_score,
                'risk_level': risk_level,
                'ai_confidence': ai_confidence,
                'recommendations': recommendations,
                'timestamp': now_iso,
                'predictionTimestamp': now_iso,
            }
            log_ref.set(data)
            # Synchronize with users/{user_id}/predictionHistory/{log_id} so Flutter app real-time streams update immediately
            db.reference(f'users/{user_id}/predictionHistory/{log_id}').set(data)
            return log_id
        except Exception as e:
            print(f"Error creating screening log in RTDB: {e}")
            return None
        
    @staticmethod
    def get_by_user(user_id, limit=5):
        root = _get_root_ref()
        if not root: return []
        try:
            # 1. First check user's predictionHistory node
            history_snap = db.reference(f'users/{user_id}/predictionHistory').get()
            results = []
            if history_snap and isinstance(history_snap, dict):
                for key, val in history_snap.items():
                    if isinstance(val, dict):
                        val_copy = dict(val)
                        val_copy['id'] = key
                        results.append(val_copy)
            else:
                # 2. Check global screening_logs indexed by user_id
                logs_snap = db.reference('screening_logs').order_by_child('user_id').equal_to(str(user_id)).get()
                if logs_snap and isinstance(logs_snap, dict):
                    for key, val in logs_snap.items():
                        if isinstance(val, dict):
                            val_copy = dict(val)
                            val_copy['id'] = key
                            results.append(val_copy)

            results.sort(key=lambda d: str(d.get('timestamp') or d.get('predictionTimestamp') or ''), reverse=True)
            return results[:limit]
        except Exception as e:
            print(f"Error fetching screening logs from RTDB: {e}")
            return []

    @staticmethod
    def get_by_id(log_id):
        root = _get_root_ref()
        if not root: return None
        try:
            data = db.reference(f'screening_logs/{log_id}').get()
            if data and isinstance(data, dict):
                data_copy = dict(data)
                data_copy['id'] = log_id
                return data_copy
            return None
        except Exception as e:
            print(f"Error fetching screening log by id from RTDB: {e}")
            return None
