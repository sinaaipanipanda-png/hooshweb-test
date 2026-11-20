
import os
import sqlite3
import zipfile
import threading
from datetime import datetime

from flask import Flask, jsonify
from bale import Bot, Message, InputFile, MenuKeyboardMarkup, MenuKeyboardButton

# =========================================
# تنظیمات اصلی
# =========================================

TOKEN = os.getenv("BALE_TOKEN", "").strip()
ADMIN_ID = 696006270

CLASS_LINK = "https://meet35312345.adobeconnect.com/hooshweb130/"
GROUP_LINK = "https://ble.ir/join/6JopirnSXz"

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

# =========================================
# پایگاه داده
# =========================================

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def add_column(con, table, column, definition):
    columns = [
        row["name"]
        for row in con.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    if column not in columns:
        con.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            started INTEGER DEFAULT 0
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
            title TEXT,
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
            title TEXT,
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

        # سازگاری با اطلاعات نسخه قبلی
        add_column(con, "reports", "title", "TEXT")
        add_column(con, "attendance", "title", "TEXT")

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

    if row:
        return row["name"]

    return STUDENTS.get(uid, f"کاربر {uid}")


def all_students():
    with connect() as con:
        return con.execute(
            "SELECT user_id,name FROM users ORDER BY name"
        ).fetchall()


def user_id(message):
    return int(message.author.user_id)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
        ["پیام‌های پشتیبانی 📞"],
        ["دریافت فایل بکاپ 📥", "بارگزاری فایل بکاپ 📤"],
        ["بازگشت به منوی اصلی 🏠"]
    ])


def homework_menu():
    return keyboard([
        ["ثبت تکلیف جدید ➕"],
        ["مشاهده تکالیف 📋"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


def users_menu():
    return keyboard([
        ["افزودن دانش‌آموز ➕"],
        ["حذف دانش‌آموز 🗑"],
        ["فهرست دانش‌آموزان 👥"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


def points_menu():
    return keyboard([
        ["مشاهده مثبت و منفی‌ها 📋"],
        ["حذف مثبت یا منفی 🗑"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


def attendance_menu():
    return keyboard([
        ["ثبت حضور و غیاب ➕"],
        ["مشاهده حضور و غیاب 📋"],
        ["حذف حضور و غیاب 🗑"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


def reports_menu():
    return keyboard([
        ["ثبت کارنامه جدید ➕"],
        ["مشاهده کارنامه‌ها 📋"],
        ["ویرایش عنوان کارنامه ✏️"],
        ["حذف کارنامه 🗑"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


def student_menu():
    names = [row["name"] for row in all_students()]
    rows = []

    for i in range(0, len(names), 2):
        rows.append(names[i:i + 2])

    rows.append(["لغو ❌"])
    return keyboard(rows)


def back_menu():
    return keyboard([
        ["لغو ❌"],
        ["بازگشت به پنل مدیریت 🛠"]
    ])


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

    path = os.path.join(
        FILES_DIR,
        f"{prefix}_{stamp}.{extension}"
    )

    with open(path, "wb") as f:
        await attachment.save_to_memory(f)

    return path


async def send_file(chat_id, path, caption=""):
    if not path or not os.path.exists(path):
        return

    with open(path, "rb") as f:
        await bot.send_document(
            chat_id,
            InputFile(f.read()),
            caption=caption
        )


# =========================================
# انتخاب دانش‌آموز
# =========================================

async def ask_student(message, action, extra=None):
    states[user_id(message)] = {
        "action": "select_student",
        "next": action,
        "extra": extra or {}
    }

    await reply(
        message,
        "دانش‌آموز موردنظر را انتخاب کنید:",
        student_menu()
    )


def selected_student(text):
    for row in all_students():
        if row["name"] == text:
            return int(row["user_id"])
    return None


# =========================================
# نمایش اطلاعات دانش‌آموز
# =========================================

async def show_homework(chat_id):
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM homework ORDER BY id DESC"
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "فعلاً تکلیفی ثبت نشده است.")
        return

    for row in rows:
        await bot.send_message(
            chat_id,
            f"📝 تکلیف شماره {row['id']}\n"
            f"عنوان: {row['title']}\n\n"
            f"{row['body']}"
        )


async def show_grades(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM grades WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز نمره‌ای ثبت نشده است.")
        return

    text = "✍️ نمرات شما:\n\n"
    for row in rows:
        text += (
            f"📚 {row['title']}\n"
            f"نمره: {row['score']} از ۲۰\n\n"
        )

    await bot.send_message(chat_id, text)


async def show_reports(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM reports WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز کارنامه‌ای ثبت نشده است.")
        return

    for row in rows:
        path = row["path"]
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                await bot.send_photo(
                    chat_id,
                    InputFile(f.read()),
                    caption=f"💘 {row['title'] or 'کارنامه شما'}"
                )


async def show_points(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM points WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "موردی ثبت نشده است.")
        return

    text = f"〽️ مثبت و منفی‌های {student_name(uid)}:\n\n"
    for row in rows:
        icon = "➕" if row["kind"] == "مثبت" else "➖"
        text += (
            f"شماره: {row['id']}\n"
            f"{icon} {row['kind']}: {row['reason']}\n\n"
        )

    await bot.send_message(chat_id, text)


async def show_attendance(chat_id, uid):
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM attendance WHERE user_id=? ORDER BY id DESC",
            (uid,)
        ).fetchall()

    if not rows:
        await bot.send_message(chat_id, "هنوز حضور و غیابی ثبت نشده است.")
        return

    text = f"😇 حضور و غیاب {student_name(uid)}:\n\n"
    for row in rows:
        text += (
            f"شماره: {row['id']}\n"
            f"عنوان: {row['title'] or 'بدون عنوان'}\n"
            f"وضعیت: {row['status']}\n"
            f"تاریخ: {row['day']}\n\n"
        )

    await bot.send_message(chat_id, text)


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
# حذف کامل دانش‌آموز
# =========================================

def delete_student_completely(uid):
    with connect() as con:
        report_rows = con.execute(
            "SELECT path FROM reports WHERE user_id=?",
            (uid,)
        ).fetchall()

        submission_rows = con.execute(
            "SELECT path FROM submissions WHERE user_id=?",
            (uid,)
        ).fetchall()

        for row in report_rows + submission_rows:
            path = row["path"]
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

        for table in (
            "grades",
            "reports",
            "points",
            "attendance",
            "submissions",
            "support"
        ):
            con.execute(
                f"DELETE FROM {table} WHERE user_id=?",
                (uid,)
            )

        con.execute("DELETE FROM users WHERE user_id=?", (uid,))


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

    name = STUDENTS.get(
        uid,
        getattr(message.author, "first_name", None) or f"کاربر {uid}"
    )

    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(user_id,name,started) VALUES(?,?,1)",
            (uid, name)
        )
        con.execute(
            "UPDATE users SET started=1 WHERE user_id=?",
            (uid,)
        )

    state = states.get(uid)

    # شروع
    if text in ["/start", "شروع"]:
        states.pop(uid, None)
        await reply(
            message,
            "*در حال بارگزاری اطلاعات...*\n*کمی صبر کنید..🌹*"
        )
        await reply(
            message,
            "سلام 👋\n"
            "خیلی به هوش وب یار خوش اومدید!\n"
            "یکی از گزینه‌های زیر را انتخاب کنید 👇",
            admin_menu() if uid == ADMIN_ID else main_menu()
        )
        return

    # پنل مدیریت
    if uid == ADMIN_ID and text in ["/admin", "پنل مدیریت"]:
        states.pop(uid, None)
        await reply(message, "🛠 پنل مدیریت هوش وب یار", admin_menu())
        return

    if text == "بازگشت به پنل مدیریت 🛠":
        states.pop(uid, None)
        await reply(message, "🛠 پنل مدیریت", admin_menu())
        return

    if text == "بازگشت به منوی اصلی 🏠":
        states.pop(uid, None)
        await reply(message, "منوی اصلی:", main_menu())
        return

    if text == "لغو ❌":
        states.pop(uid, None)
        await reply(
            message,
            "عملیات لغو شد.",
            admin_menu() if uid == ADMIN_ID else main_menu()
        )
        return

    # =====================================
    # ادامه عملیات چندمرحله‌ای
    # =====================================

    if state:
        action = state["action"]

        if action == "select_student":
            target = selected_student(text)

            if target is None:
                await reply(message, "لطفاً یک دانش‌آموز از فهرست انتخاب کنید.", student_menu())
                return

            next_action = state["next"]
            extra = state.get("extra", {})

            states[uid] = {
                "action": next_action,
                "target": target,
                "extra": extra
            }

            prompts = {
                "report_title": "عنوان کارنامه را وارد کنید:",
                "grade_title": "عنوان نمره را وارد کنید:",
                "point_kind": "نوع مورد را بنویسید: مثبت یا منفی",
                "attendance_status": "وضعیت را بنویسید: حاضر، غایب یا تأخیر",
                "view_points": "اطلاعات در حال نمایش است."
            }

            if next_action == "view_points":
                await show_points(uid, target)
                states.pop(uid, None)
                await reply(message, "عملیات تمام شد.", points_menu())
                return

            await reply(message, prompts.get(next_action, "ادامه عملیات:"))
            return

        # ثبت تکلیف
        if action == "homework_title":
            states[uid] = {"action": "homework_body", "title": text}
            await reply(message, "متن و توضیحات تکلیف را وارد کنید:")
            return

        if action == "homework_body":
            with connect() as con:
                con.execute(
                    "INSERT INTO homework(title,body,created_at) VALUES(?,?,?)",
                    (state["title"], text, now())
                )

            states.pop(uid, None)
            await reply(message, "تکلیف با موفقیت ثبت شد. ✅", homework_menu())
            return

        # ویرایش تکلیف
        if action == "homework_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره تکلیف را به‌صورت عدد وارد کنید.")
                return

            with connect() as con:
                row = con.execute(
                    "SELECT * FROM homework WHERE id=?",
                    (item_id,)
                ).fetchone()

            if not row:
                await reply(message, "این تکلیف پیدا نشد.")
                return

            states[uid] = {
                "action": "homework_edit_title",
                "item_id": item_id
            }
            await reply(message, "عنوان جدید تکلیف را وارد کنید:")
            return

        if action == "homework_edit_title":
            states[uid]["title"] = text
            states[uid]["action"] = "homework_edit_body"
            await reply(message, "متن جدید تکلیف را وارد کنید:")
            return

        if action == "homework_edit_body":
            with connect() as con:
                con.execute(
                    "UPDATE homework SET title=?,body=? WHERE id=?",
                    (state["title"], text, state["item_id"])
                )

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
                cur = con.execute(
                    "DELETE FROM homework WHERE id=?",
                    (item_id,)
                )

            states.pop(uid, None)
            await reply(
                message,
                "تکلیف حذف شد. 🗑" if cur.rowcount else "تکلیف پیدا نشد.",
                homework_menu()
            )
            return

        # افزودن دانش‌آموز
        if action == "add_student_name":
            states[uid] = {
                "action": "add_student_id",
                "name": text
            }
            await reply(message, "آیدی عددی دانش‌آموز را وارد کنید:")
            return

        if action == "add_student_id":
            try:
                new_id = int(text)
                if new_id <= 0:
                    raise ValueError
            except ValueError:
                await reply(message, "آیدی باید یک عدد معتبر باشد.")
                return

            with connect() as con:
                exists = con.execute(
                    "SELECT user_id FROM users WHERE user_id=?",
                    (new_id,)
                ).fetchone()

                if exists:
                    await reply(message, "این آیدی قبلاً ثبت شده است.")
                    return

                con.execute(
                    "INSERT INTO users(user_id,name,started) VALUES(?,?,0)",
                    (new_id, state["name"])
                )

            states.pop(uid, None)
            await reply(message, "دانش‌آموز اضافه شد. ✅", users_menu())
            return

        # حذف دانش‌آموز
        if action == "delete_student_id":
            try:
                target = int(text)
            except ValueError:
                await reply(message, "آیدی عددی دانش‌آموز را وارد کنید.")
                return

            if target == ADMIN_ID:
                await reply(message, "امکان حذف مدیر اصلی وجود ندارد.")
                return

            exists = any(
                int(row["user_id"]) == target
                for row in all_students()
            )

            if not exists:
                await reply(message, "دانش‌آموزی با این آیدی پیدا نشد.")
                return

            delete_student_completely(target)
            states.pop(uid, None)
            await reply(
                message,
                "دانش‌آموز و تمام اطلاعات مرتبط با او حذف شدند. 🗑",
                users_menu()
            )
            return

        # ثبت کارنامه
        if action == "report_title":
            states[uid] = {
                "action": "report_photo",
                "target": state["target"],
                "title": text
            }
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
                con.execute(
                    "INSERT INTO reports(user_id,title,path,created_at) VALUES(?,?,?,?)",
                    (state["target"], state["title"], path, now())
                )

            states.pop(uid, None)
            await reply(message, "کارنامه ثبت شد. 💙", reports_menu())
            return

        # ویرایش عنوان کارنامه
        if action == "report_edit_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره کارنامه را وارد کنید.")
                return

            with connect() as con:
                row = con.execute(
                    "SELECT id FROM reports WHERE id=?",
                    (item_id,)
                ).fetchone()

            if not row:
                await reply(message, "کارنامه پیدا نشد.")
                return

            states[uid] = {
                "action": "report_edit_title",
                "item_id": item_id
            }
            await reply(message, "عنوان جدید کارنامه را وارد کنید:")
            return

        if action == "report_edit_title":
            with connect() as con:
                con.execute(
                    "UPDATE reports SET title=? WHERE id=?",
                    (text, state["item_id"])
                )

            states.pop(uid, None)
            await reply(message, "عنوان کارنامه ویرایش شد. ✅", reports_menu())
            return

        # حذف کارنامه
        if action == "report_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره کارنامه را وارد کنید.")
                return

            with connect() as con:
                row = con.execute(
                    "SELECT path FROM reports WHERE id=?",
                    (item_id,)
                ).fetchone()

                if row:
                    path = row["path"]
                    con.execute("DELETE FROM reports WHERE id=?", (item_id,))
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass

            states.pop(uid, None)
            await reply(
                message,
                "کارنامه حذف شد. 🗑" if row else "کارنامه پیدا نشد.",
                reports_menu()
            )
            return

        # ثبت نمره
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
                    "INSERT INTO grades(user_id,title,score,created_at) VALUES(?,?,?,?)",
                    (state["target"], state["title"], score, now())
                )

            states.pop(uid, None)
            await reply(message, "نمره ثبت شد. ✅", admin_menu())
            return

        # ثبت مثبت و منفی
        if action == "point_kind":
            if text not in ["مثبت", "منفی"]:
                await reply(message, "فقط «مثبت» یا «منفی» بنویسید.")
                return

            states[uid] = {
                "action": "point_reason",
                "target": state["target"],
                "kind": text
            }
            await reply(message, "دلیل یا توضیح را وارد کنید:")
            return

        if action == "point_reason":
            with connect() as con:
                con.execute(
                    "INSERT INTO points(user_id,kind,reason,created_at) VALUES(?,?,?,?)",
                    (state["target"], state["kind"], text, now())
                )

            states.pop(uid, None)
            await reply(message, "مورد ثبت شد. ✅", points_menu())
            return

        # حذف مثبت یا منفی
        if action == "point_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره مورد را وارد کنید.")
                return

            with connect() as con:
                cur = con.execute(
                    "DELETE FROM points WHERE id=?",
                    (item_id,)
                )

            states.pop(uid, None)
            await reply(
                message,
                "مورد حذف شد. 🗑" if cur.rowcount else "مورد پیدا نشد.",
                points_menu()
            )
            return

        # حضور و غیاب: اول عنوان
        if action == "attendance_title":
            states[uid] = {
                "action": "attendance_select",
                "title": text
            }
            await reply(message, "دانش‌آموز موردنظر را انتخاب کنید:", student_menu())
            return

        if action == "attendance_select":
            target = selected_student(text)
            if target is None:
                await reply(message, "از فهرست دانش‌آموزان انتخاب کنید.", student_menu())
                return

            states[uid] = {
                "action": "attendance_status",
                "target": target,
                "title": state["title"]
            }
            await reply(message, "وضعیت را بنویسید: حاضر، غایب یا تأخیر")
            return

        if action == "attendance_status":
            if text not in ["حاضر", "غایب", "تأخیر"]:
                await reply(message, "یکی از گزینه‌های حاضر، غایب یا تأخیر را بنویسید.")
                return

            with connect() as con:
                con.execute(
                    "INSERT INTO attendance(user_id,title,status,day,created_at) VALUES(?,?,?,?,?)",
                    (
                        state["target"],
                        state["title"],
                        text,
                        datetime.now().strftime("%Y-%m-%d"),
                        now()
                    )
                )

            states.pop(uid, None)
            await reply(message, "حضور و غیاب ثبت شد. ✅", attendance_menu())
            return

        # حذف حضور و غیاب
        if action == "attendance_delete_id":
            try:
                item_id = int(text)
            except ValueError:
                await reply(message, "شماره رکورد را وارد کنید.")
                return

            with connect() as con:
                cur = con.execute(
                    "DELETE FROM attendance WHERE id=?",
                    (item_id,)
                )

            states.pop(uid, None)
            await reply(
                message,
                "رکورد حذف شد. 🗑" if cur.rowcount else "رکورد پیدا نشد.",
                attendance_menu()
            )
            return

        # ارسال تکلیف توسط دانش‌آموز
        if action == "submit":
            path = await save_file(message, "submission")

            with connect() as con:
                con.execute(
                    "INSERT INTO submissions(user_id,text,path,created_at) VALUES(?,?,?,?)",
                    (uid, text, path, now())
                )

            await bot.send_message(
                ADMIN_ID,
                f"📨 تکلیف جدید\n"
                f"نام: {student_name(uid)}\n"
                f"آیدی: {uid}\n"
                f"متن: {text or 'فایل ارسال شده'}"
            )

            if path:
                await send_file(ADMIN_ID, path, "📎 فایل تکلیف")

            states.pop(uid, None)
            await reply(message, "تکلیف شما برای مدیر ارسال شد. 💙", main_menu())
            return

        # پشتیبانی
        if action == "support":
            path = await save_file(message, "support")

            with connect() as con:
                cur = con.execute(
                    "INSERT INTO support(user_id,text,created_at) VALUES(?,?,?)",
                    (uid, text or "فایل پشتیبانی", now())
                )
                support_id = cur.lastrowid

            await bot.send_message(
                ADMIN_ID,
                f"📞 پیام پشتیبانی شماره {support_id}\n"
                f"نام: {student_name(uid)}\n"
                f"آیدی: {uid}\n\n{text}"
            )

            if path:
                await send_file(ADMIN_ID, path, "📎 فایل پشتیبانی")

            states.pop(uid, None)
            await reply(message, "پیام شما برای پشتیبانی ارسال شد. 💙", main_menu())
            return

        # پاسخ پشتیبانی
        if action == "support_reply":
            try:
                support_id_text, answer = text.split(" ", 1)
                support_id = int(support_id_text)

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

        # بازیابی بکاپ
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

        # منوهای مدیریت
        if text == "مدیریت تکالیف 📝":
            states.pop(uid, None)
            await reply(message, "مدیریت تکالیف:", homework_menu())
            return

        if text == "مدیریت کاربران 👥":
            states.pop(uid, None)
            await reply(message, "مدیریت کاربران:", users_menu())
            return

        if text == "مدیریت مثبت و منفی 〽️":
            states.pop(uid, None)
            await reply(message, "مدیریت مثبت و منفی:", points_menu())
            return

        if text == "مدیریت حضور و غیاب 😇":
            states.pop(uid, None)
            await reply(message, "مدیریت حضور و غیاب:", attendance_menu())
            return

        if text == "مدیریت کارنامه‌ها 📸":
            states.pop(uid, None)
            await reply(message, "مدیریت کارنامه‌ها:", reports_menu())
            return

        # تکالیف
        if text == "ثبت تکلیف جدید ➕":
            states[uid] = {"action": "homework_title"}
            await reply(message, "عنوان تکلیف را وارد کنید:", back_menu())
            return

        if text == "مشاهده تکالیف 📋":
            await show_homework(uid)
            await reply(
                message,
                "برای ویرایش، شماره تکلیف را بنویسید: ویرایش تکلیف\n"
                "برای حذف، بنویسید: حذف تکلیف",
                homework_menu()
            )
            states[uid] = {"action": "homework_manage_choice"}
            return

        if text == "ویرایش تکلیف":
            states[uid] = {"action": "homework_edit_id"}
            await reply(message, "شماره تکلیف موردنظر را وارد کنید:", back_menu())
            return

        if text == "حذف تکلیف":
            states[uid] = {"action": "homework_delete_id"}
            await reply(message, "شماره تکلیف موردنظر برای حذف را وارد کنید:", back_menu())
            return

        # کاربران
        if text == "افزودن دانش‌آموز ➕":
            states[uid] = {"action": "add_student_name"}
            await reply(message, "نام و نام خانوادگی دانش‌آموز را وارد کنید:", back_menu())
            return

        if text == "حذف دانش‌آموز 🗑":
            states[uid] = {"action": "delete_student_id"}
            await reply(message, "آیدی عددی دانش‌آموزی را که می‌خواهید حذف کنید وارد کنید:", back_menu())
            return

        if text == "فهرست دانش‌آموزان 👥":
            rows = all_students()
            result = "👥 فهرست دانش‌آموزان:\n\n"
            for row in rows:
                result += f"{row['name']} — {row['user_id']}\n"

            await reply(message, result, users_menu())
            return

        # مثبت و منفی
        if text == "مشاهده مثبت و منفی‌ها 📋":
            await ask_student(message, "view_points")
            return

        if text == "حذف مثبت یا منفی 🗑":
            states[uid] = {"action": "point_delete_id"}
            await reply(
                message,
                "ابتدا فهرست مثبت و منفی‌ها را از بخش مشاهده ببینید.\n"
                "سپس شماره موردی را که می‌خواهید حذف کنید وارد کنید:",
                back_menu()
            )
            return

        # حضور و غیاب
        if text == "ثبت حضور و غیاب ➕":
            states[uid] = {"action": "attendance_title"}
            await reply(message, "ابتدا عنوان حضور و غیاب را وارد کنید:", back_menu())
            return

        if text == "مشاهده حضور و غیاب 📋":
            with connect() as con:
                rows = con.execute(
                    "SELECT * FROM attendance ORDER BY id DESC"
                ).fetchall()

            if not rows:
                await reply(message, "هنوز رکوردی ثبت نشده است.", attendance_menu())
                return

            result = "😇 فهرست حضور و غیاب‌ها:\n\n"
            for row in rows:
                result += (
                    f"شماره: {row['id']}\n"
                    f"دانش‌آموز: {student_name(row['user_id'])}\n"
                    f"عنوان: {row['title'] or 'بدون عنوان'}\n"
                    f"وضعیت: {row['status']}\n"
                    f"تاریخ: {row['day']}\n\n"
                )

            await reply(message, result, attendance_menu())
            return

        if text == "حذف حضور و غیاب 🗑":
            states[uid] = {"action": "attendance_delete_id"}
            await reply(message, "شماره رکورد حضور و غیاب را وارد کنید:", back_menu())
            return

        # کارنامه‌ها
        if text == "ثبت کارنامه جدید ➕":
            await ask_student(message, "report_title")
            return

        if text == "مشاهده کارنامه‌ها 📋":
            with connect() as con:
                rows = con.execute(
                    "SELECT * FROM reports ORDER BY id DESC"
                ).fetchall()

            if not rows:
                await reply(message, "هنوز کارنامه‌ای ثبت نشده است.", reports_menu())
                return

            result = "📸 فهرست کارنامه‌ها:\n\n"
            for row in rows:
                result += (
                    f"شماره: {row['id']}\n"
                    f"دانش‌آموز: {student_name(row['user_id'])}\n"
                    f"عنوان: {row['title'] or 'بدون عنوان'}\n\n"
                )

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

        # ثبت نمره
        if text == "ثبت نمره ✍️":
            await ask_student(message, "grade_title")
            return

        # پشتیبانی
        if text == "پیام‌های پشتیبانی 📞":
            with connect() as con:
                rows = con.execute(
                    "SELECT * FROM support WHERE answered=0 ORDER BY id DESC"
                ).fetchall()

            if not rows:
                await reply(message, "پیام بی‌پاسخی وجود ندارد.", admin_menu())
                return

            result = "📞 پیام‌های پشتیبانی:\n\n"
            for row in rows:
                result += (
                    f"شماره: {row['id']}\n"
                    f"نام: {student_name(row['user_id'])}\n"
                    f"متن: {row['text']}\n\n"
                )

            states[uid] = {"action": "support_reply"}
            await reply(
                message,
                result + "برای پاسخ بنویسید: شماره پیام سپس متن پاسخ",
                back_menu()
            )
            return

        # بکاپ
        if text == "دریافت فایل بکاپ 📥":
            path = create_backup()
            await send_file(uid, path, "📦 فایل پشتیبان هوش وب یار")
            return

        if text == "بارگزاری فایل بکاپ 📤":
            states[uid] = {"action": "restore"}
            await reply(message, "فایل ZIP بکاپ را ارسال کنید:", back_menu())
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
# وب‌سایت Render
# =========================================

@app.route("/")
def home():
    return "HOOSH WEB YAR - ONLINE"


@app.route("/health")
def health():
    return jsonify({
        "status": "online",
        "project": "HooshwebYar"
    })


# =========================================
# اجرای ربات
# =========================================

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
