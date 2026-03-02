from fastapi import FastAPI
import asyncpg
import os

app = FastAPI()

@app.on_event("startup")
async def startup():
    app.state.db = await asyncpg.connect(os.environ["DATABASE_URL"])
    await app.state.db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            subscription TEXT DEFAULT 'free'
        );
    """)

@app.get("/")
async def home():
    return {"status": "Bot Builder is running 🚀"}

@app.get("/users")
async def get_users():
    rows = await app.state.db.fetch(
        "SELECT telegram_id, subscription FROM users ORDER BY id DESC"
    )
    return [
        {"telegram_id": r["telegram_id"], "subscription": r["subscription"]}
        for r in rows
    ]

@app.get("/add-test-user")
async def add_test_user():
    try:
        await app.state.db.execute(
            "INSERT INTO users (telegram_id, subscription) VALUES ($1, $2)",
            999999,
            "free"
        )
        return {"status": "test user added"}
    except:
        return {"status": "already exists"}
