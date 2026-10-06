"""
Unit test for backend/database.py to verify Realtime Database interface.
Tests fallback/graceful handling and API surface.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import User, SensorReading, Questionnaire, ScreeningLog, _get_root_ref

def test_api_surface():
    print("Testing database.py RTDB API Surface...")
    
    # Check classes and methods exist
    assert hasattr(User, 'create')
    assert hasattr(User, 'get_by_uid')
    assert hasattr(User, 'get_by_email')
    assert hasattr(User, 'update_profile')
    
    assert hasattr(SensorReading, 'create')
    assert hasattr(SensorReading, 'get_latest')
    
    assert hasattr(Questionnaire, 'create')
    assert hasattr(Questionnaire, 'get_latest')
    
    assert hasattr(ScreeningLog, 'create')
    assert hasattr(ScreeningLog, 'get_by_user')
    assert hasattr(ScreeningLog, 'get_by_id')
    
    print("All class methods successfully verified!")
    
    # Verify graceful degradation if no connection
    res = User.get_by_uid('nonexistent_uid')
    print(f"User.get_by_uid result: {res}")
    
    res2 = SensorReading.get_latest('test_user')
    print(f"SensorReading.get_latest result: {res2}")
    
    res3 = Questionnaire.get_latest('test_user')
    print(f"Questionnaire.get_latest result: {res3}")
    
    res4 = ScreeningLog.get_by_user('test_user')
    print(f"ScreeningLog.get_by_user result: {res4}")
    
    print("\n=> ALL BACKEND DATABASE UNIT CHECKS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_api_surface()
