"""
إعدادات البوت — كلها تُقرأ من متغيرات البيئة (Environment Variables)
لا تكتب أي مفتاح سري هنا مباشرة، أضفه من لوحة تحكم Railway بدلاً من ذلك.
"""

import os

# توكن البوت من @BotFather
BOT_TOKEN = os.environ["BOT_TOKEN"]

# توكن تطبيقك في @CryptoBot (Crypto Pay API)
CRYPTO_PAY_TOKEN = os.environ["CRYPTO_PAY_TOKEN"]

# رابط API الأساسي — استخدم testnet أثناء التجربة إن أردت
# mainnet: https://pay.crypt.bot/api
# testnet: https://testnet-pay.crypt.bot/api
CRYPTO_PAY_API_URL = os.environ.get("CRYPTO_PAY_API_URL", "https://pay.crypt.bot/api")

# معرف القناة الخاصة (رقم سالب يبدأ بـ -100...)
# احصل عليه بإضافة @userinfobot للقناة كأدمن مؤقتًا أو عبر أي طريقة مشابهة
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

# سعر ومدة الاشتراك
SUBSCRIPTION_PRICE_USD = float(os.environ.get("SUBSCRIPTION_PRICE_USD", "20"))
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))

# كل كم ثانية يتم فحص حالة الفواتير المعلّقة
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "30"))
