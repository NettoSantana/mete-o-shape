# server.py — Mete o Shape (WhatsApp) + health-check
# Fluxo: Boas-vindas → Q0 Nome → Anamnese → Resultados Iniciais → Plano Alimentar (cardápio exemplo)
#        → Hidratação → Treino ABC → Mensagens diárias automáticas → Check-in semanal
import os, json, logging, threading, math
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
from flask import Flask, request, Response

# Twilio TwiML (fallback local) + envio opcional (REST)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM        = os.getenv("WHATSAPP_FROM", "")  # ex: 'whatsapp:+14155238886'

try:
    from twilio.twiml.messaging_response import MessagingResponse
    from twilio.rest import Client as TwilioClient
except Exception:  # pragma: no cover
    class _FakeMsg:
        def __init__(self, body: str): self.body = body
    class MessagingResponse:  # type: ignore
        def __init__(self): self._m = None
        def message(self, text: str): self._m = _FakeMsg(text); return self._m
        def __str__(self): return getattr(self._m, "body", "")
    TwilioClient = None

APP_NAME = os.getenv("PROJECT_NAME", "mete_o_shape")
# >>> Ajuste de fuso horário dos lembretes <<<
# Use TZ=America/Bahia no ambiente
TZ = os.getenv("TZ", "America/Bahia")

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
    d = _digits_only(waid or "") or _digits_only(sender or "")
    return d or (sender or "anon")

def _safe_reply(text: Optional[str]) -> str:
    t = (text or "").strip()
    return t if t else "⚠️ Não entendi. Digite **oi** para iniciar ou **reiniciar** para recomeçar."

def _round(x: float, base: int = 5) -> int:
    return int(base * round(float(x) / base))

def _round_g(x: float) -> int:
    return int(round(x))

def _now_br() -> datetime:
    try:
        from zoneinfo import ZoneInfo  # py3.9+
        return datetime.now(ZoneInfo(TZ))
    except Exception:
        return datetime.now()

def _clamp_hour(h: int) -> int:
    return max(0, min(23, int(h)))

def _parse_hh_range(s: str) -> Optional[Tuple[int,int]]:
    """'HH–HH' ou 'HH-HH' → (start,end) horas [0..23]"""
    s = (s or "").replace(" ", "").replace("—","-").replace("–","-")
    if "-" not in s: return None
    a,b = s.split("-",1)
    try:
        A = _clamp_hour(int(a)); B = _clamp_hour(int(b))
        return (A,B)
    except Exception:
        return None

def _in_window(hour: int, A: int, B: int) -> bool:
    """Retorna True se 'hour' está dentro da janela [A..B] inclusive, considerando A<=B.
       Se A>B (não usual para feeding_window), considera janela vazia."""
    if A <= B:
        return A <= hour <= B
    return False

def _in_mute(hour: int, M: int, N: int) -> bool:
    """Silêncio pode cruzar meia-noite (ex.: 22–05)."""
    if M == N:  # silêncio 24h (edge raro)
        return True
    if M < N:
        return M <= hour < N
    else:
        return hour >= M or hour < N

# Mapas de faixas → valores estimados (para cálculos)
AGE_MAP = {
    "1": (16, 24, 21),
    "2": (25, 34, 29),
    "3": (35, 44, 39),
    "4": (45, 54, 49),
    "5": (55, 64, 59),
    "6": (65, 75, 68),
}
HEIGHT_MAP = {  # cm (low, high, mid)
    "1": (150, 159, 158),
    "2": (160, 169, 165),
    "3": (170, 179, 175),
    "4": (180, 189, 185),
    "5": (190, 205, 195),
}
WEIGHT_MAP = {  # kg (low, high, mid)
    "1": (50, 59, 57.5),
    "2": (60, 69, 65.0),
    "3": (70, 79, 75.0),
    "4": (80, 89, 85.0),
    "5": (90, 99, 95.0),
    "6": (100, 130, 105.0),
}

ACTIVITY_FACTOR = {
    "Sedentário": 1.25,
    "Leve":       1.40,
    "Moderado":   1.55,
    "Intenso":    1.70,
}

OBJ_CAL_ADJ = {
    "Emagrecimento": -0.15,
    "Manutenção":     0.00,
    "Hipertrofia":    0.10,
}

# ============== Envio opcional de mensagens proativas (cron) ==============
def _twilio_client():
    if TwilioClient and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM:
        try:
            return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        except Exception:
            return None
    return None

def _send_whatsapp(to_num: str, body: str, log) -> bool:
    cli = _twilio_client()
    if not cli:
        log.info(f"[send] (dry-run) to={to_num} body={body[:90]}...")
        return False
    try:
        cli.messages.create(from_=TWILIO_FROM, to=to_num, body=body)
        log.info(f"[send] OK to={to_num}")
        return True
    except Exception as e:
        log.error(f"[send] FAIL to={to_num}: {e}")
        return False

# ===================== Cálculos de Nutrição =====================
def _calc_tmb_mifflin(sexo: str, peso_kg: float, altura_cm: float, idade: int) -> float:
    base = 10 * peso_kg + 6.25 * altura_cm - 5 * idade
    return base + (5 if (sexo or "").lower().startswith("m") else -161)

def _calc_get(tmb: float, atividade: str) -> float:
    f = ACTIVITY_FACTOR.get(atividade, 1.40)
    return tmb * f

def _apply_objective(cal_get: float, objetivo: str) -> float:
    adj = OBJ_CAL_ADJ.get(objetivo, 0.0)
    return cal_get * (1.0 + adj)

def _calc_macros(peso_kg: float, cal_alvo: float) -> Tuple[int, int, int]:
    # Proteína: 2.0 g/kg (com guard entre 1.6 e 2.4)
    prot_g  = max(1.6, min(2.4, 2.0)) * peso_kg
    # Gorduras: 25% (9 kcal/g)
    gord_kcal = cal_alvo * 0.25
    gord_g = gord_kcal / 9.0
    # Carboidratos: resto (4 kcal/g)
    cal_rest = cal_alvo - (prot_g * 4.0) - gord_kcal
    carb_g = max(0.0, cal_rest / 4.0)
    return _round_g(prot_g), _round_g(carb_g), _round_g(gord_g)

def _split_by_meals(total: int, meals: int) -> Dict[str, int]:
    base = total / meals
    parts = [int(round(base)) for _ in range(meals)]
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

# ===================== Cardápio exemplo =====================
CARDAPIO_EXEMPLO = {
    "Cafe da manhã": [
        "Ovos mexidos + aveia com banana",
        "Iogurte natural + granola + fruta",
        "Sanduíche integral com frango desfiado"
    ],
    "Lanche da manhã": [
        "Fruta + castanhas",
        "Iogurte proteico",
        "Sanduíche fit (peito de peru + queijo)"
    ],
    "Almoço": [
        "Arroz + feijão + frango/peixe + salada",
        "Batata doce + patinho + legumes",
        "Quinoa + frango + salada"
    ],
    "Lanche da tarde": [
        "Overnight oats",
        "Shake proteico + fruta",
        "Wrap integral com frango e salada"
    ],
    "Jantar (pré-treino)": [
        "Arroz/batata + carne magra + legumes",
        "Massa integral + frango + salada",
        "Omelete + arroz + salada"
    ],
    "Ceia": [
        "Iogurte + fruta",
        "Cottage/queijo + torradas integrais",
        "Leite/veg + aveia"
    ],
    "Receitas rápidas": [
        "Panqueca de aveia",
        "Sanduíche fit",
        "Frango desfiado",
        "Overnight oats",
        "Wrap integral"
    ],
}

def _render_cardapio() -> str:
    linhas: List[str] = []
    for bloco, itens in CARDAPIO_EXEMPLO.items():
        if bloco == "Receitas rápidas":
            linhas.append("\n🍳 *Receitas rápidas*: " + ", ".join(itens))
        else:
            linhas.append(f"• {bloco}: " + " | ".join(itens))
    return "\n".join(linhas)

# ===================== Core do fluxo =====================
def build_reply(body: str, sender: str, waid: Optional[str], media_urls: Optional[List[str]] = None) -> str:
    """
    Fluxo — Boas-vindas → Q0 Nome → Anamnese (Q1–Q7) + fotos → Q8a–Q8c → Resultados Iniciais → Plano → ...
    Estado: users[uid] = { flow:'ms', step:int, data:{...}, schedule:{...} }
    Comandos: oi | reiniciar | status | ping
    """
    text = (body or "").strip().lower()
    uid = _uid_from(sender, waid)

    db = load_db()
    users = db.setdefault("users", {})
    st = users.setdefault(uid, {"flow": "ms", "step": 0, "data": {}, "schedule": {"last": {}}})
    step = int(st.get("step", 0))
    data = st.get("data", {})
    schedule = st.get("schedule", {"last": {}})

    # ---- Comandos utilitários
    if text in {"ping", "status", "up"}:
        return "✅ Online. Digite **oi** para iniciar."
    if text in {"reiniciar", "reset", "recomeçar", "recomecar"}:
        st["step"] = 0; st["data"] = {}; st["schedule"] = {"last": {}}
        users[uid] = st; save_db(db)
        return "🔁 Reiniciado. Digite **oi** para começar."

    # ---- Step 0 → Q0 (saudação + NOME)
    if step == 0:
        if text not in START_WORDS:
            return "👋 Digite **oi** para iniciar."
        st["step"] = 1; st["data"] = {}; users[uid] = st; save_db(db)
        return (
            "👋 *Bem-vindo ao Mete o Shape* 🚀\n"
            "Aqui você terá acompanhamento completo de nutrição, treino e motivação.\n"
            "Vamos começar rápido.\n\n"
            "**Q0. Qual seu primeiro nome?**"
        )

    # oi/ola no meio do fluxo sem reset
    if text in START_WORDS and 0 < step < 999:
        return "ℹ️ Estamos no processo. Para recomeçar: **reiniciar**."

    # ===================== Q0 Nome =====================
    if step == 1:
        nome = (body or "").strip()
        if not nome or len(nome) < 2:
            return "❗ Me diga seu primeiro nome (ex.: Carlos)."
        data["nome"] = nome.split()[0].title()
        st["step"] = 2; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q1. Sexo**\n"
            "1️⃣ Masculino\n2️⃣ Feminino\n_Responda 1–2._"
        )

    # ===================== ANAMNESE =====================
    # Q1 (Sexo) → Q2 (Faixa de idade)
    if step == 2:
        if text not in {"1","2"}:
            return "❗ Responda **1** (Masculino) ou **2** (Feminino)."
        data["sexo"] = "Masculino" if text == "1" else "Feminino"
        st["step"] = 3; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q2. Idade (faixa)**\n"
            "1️⃣ 16–24\n2️⃣ 25–34\n3️⃣ 35–44\n4️⃣ 45–54\n5️⃣ 55–64\n6️⃣ 65+\n_Responda 1–6._"
        )

    # Q2 (faixa) → Q2b (exata) → Q3 (altura)
    if step == 3:
        if text not in AGE_MAP:
            return "❗ Idade: responda **1–6**."
        low, high, mid = AGE_MAP[text]
        data["idade_faixa"] = f"{low}–{high}"
        data["idade_estimada"] = mid
        st["step"] = 4; st["data"] = data; users[uid] = st; save_db(db)
        return "**Q2b. Qual sua idade EXATA (número)?**"

    if step == 4:
        # idade exata opcional (se inválida, fica com estimada)
        try:
            idade_exata = int("".join(ch for ch in (body or "") if ch.isdigit()))
        except Exception:
            idade_exata = 0
        if 10 < idade_exata < 100:
            data["idade_exata"] = idade_exata
        else:
            data["idade_exata"] = data.get("idade_estimada", 30)
        st["step"] = 5; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q3. Altura (faixa)**\n"
            "1️⃣ <1,60 m\n2️⃣ 1,60–1,69 m\n3️⃣ 1,70–1,79 m\n4️⃣ 1,80–1,89 m\n5️⃣ ≥1,90 m\n_Responda 1–5._"
        )

    # Q3 Altura → Q4 Peso
    if step == 5:
        if text not in HEIGHT_MAP:
            return "❗ Altura: responda **1–5**."
        low, high, mid = HEIGHT_MAP[text]
        data["altura_faixa"] = f"{low}–{high} cm" if high != 205 else "≥190 cm"
        data["altura_cm_est"] = mid
        st["step"] = 6; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q4. Peso atual (faixa, kg)**\n"
            "1️⃣ <60\n2️⃣ 60–69\n3️⃣ 70–79\n4️⃣ 80–89\n5️⃣ 90–99\n6️⃣ 100+\n_Responda 1–6._"
        )

    # Q4 Peso → Q5 Atividade
    if step == 6:
        if text not in WEIGHT_MAP:
            return "❗ Peso: responda **1–6**."
        low, high, mid = WEIGHT_MAP[text]
        data["peso_faixa"] = f"{low}–{high} kg" if high != 130 else "100+ kg"
        data["peso_kg_est"] = mid
        st["step"] = 7; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q5. Nível de atividade física**\n"
            "1️⃣ Sedentário (0–1x/sem)\n2️⃣ Leve (2–3x/sem)\n3️⃣ Moderado (3–4x/sem)\n4️⃣ Intenso (5–6x/sem)\n_Responda 1–4._"
        )

    # Q5 Atividade → Q6 Objetivo
    if step == 7:
        if text not in {"1","2","3","4"}:
            return "❗ Atividade: responda **1–4**."
        atividade = {"1":"Sedentário","2":"Leve","3":"Moderado","4":"Intenso"}[text]
        data["atividade"] = atividade
        st["step"] = 8; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q6. Objetivo principal**\n"
            "1️⃣ Emagrecimento\n2️⃣ Definição/Manutenção\n3️⃣ Ganho de massa\n_Responda 1–3._"
        )

    # Q6 Objetivo → Q7 Restrições
    if step == 8:
        if text not in {"1","2","3"}:
            return "❗ Objetivo: responda **1–3**."
        objetivo = {"1":"Emagrecimento","2":"Manutenção","3":"Hipertrofia"}[text]
        data["objetivo"] = objetivo
        st["step"] = 9; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q7. Restrições/observações**\n"
            "1️⃣ Sem restrições\n2️⃣ Intolerância à lactose\n3️⃣ Vegetariano\n4️⃣ Low-carb\n5️⃣ Outras\n_Responda 1–5._"
        )

    # Q7 → Observação livre (71) ou segue
    if step == 9:
        if text not in {"1","2","3","4","5"}:
            return "❗ Responda **1–5**."
        restr_map = {
            "1":"Sem restrições",
            "2":"Sem lactose",
            "3":"Vegetariano",
            "4":"Low-carb",
            "5":"Outras"
        }
        data["restricoes"] = restr_map[text]
        if text == "5":
            st["step"] = 91; st["data"] = data; users[uid] = st; save_db(db)
            return "✍️ Digite sua observação em uma frase curta (ex.: alergia a ovos)."
        st["step"] = 10; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q7c. Quer enviar fotos (frente/lado/costas) agora?**\n"
            "1️⃣ Sim, vou enviar\n2️⃣ Pular por enquanto"
        )

    if step == 91:
        obs = (body or "").strip()
        if not obs:
            return "❗ Escreva uma observação curta (texto)."
        data["restricoes_obs"] = obs
        st["step"] = 10; st["data"] = data; users[uid] = st; save_db(db)
        return (
            "**Q7c. Quer enviar fotos (frente/lado/costas) agora?**\n"
            "1️⃣ Sim, vou enviar\n2️⃣ Pular por enquanto"
        )

    # Q7c Fotos → se Sim, entra no step 92 aguardando mídias
    if step == 10:
        if text not in {"1","2"}:
            return "❗ Responda **1** (Sim) ou **2** (Pular)."
        if text == "1":
            st["step"] = 92; users[uid] = st; save_db(db)
            return "📸 Envie de 1 a 3 fotos agora (frente / lado / costas)."
        # pular → segue para Q8a (treino)
        st["step"] = 100; users[uid] = st; save_db(db)
        return (
            "**Q8a. Horário do TREINO**\n"
            "1️⃣ 6h  2️⃣ 12h  3️⃣ 17h  4️⃣ 18h  5️⃣ 19h  6️⃣ 20h  7️⃣ Não treino  8️⃣ Outro (0–23)\n"
            "_Responda 1–8._"
        )

    # Step 92: recebendo fotos
    if step == 92:
        fotos = data.get("fotos", [])
        media_urls = media_urls or []
        if media_urls:
            fotos.extend(media_urls[:3])
            data["fotos"] = fotos
            st["data"] = data
            # após fotos → Q8a (treino)
            st["step"] = 100; users[uid] = st; save_db(db)
            return (
                "✅ Fotos recebidas.\n\n"
                "**Q8a. Horário do TREINO**\n"
                "1️⃣ 6h  2️⃣ 12h  3️⃣ 17h  4️⃣ 18h  5️⃣ 19h  6️⃣ 20h  7️⃣ Não treino  8️⃣ Outro (0–23)\n"
                "_Responda 1–8._"
            )
        else:
            return "❗ Não recebi imagem. Envie a(s) foto(s) agora ou digite **pular** para seguir."

    if step == 92 and text == "pular":
        st["step"] = 100; users[uid] = st; save_db(db)
        return (
            "➡️ Pulando fotos.\n\n"
            "**Q8a. Horário do TREINO**\n"
            "1️⃣ 6h  2️⃣ 12h  3️⃣ 17h  4️⃣ 18h  5️⃣ 19h  6️⃣ 20h  7️⃣ Não treino  8️⃣ Outro (0–23)\n"
            "_Responda 1–8._"
        )

    # ===================== Q8a/Q8b/Q8c (perfil de alertas) =====================
    if step == 100:
        # Treino
        opt = text
        map_opt = {"1":6,"2":12,"3":17,"4":18,"5":19,"6":20}
        if opt in map_opt:
            data["training_hour"] = map_opt[opt]
        elif opt == "7":
            data["training_hour"] = None
        elif opt == "8":
            return "Digite a hora do treino (0–23), número inteiro."
        else:
            # pode ter digitado direto a hora
            try:
                h = _clamp_hour(int(opt))
                data["training_hour"] = h
            except Exception:
                return "❗ Responda 1–8 ou uma hora válida (0–23)."
        st["data"] = data; st["step"] = 101; users[uid] = st; save_db(db)
        return (
            "**Q8b. Janela de ALIMENTAÇÃO (HH–HH)**\n"
            "1️⃣ 08–20  2️⃣ 07–21  3️⃣ 06–22  4️⃣ 10–18  5️⃣ Outra (digite HH–HH)\n"
            "_Responda 1–5._"
        )

    if step == 101:
        # feeding_window
        preset = {"1":(8,20), "2":(7,21), "3":(6,22), "4":(10,18)}
        if text in preset:
            data["feeding_window"] = list(preset[text])
        else:
            rng = _parse_hh_range(body or "")
            if not rng:
                return "❗ Formato inválido. Envie no formato HH–HH (ex.: 08–20)."
            data["feeding_window"] = [rng[0], rng[1]]
        st["data"] = data; st["step"] = 102; users[uid] = st; save_db(db)
        return (
            "**Q8c. Silêncio/Não perturbe (HH–HH)**\n"
            "1️⃣ 22–05  2️⃣ 23–06  3️⃣ 00–06  4️⃣ Não silenciar  5️⃣ Outra (HH–HH)\n"
            "_Responda 1–5._"
        )

    if step == 102:
        # mute_hours (pode cruzar meia-noite)
        if text == "4":
            data["mute_hours"] = None
        elif text in {"1","2","3"}:
            preset = {"1":(22,5), "2":(23,6), "3":(0,6)}
            data["mute_hours"] = [preset[text][0], preset[text][1]]
        else:
            rng = _parse_hh_range(body or "")
            if not rng:
                return "❗ Formato inválido. Envie HH–HH (ex.: 22–05) ou escolha 1–4."
            data["mute_hours"] = [rng[0], rng[1]]
        st["data"] = data; st["step"] = 11; users[uid] = st; save_db(db)
        # segue para confirmação como antes:
        nome = data.get("nome","")
        return (
            "✅ *Resumo rápido*\n"
            f"Nome: {nome}\n"
            f"Sexo: {data['sexo']} | Idade: {data.get('idade_exata', data.get('idade_estimada'))} anos\n"
            f"Altura: {data['altura_faixa']} | Peso: {data['peso_faixa']}\n"
            f"Atividade: {data['atividade']} | Objetivo: {data['objetivo']}\n"
            f"Restrições: {data.get('restricoes')} {('('+data.get('restricoes_obs','')+')') if data.get('restricoes_obs') else ''}\n"
            f"Treino: {('sem treino' if data.get('training_hour') is None else str(data.get('training_hour'))+'h')}\n"
            f"Janela: {tuple(data.get('feeding_window',[8,20]))}\n"
            f"Silêncio: {('nenhum' if data.get('mute_hours') in (None,[]) else tuple(data.get('mute_hours')))}\n\n"
            "**Confirmar?**\n1️⃣ Confirmar\n2️⃣ Reiniciar"
        )

    # Confirmação → Resultados Iniciais
    if step == 11:
        if text == "2":
            st["step"] = 0; st["data"] = {}; users[uid] = st; save_db(db)
            return "🔁 Reiniciado. Digite **oi** para começar."
        if text != "1":
            return "❗ Responda **1** para Confirmar ou **2** para Reiniciar."

        sexo   = data.get("sexo", "Masculino")
        idade  = int(data.get("idade_exata", data.get("idade_estimada", 30)))
        peso   = float(data.get("peso_kg_est", 75.0))
        altura = float(data.get("altura_cm_est", 175.0))
        objetivo  = data.get("objetivo", "Manutenção")
        atividade = data.get("atividade", "Leve")
        nome      = data.get("nome","")

        tmb = _calc_tmb_mifflin(sexo, peso, altura, idade)
        tdee = _calc_get(tmb, atividade)
        cal_alvo = _apply_objective(tdee, objetivo)
        cal_final = max(1200, _round(cal_alvo, base=10))
        prot_g, carb_g, gord_g = _calc_macros(peso, cal_final)

        data.update({
            "tmb": int(round(tmb)),
            "tdee": int(round(tdee)),
            "calorias": cal_final,
            "prot_g": prot_g, "carb_g": carb_g, "gord_g": gord_g
        })

        st["step"] = 12; st["data"] = data; users[uid] = st; save_db(db)
        return (
            f"📊 *Resultados Iniciais — {nome} ({idade} anos)*\n"
            f"TMB: {data['tmb']} kcal\n"
            f"TDEE (atividade): {data['tdee']} kcal\n"
            f"Calorias meta ({objetivo}): {data['calorias']} kcal/dia\n"
            f"Macros: Proteína {prot_g} g | Carboidratos {carb_g} g | Gorduras {gord_g} g\n\n"
            "**Q9. Quantas refeições por dia você prefere?**\n"
            "1️⃣ 3\n2️⃣ 4\n3️⃣ 5\n4️⃣ 6+\n_Responda 1–4._"
        )

    # Q9 — Nº de refeições → Plano + Cardápio + Hidratação + Treino
    if step == 12:
        if text not in {"1","2","3","4"}:
            return "❗ Refeições: responda **1–4**."
        meals = {"1":3, "2":4, "3":5, "4":6}[text]
        data["meal_count"] = meals

        kcal_split = _split_by_meals(int(data["calorias"]), meals)
        p_split = _split_by_meals(int(data["prot_g"]), meals)
        c_split = _split_by_meals(int(data["carb_g"]), meals)
        g_split = _split_by_meals(int(data["gord_g"]), meals)
        data.update({"split_kcal": kcal_split, "split_p": p_split, "split_c": c_split, "split_g": g_split})

        # Hidratação (37 ml/kg)
        peso = float(data.get("peso_kg_est", 75.0))
        agua_ml = int(round(peso * 37))
        agua_l = max(2, round(agua_ml/1000, 1))
        agua_manha = round(agua_l * 0.33, 1)
        agua_tarde = round(agua_l * 0.37, 1)
        agua_noite = round(agua_l * 0.30, 1)
        data.update({"agua_l": agua_l, "agua_split": {"manhã": agua_manha, "tarde": agua_tarde, "noite": agua_noite}})

        # Treino ABC (fixo neste roteiro)
        treino_txt = (
            "🏋️ *Treino (ABC sugerido)*\n"
            "A: Peito, Ombro, Tríceps\n"
            "B: Costas, Bíceps\n"
            "C: Pernas, Abdômen\n"
            "Frequência: 3x/sem (ABC) ou 6x/sem (ABC duas vezes)\n"
        )

        # Split por refeição (labels completos)
        linhas_split = []
        for i in range(1, meals+1):
            k = f"Ref {i}"
            linhas_split.append(
                f"- {k}: {kcal_split[k]} kcal | Proteína {p_split[k]} g | Carboidratos {c_split[k]} g | Gorduras {g_split[k]} g"
            )
        split_txt = "\n".join(linhas_split)

        cardapio_txt = _render_cardapio()
        agua_txt = f"💧 *Hidratação*: ~{agua_l} L/dia (manhã {agua_manha} L, tarde {agua_tarde} L, noite {agua_noite} L)."
        nome = data.get("nome",""); idade = int(data.get("idade_exata", data.get("idade_estimada", 30)))

        st["step"] = 999
        st["data"] = data
        schedule.setdefault("last", {})
        schedule["enabled"] = True
        st["schedule"] = schedule
        users[uid] = st
        save_db(db)

        return (
            f"🔥 *Plano Inicial — {nome} ({idade} anos)*\n\n"
            f"Calorias: {data['calorias']} kcal/dia\n"
            f"Macros: Proteína {data['prot_g']} g | Carboidratos {data['carb_g']} g | Gorduras {data['gord_g']} g\n\n"
            "📅 *Divisão por refeição*\n"
            f"{split_txt}\n\n"
            "🍽️ *Cardápio exemplo*\n"
            f"{cardapio_txt}\n\n"
            f"{agua_txt}\n\n"
            f"{treino_txt}\n"
            "ℹ️ Você receberá lembretes diários (água/refeições) e 1 *check-in semanal*. "
            "Para desligar: *PAUSAR*. Para reativar: *ATIVAR*."
        )

    # Pós-conclusão / comandos de agendamento
    if step >= 999:
        if text == "pausar":
            st["schedule"]["enabled"] = False
            users[uid] = st; save_db(db)
            return "⏸️ Lembretes pausados. Envie *ATIVAR* para reativar."
        if text == "ativar":
            st["schedule"]["enabled"] = True
            users[uid] = st; save_db(db)
            return "▶️ Lembretes reativados. Você receberá mensagens ao longo do dia."
        return (
            "✅ Fluxo concluído.\n"
            "• *reiniciar* para recomeçar\n"
            "• *pausar* ou *ativar* lembretes\n"
            "• *status* para checar online"
        )

    # Fallback
    return "❓ Não entendi. Digite **oi** para iniciar ou **reiniciar** para recomeçar."

# ===================== CRON: mensagens diárias + check-in semanal =====================

WEEKDAY_CHECKIN = 0  # 0=segunda-feira

def _distribute_meal_hours(A: int, B: int, count: int) -> List[int]:
    A = _clamp_hour(A); B = _clamp_hour(B); count = max(1, int(count))
    if A > B:  # janela inválida para refeições
        return []
    if count == 1: return [A]
    hours = []
    span = B - A
    for i in range(count):
        h = int(round(A + (span * (i/(count-1)))))
        hours.append(_clamp_hour(h))
    # dedup mantendo ordem
    seen=set(); out=[]
    for h in hours:
        if h not in seen:
            out.append(h); seen.add(h)
    return sorted(out)

def _force_post_workout(meals: List[int], A: int, B: int, T: Optional[int]) -> List[int]:
    if T is None: return sorted(meals)
    if not _in_window(T, A, B): return sorted(meals)
    target = min(B, T+1)
    if target in meals: return sorted(meals)
    # mover a refeição mais próxima para target
    if not meals: return [target]
    idx = min(range(len(meals)), key=lambda i: abs(meals[i]-target))
    meals[idx] = target
    return sorted(list(set(meals)))

def _water_slots(meals: List[int], A: int, B: int, avoid: set, need: int = 3) -> List[int]:
    """Escolhe até 3 horas cheias entre as refeições; evita colisões com 'avoid'; respeita janela."""
    cand: List[int] = []
    m = sorted(meals)
    if len(m) >= 2:
        for i in range(len(m)-1):
            mid = int(round((m[i]+m[i+1])/2))
            if _in_window(mid, A, B): cand.append(mid)
    # se faltar, preenche por terços da janela
    while len(cand) < need and A <= B:
        slots = [int(round(A + (B-A)*p)) for p in [1/4, 2/4, 3/4]]
        for s in slots:
            if len(cand) >= need: break
            if _in_window(s, A, B): cand.append(s)
        break
    # filtra colisões/mute posteriormente no cron
    # dedup e corta tamanho
    seen=set(); out=[]
    for h in cand:
        if h not in seen and h not in avoid:
            out.append(h); seen.add(h)
    return sorted(out)[:need]

def _should_send(last: Dict[str,str], key: str, now: datetime, h: int) -> bool:
    """Marca e libera 1x por dia/hora (idempotência)."""
    today_key = now.strftime("%Y-%m-%d") + f"@{h}"
    if last.get(key) == today_key:
        return False
    last[key] = today_key
    return True

def _cron_payload_for(uid: str, u: Dict[str, Any], log) -> List[Tuple[str, str]]:
    """Retorna lista de (to, body) a enviar agora, calculado por PERFIL."""
    to_num = u.get("last_from") or ""  # salvo no /bot
    if not to_num:
        return []
    sched = (u.get("schedule") or {})
    if not sched.get("enabled", True):
        return []
    last = sched.get("last", {})
    data = (u.get("data") or {})

    now = _now_br()
    hour = now.hour
    weekday = now.weekday()

    # Perfil
    fw = data.get("feeding_window", [8,20])
    A, B = int(fw[0]), int(fw[1])
    meal_count = int(data.get("meal_count", 4))
    T = data.get("training_hour", None)
    if isinstance(T, str) and T.isdigit(): T = int(T)
    if isinstance(T, float): T = int(T)
    if T is not None: T = _clamp_hour(T)

    mute = data.get("mute_hours", [22,5])
    mute_tuple: Optional[Tuple[int,int]]
    if mute in (None, []):
        mute_tuple = None
    else:
        mute_tuple = (_clamp_hour(mute[0]), _clamp_hour(mute[1]))

    def not_muted(h: int) -> bool:
        if mute_tuple is None: return True
        return not _in_mute(h, mute_tuple[0], mute_tuple[1])

    out: List[Tuple[str, str]] = []
    avoid = set()

    # Refeições (por janela/Q9), garantindo 1 pós-treino se T∈[A,B]
    meals = _distribute_meal_hours(A, B, meal_count)
    meals = _force_post_workout(meals, A, B, T)
    meals = sorted(h for h in meals if not_muted(h))

    # Água (3 pings entre refeições)
    water = _water_slots(meals, A, B, avoid=set(meals), need=3)
    water = [h for h in water if not_muted(h)]

    # Treino (T−1/T+1), independentemente da janela de alimentação, mas respeita mute
    pre = post = None
    if T is not None:
        pre = _clamp_hour(T-1)
        post = _clamp_hour(T+1)
    train_slots = []
    if pre is not None and not_muted(pre): train_slots.append(("pretreino", pre))
    if post is not None and not_muted(post): train_slots.append(("pos_treino", post))

    # Envio: só na hora exata (cron 1x/h)
    # Refeições
    for i, h in enumerate(meals, start=1):
        if h == hour and _should_send(last, f"meal_{h}", now, h):
            out.append((to_num, f"🍽️ *Refeição {i}* agora ({h:02d}:00). Mantenha as porções do plano."))

    # Água
    for j, h in enumerate(water, start=1):
        if h == hour and _should_send(last, f"agua_{h}", now, h):
            out.append((to_num, "💧 Lembrete de água. Pequenos goles agora. Meta diária em andamento."))

    # Treino
    for tag, h in train_slots:
        if h == hour and _should_send(last, f"{tag}_{h}", now, h):
            if tag == "pretreino":
                out.append((to_num, "⚡ Pré-treino (T−1h): aquece, técnica limpa, foco total."))
            else:
                out.append((to_num, "✅ Pós-treino (T+1h): proteína + carbo limpo. Marca no app como feito."))

    # Check-in semanal (segunda >= 08h)
    ck_key = "checkin"
    ck_mark = last.get(ck_key)
    if weekday == WEEKDAY_CHECKIN and hour >= 8:
        today_ck = now.strftime("%Y-%m-%d")
        if ck_mark != today_ck:
            last[ck_key] = today_ck
            out.append((to_num,
                "📈 *Check-in semanal*\n"
                "Qual seu peso desta semana? Mudou algo nas medidas/fotos?\n"
                "Responda aqui que ajusto suas calorias/macros se precisar."
            ))

    # persistir last
    u.setdefault("schedule", {})["last"] = last
    return out

def _remember_last_from(users: Dict[str, Any], uid: str, sender: str):
    users[uid]["last_from"] = sender

# ===================== Flask app / rotas =====================
def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger(APP_NAME)

    @app.route("/", methods=["GET"])
    def root():
        return Response("OK / (root) – use /bot (GET/POST), /admin/ping ou /admin/cron", 200, mimetype="text/plain")

    @app.route("/admin/ping", methods=["GET"])
    def admin_ping():
        return Response("OK /admin/ping", 200, mimetype="text/plain")

    @app.route("/health", methods=["GET"])
    def health():
        return Response("ok", 200, mimetype="text/plain")

    @app.route("/admin/cron", methods=["GET"])
    def admin_cron():
        """Chame esta rota 1x/h pela sua automação (Railway/cron) para disparar lembretes/check-ins."""
        db = load_db()
        users = db.get("users", {})
        total_msgs = 0
        for uid, u in users.items():
            try:
                payloads = _cron_payload_for(uid, u, log)
                for to, body in payloads:
                    _send_whatsapp(to, body, log)
                    total_msgs += 1
            except Exception as e:
                log.error(f"/admin/cron error uid={uid}: {e}")
        save_db(db)
        return Response(f"cron ok – sent={total_msgs}", 200, mimetype="text/plain")

    @app.route("/bot", methods=["GET", "POST"])
    def bot():
        if request.method == "GET":
            log.info("GET /bot -> 200 (health-check)")
            return Response("OK /bot (GET) – use POST via Twilio", 200, mimetype="text/plain")

        body: str = (request.values.get("Body") or "").strip()
        sender: str = request.values.get("From", "")
        waid: Optional[str] = request.values.get("WaId")

        # Coleta mídias (Twilio: NumMedia, MediaUrl0..)
        try:
            num_media = int(request.values.get("NumMedia", "0"))
        except Exception:
            num_media = 0
        media_urls: List[str] = []
        if num_media > 0:
            for i in range(min(num_media, 3)):
                url = request.values.get(f"MediaUrl{i}")
                if url:
                    media_urls.append(url)

        log.info(f"POST /bot <- From={sender} WaId={waid} Body='{body}' Media={len(media_urls)}")

        # lembrar destino para cron
        try:
            db = load_db()
            users = db.setdefault("users", {})
            uid = _uid_from(sender, waid)
            users.setdefault(uid, {"flow":"ms","step":0,"data":{},"schedule":{"last":{}}})
            _remember_last_from(users, uid, sender)
            save_db(db)
        except Exception:
            pass

        try:
            reply_text = _safe_reply(build_reply(body=body, sender=sender, waid=waid, media_urls=media_urls))
        except Exception as e:
            app.logger.exception(f"Erro no build_reply: {e}")
            reply_text = "⚠️ Tive um erro aqui. Mande **reiniciar** ou **oi** para seguir."

        log.info("POST /bot -> Reply='%s...'", (reply_text or "")[:180].replace("\n"," "))

        twiml = MessagingResponse()
        twiml.message(reply_text)
        return Response(str(twiml), 200, mimetype="application/xml; charset=utf-8")

    @app.errorhandler(404)
    def not_found(_e):
        return Response("404 – rota não encontrada. Use /bot, /admin/ping ou /admin/cron", 404, mimetype="text/plain")

    return app

# ===== expõe server:app =====
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
