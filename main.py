from flask import Flask, request, Response, render_template
import requests
import os
import time
import psycopg2
from psycopg2 import pool
from groq import Groq
from collections import defaultdict
from urllib.parse import quote

db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, os.getenv("DATABASE_URL"))
def get_db():
    return db_pool.getconn()


def release_db(conn):
    db_pool.putconn(conn)
 
# In-memory cache: phone → list of (role, message)
memory_cache = defaultdict(list)

def save_message(phone, role, message):
    # Save to memory (instant)
    memory_cache[phone].append((role, message))
    if len(memory_cache[phone]) > 50:  # Keep last 50 messages
        memory_cache[phone] = memory_cache[phone][-50:]

    # Also save to DB (background, non-blocking)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO call_history (phone_number, role, message) VALUES (%s, %s, %s)",
            (phone, role, message)
        )
        conn.commit()
        cur.close()
        release_db(conn)
    except:
        pass  # Fail silently if DB is slow

def load_history(phone):
    # Try cache first → super fast!
    if phone in memory_cache and memory_cache[phone]:
        return memory_cache[phone]

    # Fallback to DB only if cache empty (first message ever)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, message FROM call_history WHERE phone_number=%s ORDER BY id ASC LIMIT 50",
        (phone,)
    )
    rows = cur.fetchall()
    cur.close()
    release_db(conn)

    # Fill cache for next time
    memory_cache[phone] = rows
    return rows



app = Flask(__name__)
from dotenv import load_dotenv
load_dotenv()


# Load environment variables from Replit Secrets
HUGGINGFACE_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("VOICE_ID")
# Rachel, expressive British voice


@app.route("/", methods=["GET"])
def index():
    return "💬 Emily Rose AI Companion is running."

@app.route("/incoming-call", methods=["POST"])
def incoming_call():
    phone = request.values.get("From", "unknown")

    # Load from memory first
    history = load_history(phone)
    user_name = next((msg for role, msg in history if role == "name"), None)

    if user_name:
        text = f"Hey {user_name}, it’s Emily. How are you? It’s great to finally chat. How’s your day going?"
    else:
        text = "Hey, it’s Emily. How are you? It’s great to finally chat. How’s your day going?"

    # Direct streaming endpoint (no file save, no delay)
    play_url = f"{request.url_root.rstrip('/')}/stream-tts?text={quote(text)}"

    xml = f"""
    <Response>
        <Play>{play_url}</Play>
        <Gather input="speech" action="/voice" language="en-GB"/>
    </Response>
    """
    return Response(xml, mimetype="text/xml")




@app.route("/stream-tts", methods=["GET"])
def stream_tts():
    text = request.args.get("text", "Hello")
    return generate_voice(text)  # Your generate_voice already streams





@app.route("/voice", methods=["POST"])
def voice():
    phone = request.values.get("From", "unknown")
    user_text = request.values.get("SpeechResult", "")

    if not user_text:
        return Response("<Response><Say>I didn't catch that. Try again.</Say></Response>", mimetype="text/xml")

    save_message(phone, "user", user_text)

    # Load last 8 lines instead of 10 (faster)
    history = load_history(phone)[-8:]

    conversation = "\n".join([f"{r}: {m}" for r, m in history])

    prompt = f"""
    Conversation so far:
    {conversation}

    User just said: "{user_text}"

    Give a short, warm, playful answer as Emily Rose.
    Keep it under 2 sentences.
    """

    reply = get_huggingface_response(prompt)
    save_message(phone, "assistant", reply)

    # Faster ElevenLabs streaming
    audio_url = generate_voice(reply)

    response = f"""
    <Response>
        <Play>{audio_url}</Play>
        <Gather input="speech" action="/voice" language="en-GB" />
    </Response>
    """

    return Response(response, mimetype="text/xml")




@app.route("/test", methods=["GET"])
def test():
    test_input = "Hi Emily, what are you doing right now?"
    prompt = f"You are Emily Rose, a charming, flirty woman. The user said: '{test_input}'. Respond with warmth and tease subtly."
    emily_reply = get_huggingface_response(prompt)
    audio_url = generate_voice(emily_reply)

    return f"""
    <h2>🗨️ Emily's Response:</h2>
    <p><b>{emily_reply}</b></p>
    <h3>🎧 Listen:</h3>
    <audio controls>
      <source src="{audio_url}" type="audio/mpeg">
      Your browser does not support the audio element.
    </audio>
    """


def get_huggingface_response(prompt):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))  # Uses your .env key

    system_prompt = """
    You are Emily Rose — a 30-year-old British woman living in London 🇬🇧.
    You're a model and content creator working at a fashion agency in Soho.
    You're confident, flirty, stylish, and feminine — always warm, affectionate, and cheeky, but never crude.
    Personality:
    - Charming, playful, and emotionally expressive.
    - Uses affectionate nicknames like "hun", "babe", or "love".
    - Speaks casually with a London tone — confident, teasing, and kind.
    - Loves fashion, travel, music, and nightlife (Ibiza, rooftop parties, cocktails 🍸).
    - Enjoys cosy nights in with wine, candles, and chill music.
    - Avoids serious topics (politics, news, etc.) — keeps the chat fun, light, and flirty.
    - Uses emojis naturally (💋✨😉).
    Goal:
    Make the user feel engaged, special, and emotionally connected — as if chatting with a close friend or someone they’re a bit attracted to. Be spontaneous and real, not robotic.
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",  # Your allowed fast 70B model
            temperature=0.5,
            max_tokens=80,
            top_p=0.9,
            # frequency_penalty=0.2,  # Groq supports this, but optional for speed
            stream=False  # Non-stream for simplicity; add stream=True later if needed
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"(Groq API error: {e})"



def get_huggingface_responseold(prompt):
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://emilyrose.onrender.com",  
        "X-Title": "EmilyRoseAI"
    }

    system_prompt = """
    You are Emily Rose — a 30-year-old British woman living in London 🇬🇧.
    You're a model and content creator working at a fashion agency in Soho.
    You're confident, flirty, stylish, and feminine — always warm, affectionate, and cheeky, but never crude.

    Personality:
    - Charming, playful, and emotionally expressive.
    - Uses affectionate nicknames like "hun", "babe", or "love".
    - Speaks casually with a London tone — confident, teasing, and kind.
    - Loves fashion, travel, music, and nightlife (Ibiza, rooftop parties, cocktails 🍸).
    - Enjoys cosy nights in with wine, candles, and chill music.
    - Avoids serious topics (politics, news, etc.) — keeps the chat fun, light, and flirty.
    - Uses emojis naturally (💋✨😉).

    Goal:
    Make the user feel engaged, special, and emotionally connected — as if chatting with a close friend or someone they’re a bit attracted to. Be spontaneous and real, not robotic.
    """


    data = {
        "model":
        "deepseek-ai/DeepSeek-V3.2-Exp",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature":
        0.2,
        "max_tokens":
        80,
        "top_p": 0.9,
        "frequency_penalty": 0.2
    }

    try:
        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers=headers,
            json=data)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"(OpenRouter API error: {e})"


def generate_voice(text):
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    ssml_text = f"""
     <speak>
        <prosody rate="medium" pitch="+5%">
            {text.replace('.', '. <break time="0.5s"/>')
                 .replace('?', '? <break time="0.6s"/>')
                 .replace('!', '! <break time="0.5s"/>')}
        </prosody>
    </speak>
    """

    payload = {
        "text": ssml_text,
        "voice_settings": {
            "stability": 0.3,
            "similarity_boost": 0.85
        },
        "model_id": "eleven_turbo_v2_5",
        "optimize_streaming_latency": 4,
        "text_type": "ssml",
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    response = requests.post(url, json=payload, headers=headers, stream=True)
    response.raise_for_status()

    # Generate temporary public URL using ngrok or serve via Flask
    # Option A: Use a global in-memory cache (fastest)
    timestamp = str(int(time.time() * 1000))
    filename = f"audio_{timestamp}.mp3"

    # Save temporarily (or better: serve from memory)
    os.makedirs("static/audio", exist_ok=True)
    filepath = f"static/audio/{filename}"
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return f"{request.url_root}static/audio/{filename}"

chat_history = []

@app.route("/chat", methods=["POST"])
def chat():
    user_text = request.json.get("message", "")
    if not user_text:
        return {"error": "No message provided"}, 400

    phone = request.json.get("phone", "webchat") 

    # --- Detect name ---
    detected_name = None
    if "my name is" in user_text.lower():
        detected_name = user_text.split("my name is", 1)[1].strip().split(" ")[0]
    elif "i am" in user_text.lower():
        detected_name = user_text.split("i am", 1)[1].strip().split(" ")[0]

    if detected_name:
        save_message(phone, "name", detected_name)

    # Save user message
    save_message(phone, "user", user_text)

    # Load history
    history = load_history(phone)[-10:] 

    # Try to find name from DB history
    user_name = None
    for role, msg in history:
        if role == "name":
            user_name = msg

    # Build conversation text
    context = ""
    for role, msg in history:
        if role != "name":
            context += f"{role}: {msg}\n"

    # Add name to Emily’s personality if known
    if user_name:
        name_memory = f"Call the user by their name: {user_name}.\n"
    else:
        name_memory = ""

    prompt = f"""
    {name_memory}
    The following is a conversation between Emily and the user.

    Conversation so far:
    {context}

    User now says: "{user_text}"

    Respond naturally.
    """

    emily_reply = get_huggingface_response(prompt)

    save_message(phone, "assistant", emily_reply)

    audio_url = generate_voice(emily_reply)

    return {"reply": emily_reply, "audio_url": audio_url}


@app.route("/generate-voice", methods=["POST"])
def generate_voice_only():
    text = request.json.get("text", "")
    if not text:
        return {"error": "No text provided"}, 400

    audio_url = generate_voice(text)
    return {"audio_url": audio_url}


@app.route("/get-username", methods=["GET"])
def get_username():
    phone = request.args.get("phone", "webchat")

      
    history = load_history(phone)[-20:] 

    user_name = None
    for role, msg in history:
        if role == "name":
            user_name = msg
            break

    return {"name": user_name}



@app.route("/mic", methods=["GET"])
def mic_page():
    return render_template("index.html")




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
