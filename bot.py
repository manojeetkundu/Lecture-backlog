import os
import sqlite3
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 1. Dummy Web Server (Render ke port binding ke liye) ---
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
            duration REAL NOT NULL,
            priority INTEGER NOT NULL,
            completed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# --- 3. Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Main aapka Lecture Backlog Bot hoon.\n\n"
        "Commands:\n"
        "📌 /add [title], [subject], [duration], [priority 1-3]\n"
        "   *(Example: /add Integration, Maths, 1.5, 1)*\n\n"
        "🎯 /suggest [hours]\n"
        "   *(Example: /suggest 2.0)*\n\n"
        "🎉 /done [id]\n"
        "   *(Example: /done 1)*"
    )

async def add_lecture_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = " ".join(context.args)
        parts = [p.strip() for p in text.split(',')]
        title, subject, duration, priority = parts[0], parts[1], float(parts[2]), int(parts[3])
        
        conn = sqlite3.connect('lecture_backlog.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO lectures (title, subject, duration, priority, completed)
            VALUES (?, ?, ?, ?, 0)
        ''', (title, subject, duration, priority))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Lecture added successfully: '{title}' ({subject})")
    except Exception as e:
        await update.message.reply_text("❌ Galat format! Use karein:\n`/add Title, Subject, Duration, Priority`")

async def suggest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        available_hours = float(context.args[0])
        conn = sqlite3.connect('lecture_backlog.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, subject, duration, priority 
            FROM lectures 
            WHERE completed = 0 AND duration <= ? 
            ORDER BY priority ASC, duration DESC
            LIMIT 1
        ''', (available_hours,))
        lecture = cursor.fetchone()
        conn.close()
        
        if lecture:
            priority_str = 'High' if lecture[4] == 1 else 'Medium' if lecture[4] == 2 else 'Low'
            msg = (
                f"🎯 **Aapke liye recommended lecture:**\n\n"
                f"🆔 ID: {lecture[0]}\n"
                f"📚 Title: {lecture[1]}\n"
                f"📖 Subject: {lecture[2]}\n"
                f"⏱️ Duration: {lecture[3]} hours\n"
                f"🔥 Priority: {priority_str}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Is time mein fit hone wali koi uncompleted lecture nahi mili!")
    except Exception as e:
        await update.message.reply_text("❌ Format galat hai! Use karein: `/suggest [hours]` (e.g., `/suggest 2`)")

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lecture_id = int(context.args[0])
        conn = sqlite3.connect('lecture_backlog.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE lectures SET completed = 1 WHERE id = ?', (lecture_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 Lecture ID {lecture_id} ko complete mark kar diya gaya hai!")
    except Exception as e:
        await update.message.reply_text("❌ Format galat hai! Use karein: `/done [lecture_id]`")


# --- 4. Main Function ---
def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise ValueError("TOKEN environment variable set nahi hai!")
    
    # Flask server ko alag thread mein chalate hain taaki bot ke sath conflict na ho
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # Telegram Bot Start
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_lecture_cmd))
    app.add_handler(CommandHandler("suggest", suggest_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    
    print("🤖 Bot aur Dummy Server start ho rahe hain...")
    app.run_polling()

if __name__ == '__main__':
    main()
