import requests
import json

def test():
    url = "http://127.0.0.1:5001/api/predict"
    payload = {
        'user_id': 'ug8hTZNbZtXiznuoCD8g5B8Dvt23',  # The test user UID we created earlier
        'age': 70.0,
        'bmi': 30.9,
        'smoking_history': 1.0,
        'alcohol_consumption': 1.0,
        'diabetes': 1.0,
        'family_history': 1.0,
        'weight_loss': 1.0,
        'abdominal_pain': 1.0,
        'appetite_changes': 1.0,
        'jaundice': 1.0,
        'mq135_ppm': 35.0,
        'mq3_ppm': 12.0,
        'mq7_ppm': 5.0,
        'saliva_ph': 7.0,
        'saliva_ec': 2.8
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"Hitting Local API /api/predict: {url}...")
    try:
        response = requests.post(url, json=payload, headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Response JSON:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error response: {response.text}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test()
