# server.py — SERVER MS II (blindado contra 404 triviais)
import os, logging
from typing import Optional
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

APP_NAME = os.getenv("PROJECT_NAME", "server_ms_ii")

def create_app() -> Flask:
    app = Flask(__name__)
    # aceita /rota e /rota/
    app.url_map.strict_slashes = False

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger(APP_NAME)

    @app.route("/", methods=["GET"])
    def root():
        # se abrir a raiz no navegador, não dá 404
        return Response("OK / (root) – use /bot (GET/POST) ou /admin/ping", 200, mimetype="text/plain")

    @app.route("/admin/ping", methods=["GET"])
    def admin_ping():
        return Response("OK /admin/ping", 200, mimetype="text/plain")

    @app.route("/bot", methods=["GET", "POST"])
    def bot():
        if request.method == "GET":
            log.info("GET /bot -> 200 (health-check)")
            return Response("OK /bot (GET) – use POST via Twilio", 200, mimetype="text/plain")

        body: str = (request.values.get("Body") or "").strip()
        sender: str = request.values.get("From", "")
        waid: Optional[str] = request.values.get("WaId")
        log.info(f"POST /bot <- From={sender} WaId={waid} Body='{body}'")

        reply_text = build_reply(body=body, sender=sender)
        twiml = MessagingResponse()
        twiml.message(reply_text)
        return Response(str(twiml), 200, mimetype="application/xml")

    # handler de 404 amigável
    @app.errorhandler(404)
    def not_found(_e):
        return Response("404 – rota não encontrada. Use /bot ou /admin/ping", 404, mimetype="text/plain")

    return app

def build_reply(body: str, sender: str) -> str:
    text = body.lower()
    if text in {"ping", "status", "up"}:
        return "✅ Online.\nUse 'menu' para ver opções."
    if text in {"menu", "ajuda", "help"}:
        return (
            "📋 Menu — SERVER MS II\n"
            "1) 'ping' — checar status\n"
            "2) Qualquer texto — eco simples\n"
            "— Ajuste o fluxo aqui conforme seu projeto —"
        )
    preview = (body[:400] + "…") if len(body) > 400 else body
    return f"Recebido ✅\nDe: {sender}\nMensagem: {preview}"

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    try:
        from waitress import serve
        print(f"[{APP_NAME}] Servindo com waitress em http://{host}:{port}")
        serve(app, host=host, port=port)
    except Exception:
        print(f"[{APP_NAME}] Waitress não encontrada — usando Flask dev server em http://{host}:{port}")
        app.run(host=host, port=port, debug=False)