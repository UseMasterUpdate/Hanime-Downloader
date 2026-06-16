"""
╔══════════════════════════════════════════════════════════════╗
║       🔥  HAnime Downloader Bot  —  bot.py                  ║
║  Single-file · MongoDB · Premium · Admin · ForceSub · UPI   ║
╚══════════════════════════════════════════════════════════════╝

Required env vars:
  BOT_TOKEN        — Telegram bot token
  API_ID           — Telegram API ID (my.telegram.org)
  API_HASH         — Telegram API Hash
  MONGO_URI        — MongoDB connection string
  OWNER_ID         — Your Telegram user ID  (int)
  LOG_CHANNEL      — Channel ID for logs    (int, e.g. -100xxx)
  FSUB_CHANNEL     — Force-sub channel      (@username or -100xxx), blank = off
  API_BASE         — HF Space API base URL
  START_IMAGE_URL  — Banner image shown on /start  (direct URL, optional)
  UPI_ID           — Your UPI ID shown in payment screen  (e.g. kunal@upi)
  UPI_QR_URL       — Direct URL to your UPI QR code image (optional)
  ADMIN_USERNAME   — Telegram username of admin for payment contact (e.g. @yourusername)
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import os, re, asyncio, aiohttp, random, logging, html
from datetime import datetime, timedelta
from pathlib import Path

from pyrogram import Client, filters, enums, idle
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import (
    FloodWait, UserIsBlocked, InputUserDeactivated, UserNotParticipant,
    MessageNotModified
)
from motor.motor_asyncio import AsyncIOMotorClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ CONFIG ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN       = os.getenv("BOT_TOKEN",       "8818099946:AAFRnMbQ0FbQ-K-CDrJ9lMXkN-FskeIu-7s")
API_ID          = int(os.getenv("API_ID",      "24114514"))
API_HASH        = os.getenv("API_HASH",        "f05df583dec661a2b8039733e1c94529")
MONGO_URI       = os.getenv("MONGO_URI",       "mongodb+srv://Random_Writer:mukeshkipinki29019@cluster0.eesi7xj.mongodb.net/?appName=Cluster0")
OWNER_ID        = int(os.getenv("OWNER_ID",   "8426629771"))
LOG_CHANNEL     = int(os.getenv("LOG_CHANNEL", "-1004393605304"))
FSUB_CHANNEL    = os.getenv("FSUB_CHANNEL",   "-1003595155674")          # blank = disabled
API_BASE        = os.getenv("API_BASE",        "https://usemasterupdate-hanime.hf.space/hanime-api")
START_IMAGE_URL = os.getenv("START_IMAGE_URL", "https://iili.io/CnnMuA7.jpg")         # banner on /start
UPI_ID          = os.getenv("UPI_ID",          "radhe-krishna01@ptyes")
UPI_QR_URL      = os.getenv("UPI_QR_URL",      "https://iili.io/CnnhIqu.jpg")         # QR image shown after plan select
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME",  "@User_master_support_bot")   # contact for payment

FREE_DAILY_LIMIT = 10
TEMP_DIR = Path("/tmp/hanime")
TEMP_DIR.mkdir(exist_ok=True)

# ── Plans: key → (emoji+label, hours, price_inr) ─────────────────────
PLANS = {
    "trial": ("⚡ 1 Hour Trial",  1,    1),
    "day":   ("🌙 1 Day",         24,   8),
    "week":  ("📅 1 Week",        168,  29),
    "month": ("💎 1 Month",       720,  50),
}

# ── Quality display ───────────────────────────────────────────────────
QUALITY_META = {
    "1080": ("🔴", "1080p Full HD"),
    "720":  ("🔵", "720p HD"),
    "480":  ("🟡", "480p SD"),
    "360":  ("🟠", "360p Low"),
}
def quality_label(h: str) -> str:
    e, name = QUALITY_META.get(h, ("📹", f"{h}p"))
    return f"{e} {name}"

# ── Thumb palette ─────────────────────────────────────────────────────
THUMB_COLORS = [
    ("#FF006E","#FF6FA8"), ("#FB5607","#FFAA80"), ("#FFBE0B","#FFE57A"),
    ("#3A86FF","#80B8FF"), ("#8338EC","#C07EFF"), ("#06D6A0","#7FFFDA"),
    ("#EF233C","#FF7F8A"), ("#00B4D8","#80DAFF"), ("#F72585","#FFA8D4"),
    ("#4CC9F0","#A8E6FF"),
]

BOT_USERNAME: str | None = None  # filled lazily

# Resolved integer peer IDs — populated on startup to avoid PeerIdInvalid
_LOG_CHANNEL_ID:  int | None = None
_FSUB_CHANNEL_ID: int | None = None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ LOGGING ━━━━━━━━━━━━━━━━━━━━━━━━━━━
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s")
log = logging.getLogger("HAnimeBot")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ DATABASE ━━━━━━━━━━━━━━━━━━━━━━━━━━
mongo   = AsyncIOMotorClient(MONGO_URI)
db      = mongo["hanime_bot"]
users   = db["users"]
admins  = db["admins"]
dlogs   = db["download_logs"]
pending = db["pending"]
settings_col = db["settings"]  # key-value store for runtime settings

async def get_user(uid: int) -> dict:
    u = await users.find_one({"_id": uid})
    if not u:
        u = {"_id": uid, "premium_until": None,
             "joined": datetime.utcnow(), "total_dl": 0,
             "banned": False, "username": None}
        await users.insert_one(u)
    return u

async def is_premium(uid: int) -> bool:
    if uid == OWNER_ID:
        return True
    u  = await get_user(uid)
    pu = u.get("premium_until")
    return bool(pu and pu > datetime.utcnow())

async def is_admin(uid: int) -> bool:
    if uid == OWNER_ID:
        return True
    return bool(await admins.find_one({"_id": uid}))

async def is_banned(uid: int) -> bool:
    u = await users.find_one({"_id": uid}, {"banned": 1})
    return bool(u and u.get("banned"))

async def today_downloads(uid: int) -> int:
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return await dlogs.count_documents({"uid": uid, "ts": {"$gte": start}})

async def log_download(uid: int, slug: str, quality: str, size_mb: float):
    await dlogs.insert_one({
        "uid": uid, "slug": slug,
        "quality": quality, "size_mb": round(size_mb, 2),
        "ts": datetime.utcnow()
    })
    await users.update_one({"_id": uid}, {"$inc": {"total_dl": 1}})

async def get_setting(key: str, default=None):
    doc = await settings_col.find_one({"_id": key})
    return doc["value"] if doc else default

async def set_setting(key: str, value):
    await settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ BOT CLIENT ━━━━━━━━━━━━━━━━━━━━━━━━
app = Client("hanime_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ FORCE-SUB ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _fsub_id():
    ch = FSUB_CHANNEL.strip()
    if not ch: return None
    try:    return int(ch)
    except: return ch

async def force_sub(m: Message) -> bool:
    global BOT_USERNAME
    cid = _FSUB_CHANNEL_ID or _fsub_id()
    if not cid: return True
    uid = m.from_user.id
    if await is_admin(uid): return True
    try:
        invite     = await app.create_chat_invite_link(chat_id=cid)
        invite_url = invite.invite_link
    except FloodWait as e:
        await asyncio.sleep(e.value)
        invite     = await app.create_chat_invite_link(chat_id=cid)
        invite_url = invite.invite_link
    except Exception as e:
        log.warning(f"ForceSub invite error: {e}")
        return True
    try:
        member = await app.get_chat_member(chat_id=cid, user_id=uid)
        if member.status and member.status.name.lower() == "banned":
            await m.reply(
                "🚫 <b>You are banned from this bot.</b>\nContact support.",
                parse_mode=enums.ParseMode.HTML
            )
            return False
        return True
    except UserNotParticipant:
        if not BOT_USERNAME:
            me = await app.get_me()
            BOT_USERNAME = me.username
        await m.reply_photo(
            photo=START_IMAGE_URL or f"https://picsum.photos/seed/{uid}/800/400",
            caption=(
                "🔒 <b>Members Only Bot</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📢 Join our channel to unlock access.\n"
                "After joining tap <b>✅ I Joined</b> below.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel 🔔", url=invite_url)],
                [InlineKeyboardButton("✅ I Joined — Unlock Bot",
                                      url=f"https://t.me/{BOT_USERNAME}?start=check")],
            ]),
            parse_mode=enums.ParseMode.HTML
        )
        return False
    except Exception as e:
        log.warning(f"ForceSub check error: {e}")
        return True

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ HELPERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━
BANNER = (
    "┌─────────────────────────────────┐\n"
    "│   🔥  <b>HAnime Downloader Bot</b>   │\n"
    "└─────────────────────────────────┘"
)

def premium_badge(until) -> str:
    if not until or until < datetime.utcnow():
        return "🆓 <b>Free</b>"
    left = until - datetime.utcnow()
    h    = int(left.total_seconds() // 3600)
    if h >= 720: return f"💎 <b>Premium</b> · {h // 720}mo left"
    if h >= 168: return f"📅 <b>Premium</b> · {h // 168}w left"
    if h >= 24:  return f"🌙 <b>Premium</b> · {h // 24}d left"
    return      f"⚡ <b>Premium</b> · {h}h left"

def progress_bar(used: int, total: int, length: int = 10) -> str:
    if total == 0: return "■" * length
    filled = int((used / total) * length)
    return "▩" * filled + "□" * (length - filled)

def fmt_size(mb: float) -> str:
    if mb >= 1024: return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB"

async def send_log(text: str, photo: str | None = None):
    target = _LOG_CHANNEL_ID or LOG_CHANNEL
    try:
        if photo:
            await app.send_photo(target, photo,
                                 caption=text, parse_mode=enums.ParseMode.HTML)
        else:
            await app.send_message(target, text,
                                   parse_mode=enums.ParseMode.HTML,
                                   disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Log channel error: {e}")

async def fetch_streams(url: str) -> dict | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(API_BASE, params={"url": url},
                             timeout=aiohttp.ClientTimeout(total=40)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"API fetch error: {e}")
    return None

async def generate_thumb(slug: str, title: str) -> str | None:
    out = TEMP_DIR / f"thumb_{slug}_{random.randint(1000, 9999)}.jpg"
    c1, c2 = random.choice(THUMB_COLORS)
    r1,g1,b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    safe_title = title[:38]
    cmd = [
        "convert", "-size", "480x270",
        f"gradient:rgb({r1},{g1},{b1})-rgb({r2},{g2},{b2})",
        # dark overlay strip at bottom
        "-fill", "rgba(0,0,0,0.55)", "-draw", "rectangle 0,195 480,270",
        # title
        "-gravity", "Center", "-fill", "white",
        "-font", "DejaVu-Sans-Bold", "-pointsize", "26",
        "-annotate", "0", safe_title,
        # watermark
        "-gravity", "SouthWest", "-fill", "rgba(255,255,255,0.85)",
        "-font", "DejaVu-Sans", "-pointsize", "14",
        "-annotate", "+10+8", "🔥 HAnime Downloader",
        # play icon overlay
        "-gravity", "SouthEast", "-fill", "rgba(255,255,255,0.7)",
        "-font", "DejaVu-Sans-Bold", "-pointsize", "38",
        "-annotate", "+12+6", "▶",
        str(out),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if out.exists() and out.stat().st_size > 0:
            return str(out)
    except Exception as e:
        log.warning(f"Thumb gen error: {e}")
    return None

async def download_hls(m3u8_url: str, out_path: str) -> bool:
    cmd = [
        "yt-dlp", "--no-warnings", "--quiet",
        "-o", out_path,
        "--hls-prefer-native",
        "--merge-output-format", "mp4",
        "--no-part",
        m3u8_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.communicate(), timeout=600)
        return proc.returncode == 0 or Path(out_path).exists()
    except asyncio.TimeoutError:
        log.error("Download timed out")
        return False
    except Exception as e:
        log.error(f"Download error: {e}")
        return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ KEYBOARDS ━━━━━━━━━━━━━━━━━━━━━━━━━━
def quality_kb(streams: list, slug: str) -> InlineKeyboardMarkup:
    btns = []
    for s in sorted(streams, key=lambda x: int(x["height"]), reverse=True):
        btns.append([InlineKeyboardButton(
            quality_label(s["height"]),
            callback_data=f"dl|{slug}|{s['height']}"
        )])
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(btns)

def plans_kb() -> InlineKeyboardMarkup:
    rows = []
    for k, (label, hrs, price) in PLANS.items():
        rows.append([InlineKeyboardButton(
            f"{label}  —  ₹{price}",
            callback_data=f"plan|{k}"
        )])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def main_kb(is_pr: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💎 Premium Plans", callback_data="show_plans"),
         InlineKeyboardButton("📊 My Stats",      callback_data="my_stats")],
        [InlineKeyboardButton("❓ How to Use",    callback_data="help"),
         InlineKeyboardButton("📢 Channel",       url="https://t.me/UseMasterUpdate")],
    ]
    if not is_pr:
        rows.insert(0, [InlineKeyboardButton(
            "🚀 Upgrade to Premium", callback_data="show_plans")])
    return InlineKeyboardMarkup(rows)

def back_kb(cb: str = "back_home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=cb)]])

# ━━━━━━━━━━━━━━━━━━━━━━━━━ STARTUP PEER RESOLVER ━━━━━━━━━━━━━━━━━━━━━
@app.on_message(filters.command("_noop_startup_") & filters.user([])) 
async def _noop(_,__): pass  # dummy; real init is below

async def _resolve_peers():
    """
    Resolve LOG_CHANNEL and FSUB_CHANNEL to integer IDs on startup.
    This ensures Pyrogram has the peer in its session cache, preventing
    PeerIdInvalid errors when sending log messages or doing force-sub checks.
    """
    global _LOG_CHANNEL_ID, _FSUB_CHANNEL_ID, BOT_USERNAME

    me = await app.get_me()
    BOT_USERNAME = me.username
    log.info(f"Bot: @{BOT_USERNAME}")

    # Resolve LOG_CHANNEL
    try:
        chat = await app.get_chat(LOG_CHANNEL)
        _LOG_CHANNEL_ID = chat.id
        log.info(f"✅ Log channel resolved: {chat.title!r} ({_LOG_CHANNEL_ID})")
    except Exception as e:
        log.error(f"❌ Could not resolve LOG_CHANNEL ({LOG_CHANNEL}): {e}")
        log.error("   → Make sure the bot is an admin/member of the log channel!")

    # Resolve FSUB_CHANNEL (if set)
    raw_fsub = FSUB_CHANNEL.strip() if FSUB_CHANNEL else ""
    if raw_fsub:
        try:
            chat = await app.get_chat(raw_fsub)
            _FSUB_CHANNEL_ID = chat.id
            log.info(f"✅ ForceSub channel resolved: {chat.title!r} ({_FSUB_CHANNEL_ID})")
        except Exception as e:
            log.error(f"❌ Could not resolve FSUB_CHANNEL ({raw_fsub}): {e}")
            log.error("   → Make sure the bot is an admin of the force-sub channel!")
    else:
        log.info("ℹ️  ForceSub disabled (FSUB_CHANNEL not set)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ /start ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.on_message(filters.command("start") & filters.private)
async def start(_, m: Message):
    uid  = m.from_user.id
    name = html.escape(m.from_user.first_name or "User")

    # ban check
    if await is_banned(uid):
        return await m.reply("🚫 <b>You are banned.</b> Contact support.",
                             parse_mode=enums.ParseMode.HTML)

    # update username in db
    uname = m.from_user.username
    await get_user(uid)
    if uname:
        await users.update_one({"_id": uid}, {"$set": {"username": uname}})

    if not await force_sub(m): return

    pr    = await is_premium(uid)
    u     = await users.find_one({"_id": uid})
    badge = premium_badge(u.get("premium_until"))
    used  = await today_downloads(uid)
    limit = "∞" if pr else str(FREE_DAILY_LIMIT)
    bar   = "" if pr else f"\n📊 {progress_bar(used, FREE_DAILY_LIMIT)} {used}/{FREE_DAILY_LIMIT}"

    caption = (
        f"{BANNER}\n\n"
        f"👋 <b>Hey {name}!</b>\n\n"
        f"{'─' * 30}\n"
        f"🎖 Status  :  {badge}\n"
        f"📥 Limit   :  {limit}/day{bar}\n"
        f"{'─' * 30}\n\n"
        f"🎯 Send a <b>hanime.tv</b> link to start downloading!\n\n"
        f"<code>https://hanime.tv/videos/hentai/title</code>"
    )

    img = START_IMAGE_URL or f"https://picsum.photos/seed/{random.randint(1,9999)}/800/400"
    try:
        await m.reply_photo(photo=img, caption=caption,
                            reply_markup=main_kb(pr),
                            parse_mode=enums.ParseMode.HTML)
    except Exception:
        await m.reply(caption, reply_markup=main_kb(pr),
                      parse_mode=enums.ParseMode.HTML)

    await send_log(
        f"🆕 <b>New Start</b>\n"
        f"👤 <a href='tg://user?id={uid}'>{name}</a> · <code>{uid}</code>\n"
        f"📛 @{uname or 'no_username'}\n"
        f"🎖 {badge}\n"
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ /plans ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.on_message(filters.command("plans") & filters.private)
async def plans_cmd(_, m: Message):
    if await is_banned(m.from_user.id): return
    if not await force_sub(m): return
    u     = await users.find_one({"_id": m.from_user.id})
    badge = premium_badge(u.get("premium_until") if u else None)
    await m.reply(
        _plans_text(badge),
        reply_markup=plans_kb(),
        parse_mode=enums.ParseMode.HTML
    )

def _plans_text(badge: str) -> str:
    lines = [
        "💎 <b>PREMIUM PLANS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎖 Your Status: {badge}",
        "",
        "🎁 <b>Premium Benefits:</b>",
        "  ✅  Unlimited downloads / day",
        "  ✅  All qualities unlocked",
        "  ✅  Zero wait time",
        "  ✅  Priority support",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "<b>Choose a plan:</b>",
    ]
    return "\n".join(lines)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ADMIN CMDS ━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── /addpr ────────────────────────────────────────────────────────────
@app.on_message(filters.command("addpr") & filters.private)
async def add_premium(_, m: Message):
    if not await is_admin(m.from_user.id):
        return await m.reply("⛔ Admins only.")
    parts = m.text.split()

    # ─── BULK: /addpr all <plan> ───────────────────────────────────
    if len(parts) >= 2 and parts[1].lower() == "all":
        plan = parts[2] if len(parts) > 2 else "day"
        if plan not in PLANS:
            return await m.reply(
                f"❌ Unknown plan. Options: {', '.join(PLANS)}\n"
                f"Example: <code>/addpr all week</code>",
                parse_mode=enums.ParseMode.HTML)
        label, hrs, _ = PLANS[plan]
        until = datetime.utcnow() + timedelta(hours=hrs)
        total = await users.count_documents({})
        smsg  = await m.reply(
            f"🎁 <b>Giveaway Starting…</b>\n\n"
            f"📦 Plan: {label}\n👥 Users: <b>{total}</b>\n⏳ Activating…",
            parse_mode=enums.ParseMode.HTML)
        await users.update_many({}, {"$set": {"premium_until": until}})
        notified = failed = 0
        async for u in users.find({}, {"_id": 1}):
            try:
                await app.send_message(
                    u["_id"],
                    f"🎉 <b>Free Giveaway!</b>\n\n"
                    f"🎁 Plan: <b>{label}</b>\n"
                    f"⏳ Expires: <b>{until.strftime('%d %b %Y · %H:%M')} UTC</b>\n\n"
                    f"Enjoy unlimited downloads! 🔥\n"
                    f"<i>— HAnime Bot Team ❤️</i>",
                    parse_mode=enums.ParseMode.HTML)
                notified += 1
            except (UserIsBlocked, InputUserDeactivated): failed += 1
            except FloodWait as e: await asyncio.sleep(e.value)
            except: failed += 1
            await asyncio.sleep(0.05)
        await smsg.edit(
            f"✅ <b>Giveaway Complete!</b>\n\n"
            f"📦 Plan: {label}\n"
            f"⏳ Until: {until.strftime('%d %b %Y · %H:%M')} UTC\n"
            f"👥 Total: <b>{total}</b>  ·  📨 Notified: <b>{notified}</b>  ·  ❌ Failed: <b>{failed}</b>",
            parse_mode=enums.ParseMode.HTML)
        return await send_log(
            f"🎁 <b>Bulk Giveaway</b>\nPlan: {label} · Users: {total}\nBy: <code>{m.from_user.id}</code>")

    # ─── SINGLE USER ──────────────────────────────────────────────
    if len(parts) < 3 and not m.reply_to_message:
        return await m.reply(
            "📌 <b>Usage:</b>\n"
            "• <code>/addpr &lt;uid&gt; &lt;plan&gt;</code>\n"
            "• Reply to user: <code>/addpr week</code>\n"
            "• Everyone: <code>/addpr all week</code>\n\n"
            f"Plans: <code>{' | '.join(PLANS)}</code>",
            parse_mode=enums.ParseMode.HTML)
    try:
        if m.reply_to_message:
            uid  = m.reply_to_message.from_user.id
            plan = parts[1] if len(parts) > 1 else "day"
        else:
            uid  = int(parts[1])
            plan = parts[2]
        if plan not in PLANS:
            return await m.reply(f"❌ Unknown plan: <code>{plan}</code>", parse_mode=enums.ParseMode.HTML)
        label, hrs, price = PLANS[plan]
        until = datetime.utcnow() + timedelta(hours=hrs)
        await users.update_one({"_id": uid}, {"$set": {"premium_until": until}}, upsert=True)
        await m.reply(
            f"✅ <b>Premium Activated</b>\n"
            f"👤 UID: <code>{uid}</code>\n"
            f"📦 Plan: {label}\n"
            f"⏳ Until: {until.strftime('%d %b %Y · %H:%M')} UTC",
            parse_mode=enums.ParseMode.HTML)
        await send_log(
            f"💎 <b>Premium Added</b>\n"
            f"UID: <code>{uid}</code> · Plan: {label}\nBy: <code>{m.from_user.id}</code>")
        try:
            await app.send_message(
                uid,
                f"🎉 <b>Premium Activated!</b>\n\n"
                f"📦 Plan: {label}\n"
                f"⏳ Expires: {until.strftime('%d %b %Y · %H:%M')} UTC\n\n"
                f"You now have <b>unlimited downloads</b>! 🔥",
                parse_mode=enums.ParseMode.HTML)
        except: pass
    except Exception as e:
        await m.reply(f"❌ Error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)

# ── /rempr ────────────────────────────────────────────────────────────
@app.on_message(filters.command("rempr") & filters.private)
async def remove_premium(_, m: Message):
    if not await is_admin(m.from_user.id):
        return await m.reply("⛔ Admins only.")
    parts = m.text.split()

    if len(parts) >= 2 and parts[1].lower() == "all":
        total = await users.count_documents({"premium_until": {"$gt": datetime.utcnow()}})
        await users.update_many({}, {"$set": {"premium_until": None}})
        await m.reply(
            f"✅ Premium removed from <b>{total}</b> users.",
            parse_mode=enums.ParseMode.HTML)
        return await send_log(
            f"🗑 <b>Bulk Premium Removed</b>\nAffected: {total}\nBy: <code>{m.from_user.id}</code>")

    uid = (m.reply_to_message.from_user.id if m.reply_to_message
           else (int(parts[1]) if len(parts) > 1 else None))
    if not uid:
        return await m.reply(
            "Usage: <code>/rempr &lt;uid&gt;</code>  or  reply to user  or  <code>/rempr all</code>",
            parse_mode=enums.ParseMode.HTML)
    await users.update_one({"_id": uid}, {"$set": {"premium_until": None}})
    await m.reply(f"✅ Premium removed from <code>{uid}</code>", parse_mode=enums.ParseMode.HTML)
    await send_log(f"❌ <b>Premium Removed</b>\nUID: <code>{uid}</code> · By: <code>{m.from_user.id}</code>")

# ── /addadmin ─────────────────────────────────────────────────────────
@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin(_, m: Message):
    if m.from_user.id != OWNER_ID: return await m.reply("⛔ Owner only.")
    parts = m.text.split()
    uid   = (m.reply_to_message.from_user.id if m.reply_to_message
             else (int(parts[1]) if len(parts) > 1 else None))
    if not uid: return await m.reply("Provide UID or reply to user.")
    await admins.update_one({"_id": uid}, {"$set": {"added": datetime.utcnow()}}, upsert=True)
    await m.reply(f"✅ <code>{uid}</code> is now an Admin.", parse_mode=enums.ParseMode.HTML)
    await send_log(f"🛡 <b>Admin Added</b>\nUID: <code>{uid}</code> · By: <code>{m.from_user.id}</code>")

# ── /removeadmin ──────────────────────────────────────────────────────
@app.on_message(filters.command("removeadmin") & filters.private)
async def remove_admin(_, m: Message):
    if m.from_user.id != OWNER_ID: return await m.reply("⛔ Owner only.")
    parts = m.text.split()
    uid   = (m.reply_to_message.from_user.id if m.reply_to_message
             else (int(parts[1]) if len(parts) > 1 else None))
    if not uid: return await m.reply("Provide UID or reply to user.")
    await admins.delete_one({"_id": uid})
    await m.reply(f"✅ <code>{uid}</code> removed from admins.", parse_mode=enums.ParseMode.HTML)
    await send_log(f"🗑 <b>Admin Removed</b>\nUID: <code>{uid}</code> · By: <code>{m.from_user.id}</code>")

# ── /ban / /unban ─────────────────────────────────────────────────────
@app.on_message(filters.command("ban") & filters.private)
async def ban_user(_, m: Message):
    if not await is_admin(m.from_user.id): return await m.reply("⛔ Admins only.")
    parts = m.text.split()
    uid   = (m.reply_to_message.from_user.id if m.reply_to_message
             else (int(parts[1]) if len(parts) > 1 else None))
    if not uid: return await m.reply("Provide UID or reply to user.")
    await users.update_one({"_id": uid}, {"$set": {"banned": True}}, upsert=True)
    await m.reply(f"🚫 User <code>{uid}</code> banned.", parse_mode=enums.ParseMode.HTML)
    await send_log(f"🚫 <b>User Banned</b>\nUID: <code>{uid}</code> · By: <code>{m.from_user.id}</code>")

@app.on_message(filters.command("unban") & filters.private)
async def unban_user(_, m: Message):
    if not await is_admin(m.from_user.id): return await m.reply("⛔ Admins only.")
    parts = m.text.split()
    uid   = (m.reply_to_message.from_user.id if m.reply_to_message
             else (int(parts[1]) if len(parts) > 1 else None))
    if not uid: return await m.reply("Provide UID or reply to user.")
    await users.update_one({"_id": uid}, {"$set": {"banned": False}})
    await m.reply(f"✅ User <code>{uid}</code> unbanned.", parse_mode=enums.ParseMode.HTML)

# ── /stats ────────────────────────────────────────────────────────────
@app.on_message(filters.command("stats") & filters.private)
async def stats_cmd(_, m: Message):
    if not await is_admin(m.from_user.id): return await m.reply("⛔ Admins only.")
    now          = datetime.utcnow()
    today_start  = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start   = now - timedelta(days=7)
    total_users  = await users.count_documents({})
    pr_users     = await users.count_documents({"premium_until": {"$gt": now}})
    banned_users = await users.count_documents({"banned": True})
    total_dls    = await dlogs.count_documents({})
    today_dls    = await dlogs.count_documents({"ts": {"$gte": today_start}})
    week_dls     = await dlogs.count_documents({"ts": {"$gte": week_start}})
    new_today    = await users.count_documents({"joined": {"$gte": today_start}})
    total_admins = await admins.count_documents({})
    await m.reply(
        "📊 <b>BOT STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users    : <b>{total_users}</b>\n"
        f"🆕 Joined Today   : <b>{new_today}</b>\n"
        f"💎 Premium Users  : <b>{pr_users}</b>\n"
        f"🚫 Banned Users   : <b>{banned_users}</b>\n"
        f"🛡 Admins         : <b>{total_admins}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Today DLs      : <b>{today_dls}</b>\n"
        f"📅 Week DLs       : <b>{week_dls}</b>\n"
        f"📦 Total DLs      : <b>{total_dls}</b>",
        parse_mode=enums.ParseMode.HTML)

# ── /broadcast ────────────────────────────────────────────────────────
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast(_, m: Message):
    if not await is_admin(m.from_user.id): return await m.reply("⛔ Admins only.")
    if not m.reply_to_message:
        return await m.reply("Reply to the message you want to broadcast.")
    smsg = await m.reply("📡 Broadcasting…")
    sent = failed = blocked = 0
    async for u in users.find({}, {"_id": 1}):
        try:
            await app.forward_messages(u["_id"], m.chat.id, m.reply_to_message.id)
            sent += 1
        except (UserIsBlocked, InputUserDeactivated): blocked += 1
        except FloodWait as e: await asyncio.sleep(e.value)
        except: failed += 1
        await asyncio.sleep(0.05)
    await smsg.edit(
        f"📡 <b>Broadcast Complete</b>\n"
        f"✅ Sent: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"🚫 Blocked/Deactivated: <b>{blocked}</b>",
        parse_mode=enums.ParseMode.HTML)

# ── /userinfo ─────────────────────────────────────────────────────────
@app.on_message(filters.command("userinfo") & filters.private)
async def userinfo(_, m: Message):
    if not await is_admin(m.from_user.id): return await m.reply("⛔ Admins only.")
    parts = m.text.split()
    uid   = (m.reply_to_message.from_user.id if m.reply_to_message
             else (int(parts[1]) if len(parts) > 1 else None))
    if not uid: return await m.reply("Provide UID or reply to user.")
    u = await users.find_one({"_id": uid})
    if not u: return await m.reply("User not found in DB.")
    total_dl  = await dlogs.count_documents({"uid": uid})
    today_dl  = await today_downloads(uid)
    badge     = premium_badge(u.get("premium_until"))
    admin_tag = " 🛡 Admin" if await is_admin(uid) else ""
    await m.reply(
        f"👤 <b>User Info</b>{admin_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 UID      : <code>{uid}</code>\n"
        f"📛 Username : @{u.get('username') or 'N/A'}\n"
        f"🎖 Status   : {badge}\n"
        f"🚫 Banned   : {'Yes ❌' if u.get('banned') else 'No ✅'}\n"
        f"📅 Joined   : {u.get('joined', datetime.utcnow()).strftime('%d %b %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Today DLs : <b>{today_dl}</b>\n"
        f"📦 Total DLs : <b>{total_dl}</b>",
        parse_mode=enums.ParseMode.HTML)

# ── /setmaintenance ───────────────────────────────────────────────────
@app.on_message(filters.command(["setmaintenance","maintenance"]) & filters.private)
async def maintenance_toggle(_, m: Message):
    if m.from_user.id != OWNER_ID: return await m.reply("⛔ Owner only.")
    current = await get_setting("maintenance", False)
    new_val = not current
    await set_setting("maintenance", new_val)
    state = "🔴 ON (bot paused for users)" if new_val else "🟢 OFF (bot active)"
    await m.reply(f"🔧 Maintenance mode: <b>{state}</b>", parse_mode=enums.ParseMode.HTML)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ URL HANDLER ━━━━━━━━━━━━━━━━━━━━━━━━━━━
HANIME_RE = re.compile(r"https?://hanime\.tv/videos/hentai/([\w-]+)")

@app.on_message(filters.text & filters.private & filters.regex(HANIME_RE))
async def handle_url(_, m: Message):
    uid = m.from_user.id
    if await is_banned(uid):
        return await m.reply("🚫 You are banned.")

    # maintenance gate (admins bypass)
    if not await is_admin(uid):
        if await get_setting("maintenance", False):
            return await m.reply(
                "🔧 <b>Bot is under maintenance.</b>\nPlease try again later.",
                parse_mode=enums.ParseMode.HTML)

    if not await force_sub(m): return

    url  = HANIME_RE.search(m.text).group(0)
    slug = HANIME_RE.search(m.text).group(1)
    pr   = await is_premium(uid)

    if not pr:
        used = await today_downloads(uid)
        if used >= FREE_DAILY_LIMIT:
            bar = progress_bar(used, FREE_DAILY_LIMIT)
            return await m.reply(
                f"🚫 <b>Daily Limit Reached!</b>\n\n"
                f"📊 {bar} {used}/{FREE_DAILY_LIMIT}\n\n"
                f"Free users get <b>{FREE_DAILY_LIMIT} downloads/day</b>.\n"
                f"Reset at <b>00:00 UTC</b>.\n\n"
                f"💎 Upgrade for unlimited access!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💎 View Plans", callback_data="show_plans")
                ]]),
                parse_mode=enums.ParseMode.HTML)

    loading = await m.reply(
        "🔍 <b>Fetching stream data…</b>\n<i>Contacting API…</i>",
        parse_mode=enums.ParseMode.HTML)
    data = await fetch_streams(url)

    if not data or not data.get("streams"):
        return await loading.edit(
            "❌ <b>Could not fetch streams.</b>\n\n"
            "• Check the URL is a valid hanime.tv video\n"
            "• The video may be region-locked\n"
            "• Try again in a moment",
            parse_mode=enums.ParseMode.HTML)

    streams = data["streams"]
    title   = data.get("title") or slug.replace("-", " ").title()
    used    = await today_downloads(uid)

    status_line = (
        f"💎 <b>Premium</b> — Unlimited"
        if pr else
        f"🆓 Free — {FREE_DAILY_LIMIT - used} remaining  {progress_bar(used, FREE_DAILY_LIMIT)}"
    )

    text = (
        f"🎬 <b>{html.escape(title)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 Streams: <b>{len(streams)}</b> available\n"
        f"🔗 <code>{slug}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}\n\n"
        f"<b>🎯 Select quality:</b>"
    )
    try:
        await loading.edit(text, reply_markup=quality_kb(streams, slug),
                           parse_mode=enums.ParseMode.HTML)
    except MessageNotModified:
        pass

    await pending.update_one(
        {"_id": f"{uid}_{slug}"},
        {"$set": {"streams": streams, "url": url, "title": title, "ts": datetime.utcnow()}},
        upsert=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━ CALLBACK: DOWNLOAD ━━━━━━━━━━━━━━━━━━━━━━
@app.on_callback_query(filters.regex(r"^dl\|"))
async def cb_download(_, cq: CallbackQuery):
    _, slug, height = cq.data.split("|")
    uid = cq.from_user.id
    pr  = await is_premium(uid)

    if not pr:
        used = await today_downloads(uid)
        if used >= FREE_DAILY_LIMIT:
            return await cq.answer(
                f"🚫 Limit reached! {used}/{FREE_DAILY_LIMIT} today.\nUpgrade to Premium.",
                show_alert=True)

    pend = await pending.find_one({"_id": f"{uid}_{slug}"})
    if not pend:
        return await cq.answer("❌ Session expired. Send the URL again.", show_alert=True)

    stream = next((s for s in pend["streams"] if s["height"] == height), None)
    if not stream:
        return await cq.answer("❌ Quality not available.", show_alert=True)

    title = pend["title"]
    m3u8  = stream["url"]
    fname = f"{slug}_{height}p_{random.randint(10000, 99999)}.mp4"
    out   = str(TEMP_DIR / fname)

    await cq.message.edit(
        f"⬇️ <b>Downloading…</b>\n\n"
        f"🎬 <b>{html.escape(title)}</b>\n"
        f"📹 Quality: {quality_label(height)}\n\n"
        f"⏳ <i>Please wait, this may take a few minutes…</i>",
        parse_mode=enums.ParseMode.HTML)

    ok = await download_hls(m3u8, out)
    if not ok or not Path(out).exists():
        return await cq.message.edit(
            "❌ <b>Download Failed</b>\n\n"
            "• Try a lower quality\n"
            "• The stream may have expired — resend the URL\n"
            "• Contact support if this keeps happening",
            reply_markup=back_kb(),
            parse_mode=enums.ParseMode.HTML)

    size_mb = Path(out).stat().st_size / (1024 * 1024)
    thumb   = await generate_thumb(slug, title)

    await cq.message.edit(
        f"📤 <b>Uploading…</b>\n\n"
        f"🎬 {html.escape(title)}\n"
        f"📹 {quality_label(height)}  ·  📦 {fmt_size(size_mb)}\n\n"
        f"<i>Almost done…</i>",
        parse_mode=enums.ParseMode.HTML)

    cap = (
        f"🎬 <b>{html.escape(title)}</b>\n"
        f"{'─' * 28}\n"
        f"📹 Quality : {quality_label(height)}\n"
        f"📦 Size    : {fmt_size(size_mb)}\n"
        f"{'─' * 28}\n"
        f"🔥 <b>HAnime Downloader Bot</b> · @UseMasterUpdate"
    )

    try:
        await app.send_video(
            uid, out,
            caption=cap,
            thumb=thumb,
            parse_mode=enums.ParseMode.HTML,
            supports_streaming=True)
        await log_download(uid, slug, height, size_mb)
        await cq.message.delete()
        await send_log(
            f"📥 <b>Download Complete</b>\n"
            f"👤 <a href='tg://user?id={uid}'>{html.escape(cq.from_user.first_name or '')}</a> · <code>{uid}</code>\n"
            f"🎬 {html.escape(title)}\n"
            f"📹 {height}p  ·  📦 {fmt_size(size_mb)}\n"
            f"🎖 {'💎 Premium' if pr else '🆓 Free'}")
    except Exception as e:
        await cq.message.edit(f"❌ <b>Upload failed:</b>\n<code>{e}</code>",
                              parse_mode=enums.ParseMode.HTML)
    finally:
        for f in [out, thumb]:
            if f and Path(f).exists():
                Path(f).unlink(missing_ok=True)

# ━━━━━━━━━━━━━━━━━━━━━━━ CALLBACK: MISC ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.on_callback_query(filters.regex(r"^cancel$"))
async def cb_cancel(_, cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer("Cancelled.")

@app.on_callback_query(filters.regex(r"^show_plans$"))
async def cb_plans(_, cq: CallbackQuery):
    u     = await users.find_one({"_id": cq.from_user.id})
    badge = premium_badge(u.get("premium_until") if u else None)
    try:
        await cq.message.edit(_plans_text(badge),
                              reply_markup=plans_kb(),
                              parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: pass
    await cq.answer()

@app.on_callback_query(filters.regex(r"^plan\|"))
async def cb_plan_select(_, cq: CallbackQuery):
    key             = cq.data.split("|")[1]
    label, hrs, price = PLANS[key]
    uid             = cq.from_user.id

    # Build UPI payment block
    upi_block = (
        f"\n<b>━━━ 💳 Payment ━━━</b>\n"
        f"UPI ID: <code>{UPI_ID}</code>\n"
        f"Amount: <b>₹{price}</b>\n\n"
        f"After payment, send screenshot to {ADMIN_USERNAME}\n"
        f"along with your User ID below."
    )

    text = (
        f"💎 <b>{label}</b>\n"
        f"{'─' * 28}\n"
        f"💰 Price    : <b>₹{price}</b>\n"
        f"⏳ Duration : <b>{hrs} hour{'s' if hrs > 1 else ''}</b>\n"
        f"{'─' * 28}"
        f"{upi_block}\n\n"
        f"🆔 <b>Your User ID:</b> <code>{uid}</code>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📩 Contact {ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton("🔙 Back to Plans", callback_data="show_plans")],
    ])

    # If QR image configured, send as photo; else edit text
    if UPI_QR_URL:
        try:
            await cq.message.delete()
            await app.send_photo(
                cq.from_user.id,
                photo=UPI_QR_URL,
                caption=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML)
        except Exception:
            await cq.message.edit(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    else:
        try:
            await cq.message.edit(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified: pass

    await cq.answer(f"Selected: {label} — ₹{price}", show_alert=False)
    await send_log(
        f"🛒 <b>Plan Interest</b>\n"
        f"👤 <a href='tg://user?id={uid}'>{html.escape(cq.from_user.first_name or '')}</a> · <code>{uid}</code>\n"
        f"📦 Plan: {label} · ₹{price}")

@app.on_callback_query(filters.regex(r"^my_stats$"))
async def cb_mystats(_, cq: CallbackQuery):
    uid      = cq.from_user.id
    u        = await get_user(uid)
    pr       = await is_premium(uid)
    used     = await today_downloads(uid)
    total_dl = await dlogs.count_documents({"uid": uid})
    badge    = premium_badge(u.get("premium_until"))
    bar      = progress_bar(used, FREE_DAILY_LIMIT) if not pr else "∞"
    rank     = "👑 Owner" if uid == OWNER_ID else ("🛡 Admin" if await is_admin(uid) else ("💎 Premium" if pr else "🆓 Free"))

    # last 3 downloads
    recent = []
    async for d in dlogs.find({"uid": uid}, sort=[("ts", -1)], limit=3):
        ts  = d["ts"].strftime("%d %b %H:%M")
        sl  = d.get("slug", "?")[:20]
        ql  = d.get("quality", "?") + "p"
        recent.append(f"  <code>{sl}</code> · {ql} · {ts}")
    recent_block = ("\n<b>🕒 Recent Downloads:</b>\n" + "\n".join(recent)) if recent else ""

    text = (
        f"📊 <b>YOUR PROFILE</b>\n"
        f"{'─' * 28}\n"
        f"👤 ID       : <code>{uid}</code>\n"
        f"📛 Username : @{u.get('username') or 'N/A'}\n"
        f"🎖 Rank     : {rank}\n"
        f"💎 Status   : {badge}\n"
        f"{'─' * 28}\n"
        f"📥 Today    : {used}/{FREE_DAILY_LIMIT if not pr else '∞'}  {bar}\n"
        f"📦 All Time : <b>{total_dl}</b>\n"
        f"📅 Joined   : {u.get('joined', datetime.utcnow()).strftime('%d %b %Y')}"
        f"{recent_block}"
    )
    try:
        await cq.message.edit(text, reply_markup=back_kb(), parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: pass
    await cq.answer()

@app.on_callback_query(filters.regex(r"^help$"))
async def cb_help(_, cq: CallbackQuery):
    text = (
        "❓ <b>HOW TO USE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣  <b>Join</b> the channel (required)\n"
        "2️⃣  <b>Send</b> a hanime.tv video URL\n"
        "3️⃣  <b>Pick</b> your quality from the buttons\n"
        "4️⃣  <b>Wait</b> — video is uploaded directly to chat\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Supported URL:</b>\n"
        "<code>https://hanime.tv/videos/hentai/title</code>\n\n"
        "🎯 <b>Qualities:</b>  720p · 480p · 360p\n\n"
        "🆓 <b>Free:</b>  10 downloads / day (resets 00:00 UTC)\n"
        "💎 <b>Premium:</b>  Unlimited · all qualities\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Commands:</b>\n"
        "/start  — Home\n"
        "/plans  — Upgrade to Premium"
    )
    try:
        await cq.message.edit(text, reply_markup=back_kb(), parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: pass
    await cq.answer()

@app.on_callback_query(filters.regex(r"^back_home$"))
async def cb_back(_, cq: CallbackQuery):
    uid   = cq.from_user.id
    name  = html.escape(cq.from_user.first_name or "User")
    pr    = await is_premium(uid)
    u     = await users.find_one({"_id": uid})
    badge = premium_badge(u.get("premium_until") if u else None)
    used  = await today_downloads(uid)
    bar   = "" if pr else f"\n📊 {progress_bar(used, FREE_DAILY_LIMIT)} {used}/{FREE_DAILY_LIMIT}"

    text = (
        f"{BANNER}\n\n"
        f"👋 <b>Hey {name}!</b>\n\n"
        f"{'─' * 30}\n"
        f"🎖 Status  :  {badge}\n"
        f"📥 Limit   :  {'∞' if pr else str(FREE_DAILY_LIMIT)}/day{bar}\n"
        f"{'─' * 30}\n\n"
        f"<b>Send a hanime.tv link to start!</b>"
    )
    try:
        await cq.message.edit(text, reply_markup=main_kb(pr), parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: pass
    await cq.answer()

# ━━━━━━━━━━━━━━━━━━━━━━━━━ UNKNOWN CMD / TEXT ━━━━━━━━━━━━━━━━━━━━━━━
@app.on_message(filters.private & filters.text & ~filters.regex(HANIME_RE))
async def unknown(_, m: Message):
    if m.text.startswith("/"):
        return await m.reply(
            "❓ Unknown command.\n/start · /plans",
            parse_mode=enums.ParseMode.HTML)
    # non-URL text — gentle nudge
    await m.reply(
        "🔗 <b>Send a hanime.tv video URL</b> to download.\n\n"
        "<code>https://hanime.tv/videos/hentai/title</code>",
        parse_mode=enums.ParseMode.HTML)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ENTRYPOINT ━━━━━━━━━━━━━━━━━━━━━━━━━━
async def main():
    log.info("🔥 HAnime Bot starting…")
    await app.start()
    await _resolve_peers()
    log.info("✅ Bot is online and ready.")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
