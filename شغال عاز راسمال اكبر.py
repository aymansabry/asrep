import os
import sys
import math
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

nest_asyncio.apply()
sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 5))  # مبلغ الاستثمار لكل صفقة
LEVERAGE = int(os.getenv("LEVERAGE", 3))

if not all([TELEGRAM_TOKEN, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
    raise ValueError("❌ يجب تعريف TELEGRAM_BOT_TOKEN, BINANCE_API_KEY, BINANCE_SECRET_KEY في ملف .env")

client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# دالة لجلب الرصيد الحالي (للمتابعة فقط)
def get_balance():
    balances = client.futures_account_balance()
    for b in balances:
        if b['asset'] == 'USDT':
            return float(b['balance'])
    return 0.0

# دالة لتحديد كل الأزواج الصالحة للتداول بمبلغ TRADE_AMOUNT
def get_valid_pairs():
    info = client.futures_exchange_info()
    symbols = [s for s in info['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

    valid_pairs = []
    failed_pairs = []

    for s in symbols:
        symbol = s['symbol']
        price = float(client.futures_symbol_ticker(symbol=symbol)['price'])

        # الحصول على الحد الأدنى للكمية و stepSize
        lot_filter = next(f for f in s['filters'] if f['filterType'] == 'LOT_SIZE')
        min_qty = float(lot_filter['minQty'])
        step_size = float(lot_filter['stepSize'])

        # حساب الكمية الممكن تنفيذها بالمبلغ المحدد
        quantity = TRADE_AMOUNT * LEVERAGE / price
        quantity = math.floor(quantity / step_size) * step_size

        if quantity < min_qty:
            failed_pairs.append({
                'symbol': symbol,
                'price': price,
                'quantity': quantity,
                'min_qty': min_qty
            })
        else:
            valid_pairs.append({
                'symbol': symbol,
                'price': price,
                'quantity': quantity
            })

    return valid_pairs, failed_pairs

# دالة لتنفيذ الصفقة على زوج محدد
def place_trade(pair):
    symbol = pair['symbol']
    quantity = pair['quantity']
    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
    except BinanceAPIException as e:
        return f"❌ خطأ في تغيير الرفع المالي: {e}"

    try:
        order = client.futures_create_order(
            symbol=symbol,
            side='BUY',
            type='MARKET',
            quantity=quantity
        )
        return f"✅ تم تنفيذ الصفقة على {symbol} بكمية {quantity} USDT"
    except BinanceAPIException as e:
        if e.code == -2019:
            return f"❌ الرصيد غير كافي لتنفيذ المبلغ المحدد للتداول ({TRADE_AMOUNT} USDT)"
        return f"❌ فشل تنفيذ الصفقة: {e}"

# دالة /trade
async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balance = get_balance()
    await update.message.reply_text(f"💰 الرصيد الحالي: {balance} USDT\n🔹 مبلغ الاستثمار لكل صفقة: {TRADE_AMOUNT} USDT")

    valid_pairs, failed_pairs = get_valid_pairs()

    # عرض الأزواج الفاشلة مع سبب الفشل
    if failed_pairs:
        msg = "⚠️ بعض الأزواج لم يتم التداول عليها بسبب مشاكل الكمية:\n"
        for f in failed_pairs:
            msg += (f"{f['symbol']}: السعر={f['price']}, الكمية المحسوبة={f['quantity']}, الحد الأدنى={f['min_qty']}\n")
        await update.message.reply_text(msg)

    if not valid_pairs:
        await update.message.reply_text("❌ لم يتم العثور على أي زوج صالح للتداول بالمبلغ المحدد.")
        return

    # اختيار أفضل زوج للتداول (أول زوج صالح حاليا)
    pair = valid_pairs[0]
    await update.message.reply_text(f"✅ تنفيذ الصفقة على {pair['symbol']}...")
    result = place_trade(pair)
    await update.message.reply_text(result)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! استخدم /trade لتنفيذ صفقة.")

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trade", trade))

    print("✅ البوت جاهز للتداول.")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
