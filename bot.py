import os
import threading
from flask import Flask
import sqlite3
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

# --- 1. Dummy Web Server (Render ke liye) ---
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Padhai Partner Bot is alive and running!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# --- 2. Database Connection (Local SQLite) ---
DB_NAME = "lecture_backlog.db"

def get_db_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_db_connection()
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
    cursor.close()
    conn.close()

init_db()


# --- 3. Bulk Upload Conversation States ---
GET_BULK_SUBJECT, GET_BULK_FILES = range(2)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Pehle bataiye, aap kis Subject📚 mein lectures add karna chahte hain?\n"
        "(Jaise: Maths, Physics)\n\n"
        "Radd karne ke liye /cancel bhejiye."
    )
    return GET_BULK_SUBJECT

async def get_bulk_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip().capitalize()
    context.user_data['bulk_subject'] = subject
    await update.message.reply_text(
        f"Subject {subject} set ho gaya hai!\n\n"
        "Ab aap ek sath ya ek-ek karke jitni chahein video files bhej sakte hain. "
        "Video ke caption mein lecture ka title likh sakte hain.\n\n"
        "Saari files bhejne ke baad /done type karein.",
        parse_mode="Markdown"
    )
    return GET_BULK_FILES

async def get_bulk_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = context.user_data.get('bulk_subject', 'General')
    
    # Agar user ne /done likha toh process khatam
    if update.message.text and update.message.text.lower() == '/done':
        await update.message.reply_text(f"Aapke **{subject}** ke saare lectures safalpurvak save ho gaye hain! 🎉", parse_mode="Markdown")
        return ConversationHandler.END

    file_id = "none"
    title = "Untitled Lecture"

    if update.message.video:
        file_id = update.message.video.file_id
        if update.message.caption:
            title = update.message.caption
    elif update.message.document:
        file_id = update.message.document.file_id
        if update.message.caption:
            title = update.message.caption
    elif update.message.text:
        title = update.message.text

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lectures (title, subject, file_id, completed)
        VALUES (?, ?, ?, 0)
    ''', (title, subject, file_id))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"✅ Save ho gaya: '{title}' ({subject}). Aur files bhejiye ya khatam karne ke liye /done likhiye.")
    return GET_BULK_FILES

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Process cancel kar di gayi hai.")
    return ConversationHandler.END


# --- 4. Bot Commands & Subject/Random Suggestion Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Naya Lecture Jodein", callback_data="menu_add")],
        [InlineKeyboardButton("🎯 Agla Lecture Dekhein", callback_data="menu_suggest")],
        [InlineKeyboardButton("📊 Backlog Status Dekhein", callback_data="menu_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Namaste! Main aapka personal Padhai Partner hoon.\n\n"
        "Apne lectures ko track karne ke liye niche diye gaye buttons ka use kijiye.✨",
        reply_markup=reply_markup
    )

async def suggest_cmd(update_or_query, context):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT subject FROM lectures WHERE completed = 0')
    subjects = cursor.fetchall()
    cursor.close()
    conn.close()
    
    message_obj = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query.effective_message
    chat_id = message_obj.chat_id

    if not subjects:
        text = "Badhai ho! Aapka saara backlog clear ho chuka hai!"
        if hasattr(update_or_query, 'edit_message_text'):
            try:
                await update_or_query.edit_message_text(text=text)
                return
            except Exception:
                pass
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    keyboard = []
    for sub in subjects:
        sub_name = sub[0]
        keyboard.append([InlineKeyboardButton(f"📚 {sub_name}", callback_data=f"suggest_sub_{sub_name}")])
    
    keyboard.append([InlineKeyboardButton("🔀 Randomize", callback_data="suggest_random")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "Aap kaunsa subject padhna chahte hain? Neeche se chuniye:"
    
    if hasattr(update_or_query, 'edit_message_text'):
        try:
            await update_or_query.edit_message_text(text=text, reply_markup=reply_markup)
            return
        except Exception:
            pass
            
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

async def send_lecture_message(query, context, lecture):
    chat_id = query.message.chat_id
    if lecture:
        lecture_id, title, subject, file_id = lecture
        
        keyboard = [
            [InlineKeyboardButton("Ho Gaya (Done)🥳", callback_data=f"done_{lecture_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = (
            f"Aapke liye agla lecture:👇\n\n"
            f"Subject 📚: {subject}\n"
            f"ID 🆔: {lecture_id}\n"
            f"Title: {title}"
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
        await query.message.reply_text("Is category mein koi pending lecture nahi hai!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "menu_add":
        await query.message.reply_text("Naya lecture add karne ke liye /add command type kijiye.")
    elif data == "menu_suggest":
        await suggest_cmd(query, context)
    elif data == "menu_status":
        await status_action(query)
    elif data.startswith("suggest_sub_"):
        subject_name = data.replace("suggest_sub_", "")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, subject, file_id 
            FROM lectures 
            WHERE completed = 0 AND subject = ? 
            ORDER BY id ASC 
            LIMIT 1
        ''', (subject_name,))
        lecture = cursor.fetchone()
        cursor.close()
        conn.close()
        await send_lecture_message(query, context, lecture)
    elif data == "suggest_random":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, subject, file_id 
            FROM lectures 
            WHERE completed = 0 
            ORDER BY RANDOM() 
            LIMIT 1
        ''')
        lecture = cursor.fetchone()
        cursor.close()
        conn.close()
        await send_lecture_message(query, context, lecture)
    elif data.startswith("done_"):
        lecture_id = int(data.split("_")[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE lectures SET completed = 1 WHERE id = ?', (lecture_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        try:
            if query.message.video:
                await query.edit_message_caption(caption=f"Shabash! Lecture ID {lecture_id} complete ho gaya hai!")
            else:
                await query.edit_message_text(text=f"Shabash!🏆 Lecture ID {lecture_id} complete ho gaya hai!")
        except Exception:
            await query.message.reply_text(f"Shabash!🏆 Lecture ID {lecture_id} complete ho gaya hai!")

async def status_action(query):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT subject FROM lectures')
    subjects = cursor.fetchall()
    
    if not subjects:
        await query.message.reply_text("Abhi tak koi lectures add nahi kiye gaye hain!")
        cursor.close()
        conn.close()
        return

    report = "Aapka Subject-wise Progress:\n\n"
    for sub in subjects:
        subject_name = sub[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ?', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ? AND completed = 1', (subject_name,))
        completed = cursor.fetchone()[0]
        percent = int((completed / total) * 100) if total > 0 else 0
        report += f"Subject: {subject_name}\n   Ho gaye: {completed}/{total} ({percent}%)\n   Baki hain: {total - completed}\n\n"
    
    cursor.close()
    conn.close()
    await query.message.reply_text(report)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT subject FROM lectures')
    subjects = cursor.fetchall()
    
    if not subjects:
        await update.message.reply_text("Abhi tak koi lectures add nahi kiye gaye hain!")
        cursor.close()
        conn.close()
        return

    report = "Aapka Subject-wise Progress:\n\n"
    for sub in subjects:
        subject_name = sub[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ?', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ? AND completed = 1', (subject_name,))
        completed = cursor.fetchone()[0]
        percent = int((completed / total) * 100) if total > 0 else 0
        report += f"Subject: {subject_name}\n   Ho gaye: {completed}/{total} ({percent}%)\n   Baki hain: {total - completed}\n\n"
    
    cursor.close()
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
            GET_BULK_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bulk_subject)],
            GET_BULK_FILES: [MessageHandler((filters.VIDEO | filters.Document.ALL | filters.TEXT) & ~filters.COMMAND, get_bulk_files)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('done', get_bulk_files)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_handler)
    app.add_handler(CommandHandler("suggest", lambda u, c: suggest_cmd(u, c)))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot aur Server successfully start ho rahe hain...")
    app.run_polling()

if __name__ == '__main__':
    main()
