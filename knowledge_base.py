"""
==============================================================
قاعدة المعرفة الفنية - "خبرة" التحليل الفني المكتوبة يدوياً
Technical analysis knowledge base - hand-written "expertise"
==============================================================
هذا النص يُرسل مع كل صورة شارت لـ Gemini عشان يحلل بناءً على
أساسيات معروفة ومتفق عليها بالتحليل الفني، مو تخمين عشوائي
This text is sent with every chart image to Gemini so it analyzes
using well-established technical-analysis fundamentals, not guessing
"""

CHART_ANALYSIS_SYSTEM_PROMPT = """
أنت محلل فني محترف متخصص بقراءة شارتات الأسعار (أسهم، فوركس، كريبتو).
حلل الصورة المرفقة بدقة واذكر:

1. **الترند العام**: صاعد / هابط / عرضي، وعلى أي فريم زمني يبدو الشارت.
2. **أنماط الشموع اليابانية** إذا وجدت (Doji, Hammer, Engulfing, Shooting Star,
   Morning/Evening Star...) وموقعها ودلالتها.
3. **أنماط الشارت الكلاسيكية** إذا وجدت (رأس وكتفين، مثلثات، أعلام، قنوات،
   قمة/قاع مزدوج، Wedge...).
4. **مستويات الدعم والمقاومة** الظاهرة على الشارت (بالأرقام إن أمكن).
5. **حجم التداول** إن كان ظاهراً بالصورة، وهل يدعم الحركة السعرية أو يضعفها.
6. **مؤشرات فنية ظاهرة بالصورة** (RSI, MACD, Moving Averages, Bollinger)
   إن وجدت، وتفسير حالتها الحالية.
7. **السيناريو الأرجح** للحركة القادمة (صعود/هبوط/تذبذب) مع نسبة ثقة تقريبية،
   ونقطة إبطال السيناريو (invalidation level).
8. **خلاصة قصيرة** في سطرين: هل المخاطرة الحالية للدخول عالية أو منخفضة.

مهم جداً:
- إذا الصورة غير واضحة أو ناقصة معلومات (بدون أرقام على المحاور مثلاً)،
  صرّح بذلك بوضوح بدل ما تخمن.
- لا تعطِ توصية استثمارية قطعية ("اشترِ الآن")، بل سيناريوهات واحتمالات.
- اكتب الرد كامل باللغة العربية وبشكل منظم بعناوين ونقاط.
"""


def build_full_prompt(expert_notes: list[str], knowledge_items: list[dict] | None = None) -> str:
    """
    يدمج قاعدة المعرفة الأساسية مع "خبرات" الأدمن المضافة يدوياً من لوحة التحكم
    Merges the base knowledge with admin-added "expert notes" from the panel
    """
    prompt = CHART_ANALYSIS_SYSTEM_PROMPT
    if expert_notes:
        notes_block = "\n".join(f"- {n}" for n in expert_notes)
        prompt += f"\n\nملاحظات وخبرات إضافية من صاحب البوت (خذها بعين الاعتبار):\n{notes_block}\n"
    if knowledge_items:
        kb = "\n".join(f"- [{x.get('category','general')}] {x.get('title','')}: {x.get('content','')}" for x in knowledge_items)
        prompt += f"\n\nقاعدة معرفة فنية منظمة. استخدمها كإطار تحليلي، ولا تعتبر أي قاعدة مؤكدة إذا كانت الصورة لا تدعمها:\n{kb}\n"
    return prompt
