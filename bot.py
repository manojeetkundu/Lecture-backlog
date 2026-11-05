import os
import sqlite3
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# --- 1. Dummy Web Server (Render ke port binding ke liye) ---
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "🤖 Lecture Backlog Bot is alive and running!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# --- 2. Database Initialization (Bina duration aur priority ke) ---
def init_db():
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            completed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# --- 3. Conversation States for Adding Lecture ---
TITLE, SUBJECT = range(2)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Naya lecture add karne ke liye sabse pehle lecture ka **Title** bhejo:\n"
        "(Jaise: `Chapter 1 Introduction`)\n\n"
        "*(Agar cancel karna ho toh `/cancel` likhein)*"
    )
    return TITLE

async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text("📂 Ab batao ki yeh lecture kis **Subject** ka hai?\n(Jaise: `Maths`, `Physics`):")
    return SUBJECT

async def get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip()
    title = context.user_data['title']
    
    # Database mein save karna (ID automatic generate hogi)
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lectures (title, subject, completed)
        VALUES (?, ?, 0)
    ''', (title, subject))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ Lecture successfully save ho gaya!\n\n"
        f"📚 Title: {title}\n"
        f"📂 Subject: {subject}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Lecture add karne ki process cancel kar di gayi hai.")
    return ConversationHandler.END


# --- 4. Commands (/start, /suggest, /done, /status) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Main aapka Simple Lecture Backlog Bot hoon.\n\n"
        "Commands:\n"
        "📌 `/add` - Naya lecture add karne ke liye\n"
        "🎯 `/suggest` - Jo lecture sabse pehle add kiya tha, use dekhne ke liye\n"
        "🎉 `/done [id]` - Lecture ko complete mark karne ke liye (e.g., `/done 1`)\n"
        "📊 `/status` - Har subject ka progress dekhne ke liye\n"
    )

async def suggest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    
    # Yeh query sabse pehle add kiye gaye (sabse choti ID wale) uncompleted lecture ko layegi
    cursor.execute('''
        SELECT id, title, subject 
        FROM lectures 
        WHERE completed = 0 
        ORDER BY id ASC 
        LIMIT 1
    ''')
    lecture = cursor.fetchone()
    conn.close()
    
    if lecture:
        msg = (
            f"🎯 **Aapke liye next recommended lecture:**\n\n"
            f"🆔 ID: {lecture[0]}\n"
            f"📚 Title: {lecture[1]}\n"
            f"📖 Subject: {lecture[2]}\n\n"
            f"Isko dekhne ke baad `/done {lecture[0]}` command use karna taaki agla lecture aa sake!"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("🎉 Badhai ho! Aapka saara backlog clear ho chuka hai!")

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lecture_id = int(context.args[0])
        conn = sqlite3.connect('lecture_backlog.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE lectures SET completed = 1 WHERE id = ?', (lecture_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 Great job! Lecture ID {lecture_id} complete ho gaya hai. Ab aap `/suggest` karke agla lecture dekh sakte hain.")
    except Exception as e:
        await update.message.reply_text("❌ Format galat hai! Use karein: `/done [lecture_id]` (jaise `/done 1`)")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('lecture_backlog.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT DISTINCT subject FROM lectures')
    subjects = cursor.fetchall()
    
    if not subjects:
        await update.message.reply_text("📂 Abhi tak koi lectures add nahi kiye gaye hain!")
        conn.close()
        return

    report = "📊 **Aapka Subject-wise Backlog Status:**\n\n"
    
    for sub in subjects:
        subject_name = sub[0]
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ?', (subject_name,))
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM lectures WHERE subject = ? AND completed = 1', (subject_name,))
        completed = cursor.fetchone()[0]
        
        percent = int((completed / total) * 100) if total > 0 else 0
        report += f"📁 **{subject_name}**\n"
        report += f"   - Completed: {completed}/{total} ({percent}%)\n"
        report += f"   - Pending: {total - completed} lectures\n\n"
    
    conn.close()
    await update.message.reply_text(report, parse_mode='Markdown')


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
            SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_subject)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_handler)
    app.add_handler(CommandHandler("suggest", suggest_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    
    print("🤖 Bot aur Dummy Server successfully start ho rahe hain...")
    app.run_polling()

if __name__ == '__main__':
    main()
