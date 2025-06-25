################################################################################
#  UFO PDU STATUS · v1.8c  (complete file – ready to run, dark‐mode + robust)
################################################################################
import os, json, time, threading, math, random, pathlib
from datetime import datetime
import streamlit as st, pandas as pd, altair as alt
import paho.mqtt.client as mqtt

# ───────── Ensure dark theme via .streamlit/config.toml ─────────────────────
# (create .streamlit/config.toml with:
#   [theme]
#   base = "dark"
#)

# ───────── Base path for images ─────────────────────────────────────────────
BASE = pathlib.Path(__file__).parent

# ───────── Config ────────────────────────────────────────────────────────────
USABLE_WH       = float(os.getenv("USABLE_WH", "11000"))
INV_SHUT,INV_RED,INV_ORG = 65, 55, 45
BAT_SHUT,BAT_RED,BAT_ORG = 55, 45, 35
LEG_RED,LEG_ORG = 6.0, 5.0
BRK_RED,BRK_ORG = 2.0, 1.5
c2f = lambda c: c*9/5 + 32
EDGE = dict(red="#e74c3c", orange="#f39c12", green="#27ae60",
            blue="#3498db", gray="#2e2e2e")
CARD_BG = "#1a1a1a"

# ───────── Global state ──────────────────────────────────────────────────────
lock = threading.Lock()
state = {
    "soc":0, "l1":0, "l2":0, "grid":0, "shore":True,
    "mins":0, "inv":0, "bat":0, "brk":{}, "events":[], "last":None
}
peaks = {i:0 for i in range(1,13)}

# ───────── Sidebar (demo vs live setup) ─────────────────────────────────────
with st.sidebar:
    st.header("Run mode")
    DEMO = st.checkbox("Demo mode", value=True)
    if not DEMO:
        broker = st.text_input("Broker", "mqtt-e.ecoflow.com")
        akey   = st.text_input("AccessKey")
        skey   = st.text_input("SecretKey", type="password")
        sn     = st.text_input("Device SN")
        if st.button("Connect / Update"):
            if akey and skey and sn:
                st.session_state.live = dict(
                    broker=broker, akey=akey, skey=skey, sn=sn
                )
            st.rerun()
cfg = st.session_state.get("live", {}) if not DEMO else {}

# ───────── Helpers ───────────────────────────────────────────────────────────
def card(lbl, val, u="", *, red=None, orange=None, fmt="{:.1f}"):
    edge = EDGE["green"]
    if red is not None and val >= red:
        edge = EDGE["red"]
    if orange is not None and val >= orange:
        edge = EDGE["orange"]
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
    state["mins"] = (state["soc"]/100*USABLE_WH)/(tot*1000)*60

def log_event(msg):
    with lock:
        state["events"].insert(0,(datetime.now(),msg))
        state["events"] = state["events"][:200]

def update_peak(i,v):
    with lock:
        peaks[i] = max(peaks[i], v)

# ───────── Data callbacks ────────────────────────────────────────────────────
def on_packet(p):
    with lock:
        state.update(
            soc  = p["socSum"],
            l1   = p["invOutPwrR"]/1000,
            l2   = p["invOutPwrS"]/1000,
            grid = (p["gridPwrR"]+p["gridPwrS"])/1000,
            shore= (p["gridPwrR"]+p["gridPwrS"])>100,
            inv  = max(p.get("invTempR",0), p.get("invTempS",0)),
            bat  = p.get("batTemp",0),
            brk  = {b["id"]: dict(
                        name=b["name"],
                        amps=b["current"]/1000,
                        kw=b["power"]/1000,
                        leg=1 if b["phase"]=="R" else 2
                    ) for b in p["breakerStatus"]},
            last = datetime.now()
        )
        recalc_minutes()
    for i,d in state["brk"].items():
        update_peak(i,d["kw"])

def mqtt_loop():
    if not (cfg.get("akey") and cfg.get("skey") and cfg.get("sn")):
        log_event("MQTT config missing → demo mode")
        return demo_loop()
    cli = mqtt.Client()
    cli.username_pw_set(cfg["akey"], cfg["skey"])
    cli.tls_set()
    cli.on_message = lambda *_a,m: on_packet(json.loads(m.payload)["params"])
    cli.connect(cfg["broker"], 8883)
    cli.subscribe(f"open/{cfg['akey']}/{cfg['sn']}/status",0)
    cli.loop_forever()

def demo_loop():
    start = time.time()
    log_event("Demo started")
    while True:
        t = time.time()-start
        tot = 6 + 2*math.sin(t/9) + 0.6*random.random()
        l1 = tot*(0.5+random.uniform(-.12,.12))
        l2 = tot-l1
        brk = {i: dict(
                    name=f"B{i}", amps=random.uniform(0,2),
                    kw=random.uniform(0,.28), leg=1 if i%2 else 2
                ) for i in range(1,13)}
        brk[3]["kw"] = random.uniform(1.8,2.2)
        brk[3]["amps"] = brk[3]["kw"]*4.16
        with lock:
            state.update(
                soc  = max(3,85-t/140),
                l1   = l1, l2 = l2, grid = 0, shore=False,
                inv  = random.uniform(30,60), bat  = random.uniform(25,50),
                brk  = brk, last = datetime.now()
            )
            recalc_minutes()
        for i,d in brk.items(): update_peak(i,d["kw"])
        time.sleep(1)

# ───────── Page header ──────────────────────────────────────────────────────
st.set_page_config("UFO PDU", layout="wide", initial_sidebar_state="collapsed")
logo = BASE/"header.png"; pin = BASE/"into the millennium.png"
if logo.exists() and pin.exists():
    c1,c2 = st.columns(2, gap="medium")
    c1.image(str(logo), width=400)
    c2.image(str(pin),  width=400)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
elif logo.exists():
    st.image(str(logo), use_container_width=True)
    # <-- removed the extra ')' here
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

st.markdown(
    "<h1 style='text-align:center;color:#eee;margin-bottom:8px;'>UFO PDU STATUS</h1>",
    unsafe_allow_html=True
)
st.markdown("<style>body{background:#111;} th,td{font-size:14px;}</style>",
            unsafe_allow_html=True)

def badge():
    if DEMO:
        return "<span style='background:#3498db;color:#fff;padding:2px 6px;border-radius:4px'>DEMO</span>"
    if state["last"] is None:
        return "<span style='background:#7f8c8d;color:#fff;padding:2px 6px;border-radius:4px'>no&nbsp;data</span>"
    age = (datetime.now()-state["last"]).total_seconds()
    col = EDGE["green"] if age<10 else EDGE["orange"] if age<30 else EDGE["red"]
    return f"<span style='background:{col};color:#fff;padding:2px 6px;border-radius:4px'>{age:.0f}s</span>"

# ───────── Render UI ────────────────────────────────────────────────────────
def render():
    with lock: data = state.copy()
    left,right = st.columns([1,3], gap="large")

    with left:
        card("Shore kW", data["grid"])
        card("SoC %", data["soc"], fmt="{:.1f}")
        card("Empty min", data["mins"], fmt="{:.1f}")
        card("Leg-1 kW", data["l1"], red=LEG_RED, orange=LEG_ORG)
        card("Leg-2 kW", data["l2"], red=LEG_RED, orange=LEG_ORG)
        card("Δ Leg kW", abs(data["l1"]-data["l2"]), red=LEG_RED, orange=LEG_ORG)
        card(f"Inv °F (shut {c2f(INV_SHUT):.0f})", c2f(data["inv"]),
             red=c2f(INV_RED), orange=c2f(INV_ORG), fmt="{:.0f}")
        card(f"Bat °F (shut {c2f(BAT_SHUT):.0f})", c2f(data["bat"]),
             red=c2f(BAT_RED), orange=c2f(BAT_ORG), fmt="{:.0f}")

    leg1 = [{**d, "slot":i} for i,d in data["brk"].items() if d["leg"]==1]
    leg2 = [{**d, "slot":i} for i,d in data["brk"].items() if d["leg"]==2]

    def tbl(rows):
        df = pd.DataFrame(rows)
        if df.empty:
            return st.write("No data")
        df = df.sort_values("slot")
        df["Peak"] = df["slot"].map(peaks)
        df = df[["name","amps","kw","Peak"]]
        df.columns = ["Name","A","kW","Peak"]
        def style_row(r):
            c = EDGE["gray"]
            if r["kW"] >= BRK_RED:   c = EDGE["red"]
            elif r["kW"] >= BRK_ORG: c = EDGE["orange"]
            return [f"background-color:{c}"]*4
        return (df.style.format({"A":"{:.1f}","kW":"{:.2f}","Peak":"{:.2f}"})
                    .apply(style_row, axis=1)
                    .set_table_styles([{"selector":"th","props":"background:#333;color:#ddd;"}]))

    hb = badge()
    t1,t2 = right.columns(2)
    t1.markdown(f"### Leg 1 {hb}", unsafe_allow_html=True)
    t1.dataframe(tbl(leg1), height=280, use_container_width=True)
    t2.markdown(f"### Leg 2 {hb}", unsafe_allow_html=True)
    t2.dataframe(tbl(leg2), height=280, use_container_width=True)

    c1,c2 = right.columns([2,1])
    if data["brk"]:
        top = (pd.DataFrame(data["brk"]).T.sort_values("kw", ascending=False)
                    .head(5).reset_index())
        top["col"] = top["kw"].apply(
            lambda x: EDGE["red"] if x>=BRK_RED
                      else EDGE["orange"] if x>=BRK_ORG
                      else EDGE["gray"])
        chart = (alt.Chart(top)
                 .mark_bar()
                 .encode(
                     x=alt.X("kw:Q", title="kW", scale=alt.Scale(domain=[0, BRK_RED+0.5])),
                     y=alt.Y("name:N", sort="-x", title=None),
                     color=alt.Color("col:N", scale=None, legend=None)
                 ).properties(height=180))
        c1.subheader("Top breakers kW")
        c1.altair_chart(chart, use_container_width=True)

    c2.subheader("Event log")
    with c2.container(height=180, border=True):
        for ts,msg in data["events"]:
            c2.markdown(f"`{ts:%H:%M:%S}` {msg}")

# ───────── Launch ───────────────────────────────────────────────────────────
threading.Thread(target=(demo_loop if DEMO else mqtt_loop),
                 daemon=True).start()

while True:
    render()
    time.sleep(1)
    st.rerun()