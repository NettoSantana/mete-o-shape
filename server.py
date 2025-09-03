# server.py — SERVER MS II
# Objetivo:
# - Endpoint /bot aceita GET (health-check) e POST (Twilio WhatsApp)
# - GET /bot -> 200 OK texto simples
# - POST /bot -> responde TwiML (XML) ao WhatsApp
# - /admin/ping -> 200 OK (ping alternativo)
#
# Execução:
# - Local: python server.py
# - Produção (recomendado): waitress-serve --host=0.0.0.0 --port=$PORT server:app

import os
import logging
from typing import Optional
from flask import Flask, request, Response

# Twilio (somente para responder via TwiML no webhook)
from twilio.twiml.messaging_response import MessagingResponse

# -----------------------------------------------------------------------------
# Configuração básica
# -----------------------------------------------------------------------------
APP_NAME = os.getenv("PROJECT_NAME", "server_ms_ii")

def create_app() -> Flask:
    app = Flask(__name__)

    # Logs mais limpos no console
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    log = logging.getLogger(APP_NAME)

    # -------------------------------------------------------------------------
    # Health-check simples
    # -------------------------------------------------------------------------
    @app.route("/admin/ping", methods=["GET"])
    def admin_ping():
        # Alternativa de health-check explícito
        return Response("OK /admin/ping", status=200, mimetype="text/plain")

    # -------------------------------------------------------------------------
    # Webhook WhatsApp (Twilio) — aceita GET e POST
    # -------------------------------------------------------------------------
    @app.route("/bot", methods=["GET", "POST"])
    def bot():
        # 1) GET: health-check/monitor/navegador
        if request.method == "GET":
            log.info("GET /bot -> 200 (health-check)")
            return Response("OK /bot (GET) – use POST via Twilio", status=200, mimetype="text/plain")

        # 2) POST: Twilio entrega a mensagem
        # Campos típicos do Twilio:
        # - Body: texto da mensagem
        # - From: remetente (whatsapp:+55...)
        # - WaId: id WhatsApp
        body: str = (request.values.get("Body") or "").strip()
        sender: str = request.values.get("From", "")
        waid: Optional[str] = request.values.get("WaId")

        log.info(f"POST /bot <- From={sender} WaId={waid} Body='{body}'")

        # Lógica simples de resposta (personalize à vontade)
        reply_text = build_reply(body=body, sender=sender)

        # Monta TwiML
        twiml = MessagingResponse()
        twiml.message(reply_text)

        # Retorna em XML (obrigatório para Twilio interpretar)
        return Response(str(twiml), status=200, mimetype="application/xml")

    return app


def build_reply(body: str, sender: str) -> str:
    """
    Lógica básica de resposta.
    Ajuste conforme o fluxo do seu bot.
    """
    text = body.lower()

    # Comandos simples (exemplos)
    if text in {"ping", "status", "up"}:
        return "✅ Online.\nUse 'menu' para ver opções."
    if text in {"menu", "ajuda", "help"}:
        return (
            "📋 Menu — SERVER MS II\n"
            "1) 'ping' — checar status\n"
            "2) Qualquer texto — eco simples\n"
            "— Ajuste o fluxo aqui conforme seu projeto —"
        )

    # Fallback: eco curto
    preview = (body[:400] + "…") if len(body) > 400 else body
    return f"Recebido ✅\nDe: {sender}\nMensagem: {preview}"


# -----------------------------------------------------------------------------
# Instância do app
# -----------------------------------------------------------------------------
app = create_app()

# -----------------------------------------------------------------------------
# Main (dev) — usa waitress se disponível
# -----------------------------------------------------------------------------
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
