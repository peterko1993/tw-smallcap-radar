import requests
import pandas as pd
import datetime
import yfinance as yf
import json
import os

REPORT_FILE = "radar_report.json"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def run_screener():
    print("🚀 [1/4] 正在抓取上市/上櫃市場三大法人籌碼日報...")
    today = datetime.date.today()
    trade_date = None
    df_inst = None

    for delta in range(7):
        target_date = today - datetime.timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
        try:
            res = requests.get(url_twse, headers=headers, timeout=10)
            data = res.json()
            if data.get("stat") == "OK" and "data" in data and len(data["data"]) > 0:
                trade_date = date_str
                df_twse = pd.DataFrame(data["data"], columns=data["fields"])
                df_twse = df_twse[df_twse['證券代號'].str.match(r'^\d{4}$')]
                trust_c = [c for c in df_twse.columns if "投信" in c and "買賣超" in c][0]
                tot_c = [c for c in df_twse.columns if "三大法人買賣超" in c][0]
                df_twse['投信買超'] = df_twse[trust_c].str.replace(',', '').astype(float) / 1000
                df_twse['法人買超'] = df_twse[tot_c].str.replace(',', '').astype(float) / 1000
                df_twse['市場'] = '.TW'
                df_inst = df_twse[['證券代號', '證券名稱', '投信買超', '法人買超', '市場']].copy()
                break
        except Exception:
            continue

    if df_inst is None:
        print("❌ 無法取得法人日報，終止執行。")
        return

    # 🎯 漏斗第一步：【第二道・籌碼密集度門檻】
    # 投信單日買超 >= 15 張，或三大法人合計買超 >= 80 張
    cond_chip = (df_inst['投信買超'] >= 15.0) | (df_inst['法人買超'] >= 80.0)
    df_step2 = df_inst[cond_chip].copy()

    # 🎯 漏斗第二步：【第一道・股本規模 (5億 ~ 20億)】
    print("📡 [2/4] 比對股本規模 (5億 ~ 20億) 並獲取產業分類...")
    stocks_cap = {}
    try:
        url_l = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        for row in requests.get(url_l, headers=headers, timeout=8).json():
            c = row.get("公司代號", "").strip()
            cap = float(row.get("實收資本額", 0)) / 100_000_000
            if c: stocks_cap[c] = {"cap": round(cap, 1), "ind": row.get("產業別", "上市科技")}
    except Exception: pass

    try:
        url_o = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        for row in requests.get(url_o, headers=headers, timeout=8).json():
            c = str(row.get("SecuritiesCompanyCode", "")).strip() or str(row.get("公司代號", "")).strip()
            cap = float(row.get("PaidInCapital", 0) or row.get("實收資本額", 0)) / 100_000_000
            if c: stocks_cap[c] = {"cap": round(cap, 1), "ind": row.get("SectorName", "上櫃科技")}
    except Exception: pass

    df_step2['股本(億)'] = df_step2['證券代號'].apply(lambda c: stocks_cap.get(c, {}).get("cap", 0.0))
    df_step2['產業別'] = df_step2['證券代號'].apply(lambda c: stocks_cap.get(c, {}).get("ind", "電子科技"))
    df_step1 = df_step2[(df_step2['股本(億)'] >= 5.0) & (df_step2['股本(億)'] <= 20.0)].copy()

    # 🎯 漏斗第四步：【第三道・營收爆發動能 (YoY >= 20%)】
    print("📡 [3/4] 比對單月營收爆發年增率 (YoY >= 20%)...")
    rev_dict = {}
    try:
        url_rev = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        for row in requests.get(url_rev, headers=headers, timeout=8).json():
            c = row.get("公司代號", "").strip()
            y_col = [k for k in row.keys() if "去年同月增減" in k]
            if y_col: rev_dict[c] = float(row.get(y_col[0], 0.0))
    except Exception: pass

    df_step1['營收YoY(%)'] = df_step1['證券代號'].apply(lambda c: rev_dict.get(c, 25.0))
    df_funnel = df_step1[df_step1['營收YoY(%)'] >= 20.0].copy()

    print(f"🎯 漏斗精選出 {len(df_funnel)} 檔小型動能標的，開始技術面深蹲與星級評估...")

    # 🎯 漏斗第三步：【第四道・技術面深蹲 ＋ MACD 核心動能 ＋ KD 星級加分】
    report_items = []
    total_squat_count = 0

    for _, row in df_funnel.iterrows():
        code = row['證券代號']
        name = row['證券名稱']
        ticker = f"{code}{row['市場']}"

        try:
            df_k = yf.download(ticker, period="4mo", interval="1d", progress=False)
            if df_k.empty or len(df_k) < 35: continue
            if isinstance(df_k.columns, pd.MultiIndex): df_k.columns = df_k.columns.get_level_values(0)

            # 1. 均線與均量
            df_k['MA5'] = df_k['Close'].rolling(5).mean()
            df_k['MA10'] = df_k['Close'].rolling(10).mean()
            df_k['MA20'] = df_k['Close'].rolling(20).mean()
            df_k['VOL_MA5'] = df_k['Volume'].rolling(5).mean()
            df_k['VOL_MA20'] = df_k['Volume'].rolling(20).mean()

            # 2. MACD (12, 26, 9)
            ema12 = df_k['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df_k['Close'].ewm(span=26, adjust=False).mean()
            df_k['DIF'] = ema12 - ema26
            df_k['MACD_SIG'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
            df_k['OSC'] = df_k['DIF'] - df_k['MACD_SIG']

            # 3. KD (9, 3, 3)
            low9 = df_k['Low'].rolling(9).min()
            high9 = df_k['High'].rolling(9).max()
            rsv = (df_k['Close'] - low9) / (high9 - low9 + 1e-9) * 100
            k_list, d_list = [50.0], [50.0]
            for r in rsv.fillna(50):
                new_k = (k_list[-1] * 2 / 3) + (r * 1 / 3)
                new_d = (d_list[-1] * 2 / 3) + (new_k * 1 / 3)
                k_list.append(new_k)
                d_list.append(new_d)
            df_k['K'] = k_list[1:]
            df_k['D'] = d_list[1:]

            latest = df_k.iloc[-1]
            prev = df_k.iloc[-2]
            close = float(latest['Close'])
            vol = float(latest['Volume'])
            low = float(latest['Low'])
            high = float(latest['High'])
            open_p = float(latest['Open'])
            ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
            vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])

            # 流動性底線：5 日均量 >= 500 張
            if vol_ma5 < 500 * 1000: continue

            # 基礎深蹲
            cond_trend = (ma5 > ma10) and (ma10 >= ma20) and (ma20 >= df_k['MA20'].iloc[-4])
            touch_5 = (low <= ma5 * 1.018 and close >= ma5 * 0.99)
            touch_10 = (low <= ma10 * 1.020 and close >= ma10 * 0.99)
            cond_support = touch_5 or touch_10
            cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
            cond_k = abs(close - open_p) / open_p <= 0.035
            base_squat = cond_trend and cond_support and cond_vol and cond_k

            # 💡 方案 A 核心動能：MACD 濾網 (DIF > 0 且 柱狀體翻紅或縮短)
            cond_macd = (latest['DIF'] > 0) and ((latest['OSC'] > prev['OSC']) or (latest['OSC'] > 0))

            is_squat = base_squat and cond_macd

            # 💡 方案 A 星級評定：KD 加分項 (30 <= K <= 65 且 轉折向上/金叉)
            cond_kd = (30.0 <= latest['K'] <= 65.0) and ((latest['K'] > prev['K']) or (latest['K'] >= latest['D']))

            if is_squat:
                total_squat_count += 1
                if cond_kd:
                    stars = 3
                    star_label = "🌟🌟🌟 3星・黃金狙擊 (MACD+KD)"
                    rank_score = 3
                else:
                    stars = 2
                    star_label = "🌟🌟 2星・強勢動能 (MACD)"
                    rank_score = 2
            else:
                stars = 0
                star_label = "未達標"
                rank_score = 0

            target_ma = ma5 if touch_5 else ma10
            support_name = "5MA" if touch_5 else ("10MA" if touch_10 else "無")
            cap_val = round(float(row['股本(億)']), 1)

            item_data = {
                "name": name, "code": code, "ticker": ticker,
                "industry": str(row.get('產業別', '電子科技')),
                "cap": cap_val, "cap_bracket": f"{cap_val}億 (小型爆發股)",
                "close": round(close, 1),
                "trust_buy": int(row['投信買超']),
                "inst_buy": int(row['法人買超']),
                "rev_yoy": round(float(row['營收YoY(%)']), 1),
                "is_squat": bool(is_squat),
                "stars": stars,
                "star_label": star_label,
                "rank_score": rank_score,
                "k_val": round(float(latest['K']), 1),
                "d_val": round(float(latest['D']), 1),
                "dif_val": round(float(latest['DIF']), 2),
                "support": support_name,
                "right_trigger": round(high, 1),
                "buy_min": round(target_ma, 1),
                "buy_max": round(close, 1),
                "stop_loss": round(target_ma * 0.95, 1),
                "take_profit": round(close * 1.08, 1),
                "scan_date": trade_date
            }
            report_items.append(item_data)
        except Exception:
            continue

    # 排序：3星優先，其次2星，同星級依法人買超張數排序
    report_items.sort(key=lambda x: (x['rank_score'], x['trust_buy'] + x['inst_buy']), reverse=True)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    report_data = {
        "update_time": now_str, "trade_date": trade_date,
        "total_funnel": len(df_funnel), "total_squat": total_squat_count,
        "stocks": report_items
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 戰報生成完畢！共發現 {total_squat_count} 檔星級動能獵物！")

if __name__ == "__main__":
    run_screener()
