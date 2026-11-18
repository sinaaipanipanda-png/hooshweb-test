
import os
import io
import json
import sqlite3
import zipfile
import shutil
import threading
from datetime import datetime

from flask import Flask, jsonify
from bale import (
    Bot, Message, InputFile,
    MenuKeyboardMarkup, MenuKeyboardButton
)

# =====================================
# تنظیمات اصلی
# =====================================

TOKEN = os.getenv("BALE_TOKEN", "").strip()
ADMIN_ID = 696006270

DB_PATH = "hooshwebyar.db"
DATA_DIR = "data"
FILES_DIR = os.path.join(DATA_DIR, "files")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

STUDENTS = {
    1531183616: "محمدسام قاسملو",
    1485681068: "تکین اکبری",
    604417888: "ماهیار صیادیان",
    1258198303: "رادین میرزایی گودرزی",
    2032193574: "امیرعلی شریعتی",
    1692809547: "آرتا احمدی",
}

states = {}

app = Flask(__name__)

# =====================================
# پایگاه داده
# =====================================

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            started INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS homework(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS grades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            score REAL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            path TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS points(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            kind TEXT,
            reason TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT,
            day TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            path TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS support(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            created_at TEXT,
            answered INTEGER DEFAULT 0
        );
        """)

        for uid, name in STUDENTS.items():
            con.execute(
                "INSERT OR IGNORE INTO users(user_id,name) VALUES(?,?)",
                (uid, name)
            )


def student_name(uid):
    with connect() as con:
        row = con.execute(
            "SELECT name FROM users WHERE user_id=?",
            (uid,)
        ).fetchone()

    return row["name"] if row else STUDENTS.get(uid, f"کاربر {uid}")


def get_setting(key):
    with connect() as con:
        row = con.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        ).fetchone()

    return row["value"] if row else ""


def save_setting(key, value):
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
            (key, value)
        )


def user_id(message):
    return int(message.author.user_id)


# =====================================
# صفحه‌کلیدها
# =====================================

def keyboard(rows):
    k = MenuKeyboardMarkup()

    for index, row in enumerate(rows, 1):
        for item in row:
            k.add(MenuKeyboardButton(item), row=index)

    return k


def main_menu():
    return keyboard([
        ["تکالیف جاری 📝", "ارسال تکالیف ⚡️💙"],
        ["لینک کلاس آنلاین 🧑‍💻", "لینک گروه 😁"],
        ["کارنامه 💘", "نمرات ✍️"],
        ["مثبت و منفی های کلاسی〽️", "حضور و غیاب 😇"],
        ["پشتیبانی 📞"]
    ])


def admin_menu():
    return keyboard([
        ["مدیریت تکالیف 📝", "ثبت کارنامه 📸"],
        ["ثبت نمره ✍️", "ثبت مثبت/منفی 〽️"],
        ["ثبت حضور و غیاب 😇", "تنظیم لینک‌ها 🔗"],
        ["پیام‌های پشتیبانی 📞"],
        ["دریافت فایل بکاپ 📥", "بارگزاری فایل بکاپ 📤"],
        ["فهرست دانش‌آموزان 👥"],
        ["بازگشت به منوی اصلی 🏠"]
    ])


def student_menu():
    rows = []
    names = list(STUDENTS.values())

    for i in range(0, len(names), 2):
        rows.append(names[i:i+2])

    rows.append(["لغو ❌"])
    return keyboard(rows)


# =====================================
# ابزارهای عمومی
# =====================================

async def reply(message, text, components=None):
    await message.reply(text, components=components)


async def save_file(message, prefix):
    attachment = message.attachment

    if not attachment:
        return None

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    extension = "jpg"

    if getattr(attachment, "file_name", None):
        extension = attachment.file_name.split(".")[-1]

    path = os.path.join(
        FILES_DIR,
        f"{prefix}_{stamp}.{extension}"
    )

    with open(path, "wb") as f:
        await attachment.save_to_memory(f)

    return path


async def ask_student(message, next_action):
    states[user_id(message)] = {
        "action": "select_student",
        "next": next_action
    }

    await reply(
        message,
        "دانش‌آموز موردنظر را انتخاب کنید:",
        student_menu()
    )


# =====================================
# بکاپ و بازیابی
# =====================================

def create_backup():
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(
        BACKUP_DIR,
        f"HooshwebYar_{stamp}.zip"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(DB_PATH):
            z.write(DB_PATH, "hooshwebyar.db")

        for root, dirs, files in os.walk(DATA_DIR):
            for filename in files:
                full = os.path.join(root, filename)

                if full != path:
                    z.write(full, os.path.relpath(full, "."))

    return path


def restore_backup(path):
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()

        if "hooshwebyar.db" not in names:
            raise ValueError("فایل پایگاه داده در بکاپ پیدا نشد.")

        for name in names:
            normalized = os.path.normpath(name)

            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError("فایل بکاپ معتبر نیست.")

        z.extractall(".")


# =====================================
# ارسال اطلاعات دانش‌آموز
# =====================================

async def show_homework(chat_id):
    with connect() as con:
        rows = con.execute(
            "SELECT title,body FROM homework ORDER BY id DESC"
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "فعلاً تکلیفی ثبت نشده است.")
        return

    for row in rows:
        await bot.send_message(
            chat_id,
            f"📝 {row['title']}\n\n{row['body']}"
        )


async def show_grades(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT title,score FROM grades WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز نمره‌ای ثبت نشده است.")
        return

    text = "✍️ نمرات شما:\n\n"

    for row in rows:
        text += f"📚 {row['title']}: {row['score']} از ۲۰\n"

    await bot.send_message(chat_id, text)


async def show_reports(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT path FROM reports WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز کارنامه‌ای ثبت نشده است.")
        return

    for row in rows:
        path = row["path"]

        if os.path.exists(path):
            with open(path, "rb") as f:
                await bot.send_photo(
                    chat_id,
                    InputFile(f.read()),
                    caption="💘 کارنامه شما"
                )


async def show_points(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT kind,reason FROM points WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "موردی ثبت نشده است.")
        return

    text = "〽️ مثبت و منفی‌های شما:\n\n"

    for row in rows:
        icon = "➕" if row["kind"] == "مثبت" else "➖"
        text += f"{icon} {row['kind']}: {row['reason']}\n"

    await bot.send_message(chat_id, text)


async def show_attendance(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT day,status FROM attendance WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز حضور و غیابی ثبت نشده است.")
        return

    text = "😇 وضعیت حضور و غیاب:\n\n"

    for row in rows:
        text += f"📅 {row['day']} : {row['status']}\n"

    await bot.send_message(chat_id, text)


# =====================================
# ربات بله
# =====================================

if not TOKEN:
    raise RuntimeError("BALE_TOKEN در تنظیمات Render تنظیم نشده است.")

bot = Bot(token=TOKEN)


@bot.event
async def on_ready():
    print("HOOSH WEB YAR IS ONLINE!")


@bot.event
async def on_message(message: Message):

    uid = user_id(message)
    text = (message.content or "").strip()

    name = STUDENTS.get(
        uid,
        getattr(message.author, "first_name", None) or f"کاربر {uid}"
    )

    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO users(user_id,name,started) VALUES(?,?,1)",
            (uid, name)
        )

    state = states.get(uid)

    # ---------------------------------
    # شروع
    # ---------------------------------

    if text in ["/start", "شروع"]:
        await reply(message, "*در حال بارگزاری اطلاعات...*\n*کمی صبر کنید..🌹*")
        await reply(
            message,
            "سلام 👋\n"
            "خیلی به هوش وب یار خوش اومدید!\n"
            "یکی از گزینه های زیر را انتخاب کنید 👇",
            main_menu()
        )
        return

    # ---------------------------------
    # پنل مدیر
    # ---------------------------------

    if uid == ADMIN_ID and text in ["/admin", "پنل مدیریت"]:
        states.pop(uid, None)
        await reply(message, "🛠 پنل مدیریت هوش وب یار", admin_menu())
        return

    if text == "بازگشت به منوی اصلی 🏠":
        states.pop(uid, None)
        await reply(message, "منوی اصلی:", main_menu())
        return

    if text == "لغو ❌":
        states.pop(uid, None)
        await reply(message, "عملیات لغو شد.", admin_menu() if uid == ADMIN_ID else main_menu())
        return

    # ---------------------------------
    # ادامه عملیات‌های چندمرحله‌ای
    # ---------------------------------

    if state:

        action = state["action"]

        if action == "select_student":
            target = next(
                (sid for sid, sname in STUDENTS.items() if sname == text),
                None
            )

            if target is None:
                await reply(message, "لطفاً یک نام از فهرست انتخاب کنید.", student_menu())
                return

            states[uid] = {
                "action": state["next"],
                "target": target
            }

            prompts = {
                "report": "تصویر کارنامه را ارسال کنید.",
                "grade_title": "عنوان نمره را وارد کنید:",
                "point_kind": "نوع مورد را بنویسید: مثبت یا منفی",
                "attendance": "وضعیت را بنویسید: حاضر، غایب یا تأخیر"
            }

            await reply(message, prompts[state["next"]])
            return

        if action == "report":
            path = await save_file(message, "report")

            if not path or not getattr(message, "photos", None):
                await reply(message, "لطفاً تصویر کارنامه را به‌صورت عکس ارسال کنید.")
                return

            with connect() as con:
                con.execute(
                    "INSERT INTO reports(user_id,path) VALUES(?,?)",
                    (state["target"], path)
                )

            await reply(message, f"کارنامه {student_name(state['target'])} ثبت شد. 💙", admin_menu())
            states.pop(uid, None)
            return

        if action == "grade_title":
            states[uid] = {
                "action": "grade_score",
                "target": state["target"],
                "title": text
            }

            await reply(message, "نمره را از ۲۰ وارد کنید:")
            return

        if action == "grade_score":
            try:
                score = float(text.replace("٫", ".").replace(",", "."))

                if not 0 <= score <= 20:
                    raise ValueError

            except ValueError:
                await reply(message, "نمره باید عددی بین ۰ تا ۲۰ باشد.")
                return

            with connect() as con:
                con.execute(
                    "INSERT INTO grades(user_id,title,score) VALUES(?,?,?)",
                    (state["target"], state["title"], score)
                )

            await reply(message, f"نمره برای {student_name(state['target'])} ثبت شد.", admin_menu())
            states.pop(uid, None)
            return

        if action == "point_kind":
            if text not in ["مثبت", "منفی"]:
                await reply(message, "فقط مثبت یا منفی بنویسید.")
                return

            states[uid] = {
                "action": "point_reason",
                "target": state["target"],
                "kind": text
            }

            await reply(message, "توضیح یا دلیل را وارد کنید:")
            return

        if action == "point_reason":
            with connect() as con:
                con.execute(
                    "INSERT INTO points(user_id,kind,reason) VALUES(?,?,?)",
                    (state["target"], state["kind"], text)
                )

            await reply(message, "مورد با موفقیت ثبت شد.", admin_menu())
            states.pop(uid, None)
            return

        if action == "attendance":
            if text not in ["حاضر", "غایب", "تأخیر"]:
                await reply(message, "یکی از گزینه‌های حاضر، غایب یا تأخیر را بنویسید.")
                return

            with connect() as con:
                con.execute(
                    "INSERT INTO attendance(user_id,status,day) VALUES(?,?,?)",
                    (state["target"], text, datetime.now().strftime("%Y-%m-%d"))
                )

            await reply(message, "حضور و غیاب ثبت شد.", admin_menu())
            states.pop(uid, None)
            return

        if action == "homework_title":
            states[uid] = {"action": "homework_body", "title": text}
            await reply(message, "توضیحات تکلیف را وارد کنید:")
            return

        if action == "homework_body":
            with connect() as con:
                con.execute(
                    "INSERT INTO homework(title,body) VALUES(?,?)",
                    (state["title"], text)
                )

            states.pop(uid, None)
            await reply(message, "تکلیف ثبت شد. ✅", admin_menu())
            return

        if action == "submit":
            path = await save_file(message, "submission")

            with connect() as con:
                con.execute(
                    "INSERT INTO submissions(user_id,text,path) VALUES(?,?,?)",
                    (uid, text, path)
                )

            await bot.send_message(
                ADMIN_ID,
                f"📨 تکلیف جدید\n\n"
                f"نام: {student_name(uid)}\n"
                f"شناسه: {uid}\n"
                f"متن: {text or 'فایل ارسال شده'}"
            )

            if path:
                with open(path, "rb") as f:
                    await bot.send_document(ADMIN_ID, InputFile(f.read()))

            states.pop(uid, None)
            await reply(message, "تکلیف شما برای مدیر ارسال شد. 💙", main_menu())
            return

        if action == "support":
            path = await save_file(message, "support")

            with connect() as con:
                cur = con.execute(
                    "INSERT INTO support(user_id,text) VALUES(?,?)",
                    (uid, text or "فایل پشتیبانی")
                )
                support_id = cur.lastrowid

            await bot.send_message(
                ADMIN_ID,
                f"📞 پیام پشتیبانی #{support_id}\n"
                f"نام: {student_name(uid)}\n"
                f"شناسه: {uid}\n\n{text}"
            )

            if path:
                with open(path, "rb") as f:
                    await bot.send_document(ADMIN_ID, InputFile(f.read()))

            states.pop(uid, None)
            await reply(message, "پیام شما برای پشتیبانی ارسال شد. 💙", main_menu())
            return

        if action == "class_link":
            save_setting("class_link", text)
            states.pop(uid, None)
            await reply(message, "لینک کلاس ذخیره شد.", admin_menu())
            return

        if action == "group_link":
            save_setting("group_link", text)
            states.pop(uid, None)
            await reply(message, "لینک گروه ذخیره شد.", admin_menu())
            return

        if action == "restore":
            path = await save_file(message, "backup")

            if not path or not path.lower().endswith(".zip"):
                await reply(message, "فایل ZIP بکاپ را ارسال کنید.")
                return

            try:
                restore_backup(path)
                init_db()
                states.pop(uid, None)
                await reply(message, "بازیابی بکاپ انجام شد. 💙", admin_menu())
            except Exception as error:
                await reply(message, f"خطا در بازیابی: {error}", admin_menu())

            return

        if action == "support_reply":
            try:
                support_id = int(text.split(" ", 1)[0])
                answer = text.split(" ", 1)[1]

                with connect() as con:
                    row = con.execute(
                        "SELECT user_id FROM support WHERE id=?",
                        (support_id,)
                    ).fetchone()

                if not row:
                    await reply(message, "شماره پیام پیدا نشد.")
                    return

                await bot.send_message(
                    row["user_id"],
                    "📞 پاسخ پشتیبانی:\n\n" + answer
                )

                with connect() as con:
                    con.execute(
                        "UPDATE support SET answered=1 WHERE id=?",
                        (support_id,)
                    )

                states.pop(uid, None)
                await reply(message, "پاسخ ارسال شد. ✅", admin_menu())

            except Exception:
                await reply(message, "قالب پاسخ: شماره پیام سپس متن پاسخ")
            return

    # ---------------------------------
    # امکانات مدیر
    # ---------------------------------

    if uid == ADMIN_ID:

        if text == "مدیریت تکالیف 📝":
            states[uid] = {"action": "homework_title"}
            await reply(message, "عنوان تکلیف را وارد کنید:")
            return

        if text == "ثبت کارنامه 📸":
            await ask_student(message, "report")
            return

        if text == "ثبت نمره ✍️":
            await ask_student(message, "grade_title")
            return

        if text == "ثبت مثبت/منفی 〽️":
            await ask_student(message, "point_kind")
            return

        if text == "ثبت حضور و غیاب 😇":
            await ask_student(message, "attendance")
            return

        if text == "تنظیم لینک‌ها 🔗":
            await reply(
                message,
                "برای تنظیم لینک بنویسید:\n"
                "لینک کلاس\n"
                "یا\n"
                "لینک گروه"
            )
            states[uid] = {"action": "choose_link"}
            return

        if state and state["action"] == "choose_link":
            return

        if text == "لینک کلاس":
            states[uid] = {"action": "class_link"}
            await reply(message, "لینک کلاس را ارسال کنید:")
            return

        if text == "لینک گروه":
            states[uid] = {"action": "group_link"}
            await reply(message, "لینک گروه را ارسال کنید:")
            return

        if text == "دریافت فایل بکاپ 📥":
            path = create_backup()

            with open(path, "rb") as f:
                await bot.send_document(
                    uid,
                    InputFile(f.read()),
                    caption="📦 فایل پشتیبان HooshwebYar"
                )
            return

        if text == "بارگزاری فایل بکاپ 📤":
            states[uid] = {"action": "restore"}
            await reply(message, "فایل ZIP بکاپ را ارسال کنید:")
            return

        if text == "فهرست دانش‌آموزان 👥":
            result = "\n".join(
                f"{name} — {sid}"
                for sid, name in STUDENTS.items()
            )
            await reply(message, result, admin_menu())
            return

        if text == "پیام‌های پشتیبانی 📞":
            with connect() as con:
                rows = con.execute(
                    "SELECT id,user_id,text FROM support WHERE answered=0 ORDER BY id DESC"
                ).fetchall()

            if not rows:
                await reply(message, "پیام بی‌پاسخی وجود ندارد.", admin_menu())
                return

            output = "📞 پیام‌های پشتیبانی:\n\n"

            for row in rows:
                output += (
                    f"#{row['id']} - {student_name(row['user_id'])}\n"
                    f"{row['text']}\n\n"
                )

            await reply(
                message,
                output + "برای پاسخ بنویسید: شماره پیام سپس متن پاسخ",
                admin_menu()
            )
            states[uid] = {"action": "support_reply"}
            return

    # ---------------------------------
    # منوی دانش‌آموز
    # ---------------------------------

    if text == "تکالیف جاری 📝":
        await show_homework(uid)
        return

    if text == "ارسال تکالیف ⚡️💙":
        states[uid] = {"action": "submit"}
        await reply(message, "متن یا فایل تکلیف خود را ارسال کنید:")
        return

    if text == "لینک کلاس آنلاین 🧑‍💻":
        await reply(message, get_setting("class_link") or "لینک کلاس هنوز ثبت نشده است.")
        return

    if text == "لینک گروه 😁":
        await reply(message, get_setting("group_link") or "لینک گروه هنوز ثبت نشده است.")
        return

    if text == "کارنامه 💘":
        await show_reports(uid, uid)
        return

    if text == "نمرات ✍️":
        await show_grades(uid, uid)
        return

    if text == "مثبت و منفی های کلاسی〽️":
        await show_points(uid, uid)
        return

    if text == "حضور و غیاب 😇":
        await show_attendance(uid, uid)
        return

    if text == "پشتیبانی 📞":
        states[uid] = {"action": "support"}
        await reply(message, "پیام خود را برای پشتیبانی ارسال کنید:")
        return

    if uid == ADMIN_ID:
        await reply(message, "برای ورود به پنل بنویسید: پنل مدیریت", admin_menu())
    else:
        await reply(message, "برای شروع ربات /start را بزنید.", main_menu())


# =====================================
# وب‌سایت و سلامت سرویس Render
# =====================================

@app.route("/")
def home():
    return "HOOSH WEB YAR - ONLINE"


@app.route("/health")
def health():
    return jsonify({
        "status": "online",
        "project": "HooshwebYar"
    })


# =====================================
# اجرای ربات در کنار Flask
# =====================================

def start_bot():
    bot.run()


init_db()

if TOKEN:
    threading.Thread(
        target=start_bot,
        daemon=True
    ).start()
else:
    print("ERROR: BALE_TOKEN NOT FOUND")
