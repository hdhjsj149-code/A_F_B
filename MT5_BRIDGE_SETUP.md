# ربط البوت بـ MT5 — قراءة فقط

## الفكرة

البوت المستضاف على Render لا يستطيع الوصول مباشرة إلى برنامج MT5 الموجود على جهازك.
لذلك نشغّل `mt5_bridge.py` على Windows/VPS الذي عليه MetaTrader 5.
الـbridge يفتح 3 عمليات قراءة فقط:

- `GET /health`
- `GET /tick?symbol=XAUUSD`
- `GET /rates?symbol=XAUUSD&timeframe=M15&count=500`

لا توجد في الملف أي وظيفة لإرسال أمر تداول، تعديل صفقة، إغلاق صفقة أو سحب أموال.

## 1) على جهاز MT5

1. ثبّت MetaTrader 5 وسجّل الدخول بالحساب المطلوب.
2. يفضّل استخدام حساب/وضع Investor (قراءة فقط) إذا كان الوسيط يدعمه.
3. ثبّت Python 3.11 أو أحدث.
4. افتح PowerShell داخل مجلد المشروع:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-mt5-bridge.txt
```

5. أنشئ متغيراً سرياً قوياً:

```powershell
$env:MT5_BRIDGE_TOKEN="ضع-سر-عشوائي-طويل-هنا"
$env:MT5_BRIDGE_HOST="127.0.0.1"
$env:MT5_BRIDGE_PORT="8765"
python mt5_bridge.py
```

## 2) الوصول من Render

إذا كان البوت على Render، `127.0.0.1` لن يعمل من Render لأنه يعني نفس جهاز Render.
استخدم أحد الحلول الآمنة التالية:

- VPS عليه MT5 + HTTPS reverse proxy.
- VPN خاص مثل Tailscale بين Render/VPS إن كانت بنية الاستضافة تسمح بذلك.
- Cloudflare Tunnel أو حل tunnel موثوق، مع HTTPS.

لا تفتح المنفذ 8765 للإنترنت مباشرة بدون HTTPS وحماية قوية.

في Render ضع:

```text
MT5_BRIDGE_URL=https://عنوان-الـbridge
MT5_BRIDGE_TOKEN=نفس-السر
MT5_TIMEOUT_SECONDS=10
```

## 3) اختبار الاتصال

من Telegram كمالك استخدم:

```text
/mt5status
```

إذا ظهر `🟢 متصل` فالبوت استطاع قراءة MT5.

## 4) تحليل MT5

من زر تحليل السوق اختر MT5، ثم اكتب رمز الوسيط كما يظهر داخل MT5، مثلاً:

```text
XAUUSD
```

بعض الوسطاء يستخدمون أسماء مختلفة مثل `XAUUSD.a` أو `XAUUSDm`. يجب استخدام الاسم الموجود فعلياً في MT5.

## 5) تسجيل صفقة وربطها بالشمعة

استخدم UTC للوقت التاريخي:

```text
/trade XAUUSD mt5 15m BUY 3500 3480 3540 2026-09-12T14:30:00 breakout
```

النظام سيحاول تحديد شمعة الدخول نفسها، ثم يحفظ:

- وقت الدخول UTC
- وقت افتتاح شمعة الدخول
- OHLCV
- نافذة الشموع السابقة
- مؤشرات التحليل
- نماذج الشموع المكتشفة
- Market Structure
- Support/Resistance
- سياق الفريمات الأعلى المتاحة
- مصدر البيانات
- فرق وقت الصفقة عن الشمعة

إذا لم يجد مطابقة موثوقة، يحفظ الصفقة مع تحذير ولا يعاملها كعينة سياق دقيقة للتعلم.

## الأمان

- لا تحفظ كلمة مرور MT5 في Render.
- لا تضع كلمة مرور الحساب داخل Telegram.
- لا تستخدم Trading API keys.
- لا تضف `order_send` أو أي دالة تنفيذ إلى bridge.
- اجعل `MT5_BRIDGE_TOKEN` سراً طويلاً وعشوائياً.
- استخدم HTTPS عند الربط عبر الإنترنت.
