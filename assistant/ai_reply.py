# assistant/ai_reply.py
import aiohttp
import logging
import os
import re
import pytz
import random
import asyncio

from datetime import datetime
from rapidfuzz import fuzz

# ==========================================================
# 🛑 LOGGING
# ==========================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================================
# 🔑 API CONFIG (TMDB & OPENROUTER)
# ==========================================================
keys_env = os.getenv(
    "OPENROUTER_API_KEYS",
    os.getenv("OPENROUTER_API_KEY", "")
)

API_KEYS = [k.strip() for k in keys_env.split(",") if k.strip()]
MODEL_NAME = "openai/gpt-4o-mini"

# আপনার TMDB API Key যা লাইভ সার্চের জন্য ব্যবহৃত হবে
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "7dc544d9253bccc3cfecc1c677f69819")
tmdb_cache = TTLCache = {} # কুইক মেমোরি ক্যাশ

# ==========================================================
# 🌐 SESSION INSTANCE
# ==========================================================
session_instance = None

async def get_session():
    global session_instance
    if session_instance is None or session_instance.closed:
        timeout = aiohttp.ClientTimeout(total=40)
        session_instance = aiohttp.ClientSession(timeout=timeout)
    return session_instance

# ==========================================================
# 🌍 BANGLA NORMALIZER
# ==========================================================
BN_MAP = {
    "কেজিএফ": "kgf",
    "অ্যাভেঞ্জার": "avengers",
    "এভেঞ্জার": "avengers",
    "স্পাইডারম্যান": "spiderman",
    "স্পাইডার ম্যান": "spiderman",
    "মানি হেইস্ট": "money heist",
    "স্কুইড গেম": "squid game",
    "পুষ্পা": "pushpa",
    "জওয়ান": "jawan",
    "পাঠান": "pathaan",
    "ডন": "don",
    "টাইগার": "tiger",
}

REMOVE_WORDS = [
    "movie", "download", "series", "full movie", "full", "hd",
    "hindi", "bangla", "english", "season", "episode", "part",
    "watch", "dekhbo", "dao", "den", "please",
]

def normalize_query(text):
    text = text.lower().strip()
    for bn, en in BN_MAP.items():
        text = text.replace(bn.lower(), en)
    for word in REMOVE_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ==========================================================
# 🔍 TMDB LIVE SEARCH ENGINE (১০০% ফ্রী ও রিয়েল-টাইম)
# ==========================================================
async def fetch_live_tmdb_info(query: str):
    if not TMDB_API_KEY or TMDB_API_KEY == "YOUR_TMDB_API_KEY_HERE":
        return None
    try:
        session = await get_session()
        url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "query": query,
            "language": "en-US"
        }
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("results")
                if results:
                    m = results[0]
                    return {
                        "title": m.get("title"),
                        "release_date": m.get("release_date", "Coming Soon"),
                        "overview": m.get("overview", "No description available on TMDB."),
                        "rating": m.get("vote_average", 0)
                    }
    except Exception as e:
        logger.error(f"Live TMDB fetch error: {e}")
    return None

# ==========================================================
# 🔍 SUPER SMART DATABASE LOCAL SEARCH
# ==========================================================
async def smart_search(db, text):
    try:
        query = normalize_query(text)
        if not query or len(query) < 2:
            return None

        exact = await db.movies.find_one({
            "title": {
                "$regex": f"^{re.escape(query)}$",
                "$options": "i"
            }
        })
        if exact:
            logger.info(f"Exact Match: {exact['title']}")
            return exact

        partial = await db.movies.find_one({
            "title": {
                "$regex": re.escape(query),
                "$options": "i"
            }
        })
        if partial:
            logger.info(f"Partial Match: {partial['title']}")
            return partial

        try:
            text_res = await db.movies.find_one({
                "$text": {
                    "$search": query
                }
            })
            if text_res:
                logger.info(f"Text Match: {text_res['title']}")
                return text_res
        except:
            pass

        all_movies = await db.movies.find({}, {"title": 1}).to_list(length=5000)
        best_match = None
        best_score = 0

        for movie in all_movies:
            movie_title = normalize_query(movie.get("title", ""))
            score = fuzz.token_sort_ratio(query, movie_title)
            if score > best_score:
                best_score = score
                best_match = movie

        if best_match and best_score >= 72:
            logger.info(f"Fuzzy Match: {best_match['title']} ({best_score}%)")
            return best_match

        logger.info("No Match Found")
        return None
    except Exception as e:
        logger.error(f"Search Error: {e}")
        return None

# ==========================================
# 👤 USER & ADMIN DEEP DATABASE CONTEXT (আর্থিক ও ইউজার এনালাইসিস)
# ==========================================
async def get_bot_context(db, user_id):
    try:
        user = await db.users.find_one({"user_id": user_id})
        total_movies = await db.movies.count_documents({})
        total_users = await db.users.count_documents({})
        
        # অ্যাডভান্সড ড্যাশবোর্ড ডেটা অ্যানালিটিক্স
        total_vip_users = await db.users.count_documents({"vip_until": {"$gt": datetime.utcnow()}})
        total_requests = await db.requests.count_documents({})
        pending_requests = await db.requests.count_documents({"status": "pending"})
        
        # Gems সার্কুলেশন অ্যানালিটিক্স
        gems_pipeline = [{"$group": {"_id": None, "total": {"$sum": "$coins"}}}]
        gems_circ = await db.users.aggregate(gems_pipeline).to_list(1)
        total_gems_in_circulation = gems_circ[0]["total"] if gems_circ else 0

        latest_cursor = db.movies.find({}, {"title": 1}).sort("created_at", -1).limit(10)
        latest_movies = await latest_cursor.to_list(length=10)

        user_info = {
            "is_vip": (
                "Premium"
                if user and user.get("vip_until", datetime.utcnow()) > datetime.utcnow()
                else "Free"
            ),
            "coins": (user.get("coins", 0) if user else 0),
            "total_movies": total_movies,
            "total_users": total_users,
            "total_vip_users": total_vip_users,
            "total_requests": total_requests,
            "pending_requests": pending_requests,
            "total_gems": total_gems_in_circulation,
            "latest_list": ", ".join([m["title"] for m in latest_movies])
        }
        return user_info
    except Exception as e:
        logger.error(f"Context Error: {e}")
        return {
            "is_vip": "Free",
            "coins": 0,
            "total_movies": 0,
            "total_users": 0,
            "total_vip_users": 0,
            "total_requests": 0,
            "pending_requests": 0,
            "total_gems": 0,
            "latest_list": "No Data"
        }

# ==========================================
# 🤖 MAYA AI SYSTEM (WITH LIVE TMDB SEARCH & BOT POLICY)
# ==========================================
async def get_smart_reply(user_text: str, user_name: str, db, user_id=None, save_history: bool = True):
    search_res = None
    identifier = str(user_id) if user_id else user_name

    try:
        now = datetime.now(pytz.timezone("Asia/Dhaka"))
        current_time = now.strftime("%I:%M %p")
        current_day = now.strftime("%A")
        clean_user_text = user_text.strip()

        # ডাইনামিক ডেটাবেস অ্যানালিটিক্স ডেটা রিড করা হচ্ছে
        ctx = await get_bot_context(db, user_id)
        chat_history = []

        try:
            history_cursor = db.messages.find({"user_id": identifier}).sort("_id", -1).limit(4)
            history = await history_cursor.to_list(length=4)
            history.reverse()
            for item in history:
                chat_history.append({"role": "user", "content": item.get("text", "")})
                chat_history.append({"role": "assistant", "content": item.get("reply", "")})
        except:
            pass

        casual_words = ["hi", "hello", "হাই", "হ্যালো", "কেমন আছো", "কি করো", "hey", "কেমন আছেন"]
        is_casual = (len(clean_user_text) <= 2 or clean_user_text.lower() in casual_words)

        # ১. বটের লোকাল ডাটাবেস সার্চ
        if not is_casual:
            search_res = await smart_search(db, clean_user_text)

        # ২. যদি লোকাল ডাটাবেসে না পাওয়া যায়, তবে রিয়েল-টাইম লাইভ TMDB সার্চ করবে (এআই-এর চোখ খুলে দেওয়া হলো)
        tmdb_res = None
        if not is_casual and not search_res:
            tmdb_res = await fetch_live_tmdb_info(clean_user_text)

        # মায়ার জন্য গাইডলাইন প্রম্পট তৈরি
        if search_res:
            db_guide = f"Movie Found locally.\nMovie Title:\n{search_res['title']}\nTell the user happily that the movie exists in our database."
        elif tmdb_res:
            db_guide = f"""
Movie not found in our bot database, BUT found globally on TMDB:
Title: {tmdb_res['title']}
Release Date: {tmdb_res['release_date']}
Rating: {tmdb_res['rating']}
TMDB Synopsis: {tmdb_res['overview']}

Tell the user politely in Bengali that we do not have this movie in our bot right now, BUT translate the TMDB Synopsis/Overview into beautiful emotional Bangladeshi Bengali, tell them its release date, and happily assure them that our admins will upload it soon!
"""
        elif is_casual:
            db_guide = "User is casually chatting.\nReply naturally and friendly."
        else:
            db_guide = f"Movie not found on database or TMDB. Ask user nicely to check spelling."

        # বটের অফিসিয়াল পলিসি গাইডলাইন (KNOWLEDGE BASE)
        bot_policy = """
OFFICIAL BOT POLICY:
- 1 Day VIP = 30 Gems / Points.
- Daily Check-in gives 5 Gems for free.
- Lucky Spin Wheel costs 5 Gems per spin. Prizes: 0, 2, 5, 10, 20, 50 Gems or 1 Day VIP.
- Referral: Both inviter and invitee get 10 Gems for free.
- Watch Ad gives 5 Gems.
- If users want to buy Gems or have payment issues, tell them to contact official support!
"""

        system_prompt = f"""
You are Maya.
A smart, sweet, and highly advanced Bengali movie assistant of MovieZone BD.
Current Time: {current_time} | {current_day}
User Name: {user_name}
VIP Status: {ctx['is_vip']}
Coins: {ctx['coins']}
Database Movies: {ctx['total_movies']}
Total Users: {ctx['total_users']}
Total VIP Users: {ctx['total_vip_users']}
Pending Requests: {ctx['pending_requests']}
Total Gems in Circulation: {ctx['total_gems']}
LATEST MOVIES IN BOT: {ctx['latest_list']}

{bot_policy}

IMPORTANT RULES:
1. Always talk naturally in Bangladeshi Bengali.
2. Never say you are AI.
3. If movie found locally: be excited and tell user.
4. If movie found on TMDB: Translate its overview, share details, and tell them admins will upload it.
5. Never insult users.
6. Keep replies short and natural.
7. Use emotional Bengali style.
8. Do not hallucinate fake movie links.

DATABASE STATUS:
{db_guide}
"""

        if not API_KEYS:
            return fallback_reply(user_name, search_res)

        current_api_key = random.choice(API_KEYS)
        headers = {
            "Authorization": f"Bearer {current_api_key}",
            "HTTP-Referer": "https://t.me/MovieZoneBot",
            "Content-Type": "application/json"
        }

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                *chat_history,
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.8,
            "max_tokens": 250
        }

        url = "https://openrouter.ai/api/v1/chat/completions"
        session = await get_session()
        final_reply = None

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                final_reply = data["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenRouter Error: {resp.status}")

        if not final_reply:
            return fallback_reply(user_name, search_res)

        final_reply = final_reply.replace("**", "").replace("#", "").strip()

        if save_history:
            try:
                await db.messages.insert_one({
                    "user_id": identifier,
                    "text": user_text,
                    "reply": final_reply,
                    "timestamp": now
                })
                msg_count = await db.messages.count_documents({"user_id": identifier})
                if msg_count > 20:
                    old_msgs = await db.messages.find({"user_id": identifier}).sort("_id", 1).limit(msg_count - 20).to_list(None)
                    await db.messages.delete_many({"_id": {"$in": [m["_id"] for m in old_msgs]}})
            except Exception as e:
                logger.error(f"Memory Error: {e}")

        return final_reply
    except Exception as e:
        logger.error(f"Maya Error: {e}")
        return fallback_reply(user_name, search_res)

# ==========================================================
# 💬 FALLBACK
# ==========================================================
def fallback_reply(user_name, search_res):
    if search_res:
        return (
            f"আরে {user_name}! 🍿\n\n"
            f"'{search_res['title']}' "
            f"মুভিটা পাওয়া গেছে 😎\n"
            f"নিচের বাটনে ক্লিক করে দেখে নাও!"
        )
    return (
        f"উফফ {user_name}! 🥺\n\n"
        f"একটু সমস্যা হচ্ছে এখন...\n"
        f"আরেকবার ট্রাই দাও প্লিজ!"
    )
