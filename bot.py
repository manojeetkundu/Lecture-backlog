import os
import sqlite3
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# --- 1. Dummy Web Server ---
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "🤖 Lecture Backlog Bot is alive and running!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# --- 2. Database Initialization ---
def init_db():
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            file_id TEXT,
            completed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# --- 3. Conversation States ---
TITLE, VIDEO_FILE, SUBJECT = range(3)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Naya lecture add karne ke liye sabse pehle lecture ka **Title** bhejiye:\n"
        "*(Jaise: Chapter 1 Introduction)*\n\n"
        "💡 *Radd karne ke liye `/cancel` bhejiye*"
    )
    return TITLE

async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text(
        "🎥 **Video File**\n\n"
        "Ab is lecture ki video file (video message) bhejiye:\n"
        "*(Agar video nahi hai toh 'none' likh kar bhej sakte hain)*"
    )
    return VIDEO_FILE

async def get_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        context.user_data['file_id'] = update.message.video.file_id
    else:
        context.user_data['file_id'] = "none"
        
    await update.message.reply_text(
        "📂 **Subject**\n\n"
        "Ab bataiye ki yeh lecture kis Subject ka hai?\n"
        "*(Jaise: Maths, Physics)*"
    )
    return SUBJECT

async def get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip()
    title = context.user_data['title']
    file_id = context.user_data['file_id']
    
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lectures (title, subject, file_id, completed)
        VALUES (?, ?, ?, 0)
    ''', (title, subject, file_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ **Lecture safalpurvak save ho gaya!**\n\n"
        f"📌 Title: {title}\n"
        f"📖 Subject: {subject}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Process cancel kar di gayi hai.")
    return ConversationHandler.END


# --- 4. Bot Commands & Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Naya Lecture Jodein", callback_data="menu_add")],
        [InlineKeyboardButton("🎯 Agla Lecture Dekhein", callback_data="menu_suggest")],
        [InlineKeyboardButton("📊 Backlog Status Dekhein", callback_data="menu_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 **Namaste!** Main aapka personal **Lecture Backlog Bot** hoon.\n\n"
        "Apne lectures ko track karne ke liye niche diye gaye buttons ka use kijiye. ✨",
        reply_markup=reply_markup
    )

async def suggest_cmd(update_or_query, context):
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, subject, file_id 
        FROM lectures 
        WHERE completed = 0 
        ORDER BY id ASC 
        LIMIT 1
    ''')
    lecture = cursor.fetchone()
    conn.close()
    
    message_obj = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query.effective_message
    chat_id = message_obj.chat_id

    if lecture:
        lecture_id, title, subject, file_id = lecture
        
        keyboard = [
            [InlineKeyboardButton("🎉 Ho Gaya (Done)", callback_data=f"done_{lecture_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = (
            f"🎯 **Aapke liye agla lecture:**\n\n"
            f"🆔 ID: {lecture_id}\n"
            f"📚 Title: {title}\n"
            f"📖 Subject: {subject}"
        )
        
        if file_id and file_id != "none":
            await context.bot.send_video(
                chat_id=chat_id, 
                video=file_id, 
                caption=msg, 
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=msg, 
                reply_markup=reply_markup
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id, 
            text="🎉 **Badhai ho!** Aapka saara backlog clear ho chuka hai! 🚀"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "menu_suggest":
        await suggest_cmd(query, context)
    elif data == "menu_status":
        await status_action(query)
    elif data.startswith("done_"):
        lecture_id = int(data.split("_")[1])
        conn = sqlite3.connect('lecture_backlog.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE lectures SET completed = 1 WHERE id = ?', (lecture_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"🎉 **Shabash!** Lecture ID {lecture_id} complete ho gaya hai! Agla lecture dekhne ke liye `/suggest` use kijiye.")

async def status_action(query):
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT subject FROM lectures')
    subjects = cursor.fetchall()
    
    if not subjects:
        await query.message.reply_text("📂 Abhi tak koi lectures add nahi kiye gaye hain!")
        conn.close()
        return

    report = "📊 **Aapka Subject-wise Progress:**\n\n"
    for sub in subjects:
        subject_name = sub[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ?', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ? AND completed = 1', (subject_name,))
        completed = cursor.fetchone()[0]
        percent = int((completed / total) * 100) if total > 0 else 0
        report += f"📁 **{subject_name}**\n   ✨ Ho gaye: {completed}/{total} ({percent}%)\n   ⏳ Baki hain: {total - completed}\n\n"
    
    conn.close()
    await query.message.reply_text(report)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT subject FROM lectures')
    subjects = cursor.fetchall()
    
    if not subjects:
        await update.message.reply_text("📂 Abhi tak koi lectures add nahi kiye gaye hain!")
        conn.close()
        return

    report = "📊 **Aapka Subject-wise Progress:**\n\n"
    for sub in subjects:
        subject_name = sub[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ?', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ? AND completed = 1', (subject_name,))
        completed = cursor.fetchone()[0]
        percent = int((completed / total) * 100) if total > 0 else 0
        report += f"📁 **{subject_name}**\n   ✨ Ho gaye: {completed}/{total} ({percent}%)\n   ⏳ Baki hain: {total - completed}\n\n"
    
    conn.close()
    await update.message.reply_text(report)


# --- 5. Main Function ---
def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise ValueError("TOKEN environment variable set nahi hai!")
    
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    add_handler = ConversationHandler(
        entry_points=[CommandHandler('add', start_add)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            VIDEO_FILE: [MessageHandler(filters.VIDEO | filters.TEXT & ~filters.COMMAND, get_video)],
            SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_subject)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_handler)
    app.add_handler(CommandHandler("suggest", lambda u, c: suggest_cmd(u, c)))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot aur Server successfully start ho rahe ہیں...")
    app.run_polling()

if __name__ == '__main__':
    main()
