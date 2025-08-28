import asyncio
from binance.client import Client
from binance.exceptions import BinanceAPIException
from datetime import datetime
import requests

# ------------------ متغيرات أساسية ------------------
BINANCE_API_KEY ="owuqpU1wGlghV8EyKufEtJ8mW3cbzo5PYc8yjTlN5yO0JQF2uTEeXnYd6Uddb81H"
BINANCE_API_SECRET = "Hv4auIvVV1HmfaDdpgPiSTMcJbafTrkO8xnd5dP3yqCiFkNEpfhZGCVjcN3SVKC8"
TELEGRAM_TOKEN = "7434367964:AAFzyoLKKAW3tYzQI4c8Uvlp1ypxhgYasfE"
TELEGRAM_CHAT_ID = "5427885291"

TRADE_AMOUNT = 5        # المبلغ الابتدائي لكل صفقة
PROFIT_THRESHOLD = 1.0   # الربح المستهدف لتعديل المبلغ
STOP_LOSS_THRESHOLD = -0.5 # الحد الأقصى للخسارة لكل صفقة
INCREASE_FACTOR = 1.2    # نسبة زيادة المبلغ بعد الربح
REQUEST_DELAY = 1        # تأخير بين الصفقات بالثواني

last_trade_amount = TRADE_AMOUNT
trading_active = True

# ------------------ دوال مساعدة ------------------
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print(f"Telegram Error: {e}")

def adjust_trade_amount(pnl: float) -> float:
    global last_trade_amount
    if pnl >= PROFIT_THRESHOLD:
        last_trade_amount *= INCREASE_FACTOR
    elif pnl < 0:
        last_trade_amount = TRADE_AMOUNT
    return last_trade_amount

# ------------------ إعداد Binance Client ------------------
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def get_all_pairs():
    try:
        info = client.get_exchange_info()
        pairs = [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING']
        return pairs
    except Exception as e:
        send_telegram(f"⚠️ خطأ في جلب أزواج التداول: {e}")
        return []

# ------------------ متابعة الصفقات ------------------
async def monitor_positions():
    while trading_active:
        try:
            positions = client.futures_account()['positions']
            for pos in positions:
                qty = float(pos['positionAmt'])
                if qty != 0:
                    pnl = float(pos['unrealizedProfit'])
                    side = "LONG" if qty > 0 else "SHORT"
                    send_telegram(f"💹 {pos['symbol']} | {side} | Qty: {qty} | Entry: {pos['entryPrice']} | PnL: {pnl:.2f} | Opened: {datetime.now().strftime('%H:%M:%S')}")
                    # إدارة المخاطر: إغلاق الصفقة إذا وصلت للخسارة
                    if pnl <= STOP_LOSS_THRESHOLD:
                        close_trade(pos)
                    adjust_trade_amount(pnl)
            await asyncio.sleep(5)
        except Exception as e:
            send_telegram(f"⚠️ خطأ في متابعة الصفقات: {e}")
            await asyncio.sleep(5)

# ------------------ تنفيذ وغلق الصفقة ------------------
def place_trade(symbol: str, qty: float):
    try:
        order = client.order_market_buy(symbol=symbol, quantity=qty)
        send_telegram(f"✅ تم فتح صفقة: {symbol} | Qty: {qty} | {datetime.now().strftime('%H:%M:%S')}")
        return order
    except BinanceAPIException as e:
        send_telegram(f"⚠️ خطأ في فتح الصفقة: {symbol} - {e}")
    except Exception as e:
        send_telegram(f"⚠️ خطأ عام: {e}")

def close_trade(pos):
    qty = abs(float(pos['positionAmt']))
    side = 'SELL' if float(pos['positionAmt']) > 0 else 'BUY'
    try:
        client.futures_create_order(symbol=pos['symbol'], side=side, type='MARKET', quantity=qty)
        send_telegram(f"⚠️ تم إغلاق الصفقة لتجنب الخسارة: {pos['symbol']} | Qty: {qty}")
    except Exception as e:
        send_telegram(f"⚠️ خطأ عند غلق الصفقة: {pos['symbol']} - {e}")

# ------------------ تشغيل التداول ------------------
async def main():
    global trading_active
    pairs = get_all_pairs()
    if not pairs:
        send_telegram("⚠️ لم يتم العثور على أزواج للتداول.")
        return

    send_telegram("🚀 بدأ تشغيل البوت")
    asyncio.create_task(monitor_positions())

    while trading_active:
        for pair in pairs:
            qty = last_trade_amount
            place_trade(pair, qty)
            await asyncio.sleep(REQUEST_DELAY)

# ------------------ إيقاف ذكي للتداول ------------------
def stop_trading():
    global trading_active
    trading_active = False
    send_telegram("🛑 تم تفعيل إيقاف التداول. جارٍ غلق كل الصفقات المفتوحة...")
    positions = client.futures_account()['positions']
    for pos in positions:
        if float(pos['positionAmt']) != 0:
            close_trade(pos)

# ------------------ نقطة البداية ------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        stop_trading()
        send_telegram("🛑 تم إيقاف البوت يدويًا.")