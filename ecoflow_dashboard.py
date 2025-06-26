import os
import streamlit as st

# ──────────────── IMAGE LOADING ─────────────────
# Figure out where the dashboard script lives:
HERE = os.path.dirname(__file__)

# Build absolute paths to your two PNGs:
HEADER1 = os.path.join(HERE, "header.png")
HEADER2 = os.path.join(HERE, "into_the_millennium.png")

# Display them side-by-side with a little padding column in the middle:
cols = st.columns([1,2,1])
with cols[0]:
    if os.path.isfile(HEADER1):
        st.image(HEADER1, use_column_width=True)
    else:
        st.warning("⚠️ header.png not found")
with cols[2]:
    if os.path.isfile(HEADER2):
        st.image(HEADER2, use_column_width=True)
    else:
        st.warning("⚠️ into_the_millennium.png not found")

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)


import streamlit as st
import paho.mqtt.client as mqtt
import threading, time, json
from datetime import datetime

import threading
import json
import paho.mqtt.client as mqtt
from datetime import datetime

# ──────────────── MQTT HELPER ────────────────────
STATE = {"last_update": None}

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        STATE["connected"] = True
        STATE["last_update"] = datetime.now()
        client.subscribe(f"open/{ACCESS_KEY}/{DEVICE_SN}/status")
        USER_LOG.append(f"{datetime.now():%H:%M:%S} ✅ Connected to broker")
    else:
        STATE["connected"] = False
        USER_LOG.append(f"{datetime.now():%H:%M:%S} ❌ Connection failed (rc={rc})")

def on_message(client, userdata, msg):
    # Example payload parsing — adjust to your actual JSON structure:
    data = json.loads(msg.payload.decode())
    # Merge new keys into STATE:
    STATE.update(data)
    STATE["last_update"] = datetime.now()

def start_mqtt_loop(broker: str, acc: str, sec: str, sn: str):
    global ACCESS_KEY, SECRET_KEY, DEVICE_SN, USER_LOG
    ACCESS_KEY, SECRET_KEY, DEVICE_SN = acc, sec, sn
    USER_LOG = []
    client = mqtt.Client()
    client.tls_set()  # system CAs
    client.username_pw_set(ACCESS_KEY, SECRET_KEY)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(broker, 8883)
    threading.Thread(target=client.loop_forever, daemon=True).start()



# ─── PAGE SETUP ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="UFO PDU Status",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Force dark theme
st.markdown(
    """
    <style>
      html, body, [class*="css"]  { background-color: #0e1117 !important; color: #fafafa !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── STATE INITIALIZATION ──────────────────────────────────────────────────────
if "mqtt_client" not in st.session_state:
    st.session_state.mqtt_client = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "state" not in st.session_state:
    # Holds the latest values from the panel
    st.session_state.state = {
        "shore_kw": 0.0,
        "soc_pct": 0.0,
        "empty_min": 0.0,
        "leg1_kw": 0.0,
        "leg2_kw": 0.0,
        "delta_leg_kw": 0.0,
        "inv_temp": 0.0,
        "bat_temp": 0.0,
        "last_update": None,
    }

# ─── MQTT CALLBACKS ────────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        st.session_state.connected = True
        topic = f"open/{st.session_state.access_key}/{st.session_state.device_sn}/status"
        client.subscribe(topic)
        st.session_state.state["last_update"] = datetime.now()
        log_event("Connected to broker")
    else:
        st.session_state.connected = False
        log_event(f"Connection failed (rc={rc})")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        params = payload.get("params", {})
        # map your params into our state keys
        st.session_state.state.update({
            "shore_kw": params.get("invChgPow", 0) / 1000.0,
            "soc_pct": params.get("socSum", 0),
            "empty_min": params.get("runtime", 0),
            "leg1_kw": params.get("acOutPwrR", 0) / 1000.0,
            "leg2_kw": params.get("acOutPwrS", 0) / 1000.0,
            "delta_leg_kw": abs(params.get("acOutPwrR", 0) - params.get("acOutPwrS", 0)) / 1000.0,
            "inv_temp": params.get("invTemp", 0),
            "bat_temp": params.get("batTemp", 0),
        })
        st.session_state.state["last_update"] = datetime.now()
    except Exception as e:
        log_event(f"Message parse error: {e}")

def log_event(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.log.append(f"{timestamp}  {msg}")

# ─── MQTT CONNECTOR ────────────────────────────────────────────────────────────
def connect_mqtt():
    # reset log
    st.session_state.log = []
    broker = st.session_state.broker.strip()
    key    = st.session_state.access_key.strip()
    secret = st.session_state.secret_key.strip()
    sn     = st.session_state.device_sn.strip()
    if not all([broker, key, secret, sn]):
        log_event("❗ Missing credentials – cannot connect")
        return

    # stop any old client
    if st.session_state.mqtt_client:
        try:
            st.session_state.mqtt_client.loop_stop()
            st.session_state.mqtt_client.disconnect()
        except: pass

    client = mqtt.Client()
    client.tls_set()  # system CAs
    client.username_pw_set(key, secret)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(broker, 8883, keepalive=60)
        client.loop_start()
        st.session_state.mqtt_client = client
    except Exception as e:
        log_event(f"❌ Connect error: {e}")
        st.session_state.connected = False

# ─── SIDEBAR ──────────────────────────────────────────────────────────────
st.sidebar.title("Live mode credentials")

# 1) Text inputs, all bound into session_state via `key=…`
broker     = st.sidebar.text_input("Broker",     value="mqtt-e.ecoflow.com", key="broker")
access_key = st.sidebar.text_input("AccessKey",  key="access_key")
secret_key = st.sidebar.text_input("SecretKey",  type="password", key="secret_key")
device_sn  = st.sidebar.text_input("Device SN",  key="device_sn")

# 2) Connect / Update button
if st.sidebar.button("Connect / Update"):
    # Reset the event log on each connect attempt
    st.session_state.log = ["-- Event log --"]
    start_mqtt_loop(
        broker=broker,
        acc=access_key,
        sec=secret_key,
        sn=device_sn,
    )
    st.experimental_rerun()  # re-render immediately so you see ONLINE/OFFLINE

# 3) Ensure we always have a log list in session_state
if "log" not in st.session_state:
    st.session_state.log = ["-- Event log --"]

# ─── HEADER ────────────────────────────────────────────────────────────────────
cols = st.columns([1,2,1])
with cols[0]:
    st.image("header.png", use_column_width=True)
with cols[2]:
    st.image("into_the_millennium.png", use_column_width=True)

# ─── MAIN TITLE + PANEL STATUS ─────────────────────────────────────────────────
status_color = "green" if st.session_state.connected else "red"
st.markdown(
    f"### UFO PDU STATUS   <span style='color:{status_color};'>**{'ONLINE' if st.session_state.connected else 'OFFLINE'}**</span>",
    unsafe_allow_html=True
)
 status_color = "green" if st.session_state.connected else "red"
 st.markdown(
     f"### UFO PDU STATUS   <span style='color:{status_color};'>"
     f"**{'ONLINE' if st.session_state.connected else 'OFFLINE'}**</span>",
     unsafe_allow_html=True
 )

-# ─── METRIC CARDS ─────────────────────────────────────────────────────────────
-m = st.session_state.state
-metric_cols = st.columns(3)
-metric_cols[0].metric("Shore kW",    f"{m['shore_kw']:.1f}")
-metric_cols[1].metric("SoC %",       f"{m['soc_pct']:.1f}")
-metric_cols[2].metric("Empty min",    f"{m['empty_min']:.1f}")

# ─── LIVE METRICS (from STATE) ────────────────────────────────────────────────
conn_text = "ONLINE" if STATE.get("connected") else "OFFLINE"
st.markdown(f"**Panel status:** {conn_text}")

st.metric("State of Charge", f"{STATE.get('soc', 0):.1f}%")
st.metric("Shore kW",         f"{STATE.get('shore_kw', 0):.2f}")
st.metric("Leg-1 kW",         f"{STATE.get('leg1_kw', 0):.2f}")
st.metric("Leg-2 kW",         f"{STATE.get('leg2_kw', 0):.2f}")

# ─── BREAKER TABLES ────────────────────────────────────────────────────────────
table_cols = st.columns(2)
# Leg 1
leg1 = {
    "Name":   ["B1","B3","B5","B7","B9","B11"],
    "A":      [], "kW": [], "Peak": []
}
leg2 = {
    "Name":   ["B2","B4","B6","B8","B10","B12"],
    "A":      [], "kW": [], "Peak": []
}
# populate from state (or zero)
for name in leg1["Name"]:
    # grab a dummy amperage from state if exists, else 0
    A = m["leg1_kw"] *  AmpPerKW  if "leg1_kw" in m else 0
    KW = m["leg1_kw"]
    leg1["A"].append(f"{A:.1f}")
    leg1["kW"].append(f"{KW:.2f}")
    leg1["Peak"].append(f"{max(KW, m.get('peak_leg1_kw',0)):.2f}")
for name in leg2["Name"]:
    A = m["leg2_kw"] * AmpPerKW
    KW = m["leg2_kw"]
    leg2["A"].append(f"{A:.1f}")
    leg2["kW"].append(f"{KW:.2f}")
    leg2["Peak"].append(f"{max(KW, m.get('peak_leg2_kw',0)):.2f}")

with table_cols[0]:
    st.write("**Leg 1**")
    st.table(leg1)
with table_cols[1]:
    st.write("**Leg 2**")
    st.table(leg2)

# ─── EVENT LOG ────────────────────────────────────────────────────────────────
log_col, _ = st.columns([2,1])
with log_col:
    st.write("**Event log**")
    st.text_area("", value="\n".join(st.session_state.log), height=200)

# ─── KEEP STREAMLIT RUNNING ────────────────────────────────────────────────────
# no manual rerun needed—loop is in background via paho.loop_start()