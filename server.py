# server.py — Mete o Shape (WhatsApp) + health-check
import os, logging
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


# ===== Fluxo Mete o Shape: boas-vindas + anamnese (múltipla escolha) =====
def build_reply(body: str, sender: str) -> str:
    """
    Fluxo exclusivo METE O SHAPE
    - Boas-vindas motivacional
    - Anamnese por múltipla escolha (1,2,3…)
    - Estado salvo em db.json via storage.py
    """
    from storage import load_db, save_db

    text = (body or "").strip().lower()
    uid = sender or "anon"

    def get_state():
        db = load_db()
        users = db.setdefault("users", {})
        st = users.setdefault(uid, {"flow": "ms", "step": 0, "data": {}})
        return db, users, st

    def set_state(db, users, st):
        users[uid] = st
        save_db(db)

    if text in {"ping", "status", "up"}:
        return "✅ Online. Digite **oi** para iniciar sua anamnese."
    if text in {"reiniciar", "reset", "recomeçar", "recomecar"}:
        db, users, st = get_state()
        st["step"] = 0
        st["data"] = {}
        set_state(db, users, st)
        text = "oi"

    db, users, st = get_state()
    step = int(st.get("step", 0))
    data = st.get("data", {})

    # Step 0 — saudação e Q1
    if step == 0 or text in {"oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"}:
        st["step"] = 1
        st["data"] = {}
        set_state(db, users, st)
        return (
            "👋 **Bem-vindo ao METE O SHAPE!**\n"
            "Você decidiu cuidar do corpo e da mente — **respeito**. Vou te guiar, sem enrolação.\n\n"
            "**Q1. Qual seu sexo?**\n"
            "1️⃣ Masculino\n"
            "2️⃣ Feminino\n"
            "_Responda com 1 ou 2._"
        )

    # Q1 → Q2
    if step == 1:
        if text not in {"1", "2"}:
            return "❗ Responda **1** para Masculino ou **2** para Feminino."
        data["sexo"] = "Masculino" if text == "1" else "Feminino"
        st["step"] = 2; st["data"] = data; set_state(db, users, st)
        return (
            "**Q2. Faixa de idade?**\n"
            "1️⃣ 16–24\n"
            "2️⃣ 25–34\n"
            "3️⃣ 35–44\n"
            "4️⃣ 45–54\n"
            "5️⃣ 55–64\n"
            "6️⃣ 65+\n"
            "_Responda 1–6._"
        )

    # Q2 → Q3
    if step == 2:
        if text not in {"1", "2", "3", "4", "5", "6"}:
            return "❗ Idade: responda **1–6**."
        faixa = {"1":"16–24","2":"25–34","3":"35–44","4":"45–54","5":"55–64","6":"65+"}[text]
        data["idade"] = faixa
        st["step"] = 3; st["data"] = data; set_state(db, users, st)
        return (
            "**Q3. Faixa de peso atual?**\n"
            "1️⃣ < 60 kg\n"
            "2️⃣ 60–69 kg\n"
            "3️⃣ 70–79 kg\n"
            "4️⃣ 80–89 kg\n"
            "5️⃣ 90–99 kg\n"
            "6️⃣ 100 kg ou mais\n"
            "_Responda 1–6._"
        )

    # Q3 → Q4
    if step == 3:
        if text not in {"1", "2", "3", "4", "5", "6"}:
            return "❗ Peso: responda **1–6**."
        peso = {"1":"<60","2":"60–69","3":"70–79","4":"80–89","5":"90–99","6":"100+"}[text]
        data["peso"] = peso
        st["step"] = 4; st["data"] = data; set_state(db, users, st)
        return (
            "**Q4. Altura (faixa)?**\n"
            "1️⃣ < 1,60 m\n"
            "2️⃣ 1,60–1,69 m\n"
            "3️⃣ 1,70–1,79 m\n"
            "4️⃣ 1,80–1,89 m\n"
            "5️⃣ 1,90 m ou mais\n"
            "_Responda 1–5._"
        )

    # Q4 → Q5
    if step == 4:
        if text not in {"1", "2", "3", "4", "5"}:
            return "❗ Altura: responda **1–5**."
        altura = {"1":"<1,60","2":"1,60–1,69","3":"1,70–1,79","4":"1,80–1,89","5":"1,90+"}[text]
        data["altura"] = altura
        st["step"] = 5; st["data"] = data; set_state(db, users, st)
        return (
            "**Q5. Objetivo principal?**\n"
            "1️⃣ Emagrecer\n"
            "2️⃣ Manter\n"
            "3️⃣ Ganhar massa\n"
            "_Responda 1–3._"
        )

    # Q5 → Q6
    if step == 5:
        if text not in {"1", "2", "3"}:
            return "❗ Objetivo: responda **1–3**."
        objetivo = {"1":"Emagrecimento","2":"Manutenção","3":"Hipertrofia"}[text]
        data["objetivo"] = objetivo
        st["step"] = 6; st["data"] = data; set_state(db, users, st)
        return (
            "**Q6. Nível de atividade semanal?**\n"
            "1️⃣ Sedentário (0–1x/sem)\n"
            "2️⃣ Leve (2–3x/sem)\n"
            "3️⃣ Moderado (3–4x/sem)\n"
            "4️⃣ Intenso (5–6x/sem)\n"
            "_Responda 1–4._"
        )

    # Q6 → Q7
    if step == 6:
        if text not in {"1", "2", "3", "4"}:
            return "❗ Atividade: responda **1–4**."
        atividade = {"1":"Sedentário","2":"Leve","3":"Moderado","4":"Intenso"}[text]
        data["atividade"] = atividade
        st["step"] = 7; st["data"] = data; set_state(db, users, st)
        return (
            "**Q7. Preferência alimentar?**\n"
            "1️⃣ Sem restrições\n"
            "2️⃣ Low-carb\n"
            "3️⃣ Sem lactose\n"
            "4️⃣ Vegetariano\n"
            "_Responda 1–4._"
        )

    # Q7 → Resumo
    if step == 7:
        if text not in {"1", "2", "3", "4"}:
            return "❗ Preferência: responda **1–4**."
        pref = {"1":"Sem restrições","2":"Low-carb","3":"Sem lactose","4":"Vegetariano"}[text]
        data["preferencia"] = pref
        st["step"] = 8; st["data"] = data; set_state(db, users, st)

        resumo = (
            "✅ **Resumo da sua anamnese**\n"
            f"• Sexo: {data.get('sexo')}\n"
            f"• Idade: {data.get('idade')}\n"
            f"• Peso: {data.get('peso')} kg\n"
            f"• Altura: {data.get('altura')} m\n"
            f"• Objetivo: {data.get('objetivo')}\n"
            f"• Atividade: {data.get('atividade')}\n"
            f"• Preferência: {data.get('preferencia')}\n\n"
            "**Confirmar?**\n"
            "1️⃣ Confirmar\n"
            "2️⃣ Reiniciar anamnese"
        )
        return resumo

    # Confirmação final
    if step == 8:
        if text == "1":
            st["step"] = 0; set_state(db, users, st)
            return (
                "🔥 **Fechado!** Sua anamnese foi registrada.\n"
                "Na sequência vou calcular seu plano inicial e te enviar.\n"
                "Digite **oi** se precisar recomeçar."
            )
        if text == "2":
            st["step"] = 0; st["data"] = {}; set_state(db, users, st)
            return "🔁 Anamnese reiniciada. Digite **oi** para começar."
        return "❗ Responda **1** para Confirmar ou **2** para Reiniciar."

    return "❓ Não entendi. Digite **oi** para iniciar sua anamnese ou **reiniciar** para recomeçar."


# ===== expõe server:app para o processo do Railway =====
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