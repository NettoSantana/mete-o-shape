# server.py — webhook WhatsApp + healthcheck
import os
import logging
from typing import Optional
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

APP_NAME = os.getenv("PROJECT_NAME", "mete_o_shape")

def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger(APP_NAME)

    @app.route("/", methods=["GET"])
    def root():
        return Response("OK / (root) – use /bot (GET/POST) ou /admin/ping", 200, mimetype="text/plain")

    @app.route("/admin/ping", methods=["GET"])
    def admin_ping():
        return Response("OK /admin/ping", 200, mimetype="text/plain")

    @app.route("/bot", methods=["GET", "POST"])
    def bot():
        if request.method == "GET":
            log.info("GET /bot -> 200 (health-check)")
            return Response("OK /bot (GET) – use POST via Twilio", 200, mimetype="text/plain")

        # POST do Twilio
        body: str = (request.values.get("Body") or "").strip()
        sender: str = request.values.get("From", "")
        waid: Optional[str] = request.values.get("WaId")
        log.info(f"POST /bot <- From={sender} WaId={waid} Body='{body}'")

        reply_text = build_reply(body=body, sender=sender)

        twiml = MessagingResponse()
        twiml.message(reply_text)
        return Response(str(twiml), 200, mimetype="application/xml")

    @app.errorhandler(404)
    def not_found(_e):
        return Response("404 – rota não encontrada. Use /bot ou /admin/ping", 404, mimetype="text/plain")

    return app


# ===== SUA LÓGICA DE RESPOSTA (mantive sua versão refatorada) =====
def build_reply(body: str, sender: str) -> str:
    """
    Responde mensagens recebidas via WhatsApp.
    - 'menu' ou '0' → mostra o menu principal
    - '1' → Mete o Shape
    - '2' → Cardápio/Pedidos
    - '3' → Assistente Educacional
    - 'ping' → healthcheck
    - fallback → instrução para voltar ao menu
    """
    text = (body or "").strip().lower()

    # Respostas de cada módulo
    menus = {
        "1": (
            "🏋️ METE O SHAPE\n"
            "Status: esqueleto ativo ✅\n"
            "➡️ Fluxo: Anamnese → Macros → Cardápio/Treino diário.\n"
            "Digite 'menu' para voltar."
        ),
        "2": (
            "🍔 CARDÁPIO/PEDIDOS\n"
            "Fluxo híbrido: abra o cardápio (HTML), monte seu carrinho e finalize.\n"
            "➡️ O pedido é registrado no WhatsApp e atualizado por status.\n"
            "Digite 'menu' para voltar."
        ),
        "3": (
            "📚 ASSISTENTE EDUCACIONAL\n"
            "Fluxo: Matemática → Português → Leitura (90 dias).\n"
            "➡️ Pronto para ativar Leitura.\n"
            "Digite 'menu' para voltar."
        ),
    }

    # Healthcheck
    if text in {"ping", "status", "up"}:
        return "✅ Online.\nDigite 'menu' para ver as opções."

    # Menu principal
    if text in {"menu", "0"}:
        opcoes = "\n".join(
            [
                "1️⃣ 🏋️ Mete o Shape — treino/dieta via WhatsApp",
                "2️⃣ 🍔 Cardápio/Pedidos — escolher no site e fechar pelo WhatsApp",
                "3️⃣ 📚 Assistente Educacional — MAT/PT/Leitura",
            ]
        )
        return f"📋 MENU PRINCIPAL\n{opcoes}\n\nResponda com 1, 2 ou 3."

    # Seleção de módulo
    if text in menus:
        return menus[text]

    # Fallback
    return "❓ Não entendi.\nDigite 'menu' para ver as opções."


# ===== RODAPÉ OBRIGATÓRIO (expoe server:app) =====
app = create_app()
print("[server] app criado")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    try:
        from waitress import serve
        print(f"[server] Servindo com waitress em http://{host}:{port}")
        serve(app, host=host, port=port)
    except Exception as e:
        print(f"[server] Waitress não disponível ({e}) — usando Flask dev em http://{host}:{port}")
        app.run(host=host, port=port, debug=False)
