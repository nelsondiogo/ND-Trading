import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return """
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>nd-bot v8</title>
    </head>
    <body style="background:#0b0f19; color:white; font-family:Arial; text-align:center; padding-top:50px;">
        <h1 style="color:#4ade80;">nd-bot v8 Online com Sucesso!</h1>
        <p>O servidor está a operar corretamente na porta do Render.</p>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
