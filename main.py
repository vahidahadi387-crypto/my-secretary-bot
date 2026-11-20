import os
import sqlite3
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")
DB_PATH = os.getenv("DB_PATH", "secretary.db")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

MENU = ReplyKeyboardMarkup(
    [
        ["📝 یادداشت جدید", "📋 یادداشت‌ها"],
        ["➕ کار جدید", "✅ کارهای من"],
        ["⏰ یادآوری جدید", "🔔 یادآوری‌ها"],
        ["🗑 حذف آخرین یادداشت", "ℹ️ راهنما"],
    ],
    resize_keyboard=True
)

# Each owner's current input mode is kept in memory.
MODES = {}

def connect():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL, body TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL, body TEXT NOT NULL,
        due_at TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0
    )""")
    con.commit()
    return con

def allowed(update: Update) -> bool:
    return bool(update.effective_user and OWNER_ID and update.effective_user.id == OWNER_ID)

async def private_only(update: Update) -> bool:
    if not allowed(update):
        if update.effective_message:
            await update.effective_message.reply_text(
                "این منشی خصوصی است و فقط صاحب ربات می‌تواند از آن استفاده کند."
            )
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    await update.message.reply_text(
        "سلام! منشی دیجیتال شخصی‌ات آماده است.\nاز دکمه‌های پایین برای مدیریت کارها استفاده کن.",
        reply_markup=MENU
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    await update.message.reply_text(
        "راهنما:\n"
        "• یادداشت جدید: متن یادداشت را ارسال کن.\n"
        "• کار جدید: متن کار را ارسال کن.\n"
        "• یادآوری جدید: ابتدا متن را بنویس، سپس زمان را با قالب YYYY-MM-DD HH:MM بفرست.\n"
        "• زمان بر اساس منطقه زمانی تنظیم‌شده در TIMEZONE است.\n"
        "• برای تکمیل کار، در فهرست کارها /done شماره را بزن.\n"
        "• برای حذف یادداشت، از دکمه حذف آخرین یادداشت استفاده کن."
    )

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("روش استفاده: /done شماره")
        return
    task_id = int(context.args[0])
    with connect() as con:
        cur = con.execute(
            "UPDATE tasks SET done=1 WHERE id=? AND owner_id=?",
            (task_id, OWNER_ID)
        )
    await update.message.reply_text("کار انجام‌شده علامت خورد. ✅" if cur.rowcount else "این شماره پیدا نشد.")

async def reminders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    with connect() as con:
        rows = con.execute(
            "SELECT id, body, due_at FROM reminders WHERE owner_id=? AND sent=0 ORDER BY due_at",
            (OWNER_ID,)
        ).fetchall()
    if not rows:
        await update.message.reply_text("فعلاً یادآوری ثبت‌نشده‌ای نداری.")
        return
    text = "🔔 یادآوری‌های آینده:\n" + "\n".join(
        f"{rid}) {body} — {due}" for rid, body, due in rows
    )
    await update.message.reply_text(text)

async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ZoneInfo(TIMEZONE))
    with connect() as con:
        rows = con.execute(
            "SELECT id, owner_id, body FROM reminders WHERE sent=0 AND due_at<=?",
            (now.isoformat(timespec="minutes"),)
        ).fetchall()
        for rid, owner_id, body in rows:
            try:
                await context.bot.send_message(
                    chat_id=owner_id, text=f"⏰ یادآوری:\n{body}"
                )
                con.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
            except Exception:
                log.exception("Could not send reminder %s", rid)
        con.commit()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if text == "ℹ️ راهنما":
        await help_cmd(update, context)
        return
    if text == "📋 یادداشت‌ها":
        with connect() as con:
            rows = con.execute(
                "SELECT id, body, created_at FROM notes WHERE owner_id=? ORDER BY id DESC LIMIT 20",
                (OWNER_ID,)
            ).fetchall()
        await update.message.reply_text(
            "📝 یادداشت‌ها:\n" + ("\n".join(f"{i}) {b} ({d})" for i,b,d in rows) if rows else "هنوز یادداشتی نداری.")
        )
        return
    if text == "🗑 حذف آخرین یادداشت":
        with connect() as con:
            row = con.execute(
                "SELECT id FROM notes WHERE owner_id=? ORDER BY id DESC LIMIT 1",
                (OWNER_ID,)
            ).fetchone()
            if row:
                con.execute("DELETE FROM notes WHERE id=?", (row[0],))
        await update.message.reply_text("آخرین یادداشت حذف شد." if row else "یادداشتی برای حذف وجود ندارد.")
        return
    if text == "➕ کار جدید":
        MODES[user_id] = "task"
        await update.message.reply_text("متن کاری را که می‌خواهی ثبت شود بفرست.")
        return
    if text == "📝 یادداشت جدید":
        MODES[user_id] = "note"
        await update.message.reply_text("متن یادداشت را بفرست.")
        return
    if text == "📋 یادداشت‌ها":
        return
    if text == "✅ کارهای من":
        with connect() as con:
            rows = con.execute(
                "SELECT id, body FROM tasks WHERE owner_id=? AND done=0 ORDER BY id DESC",
                (OWNER_ID,)
            ).fetchall()
        body = "\n".join(f"{i}) {b} — تکمیل: /done {i}" for i,b in rows)
        await update.message.reply_text("📋 کارهای انجام‌نشده:\n" + (body or "همه کارها انجام شده‌اند!"))
        return
    if text == "🔔 یادآوری‌ها":
        await reminders_cmd(update, context)
        return
    if text == "⏰ یادآوری جدید":
        MODES[user_id] = "reminder_text"
        await update.message.reply_text("موضوع یادآوری را بنویس.")
        return

    mode = MODES.get(user_id)
    if mode == "note":
        with connect() as con:
            con.execute(
                "INSERT INTO notes(owner_id, body, created_at) VALUES(?,?,?)",
                (OWNER_ID, text, datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="minutes"))
            )
        MODES.pop(user_id, None)
        await update.message.reply_text("یادداشت ذخیره شد. 📝", reply_markup=MENU)
    elif mode == "task":
        with connect() as con:
            con.execute(
                "INSERT INTO tasks(owner_id, body, created_at) VALUES(?,?,?)",
                (OWNER_ID, text, datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="minutes"))
            )
        MODES.pop(user_id, None)
        await update.message.reply_text("کار ثبت شد. ✅", reply_markup=MENU)
    elif mode == "reminder_text":
        MODES[user_id] = ("reminder_time", text)
        await update.message.reply_text("حالا زمان را بفرست؛ نمونه: 2026-12-01 18:30")
    elif isinstance(mode, tuple) and mode[0] == "reminder_time":
        try:
            due = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(TIMEZONE))
            if due <= datetime.now(ZoneInfo(TIMEZONE)):
                await update.message.reply_text("زمان باید در آینده باشد. دوباره زمان را بفرست.")
                return
            body = mode[1]
            with connect() as con:
                con.execute(
                    "INSERT INTO reminders(owner_id, body, due_at) VALUES(?,?,?)",
                    (OWNER_ID, body, due.isoformat(timespec="minutes"))
                )
            MODES.pop(user_id, None)
            await update.message.reply_text("یادآوری ثبت شد. در زمان تعیین‌شده پیامت می‌دهم. ⏰", reply_markup=MENU)
        except ValueError:
            await update.message.reply_text("قالب زمان درست نیست. نمونه: 2026-12-01 18:30")
    else:
        await update.message.reply_text("از دکمه‌های منو استفاده کن یا /start را بزن.", reply_markup=MENU)

def main():
    if not BOT_TOKEN or not OWNER_ID:
        raise SystemExit("لطفاً BOT_TOKEN و OWNER_ID را در متغیرهای محیطی تنظیم کن.")
    connect()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("reminders", reminders_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(send_due_reminders, interval=30, first=10)
    log.info("Personal secretary bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
