"""
بوت اشتراكات قناة توصيات الكريبتو
====================================
يتعامل مع:
- استقبال طلب اشتراك من المستخدم
- إنشاء فاتورة دفع عبر @CryptoBot (Crypto Pay API)
- التحقق من حالة الدفع بشكل دوري
- توليد رابط دعوة صالح لمرة واحدة فقط بعد تأكيد الدفع
- تتبع تاريخ انتهاء الاشتراك وطرد المستخدم تلقائيًا عند الانتهاء
"""

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import (
    BOT_TOKEN,
    CRYPTO_PAY_TOKEN,
    CRYPTO_PAY_API_URL,
    CHANNEL_ID,
    SUBSCRIPTION_PRICE_USD,
    SUBSCRIPTION_DAYS,
    CHECK_INTERVAL_SECONDS,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_PATH = "subscriptions.db"


# ---------------------------------------------------------------------------
# قاعدة البيانات
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            expires_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.commit()
    conn.close()


def save_invoice(invoice_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO invoices (invoice_id, user_id, status, created_at) VALUES (?, ?, 'pending', ?)",
        (invoice_id, user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_pending_invoices():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT invoice_id, user_id FROM invoices WHERE status = 'pending'")
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_invoice_paid(invoice_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
    conn.commit()
    conn.close()


def upsert_subscription(user_id: int, days: int):
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO subscriptions (user_id, expires_at, active) VALUES (?, ?, 1)",
        (user_id, expires_at),
    )
    conn.commit()
    conn.close()


def get_expired_subscriptions():
    conn = sqlite3.connect(DB_PATH)
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "SELECT user_id FROM subscriptions WHERE expires_at < ? AND active = 1", (now,)
    )
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def deactivate_subscription(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscriptions SET active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# التعامل مع Crypto Pay API
# ---------------------------------------------------------------------------
async def create_invoice(amount_usd: float, description: str) -> dict:
    """ينشئ فاتورة دفع عبر @CryptoBot ويرجع بياناتها (invoice_id, pay_url)."""
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    payload = {
        "amount": str(amount_usd),
        "currency_type": "fiat",
        "fiat": "USD",
        "description": description,
        "expires_in": 1800,  # نصف ساعة صلاحية للفاتورة
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CRYPTO_PAY_API_URL}/createInvoice", json=payload, headers=headers
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                logger.error("فشل إنشاء الفاتورة: %s", data)
                raise RuntimeError(f"createInvoice failed: {data}")
            return data["result"]


async def get_invoice_status(invoice_id: int) -> str:
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    params = {"invoice_ids": str(invoice_id)}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{CRYPTO_PAY_API_URL}/getInvoices", params=params, headers=headers
        ) as resp:
            data = await resp.json()
            if not data.get("ok") or not data["result"]["items"]:
                return "unknown"
            return data["result"]["items"][0]["status"]  # active / paid / expired


# ---------------------------------------------------------------------------
# أوامر البوت
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 اشتراك", callback_data="subscribe")]]
    )
    await update.message.reply_text(
        "مرحبًا بك 👋\n\n"
        f"اشترك للحصول على توصيات التداول لمدة {SUBSCRIPTION_DAYS} يومًا "
        f"مقابل {SUBSCRIPTION_PRICE_USD}$.",
        reply_markup=keyboard,
    )


async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    try:
        invoice = await create_invoice(
            SUBSCRIPTION_PRICE_USD, f"اشتراك توصيات - {SUBSCRIPTION_DAYS} يوم"
        )
    except Exception as e:
        logger.exception("خطأ في إنشاء الفاتورة")
        await query.message.reply_text("حدث خطأ أثناء إنشاء الفاتورة، حاول لاحقًا.")
        return

    save_invoice(invoice["invoice_id"], user_id)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("الذهاب للدفع 🔗", url=invoice["pay_url"])]]
    )
    await query.message.reply_text(
        "تم إنشاء فاتورة الدفع. اضغط الزر أدناه لإتمام الدفع، "
        "وسيتم تفعيل اشتراكك تلقائيًا فور تأكيد الدفع (قد يستغرق دقيقة).",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# مهام الخلفية (polling)
# ---------------------------------------------------------------------------
async def check_payments_job(application: Application):
    """يفحص الفواتير المعلقة بشكل دوري، وعند الدفع يولّد رابط دعوة ويفعّل الاشتراك."""
    while True:
        try:
            pending = get_pending_invoices()
            for invoice_id, user_id in pending:
                status = await get_invoice_status(invoice_id)
                if status == "paid":
                    mark_invoice_paid(invoice_id)
                    upsert_subscription(user_id, SUBSCRIPTION_DAYS)

                    invite_link = await application.bot.create_chat_invite_link(
                        chat_id=CHANNEL_ID,
                        member_limit=1,
                        expire_date=int(time.time()) + 3600,  # الرابط صالح ساعة واحدة فقط
                    )
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "✅ تم تأكيد الدفع بنجاح!\n\n"
                            f"رابط الانضمام للقناة (صالح لمرة واحدة):\n{invite_link.invite_link}"
                        ),
                    )
                    logger.info("تم تفعيل اشتراك المستخدم %s", user_id)
        except Exception:
            logger.exception("خطأ في فحص الدفعات")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def check_expired_job(application: Application):
    """يفحص يوميًا المشتركين المنتهية صلاحيتهم ويطردهم من القناة."""
    while True:
        try:
            expired_users = get_expired_subscriptions()
            for user_id in expired_users:
                try:
                    await application.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                    await application.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                    deactivate_subscription(user_id)
                    await application.bot.send_message(
                        chat_id=user_id,
                        text="⏰ انتهى اشتراكك. يمكنك تجديده عبر /start.",
                    )
                    logger.info("تم إنهاء اشتراك المستخدم %s", user_id)
                except Exception:
                    logger.exception("فشل طرد المستخدم %s", user_id)
        except Exception:
            logger.exception("خطأ في فحص الاشتراكات المنتهية")

        await asyncio.sleep(6 * 3600)  # كل 6 ساعات


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------
async def post_init(application: Application):
    init_db()
    asyncio.create_task(check_payments_job(application))
    asyncio.create_task(check_expired_job(application))
    logger.info("تم تشغيل مهام الخلفية بنجاح")


def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(subscribe_callback, pattern="^subscribe$"))

    logger.info("البوت يعمل الآن...")
    application.run_polling()


if __name__ == "__main__":
    main()
