import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import base64
import requests
import datetime
import importlib

st.set_page_config(page_title="小型爆發股・動能深蹲指示器 V1.0", page_icon="🚀", layout="wide")

WATCHLIST_FILE = "watchlist.json"
REPORT_FILE = "radar_report.json"
POSITIONS_FILE = "positions.json"
HISTORY_FILE = "trade_history.csv"

FEE_RATE = 0.001425 * 0.5
TAX_RATE = 0.003

DEFAULT_STOCKS = {
    "系統電 (5309)": "5309.TWO", "雙鴻 (3324)": "3324.TWO",
    "定穎投控 (6187)": "6187.TW", "閎康 (3587)": "3587.TWO",
    "弘塑 (3131)": "3131.TWO", "台燿 (6274)": "6274.TWO",
    "致伸 (4915)": "4915.TW"
}

TW_INDUSTRY_MAP = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學生技", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險業", "18": "貿易百貨業", "19": "綜合", "20": "其他業",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業"
}

def translate_industry(ind_raw):
    raw_str = str(ind_raw).strip()
    if raw_str in TW_INDUSTRY_MAP: return TW_INDUSTRY_MAP[raw_str]
    for code, name in TW_INDUSTRY_MAP.items():
        if code in raw_str: return name
    return raw_str if raw_str and raw_str not in ["None", "nan", ""] else "電子科技"

def load_json(filepath, default):
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def push_file_to_github(filepath, content_bytes):
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            get_res = requests.get(url, headers=headers)
            sha = get_res.json().get("sha") if get_res.status_code == 200 else None
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            payload = {"message": f"🤖 [Streamlit] 更新 {filepath}", "content": content_b64}
            if sha: payload["sha"] = sha
            requests.put(url, headers=headers, json=payload)
        except Exception: pass

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    push_file_to_github(filepath, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

def save_history_csv(df):
    df.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    with open(HISTORY_FILE, "rb") as f: push_file_to_github(HISTORY_FILE, f.read())

@st.cache_data(ttl=1800)
def get_twii_market_status():
    try:
        twii = yf.download("^TWII", period="3mo", interval="1d", progress=False)
        if not twii.empty:
            if isinstance(twii.columns, pd.MultiIndex): twii.columns = twii.columns.get_level_values(0)
            twii['MA20'] = twii['Close'].rolling(20).mean()
            latest = twii.iloc[-1]
            c_p, ma_p = float(latest['Close']), float(latest['MA20'])
            return (c_p >= ma_p), c_p, ma_p
    except Exception: pass
    return True, 0, 0

@st.cache_data(ttl=86400)
def get_all_taiwan_stocks():
    stocks = {}
    try:
        url_l = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        for item in requests.get(url_l, headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json():
            c, n = item.get("公司代號", "").strip(), item.get("公司簡稱", "").strip() or item.get("公司名稱", "").strip()
            cap = float(item.get("實收資本額", 0)) / 100_000_000
            if c and n: stocks[c] = {"code": c, "name": n, "market": ".TW", "market_name": "上市", "industry": translate_industry(item.get("產業別", "")), "cap": round(cap, 1)}
    except Exception: pass
    try:
        url_o = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        for item in requests.get(url_o, headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json():
            c = str(item.get("SecuritiesCompanyCode", "")).strip() or str(item.get("公司代號", "")).strip()
            n = str(item.get("CompanyBriefName", "")).strip() or str(item.get("公司簡稱", "")).strip()
            cap = float(item.get("PaidInCapital", 0) or item.get("實收資本額", 0)) / 100_000_000
            if c and n: stocks[c] = {"code": c, "name": n, "market": ".TWO", "market_name": "上櫃", "industry": translate_industry(item.get("SectorName", "")), "cap": round(cap, 1)}
    except Exception: pass
    return stocks

def resolve_taiwan_stock(query):
    q = query.strip()
    if not q: return None, "請輸入股票名稱或代號！"
    universe = get_all_taiwan_stocks()
    if q in universe: return universe[q], None
    for c, s in universe.items():
        if s['name'] == q: return s, None
    cands = [s for s in universe.values() if (q in s['name']) or (q == s['code'])]
    if len(cands) == 1:
        return cands[0], None
    elif len(cands) > 1:
        cand_str = "、".join([f"{x['name']} ({x['code']})" for x in cands[:4]])
        return None, f"符合多檔：{cand_str}，請更精確輸入"
    return None, f"查無台股標的「{q}」"

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_json(WATCHLIST_FILE, DEFAULT_STOCKS)

# ================= 側邊欄設定 =================
with st.sidebar:
    st.header("🎛️ 小型股專屬風控參數")
    with st.expander("🛡️ 實盤防禦開關", expanded=True):
        st.caption("5 槽位分散模型 (每槽 12 萬)")
        hard_stop_val = st.slider("硬停損比例 (-%)", 3.0, 7.0, 5.0, 0.5)
        tp_target_val = st.slider("階段一停利目標 (+%)", 6.0, 15.0, 8.0, 0.5)
        be_val = st.slider("動態保本啟動點 (+%)", 3.0, 6.0, 4.5, 0.5)
        time_limit_val = st.slider("時間停損交易日 (天)", 3, 7, 5, 1)

    st.header("📋 觀察名單管理")
    with st.expander("➕ 快速新增自選股票", expanded=False):
        sb_q = st.text_input("輸入名稱或 4 碼代號", placeholder="例如：系統電 或 5309", key="sb_in")
        if st.button("確認加入", type="primary", use_container_width=True, key="sb_add"):
            info, err = resolve_taiwan_stock(sb_q)
            if info:
                lbl = f"{info['name']} ({info['code']})"
                st.session_state.watchlist[lbl] = f"{info['code']}{info['market']}"
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"已新增：{lbl}")
                st.rerun()
            else: st.error(err)

    with st.expander("🗑️ 刪除自選股票", expanded=False):
        if st.session_state.watchlist:
            del_t = st.selectbox("選擇要移除的標的", options=list(st.session_state.watchlist.keys()))
            if st.button("確認刪除", use_container_width=True):
                del st.session_state.watchlist[del_t]
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"已移除：{del_t}")
                st.rerun()

st.title("🚀 小型爆發股・動能深蹲指示器 V1.0")
is_bull, twii_c, twii_ma = get_twii_market_status()
if is_bull:
    st.success(f"🟢 **大盤多頭健康**（加權指數：{twii_c:,.0f} 點 守於月線 {twii_ma:,.0f} 點之上）")
else:
    st.warning(f"🟡 **大盤月線反壓中**（加權指數：{twii_c:,.0f} 點 低於月線 {twii_ma:,.0f} 點），小型股建議空手或將部位打折！")

tab_radar, tab_tracker, tab_batch, tab_watchlist, tab_docs = st.tabs([
    "📡 今日小型動能戰報",
    "📊 5槽位實盤帳本 (方案B)",
    "🚀 自選名單技術體檢", 
    "📋 自選股票清單總覽",
    "📖 小型爆發作戰手冊"
])

# ================= TAB 0: 每日小型動能戰報 (星級評分呈現) =================
with tab_radar:
    c_title, c_scan = st.columns([3, 1.4])
    with c_title: st.subheader("📡 小型爆發股雷達・今日盤後戰報 (分級星號評分制)")
    with c_scan: btn_manual_scan = st.button("⚡ 手動立即掃描雷達", type="primary", use_container_width=True)

    if btn_manual_scan:
        with st.spinner("🚀 正在連線 2»1»4»3 小型股漏斗 ＋ 星級評分引擎... (約需 15 秒)"):
            try:
                import screener, tracker
                importlib.reload(screener)
                importlib.reload(tracker)
                screener.run_screener()
                tracker.run_tracker()
                st.success("✅ 雷達掃描與 5 槽位持倉結算已完成！")
                st.rerun()
            except Exception as e: st.error(f"❌ 掃描異常: {e}")

    st.write("---")
    report = load_json(REPORT_FILE, {})
    if not report:
        st.info("💡 目前尚未有雷達報告。每日 16:40 GitHub Actions 會自動更新產出！")
    else:
        cr1, cr2, cr3 = st.columns(3)
        cr1.metric("最後掃描時間", report.get("update_time", "未知"))
        cr2.metric("2»1»4»3 篩選留存", f"{report.get('total_funnel', 0)} 檔")
        cr3.metric("🎯 符合深蹲進場點", f"{report.get('total_squat', 0)} 檔")
        st.write("---")
        
        squat_stocks = [s for s in report.get("stocks", []) if s.get("is_squat")]
        if squat_stocks:
            three_stars = [s for s in squat_stocks if s.get('rank_score') == 3]
            two_stars = [s for s in squat_stocks if s.get('rank_score') == 2]
            
            st.success(f"🎯 **【今日焦點】：共發現 {len(squat_stocks)} 檔小型飆股符合深蹲門檻（含 🌟🌟🌟 3 星黃金狙擊 {len(three_stars)} 檔、🌟🌟 2 星強勢動能 {len(two_stars)} 檔）！**")
            
            for s in squat_stocks:
                s_name = s.get('name', '')
                s_code = str(s.get('code', '')).split('.')[0].strip()
                s_stars = s.get('rank_score', 2)
                
                with st.container():
                    c1, c2, c3, c4 = st.columns([2.2, 1.8, 2.0, 2.0])
                    
                    # 💡 徽章凸顯星級
                    if s_stars == 3:
                        c1.markdown(f"### 🏆 **{s_name} ({s_code})**")
                        c1.markdown("**:red[🌟🌟🌟 3星・黃金狙擊點 (MACD+KD)]**")
                    else:
                        c1.markdown(f"### **{s_name} ({s_code})**")
                        c1.markdown("**:orange[🌟🌟 2星・強勢動能點 (MACD)]**")
                        
                    c1.caption(f"最新收盤：${s['close']} ｜ 支撐：**{s['support']}** ｜ 股本：{s['cap']}億")
                    c1.write(f"🏷️ **類股**：`{translate_industry(s.get('industry', '電子科技'))}`")
                    
                    c2.write(f"• **投信買超**：`+{s['trust_buy']}` 張")
                    c2.write(f"• **三大法人**：`+{s.get('inst_buy', 0)}` 張")
                    c2.write(f"• **營收 YoY**：`+{s['rev_yoy']}%`")
                    c2.write(f"• **技術位階**：`K:{s.get('k_val', 0)} / D:{s.get('d_val', 0)}` (DIF: {s.get('dif_val', 0)})")
                    
                    c3.write(f"• **🎯 明日右側確認**：`突破 ${s.get('right_trigger', s['close'])}`")
                    c3.write(f"• **硬停損 (-5%)**：`${s['stop_loss']}`")
                    c3.write(f"• **目標價 (+8%)**：`${s['take_profit']}`")
                    
                    label_key = f"{s_name} ({s_code})"
                    if label_key not in st.session_state.watchlist:
                        if c4.button(f"📥 加到自選名單", key=f"r_add_{s_code}"):
                            st.session_state.watchlist[label_key] = s['ticker']
                            save_json(WATCHLIST_FILE, st.session_state.watchlist)
                            st.rerun()
                    else: c4.write("✅ 已在自選名單中")

                    yahoo_url = f"https://tw.stock.yahoo.com/quote/{s_code}/news"
                    google_url = f"https://www.google.com/search?q={s_name}+{s_code}+股票&tbm=nws&tbs=qdr:m"
                    with st.expander(f"📰 查看 {s_name} 即時新聞速查", expanded=False):
                        st.markdown(f"[📰 Yahoo 奇摩股市]({yahoo_url}) ｜ [🔍 Google 財經新聞]({google_url})")
                st.divider()
        else: st.info("⏸ 今日小型股尚未有標的剛好踩在均線窒息量深蹲點，建議空手觀望。")

# ================= TAB 1: 5 槽位實盤帳本 =================
with tab_tracker:
    st.subheader("📊 方案 B：5 槽位小型股實盤流水帳本")
    positions = load_json(POSITIONS_FILE, [])
    df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame(columns=[
        "代號", "名稱", "進場日", "進場價", "出場日", "持股天數",
        "投入金額", "回收金額", "淨損益(NTD)", "部位A_損益%", "部位B_損益%",
        "綜合報酬率%", "出場原因"
    ])

    total_trades = len(df_history)
    win_rate = (len(df_history[df_history['綜合報酬率%'] > 0]) / total_trades * 100) if total_trades > 0 else 0.0
    total_pnl = df_history['淨損益(NTD)'].sum() if total_trades > 0 else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("在倉持股數", f"{len(positions)} / 5 檔")
    m2.metric("已結案筆數", f"{total_trades} 筆")
    m3.metric("勝率", f"{win_rate:.1f} %")
    m4.metric("累積淨獲利", f"NT$ {int(total_pnl):+,d}")
    m5.metric("每槽預算", "NT$ 120,000")
    st.divider()

    st.markdown("#### 🏦 【當前持倉部位即時監控】")
    if positions:
        pos_display = []
        for p in positions:
            entry_p = float(p['entry_price'])
            curr_p = float(p.get('curr_price', entry_p))
            unreal_pct = float(p.get('unrealized_pct', 0.0))
            days = p.get('days_held', 0)
            is_ext = p.get('is_extended', False)
            limit_days = 7 if is_ext else 5
            day_str = f"{days}/{limit_days}天 🔄已展延" if is_ext else f"{days}/{limit_days}天"
            
            stop_display = f"🛡️ ${entry_p * 1.002:.1f} (保本線)" if (p.get('is_breakeven') and days >= 1) else f"🛑 ${entry_p * 0.95:.1f} (-5%)"
            tp1_display = "✅ 半倉已停利" if p.get('lot_a_sold') else f"🎯 ${entry_p * 1.08:.1f} (+8%)"

            pos_display.append({
                "評級": p.get('star_tag', "🌟🌟 2星"),
                "標的": f"{p['name']} ({p['code']})",
                "進場日": p['entry_date'],
                "交易日進度": day_str,
                "進場成本": f"${entry_p:.1f}",
                "現價 (浮盈%)": f"${curr_p:.1f} ({unreal_pct:+.2f}%)",
                "🛑 防守停損": stop_display,
                "🎯 階段一停利": tp1_display,
                "🏄 移動停利 (10MA)": f"${p.get('ma10', 0):.1f}"
            })
        st.dataframe(pd.DataFrame(pos_display), use_container_width=True, hide_index=True)
        
        with st.expander("🎯 手動平倉結案（自訂出場價記帳至歷史明細）", expanded=False):
            c_cl1, c_cl2, c_cl3 = st.columns(3)
            with c_cl1:
                target_to_close = st.selectbox("選擇要平倉標的", options=[f"{p['name']} ({p['code']})" for p in positions], key="cl_t")
                matched_pos = next((p for p in positions if f"{p['name']} ({p['code']})" == target_to_close), None)
            with c_cl2:
                default_sp = float(matched_pos.get('curr_price', matched_pos['entry_price'])) if matched_pos else 100.0
                user_ep = st.number_input("實際賣出均價", value=default_sp, step=0.1, key="cl_p")
            with c_cl3:
                user_reason = st.selectbox("結案原因", ["🎯 手動獲利了結", "🛑 手動停損離場", "⏳ 手動換股平倉"], key="cl_r")
                
            if st.button("確認結案並寫入帳本", type="primary", use_container_width=True):
                if matched_pos:
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    cost = float(matched_pos['total_invested'])
                    tot_shares = matched_pos['shares_a'] + matched_pos['shares_b']
                    rev = tot_shares * user_ep * (1 - FEE_RATE - TAX_RATE)
                    net_pnl = rev - cost
                    tot_roi = (net_pnl / cost) * 100
                    
                    new_r = {
                        "代號": matched_pos['code'], "名稱": matched_pos['name'],
                        "進場日": matched_pos['entry_date'], "進場價": matched_pos['entry_price'],
                        "出場日": today_str, "持股天數": matched_pos.get('days_held', 0),
                        "投入金額": int(cost), "回收金額": int(rev), "淨損益(NTD)": int(net_pnl),
                        "部位A_損益%": round(tot_roi, 2), "部位B_損益%": round(tot_roi, 2),
                        "綜合報酬率%": round(tot_roi, 2), "出場原因": user_reason
                    }
                    df_history = pd.concat([df_history, pd.DataFrame([new_r])], ignore_index=True)
                    save_history_csv(df_history)
                    positions = [p for p in positions if f"{p['name']} ({p['code']})" != target_to_close]
                    save_json(POSITIONS_FILE, positions)
                    st.success(f"已成功平倉 {target_to_close}！")
                    st.rerun()
    else: st.info("目前無在倉持股，5 個槽位 (共 60 萬資金) 100% 待命中。")

    if not df_history.empty:
        with st.expander("🔄 誤結案一鍵還原（撤回歷史紀錄並重返在倉監控）", expanded=False):
            h_opts = [f"第{i+1}筆：{r['名稱']} ({r['代號']}) - 進場日:{r['進場日']}" for i, r in df_history.iterrows()]
            sel_h = st.selectbox("選擇要還原的結案記錄", options=h_opts)
            h_idx = h_opts.index(sel_h)
            h_row = df_history.iloc[h_idx]
            h_code = str(h_row['代號']).split('.')[0].strip()
            
            if st.button("確認撤回此紀錄並重返持倉", type="primary", use_container_width=True):
                restored_p = {
                    "code": h_code, "name": h_row['名稱'], "ticker": f"{h_code}.TW",
                    "entry_date": h_row['進場日'], "entry_price": float(h_row['進場價']),
                    "total_invested": float(h_row['投入金額']), "shares_a": int(float(h_row['投入金額'])/float(h_row['進場價'])//2),
                    "shares_b": int(float(h_row['投入金額'])/float(h_row['進場價'])//2), "days_held": int(h_row.get('持股天數', 2)),
                    "is_breakeven": False, "lot_a_sold": False, "curr_price": float(h_row['進場價']),
                    "unrealized_pct": 0.0, "curr_stop": round(float(h_row['進場價']) * 0.95, 1),
                    "tp_stage1": round(float(h_row['進場價']) * 1.08, 1), "ma10": round(float(h_row['進場價']) * 0.99, 1),
                    "star_tag": "🌟🌟 2星"
                }
                positions.append(restored_p)
                save_json(POSITIONS_FILE, positions)
                cand_e_raw = str(h_row['進場日']).strip()
                df_history = df_history[~((df_history['代號'].astype(str).str.split('.').str[0].str.strip() == h_code) & 
                                          (df_history['進場日'].astype(str).str.strip() == cand_e_raw))].reset_index(drop=True)
                save_history_csv(df_history)
                st.success(f"已成功恢復 {h_row['名稱']} 持倉！")
                st.rerun()

    st.write("---")
    st.markdown("#### 📋 【歷史結案明細表】")
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True, hide_index=True)
    else: st.info("尚無結案紀錄，等待每日 16:40 自動追蹤結算。")

# ================= TAB 2: 自選名單技術體檢 =================
with tab_batch:
    st.subheader("🚀 自選股今日小型動能深蹲掃描")
    if st.button("⚡ 開始全自選股技術體檢", type="primary", use_container_width=True):
        triggered_list = []
        for label, ticker in st.session_state.watchlist.items():
            try:
                df = yf.download(ticker, period="3mo", interval="1d", progress=False)
                if df.empty or len(df) < 25: continue
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['VOL_MA5'] = df['Volume'].rolling(5).mean()
                df['VOL_MA20'] = df['Volume'].rolling(20).mean()

                latest = df.iloc[-1]
                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])

                cond_trend = (ma5 > ma10) and (ma10 >= ma20) and (ma20 >= df['MA20'].iloc[-4])
                touch_5 = (low <= ma5 * 1.018 and close >= ma5 * 0.99)
                touch_10 = (low <= ma10 * 1.020 and close >= ma10 * 0.99)
                cond_support = touch_5 or touch_10
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
                cond_k = abs(close - open_p) / open_p <= 0.035

                if cond_trend and cond_support and cond_vol and cond_k:
                    triggered_list.append({
                        "標的": label, "最新收盤": f"${close:,.1f}", "回測均線": "5MA" if touch_5 else "10MA",
                        "🎯 明日右側確認價": f"突破 ${high:,.1f}", "硬停損 (-5\%)": f"${high * 0.95:,.1f}",
                        "目標價 (+8%)": f"${high * 1.08:,.1f}"
                    })
            except Exception: pass
            
        if triggered_list:
            st.success(f"🎯 **自選股中今日共發現 {len(triggered_list)} 檔符合小型深蹲條件！**")
            st.dataframe(pd.DataFrame(triggered_list), use_container_width=True, hide_index=True)
        else: st.warning("今日自選股中無標的符合深蹲條件。")

# ================= TAB 3: 自選股票清單總覽 =================
with tab_watchlist:
    st.subheader("📋 自選股票清單總覽")
    profiles = get_all_taiwan_stocks()
    rows = []
    for label, ticker in st.session_state.watchlist.items():
        code = ticker.split(".")[0].strip()
        p = profiles.get(code, {})
        rows.append({
            "標的代號": label, "產業類別": p.get("industry", "電子科技"),
            "股本規模": f"{p.get('cap', 0)}億" if p.get('cap') else "小型股",
            "市場別": p.get("market_name", "上櫃")
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ================= TAB 4: 小型爆發作戰手冊 =================
with tab_docs:
    st.subheader("📖 小型爆發股・動能深蹲作戰手冊 V1.0 (方案 A 星級評分制)")
    st.info("💡 專為『股本 5~20 億、5 槽位分散、MACD+KD 雙重評級』設計的量化交易系統。")

    with st.expander("🔍 一、 2»1»4»3 漏斗 ＋ 方案 A 星級評分 SOP", expanded=True):
        st.write("• **第 1 步【第二道・籌碼密集度】**：投信近 5 日累計買超 >= 15 張，或三大法人合計買超 >= 80 張。")
        st.write("• **第 2 步【第一道・規模與健康流動性】**：實收資本額 5 億 ～ 20 億元，且近 5 日日均量 >= 500 張。")
        st.write("• **第 3 步【第四道・技術面深蹲壓縮 ＋ MACD 核心動能】**：回踩 5MA 或 10MA，成交量低於 5MV & 20MV，K 棒實體振幅 <= 3.5%，且 **MACD DIF > 0 柱狀體翻紅或縮短**。")
        st.write("• **第 4 步【第三道・營收動能加速】**：最新單月營收年增率 YoY >= 20.0%。")
        st.write("• **🌟🌟🌟 3 星黃金狙擊點判定**：若同時滿足上述條件 ＋ **KD 位於 30～65 且轉折向上/金叉**，標記為 3 星，實盤系統優先分配資金開倉！")

    with st.expander("🛑 二、 5 槽位出賽與風控紀律", expanded=True):
        st.write("• **5 槽位分散模型**：60 萬總資金切分為 5 槽位，每槽 12 萬元。")
        st.write("• **🛑 防線 1【硬停損 (-5.0%)】**：跌破成本 -5.0% 無條件出清。")
        st.write("• **⏳ 防線 2【時間停損 (5個交易日)】**：持有滿 5 個開盤交易日漲幅未達 +1.0% 平手換股；若再次深蹲且在成本之上，允許展延至滿 7 天。")
        st.write("• **🛡️ 防線 3【動態保本 (+4.5%)】**：浮盈達 +4.5% 時，次日起停損推至成本價 (+0.2%)。")
        st.write("• **🎯 防線 4【階段一停利 (+8.0%)】**：觸及 +8.0% 出脫半倉鎖住利潤。")
        st.write("• **🏄 防線 5【階段二波段停利 (破 10MA)】**：剩餘半倉跌破 10MA 次日開盤全數出清。")
