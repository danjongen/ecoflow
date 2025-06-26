#!/usr/bin/env python3
################################################################################
# UFO PDU STATUS · v2.0  (all-in-one, dark-mode, hard-coded creds, auto-update)   #
################################################################################

import json
import threading
import pathlib
from datetime import datetime
import traceback

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ───────── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="UFO PDU",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ───────── Force dark mode & tweak tables ────────────────────────────────────
st.markdown(
    """
    <style>
      body { background: #111; color: #eee; }
      th, td { color: #ddd !important; font-size: 14px; }
      .streamlit-expanderHeader { color: #fff; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ───────── Base path for images ─────────────────────────────────────────────
BASE = pathlib.Path(__file__).parent

# ───────── Static config ─────────────────────────────────────────────────────
USABLE_WH = 11000.0  # adjust if your battery size differs

# shut/alert thresholds
INV_SHUT, INV_RED, INV_ORG = 65, 55, 45
BAT_SHUT, BAT_RED, BAT_ORG = 55, 45, 35
LEG_RED, LEG_ORG       = 6.0, 5.0
BRK_RED, BRK_ORG       = 2.0, 1.5

# conversion
c2f = lambda c: c * 9/5 + 32

# colors
EDGE = dict(red="#e74c3c", orange="#f39c12", green="#27ae60",
            blue="#3498db", gray="#2e2e2e")
CARD_BG = "#1a1a1a"

# ───────── Hard-coded Live credentials ───────────────────────────────────────
BROKER    = "mqtt-e.ecoflow.com"
ACCESSKEY = "Tf9MP4iMBbymFIbVXQKArJd1IreqXDZt"
SECRETKEY = "upmnU2HTFRuVuBkXTIRtCq6NgYBTaTB2"
DEVICESN  = "HD31ZAS4HGC70401"

# ───────── Global state containers ────────────────────────────────────────────
lock = threading.Lock()
state = {
    "soc":0, "l1":0, "l2":0, "shore":True, "grid":0,
    "mins":0, "inv":0, "bat":0, "brk":{}, "events":[], "last":None,
    "error": None,
}
peaks = {i:0.0 for i in range(1,13)}

# ───────── Helpers ───────────────────────────────────────────────────────────
def log_event(msg):
    """Prepend an event to the log (up to 200 entries)."""
    with lock:
        state["events"].insert(0, (datetime.now(), msg))
        state["events"] = state["events"][:200]

def recalc_minutes():
    """Estimate minutes left at current draw."""
    draw_kw = max(state["l1"] + state["l2"], 0.001)
    state["mins"] = (state["soc"]/100*USABLE_WH) / (draw_kw*1000) * 60

def update_peak(i, v):
    """Remember the peak kW seen on breaker i."""
    with lock:
        peaks[i] = max(peaks[i], v)

def on_packet(params):
    """Called for each incoming MQTT message JSON→update state."""
    with lock:
        state.update(
            soc   = params.get("soc",    state["soc"]),
            l1    = params.get("l1",     state["l1"]),
            l2    = params.get("l2",     state["l2"]),
            shore = params.get("shore",  state["shore"]),
            grid  = params.get("grid",   state["grid"]),
            inv   = params.get("invt",   state["inv"]),
            bat   = params.get("batt",   state["bat"]),
            brk   = params.get("breakers",state["brk"]),
            last  = datetime.now(),
        )
        recalc_minutes()
        for idx, br in state["brk"].items():
            update_peak(idx, br.get("kw", 0.0))

# ───────── MQTT callbacks & thread ──────────────────────────────────────────
def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        log_event("✅ MQTT connected")
        with lock:
            state["error"] = None
        topic = f"open/{ACCESSKEY}/{DEVICESN}/status"
        client.subscribe(topic, qos=0)
    else:
        log_event(f"❌ MQTT conn fail, rc={rc}")
        with lock:
            state["error"] = f"Connect RC={rc}"

def mqtt_start():
    """Spawn an MQTT client that feeds state via on_packet()."""
    try:
        client = mqtt.Client()
        client.username_pw_set(ACCESSKEY, SECRETKEY)
        client.tls_set()
        client.on_connect = on_mqtt_connect
        client.on_message = lambda c, u, m: (
            log_event(f"📥 raw: {m.payload!r}"),
            on_packet(json.loads(m.payload)["params"])
        )
        client.connect(BROKER, 8883)
        client.loop_start()
    except Exception as e:
        err = traceback.format_exc()
        with lock:
            state["error"] = err
        log_event(f"❌ MQTT exception: {e}")

# Launch it once (in its own daemon thread):
threading.Thread(target=mqtt_start, daemon=True).start()

# ───────── Card renderer ─────────────────────────────────────────────────────
def card(label, val, unit="", red=None, orange=None, fmt="{:.1f}"):
    """Draw one of the left-hand metric cards."""
    edge = EDGE["green"]
    if red    is not None and val >= red:    edge = EDGE["red"]
    if orange is not None and val >= orange: edge = EDGE["orange"]
    html = f"""
      <div style='position:relative;margin:6px 0;padding:8px 12px 6px 16px;
                  background:{CARD_BG};border-radius:6px;box-shadow:0 0 4px #0007;'>
        <div style='position:absolute;left:0;top:0;width:8px;height:100%;
                    background:{edge};border-radius:6px 0 0 6px;'></div>
        <span style='font-size:16px;color:#ccc;font-weight:600;'>{label}</span><br>
        <span style='font-size:24px;font-weight:700;color:#fafafa;'>
          {fmt.format(val)}{unit}</span>
      </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ───────── Load & show logos ─────────────────────────────────────────────────
logo = BASE / "header.png"
pin  = BASE / "into_the_millenium.png"

if logo.exists() and pin.exists():
    c1, c2 = st.columns(2, gap="large")
    c1.image(str(logo), width=350)
    c2.image(str(pin),  width=350)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
elif logo.exists():
    st.image(str(logo), use_container_width=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# Title
st.markdown(
    "<h1 style='text-align:center;color:#eef;margin-bottom:12px;'>UFO PDU STATUS</h1>",
    unsafe_allow_html=True
)

# ───────── Render function ──────────────────────────────────────────────────
def render():
    with lock:
        data = dict(state)  # snapshot

    # ONLINE/OFFLINE badge
    status = "ONLINE" if data["last"] else "OFFLINE"
    color  = "#2ecc71" if data["last"] else "#e74c3c"
    st.markdown(
        f"**Panel status:** `<span style='color:{color}'>{status}</span>`",
        unsafe_allow_html=True
    )

    # show any connection error
    if data.get("error"):
        st.error("MQTT Error:\n" + data["error"])

    # split into two columns
    left, right = st.columns([1,3], gap="large")

    # Left: metric cards
    with left:
        card("Shore kW",    data["grid"], fmt="{:.2f}")
        card("SoC %",       data["soc"], fmt="{:.1f}%")
        card("Est. min",    data["mins"], fmt="{:.1f}")
        card("Leg1 kW",     data["l1"], red=LEG_RED, orange=LEG_ORG, fmt="{:.2f}")
        card("Leg2 kW",     data["l2"], red=LEG_RED, orange=LEG_ORG, fmt="{:.2f}")
        card("Δ Leg kW",    abs(data["l1"]-data["l2"]), red=LEG_RED, orange=LEG_ORG, fmt="{:.2f}")
        card(f"Inv °F (shut {c2f(INV_SHUT):.0f})", c2f(data["inv"]),
             red=c2f(INV_RED), orange=c2f(INV_ORG), fmt="{:.0f}")
        card(f"Bat °F (shut {c2f(BAT_SHUT):.0f})", c2f(data["bat"]),
             red=c2f(BAT_RED), orange=c2f(BAT_ORG), fmt="{:.0f}")

    # Right: breaker tables + chart + log
    def make_table(rows):
        df = pd.DataFrame(rows)
        if df.empty:
            st.write("No data")
            return
        df = df.sort_values("slot")
        df["Peak"] = df["slot"].map(peaks)
        df = df[["name","amps","kw","Peak"]]
        df.columns = ["Name","A","kW","Peak"]
        def style_row(r):
            bg = EDGE["gray"]
            if r.kW >= BRK_RED:   bg = EDGE["red"]
            elif r.kW >= BRK_ORG: bg = EDGE["orange"]
            return [f"background-color:{bg};"]*4
        styled = (df.style
                  .format({"A":"{:.1f}","kW":"{:.2f}","Peak":"{:.2f}"})
                  .apply(style_row, axis=1)
                  .set_table_styles([{
                     "selector":"th",
                     "props":[("background","#333"),("color","#ddd")]
                  }]))
        st.dataframe(styled, height=260, use_container_width=True)

    # freshness badge
    hb = "<span style='color:#fff;background:#444;padding:3px 6px;border-radius:4px;'>no data</span>"
    if data["last"]:
        age = (datetime.now()-data["last"]).total_seconds()
        col = EDGE["green"] if age<10 else EDGE["orange"] if age<30 else EDGE["red"]
        hb = f"<span style='color:#fff;background:{col};padding:3px 6px;border-radius:4px;'>{age:.0f}s</span>"

    # build lists by leg
    leg1 = [{**d,"slot":i} for i,d in data["brk"].items() if d.get("leg")==1]
    leg2 = [{**d,"slot":i} for i,d in data["brk"].items() if d.get("leg")==2]

    t1, t2 = right.columns(2, gap="medium")
    t1.markdown(f"### Leg 1 {hb}", unsafe_allow_html=True)
    make_table(leg1)
    t2.markdown(f"### Leg 2 {hb}", unsafe_allow_html=True)
    make_table(leg2)

    # bottom: top breakers chart + log
    c1, c2 = right.columns([2,1], gap="medium")
    if data["brk"]:
        top = (pd.DataFrame(data["brk"]).T
               .sort_values("kw",ascending=False).head(5)
               .reset_index().rename(columns={"index":"name"}))
        top["col"] = top.kw.apply(
            lambda x: EDGE["red"] if x>=BRK_RED
                      else EDGE["orange"] if x>=BRK_ORG
                      else EDGE["gray"]
        )
        chart = (alt.Chart(top).mark_bar().encode(
            x=alt.X("kw:Q",title="kW",scale=alt.Scale(domain=[0,BRK_RED+0.5])),
            y=alt.Y("name:N",sort="-x",title=None),
            color=alt.Color("col:N",scale=None,legend=None)
        ).properties(height=180))
        c1.subheader("Top breakers")
        c1.altair_chart(chart, use_container_width=True)
    else:
        c1.write("No breaker data")

    # event log
    c2.subheader("Event log")
    for ts, msg in data["events"]:
        c2.markdown(f"`{ts:%H:%M:%S}`  {msg}")

# ───────── Launch ────────────────────────────────────────────────────────────
render()