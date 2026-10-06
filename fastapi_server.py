from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
import time

app = FastAPI(
    title="PancreaSense Real-Time Multi-Sensor Backend",
    description="FastAPI Server listening on 0.0.0.0:8000 for ESP32 HTTP POST and serving Flutter & Web Dashboards",
    version="2.0.0"
)

# Enable CORS for Flutter mobile/web apps and browser dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global memory state for latest ESP32 telemetry
latest_sensor_data = {
    "tds_raw": None,
    "tds_voltage": None,
    "mq_raw": None,
    "mq_voltage": None,
    "ph_raw": None,
    "ph_voltage": None,
    "timestamp": None,
    "received_unix": 0.0
}

# Pydantic validation schema for incoming ESP32 HTTP POST payload
class ESP32SensorPayload(BaseModel):
    tds_raw: int
    tds_voltage: float
    mq_raw: int
    mq_voltage: float
    ph_raw: int
    ph_voltage: float

# Helper to determine ESP32 live connection status (within 5 seconds)
def get_esp32_connection_status():
    if latest_sensor_data["received_unix"] == 0.0:
        return "NO ESP32 DATA RECEIVED YET", "DISCONNECTED"
    elapsed = time.time() - latest_sensor_data["received_unix"]
    if elapsed <= 5.0:
        return "ACTIVE", "CONNECTED"
    else:
        return f"INACTIVE ({int(elapsed)}s ago)", "DISCONNECTED"


# =====================================================
# 1. ESP32 ENDPOINT: POST /sensor-data
# =====================================================
@app.post("/sensor-data")
async def receive_sensor_data(payload: ESP32SensorPayload):
    global latest_sensor_data
    
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_unix = time.time()
    
    # Store validated payload in memory with timestamp
    latest_sensor_data = {
        "tds_raw": payload.tds_raw,
        "tds_voltage": payload.tds_voltage,
        "mq_raw": payload.mq_raw,
        "mq_voltage": payload.mq_voltage,
        "ph_raw": payload.ph_raw,
        "ph_voltage": payload.ph_voltage,
        "timestamp": timestamp_str,
        "received_unix": current_unix
    }
    
    print(f"[{timestamp_str}] [ESP32 POST] TDS: {payload.tds_raw} ({payload.tds_voltage:.3f}V) | MQ: {payload.mq_raw} ({payload.mq_voltage:.3f}V) | pH: {payload.ph_raw} ({payload.ph_voltage:.3f}V)")
    
    return {
        "status": "success",
        "message": "Telemetry received successfully",
        "timestamp": timestamp_str
    }


# =====================================================
# 2. FLUTTER & WEB ENDPOINT: GET /api/latest-sensor
# =====================================================
@app.get("/api/latest-sensor")
async def get_latest_sensor():
    status_detail, esp32_state = get_esp32_connection_status()
    
    if latest_sensor_data["timestamp"] is None:
        return {
            "status": "online",
            "esp32_status": esp32_state,
            "status_detail": status_detail,
            "message": "Waiting for initial ESP32 telemetry stream...",
            "sensor": None
        }
        
    return {
        "status": "online",
        "esp32_status": esp32_state,
        "status_detail": status_detail,
        "sensor": {
            "tds_raw": latest_sensor_data["tds_raw"],
            "tds_voltage": latest_sensor_data["tds_voltage"],
            "mq_raw": latest_sensor_data["mq_raw"],
            "mq_voltage": latest_sensor_data["mq_voltage"],
            "ph_raw": latest_sensor_data["ph_raw"],
            "ph_voltage": latest_sensor_data["ph_voltage"],
            "timestamp": latest_sensor_data["timestamp"]
        }
    }


# =====================================================
# 3. SYSTEM STATUS ENDPOINT: GET /api/status
# =====================================================
@app.get("/api/status")
async def get_system_status():
    status_detail, esp32_state = get_esp32_connection_status()
    
    return {
        "fastapi_server_status": "ONLINE",
        "esp32_connection_status": esp32_state,
        "esp32_detail": status_detail,
        "last_received_time": latest_sensor_data["timestamp"] or "N/A (No data received)",
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# =====================================================
# 4. WEB DASHBOARD ENDPOINT: GET / & GET /dashboard
# =====================================================
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_web_dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PancreaSense Real-Time Web Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding-top: 2rem; }
        .card-custom { background: #1e293b; border: 1px solid #334155; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }
        .badge-status { font-size: 0.9rem; padding: 0.5em 1em; border-radius: 20px; }
        .metric-value { font-size: 2.2rem; font-weight: 700; color: #38bdf8; }
        .metric-sub { font-size: 1.1rem; color: #94a3b8; }
    </style>
</head>
<body>
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <div>
                <h2 class="fw-bold text-white mb-1">PancreaSense Web Dashboard</h2>
                <p class="text-secondary mb-0">Real-Time Multi-Sensor Telemetry (FastAPI & ESP32)</p>
            </div>
            <div>
                <span id="server-badge" class="badge bg-secondary badge-status me-2">FastAPI: Checking...</span>
                <span id="esp32-badge" class="badge bg-secondary badge-status">ESP32: Checking...</span>
            </div>
        </div>

        <div class="row g-4">
            <!-- TDS Sensor Card -->
            <div class="col-md-4">
                <div class="card card-custom p-4 text-center">
                    <h5 class="text-uppercase text-secondary tracking-wide mb-3">GPIO32 — TDS Sensor</h5>
                    <div id="tds-voltage" class="metric-value">-- V</div>
                    <div id="tds-raw" class="metric-sub mt-2">Raw ADC: --</div>
                </div>
            </div>

            <!-- MQ Sensor Card -->
            <div class="col-md-4">
                <div class="card card-custom p-4 text-center">
                    <h5 class="text-uppercase text-secondary tracking-wide mb-3">GPIO33 — MQ Gas Sensor</h5>
                    <div id="mq-voltage" class="metric-value text-warning">-- V</div>
                    <div id="mq-raw" class="metric-sub mt-2">Raw ADC: --</div>
                </div>
            </div>

            <!-- pH Sensor Card -->
            <div class="col-md-4">
                <div class="card card-custom p-4 text-center">
                    <h5 class="text-uppercase text-secondary tracking-wide mb-3">GPIO34 — pH Sensor</h5>
                    <div id="ph-voltage" class="metric-value text-info">-- V</div>
                    <div id="ph-raw" class="metric-sub mt-2">Raw ADC: --</div>
                </div>
            </div>
        </div>

        <div class="card card-custom p-3 mt-4 text-center text-secondary">
            <span>Last Updated Timestamp: <strong id="last-timestamp" class="text-light">N/A</strong></span>
        </div>
    </div>

    <script>
        async function updateDashboard() {
            try {
                const response = await fetch('/api/latest-sensor');
                const data = await response.json();
                
                const serverBadge = document.getElementById('server-badge');
                const esp32Badge = document.getElementById('esp32-badge');
                
                serverBadge.className = 'badge bg-success badge-status me-2';
                serverBadge.innerText = 'FastAPI: ONLINE';
                
                if (data.esp32_status === 'CONNECTED') {
                    esp32Badge.className = 'badge bg-success badge-status';
                    esp32Badge.innerText = 'ESP32: CONNECTED';
                } else {
                    esp32Badge.className = 'badge bg-danger badge-status';
                    esp32Badge.innerText = 'ESP32: DISCONNECTED';
                }

                if (data.sensor) {
                    document.getElementById('tds-voltage').innerText = data.sensor.tds_voltage.toFixed(3) + ' V';
                    document.getElementById('tds-raw').innerText = 'Raw ADC: ' + data.sensor.tds_raw;
                    
                    document.getElementById('mq-voltage').innerText = data.sensor.mq_voltage.toFixed(3) + ' V';
                    document.getElementById('mq-raw').innerText = 'Raw ADC: ' + data.sensor.mq_raw;
                    
                    document.getElementById('ph-voltage').innerText = data.sensor.ph_voltage.toFixed(3) + ' V';
                    document.getElementById('ph-raw').innerText = 'Raw ADC: ' + data.sensor.ph_raw;

                    document.getElementById('last-timestamp').innerText = data.sensor.timestamp;
                }
            } catch (err) {
                document.getElementById('server-badge').className = 'badge bg-danger badge-status me-2';
                document.getElementById('server-badge').innerText = 'FastAPI: OFFLINE';
            }
        }

        // Auto-refresh web dashboard every 1 second
        setInterval(updateDashboard, 1000);
        updateDashboard();
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    import uvicorn
    # MUST LISTEN ON 0.0.0.0 PORT 8000 FOR ESP32, FLUTTER & WEB ACCESS
    uvicorn.run(app, host="0.0.0.0", port=8000)
