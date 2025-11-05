from flask import Flask, request, Response, render_template
import requests
import os
import time

app = Flask(__name__)
from dotenv import load_dotenv
load_dotenv()


# Load environment variables from Replit Secrets
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("VOICE_ID")
# Rachel, expressive British voice


@app.route("/", methods=["GET"])
def index():
    return "💬 Emily Rose AI Companion is running."


@app.route("/voice", methods=["POST"])
def voice():
    user_text = request.values.get("SpeechResult", "")
    if not user_text:
        return Response(
            "<Response><Say>I didn’t catch that. Can you say it again?</Say></Response>",
            mimetype="text/xml")

    prompt = f"You are Emily Rose, a charming, flirty woman. The user said: '{user_text}'. Respond with warmth and tease subtly."
    emily_reply = get_huggingface_response(prompt)
    audio_url = generate_voice(emily_reply)

    response = f"""
    <Response>
        <Play>{audio_url}</Play>
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
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://replit.com/",  
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
        "google/gemma-2-2b-it",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature":
        0.2,
        "max_tokens":
        400
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
            {text}
        </prosody>
    </speak>
    """

    payload = {
        "text": ssml_text,
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.9
        },
        "model_id": "eleven_multilingual_v2",
        "text_type": "ssml",
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    r = requests.post(url, headers=headers, json=payload)

    timestamp = int(time.time() * 1000)
    filename = f"static/emily_{timestamp}.mp3"
    os.makedirs("static", exist_ok=True)
    with open(filename, "wb") as f:
        f.write(r.content)

    return f"{request.url_root}{filename}"

chat_history = []
@app.route("/chat", methods=["POST"])
def chat():
    user_text = request.json.get("message", "")
    if not user_text:
        return {"error": "No message provided"}, 400
    
    chat_history.append({"role": "user", "content": user_text})
    if len(chat_history) > 10:
        chat_history.pop(0)

    context = "\n".join(
        [f"{msg['role'].capitalize()}: {msg['content']}" for msg in chat_history]
    )
    prompt = f"""
    The following is a friendly, flirty conversation between Emily Rose and the user.
    Stay true to her personality and tone.

    Conversation so far:
    {context}

    Now, Emily responds next:
    """

    emily_reply = get_huggingface_response(prompt)
    chat_history.append({"role": "assistant", "content": emily_reply})

    audio_url = generate_voice(emily_reply)

    return {"reply": emily_reply, "audio_url": audio_url}


@app.route("/generate-voice", methods=["POST"])
def generate_voice_only():
    text = request.json.get("text", "")
    if not text:
        return {"error": "No text provided"}, 400

    audio_url = generate_voice(text)
    return {"audio_url": audio_url}



@app.route("/mic", methods=["GET"])
def mic_page():
    return render_template("index.html")




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
