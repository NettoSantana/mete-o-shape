# server.py — Mete o Shape (WhatsApp) + health-check
import os, json, logging, threading
from typing import Optional, Dict, Any, Tuple
from flask import Flask, request, Response

# Twilio TwiML (fallback seguro p/ ambiente local sem Twilio)
try:
    from twilio.twiml.messaging_response import MessagingResponse
except Exception:  # pragma: no cover
    class _FakeMsg:
        def __init__(self, body: str): self.body = body
    class MessagingResponse:  # type: ignore
        def __init__(self): self._m = None
        def message(self, text: str): self._m = _FakeMsg(text); return self._m
        def __str__(self): return getattr(self._m, "body", "")

APP_NAME = os.getenv("PROJECT_NAME", "mete_o_shape")

# ===================== Storage (com fallback local) =====================
DB_PATH = os.getenv("DB_PATH", "db.json")
_lock = threading.Lock()

def _load_db_local() -> Dict[str, Any]:
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_db_local(db: Dict[str, Any]) -> None:
    tmp = DB_PATH + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_PATH)

# tenta usar storage.py do projeto; se não existir, usa local
try:
    from storage import load_db as _load_ext, save_db as _save_ext  # type: ignore
    def load_db() -> Dict[str, Any]: return _load_ext()
    def save_db(db: Dict[str, Any]) -> None: _save_ext(db)
except Exception:  # pragma: no cover
    def load_db() -> Dict[str, Any]: return _load_db_local()
    def save_db(db: Dict[str, Any]) -> None: _save_db_local(db)

# ===================== Helpers de normalização =====================
def _digits_only(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _uid_from(sender: str, waid: Optional[str]) -> str:
    # Prioriza WaId (estável), senão From, senão anon
    d = _digits_only(waid or "") or _digits_only(sender or "")
    return d or (sender or "anon")

# Mapas de faixas → valores estimados (para cálculos futuros)
AGE_MAP = {  # (low, high, mid)
    "1": (16, 24, 21),
    "2": (25, 34, 29),
    "3": (35, 44, 39),
    "4": (45, 54, 49),
    "5": (55, 64, 59),
    "6": (65, 75, 68),
}
WEIGHT_MAP = {  # kg (low, high, mid)
    "1": (50, 59, 57.5),  # <60
    "2": (60, 69, 65.0),
    "3": (70, 79, 75.0),
    "4": (80, 89, 85.0),
    "5": (90, 99, 95.0),
    "6": (100, 130, 105.0),  # 100+
}
HEIGHT_MAP = {  # cm (low, high, mid)
    "1": (150, 159, 158),        # <1,60
    "2": (160, 169, 165),
    "3": (170, 179, 175),
    "4": (180, 189, 185),
    "5": (190, 205, 195),        # 1,90+
}

# ===================== Core do fluxo =====================
def build_reply(body: str, sender: str, waid: Optional[str]) -> str:
    """
    Fluxo METE O SHAPE — anamnese múltipla escolha (Q1→Q7 + confirmação)
    Estado salvo em users[uid] = { flow:'ms', step:int, data:{...} }
    Comandos: oi | reiniciar | status | ping
    """
    text = (body or "").strip().lower()
    uid = _uid_from(sender, waid)

    db = load_db()
    users = db.setdefault("users", {})
    st = users.setdefault(uid, {"flow": "ms", "step": 0, "data": {}})
    step = int(st.get("step", 0))
    data = st.get("data", {})

    # ---- Comandos utilitários
    if text in {"ping", "status", "up"}:
        return "✅ Online. Digite **oi** para iniciar sua anamnese."
    if text in {"reiniciar", "reset", "recomeçar", "recomecar"}:
        st["step"] = 0
        st["data"] = {}
        users[uid] = st
        save_db(db)
        text = "oi"
        step = 0
        data = {}

    # ---- Step 0 → Q1 (saudação)
    if step == 0 or text in {"oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"}:
        st["step"] = 1
        st["data"] = {}
        users[uid] = st
        save_db(db)
        return (
            "👋 **Bem-vindo ao METE O SHAPE!**\n"
            "Você decidiu cuidar do corpo e da mente — **respeito**. Vou te guiar, sem enrolação.\n\n"
            "**Q1. Qual seu sexo?**\n"
            "1️⃣ Masculino\n"
            "2️⃣ Feminino\n"
            "_Responda com 1 ou 2._"
        )

    # ---- Q1 → Q2 (sexo)
    if step == 1:
        if text not in {"1", "2"}:
            return "❗ Responda **1** (Masculino) ou **2** (Feminino)."
        data["sexo"] = "Masculino" if text == "1" else "Feminino"
        st["step"] = 2; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q2. Faixa de idade?**\n"
            "1️⃣ 16–24\n2️⃣ 25–34\n3️⃣ 35–44\n4️⃣ 45–54\n5️⃣ 55–64\n6️⃣ 65+\n"
            "_Responda 1–6._"
        )

    # ---- Q2 → Q3 (idade)
    if step == 2:
        if text not in AGE_MAP:
            return "❗ Idade: responda **1–6**."
        low, high, mid = AGE_MAP[text]
        data["idade_faixa"] = f"{low}–{high}"
        data["idade_estimada"] = mid
        st["step"] = 3; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q3. Faixa de peso atual (kg)?**\n"
            "1️⃣ < 60\n2️⃣ 60–69\n3️⃣ 70–79\n4️⃣ 80–89\n5️⃣ 90–99\n6️⃣ 100+\n"
            "_Responda 1–6._"
        )

    # ---- Q3 → Q4 (peso)
    if step == 3:
        if text not in WEIGHT_MAP:
            return "❗ Peso: responda **1–6**."
        low, high, mid = WEIGHT_MAP[text]
        data["peso_faixa"] = f"{low}–{high} kg" if high != 130 else "100+ kg"
        data["peso_kg_est"] = mid
        st["step"] = 4; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q4. Altura (faixa)?**\n"
            "1️⃣ < 1,60 m\n2️⃣ 1,60–1,69 m\n3️⃣ 1,70–1,79 m\n4️⃣ 1,80–1,89 m\n5️⃣ 1,90 m ou mais\n"
            "_Responda 1–5._"
        )

    # ---- Q4 → Q5 (altura)
    if step == 4:
        if text not in HEIGHT_MAP:
            return "❗ Altura: responda **1–5**."
        low, high, mid = HEIGHT_MAP[text]
        data["altura_faixa"] = f"{low}–{high} cm" if high != 205 else "≥190 cm"
        data["altura_cm_est"] = mid
        st["step"] = 5; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q5. Objetivo principal?**\n"
            "1️⃣ Emagrecer\n2️⃣ Manter\n3️⃣ Ganhar massa\n"
            "_Responda 1–3._"
        )

    # ---- Q5 → Q6 (objetivo)
    if step == 5:
        if text not in {"1","2","3"}:
            return "❗ Objetivo: responda **1–3**."
        objetivo = {"1":"Emagrecimento","2":"Manutenção","3":"Hipertrofia"}[text]
        data["objetivo"] = objetivo
        st["step"] = 6; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q6. Nível de atividade semanal?**\n"
            "1️⃣ Sedentário (0–1x/sem)\n2️⃣ Leve (2–3x/sem)\n3️⃣ Moderado (3–4x/sem)\n4️⃣ Intenso (5–6x/sem)\n"
            "_Responda 1–4._"
        )

    # ---- Q6 → Q7 (atividade)
    if step == 6:
        if text not in {"1","2","3","4"}:
            return "❗ Atividade: responda **1–4**."
        atividade = {"1":"Sedentário","2":"Leve","3":"Moderado","4":"Intenso"}[text]
        data["atividade"] = atividade
        st["step"] = 7; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q7. Preferência alimentar?**\n"
            "1️⃣ Sem restrições\n2️⃣ Low-carb\n3️⃣ Sem lactose\n4️⃣ Vegetariano\n"
            "_Responda 1–4._"
        )

    # ---- Q7 → Resumo e confirmação
    if step == 7:
        if text not in {"1","2","3","4"}:
            return "❗ Preferência: responda **1–4**."
        pref = {"1":"Sem restrições","2":"Low-carb","3":"Sem lactose","4":"Vegetariano"}[text]
        data["preferencia"] = pref
        st["step"] = 8; st["data"] = data; users[uid] = st; save_db(db)

        resumo = (
            "✅ **Resumo da sua anamnese**\n"
            f"• Sexo: {data.get('sexo')}\n"
            f"• Idade: {data.get('idade_faixa')} (≈{data.get('idade_estimada')} anos)\n"
            f"• Peso: {data.get('peso_faixa')}\n"
            f"• Altura: {data.get('altura_faixa')} (≈{data.get('altura_cm_est')} cm)\n"
            f"• Objetivo: {data.get('objetivo')}\n"
            f"• Atividade: {data.get('atividade')}\n"
            f"• Preferência: {data.get('preferencia')}\n\n"
            "**Confirmar?**\n"
            "1️⃣ Confirmar\n"
            "2️⃣ Reiniciar anamnese"
        )
        return resumo

    # ---- Confirmação final
    if step == 8:
        if text == "1":
            st["step"] = 100  # marcado como concluído (pronto p/ cálculos de metas)
            users[uid] = st
            save_db(db)
            return (
                "🔥 **Fechado!** Anamnese registrada.\n"
                "Na sequência posso calcular seu plano (calorias e macros) e dividir por refeição.\n"
                "Se quiser refazer, digite **reiniciar**. Se quiser ver status, **status**."
            )
        if text == "2":
            st["step"] = 0; st["data"] = {}; users[uid] = st; save_db(db)
            return "🔁 Anamnese reiniciada. Digite **oi** para começar."
        return "❗ Responda **1** para Confirmar ou **2** para Reiniciar."

    # ---- Pós-conclusão: lembrete de comando
    if step >= 100:
        return (
            "✅ Anamnese concluída.\n"
            "• Digite **reiniciar** para refazer.\n"
            "• Digite **status** para checar online."
        )

    # ---- Fallback
    return "❓ Não entendi. Digite **oi** para iniciar ou **reiniciar** para recomeçar."

# ===================== Flask app / rotas =====================
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

        reply_text = build_reply(body=body, sender=sender, waid=waid)
        twiml = MessagingResponse()
        twiml.message(reply_text)
        return Response(str(twiml), 200, mimetype="application/xml")

    @app.errorhandler(404)
    def not_found(_e):
        return Response("404 – rota não encontrada. Use /bot ou /admin/ping", 404, mimetype="text/plain")

    return app

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

        
