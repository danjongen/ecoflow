#!/usr/bin/env python3
################################################################################
#  UFO PDU STATUS · v1.9   (fully hard-coded creds, dark-mode + auto-refresh)
################################################################################

import os
import json
import time
import threading
import pathlib
from datetime import datetime

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ───────── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="UFO PDU",
    layout="wide",
    initial_sidebar_state="auto",
)

# ───────── Base path for images ─────────────────────────────────────────────
BASE = pathlib.Path(__file__).parent

# ───────── Config constants ──────────────────────────────────────────────────
USABLE_WH       = float(os.getenv("USABLE_WH", "11000"))
INV_SHUT, INV_RED, INV_ORG = 65, 55, 45
BAT_SHUT, BAT_RED, BAT_ORG = 55, 45, 35
LEG_RED, LEG_ORG = 6.0, 5.0
BRK_RED, BRK_ORG = 2.0, 1.5
c2f = lambda c: c * 9/5 + 32
EDGE = dict(red="#e74c3c", orange="#f39c12", green="#27ae60",
            blue="#3498db", gray="#2e2e2e")
CARD_BG = "#1a1a1a"

# ───────── Hard-coded live credentials ────────────────────────────────────────
cfg = {
    "broker":   "mqtt-e.ecoflow.com",
    "akey":     "Tf9MP4iMBbymFIbVXQKArJd1IreqXDZt",
    "skey":     "upmnU2HTFRuVuBkXTIRtCq6NgYBTaTB2",
    "sn":       "HD31ZAS4HGC70401",
}

# ───────── Global state ──────────────────────────────────────────────────────
lock = threading.Lock()
state = {
    "soc": 0, "l1": 0, "l2": 0, "grid": 0,
    "mins": 0, "inv": 0, "bat": 0,
    "brk": {}, "events": [], "last": None
}
peaks = {i: 0 for i in range(1, 13)}

# ───────── Helpers ───────────────────────────────────────────────────────────
def card(lbl, val, u="", *, red=None, orange=None, fmt="{:.1f}"):
    edge = EDGE["green"]
    if red     is not None and val >= red:    edge = EDGE["red"]
    if orange  is not None and val >= orange: edge = EDGE["orange"]
    html = f"""
    <div style='position:relative;margin:6px 0;padding:8px 12px 6px 16px;
                background:{CARD_BG};border-radius:6px;box-shadow:0 0 4px #0007;'>
      <div style='position:absolute;left:0;top:0;width:8px;height:100%;
                  background:{edge};border-radius:6px 0 0 6px;'></div>
      <span style='font-size:16px;color:#ccc;font-weight:600;'>{lbl}</span><br>
      <span style='font-size:24px;font-weight:700;color:#fafafa;'>
        {fmt.format(val)}{u}</span>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def recalc_minutes():
    tot = max(state["l1"] + state["l2"], 0.001)
    state["mins"] = (state["soc"]/100 * USABLE_WH) / (tot*1000) * 60

def log_event(msg):
    with lock:
        state["events"].insert(0, (datetime.now(), msg))
        state["events"] = state["events"][:200]

def update_peak(i, v):
    with lock:
        peaks[i] = max(peaks[i], v)

def on_packet(params: dict):
    with lock:
        # adapt these to your payload keys if needed
        state.update(
            soc   = params.get("soc",   state["soc"]),
            l1    = params.get("l1",    state["l1"]),
            l2    = params.get("l2",    state["l2"]),
            grid  = params.get("grid",  state["grid"]),
            inv   = params.get("invt",  state["inv"]),
            bat   = params.get("batt",  state["bat"]),
            brk   = params.get("breakers", state["brk"]),
            last  = datetime.now(),
        )
        recalc_minutes()
        for slot, br in state["brk"].items():
            update_peak(slot, br.get("kw", 0.0))

# ───────── MQTT setup ────────────────────────────────────────────────────────
def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        log_event("✅ MQTT connected!")
        client.subscribe(f"open/{cfg['akey']}/{cfg['sn']}/status", qos=0)
    else:
        log_event(f"❌ MQTT connect failed code={rc}")

def mqtt_loop():
    client = mqtt.Client()
    client.username_pw_set(cfg["akey"], cfg["skey"])
    client.tls_set()
    client.on_connect = on_mqtt_connect
    client.on_message = lambda c,u,m: on_packet(json.loads(m.payload)["params"])
    try:
        client.connect(cfg["broker"], 8883)
        client.loop_forever()
    except Exception as e:
        log_event(f"❌ MQTT exception: {e}")

# ───────── Page header & logo ────────────────────────────────────────────────
logo = BASE / "header.png"
pin  = BASE / "into_the_millennium.png"
if logo.exists() and pin.exists():
    c1,c2 = st.columns(2, gap="medium")
    c1.image(str(logo), width=400)
    c2.image(str(pin),  width=400)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
elif logo.exists():
    st.image(str(logo), use_container_width=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

st.markdown("<h1 style='text-align:center;color:#eee;'>UFO PDU STATUS</h1>",
            unsafe_allow_html=True)
st.markdown("<style>body{background:#111;} th,td{font-size:14px;}</style>",
            unsafe_allow_html=True)

def badge():
    if state["last"] is None:
        return "<span style='background:#7f8c8d;color:#fff;padding:2px 6px;'>no data</span>"
    age = (datetime.now() - state["last"]).total_seconds()
    col = EDGE["green"] if age < 10 else EDGE["orange"] if age < 30 else EDGE["red"]
    return f"<span style='background:{col};color:#fff;padding:2px 6px;'>{age:.0f}s</span>"

# ───────── Render function ──────────────────────────────────────────────────
def render():
    with lock:
        data = dict(state)  # shallow copy

    # Panel status
    status = "ONLINE" if data["last"] else "OFFLINE"
    st.markdown(f"**Panel status:** `{status}`")

    left, right = st.columns([1,3], gap="large")
    with left:
        card("Shore kW",  data["grid"])
        card("SoC %",     data["soc"], fmt="{:.1f}")
        card("Empty min", data["mins"], fmt="{:.1f}")
        card("Leg-1 kW",  data["l1"], red=LEG_RED, orange=LEG_ORG)
        card("Leg-2 kW",  data["l2"], red=LEG_RED, orange=LEG_ORG)
        card("Δ Leg kW",  abs(data["l1"] - data["l2"]),
             red=LEG_RED, orange=LEG_ORG)
        card(f"Inv °F (shut {c2f(INV_SHUT):.0f})",
             c2f(data["inv"]), red=c2f(INV_RED), orange=c2f(INV_ORG),
             fmt="{:.0f}")
        card(f"Bat °F (shut {c2f(BAT_SHUT):.0f})",
             c2f(data["bat"]), red=c2f(BAT_RED), orange=c2f(BAT_ORG),
             fmt="{:.0f}")

    # breaker tables
    def mk_table(legno):
        rows = [{**d, "slot":i} for i,d in data["brk"].items() if d.get("leg")==legno]
        df = pd.DataFrame(rows)
        if df.empty:
            return None
        df = df.sort_values("slot")
        df["Peak"] = df["slot"].map(peaks)
        df = df[["name","amps","kw","Peak"]]
        df.columns = ["Name","A","kW","Peak"]
        def style_r(r):
            bg = EDGE["gray"]
            if r["kW"]>=BRK_RED:   bg=EDGE["red"]
            elif r["kW"]>=BRK_ORG: bg=EDGE["orange"]
            return [f"background-color:{bg};"]*4
        return (df.style
                .format({"A":"{:.1f}","kW":"{:.2f}","Peak":"{:.2f}"})
                .apply(style_r,axis=1)
                .set_table_styles([{"selector":"th","props":"background:#333;color:#ddd;"}]))

    hb = badge()
    t1,t2 = right.columns(2)
    t1.markdown(f"### Leg 1 {hb}", unsafe_allow_html=True)
    tbl1 = mk_table(1)
    t1.dataframe(tbl1, height=280, use_container_width=True) if tbl1 else t1.write("No data")
    t2.markdown(f"### Leg 2 {hb}", unsafe_allow_html=True)
    tbl2 = mk_table(2)
    t2.dataframe(tbl2, height=280, use_container_width=True) if tbl2 else t2.write("No data")

    # bottom charts & log
    c1,c2 = right.columns([2,1])
    if data["brk"]:
        top = (pd.DataFrame(data["brk"]).T
               .sort_values("kw",ascending=False)
               .head(5).reset_index())
        top["col"] = top["kw"].apply(lambda x:
            EDGE["red"] if x>=BRK_RED else EDGE["orange"] if x>=BRK_ORG else EDGE["gray"]
        )
        chart = (alt.Chart(top).mark_bar().encode(
            x=alt.X("kw:Q", title="kW", scale=alt.Scale(domain=[0,BRK_RED+0.5])),
            y=alt.Y("name:N", sort="-x", title=None),
            color=alt.Color("col:N", scale=None, legend=None)
        ).properties(height=180))
        c1.subheader("Top breakers kW")
        c1.altair_chart(chart, use_container_width=True)

    c2.subheader("Event log")
    for ts,msg in data["events"]:
        c2.markdown(f"`{ts:%H:%M:%S}` {msg}")

# ───────── Start MQTT thread & auto-refresh ─────────────────────────────────
threading.Thread(target=mqtt_loop, daemon=True).start()

# Auto-refresh every 1s
count = st.experimental_get_query_params().get("refresh_count", ["0"])[0]
count = int(count) + 1
st.experimental_set_query_params(refresh_count=count)
time.sleep(1)
st.experimental_rerun()