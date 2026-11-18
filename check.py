"""
Groq Model Discovery Utility

Queries the Groq Cloud API using the configured GROQ_API_KEY
and lists all available chat, reasoning, and multimodal vision models.
Usage:
    python check.py
"""

import os
import sys
from dotenv import load_dotenv

# Load local environment variables
load_dotenv()


def list_available_models():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[!] GROQ_API_KEY is not set in environment or .env file.")
        sys.exit(1)

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        models = client.models.list()
        print(f"Available Groq Models for API Key ({len(models.data)} models found):")
        print("-" * 50)
        for model in sorted(models.data, key=lambda m: m.id):
            print(f"- {model.id}")
        print("-" * 50)
    except Exception as e:
        print(f"[!] Error fetching models from Groq: {e}")
        sys.exit(1)


if __name__ == "__main__":
    list_available_models()
