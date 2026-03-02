from fastapi import FastAPI
import os
import asyncpg

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")


@app.on_event("startup")
async def startup():
    app.state.db = await asyncpg.connect(DATABASE_URL)

    await app.state.db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE,
            subscription TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


@app.get("/")
async def home():
    return {"status": "Bot Builder is running 🚀"}


@app.get("/users")
async def users():
    rows = await app.state.db.fetch("SELECT * FROM users;")
    return [dict(r) for r in rows]
