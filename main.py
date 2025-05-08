import requests
import pandas as pd
import time
import traceback
import os

# Telegram 設定（從環境變數讀取）
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
BARK_URL = os.environ.get("BARK_URL")

SYMBOL = "TRUMPUSDT"
COOL_DOWN_SECONDS = 300
last_signal_time = 0

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
        print("✅ 已發送 Telegram 通知")
    except Exception as e:
        print("❌ Telegram 發送錯誤:", str(e))

def send_bark_message(text):
    try:
        bark_url = f"{BARK_URL}{text}"
        requests.get(bark_url, timeout=10)
        print("✅ 已發送 Bark 通知")
    except Exception as e:
        print("❌ Bark 發送錯誤:", str(e))

def calculate_kdj(df, n=9):
    df = df.copy()
    low_min = df['l'].rolling(window=n, min_periods=1).min()
    high_max = df['h'].rolling(window=n, min_periods=1).max()
    df['rsv'] = (df['c'] - low_min) / (high_max - low_min) * 100
    k_list, d_list = [], []
    for i in range(len(df)):
        if i == 0:
            k = 50
            d = 50
        else:
            k = (2 / 3) * k_list[-1] + (1 / 3) * df.loc[i, 'rsv']
            d = (2 / 3) * d_list[-1] + (1 / 3) * k
        k_list.append(k)
        d_list.append(d)
    df['k'] = k_list
    df['d'] = d_list
    df['j'] = 3 * df['k'] - 2 * df['d']
    return df

def fetch_data(instId, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={instId}&interval={interval}&limit=200"
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data or len(data) < 10:
                raise ValueError("資料不足")
            return data
        except Exception as e:
            print(f"❌ 拉取資料錯誤，第 {attempt+1}/5 次：{e}")
            time.sleep(5)
    raise Exception("無法取得數據")

def get_rsi_j(instId, interval):
    data = fetch_data(instId, interval)
    df = pd.DataFrame(data)[[0, 1, 2, 3, 4, 5]]
    df.columns = ["ts", "o", "h", "l", "c", "vol"]
    df = df[df["vol"].astype(float) > 0].reset_index(drop=True)
    df[["o", "h", "l", "c"]] = df[["o", "h", "l", "c"]].astype(float)
    df = calculate_kdj(df, n=9)
    delta = df['c'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=6, adjust=False).mean()
    avg_loss = loss.ewm(span=6, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))
    latest = df.iloc[-1]
    return latest["j"], latest["rsi"], latest["c"]

def monitor():
    global last_signal_time
    try:
        j_5m, rsi_5m, price_5m = get_rsi_j(SYMBOL, "5m")
        j_15m, rsi_15m, price_15m = get_rsi_j(SYMBOL, "15m")
        now_time = pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now_time}] 5m→J: {j_5m:.2f}, RSI: {rsi_5m:.2f}｜15m→J: {j_15m:.2f}, RSI: {rsi_15m:.2f}")
        if all(pd.notna(x) for x in [j_5m, rsi_5m, j_15m, rsi_15m]):
            trigger_signal = None
            trigger_from = ""
            if (j_5m < 5 and rsi_5m < 30):
                trigger_signal = "📉 超賣訊號"
                trigger_from = "5m"
            elif (j_15m < 5 and rsi_15m < 30):
                trigger_signal = "📉 超賣訊號"
                trigger_from = "15m"
            elif (j_5m > 95 and rsi_5m > 70):
                trigger_signal = "📈 超買訊號"
                trigger_from = "5m"
            elif (j_15m > 95 and rsi_15m > 70):
                trigger_signal = "📈 超買訊號"
                trigger_from = "15m"
            if trigger_signal:
                now = time.time()
                if now - last_signal_time > COOL_DOWN_SECONDS:
                    msg = (
                        f"{trigger_signal} | {trigger_from} 觸發 | {SYMBOL}\n"
                        f"J(5m): {j_5m:.2f}, RSI(5m): {rsi_5m:.2f}\n"
                        f"J(15m): {j_15m:.2f}, RSI(15m): {rsi_15m:.2f}\n"
                        f"5m現價: {price_5m:.4f}"
                    )
                    send_telegram_message(msg)
                    send_bark_message(msg)
                    last_signal_time = now
                else:
                    print(f"⏳ 冷卻中，剩餘 {int(COOL_DOWN_SECONDS - (now - last_signal_time))} 秒")
    except Exception as e:
        error_text = f"❌ 發生錯誤：{str(e)}\n{traceback.format_exc()}"
        print(error_text)
        send_telegram_message(error_text)
        send_bark_message(error_text)

while True:
    monitor()
    time.sleep(30)
