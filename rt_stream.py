import base64
import json
import asyncio
from fastapi import FastAPI, WebSocket
from groq import Groq
import requests
import os
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
ELEVEN_API = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("VOICE_ID")

DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------
# DATABASE CONNECTION POOL
# ---------------------------
db_pool = None
if DATABASE_URL:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)


def load_name_from_db(phone):
    if not db_pool:
        return None

    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("""
            SELECT message FROM call_history
            WHERE phone_number=%s AND role='name'
            ORDER BY id DESC LIMIT 1
        """, (phone,))
        row = cur.fetchone()
        cur.close()
        db_pool.putconn(conn)

        return row[0] if row else None

    except Exception as e:
        print("DB error:", e)
        return None


app = FastAPI()


@app.websocket("/stream")
async def stream_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔗 Twilio connected")

    audio_buffer = b""
    greeted = False
    phone_number = None

    while True:
        msg = await websocket.receive()

        if "text" in msg:
            data = json.loads(msg["text"])
        else:
            continue

        # ----------------------------------
        # START EVENT → SEND GREETING
        # ----------------------------------
        if data["event"] == "start":
            phone_number = data["start"]["customParameters"].get("caller")
            print("📞 Caller:", phone_number)

            user_name = load_name_from_db(phone_number)

            if user_name:
                greeting = (
                    f"Hey {user_name}, it’s Emily. How are you? "
                    "It’s great to finally chat. How’s your day going?"
                )
            else:
                greeting = (
                    "Hey, it’s Emily. How are you? It’s great to finally chat. "
                    "How’s your day going?"
                )

            print("🎙 Sending greeting:", greeting)

            async for chunk in eleven_stream(greeting):
                await websocket.send_json({
                    "event": "media",
                    "media": {"payload": base64.b64encode(chunk).decode()}
                })

            greeted = True
            continue

        # ----------------------------------
        # MEDIA EVENT → AUDIO STREAMING
        # ----------------------------------
        if data["event"] == "media":
            pcm_b64 = data["media"]["payload"]
            audio_buffer += base64.b64decode(pcm_b64)

        # ----------------------------------
        # STOP EVENT → PROCESS USER SPEECH
        # ----------------------------------
        if data["event"] == "stop":
            print("🎤 User stopped — transcribing...")
            user_text = transcribe(audio_buffer)
            audio_buffer = b""  # reset

            print("User said:", user_text)

            reply = generate_reply(user_text)
            print("Emily:", reply)

            async for chunk in eleven_stream(reply):
                await websocket.send_json({
                    "event": "media",
                    "media": {"payload": base64.b64encode(chunk).decode()}
                })

        # ----------------------------------
        # CLOSE EVENT
        # ----------------------------------
        if data["event"] == "close":
            print("❌ WebSocket closed")
            break


# ----------------------------------
# STT (Groq Whisper)
# ----------------------------------
def transcribe(audio_bytes):
    try:
        result = groq_client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes),
            model="whisper-large-v3"
        )
        return result.text
    except Exception as e:
        print("Transcription error:", e)
        return ""


# ----------------------------------
# LLM RESPONSE
# ----------------------------------
def generate_reply(user_text):
    system_prompt = """
    You are Emily Rose — warm, flirty, playful British woman.
    Keep responses short, sweet, and affectionate.
    """

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        max_tokens=60,
        temperature=0.6
    )
    return response.choices[0].message.content.strip()


# ----------------------------------
# ElevenLabs TTS STREAMING
# ----------------------------------
async def eleven_stream(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"

    headers = {
        "xi-api-key": ELEVEN_API,
        "Content-Type": "application/json"
    }

    payload = {
        "text": text,
        "voice_settings": {
            "stability": 0.3,
            "similarity_boost": 0.85
        },
        "model_id": "eleven_turbo_v2_5",
        "optimize_streaming_latency": 4,
        "output_format": "pcm_16000"
    }

    with requests.post(url, json=payload, headers=headers, stream=True) as r:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                yield chunk
