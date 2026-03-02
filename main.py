from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def home():
    return {"status": "Bot Builder is running 🚀"}
