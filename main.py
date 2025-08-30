# bot_final_dynamic_v2.py
import os
import json
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ====== إعداد البيئة ======
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

REQUIRED = {
    "BINANCE_API_KEY": BINANCE_API_KEY,
    "BINANCE_API_SECRET": BINANCE_API_SECRET,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID
}
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

# ====== إعدادات افتراضية ======
BASE_INVESTMENT_POOL = 3.0
DEFAULT_MAX_CONCURRENT_TRADES = 3
DEFAULT_TRADE_DURATION_MINUTES = 15
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
BLACKLISTED = []

TRADING_STRATEGIES = ['trend_following', 'mean_reversion', 'breakout', 'volume_spike']

logging.basicConfig(filename="log.txt", level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

state = {
    "investment_pool_total": BASE_INVESTMENT_POOL,
    "investment_pool_available": BASE_INVESTMENT_POOL,
    "open_trades": [],
    "eligible_pairs": [],
    "valid_symbols_master": [],
    "stop_trading": False,
}
state_lock = asyncio.Lock()

# ====== Binance client ======
try:
    from binance.client import Client
    bclient = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
except Exception as e:
    logging.error("Binance client init failed: %s", e)
    bclient = None

# ====== وظائف Telegram ======
async def send_telegram_text(text: str, pin: bool = False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = await asyncio.to_thread(requests.post, url, data=payload, timeout=10)
        data = resp.json() if resp else {}
        if pin and data.get("ok"):
            try:
                msg_id = data["result"]["message_id"]
                pin_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/pinChatMessage"
                await asyncio.to_thread(requests.post, pin_url, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": msg_id})
            except Exception as e:
                logging.error("Pin failed: %s", e)
        return data
    except Exception as e:
        logging.error("Telegram send failed: %s", e)
        return {}

# ====== Binance مساعدة ======
def load_master_symbols():
    try:
        info = bclient.futures_exchange_info()
        symbols = [s['symbol'] for s in info['symbols']]
        state['valid_symbols_master'] = symbols
        logging.info("Loaded master symbols count=%d", len(symbols))
    except Exception as e:
        logging.error("Failed load master symbols: %s", e)

def get_symbol_price(symbol: str) -> Optional[float]:
    try:
        t = bclient.futures_symbol_ticker(symbol=symbol)
        return float(t['price'])
    except:
        return None

# ====== صفقات مفتوحة ======
OPEN_TRADES_FILE = "open_trades.json"

def save_open_trades():
    try:
        serializable = []
        for t in state['open_trades']:
            copy = t.copy()
            copy['open_time'] = t['open_time'].isoformat()
            copy['close_time'] = t['close_time'].isoformat()
            serializable.append(copy)
        with open(OPEN_TRADES_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Failed save open trades: %s", e)

def load_open_trades():
    try:
        if os.path.exists(OPEN_TRADES_FILE):
            with open(OPEN_TRADES_FILE, "r", encoding="utf-8") as f:
                trades = json.load(f)
                for t in trades:
                    t['open_time'] = datetime.fromisoformat(t['open_time'])
                    t['close_time'] = datetime.fromisoformat(t['close_time'])
                state['open_trades'] = trades
    except Exception as e:
        logging.error("Failed load open trades: %s", e)

# ====== بناء الأزواج المؤهلة ======
def build_eligible_pairs(min_trade_amount: float = 5.0) -> List[str]:
    prices = {}
    eligible = []
    for sym in state['valid_symbols_master']:
        if sym.endswith("USDT") and sym not in BLACKLISTED:
            price = get_symbol_price(sym)
            if price and price > 0:
                qty = min_trade_amount / price
                if qty > 0:
                    eligible.append(sym)
    state['eligible_pairs'] = eligible
    return eligible

# ====== فتح صفقة ======
async def open_trade(symbol: str, amount_usdt: float, strategy: str):
    cur_price = get_symbol_price(symbol)
    if not cur_price:
        return
    now = datetime.now()
    close_time = now + timedelta(minutes=DEFAULT_TRADE_DURATION_MINUTES)
    trade = {
        "symbol": symbol,
        "amount_usdt": amount_usdt,
        "strategy": strategy,
        "entry_price": cur_price,
        "open_time": now,
        "close_time": close_time,
        "status": "open",
        "dry_run": DRY_RUN
    }
    async with state_lock:
        state['open_trades'].append(trade)
        state['investment_pool_available'] -= amount_usdt
        save_open_trades()
    msg = f"<b>🚀 فتح صفقة {symbol}</b>\nالسعر: {cur_price:.2f}\nالاستراتيجية: {strategy}\nالاستثمار: {amount_usdt} USDT"
    await send_telegram_text(msg)

# ====== مراقبة الصفقات ======
async def monitor_trades_loop():
    while not state['stop_trading']:
        now = datetime.now()
        async with state_lock:
            for trade in state['open_trades']:
                if trade['status'] != "open":
                    continue
                exit_price = get_symbol_price(trade['symbol']) or trade['entry_price']
                if now >= trade['close_time']:
                    trade['status'] = "closed"
                    profit = (exit_price - trade['entry_price']) / trade['entry_price'] * trade['amount_usdt']
                    trade['profit'] = profit
                    state['investment_pool_available'] += trade['amount_usdt'] + profit
                    save_open_trades()
                    msg = f"<b>🔒 أغلق صفقة {trade['symbol']}</b>\nالسبب: انتهاء المدة\nالربح/الخسارة: {profit:.2f} USDT"
                    await send_telegram_text(msg)
        await asyncio.sleep(1)

# ====== تشغيل البوت ======
async def main():
    load_master_symbols()
    build_eligible_pairs()
    load_open_trades()

    asyncio.create_task(monitor_trades_loop())

    await send_telegram_text(f"<b>🤖 بدء التداول</b>\nرصيد متاح: {state['investment_pool_available']:.2f} USDT")

    while not state['stop_trading']:
        async with state_lock:
            if len(state['open_trades']) < DEFAULT_MAX_CONCURRENT_TRADES:
                available_pairs = [p for p in state['eligible_pairs'] if p not in [t['symbol'] for t in state['open_trades']]]
                if available_pairs:
                    symbol = random.choice(available_pairs)
                    amount = min(1.0, state['investment_pool_available'])
                    strategy = random.choice(TRADING_STRATEGIES)
                    await open_trade(symbol, amount, strategy)
        await asyncio.sleep(15)

# ====== Telegram commands ======
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 البوت جاهز للتداول!")

if __name__ == "__main__":
    load_open_trades()
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    asyncio.run(main())
