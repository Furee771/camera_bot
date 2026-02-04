import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()

# На Heroku 
DATABASE_URL = os.environ.get('DATABASE_URL') 
conn = psycopg2.connect(DATABASE_URL, sslmode='require')

# 1. LOGLARNI SOZLASH
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ASOSIY SOZLAMALAR ---
TOKEN = os.environ.get("API_KEY")  
ADMIN_IDS = [8503332430]  # Adminlarning Telegram IDlarini 
CHANNEL_ID = -1003622395120 
CHANNEL_LINK = "https://t.me/cameraServiceBot1"

# 2. BAZA BILAN ISHLASH
def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(db_url, sslmode='require')
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS applications 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT, description TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, name TEXT, price TEXT, photo_id TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (key TEXT PRIMARY KEY, value TEXT)''')
        
        # FIX: Matnni xavfsiz kiritish (apostrof xatosini oldini olish uchun ?, ? ishlatamiz)
        info_text = "Bizning xizmatlar: Kamera o'rnatish, ta'mirlash va sozlash."
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('info_text', info_text))
        conn.commit()

init_db()

# 3. STATES (HOLATLAR)
NAME, PHONE, LOCATION, DESCRIPTION = range(4)
(CHOOSING_ACTION, EDIT_CATEGORY, RENAME_CATEGORY, INPUT_NAME, 
 INPUT_PRICE, INPUT_PHOTO, SELECT_CAT_FOR_ADD, CONFIRM_DELETE,
 SELECT_PRODUCT_TO_DELETE, NEW_CAT_NAME, WAIT_FOR_NEW_NAME, EDIT_INFO_TEXT) = range(10, 22)

# --- YORDAMCHI FUNKSIYALAR ---

async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return False
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS: return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

async def get_admin_link(context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = await context.bot.get_chat(ADMIN_IDS[0])
        return f"@{chat.username}" if chat.username else "Admin"
    except: return "Admin"

# --- ASOSIY MENYU VA START ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() 
    if not await is_subscribed(update, context):
        keyboard = [[KeyboardButton("✅ Obunani tekshirish")]]
        await update.message.reply_text(f"Botdan foydalanish uchun kanalga a'zo bo'ling:\n{CHANNEL_LINK}", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return ConversationHandler.END

    keyboard = [
        [KeyboardButton("🛍 Katalog")], 
        [KeyboardButton("📝 Ariza qoldirish")], 
        [KeyboardButton("ℹ️ Ma'lumot"), KeyboardButton("🚀 Botni ulashish")]
    ]
    if update.effective_user.id in ADMIN_IDS:
        keyboard.append([KeyboardButton("🛠 Admin Panel")])
        
    await update.message.reply_text("Xush kelibsiz! Asosiy menyu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ConversationHandler.END

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update, context): return await start(update, context)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'info_text'")
        row = cursor.fetchone()
        text = row[0] if row else "Ma'lumot topilmadi."
    await update.message.reply_text(text, parse_mode='HTML')

async def share_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await context.bot.get_me()
    await update.message.reply_text(f"Do'stlaringizga ulashing:\nhttps://t.me/cameraServiceBot?start=welcome")

async def check_sub_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_subscribed(update, context):
        await update.message.reply_text("✅ Obuna tasdiqlandi!")
        return await start(update, context)
    await update.message.reply_text("❌ Siz hali a'zo emassiz.")

# --- FOYDALANUVCHI ARIZA QOLDIRISH ---

async def new_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update, context): return await start(update, context)
    await update.message.reply_text("Ismingizni kiriting:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚫 Bekor qilish")]], resize_keyboard=True))
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['app_name'] = update.message.text
    await update.message.reply_text("Telefon raqamingizni yuboring:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚫 Bekor qilish")]], resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['app_phone'] = update.message.text
    keyboard = [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)], [KeyboardButton("Keyingi ➡️"), KeyboardButton("🚫 Bekor qilish")]]
    await update.message.reply_text("Manzilingizni yuboring (yoki lokatsiya tugmasini bosing):", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        context.user_data['app_location'] = f"https://www.google.com/maps?q={update.message.location.latitude},{update.message.location.longitude}"
    elif update.message.text == "Keyingi ➡️":
        context.user_data['app_location'] = "Ko'rsatilmadi"
    else:
        context.user_data['app_location'] = update.message.text
        
    await update.message.reply_text("Muammoni qisqacha yozing:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚫 Bekor qilish")]], resize_keyboard=True))
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    name = context.user_data.get('app_name')
    phone = context.user_data.get('app_phone')
    loc = context.user_data.get('app_location')
    
    with get_db_connection() as conn:
        conn.cursor().execute("INSERT INTO applications (user_id, name, phone, description) VALUES (?, ?, ?, ?)", 
                             (update.effective_user.id, name, phone, f"{desc}\n📍 {loc}"))
        conn.commit()
        
    report = f"🔔 <b>YANGI ARIZA</b>\n👤 {name}\n📞 {phone}\n📍 {loc}\n📝 {desc}"
    for admin_id in ADMIN_IDS:
        try: await context.bot.send_message(chat_id=admin_id, text=report, parse_mode='HTML')
        except: pass
        
    await update.message.reply_text("✅ Arizangiz qabul qilindi! Tez orada aloqaga chiqamiz.")
    return await start(update, context)

async def cancel_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

# --- ADMIN PANEL FUNKSIYALARI ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return ConversationHandler.END
    keyboard = [
        [KeyboardButton("➕ Tovar qo'shish"), KeyboardButton("✏️ Kategoriyani tahrirlash")],
        [KeyboardButton("🗑 Tovarni o'chirish"), KeyboardButton("📄 Arizalarni ko'rish")],
        [KeyboardButton("📝 Ma'lumotni tahrirlash")],
        [KeyboardButton("⬅️ Orqaga")]
    ]
    await update.message.reply_text("🛠 Admin paneli:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return CHOOSING_ACTION

# 1. Arizalarni ko'rish
async def view_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, phone, description FROM applications ORDER BY id DESC LIMIT 15")
        apps = cursor.fetchall()
    if not apps:
        await update.message.reply_text("📭 Arizalar yo'q.")
        return CHOOSING_ACTION
    text = "📄 <b>Oxirgi 15 ta ariza:</b>\n\n"
    for app_id, name, phone, desc in apps:
        text += f"<b>№{app_id}</b> | 👤 {name}\n📞 {phone}\n📝 {desc}\n--------------------\n"
    keyboard = [[KeyboardButton("🗑 Barcha arizalarni o'chirish")], [KeyboardButton("⬅️ Orqaga")]]
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return CHOOSING_ACTION

async def clear_all_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        conn.cursor().execute("DELETE FROM applications")
        conn.commit()
    await update.message.reply_text("✅ Barcha arizalar o'chirildi!")
    return await admin_panel(update, context)

# 2. Ma'lumotni tahrirlash
async def start_edit_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Yangi ma'lumot matnini yuboring:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Orqaga")]], resize_keyboard=True))
    return EDIT_INFO_TEXT

async def save_info_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await admin_panel(update, context)
    with get_db_connection() as conn:
        conn.cursor().execute("UPDATE settings SET value = ? WHERE key = 'info_text'", (update.message.text,))
        conn.commit()
    await update.message.reply_text("✅ Ma'lumot yangilandi!")
    return await admin_panel(update, context)

# 3. Tovar qo'shish
async def start_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products")
        cats = cursor.fetchall()
    keyboard = [[KeyboardButton(c[0])] for c in cats]
    keyboard.append([KeyboardButton("➕ Yangi kategoriya"), KeyboardButton("⬅️ Orqaga")])
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return SELECT_CAT_FOR_ADD

async def get_cat_for_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⬅️ Orqaga": return await admin_panel(update, context)
    if text == "➕ Yangi kategoriya":
        await update.message.reply_text("Yangi kategoriya nomini yozing:")
        return NEW_CAT_NAME
    context.user_data['p_cat'] = text
    await update.message.reply_text("Tovar nomi:")
    return INPUT_NAME

async def get_new_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await start_add_product(update, context)
    context.user_data['p_cat'] = update.message.text
    await update.message.reply_text("Tovar nomi:")
    return INPUT_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await start_add_product(update, context)
    context.user_data['p_name'] = update.message.text
    await update.message.reply_text("Narxi:")
    return INPUT_PRICE

async def process_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await start_add_product(update, context)
    context.user_data['p_price'] = update.message.text
    await update.message.reply_text("Rasm yuboring:")
    return INPUT_PHOTO

async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await start_add_product(update, context)
    if not update.message.photo: 
        await update.message.reply_text("Iltimos, rasm yuboring!")
        return INPUT_PHOTO
    
    fid = update.message.photo[-1].file_id
    with get_db_connection() as conn:
        conn.cursor().execute("INSERT INTO products (category, name, price, photo_id) VALUES (?, ?, ?, ?)", 
                             (context.user_data['p_cat'], context.user_data['p_name'], context.user_data['p_price'], fid))
    await update.message.reply_text("✅ Tovar qo'shildi!")
    return await admin_panel(update, context)

# 4. Kategoriya tahrirlash/o'chirish
async def prepare_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products")
        cats = cursor.fetchall()
    if not cats: 
        await update.message.reply_text("Kategoriya yo'q.")
        return await admin_panel(update, context)
    keyboard = [[KeyboardButton(c[0])] for c in cats]
    keyboard.append([KeyboardButton("⬅️ Orqaga")])
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return EDIT_CATEGORY

async def get_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await admin_panel(update, context)
    context.user_data['old_cat'] = update.message.text
    keyboard = [[KeyboardButton("✏️ Nomini o'zgartirish"), KeyboardButton("🗑 Kategoriyani o'chirish")], [KeyboardButton("⬅️ Orqaga")]]
    await update.message.reply_text("Amalni tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return RENAME_CATEGORY

async def start_rename_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Yangi nomni kiriting:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Orqaga")]], resize_keyboard=True))
    return WAIT_FOR_NEW_NAME

async def do_actual_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await prepare_rename(update, context)
    with get_db_connection() as conn:
        conn.cursor().execute("UPDATE products SET category = ? WHERE category = ?", (update.message.text, context.user_data['old_cat']))
    await update.message.reply_text("✅ Yangilandi!")
    return await admin_panel(update, context)

async def final_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        conn.cursor().execute("DELETE FROM products WHERE category = ?", (context.user_data['old_cat'],))
    await update.message.reply_text("🗑 O'chirildi!")
    return await admin_panel(update, context)

# 5. Tovarni o'chirish
async def delete_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products")
        categories = cursor.fetchall()
    if not categories: return await admin_panel(update, context)
    keyboard = [[KeyboardButton(cat[0])] for cat in categories]
    keyboard.append([KeyboardButton("⬅️ Orqaga")])
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return SELECT_PRODUCT_TO_DELETE

async def delete_product_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await admin_panel(update, context)
    category = update.message.text
    context.user_data['del_cat'] = category
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM products WHERE category = ?", (category,))
        products = cursor.fetchall()
    if not products:
        await update.message.reply_text("Bu kategoriyada tovar yo'q.")
        return await delete_product_start(update, context)
    keyboard = [[KeyboardButton(p[0])] for p in products]
    keyboard.append([KeyboardButton("⬅️ Orqaga")])
    await update.message.reply_text("O'chirish uchun tovarni tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return CONFIRM_DELETE

async def delete_product_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Orqaga": return await delete_product_start(update, context)
    p_name = update.message.text
    cat = context.user_data.get('del_cat')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE name = ? AND category = ?", (p_name, cat))
        conn.commit()
    await update.message.reply_text(f"✅ {p_name} o'chirildi!")
    return await admin_panel(update, context)

# --- KATALOG KO'RISH ---
async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products")
        cats = cursor.fetchall()
    if not cats:
        await update.message.reply_text("Katalog bo'sh.")
        return
    keyboard = [[KeyboardButton(c[0])] for c in cats]
    keyboard.append([KeyboardButton("⬅️ Orqaga")])
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_category_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text
    # FIX: Agar foydalanuvchi "Orqaga" ni bossa, startga yuboramiz (buni quyida alohida handler ham qiladi, lekin ehtiyot shart)
    if category == "⬅️ Orqaga": return await start(update, context)
    
    ignore_list = ["🛍 Katalog", "📝 Ariza qoldirish", "ℹ️ Ma'lumot", "🚀 Botni ulashish", "🛠 Admin Panel", "➕ Tovar qo'shish"]
    if category in ignore_list: return 
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, price, photo_id FROM products WHERE category = ?", (category,))
        prods = cursor.fetchall()
        
    if not prods: return 
    
    admin_link = await get_admin_link(context)
    
    for n, p, f in prods:
        cap = f"<b>{n}</b>\n💰 Narxi: {p}\n\n✅ Buyurtma berish uchun, iltimos, biz bilan bog'laning yoki ariza qoldiring: {admin_link}"
        try: await context.bot.send_photo(update.effective_chat.id, f, caption=cap, parse_mode='HTML')
        except: await update.message.reply_text(cap, parse_mode='HTML')

# --- MAIN ---
def main():
    app = Application.builder().token(TOKEN).build()
    back_f = filters.Regex("^⬅️ Orqaga$")
    cancel_f = filters.Regex("^🚫 Bekor qilish$")

    # 1. FOYDALANUVCHI HANDLERI (ARIZA)
    user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Ariza qoldirish$"), new_application)],
        states={
            NAME: [MessageHandler(cancel_f, cancel_user), MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(cancel_f, cancel_user), MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            LOCATION: [MessageHandler(cancel_f, cancel_user), MessageHandler(filters.LOCATION | filters.TEXT, get_location)],
            DESCRIPTION: [MessageHandler(cancel_f, cancel_user), MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    # 2. ADMIN HANDLERI
    admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠 Admin Panel$"), admin_panel)],
        states={
            CHOOSING_ACTION: [
                MessageHandler(filters.Regex("^➕ Tovar qo'shish$"), start_add_product),
                MessageHandler(filters.Regex("^✏️ Kategoriyani tahrirlash$"), prepare_rename),
                MessageHandler(filters.Regex("^🗑 Tovarni o'chirish$"), delete_product_start),
                MessageHandler(filters.Regex("^📄 Arizalarni ko'rish$"), view_applications),
                MessageHandler(filters.Regex("^🗑 Barcha arizalarni o'chirish$"), clear_all_applications),
                MessageHandler(filters.Regex("^📝 Ma'lumotni tahrirlash$"), start_edit_info),
                MessageHandler(back_f, start)
            ],
            # Qo'shish
            SELECT_CAT_FOR_ADD: [MessageHandler(filters.TEXT, get_cat_for_add)],
            NEW_CAT_NAME: [MessageHandler(filters.TEXT, get_new_cat_name)],
            INPUT_NAME: [MessageHandler(filters.TEXT, process_name)],
            INPUT_PRICE: [MessageHandler(filters.TEXT, process_price)],
            INPUT_PHOTO: [MessageHandler(filters.PHOTO, process_photo)],
            # Kategoriya Tahrirlash
            EDIT_CATEGORY: [MessageHandler(filters.TEXT, get_new_name)],
            RENAME_CATEGORY: [
                MessageHandler(filters.Regex("^✏️ Nomini o'zgartirish$"), start_rename_input),
                MessageHandler(filters.Regex("^🗑 Kategoriyani o'chirish$"), final_rename),
                MessageHandler(back_f, prepare_rename)
            ],
            WAIT_FOR_NEW_NAME: [MessageHandler(filters.TEXT, do_actual_rename)],
            # O'chirish
            SELECT_PRODUCT_TO_DELETE: [MessageHandler(filters.TEXT, delete_product_choice)],
            CONFIRM_DELETE: [MessageHandler(filters.TEXT, delete_product_final)],
            # Info
            EDIT_INFO_TEXT: [MessageHandler(filters.TEXT, save_info_text)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.Regex("^🛍 Katalog$"), show_catalog))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Ma'lumot$"), info))
    app.add_handler(MessageHandler(filters.Regex("^🚀 Botni ulashish$"), share_bot))
    app.add_handler(MessageHandler(filters.Regex("^✅ Obunani tekshirish$"), check_sub_button))
    
    app.add_handler(user_conv)
    app.add_handler(admin_conv)
    
    # FIX: "Orqaga" tugmasi uchun MAXSUS handler. Bu Katalogdagi matn ushlagichidan oldin turishi SHART.
    app.add_handler(MessageHandler(filters.Regex("^⬅️ Orqaga$"), start))

    # Eng oxirida matnni ushlaymiz (Katalogdagi tovarlar uchun)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, show_category_products))

    print("Bot muvaffaqiyatli ishga tushdi 🚀")
    app.run_polling()

if __name__ == '__main__': main()