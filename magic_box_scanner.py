import requests
import os
from datetime import datetime, timedelta, timezone

# ============================================================
# تنظیمات
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

NY_TZ = timezone(timedelta(hours=-4))

# ============================================================
# توابع کمکی
# ============================================================
def to_ny_time(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NY_TZ)

def is_in_asia_session(dt):
    ny_dt = to_ny_time(dt)
    return 0 <= ny_dt.hour < 9

def is_in_mbox(dt):
    ny_dt = to_ny_time(dt)
    return ny_dt.hour >= 18 or ny_dt.hour < 2

def is_in_shred_time(dt):
    ny_dt = to_ny_time(dt)
    return (ny_dt.hour == 2 or (ny_dt.hour == 3 and ny_dt.minute <= 5))

def is_scanning_time(dt):
    ny_dt = to_ny_time(dt)
    return 2 <= ny_dt.hour < 12

# ============================================================
# دریافت داده از Yahoo Finance
# ============================================================
def fetch_eurusd_data():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        params = {
            "range": "2d",
            "interval": "15m",
            "includePrePost": "false"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        print("📡 Fetching data from Yahoo Finance...")
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ HTTP Error: {response.status_code}")
            return None
        
        data = response.json()
        
        if "chart" not in data or "result" not in data["chart"]:
            print(f"❌ Invalid response structure")
            return None
        
        result = data["chart"]["result"]
        if not result:
            print("❌ Empty result")
            return None
        
        chart_data = result[0]
        timestamps = chart_data.get("timestamp", [])
        indicators = chart_data.get("indicators", {})
        quote = indicators.get("quote", [{}])[0]
        
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        
        print(f"✅ Received {len(timestamps)} candles from Yahoo")
        
        candles = []
        for i in range(len(timestamps)):
            try:
                if opens[i] is None or highs[i] is None or lows[i] is None or closes[i] is None:
                    continue
                
                candle_time = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)
                
                candles.append({
                    "time": candle_time,
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": 0
                })
            except (ValueError, TypeError, IndexError) as e:
                continue
        
        print(f"✅ Processed {len(candles)} valid candles")
        
        if len(candles) < 10:
            print(f"❌ Not enough candles ({len(candles)} < 10)")
            return None
        
        return candles
        
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return None

# ============================================================
# تحلیل تکنیکال
# ============================================================
def check_asia_range(candles):
    asia_candles = [c for c in candles if is_in_asia_session(c["time"])]
    
    if len(asia_candles) < 10:
        return False, None, None, None
    
    asia_high = max(c["high"] for c in asia_candles)
    asia_low = min(c["low"] for c in asia_candles)
    asia_close = asia_candles[-1]["close"]
    range_pct = ((asia_high - asia_low) / asia_close) * 100
    
    is_ranging = range_pct < 0.35
    print(f"🌏 Asia Range: {range_pct:.3f}% - {'Ranging ✅' if is_ranging else 'Trending ❌'}")
    return is_ranging, asia_high, asia_low, range_pct

def find_mbox_range(candles):
    mbox_candles = [c for c in candles if is_in_mbox(c["time"])]
    
    if len(mbox_candles) < 10:
        return None
    
    mbox_high = max(c["high"] for c in mbox_candles)
    mbox_low = min(c["low"] for c in mbox_candles)
    
    print(f"📦 MBOX: {mbox_low:.5f} - {mbox_high:.5f}")
    return {
        "high": mbox_high,
        "low": mbox_low,
        "mid": (mbox_high + mbox_low) / 2,
        "range": mbox_high - mbox_low
    }

def detect_choch(candles, lookback=20):
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
    print("\n🔍 Checking Magic Box setup...")
    details = {}
    signals = []
    
    is_ranging, asia_high, asia_low, range_pct = check_asia_range(candles)
    details["asia_ranging"] = is_ranging
    details["asia_range_pct"] = range_pct
    
    if not is_ranging:
        print("❌ Asia is not ranging")
        return None, details
    
    mbox = find_mbox_range(candles)
    if not mbox:
        print("❌ MBOX not found")
        return None, details
    details["mbox"] = mbox
    
    choch_events = detect_choch(candles, lookback=30)
    if not choch_events:
        print("❌ No CHOCH detected")
        return None, details
    
    order_blocks = detect_order_blocks(candles, choch_events, lookback=10)
    if not order_blocks:
        print("❌ No Order Blocks detected")
        return None, details
    
    current_price = candles[-1]["close"]
    current_time = candles[-1]["time"]
    
    print(f"\n💰 Current price: {current_price:.5f}")
    print(f"⏰ Current NY time: {to_ny_time(current_time)}")
    
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
                print(f"✅ SIGNAL FOUND: {direction}")
    
    if not signals:
        print("❌ No signals found")
    
    if signals:
        return signals, details
    return None, details

# ============================================================
# ارسال پیام تلگرام
# ============================================================
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Error: Telegram credentials not set")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        print("📤 Sending message to Telegram...")
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Message sent successfully!")
            return True
        else:
            print(f"❌ Telegram API error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False

def format_signal_message(signal, details):
    emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
    
    return f"""
{emoji} <b>Magic Box Signal - EURUSD</b> {emoji}

📊 <b>Direction:</b> {signal["direction"]}
💰 <b>Entry:</b> {signal["entry"]:.5f}
🛑 <b>Stop Loss:</b> {signal["stop_loss"]:.5f}
🎯 <b>Take Profit:</b> {signal["take_profit"]:.5f}

📋 <b>Setup Details:</b>
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
    print("=" * 50)
    print("🚀 Starting Magic Box Scanner...")
    print("=" * 50)
    
    candles = fetch_eurusd_data()
    if not candles:
        print("❌ Error: Could not fetch data")
        return
    
    current_time = candles[-1]["time"]
    ny_time = to_ny_time(current_time)
    print(f"\n🕒 Current NY time: {ny_time}")
    print(f"📊 Scanning hours: 02:00 - 12:00 NY")
    
    if not is_scanning_time(current_time):
        print(f"⏰ Not in scanning time (current hour: {ny_time.hour})")
        return
    
    print("\n✅ In scanning time - proceeding...")
    signals, details = check_magic_box_setup(candles)
    
    if signals:
        print(f"\n🎯 {len(signals)} signal(s) found!")
        for signal in signals:
            message = format_signal_message(signal, details)
            if send_telegram_message(message):
                print(f"✅ Signal sent: {signal['direction']}")
    else:
        print("\n❌ No signals found - no message sent")

if __name__ == "__main__":
    main()
