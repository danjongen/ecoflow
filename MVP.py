#!/usr/bin/env python3
"""
BSB UFO PDU Monitor - EcoFlow Smart Home Panel Dashboard
Corrected API field mappings for Delta Pro Ultra and Smart Home Panel 2
"""

import streamlit as st
import requests
import json
import time
import hmac
import hashlib
import random
import string
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import threading
from collections import deque

# Page config
st.set_page_config(
    page_title="BSB UFO PDU Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Condensed CSS
st.markdown("""
<style>
    .stApp { background-color: #111; color: #eee; }
    .main > div { padding: 0 !important; max-width: 100% !important; }
    .block-container { padding: 8px !important; max-width: 100% !important; }
    
    /* Typography */
    h1 { font-size: 20px !important; margin: 0 0 8px 0 !important; }
    h2 { font-size: 16px !important; margin: 0 0 4px 0 !important; }
    h3 { font-size: 14px !important; margin: 0 !important; }
    p, div { font-size: 12px !important; line-height: 1.2; }
    
    /* Compact cards */
    .metric-card {
        background: #1e2329;
        padding: 8px;
        border-radius: 4px;
        height: 65px;
    }
    .metric-value { font-size: 28px; font-weight: bold; line-height: 1; }
    .metric-label { font-size: 11px; color: #888; }
    
    /* Circuit cards */
    .circuit-card {
        background: #1e2329;
        padding: 6px;
        border-radius: 3px;
        border-left: 3px solid;
        margin-bottom: 4px;
        height: 52px;
    }
    
    /* Battery cards */
    .battery-card {
        background: #1e2329;
        padding: 8px;
        border-radius: 4px;
        margin-bottom: 6px;
    }
    
    .soc-bar {
        height: 6px;
        background: #0d0f14;
        border-radius: 3px;
        overflow: hidden;
        margin-top: 4px;
    }
    
    /* Event log */
    .event-log {
        background: #0d0f14;
        padding: 6px;
        border-radius: 3px;
        height: 120px;
        overflow-y: auto;
        font-family: monospace;
        font-size: 10px;
        line-height: 1.4;
    }
    
    /* Hide Streamlit elements */
    #MainMenu, footer, header { visibility: hidden; }
    .css-1y4p8pa { padding: 0 !important; }
    
    /* Remove spacing */
    .element-container { margin: 0 !important; padding: 0 !important; }
    div[data-testid="stVerticalBlock"] > div { padding: 0 !important; }
    hr { margin: 4px 0 !important; }
    
    /* Status colors */
    .status-ok { color: #4CAF50; }
    .status-warn { color: #FFC107; }
    .status-crit { color: #F44336; }
</style>
""", unsafe_allow_html=True)

# Credentials - Use Streamlit secrets in production
try:
    ACCESS_KEY = st.secrets["ACCESS_KEY"]
    SECRET_KEY = st.secrets["SECRET_KEY"]
except:
    # Fallback for local development
    ACCESS_KEY = "ED0inAmV1FyfekoXwa1yEvORjd2RO82D"
    SECRET_KEY = "mMHl09KIP1hNEeMLrPDPEBjbA9T9ElO7"

# Device mappings
DEVICES = {
    "BSB Pack #1": "Y711ZABA9H250592",
    "BSB Pack #2": "Y711ZABA9H250595", 
    "BSB Pack #3": "Y711ZAB59GA70085",
    "Smart Panel": "HD31ZAS4HGC70401"
}

# All 12 circuits - Smart Home Panel uses 0-indexed arrays
CIRCUITS = {
    0: {"name": "Kitchen", "leg": 1, "breaker": 20, "display": "L11"},
    1: {"name": "Living Room", "leg": 1, "breaker": 20, "display": "L12"},
    2: {"name": "Circuit L13", "leg": 1, "breaker": 15, "display": "L13"},
    3: {"name": "Master Bedroom", "leg": 1, "breaker": 15, "display": "L14"},
    4: {"name": "Circuit L15", "leg": 1, "breaker": 15, "display": "L15"},
    5: {"name": "Circuit L16", "leg": 1, "breaker": 20, "display": "L16"},
    6: {"name": "Garage", "leg": 2, "breaker": 20, "display": "L21"},
    7: {"name": "Office", "leg": 2, "breaker": 15, "display": "L22"},
    8: {"name": "Circuit L23", "leg": 2, "breaker": 15, "display": "L23"},
    9: {"name": "Circuit L24", "leg": 2, "breaker": 15, "display": "L24"},
    10: {"name": "Circuit L25", "leg": 2, "breaker": 20, "display": "L25"},
    11: {"name": "Circuit L26", "leg": 2, "breaker": 20, "display": "L26"},
}

# Operating specs with temperature thresholds
OPERATING_SPECS = {
    "battery": {
        "capacity_per_battery": 6144,
        "temp_optimal": 40,      # Green <= 40°C
        "temp_warning": 45,      # Orange 40-45°C
        "temp_critical": 59,     # Red 45-59°C
        "temp_shutdown": 60      # Shutdown >= 60°C
    },
    "inverter": {
        "output_continuous": 7200,
        "temp_optimal": 40,      # Green <= 40°C
        "temp_warning": 54,      # Orange 40-54°C
        "temp_critical": 64,     # Red 54-64°C
        "temp_shutdown": 65      # Shutdown >= 65°C
    }
}

# Initialize session state
if 'event_log' not in st.session_state:
    st.session_state.event_log = deque(maxlen=50)
    
if 'last_data' not in st.session_state:
    st.session_state.last_data = {}

if 'api_success_count' not in st.session_state:
    st.session_state.api_success_count = 0
    
if 'api_fail_count' not in st.session_state:
    st.session_state.api_fail_count = 0

if 'historical_data' not in st.session_state:
    st.session_state.historical_data = deque(maxlen=300)  # 5 minutes of data

def generate_nonce(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_signature(params, secret_key):
    sorted_params = sorted(params.items())
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

def get_device_data(device_sn):
    nonce = generate_nonce()
    timestamp = str(int(time.time() * 1000))
    
    params = {
        'accessKey': ACCESS_KEY,
        'nonce': nonce,
        'timestamp': timestamp
    }
    
    sign = generate_signature(params, SECRET_KEY)
    
    headers = {
        'accessKey': ACCESS_KEY,
        'nonce': nonce,
        'timestamp': timestamp,
        'sign': sign,
        'Content-Type': 'application/json'
    }
    
    url = f"https://api.ecoflow.com/iot-open/sign/device/quota/all?sn={device_sn}"
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '0':
                st.session_state.api_success_count += 1
                return data.get('data', {})
            else:
                st.session_state.api_fail_count += 1
                log_event("ERROR", f"API: {data.get('message', 'Unknown')}")
        else:
            st.session_state.api_fail_count += 1
            log_event("ERROR", f"HTTP {response.status_code}")
    except Exception as e:
        st.session_state.api_fail_count += 1
        log_event("ERROR", f"Failed: {str(e)[:30]}")
    
    return None

def get_device_list():
    nonce = generate_nonce()
    timestamp = str(int(time.time() * 1000))
    
    params = {
        'accessKey': ACCESS_KEY,
        'nonce': nonce,
        'timestamp': timestamp
    }
    
    sign = generate_signature(params, SECRET_KEY)
    
    headers = {
        'accessKey': ACCESS_KEY,
        'nonce': nonce,
        'timestamp': timestamp,
        'sign': sign,
        'Content-Type': 'application/json'
    }
    
    url = "https://api.ecoflow.com/iot-open/sign/device/list"
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '0':
                return data.get('data', [])
    except:
        pass
    
    return []

def log_event(event_type, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    color = {"INFO": "#4CAF50", "WARNING": "#FFC107", "ERROR": "#F44336"}.get(event_type, "#eee")
    event = f'[{timestamp}] <span style="color: {color}">{event_type}: {message}</span>'
    st.session_state.event_log.append(event)

def get_circuit_color(amps, breaker_size):
    load_percent = (amps / breaker_size) * 100 if breaker_size > 0 else 0
    if load_percent < 50:
        return "#4CAF50"
    elif load_percent < 85:
        return "#FFC107"
    else:
        return "#F44336"

def get_temp_color(temp, device_type="battery"):
    """Get color based on temperature thresholds with traffic light system"""
    specs = OPERATING_SPECS[device_type]
    
    if temp <= specs["temp_optimal"]:
        return "#4CAF50"  # Green - Optimal
    elif temp <= specs["temp_warning"]:
        return "#FFC107"  # Orange - Warning
    elif temp <= specs["temp_critical"]:
        return "#F44336"  # Red - Critical
    else:
        return "#8B0000"  # Dark Red - Shutdown imminent

def check_temperature_alerts(device_name, temp, device_type="battery"):
    """Check and log temperature alerts"""
    specs = OPERATING_SPECS[device_type]
    
    last_temp = st.session_state.last_data.get(device_name, {}).get('temp', 0)
    
    # Check for threshold crossings
    if temp > specs["temp_critical"] and last_temp <= specs["temp_critical"]:
        log_event("ERROR", f"{device_name} CRITICAL TEMP: {temp:.1f}°C (shutdown at {specs['temp_shutdown']}°C)")
    elif temp > specs["temp_warning"] and last_temp <= specs["temp_warning"]:
        log_event("WARNING", f"{device_name} HIGH TEMP: {temp:.1f}°C")
    elif temp <= specs["temp_optimal"] and last_temp > specs["temp_optimal"]:
        log_event("INFO", f"{device_name} temp normal: {temp:.1f}°C")

def calculate_time_to_empty(total_output, available_kwh):
    """Calculate estimated time to empty based on average load"""
    if total_output <= 0 or available_kwh <= 0:
        return None
    
    # Use historical data for average if available
    if len(st.session_state.historical_data) > 10:
        avg_output = sum(d['output'] for d in st.session_state.historical_data) / len(st.session_state.historical_data)
    else:
        avg_output = total_output
    
    hours = (available_kwh * 1000) / avg_output if avg_output > 0 else 0
    return hours

def parse_battery_data(device_data, device_name):
    """Extract battery data from various possible field locations"""
    soc = 0
    watts_in = 0
    watts_out = 0
    temp = 0
    
    # Check for hs_yj751_ prefixed fields (primary source)
    appshow = device_data.get('hs_yj751_pd_appshow_addr', {})
    if appshow:
        soc = appshow.get('soc', 0)
        watts_out = appshow.get('wattsOutSum', 0)
        watts_in = appshow.get('wattsInSum', 0)
    
    backend = device_data.get('hs_yj751_pd_backend_addr', {})
    if backend:
        if watts_in == 0:
            watts_in = backend.get('bmsInputWatts', 0)
        if watts_out == 0:
            watts_out = backend.get('bmsOutputWatts', 0)
    
    # Direct field access for the specific structure
    soc = device_data.get('hs_yj751_bms_slave_addr.1.soc', soc)
    temp = device_data.get('hs_yj751_bms_slave_addr.1.temp', 
           device_data.get('hs_yj751_bms_slave_addr.1.cellTemp',
           device_data.get('hs_yj751_bms_slave_addr.1.maxCellTemp', temp)))
    
    if watts_in == 0:
        watts_in = device_data.get('hs_yj751_bms_slave_addr.1.inputWatts', 0)
    if watts_out == 0:
        watts_out = device_data.get('hs_yj751_bms_slave_addr.1.outputWatts', 0)
    
    return soc, watts_in, watts_out, temp

def parse_circuit_data(panel_data):
    """Extract circuit data from Smart Home Panel"""
    circuit_data = {}
    
    # Get data from appshow and backend addresses
    appshow = panel_data.get('hs_yj751_pd_appshow_addr', {})
    backend = panel_data.get('hs_yj751_pd_backend_addr', {})
    
    # Circuit mappings for the specific field names
    circuit_fields = [
        {'power': 'outAcL11Pwr', 'amp': 'outAcL11Amp', 'vol': 'outAcL11Vol'},
        {'power': 'outAcL12Pwr', 'amp': 'outAcL12Amp', 'vol': 'outAcL12Vol'},
        {'power': 'outAcL13Pwr', 'amp': 'outAcL13Amp', 'vol': 'outAcL13Vol'},
        {'power': 'outAcL14Pwr', 'amp': 'outAcL14Amp', 'vol': 'outAcL14Vol'},
        {'power': 'outAcL15Pwr', 'amp': 'outAcL15Amp', 'vol': 'outAcL15Vol'},
        {'power': 'outAcL16Pwr', 'amp': 'outAcL16Amp', 'vol': 'outAcL16Vol'},
        {'power': 'outAcL21Pwr', 'amp': 'outAcL21Amp', 'vol': 'outAcL21Vol'},
        {'power': 'outAcL22Pwr', 'amp': 'outAcL22Amp', 'vol': 'outAcL22Vol'},
        {'power': 'outAcL23Pwr', 'amp': 'outAcL23Amp', 'vol': 'outAcL23Vol'},
        {'power': 'outAcL24Pwr', 'amp': 'outAcL24Amp', 'vol': 'outAcL24Vol'},
        {'power': 'outAcL25Pwr', 'amp': 'outAcL25Amp', 'vol': 'outAcL25Vol'},
        {'power': 'outAcL26Pwr', 'amp': 'outAcL26Amp', 'vol': 'outAcL26Vol'}
    ]
    
    for i, fields in enumerate(circuit_fields):
        # Get power from appshow
        watts = appshow.get(fields['power'], 0)
        # Get amps and voltage from backend
        amps = backend.get(fields['amp'], 0)
        voltage = backend.get(fields['vol'], 0)
        
        circuit_data[i] = {
            'watts': watts,
            'amps': amps,
            'voltage': voltage,
            'is_on': watts > 10,
            'name': CIRCUITS[i]['name']
        }
    
    return circuit_data

def main():
    # Header
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown("# ⚡ BSB UFO PDU MONITOR")
    with col2:
        if st.button("🔄 Refresh", key="refresh", type="primary"):
            st.rerun()
    with col3:
        panel_status = st.empty()
    
    # Create placeholders
    metrics_placeholder = st.empty()
    main_content_placeholder = st.empty()
    event_log_placeholder = st.empty()
    footer_placeholder = st.empty()
    
    # Update loop
    while True:
        # Get fresh device list
        devices = get_device_list()
        all_data = {}
        
        for device_name, device_sn in DEVICES.items():
            data = get_device_data(device_sn)
            if data:
                all_data[device_name] = data
        
        # Update panel status
        panel_online = any(d['sn'] == DEVICES['Smart Panel'] and d['online'] == 1 for d in devices)
        with panel_status:
            if panel_online:
                st.markdown('<span class="status-ok">● PANEL ONLINE</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-crit">● PANEL OFFLINE</span>', unsafe_allow_html=True)
        
        # Track online/offline changes
        for device_name in DEVICES:
            device_online = any(d['sn'] == DEVICES.get(device_name, "") and d['online'] == 1 for d in devices)
            if device_name not in st.session_state.last_data:
                st.session_state.last_data[device_name] = {'was_online': False}
            
            if device_online != st.session_state.last_data[device_name].get('was_online', False):
                if device_online:
                    log_event("INFO", f"{device_name} online")
                else:
                    log_event("WARNING", f"{device_name} offline")
                st.session_state.last_data[device_name]['was_online'] = device_online
        
        # Parse circuit data from Smart Panel
        circuit_data = {}
        smart_panel_data = all_data.get("Smart Panel", {})
        if smart_panel_data:
            circuit_data = parse_circuit_data(smart_panel_data)
            
            # Check for circuit alerts
            for circuit_idx, data in circuit_data.items():
                circuit_info = CIRCUITS[circuit_idx]
                last_circuit = st.session_state.last_data.get('circuits', {}).get(circuit_idx, {})
                
                # Circuit on/off detection
                if data['watts'] > 10 and last_circuit.get('watts', 0) <= 10:
                    log_event("INFO", f"{circuit_info['name']} ON ({data['amps']:.1f}A)")
                elif data['watts'] <= 10 and last_circuit.get('watts', 0) > 10:
                    log_event("INFO", f"{circuit_info['name']} OFF")
                
                # Load warnings
                load_percent = (data['amps'] / circuit_info['breaker']) * 100
                last_load_percent = (last_circuit.get('amps', 0) / circuit_info['breaker']) * 100
                
                if load_percent >= 80 and last_load_percent < 80:
                    log_event("WARNING", f"{circuit_info['name']} at {load_percent:.0f}% limit!")
                elif load_percent >= 90 and last_load_percent < 90:
                    log_event("ERROR", f"{circuit_info['name']} CRITICAL {load_percent:.0f}% limit!")
        
        # Calculate totals and battery data
        total_input = 0
        total_output = 0
        online_batteries = []
        battery_details = {}
        
        # Get inverter data if available
        inverter_temp = 0
        for device_name, data in all_data.items():
            if device_name == "Smart Panel" and data:
                inv = data.get('inv', {})
                if inv:
                    inverter_temp = max(inv.get('dcInTemp', 0), inv.get('outTemp', 0))
                    if inverter_temp > 0:
                        check_temperature_alerts("Inverter", inverter_temp, "inverter")
        
        # Process battery data
        for device_name, data in all_data.items():
            if device_name != "Smart Panel" and data:
                soc, watts_in, watts_out, temp = parse_battery_data(data, device_name)
                
                total_input += watts_in
                total_output += watts_out
                
                if soc > 0:
                    online_batteries.append(soc)
                    battery_details[device_name] = {
                        'soc': soc,
                        'watts_in': watts_in,
                        'watts_out': watts_out,
                        'temp': temp
                    }
                    
                    # Check temperature alerts
                    if temp > 0:
                        check_temperature_alerts(device_name, temp, "battery")
                    
                    # Store last data
                    if device_name not in st.session_state.last_data:
                        st.session_state.last_data[device_name] = {}
                    st.session_state.last_data[device_name]['temp'] = temp
        
        # Store historical data
        st.session_state.historical_data.append({
            'time': datetime.now(),
            'output': total_output,
            'input': total_input
        })
        
        # Calculate averages
        avg_soc = sum(online_batteries) / len(online_batteries) if online_batteries else 0
        total_capacity = len(online_batteries) * OPERATING_SPECS["battery"]["capacity_per_battery"]
        kwh_available = (avg_soc / 100 * total_capacity / 1000) if total_capacity > 0 else 0
        
        # Calculate time to empty
        time_to_empty = calculate_time_to_empty(total_output, kwh_available)
        
        # Update metrics
        with metrics_placeholder.container():
            st.markdown("### System Overview")
            metric_cols = st.columns(5)
            
            with metric_cols[0]:
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-label">Total Input</div>
                    <div class="metric-value">{total_input:.0f}W</div>
                    <div class="metric-label">Net: {total_input - total_output:+.0f}W</div>
                </div>
                ''', unsafe_allow_html=True)
            
            with metric_cols[1]:
                max_output = OPERATING_SPECS["inverter"]["output_continuous"]
                output_percent = (total_output/max_output)*100
                output_color = "#4CAF50" if output_percent < 80 else "#FFC107" if output_percent < 90 else "#F44336"
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-label">Total Output</div>
                    <div class="metric-value" style="color: {output_color};">{total_output:.0f}W</div>
                    <div class="metric-label">{output_percent:.1f}% of {max_output/1000:.1f}kW</div>
                </div>
                ''', unsafe_allow_html=True)
            
            with metric_cols[2]:
                soc_color = "#4CAF50" if avg_soc > 30 else "#FFC107" if avg_soc > 15 else "#F44336"
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-label">Average SoC</div>
                    <div class="metric-value" style="color: {soc_color};">{avg_soc:.0f}%</div>
                    <div class="metric-label">{kwh_available:.1f} kWh available</div>
                </div>
                ''', unsafe_allow_html=True)
            
            with metric_cols[3]:
                if time_to_empty:
                    hours = int(time_to_empty)
                    minutes = int((time_to_empty - hours) * 60)
                    time_color = "#4CAF50" if time_to_empty > 4 else "#FFC107" if time_to_empty > 1 else "#F44336"
                    st.markdown(f'''
                    <div class="metric-card">
                        <div class="metric-label">Time to Empty</div>
                        <div class="metric-value" style="color: {time_color};">{hours}:{minutes:02d}</div>
                        <div class="metric-label">at avg load</div>
                    </div>
                    ''', unsafe_allow_html=True)
                else:
                    st.markdown(f'''
                    <div class="metric-card">
                        <div class="metric-label">Time to Empty</div>
                        <div class="metric-value">--:--</div>
                        <div class="metric-label">charging</div>
                    </div>
                    ''', unsafe_allow_html=True)
            
            with metric_cols[4]:
                active_circuits = sum(1 for d in circuit_data.values() if d['watts'] > 10)
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-label">Active Circuits</div>
                    <div class="metric-value">{active_circuits}</div>
                    <div class="metric-label">of 12 total</div>
                </div>
                ''', unsafe_allow_html=True)
        
        # Update main content
        with main_content_placeholder.container():
            col_left, col_right = st.columns([2, 1])
            
            # Left: Circuit Monitoring
            with col_left:
                st.markdown("### ⚡ Circuit Monitoring")
                
                # LEG 1
                st.markdown("**LEG 1**")
                leg1_cols = st.columns(6)
                leg1_circuits = {idx: data for idx, data in enumerate(circuit_data.values()) if CIRCUITS[idx]['leg'] == 1}
                
                for idx, (circuit_idx, data) in enumerate(leg1_circuits.items()):
                    info = CIRCUITS[circuit_idx]
                    color = get_circuit_color(data['amps'], info['breaker'])
                    
                    with leg1_cols[idx % 6]:
                        st.markdown(f'''
                        <div class="circuit-card" style="border-left-color: {color};">
                            <div style="font-size: 11px; font-weight: bold;">{info["name"]}</div>
                            <div style="font-size: 16px; color: {color}; font-weight: bold;">{data['amps']:.1f}A</div>
                            <div style="font-size: 10px; color: #888;">{data['watts']/1000:.2f}kW • {info["breaker"]}A</div>
                        </div>
                        ''', unsafe_allow_html=True)
                
                # LEG 2
                st.markdown("**LEG 2**")
                leg2_cols = st.columns(6)
                leg2_circuits = {idx: data for idx, data in enumerate(circuit_data.values()) if CIRCUITS[idx]['leg'] == 2}
                
                for idx, (circuit_idx, data) in enumerate(leg2_circuits.items()):
                    info = CIRCUITS[circuit_idx]
                    color = get_circuit_color(data['amps'], info['breaker'])
                    
                    with leg2_cols[idx % 6]:
                        st.markdown(f'''
                        <div class="circuit-card" style="border-left-color: {color};">
                            <div style="font-size: 11px; font-weight: bold;">{info["name"]}</div>
                            <div style="font-size: 16px; color: {color}; font-weight: bold;">{data['amps']:.1f}A</div>
                            <div style="font-size: 10px; color: #888;">{data['watts']/1000:.2f}kW • {info["breaker"]}A</div>
                        </div>
                        ''', unsafe_allow_html=True)
            
            # Right: Battery Status + Leg Balance
            with col_right:
                st.markdown("### 🔋 Battery Status")
                
                # Battery packs
                for device_name in ["BSB Pack #1", "BSB Pack #2", "BSB Pack #3"]:
                    device_online = any(d['sn'] == DEVICES.get(device_name, "") and d['online'] == 1 for d in devices)
                    
                    if device_online and device_name in battery_details:
                        details = battery_details[device_name]
                        capacity = OPERATING_SPECS["battery"]["capacity_per_battery"]
                        remaining_kwh = (details['soc'] / 100) * (capacity / 1000)
                        
                        soc_color = "#4CAF50" if details['soc'] > 30 else "#FFC107" if details['soc'] > 15 else "#F44336"
                        temp_color = get_temp_color(details['temp'], "battery")
                        
                        # Show temperature warnings
                        temp_warning = ""
                        if details['temp'] > OPERATING_SPECS["battery"]["temp_critical"]:
                            temp_warning = " ⚠️ CRITICAL"
                        elif details['temp'] > OPERATING_SPECS["battery"]["temp_warning"]:
                            temp_warning = " ⚠️"
                        
                        st.markdown(f'''
                        <div class="battery-card">
                            <div style="display: flex; justify-content: space-between;">
                                <h3>{device_name}</h3>
                                <span style="font-size: 10px; color: #888;">{remaining_kwh:.1f}/{capacity/1000:.1f}kWh</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div style="font-size: 24px; font-weight: bold; color: {soc_color};">{int(details['soc'])}%</div>
                                <div style="text-align: right;">
                                    <div style="font-size: 14px;">{int(details['watts_out'])}W out</div>
                                    <div style="font-size: 12px; color: {temp_color};">{details['temp']:.1f}°C{temp_warning}</div>
                                </div>
                            </div>
                            <div class="soc-bar">
                                <div style="width: {details['soc']}%; height: 100%; background: {soc_color};"></div>
                            </div>
                        </div>
                        ''', unsafe_allow_html=True)
                    else:
                        st.markdown(f'''
                        <div class="battery-card" style="text-align: center; padding: 12px;">
                            <h3>{device_name}</h3>
                            <div style="font-size: 24px; color: #666;">⚫</div>
                            <div style="font-size: 11px; color: #888;">OFFLINE</div>
                        </div>
                        ''', unsafe_allow_html=True)
                
                # Leg Balance
                st.markdown("### ⚖️ Leg Balance")
                
                leg1_power = sum(circuit_data[i]['watts'] for i in range(6))
                leg2_power = sum(circuit_data[i]['watts'] for i in range(6, 12))
                total_power = leg1_power + leg2_power
                
                if total_power > 0:
                    balance = abs(leg1_power - leg2_power) / total_power * 100
                    balance_color = "#4CAF50" if balance < 20 else "#FFC107" if balance < 40 else "#F44336"
                else:
                    balance = 0
                    balance_color = "#4CAF50"
                
                # Check for leg imbalance alerts
                if 'leg_balance' not in st.session_state.last_data:
                    st.session_state.last_data['leg_balance'] = 0
                
                last_balance = st.session_state.last_data['leg_balance']
                if balance > 40 and last_balance <= 40:
                    log_event("ERROR", f"LEG IMBALANCE: {balance:.0f}% (L1: {leg1_power/1000:.1f}kW, L2: {leg2_power/1000:.1f}kW)")
                elif balance > 20 and last_balance <= 20:
                    log_event("WARNING", f"Leg imbalance: {balance:.0f}%")
                
                st.session_state.last_data['leg_balance'] = balance
                
                fig_balance = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=balance,
                    gauge={
                        'axis': {'range': [0, 100], 'tickcolor': '#eee'},
                        'bar': {'color': balance_color},
                        'bgcolor': '#0d0f14',
                        'borderwidth': 1,
                        'bordercolor': '#333',
                    },
                    number={'suffix': "%", 'font': {'color': '#eee', 'size': 20}}
                ))
                
                fig_balance.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    height=120,
                    margin=dict(l=0, r=0, t=0, b=0)
                )
                
                st.plotly_chart(fig_balance, use_container_width=True, key=f"balance_{time.time()}")
                
                st.markdown(f'''
                <div style="text-align: center; font-size: 11px;">
                    L1: {leg1_power/1000:.1f}kW • L2: {leg2_power/1000:.1f}kW
                </div>
                ''', unsafe_allow_html=True)
        
        # Update event log
        with event_log_placeholder.container():
            st.markdown("### 📜 Event Log")
            events_html = "<br>".join(list(st.session_state.event_log))
            st.markdown(f'<div class="event-log">{events_html if events_html else "No events"}</div>', unsafe_allow_html=True)
        
        # Update footer
        with footer_placeholder:
            api_rate = st.session_state.api_success_count / (st.session_state.api_success_count + st.session_state.api_fail_count) * 100 if (st.session_state.api_success_count + st.session_state.api_fail_count) > 0 else 100
            st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} • API Success: {api_rate:.0f}% • Auto-refresh 1s")
        
        # Store circuit data for next iteration
        if 'circuits' not in st.session_state.last_data:
            st.session_state.last_data['circuits'] = {}
        for idx, data in circuit_data.items():
            st.session_state.last_data['circuits'][idx] = data
        
        # Wait before next update
        time.sleep(1)

if __name__ == "__main__":
    main()