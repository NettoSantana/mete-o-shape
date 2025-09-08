# server.py — Mete o Shape (WhatsApp) + health-check (v2: Anamnese → Treino → Alimentação)
import os, json, logging, threading, math
from typing import Optional, Dict, Any, Tuple
from flask import Flask, request, Response

# Twilio TwiML (fallback para ambiente local sem Twilio)
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

# ===================== Helpers / Constantes =====================
START_WORDS = {"oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"}

def _digits_only(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _uid_from(sender: str, waid: Optional[str]) -> str:
    # Prioriza WaId (estável), senão From, senão anon
    d = _digits_only(waid or "") or _digits_only(sender or "")
    return d or (sender or "anon")

def _safe_reply(text: Optional[str]) -> str:
    t = (text or "").strip()
    return t if t else "⚠️ Não entendi. Digite **oi** para iniciar ou **reiniciar** para recomeçar."

def _round(x: float, base: int = 5) -> int:
    # arredonda para múltiplos (5 kcal/g)
    return int(base * round(float(x) / base))

def _round_g(x: float) -> int:
    return int(round(x))

# Mapas de faixas → valores estimados (para cálculos)
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

ACTIVITY_FACTOR = {
    "Sedentário": 1.25,  # 0–1x/sem (ligeiramente acima do BMR para simplificar)
    "Leve":       1.40,  # 2–3x/sem
    "Moderado":   1.55,  # 3–4x/sem
    "Intenso":    1.70,  # 5–6x/sem
}

OBJ_CAL_ADJ = {
    "Emagrecimento": -0.15,  # -15%
    "Manutenção":     0.00,
    "Hipertrofia":    0.10,  # +10%
}

# ===================== Cálculos de Nutrição =====================
def _calc_tmb_mifflin(sexo: str, peso_kg: float, altura_cm: float, idade: int) -> float:
    """
    Mifflin-St Jeor:
      Homem:   TMB = 10*peso + 6.25*altura - 5*idade + 5
      Mulher:  TMB = 10*peso + 6.25*altura - 5*idade - 161
    """
    base = 10 * peso_kg + 6.25 * altura_cm - 5 * idade
    return base + (5 if (sexo or "").lower().startswith("m") else -161)

def _calc_get(tmb: float, atividade: str) -> float:
    f = ACTIVITY_FACTOR.get(atividade, 1.40)
    return tmb * f

def _apply_objective(cal_get: float, objetivo: str) -> float:
    adj = OBJ_CAL_ADJ.get(objetivo, 0.0)
    return cal_get * (1.0 + adj)

def _calc_macros(peso_kg: float, cal_alvo: float) -> Tuple[int, int, int]:
    """
    Proteína: 2.0 g/kg
    Gorduras: 25% das calorias (9 kcal/g)
    Carbo: restante (4 kcal/g)
    """
    prot_g  = max(1.6, min(2.4, 2.0)) * peso_kg
    gord_kcal = cal_alvo * 0.25
    gord_g = gord_kcal / 9.0
    cal_rest = cal_alvo - (prot_g * 4.0) - gord_kcal
    carb_g = max(0.0, cal_rest / 4.0)
    return _round_g(prot_g), _round_g(carb_g), _round_g(gord_g)

def _split_by_meals(total: int, meals: int) -> Dict[str, int]:
    base = total / meals
    parts = [int(round(base)) for _ in range(meals)]
    # ajustar soma
    diff = total - sum(parts)
    i = 0
    while diff != 0:
        if diff > 0:
            parts[i] += 1; diff -= 1
        else:
            if parts[i] > 0:
                parts[i] -= 1; diff += 1
        i = (i + 1) % meals
    return {f"Ref {i+1}": v for i, v in enumerate(parts)}

# ===================== Core do fluxo =====================
def build_reply(body: str, sender: str, waid: Optional[str]) -> str:
    """
    Fluxo METE O SHAPE — Anamnese (Q1–Q7) → Treino (Q8–Q10) → Alimentação (Q11) → Saída
    Estado salvo em users[uid] = { flow:'ms', step:int, data:{...} }
    Comandos: oi | reiniciar | status | ping
    """
    text = (body or "").strip().lower()
    uid = _uid_from(sender, waid)

    db = load_db()
    users = db.setdefault("users", {})
    st = users.setdefault(uid, {"flow": "ms", "step": 0, "data": {}})
    step = int(st.get("step", 0))
    data = st.get("data", {})  # dict mutável

    # ---- Comandos utilitários
    if text in {"ping", "status", "up"}:
        return "✅ Online. Digite **oi** para iniciar sua anamnese."
    if text in {"reiniciar", "reset", "recomeçar", "recomecar"}:
        st["step"] = 0
        st["data"] = {}
        users[uid] = st
        save_db(db)
        return "🔁 Reiniciado. Digite **oi** para começar."

    # ---- Step 0 → Q1 (saudação)
    if step == 0:
        if text not in START_WORDS:
            return "👋 Digite **oi** para iniciar sua anamnese."
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

    # oi/ola no meio do fluxo sem reset
    if text in START_WORDS and 0 < step < 999:
        return "ℹ️ Já estamos no processo. Se quiser reiniciar, digite **reiniciar**."

    # ===================== ANAMNESE =====================
    # Q1 → Q2 (sexo)
    if step == 1:
        if text not in {"1", "2"}:
            return "❗ Responda **1** (Masculino) ou **2** (Feminino)."
        data["sexo"] = "Masculino" if text == "1" else "Feminino"
        st["step"] = 2; users[uid] = st; save_db(db)
        return (
            "**Q2. Faixa de idade?**\n"
            "1️⃣ 16–24\n2️⃣ 25–34\n3️⃣ 35–44\n4️⃣ 45–54\n5️⃣ 55–64\n6️⃣ 65+\n"
            "_Responda 1–6._"
        )

    # Q2 → Q3 (idade)
    if step == 2:
        if text not in AGE_MAP:
            return "❗ Idade: responda **1–6**."
        low, high, mid = AGE_MAP[text]
        data["idade_faixa"] = f"{low}–{high}"
        data["idade_estimada"] = mid
        st["step"] = 3; users[uid] = st; save_db(db)
        return (
            "**Q3. Faixa de peso (kg)?**\n"
            "1️⃣ < 60\n2️⃣ 60–69\n3️⃣ 70–79\n4️⃣ 80–89\n5️⃣ 90–99\n6️⃣ 100+\n"
            "_Responda 1–6._"
        )

    # Q3 → Q4 (peso)
    if step == 3:
        if text not in WEIGHT_MAP:
            return "❗ Peso: responda **1–6**."
        low, high, mid = WEIGHT_MAP[text]
        data["peso_faixa"] = f"{low}–{high} kg" if high != 130 else "100+ kg"
        data["peso_kg_est"] = mid
        st["step"] = 4; users[uid] = st; save_db(db)
        return (
            "**Q4. Altura (faixa)?**\n"
            "1️⃣ < 1,60 m\n2️⃣ 1,60–1,69 m\n3️⃣ 1,70–1,79 m\n4️⃣ 1,80–1,89 m\n5️⃣ 1,90 m ou mais\n"
            "_Responda 1–5._"
        )

    # Q4 → Q5 (altura)
    if step == 4:
        if text not in HEIGHT_MAP:
            return "❗ Altura: responda **1–5**."
        low, high, mid = HEIGHT_MAP[text]
        data["altura_faixa"] = f"{low}–{high} cm" if high != 205 else "≥190 cm"
        data["altura_cm_est"] = mid
        st["step"] = 5; users[uid] = st; save_db(db)
        return (
            "**Q5. Objetivo principal?**\n"
            "1️⃣ Emagrecer\n2️⃣ Manter\n3️⃣ Ganhar massa\n"
            "_Responda 1–3._"
        )

    # Q5 → Q6 (objetivo)
    if step == 5:
        if text not in {"1","2","3"}:
            return "❗ Objetivo: responda **1–3**."
        objetivo = {"1":"Emagrecimento","2":"Manutenção","3":"Hipertrofia"}[text]
        data["objetivo"] = objetivo
        st["step"] = 6; users[uid] = st; save_db(db)
        return (
            "**Q6. Nível de atividade semanal?**\n"
            "1️⃣ Sedentário (0–1x/sem)\n2️⃣ Leve (2–3x/sem)\n3️⃣ Moderado (3–4x/sem)\n4️⃣ Intenso (5–6x/sem)\n"
            "_Responda 1–4._"
        )

    # Q6 → Q7 (atividade)
    if step == 6:
        if text not in {"1","2","3","4"}:
            return "❗ Atividade: responda **1–4**."
        atividade = {"1":"Sedentário","2":"Leve","3":"Moderado","4":"Intenso"}[text]
        data["atividade"] = atividade
        st["step"] = 7; users[uid] = st; save_db(db)
        return (
            "**Q7. Preferência alimentar?**\n"
            "1️⃣ Sem restrições\n2️⃣ Low-carb\n3️⃣ Sem lactose\n4️⃣ Vegetariano\n"
            "_Responda 1–4._"
        )

    # Q7 → Resumo e confirmação
    if step == 7:
        if text not in {"1","2","3","4"}:
            return "❗ Preferência: responda **1–4**."
        pref = {"1":"Sem restrições","2":"Low-carb","3":"Sem lactose","4":"Vegetariano"}[text]
        data["preferencia"] = pref
        st["step"] = 8; users[uid] = st; save_db(db)

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
            "2️⃣ Reiniciar"
        )
        return resumo

    # Confirmação → segue para TREINO
    if step == 8:
        if text == "1":
            st["step"] = 10  # bloco de treino inicia em 10
            users[uid] = st; save_db(db)
            return (
                "🔥 **Anamnese confirmada.**\n"
                "Agora, vamos montar seu **plano de treino**.\n\n"
                "**Q8. Quantos dias/semana você treina consegue manter?**\n"
                "1️⃣ 2x\n2️⃣ 3x\n3️⃣ 4x\n4️⃣ 5x\n5️⃣ 6x ou mais\n"
                "_Responda 1–5._"
            )
        if text == "2":
            st["step"] = 0; st["data"] = {}; users[uid] = st; save_db(db)
            return "🔁 Reiniciado. Digite **oi** para começar."
        return "❗ Responda **1** para Confirmar ou **2** para Reiniciar."

    # ===================== TREINO =====================
    # Q8 → Q9 (frequência)
    if step == 10:
        if text not in {"1","2","3","4","5"}:
            return "❗ Frequência: responda **1–5**."
        freq_map = {"1":2,"2":3,"3":4,"4":5,"5":6}
        freq = freq_map[text]
        data["treino_freq"] = freq
        # sugerir divisão baseada em frequência
        if freq <= 3:
            data["treino_div"] = "Full Body"
        elif freq in (4,5):
            data["treino_div"] = "ABC"
        else:
            data["treino_div"] = "ABCD"

        st["step"] = 11; users[uid] = st; save_db(db)
        return (
            "**Q9. Alguma limitação/lesão atual?**\n"
            "1️⃣ Não\n"
            "2️⃣ Joelho\n"
            "3️⃣ Ombro\n"
            "4️⃣ Lombar\n"
            "5️⃣ Outras\n"
            "_Responda 1–5._"
        )

    # Q9 → Q10 (lesões)
    if step == 11:
        if text not in {"1","2","3","4","5"}:
            return "❗ Responda **1–5**."
        les_map = {"1":"Nenhuma","2":"Joelho","3":"Ombro","4":"Lombar","5":"Outras"}
        data["treino_lesao"] = les_map[text]
        st["step"] = 12; users[uid] = st; save_db(db)
        # escolha de ênfase (opcional, ainda múltipla)
        return (
            "**Q10. Deseja ênfase específica?**\n"
            "1️⃣ Sem ênfase (equilíbrio)\n"
            "2️⃣ Peito/Costas\n"
            "3️⃣ Pernas/Glúteos\n"
            "4️⃣ Ombros/Braços\n"
            "_Responda 1–4._"
        )

    # Q10 → fecha treino, abre alimentação
    if step == 12:
        if text not in {"1","2","3","4"}:
            return "❗ Responda **1–4**."
        enf_map = {"1":"Equilíbrio","2":"Peito/Costas","3":"Pernas/Glúteos","4":"Ombros/Braços"}
        data["treino_enfase"] = enf_map[text]

        # Resumo do treino
        resumo_treino = (
            "🏋️ **Treino sugerido**\n"
            f"• Frequência: {data['treino_freq']}x/sem\n"
            f"• Divisão: {data['treino_div']}\n"
            f"• Ênfase: {data['treino_enfase']}\n"
            f"• Limitações: {data['treino_lesao']}\n\n"
        )

        st["step"] = 20; users[uid] = st; save_db(db)
        return resumo_treino + (
            "Agora vamos fechar **alimentação**.\n\n"
            "**Q11. Quantas refeições por dia você quer/consigue fazer?**\n"
            "1️⃣ 3 (café, almoço, jantar)\n"
            "2️⃣ 4 (inclui 1 lanche)\n"
            "3️⃣ 5 (inclui 2 lanches)\n"
            "4️⃣ 6+ (maior divisão)\n"
            "_Responda 1–4._"
        )

    # ===================== ALIMENTAÇÃO =====================
    # Q11 → cálculo e saída final
    if step == 20:
        if text not in {"1","2","3","4"}:
            return "❗ Refeições: responda **1–4**."
        meals_map = {"1":3,"2":4,"3":5,"4":6}
        meals = meals_map[text]
        data["meal_count"] = meals

        # ---- cálculos a partir da anamnese
        sexo = data.get("sexo", "Masculino")
        idade = int(data.get("idade_estimada", 30))
        peso = float(data.get("peso_kg_est", 75.0))
        altura = float(data.get("altura_cm_est", 175.0))
        objetivo = data.get("objetivo", "Manutenção")
        atividade = data.get("atividade", "Leve")

        tmb = _calc_tmb_mifflin(sexo, peso, altura, idade)
        get = _calc_get(tmb, atividade)
        cal_alvo = _apply_objective(get, objetivo)
        cal_alvo = max(1200.0, cal_alvo)  # guard minimo

        prot_g, carb_g, gord_g = _calc_macros(peso, cal_alvo)

        # arredondar kcal
        cal_final = _round(cal_alvo, base=10)

        # dividir por refeições
        kcal_split = _split_by_meals(cal_final, meals)
        p_split = _split_by_meals(prot_g, meals)
        c_split = _split_by_meals(carb_g, meals)
        g_split = _split_by_meals(gord_g, meals)

        data.update({
            "tmb": int(round(tmb)),
            "get": int(round(get)),
            "calorias": cal_final,
            "prot_g": prot_g,
            "carb_g": carb_g,
            "gord_g": gord_g,
            "split_kcal": kcal_split,
            "split_p": p_split,
            "split_c": c_split,
            "split_g": g_split,
        })

        st["step"] = 999  # fluxo concluído
        st["data"] = data
        users[uid] = st
        save_db(db)

        # montar texto final
        linhas_split = []
        for i in range(1, meals+1):
            k = f"Ref {i}"
            linhas_split.append(
                f"- {k}: {kcal_split[k]} kcal | P {p_split[k]} g | C {c_split[k]} g | G {g_split[k]} g"
            )
        split_txt = "\n".join(linhas_split)

        return (
            "🔥 **Seu plano inicial**\n\n"
            f"Calorias alvo: {cal_final} kcal/dia\n"
            f"Proteínas: {prot_g} g\n"
            f"Carboidratos: {carb_g} g\n"
            f"Gorduras: {gord_g} g\n\n"
            "📅 **Divisão por refeição**\n"
            f"{split_txt}\n\n"
            "ℹ️ Ajustes finos serão feitos após 7 dias de feedback (peso, medidas, energia, fome). "
            "Se quiser reiniciar o processo: **reiniciar**."
        )

    # Pós-conclusão
    if step >= 999:
        return (
            "✅ Fluxo concluído.\n"
            "• Digite **reiniciar** para recomeçar.\n"
            "• Digite **status** para checar online."
        )

    # Fallback
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

    @app.route("/health", methods=["GET"])
    def health():
        return Response("ok", 200, mimetype="text/plain")

    @app.route("/bot", methods=["GET", "POST"])
    def bot():
        if request.method == "GET":
            log.info("GET /bot -> 200 (health-check)")
            return Response("OK /bot (GET) – use POST via Twilio", 200, mimetype="text/plain")

        body: str = (request.values.get("Body") or "").strip()
        sender: str = request.values.get("From", "")
        waid: Optional[str] = request.values.get("WaId")
        log.info(f"POST /bot <- From={sender} WaId={waid} Body='{body}'")

        try:
            reply_text = _safe_reply(build_reply(body=body, sender=sender, waid=waid))
        except Exception as e:
            app.logger.exception(f"Erro no build_reply: {e}")
            reply_text = "⚠️ Tive um erro aqui. Mande **reiniciar** ou **oi** para seguir."

        log.info("POST /bot -> Reply='%s...'", (reply_text or "")[:160].replace("\n"," "))

        twiml = MessagingResponse()
        twiml.message(reply_text)
        return Response(str(twiml), 200, mimetype="application/xml; charset=utf-8")

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
