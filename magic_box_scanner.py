import requests
import os
from datetime import datetime, timedelta, timezone

# ============================================================
# تنظیمات
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# NY Timezone
NY_TZ = timezone(timedelta(hours=-4))  # EDT

# ============================================================
# توابع کمکی
# ============================================================
def to_ny_time(dt):
    """تبدیل به زمان نیویورک"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NY_TZ)

def is_in_asia_session(dt):
    """بررسی سشن آسیا (00:00 تا 09:00 NY)"""
    ny_dt = to_ny_time(dt)
    return 0 <= ny_dt.hour < 9

def is_in_mbox(dt):
    """بررسی MBOX (18:00 تا 02:00 NY)"""
    ny_dt = to_ny_time(dt)
    return ny_dt.hour >= 18 or ny_dt.hour < 2

def is_in_shred_time(dt):
    """بررسی SHRED time (02:00 تا 03:00 NY)"""
    ny_dt = to_ny_time(dt)
    return (ny_dt.hour == 2 or (ny_dt.hour == 3 and ny_dt.minute <= 5))

def is_scanning_time(dt):
    """بررسی زمان اسکن (02:00 تا 12:00 NY)"""
    ny_dt = to_ny_time(dt)
    return 2 <= ny_dt.hour < 12

# ============================================================
# دریافت داده
# ============================================================
def fetch_eurusd_data():
    """دریافت داده EURUSDT از Binance"""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": "EURUSDT",
            "interval": "15m",
            "limit": 200
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        candles = []
        for candle in data:
            candles.append({
                "time": datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5])
            })
        
        return candles
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

# ============================================================
# تحلیل تکنیکال
# ============================================================
def check_asia_range(candles):
    """بررسی رنج بودن سشن آسیا"""
    asia_candles = [c for c in candles if is_in_asia_session(c["time"])]
    
    if len(asia_candles) < 10:
        return False, None, None, None
    
    asia_high = max(c["high"] for c in asia_candles)
    asia_low = min(c["low"] for c in asia_candles)
    asia_close = asia_candles[-1]["close"]
    range_pct = ((asia_high - asia_low) / asia_close) * 100
    
    is_ranging = range_pct < 0.35
    return is_ranging, asia_high, asia_low, range_pct

def find_mbox_range(candles):
    """پیدا کردن بازه MBOX"""
    mbox_candles = [c for c in candles if is_in_mbox(c["time"])]
    
    if len(mbox_candles) < 10:
        return None
    
    mbox_high = max(c["high"] for c in mbox_candles)
    mbox_low = min(c["low"] for c in mbox_candles)
    
    return {
        "high": mbox_high,
        "low": mbox_low,
        "mid": (mbox_high + mbox_low) / 2,
        "range": mbox_high - mbox_low
    }

def detect_choch(candles, lookback=20):
    """تشخیص CHOCH"""
    choch_events = []
    
    for i in range(lookback, len(candles)):
        current = candles[i]
        prev_highs = [c["high"] for c in candles[i-lookback:i]]
        prev_lows = [c["low"] for c in candles[i-lookback:i]]
        
        if current["close"] > max(prev_highs):
            choch_events.append({
                "type": "bullish",
                "price": current["close"],
                "time": current["time"]
            })
        
        if current["close"] < min(prev_lows):
            choch_events.append({
                "type": "bearish",
                "price": current["close"],
                "time": current["time"]
            })
    
    return choch_events

def detect_order_blocks(candles, choch_events, lookback=10):
    """تشخیص Order Blocks"""
    order_blocks = []
    
    for choch in choch_events:
        choch_idx = next((i for i, c in enumerate(candles) if c["time"] == choch["time"]), None)
        
        if choch_idx is None or choch_idx < lookback:
            continue
        
        if choch["type"] == "bullish":
            for j in range(choch_idx - 1, max(choch_idx - lookback, 0), -1):
                candle = candles[j]
                if candle["close"] < candle["open"]:
                    order_blocks.append({
                        "type": "bullish",
                        "top": candle["open"],
                        "bottom": candle["low"]
                    })
                    break
        
        elif choch["type"] == "bearish":
            for j in range(choch_idx - 1, max(choch_idx - lookback, 0), -1):
                candle = candles[j]
                if candle["close"] > candle["open"]:
                    order_blocks.append({
                        "type": "bearish",
                        "top": candle["high"],
                        "bottom": candle["close"]
                    })
                    break
    
    return order_blocks

# ============================================================
# بررسی ستاپ
# ============================================================
def check_magic_box_setup(candles):
    """بررسی کامل ستاپ Magic Box"""
    details = {}
    signals = []
    
    is_ranging, asia_high, asia_low, range_pct = check_asia_range(candles)
    details["asia_ranging"] = is_ranging
    details["asia_range_pct"] = range_pct
    
    if not is_ranging:
        return None, details
    
    mbox = find_mbox_range(candles)
    if not mbox:
        return None, details
    details["mbox"] = mbox
    
    choch_events = detect_choch(candles, lookback=30)
    if not choch_events:
        return None, details
    
    order_blocks = detect_order_blocks(candles, choch_events, lookback=10)
    if not order_blocks:
        return None, details
    
    current_price = candles[-1]["close"]
    current_time = candles[-1]["time"]
    
    for ob in order_blocks:
        if ob["bottom"] <= current_price <= ob["top"]:
            if is_in_shred_time(current_time):
                direction = "LONG" if ob["type"] == "bullish" else "SHORT"
                signals.append({
                    "direction": direction,
                    "entry": current_price,
                    "stop_loss": ob["bottom"] - mbox["range"] * 0.1 if ob["type"] == "bullish" else ob["top"] + mbox["range"] * 0.1,
                    "take_profit": mbox["high"] if ob["type"] == "bullish" else mbox["low"],
                    "reason": f"{ob['type'].capitalize()} OB retest in SHRED time"
                })
    
    if signals:
        return signals, details
    return None, details

# ============================================================
# ارسال پیام تلگرام
# ============================================================
def send_telegram_message(message):
    """ارسال پیام به تلگرام"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram credentials not set")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Message sent to Telegram")
        else:
            print(f"Telegram API error: {response.text}")
    except Exception as e:
        print(f"Error sending message: {e}")

def format_signal_message(signal, details):
    """فرمت پیام سیگنال"""
    emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
    
    return f"""
{emoji} <b>Magic Box Signal - EURUSD</b> {emoji}

📊 <b>Direction:</b> {signal["direction"]}
💰 <b>Entry:</b> {signal["entry"]:.5f}
🛑 <b>Stop Loss:</b> {signal["stop_loss"]:.5f}
 <b>Take Profit:</b> {signal["take_profit"]:.5f}

 <b>Setup Details:</b>
• Asia Range: {details.get('asia_range_pct', 0):.3f}%
• MBOX High: {details['mbox']['high']:.5f}
• MBOX Low: {details['mbox']['low']:.5f}

📝 <b>Reason:</b> {signal["reason"]}

⏰ <b>Time:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

# ============================================================
# تابع اصلی
# ============================================================
def main():
    """تابع اصلی"""
    print("Starting Magic Box Scanner...")
    
    candles = fetch_eurusd_data()
    if not candles:
        print("❌ Error: Could not fetch data")
        return
    
    current_time = candles[-1]["time"]
    print(f"Current NY time: {to_ny_time(current_time)}")
    
    if not is_scanning_time(current_time):
        print("⏰ Not in scanning time (02:00-12:00 NY)")
        return
    
    print("🔍 Checking for Magic Box setup...")
    signals, details = check_magic_box_setup(candles)
    
    if signals:
        for signal in signals:
            message = format_signal_message(signal, details)
            send_telegram_message(message)
            print(f"✅ Signal sent: {signal['direction']}")
    else:
        print("❌ No signal found")

if __name__ == "__main__":
    main()
