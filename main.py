from fastapi import FastAPI, Body
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
    rows = await app.state.db.fetch("SELECT telegram_id, subscription FROM users ORDER BY id DESC")
    return [{"telegram_id": r["telegram_id"], "subscription": r["subscription"]} for r in rows]

@app.post("/create-user")
async def create_user(payload: dict = Body(...)):
    telegram_id = int(payload["telegram_id"])
    try:
        await app.state.db.execute(
            "INSERT INTO users (telegram_id, subscription) VALUES ($1, $2)",
            telegram_id,
            "free"
        )
        return {"status": "user created"}
    except Exception:
        return {"status": "user already exists"}
       
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
