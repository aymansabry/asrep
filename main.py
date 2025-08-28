import asyncio
import logging
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException
import requests

# -------------------------
# متغيرات API وTelegram
# -------------------------
BINANCE_API_KEY = "owuqpU1wGlghV8EyKufEtJ8mW3cbzo5PYc8yjTlN5yO0JQF2uTEeXnYd6Uddb81Hا"
BINANCE_API_SECRET = "Hv4auIvVV1HmfaDdpgPiSTMcJbafTrkO8xnd5dP3yqCiFkNEpfhZGCVjcN3SVKC8"
TELEGRAM_BOT_TOKEN = "7434367964:AAHRenO8wkjN0UOY8lIRJSiD8OJ1hLgroRw"
TELEGRAM_CHAT_ID = "5427885291"

# -------------------------
# إعدادات البوت
# -------------------------
TRADE_AMOUNT = 5  # قيمة الاستثمار بالدولار لكل صفقة
USE_FUTURES = True  # تفعيل التداول بالرافعة
FUTURE_LEVERAGE = 10  # رافعة Futures
MAX_OPEN_TRADES = None  # لا يوجد حد للصفقات المفتوحة
STOP_TRADING = False  # لإيقاف التداول الذكي
LOG_FILE = "bot.log"

# -------------------------
# إعدادات اللوج
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)

# -------------------------
# دوال مساعدة
# -------------------------
def telegram_send(message: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message}
        )
    except Exception as e:
        logging.error(f"فشل إرسال رسالة Telegram: {e}")

def format_trade_msg(symbol, quantity, entry_price, current_price, leverage, open_time):
    pnl_percent = ((current_price - entry_price) / entry_price) * 100
    return (
        f"📊 صفقة مفتوحة على {symbol}\n"
        f"⏱ وقت الفتح: {open_time}\n"
        f"💰 كمية: {quantity}\n"
        f"💵 سعر الدخول: {entry_price}\n"
        f"📈 السعر الحالي: {current_price}\n"
        f"⚖️ رافعة: {leverage}x\n"
        f"📊 الربح/الخسارة: {pnl_percent:.2f}%"
    )

# -------------------------
# إعداد Binance
# -------------------------
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# -------------------------
# جلب جميع أزواج التداول المتاحة
# -------------------------
def get_all_pairs():
    info = client.get_exchange_info()
    symbols = [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING']
    return symbols

# -------------------------
# متابعة الصفقات المفتوحة
# -------------------------
OPEN_TRADES = []

async def monitor_trades():
    while True:
        for trade in OPEN_TRADES:
            try:
                symbol = trade['symbol']
                entry_price = trade['entry_price']
                quantity = trade['quantity']
                leverage = trade['leverage']
                open_time = trade['open_time']

                current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])
                msg = format_trade_msg(symbol, quantity, entry_price, current_price, leverage, open_time)
                logging.info(msg)
            except Exception as e:
                logging.error(f"خطأ متابعة صفقة {symbol}: {e}")
        await asyncio.sleep(10)

# -------------------------
# فتح صفقة
# -------------------------
async def place_trade(symbol, amount_usdt):
    global OPEN_TRADES, STOP_TRADING
    if STOP_TRADING:
        logging.info(f"⏹ تم إيقاف التداول، لن يتم فتح صفقة جديدة على {symbol}")
        return

    try:
        price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        quantity = round(amount_usdt / price, 6)

        info = client.get_symbol_info(symbol)
        min_qty = float(next(f['minQty'] for f in info['filters'] if f['filterType'] == 'LOT_SIZE'))
        if quantity < min_qty:
            msg = f"⚠️ لا يمكن التداول على {symbol}: الكمية {quantity} أقل من الحد الأدنى {min_qty}"
            logging.warning(msg)
            telegram_send(msg)
            return

        order = client.order_market_buy(symbol=symbol, quantity=quantity)
        open_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        leverage = 1
        if USE_FUTURES:
            leverage = FUTURE_LEVERAGE

        trade_info = {
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': price,
            'open_time': open_time,
            'leverage': leverage
        }
        OPEN_TRADES.append(trade_info)

        msg = format_trade_msg(symbol, quantity, price, price, leverage, open_time)
        logging.info(msg)
        telegram_send(msg)
        return order
    except BinanceAPIException as e:
        logging.error(f"❌ فشل تنفيذ الصفقة على {symbol}: {e}")
        telegram_send(f"❌ فشل تنفيذ الصفقة على {symbol}: {e}")
    except Exception as e:
        logging.error(f"خطأ غير متوقع على {symbol}: {e}")
        telegram_send(f"خطأ غير متوقع على {symbol}: {e}")

# -------------------------
# إيقاف التداول الذكي
# -------------------------
async def stop_trading_bot():
    global STOP_TRADING, OPEN_TRADES
    STOP_TRADING = True
    telegram_send("⏹ تم تفعيل إيقاف التداول، جاري غلق جميع الصفقات المفتوحة...")

    for trade in OPEN_TRADES:
        try:
            symbol = trade['symbol']
            quantity = trade['quantity']
            client.order_market_sell(symbol=symbol, quantity=quantity)
            logging.info(f"✅ تم غلق الصفقة المفتوحة على {symbol}")
            telegram_send(f"✅ تم غلق الصفقة المفتوحة على {symbol}")
        except Exception as e:
            logging.error(f"❌ خطأ عند غلق الصفقة على {symbol}: {e}")
            telegram_send(f"❌ خطأ عند غلق الصفقة على {symbol}: {e}")

    OPEN_TRADES = []
    telegram_send("⏹ تم إيقاف التداول نهائيًا بعد غلق جميع الصفقات.")

# -------------------------
# تشغيل البوت
# -------------------------
async def main():
    pairs = get_all_pairs()
    logging.info(f"عدد أزواج التداول المتاحة: {len(pairs)}")

    for pair in pairs:
        await place_trade(pair, TRADE_AMOUNT)
        await asyncio.sleep(1)

    # متابعة الصفقات
    await monitor_trades()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        asyncio.run(stop_trading_bot())
    except Exception as e:
        logging.error(f"خطأ غير متوقع في البوت: {e}")
        telegram_send(f"خطأ غير متوقع في البوت: {e}")
