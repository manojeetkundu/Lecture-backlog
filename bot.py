import os
import threading
from flask import Flask
import psycopg2
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
    return "Padhai Partner Bot is alive and running!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# --- 2. Database Connection (Supabase PostgreSQL) ---
def get_db_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lectures (
            id SERIAL PRIMARY KEY,
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


# --- 3. Conversation States (Add Lecture) ---
GET_VIDEO, GET_SUBJECT = range(2)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Naya lecture add karne ke liye apni video file bhejiye, aur video ke caption mein lecture ka title likh dijiye!\n\n"
        "Radd karne ke liye /cancel bhejiye"
    )
    return GET_VIDEO

async def get_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        context.user_data['file_id'] = update.message.video.file_id
        if update.message.caption:
            context.user_data['title'] = update.message.caption
        else:
            context.user_data['title'] = "Untitled Lecture"
    else:
        context.user_data['file_id'] = "none"
        context.user_data['title'] = update.message.text
        
    await update.message.reply_text(
        "Ab bataiye ki yeh lecture kis Subject ka hai?\n"
        "(Jaise: Maths, Physics)"
    )
    return GET_SUBJECT

async def get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip().capitalize()
    title = context.user_data['title']
    file_id = context.user_data['file_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lectures (title, subject, file_id, completed)
        VALUES (%s, %s, %s, 0)
    ''', (title, subject, file_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    await update.message.reply_text(
        f"Lecture safalpurvak save ho gaya!\n\n"
        f"Title: {title}\n"
        f"Subject: {subject}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Process cancel kar di gayi hai.")
    return ConversationHandler.END


# --- 4. Bot Commands & Subject/Random Suggestion Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Naya Lecture Jodein", callback_data="menu_add")],
        [InlineKeyboardButton("Agla Lecture Dekhein", callback_data="menu_suggest")],
        [InlineKeyboardButton("Backlog Status Dekhein", callback_data="menu_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Namaste! Main aapka personal Padhai Partner hoon.\n\n"
        "Apne lectures ko track karne ke liye niche diye gaye buttons ka use kijiye.",
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
            [InlineKeyboardButton("Ho Gaya (Done)", callback_data=f"done_{lecture_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = (
            f"Aapke liye agla lecture:\n\n"
            f"Subject: {subject}\n"
            f"ID: {lecture_id}\n"
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
            WHERE completed = 0 AND subject = %s 
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
        cursor.execute('UPDATE lectures SET completed = 1 WHERE id = %s', (lecture_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        try:
            if query.message.video:
                await query.edit_message_caption(caption=f"Shabash! Lecture ID {lecture_id} complete ho gaya hai!")
            else:
                await query.edit_message_text(text=f"Shabash! Lecture ID {lecture_id} complete ho gaya hai!")
        except Exception:
            await query.message.reply_text(f"Shabash! Lecture ID {lecture_id} complete ho gaya hai!")

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
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = %s', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = %s AND completed = 1', (subject_name,))
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
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = %s', (subject_name,))
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = %s AND completed = 1', (subject_name,))
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
            GET_VIDEO: [MessageHandler(filters.VIDEO | filters.TEXT & ~filters.COMMAND, get_video)],
            GET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_subject)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
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
