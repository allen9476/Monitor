import requests
import pandas as pd
import time
import traceback
import os

# Telegram & Bark 設定（從環境變數讀取）
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
BARK_URL = os.environ.get("BARK_URL")

# 設定
SYMBOLS = ["FLOKIUSDT", "DOGEUSDT", "PNUTUSDT"]
COOL_DOWN_SECONDS = 300
last_signal_times = {symbol: 0 for symbol in SYMBOLS}  # 每個幣有獨立冷卻時間

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text}
        requests.post(url, data=data, timeout=10)
        print("✅ 已發送 Telegram 通知")
    except Exception as e:
        print("❌ Telegram 發送錯誤:", str(e))

def send_bark_message(text):
    try:
        requests.get(f"{BARK_URL}{text}", timeout=10)
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
        k = (2 / 3) * k_list[-1] + (1 / 3) * df.loc[i, 'rsv'] if i else 50
        d = (2 / 3) * d_list[-1] + (1 / 3) * k if i else 50
        k_list.append(k)
        d_list.append(d)
    df['k'], df['d'], df['j'] = k_list, d_list, 3 * pd.Series(k_list) - 2 * pd.Series(d_list)
    return df

def fetch_data(symbol, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data or len(data) < 10:
                raise ValueError("資料不足")
            return data
        except Exception as e:
            print(f"❌ 拉取 {symbol} 資料錯誤，第 {attempt+1}/5 次：{e}")
            time.sleep(5)
    raise Exception(f"{symbol} 無法取得數據")

def get_rsi_j(symbol, interval):
    data = fetch_data(symbol, interval)
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

def monitor(symbol):
    try:
        j, rsi, price = get_rsi_j(symbol, "15m")
        now_time = pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now_time}]｜{symbol}｜15m → J: {j:.2f}, RSI: {rsi:.2f}")
        if pd.notna(j) and pd.notna(rsi):
            trigger_signal = None
            if j < 3 and rsi < 30:
                trigger_signal = "↘️"
            elif j > 97 and rsi > 70:
                trigger_signal = "↗️"
            if trigger_signal:
                now = time.time()
                if now - last_signal_times[symbol] > COOL_DOWN_SECONDS:
                    msg = (
                        f"15m {trigger_signal} | {symbol}\n"
                        if symbol == "FLOKIUSDT":
                            f"現價: {price:.8f}\n" 
                        else: 
                            f"現價: {price:.4f}\n"
                        f"J: {j:.2f}, RSI: {rsi:.2f}"
                    )
                    send_telegram_message(msg)
                    send_bark_message(msg)
                    last_signal_times[symbol] = now
                else:
                    print(f"⏳ {symbol} 冷卻中，剩餘 {int(COOL_DOWN_SECONDS - (now - last_signal_times[symbol]))} 秒")
    except Exception as e:
        error_text = f"❌ {symbol} 發生錯誤：{str(e)}\n{traceback.format_exc()}"
        print(error_text)
        send_telegram_message(error_text)
        send_bark_message(error_text)

# 主迴圈
while True:
    for symbol in SYMBOLS:
        monitor(symbol)
        time.sleep(2)  # 各幣間稍微間隔一下避免 API 過載
    time.sleep(30)  # 整體監控頻率
