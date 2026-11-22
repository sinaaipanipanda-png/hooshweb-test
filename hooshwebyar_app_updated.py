import os
import sqlite3
import zipfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from flask import Flask, jsonify
from bale import Bot, Message, InputFile, MenuKeyboardMarkup, MenuKeyboardButton

# =========================================
# تنظیمات اصلی
# =========================================
TOKEN = os.getenv("BALE_TOKEN", "").strip()
ADMIN_ID = 696006270

# این رمز را در Environment سایت Render و نه در GitHub قرار دهید.
BACKUP_ACCESS_CODE = os.getenv("BACKUP_ACCESS_CODE", "").strip()

# سه پیام یا بیشتر در یک ثانیه، یک تخلف محسوب می‌شود.
SPAM_WINDOW_SECONDS = 1.0
SPAM_MESSAGE_LIMIT = 3
SPAM_DURATIONS_MINUTES = [10, 20, 40, 80, 160, 320, 640, 1250, 1280, 1680]
spam_message_times = defaultdict(deque)

CLASS_LINK = "https://meet35312345.adobeconnect.com/hooshweb130/"
GROUP_LINK = "https://ble.ir/join/6JopirnSXz"

DB_PATH = "hooshwebyar.db"
DATA_DIR = "data"
FILES_DIR = os.path.join(DATA_DIR, "files")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# آرتا احمدی و ماهیار صیادیان عمداً در فهرست اولیه نیستند.
# اگر قبلاً در دیتابیس بوده‌اند، هنگام راه‌اندازی کاملاً حذف می‌شوند.
STUDENTS = {
    1531183616: "محمدسام قاسملو",
    1485681068: "تکین اکبری",
    1258198303: "رادین میرزایی گودرزی",
    2032193574: "امیرعلی شریعتی",
}

REMOVED_STUDENT_IDS = (1692809547, 604417888)
states = {}
app = Flask(__name__)


# =========================================
# پایگاه داده
# =========================================
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def add_column(con, table, column, definition):
    columns = [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def delete_student_files(con, uid):
    for table in ("reports", "submissions"):
        rows = con.execute(f"SELECT path FROM {table} WHERE user_id=?", (uid,)).fetchall()
        for row in rows:
            path = row["path"]
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def delete_student_completely(uid):
    if uid == ADMIN_ID:
        return
    with connect() as con:
        delete_student_files(con, uid)
        for table in ("grades", "reports", "points", "attendance", "submissions", "support", "spam_control"):
            con.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE user_id=?", (uid,))


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, name TEXT, started INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS homework(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS grades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT,
            score REAL, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT,
            path TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS points(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT,
            reason TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT,
            status TEXT, day TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT,
            path TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS support(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT,
            created_at TEXT, answered INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS session_videos(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            url TEXT NOT NULL, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS spam_control(
            user_id INTEGER PRIMARY KEY,
            strikes INTEGER NOT NULL DEFAULT 0,
            blocked_until REAL NOT NULL DEFAULT 0,
            permanent INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        """)
        add_column(con, "reports", "title", "TEXT")
        add_column(con, "attendance", "title", "TEXT")

        # حذف کامل دو دانش‌آموز درخواستی، حتی اگر در دیتابیس قدیمی وجود داشته باشند.
        for removed_id in REMOVED_STUDENT_IDS:
            delete_student_files(con, removed_id)
            for table in ("grades", "reports", "points", "attendance", "submissions", "support", "spam_control"):
                con.execute(f"DELETE FROM {table} WHERE user_id=?", (removed_id,))
            con.execute("DELETE FROM users WHERE user_id=?", (removed_id,))

        for uid, name in STUDENTS.items():
            con.execute(
                "INSERT OR IGNORE INTO users(user_id,name,started) VALUES(?,?,0)",
                (uid, name)
            )


def student_name(uid):
    with connect() as con:
        row = con.execute("SELECT name FROM users WHERE user_id=?", (uid,)).fetchone()
    return row["name"] if row else f"کاربر حذف‌شده ({uid})"


def all_students():
    with connect() as con:
        return con.execute("SELECT user_id,name FROM users WHERE user_id<>? ORDER BY name", (ADMIN_ID,)).fetchall()


def user_id(message):
    return int(message.author.user_id)


# =========================================
# صفحه‌کلیدها
# =========================================
def keyboard(rows):
    k = MenuKeyboardMarkup()
    for index, row in enumerate(rows, 1):
        for item in row:
            k.add(MenuKeyboardButton(item), row=index)
    return k


def main_menu():
    return keyboard([
        ["تکالیف جاری 📝", "ارسال تکالیف ⚡️💙"],
        ["ویدئو جلسات ضبط شده ⏺️"],
        ["لینک کلاس آنلاین 🧑‍💻", "لینک گروه 😁"],
        ["کارنامه 💘", "نمرات ✍️"],
        ["مثبت و منفی های کلاسی〽️", "حضور و غیاب 😇"],
        ["پشتیبانی 📞"]
    ])


def admin_menu():
    return keyboard([
        ["مدیریت تکالیف 📝", "مدیریت کاربران 👥"],
        ["مدیریت مثبت و منفی 〽️", "مدیریت حضور و غیاب 😇"],
        ["مدیریت کارنامه‌ها 📸", "ثبت نمره ✍️"],
        ["مدیریت نمره‌ها 📊", "مدیریت ویدیو های جلسات ضبط شده ⏺️", "مدیریت ضداسپم 🛡"],
        ["پیام‌های پشتیبانی 📞", "مدیریت ضداسپم 🛡"],
        ["دریافت فایل بکاپ 📥", "بارگزاری فایل بکاپ 📤"],
        ["بازگشت به منوی اصلی 🏠"]
    ])


def homework_menu():
    return keyboard([["ثبت تکلیف جدید ➕"], ["مشاهده تکالیف 📋"], ["بازگشت به پنل مدیریت 🛠"]])


def users_menu():
    return keyboard([["افزودن دانش‌آموز ➕"], ["حذف دانش‌آموز 🗑"], ["فهرست دانش‌آموزان 👥"], ["بازگشت به پنل مدیریت 🛠"]])


def points_menu():
    return keyboard([["ثبت مثبت یا منفی ➕"], ["مشاهده مثبت و منفی‌ها 📋"], ["حذف مثبت یا منفی 🗑"], ["بازگشت به پنل مدیریت 🛠"]])


def attendance_menu():
    return keyboard([["ثبت حضور و غیاب ➕"], ["مشاهده حضور و غیاب 📋"], ["حذف حضور و غیاب 🗑"], ["بازگشت به پنل مدیریت 🛠"]])


def reports_menu():
    return keyboard([["ثبت کارنامه جدید ➕"], ["مشاهده کارنامه‌ها 📋"], ["ویرایش عنوان کارنامه ✏️"], ["حذف کارنامه 🗑"], ["بازگشت به پنل مدیریت 🛠"]])


def videos_menu():
    return keyboard([["افزودن ویدئو جلسه ➕"], ["مشاهده ویدئوها 📋"], ["ویرایش ویدئو ✏️"], ["حذف ویدئو 🗑"], ["بازگشت به پنل مدیریت 🛠"]])


def student_menu():
    names = [r["name"] for r in all_students()]
    rows = [names[i:i + 2] for i in range(0, len(names), 2)]
    rows.append(["لغو ❌"])
    return keyboard(rows)


def back_menu():
    return keyboard([["لغو ❌"], ["بازگشت به پنل مدیریت 🛠"]])


def attendance_status_menu():
    return keyboard([["حاضر ✅", "غایب ❌", "تأخیر ⏰"], ["لغو ❌"]])


async def reply(message, text, components=None):
    await message.reply(text, components=components)


# =========================================
# فایل‌ها
# =========================================
async def save_file(message, prefix):
    attachment = message.attachment
    if not attachment:
        return None
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = getattr(attachment, "file_name", None) or ""
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"
    extension = "".join(c for c in extension if c.isalnum())[:8] or "bin"
    path = os.path.join(FILES_DIR, f"{prefix}_{stamp}.{extension}")
    with open(path, "wb") as f:
        await attachment.save_to_memory(f)
    return path


async def send_file(chat_id, path, caption=""):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            await bot.send_document(chat_id, InputFile(f.read()), caption=caption)


# =========================================
# انتخاب دانش‌آموز
# =========================================
async def ask_student(message, action, extra=None):
    states[user_id(message)] = {"action": "select_student", "next": action, "extra": extra or {}}
    await reply(message, "دانش‌آموز موردنظر را انتخاب کنید:", student_menu())


def selected_student(text):
    for row in all_students():
        if row["name"] == text:
            return int(row["user_id"])
    return None


# =========================================
# نمایش اطلاعات
# =========================================
async def show_homework(chat_id):
    with connect() as con:
        rows = con.execute("SELECT * FROM homework ORDER BY id DESC").fetchall()
    if not rows:
        await bot.send_message(chat_id, "فعلاً تکلیفی ثبت نشده است.")
        return
    for row in rows:
        await bot.send_message(chat_id, f"📝 تکلیف شماره {row['id']}\nعنوان: {row['title']}\n\n{row['body']}")


async def show_grades(chat_id, uid):
    with connect() as con:
        rows = con.execute("SELECT * FROM grades WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    if not rows:
        await bot.send_message(chat_id, "هنوز نمره‌ای ثبت نشده است.")
        return
    result = "✍️ نمرات شما:\n\n"
    for r in rows:
        result += f"شماره: {r['id']}\n📚 {r['title']}\nنمره: {r['score']} از ۲۰\n\n"
    await bot.send_message(chat_id, result)


async def show_reports(chat_id, uid):
    with connect() as con:
        rows = con.execute("SELECT * FROM reports WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    if not rows:
        await bot.send_message(chat_id, "هنوز کارنامه‌ای ثبت نشده است.")
        return
    for row in rows:
        path = row["path"]
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                await bot.send_photo(chat_id, InputFile(f.read()), caption=f"💘 {row['title'] or 'کارنامه شما'}")


async def show_points(chat_id, uid):
    with connect() as con:
        rows = con.execute("SELECT * FROM points WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    if not rows:
        await bot.send_message(chat_id, "موردی ثبت نشده است.")
        return
    result = f"〽️ مثبت و منفی‌های {student_name(uid)}:\n\n"
    for r in rows:
        icon = "➕" if r["kind"] == "مثبت" else "➖"
        result += f"شماره: {r['id']}\n{icon} {r['kind']}: {r['reason']}\n\n"
    await bot.send_message(chat_id, result)


async def show_attendance(chat_id, uid):
    with connect() as con:
        rows = con.execute("SELECT * FROM attendance WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    if not rows:
        await bot.send_message(chat_id, "هنوز حضور و غیابی ثبت نشده است.")
        return
    result = f"😇 حضور و غیاب {student_name(uid)}:\n\n"
    for r in rows:
        result += f"شماره: {r['id']}\nعنوان: {r['title'] or 'بدون عنوان'}\nوضعیت: {r['status']}\nتاریخ: {r['day']}\n\n"
    await bot.send_message(chat_id, result)


async def show_videos(chat_id):
    with connect() as con:
        rows = con.execute("SELECT * FROM session_videos ORDER BY id DESC").fetchall()
    if not rows:
        await bot.send_message(chat_id, "هنوز ویدئویی ثبت نشده است.")
        return
    for r in rows:
        await bot.send_message(chat_id, f"⏺️ جلسه شماره {r['id']}\nعنوان: {r['title']}\nلینک دانلود:\n{r['url']}")


# =========================================
# مدیریت ضداسپم
# =========================================
def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes or not parts:
        parts.append(f"{minutes} دقیقه")
    return " و ".join(parts)


def get_spam_record(uid):
    with connect() as con:
        return con.execute("SELECT * FROM spam_control WHERE user_id=?", (uid,)).fetchone()


def spam_status_text():
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM spam_control WHERE strikes>0 ORDER BY strikes DESC, user_id"
        ).fetchall()
    if not rows:
        return "هنوز تخلف اسپمی ثبت نشده است."
    now_ts = time.time()
    out = ["🛡 وضعیت ضداسپم کاربران:\n"]
    for r in rows:
        status = "مسدودی کامل" if r["permanent"] else (
            "محدود" if r["blocked_until"] > now_ts else "آزاد"
        )
        next_step = (
            "مسدودی کامل" if r["strikes"] >= 10
            else format_duration(SPAM_DURATIONS_MINUTES[r["strikes"]] * 60)
        )
        remain = (
            format_duration(r["blocked_until"] - now_ts)
            if r["blocked_until"] > now_ts else "—"
        )
        out.append(
            f"نام: {student_name(r['user_id'])}\nآیدی: {r['user_id']}\n"
            f"تخلف: {r['strikes']}\nوضعیت: {status}\n"
            f"زمان باقی‌مانده: {remain}\nمجازات دفعه بعد: {next_step}\n"
        )
    return "\n".join(out)


def register_spam_violation(uid):
    with connect() as con:
        row = con.execute(
            "SELECT strikes FROM spam_control WHERE user_id=?", (uid,)
        ).fetchone()
        strikes = (row["strikes"] if row else 0) + 1
        if strikes >= 11:
            con.execute(
                "INSERT INTO spam_control(user_id,strikes,blocked_until,permanent,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "strikes=excluded.strikes,blocked_until=0,permanent=1,updated_at=excluded.updated_at",
                (uid, strikes, 0, 1, now())
            )
            return strikes, None, True
        minutes = SPAM_DURATIONS_MINUTES[strikes - 1]
        until = time.time() + minutes * 60
        con.execute(
            "INSERT INTO spam_control(user_id,strikes,blocked_until,permanent,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "strikes=excluded.strikes,blocked_until=excluded.blocked_until,"
            "permanent=0,updated_at=excluded.updated_at",
            (uid, strikes, until, 0, now())
        )
        return strikes, minutes, False


def check_spam(uid):
    if uid == ADMIN_ID:
        return False, None
    rec = get_spam_record(uid)
    now_ts = time.time()
    if rec and rec["permanent"]:
        return True, "⛔ دسترسی شما به ربات به‌طور کامل مسدود شده است. رفع مسدودی فقط توسط مدیر ربات انجام می‌شود."
    if rec and rec["blocked_until"] > now_ts:
        return True, None

    q = spam_message_times[uid]
    while q and now_ts - q[0] > SPAM_WINDOW_SECONDS:
        q.popleft()
    q.append(now_ts)
    if len(q) >= SPAM_MESSAGE_LIMIT:
        q.clear()
        strikes, minutes, permanent = register_spam_violation(uid)
        if permanent:
            notice = "⛔ به دلیل تکرار تخلف اسپم، دسترسی شما به ربات به‌طور کامل مسدود شد. فقط مدیر ربات می‌تواند مسدودی را بردارد."
        else:
            next_text = (
                "مسدودی کامل" if strikes >= 10
                else format_duration(SPAM_DURATIONS_MINUTES[strikes] * 60)
            )
            notice = (
                f"⚠️ به‌دلیل ارسال ۳ پیام یا بیشتر در یک ثانیه، پیام‌های شما نادیده گرفته می‌شوند.\n"
                f"تخلف شماره: {strikes}\n"
                f"مدت غیرفعال بودن ربات: {format_duration(minutes * 60)}\n"
                f"مجازات دفعه بعد: {next_text}"
            )
        return True, notice
    return False, None


# =========================================
# بکاپ
# =========================================
def create_backup():
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"HooshwebYar_{stamp}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(DB_PATH):
            z.write(DB_PATH, DB_PATH)
        for root, dirs, files in os.walk(DATA_DIR):
            for filename in files:
                full = os.path.join(root, filename)
                if full != path:
                    z.write(full, os.path.relpath(full, "."))
    return path


def restore_backup(path):
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        if DB_PATH not in names:
            raise ValueError("فایل پایگاه داده در بکاپ وجود ندارد.")
        for name in names:
            normalized = os.path.normpath(name)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError("فایل بکاپ معتبر نیست.")
        z.extractall(".")


# =========================================
# ربات
# =========================================
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

    if uid in REMOVED_STUDENT_IDS:
        await reply(message, "دسترسی این حساب به ربات غیرفعال شده است.")
        return

    blocked, spam_notice = check_spam(uid)
    if blocked:
        if spam_notice:
            await reply(message, spam_notice)
        return

    name = STUDENTS.get(uid, getattr(message.author, "first_name", None) or f"کاربر {uid}")

    with connect() as con:
        # برای افراد حذف‌شده دوباره حساب نساز.
        if uid not in REMOVED_STUDENT_IDS:
            con.execute("INSERT OR IGNORE INTO users(user_id,name,started) VALUES(?,?,1)", (uid, name))
            con.execute("UPDATE users SET started=1 WHERE user_id=?", (uid,))

    state = states.get(uid)

    if text in ["/start", "شروع"]:
        states.pop(uid, None)
        await reply(message, "*در حال بارگزاری اطلاعات...*\n*کمی صبر کنید..🌹*")
        await reply(message, "سلام 👋\nخیلی به هوش وب یار خوش اومدید!\nیکی از گزینه‌های زیر را انتخاب کنید 👇",
                    admin_menu() if uid == ADMIN_ID else main_menu())
        return

    if uid == ADMIN_ID and text in ["/admin", "پنل مدیریت"]:
        states.pop(uid, None)
        await reply(message, "🛠 پنل مدیریت هوش وب یار", admin_menu())
        return

    if text == "بازگشت به پنل مدیریت 🛠" and uid == ADMIN_ID:
        states.pop(uid, None)
        await reply(message, "🛠 پنل مدیریت", admin_menu())
        return

    if text == "بازگشت به منوی اصلی 🏠":
        states.pop(uid, None)
        await reply(message, "منوی اصلی:", main_menu())
        return

    if text == "لغو ❌":
        states.pop(uid, None)
        await reply(message, "عملیات لغو شد.", admin_menu() if uid == ADMIN_ID else main_menu())
        return

    # منوهای اصلی را حتی اگر state باز مانده باشد، پردازش کن.
    if uid == ADMIN_ID:
        admin_menu_texts = {
            "مدیریت تکالیف 📝", "مدیریت کاربران 👥", "مدیریت مثبت و منفی 〽️",
            "مدیریت حضور و غیاب 😇", "مدیریت کارنامه‌ها 📸",
            "مدیریت نمره‌ها 📊", "مدیریت ویدیو های جلسات ضبط شده ⏺️"
        }
        if text in admin_menu_texts:
            states.pop(uid, None)
            menus = {
                "مدیریت تکالیف 📝": ("مدیریت تکالیف:", homework_menu()),
                "مدیریت کاربران 👥": ("مدیریت کاربران:", users_menu()),
                "مدیریت مثبت و منفی 〽️": ("مدیریت مثبت و منفی:", points_menu()),
                "مدیریت حضور و غیاب 😇": ("مدیریت حضور و غیاب:", attendance_menu()),
                "مدیریت کارنامه‌ها 📸": ("مدیریت کارنامه‌ها:", reports_menu()),
                "مدیریت نمره‌ها 📊": ("مدیریت نمره‌ها:", grades_menu()),
                "مدیریت ویدیو های جلسات ضبط شده ⏺️": ("مدیریت ویدئو جلسات ضبط‌شده:", videos_menu()),
"مدیریت ضداسپم 🛡": ("🛡 مدیریت ضداسپم\nبرای مشاهده وضعیت: وضعیت ضداسپم\nبرای رفع مسدودی: رفع مسدودی 123456789", admin_menu())
            }
            caption, menu = menus[text]
            await reply(message, caption, menu)
            return

    # دستورات مدیریتی تیکت‌ها و ضداسپم
    if uid == ADMIN_ID and text.startswith("حذف پشتیبانی"):
        parts = text.split()[2:]
        if not parts:
            await reply(message, "نمونه: حذف پشتیبانی 6 یا حذف پشتیبانی 1 2 3 4 5 6 7 8 9", admin_menu())
            return
        try:
            ticket_ids = sorted(set(int(x) for x in parts))
            if any(x <= 0 for x in ticket_ids):
                raise ValueError
            with connect() as con:
                placeholders = ",".join("?" for _ in ticket_ids)
                cur = con.execute(
                    f"DELETE FROM support WHERE id IN ({placeholders})", ticket_ids
                )
                deleted = cur.rowcount
            await reply(
                message,
                f"🗑 تعداد {deleted} تیکت حذف شد.\nشماره‌ها: {', '.join(map(str, ticket_ids))}",
                admin_menu()
            )
        except ValueError:
            await reply(message, "شماره تیکت‌ها باید عدد صحیح مثبت باشند.", admin_menu())
        return

    if uid == ADMIN_ID and text == "وضعیت ضداسپم":
        await reply(message, spam_status_text(), admin_menu())
        return

    if uid == ADMIN_ID and text.startswith("رفع مسدودی "):
        try:
            target_uid = int(text.split(maxsplit=2)[2])
            with connect() as con:
                cur = con.execute(
                    "UPDATE spam_control SET blocked_until=0, permanent=0, updated_at=? WHERE user_id=?",
                    (now(), target_uid)
                )
            spam_message_times.pop(target_uid, None)
            answer = (
                "✅ مسدودی برداشته شد؛ سابقه تخلف‌ها حفظ شد."
                if cur.rowcount else "برای این آیدی سابقه محدودیت ثبت نشده است."
            )
            await reply(message, answer, admin_menu())
        except (ValueError, IndexError):
            await reply(message, "قالب درست: رفع مسدودی 123456789", admin_menu())
        return

    # =====================================
    # ادامه عملیات چندمرحله‌ای
    # =====================================
    if state:
        action = state["action"]

        if action in ("backup_code", "restore_code"):
            if not BACKUP_ACCESS_CODE:
                states.pop(uid, None)
                await reply(message, "کد امنیتی BACKUP_ACCESS_CODE در تنظیمات Render ثبت نشده است.", admin_menu())
                return
            if text != BACKUP_ACCESS_CODE:
                await reply(message, "❌ کد اشتباه است. دوباره وارد کنید یا لغو بزنید.", back_menu())
                return
            if action == "backup_code":
                states.pop(uid, None)
                path = create_backup()
                await send_file(uid, path, "📦 فایل پشتیبان هوش وب‌یار")
            else:
                states[uid] = {"action": "restore"}
                await reply(message, "✅ کد تأیید شد. حالا فایل ZIP بکاپ را ارسال کنید:", back_menu())
            return

        if action == "select_student":
            target = selected_student(text)
            if target is None:
                await reply(message, "لطفاً یک دانش‌آموز از فهرست انتخاب کنید.", student_menu())
                return
            next_action = state["next"]
            extra = state.get("extra", {})
            states[uid] = {"action": next_action, "target": target, "extra": extra}
            prompts = {
                "report_title": "عنوان کارنامه را وارد کنید:",
                "grade_title": "عنوان نمره را وارد کنید:",
                "point_kind": "نوع مورد را انتخاب کنید: مثبت یا منفی",
                "view_points": "اطلاعات در حال نمایش است."
            }
            if next_action == "view_points":
                await show_points(uid, target)
                states.pop(uid, None)
                await reply(message, "عملیات تمام شد.", points_menu())
                return
            await reply(message, prompts.get(next_action, "ادامه عملیات:"),
                        keyboard([["مثبت ➕", "منفی ➖"], ["لغو ❌"]]) if next_action == "point_kind" else None)
            return

        # تکالیف
        if action == "homework_title":
            states[uid] = {"action": "homework_body", "title": text}
            await reply(message, "متن و توضیحات تکلیف را وارد کنید:")
            return
        if action == "homework_body":
            with connect() as con:
                con.execute("INSERT INTO homework(title,body,created_at) VALUES(?,?,?)", (state["title"], text, now()))
            states.pop(uid, None)
            await reply(message, "تکلیف با موفقیت ثبت شد. ✅", homework_menu())
            return
        if action == "homework_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره تکلیف را به‌صورت عدد وارد کنید.")
                return
            with connect() as con:
                row = con.execute("SELECT * FROM homework WHERE id=?", (item_id,)).fetchone()
            if not row:
                await reply(message, "این تکلیف پیدا نشد.")
                return
            states[uid] = {"action": "homework_edit_title", "item_id": item_id}
            await reply(message, "عنوان جدید تکلیف را وارد کنید:")
            return
        if action == "homework_edit_title":
            states[uid].update({"action": "homework_edit_body", "title": text})
            await reply(message, "متن جدید تکلیف را وارد کنید:")
            return
        if action == "homework_edit_body":
            with connect() as con:
                con.execute("UPDATE homework SET title=?,body=? WHERE id=?", (state["title"], text, state["item_id"]))
            states.pop(uid, None)
            await reply(message, "تکلیف ویرایش شد. ✅", homework_menu())
            return
        if action == "homework_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره تکلیف را وارد کنید.")
                return
            with connect() as con:
                cur = con.execute("DELETE FROM homework WHERE id=?", (item_id,))
            states.pop(uid, None)
            await reply(message, "تکلیف حذف شد. 🗑" if cur.rowcount else "تکلیف پیدا نشد.", homework_menu())
            return

        # کاربران
        if action == "add_student_name":
            states[uid] = {"action": "add_student_id", "name": text}
            await reply(message, "آیدی عددی دانش‌آموز را وارد کنید:")
            return
        if action == "add_student_id":
            try:
                new_id = int(text)
                if new_id <= 0 or new_id in REMOVED_STUDENT_IDS:
                    raise ValueError
            except ValueError:
                await reply(message, "آیدی باید معتبر باشد و این شناسه قابل افزودن نیست.")
                return
            with connect() as con:
                if con.execute("SELECT 1 FROM users WHERE user_id=?", (new_id,)).fetchone():
                    await reply(message, "این آیدی قبلاً ثبت شده است.")
                    return
                con.execute("INSERT INTO users(user_id,name,started) VALUES(?,?,0)", (new_id, state["name"]))
            states.pop(uid, None)
            await reply(message, "دانش‌آموز اضافه شد. ✅", users_menu())
            return
        if action == "delete_student_id":
            try:
                target = int(text)
            except ValueError:
                await reply(message, "آیدی عددی دانش‌آموز را وارد کنید.")
                return
            if target == ADMIN_ID:
                await reply(message, "امکان حذف مدیر اصلی وجود ندارد.")
                return
            if not any(int(r["user_id"]) == target for r in all_students()):
                await reply(message, "دانش‌آموزی با این آیدی پیدا نشد.")
                return
            delete_student_completely(target)
            states.pop(uid, None)
            await reply(message, "دانش‌آموز و تمام اطلاعات مرتبط با او حذف شدند. 🗑", users_menu())
            return

        # کارنامه
        if action == "report_title":
            states[uid] = {"action": "report_photo", "target": state["target"], "title": text}
            await reply(message, "حالا تصویر کارنامه را به‌صورت عکس ارسال کنید:")
            return
        if action == "report_photo":
            if not getattr(message, "photos", None):
                await reply(message, "لطفاً تصویر کارنامه را به‌صورت عکس ارسال کنید.")
                return
            path = await save_file(message, "report")
            if not path:
                await reply(message, "دریافت تصویر ناموفق بود. دوباره ارسال کنید.")
                return
            with connect() as con:
                con.execute("INSERT INTO reports(user_id,title,path,created_at) VALUES(?,?,?,?)",
                            (state["target"], state["title"], path, now()))
            states.pop(uid, None)
            await reply(message, "کارنامه ثبت شد. 💙", reports_menu())
            return
        if action == "report_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره کارنامه را وارد کنید.")
                return
            with connect() as con:
                row = con.execute("SELECT id FROM reports WHERE id=?", (item_id,)).fetchone()
            if not row:
                await reply(message, "کارنامه پیدا نشد.")
                return
            states[uid] = {"action": "report_edit_title", "item_id": item_id}
            await reply(message, "عنوان جدید کارنامه را وارد کنید:")
            return
        if action == "report_edit_title":
            with connect() as con:
                con.execute("UPDATE reports SET title=? WHERE id=?", (text, state["item_id"]))
            states.pop(uid, None)
            await reply(message, "عنوان کارنامه ویرایش شد. ✅", reports_menu())
            return
        if action == "report_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره کارنامه را وارد کنید.")
                return
            with connect() as con:
                row = con.execute("SELECT path FROM reports WHERE id=?", (item_id,)).fetchone()
                if row:
                    con.execute("DELETE FROM reports WHERE id=?", (item_id,))
                    if row["path"] and os.path.exists(row["path"]):
                        try:
                            os.remove(row["path"])
                        except OSError:
                            pass
            states.pop(uid, None)
            await reply(message, "کارنامه حذف شد. 🗑" if row else "کارنامه پیدا نشد.", reports_menu())
            return

        # نمره‌ها
        if action == "grade_title":
            states[uid] = {"action": "grade_score", "target": state["target"], "title": text}
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
                con.execute("INSERT INTO grades(user_id,title,score,created_at) VALUES(?,?,?,?)",
                            (state["target"], state["title"], score, now()))
            states.pop(uid, None)
            await reply(message, "نمره ثبت شد. ✅", admin_menu())
            return
        if action == "grade_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره نمره را وارد کنید.")
                return
            with connect() as con:
                row = con.execute("SELECT * FROM grades WHERE id=?", (item_id,)).fetchone()
            if not row:
                await reply(message, "نمره پیدا نشد.")
                return
            states[uid] = {"action": "grade_edit_title", "item_id": item_id}
            await reply(message, "عنوان جدید نمره را وارد کنید:")
            return
        if action == "grade_edit_title":
            states[uid].update({"action": "grade_edit_score", "title": text})
            await reply(message, "نمره جدید را از ۲۰ وارد کنید:")
            return
        if action == "grade_edit_score":
            try:
                score = float(text.replace("٫", ".").replace(",", "."))
                if not 0 <= score <= 20:
                    raise ValueError
            except ValueError:
                await reply(message, "نمره باید بین ۰ تا ۲۰ باشد.")
                return
            with connect() as con:
                con.execute("UPDATE grades SET title=?,score=? WHERE id=?",
                            (state["title"], score, state["item_id"]))
            states.pop(uid, None)
            await reply(message, "نمره ویرایش شد. ✅", grades_menu())
            return
        if action == "grade_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره نمره را وارد کنید.")
                return
            with connect() as con:
                cur = con.execute("DELETE FROM grades WHERE id=?", (item_id,))
            states.pop(uid, None)
            await reply(message, "نمره حذف شد. 🗑" if cur.rowcount else "نمره پیدا نشد.", grades_menu())
            return

        # مثبت و منفی
        if action == "point_kind":
            normalized = text.replace("➕", "").replace("➖", "").strip()
            if normalized not in ("مثبت", "منفی"):
                await reply(message, "نوع مورد را با دکمه مثبت یا منفی انتخاب کنید.",
                            keyboard([["مثبت ➕", "منفی ➖"], ["لغو ❌"]]))
                return
            states[uid] = {"action": "point_reason", "target": state["target"], "kind": normalized}
            await reply(message, "دلیل یا توضیح را وارد کنید:")
            return
        if action == "point_reason":
            with connect() as con:
                con.execute("INSERT INTO points(user_id,kind,reason,created_at) VALUES(?,?,?,?)",
                            (state["target"], state["kind"], text, now()))
            states.pop(uid, None)
            await reply(message, "مورد ثبت شد. ✅", points_menu())
            return
        if action == "point_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره مورد را وارد کنید.")
                return
            with connect() as con:
                cur = con.execute("DELETE FROM points WHERE id=?", (item_id,))
            states.pop(uid, None)
            await reply(message, "مورد حذف شد. 🗑" if cur.rowcount else "مورد پیدا نشد.", points_menu())
            return

        # حضور و غیاب یک جلسه برای تمام دانش‌آموزان
        if action == "attendance_title":
            students = all_students()
            if not students:
                states.pop(uid, None)
                await reply(message, "فهرست دانش‌آموزان خالی است.", attendance_menu())
                return
            states[uid] = {
                "action": "attendance_batch_status",
                "title": text,
                "students": [int(r["user_id"]) for r in students],
                "names": [r["name"] for r in students],
                "index": 0,
                "records": []
            }
            first_name = states[uid]["names"][0]
            await reply(message, f"وضعیت {first_name} را انتخاب کنید:", attendance_status_menu())
            return
        if action == "attendance_batch_status":
            statuses = {"حاضر": "حاضر", "حاضر ✅": "حاضر", "غایب": "غایب", "غایب ❌": "غایب",
                        "تأخیر": "تأخیر", "تأخیر ⏰": "تأخیر"}
            status_value = statuses.get(text)
            if not status_value:
                await reply(message, "یکی از گزینه‌های حاضر، غایب یا تأخیر را انتخاب کنید:", attendance_status_menu())
                return
            state["records"].append((state["students"][state["index"]], status_value))
            state["index"] += 1
            if state["index"] < len(state["students"]):
                next_name = state["names"][state["index"]]
                await reply(message, f"وضعیت {next_name} را انتخاب کنید:", attendance_status_menu())
                return
            with connect() as con:
                today = datetime.now().strftime("%Y-%m-%d")
                for target, status_value in state["records"]:
                    con.execute("INSERT INTO attendance(user_id,title,status,day,created_at) VALUES(?,?,?,?,?)",
                                (target, state["title"], status_value, today, now()))
            total = len(state["records"])
            states.pop(uid, None)
            await reply(message, f"حضور و غیاب تمام {total} دانش‌آموز ثبت شد. ✅", attendance_menu())
            return
        if action == "attendance_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره رکورد را وارد کنید.")
                return
            with connect() as con:
                cur = con.execute("DELETE FROM attendance WHERE id=?", (item_id,))
            states.pop(uid, None)
            await reply(message, "رکورد حذف شد. 🗑" if cur.rowcount else "رکورد پیدا نشد.", attendance_menu())
            return

        # ویدئوهای جلسات ضبط‌شده
        if action == "video_title":
            states[uid] = {"action": "video_url", "title": text}
            await reply(message, "لینک دانلود مستقیم یا لینک اشتراک‌گذاری ویدئو را ارسال کنید:")
            return
        if action == "video_url":
            if not text.startswith(("https://", "http://")):
                await reply(message, "لطفاً یک لینک معتبر که با http:// یا https:// شروع می‌شود وارد کنید.")
                return
            with connect() as con:
                con.execute("INSERT INTO session_videos(title,url,created_at) VALUES(?,?,?)", (state["title"], text, now()))
            states.pop(uid, None)
            await reply(message, "ویدئوی جلسه ثبت شد. ⏺️", videos_menu())
            return
        if action == "video_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره ویدئو را وارد کنید.")
                return
            with connect() as con:
                row = con.execute("SELECT * FROM session_videos WHERE id=?", (item_id,)).fetchone()
            if not row:
                await reply(message, "ویدئو پیدا نشد.")
                return
            states[uid] = {"action": "video_edit_title", "item_id": item_id}
            await reply(message, "عنوان جدید را وارد کنید:")
            return
        if action == "video_edit_title":
            states[uid].update({"action": "video_edit_url", "title": text})
            await reply(message, "لینک جدید ویدئو را وارد کنید:")
            return
        if action == "video_edit_url":
            if not text.startswith(("https://", "http://")):
                await reply(message, "لینک باید با http:// یا https:// شروع شود.")
                return
            with connect() as con:
                con.execute("UPDATE session_videos SET title=?,url=? WHERE id=?",
                            (state["title"], text, state["item_id"]))
            states.pop(uid, None)
            await reply(message, "ویدئو ویرایش شد. ✅", videos_menu())
            return
        if action == "video_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره ویدئو را وارد کنید.")
                return
            with connect() as con:
                cur = con.execute("DELETE FROM session_videos WHERE id=?", (item_id,))
            states.pop(uid, None)
            await reply(message, "ویدئو حذف شد. 🗑" if cur.rowcount else "ویدئو پیدا نشد.", videos_menu())
            return

        # ثبت و حذف حضور و غیاب
        # تکلیف ارسالی دانش‌آموز
        if action == "submit":
            path = await save_file(message, "submission")
            with connect() as con:
                con.execute("INSERT INTO submissions(user_id,text,path,created_at) VALUES(?,?,?,?)",
                            (uid, text, path, now()))
            await bot.send_message(ADMIN_ID, f"📨 تکلیف جدید\nنام: {student_name(uid)}\nآیدی: {uid}\nمتن: {text or 'فایل ارسال شده'}")
            if path:
                await send_file(ADMIN_ID, path, "📎 فایل تکلیف")
            states.pop(uid, None)
            await reply(message, "تکلیف شما برای مدیر ارسال شد. 💙", main_menu())
            return

        # پشتیبانی
        if action == "support":
            path = await save_file(message, "support")
            with connect() as con:
                cur = con.execute("INSERT INTO support(user_id,text,created_at) VALUES(?,?,?)",
                                  (uid, text or "فایل پشتیبانی", now()))
                support_id = cur.lastrowid
            await bot.send_message(ADMIN_ID, f"📞 پیام پشتیبانی شماره {support_id}\nنام: {student_name(uid)}\nآیدی: {uid}\n\n{text or 'فایل ارسال شده'}")
            if path:
                await send_file(ADMIN_ID, path, "📎 فایل پشتیبانی")
            states.pop(uid, None)
            await reply(message, "پیام شما برای پشتیبانی ارسال شد. 💙", main_menu())
            return

        if action == "support_reply":
            try:
                support_id_text, answer = text.split(" ", 1)
                support_id = int(support_id_text)
                with connect() as con:
                    row = con.execute("SELECT user_id FROM support WHERE id=?", (support_id,)).fetchone()
                if not row:
                    await reply(message, "شماره پیام پیدا نشد.")
                    return
                await bot.send_message(row["user_id"], "📞 پاسخ پشتیبانی:\n\n" + answer)
                with connect() as con:
                    con.execute("UPDATE support SET answered=1 WHERE id=?", (support_id,))
                states.pop(uid, None)
                await reply(message, "پاسخ ارسال شد. ✅", admin_menu())
            except Exception:
                await reply(message, "قالب پاسخ: شماره پیام سپس متن پاسخ")
            return

        if action == "restore":
            path = await save_file(message, "backup")
            if not path or not zipfile.is_zipfile(path):
                await reply(message, "لطفاً فایل ZIP معتبر ارسال کنید.")
                return
            try:
                restore_backup(path)
                init_db()
                states.pop(uid, None)
                await reply(message, "بازیابی بکاپ انجام شد. 💙", admin_menu())
            except Exception as error:
                await reply(message, f"خطا در بازیابی: {error}", admin_menu())
            return

    # =====================================
    # امکانات مدیر
    # =====================================
    if uid == ADMIN_ID:
        # مدیریت تکالیف
        if text == "ثبت تکلیف جدید ➕":
            states[uid] = {"action": "homework_title"}
            await reply(message, "عنوان تکلیف را وارد کنید:", back_menu())
            return
        if text == "مشاهده تکالیف 📋":
            await show_homework(uid)
            await reply(message, "برای ویرایش بنویسید «ویرایش تکلیف» و برای حذف «حذف تکلیف».", homework_menu())
            states[uid] = {"action": "homework_manage_choice"}
            return
        if text in ("ویرایش تکلیف", "حذف تکلیف"):
            states[uid] = {"action": "homework_edit_id" if text == "ویرایش تکلیف" else "homework_delete_id"}
            await reply(message, "شماره تکلیف را وارد کنید:", back_menu())
            return

        # کاربران
        if text == "افزودن دانش‌آموز ➕":
            states[uid] = {"action": "add_student_name"}
            await reply(message, "نام و نام خانوادگی دانش‌آموز را وارد کنید:", back_menu())
            return
        if text == "حذف دانش‌آموز 🗑":
            states[uid] = {"action": "delete_student_id"}
            await reply(message, "آیدی عددی دانش‌آموز را وارد کنید:", back_menu())
            return
        if text == "فهرست دانش‌آموزان 👥":
            result = "👥 فهرست دانش‌آموزان:\n\n" + "".join(f"{r['name']} — {r['user_id']}\n" for r in all_students())
            await reply(message, result, users_menu())
            return

        # مثبت و منفی
        if text == "ثبت مثبت یا منفی ➕":
            await ask_student(message, "point_kind")
            return
        if text == "مشاهده مثبت و منفی‌ها 📋":
            await ask_student(message, "view_points")
            return
        if text == "حذف مثبت یا منفی 🗑":
            with connect() as con:
                rows = con.execute("SELECT * FROM points ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "موردی برای حذف وجود ندارد.", points_menu())
                return
            result = "〽️ فهرست موارد:\n\n"
            for r in rows:
                result += f"شماره: {r['id']} | {student_name(r['user_id'])} | {r['kind']} | {r['reason']}\n"
            states[uid] = {"action": "point_delete_id"}
            await reply(message, result + "\nشماره موردی را که می‌خواهید حذف کنید وارد کنید:", back_menu())
            return

        # حضور و غیاب
        if text == "ثبت حضور و غیاب ➕":
            states[uid] = {"action": "attendance_title"}
            await reply(message, "ابتدا عنوان یا موضوع جلسه را وارد کنید:", back_menu())
            return
        if text == "مشاهده حضور و غیاب 📋":
            with connect() as con:
                rows = con.execute("SELECT * FROM attendance ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "هنوز رکوردی ثبت نشده است.", attendance_menu())
                return
            result = "😇 فهرست حضور و غیاب‌ها:\n\n"
            for r in rows:
                result += f"شماره: {r['id']}\nدانش‌آموز: {student_name(r['user_id'])}\nعنوان: {r['title'] or 'بدون عنوان'}\nوضعیت: {r['status']}\nتاریخ: {r['day']}\n\n"
            await reply(message, result, attendance_menu())
            return
        if text == "حذف حضور و غیاب 🗑":
            with connect() as con:
                rows = con.execute("SELECT * FROM attendance ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "رکوردی برای حذف وجود ندارد.", attendance_menu())
                return
            result = "فهرست رکوردها:\n\n" + "".join(
                f"شماره: {r['id']} | {student_name(r['user_id'])} | {r['title']} | {r['status']}\n" for r in rows
            )
            states[uid] = {"action": "attendance_delete_id"}
            await reply(message, result + "\nشماره رکورد برای حذف را وارد کنید:", back_menu())
            return

        # کارنامه‌ها
        if text == "ثبت کارنامه جدید ➕":
            await ask_student(message, "report_title")
            return
        if text == "مشاهده کارنامه‌ها 📋":
            with connect() as con:
                rows = con.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "هنوز کارنامه‌ای ثبت نشده است.", reports_menu())
                return
            result = "📸 فهرست کارنامه‌ها:\n\n"
            for r in rows:
                result += f"شماره: {r['id']}\nدانش‌آموز: {student_name(r['user_id'])}\nعنوان: {r['title'] or 'بدون عنوان'}\n\n"
            await reply(message, result, reports_menu())
            return
        if text == "ویرایش عنوان کارنامه ✏️":
            states[uid] = {"action": "report_edit_id"}
            await reply(message, "شماره کارنامه را وارد کنید:", back_menu())
            return
        if text == "حذف کارنامه 🗑":
            states[uid] = {"action": "report_delete_id"}
            await reply(message, "شماره کارنامه را وارد کنید:", back_menu())
            return

        # نمره‌ها
        if text == "ثبت نمره ✍️":
            await ask_student(message, "grade_title")
            return
        if text == "مشاهده همه نمره‌ها 📋":
            await show_all_grades(uid)
            await reply(message, "مدیریت نمره‌ها:", grades_menu())
            return
        if text == "ویرایش نمره ✏️":
            with connect() as con:
                rows = con.execute("SELECT * FROM grades ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "نمره‌ای برای ویرایش وجود ندارد.", grades_menu())
                return
            result = grades_list_text(rows)
            states[uid] = {"action": "grade_edit_id"}
            await reply(message, result + "\nشماره نمره برای ویرایش را وارد کنید:", back_menu())
            return
        if text == "حذف نمره 🗑":
            with connect() as con:
                rows = con.execute("SELECT * FROM grades ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "نمره‌ای برای حذف وجود ندارد.", grades_menu())
                return
            states[uid] = {"action": "grade_delete_id"}
            await reply(message, grades_list_text(rows) + "\nشماره نمره برای حذف را وارد کنید:", back_menu())
            return

        # ویدئوها
        if text == "افزودن ویدئو جلسه ➕":
            states[uid] = {"action": "video_title"}
            await reply(message, "عنوان جلسه را وارد کنید:", back_menu())
            return
        if text == "مشاهده ویدئوها 📋":
            await show_videos(uid)
            await reply(message, "مدیریت ویدئوها:", videos_menu())
            return
        if text == "ویرایش ویدئو ✏️":
            with connect() as con:
                rows = con.execute("SELECT * FROM session_videos ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "ویدئویی برای ویرایش وجود ندارد.", videos_menu())
                return
            result = videos_list_text(rows)
            states[uid] = {"action": "video_edit_id"}
            await reply(message, result + "\nشماره ویدئو برای ویرایش را وارد کنید:", back_menu())
            return
        if text == "حذف ویدئو 🗑":
            with connect() as con:
                rows = con.execute("SELECT * FROM session_videos ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "ویدئویی برای حذف وجود ندارد.", videos_menu())
                return
            result = videos_list_text(rows)
            states[uid] = {"action": "video_delete_id"}
            await reply(message, result + "\nشماره ویدئو برای حذف را وارد کنید:", back_menu())
            return

        # پشتیبانی
        if text == "پیام‌های پشتیبانی 📞":
            with connect() as con:
                rows = con.execute("SELECT * FROM support ORDER BY id DESC").fetchall()
            if not rows:
                await reply(message, "هنوز تیکتی ثبت نشده است.", admin_menu())
                return
            result = "📞 فهرست تیکت‌های پشتیبانی:\n\n"
            for r in rows:
                status = "پاسخ داده شده" if r["answered"] else "بی‌پاسخ"
                result += f"شماره: {r['id']}\nنام: {student_name(r['user_id'])}\nوضعیت: {status}\nمتن: {r['text']}\n\n"
            states[uid] = {"action": "support_reply"}
            await reply(message, result + "برای پاسخ: شماره تیکت سپس متن پاسخ\nبرای حذف تکی: حذف پشتیبانی 6\nبرای حذف چندتایی: حذف پشتیبانی 1 2 3 4 5 6 7 8 9", back_menu())
            return

        # بکاپ
        if text == "دریافت فایل بکاپ 📥":
            states[uid] = {"action": "backup_code"}
            await reply(message, "🔐 کد امنیتی دریافت بکاپ را وارد کنید:", back_menu())
            return
        if text == "بارگزاری فایل بکاپ 📤":
            states[uid] = {"action": "restore_code"}
            await reply(message, "🔐 برای بازیابی، ابتدا کد امنیتی را وارد کنید:", back_menu())
            return

    # =====================================
    # امکانات دانش‌آموز
    # =====================================
    if text == "تکالیف جاری 📝":
        await show_homework(uid)
        return
    if text == "ارسال تکالیف ⚡️💙":
        states[uid] = {"action": "submit"}
        await reply(message, "متن یا فایل تکلیف خود را ارسال کنید:")
        return
    if text == "ویدئو جلسات ضبط شده ⏺️":
        await show_videos(uid)
        return
    if text == "لینک کلاس آنلاین 🧑‍💻":
        await reply(message, "🧑‍💻 لینک کلاس آنلاین:\n" + CLASS_LINK)
        return
    if text == "لینک گروه 😁":
        await reply(message, "😁 لینک گروه کلاس:\n" + GROUP_LINK)
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


# =========================================
# توابع منوی نمرات
# =========================================
def grades_menu():
    return keyboard([["مشاهده همه نمره‌ها 📋"], ["ویرایش نمره ✏️"], ["حذف نمره 🗑"], ["بازگشت به پنل مدیریت 🛠"]])


def grades_list_text(rows):
    result = "📊 فهرست نمره‌ها:\n\n"
    for r in rows:
        result += f"شماره: {r['id']}\nدانش‌آموز: {student_name(r['user_id'])}\nعنوان: {r['title']}\nنمره: {r['score']} از ۲۰\n\n"
    return result


async def show_all_grades(chat_id):
    with connect() as con:
        rows = con.execute("SELECT * FROM grades ORDER BY id DESC").fetchall()
    await bot.send_message(chat_id, grades_list_text(rows) if rows else "هنوز نمره‌ای ثبت نشده است.")


def videos_list_text(rows):
    return "⏺️ فهرست ویدئوهای جلسات:\n\n" + "".join(
        f"شماره: {r['id']}\nعنوان: {r['title']}\nلینک: {r['url']}\n\n" for r in rows
    )


# =========================================
# وب‌سایت Render
# =========================================
@app.route("/")
def home():
    return "HOOSH WEB YAR - ONLINE"


@app.route("/health")
def health():
    return jsonify({"status": "online", "project": "HooshwebYar"})


# =========================================
# اجرای ربات
# =========================================
def start_bot():
    bot.run()


init_db()
threading.Thread(target=start_bot, daemon=True).start()
