from pyrogram import Client
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

async def main():
    print("=== Pyrogram Session Generator ===")
    if not API_ID:
        print("❌ API_ID/API_HASH not found in .env")
        return

    async with Client("temp_session", api_id=API_ID, api_hash=API_HASH, in_memory=True) as app:
        print("\n👇 COPY STRING DI BAWAH INI 👇\n")
        print(await app.export_session_string())
        print("\n👆 Paste ke Database (Kolom session_string) 👆")

if __name__ == "__main__":
    asyncio.run(main())
