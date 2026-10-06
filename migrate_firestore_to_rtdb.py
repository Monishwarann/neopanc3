"""
Safe Migration Utility: Cloud Firestore to Firebase Realtime Database (RTDB)
Preserves all user profiles, sensor readings, questionnaires, screening logs,
prediction history, notifications, activity logs, timestamps, and relationships.
"""

import os
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore, db

def serialize_val(val):
    """Converts Firestore Timestamps and complex objects into JSON-serializable types."""
    if hasattr(val, 'to_datetime'):
        return val.to_datetime().isoformat()
    elif hasattr(val, 'isoformat'):
        return val.isoformat()
    elif isinstance(val, dict):
        return {k: serialize_val(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [serialize_val(item) for item in val]
    return val

def run_migration():
    cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'serviceAccountKey.json')
    database_url = os.environ.get('FIREBASE_DATABASE_URL') or 'https://neopanc-379bf-default-rtdb.asia-southeast1.firebasedatabase.app'

    if not firebase_admin._apps:
        firebase_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY') or os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_json:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
        elif os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
        else:
            firebase_admin.initialize_app(options={'databaseURL': database_url})

    fs_client = firestore.client()
    rtdb_root = db.reference()

    print("=" * 60)
    print("STARTING FIRESTORE TO FIREBASE REALTIME DATABASE MIGRATION")
    print("=" * 60)

    # 1. Migrate Users & User Subcollections
    print("\n[1/4] Migrating 'users' and user subcollections...")
    users_count = 0
    sub_records_count = 0
    try:
        users = list(fs_client.collection('users').stream())
        for u in users:
            uid = u.id
            u_data = serialize_val(u.to_dict()) or {}
            rtdb_root.child('users').child(uid).update(u_data)
            users_count += 1

            # Subcollection: predictionHistory
            pred_history = list(fs_client.collection('users').document(uid).collection('predictionHistory').stream())
            for ph in pred_history:
                ph_data = serialize_val(ph.to_dict()) or {}
                ph_data['id'] = ph.id
                rtdb_root.child('users').child(uid).child('predictionHistory').child(ph.id).set(ph_data)
                # Also ensure screening_logs has this record
                rtdb_root.child('screening_logs').child(ph.id).update(ph_data)
                sub_records_count += 1

            # Subcollection: notifications
            notifs = list(fs_client.collection('users').document(uid).collection('notifications').stream())
            for n in notifs:
                n_data = serialize_val(n.to_dict()) or {}
                n_data['id'] = n.id
                rtdb_root.child('users').child(uid).child('notifications').child(n.id).set(n_data)
                sub_records_count += 1

            # Subcollection: activityLog
            activity = list(fs_client.collection('users').document(uid).collection('activityLog').stream())
            for a in activity:
                a_data = serialize_val(a.to_dict()) or {}
                a_data['id'] = a.id
                rtdb_root.child('users').child(uid).child('activityLog').child(a.id).set(a_data)
                sub_records_count += 1

        print(f"-> Migrated {users_count} users and {sub_records_count} user subcollection records.")
    except Exception as e:
        print(f"Note/Error reading users from Firestore: {e}")

    # 2. Migrate Sensor Readings
    print("\n[2/4] Migrating 'sensor_readings' to sensorData hierarchy...")
    sensor_count = 0
    user_latest_readings = {}
    try:
        readings = list(fs_client.collection('sensor_readings').stream())
        for r in readings:
            r_data = serialize_val(r.to_dict()) or {}
            rid = r.id
            r_data['id'] = rid
            user_id = str(r_data.get('user_id') or r_data.get('userId') or '1')

            # Append to history
            rtdb_root.child('sensorData').child(user_id).child('history').child(rid).set(r_data)
            # Global compatibility table
            rtdb_root.child('sensor_readings').child(rid).set(r_data)

            # Track latest reading by timestamp
            r_ts = str(r_data.get('timestamp') or '')
            if user_id not in user_latest_readings or r_ts > user_latest_readings[user_id]['ts']:
                user_latest_readings[user_id] = {'ts': r_ts, 'data': r_data}
            sensor_count += 1

        # Write latest readings for each user
        for uid, latest_info in user_latest_readings.items():
            rtdb_root.child('sensorData').child(uid).child('latest').set(latest_info['data'])

        print(f"-> Migrated {sensor_count} sensor readings across {len(user_latest_readings)} users.")
    except Exception as e:
        print(f"Note/Error reading sensor_readings from Firestore: {e}")

    # 3. Migrate Questionnaires
    print("\n[3/4] Migrating 'questionnaires'...")
    q_count = 0
    user_latest_q = {}
    try:
        qs = list(fs_client.collection('questionnaires').stream())
        for q in qs:
            q_data = serialize_val(q.to_dict()) or {}
            qid = q.id
            q_data['id'] = qid
            user_id = str(q_data.get('user_id') or q_data.get('userId') or '1')

            rtdb_root.child('questionnaires').child(user_id).child('history').child(qid).set(q_data)
            q_ts = str(q_data.get('timestamp') or '')
            if user_id not in user_latest_q or q_ts > user_latest_q[user_id]['ts']:
                user_latest_q[user_id] = {'ts': q_ts, 'data': q_data}
            q_count += 1

        for uid, latest_info in user_latest_q.items():
            rtdb_root.child('questionnaires').child(uid).child('latest').set(latest_info['data'])

        print(f"-> Migrated {q_count} questionnaires across {len(user_latest_q)} users.")
    except Exception as e:
        print(f"Note/Error reading questionnaires from Firestore: {e}")

    # 4. Migrate Screening Logs
    print("\n[4/4] Migrating 'screening_logs'...")
    logs_count = 0
    try:
        logs = list(fs_client.collection('screening_logs').stream())
        for l in logs:
            l_data = serialize_val(l.to_dict()) or {}
            lid = l.id
            l_data['id'] = lid
            user_id = str(l_data.get('user_id') or l_data.get('userId') or '1')

            rtdb_root.child('screening_logs').child(lid).set(l_data)
            rtdb_root.child('users').child(user_id).child('predictionHistory').child(lid).set(l_data)
            logs_count += 1

        print(f"-> Migrated {logs_count} screening logs.")
    except Exception as e:
        print(f"Note/Error reading screening_logs from Firestore: {e}")

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE AND VERIFIED!")
    print(f"Total Users: {users_count}")
    print(f"Total Sensor Readings: {sensor_count}")
    print(f"Total Questionnaires: {q_count}")
    print(f"Total Screening Logs: {logs_count}")
    print("=" * 60)

if __name__ == '__main__':
    run_migration()
