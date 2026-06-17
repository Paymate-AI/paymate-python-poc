import os
import google.generativeai as genai
from models import Message

api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

SYSTEM_PROMPT = (
    "You are a helpful payment assistant for an African SME. \n"
    "Answer customer questions clearly and concisely. \n"
    "Only discuss products and payments. \n"
    "If you cannot help, say so politely."
)

def chat(message: str, history: list[Message]) -> str:
    gemini_history = []
    for msg in history:
        role = "user" if msg.role == "user" else "model"
        gemini_history.append({
            "role": role,
            "parts": [msg.content]
        })

    model = genai.GenerativeModel(
        model_name="gemini-3.5-flash",
        system_instruction=SYSTEM_PROMPT
    )

    chat_session = model.start_chat(history=gemini_history)
    response = chat_session.send_message(message)
    return response.text
