import os, math
from typing import Tuple
from flask import Flask, request
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from storage import load_db, save_db

load_dotenv()
app = Flask(__name__)

PROJECT_NAME = os.getenv("PROJECT_NAME", "mete_o_shape")

ACTIVITY = {
    "1": ("Sedentário", 1.2),
    "2": ("Leve", 1.375),
    "3": ("Moderado", 1.55),
    "4": ("Alto", 1.725),
    "5": ("Atleta", 1.9),
}

GOAL = {
    "1": ("Emagrecimento", -0.20),
    "2": ("Definição", -0.10),
    "3": ("Manutenção", 0.00),
    "4": ("Ganho de Massa", +0.15),
}

SEX = {"1": "M", "2": "F"}

def mifflin_st_jeor(sex: str, kg: float, cm: float, age: int) -> float:
    if sex == "M":
        return 10 * kg + 6.25 * cm - 5 * age + 5
    return 10 * kg + 6.25 * cm - 5 * age - 161

def split_macros(calories: int, p_ratio=0.30, c_ratio=0.40, f_ratio=0.30) -> Tuple[int, int, int]:
    p = round((calories * p_ratio) / 4)
    c = round((calories * c_ratio) / 4)
    f = round((calories * f_ratio) / 9)
    return p, c, f

QUESTIONS = [
    ("sexo", "Qual seu sexo?\n1) Masculino\n2) Feminino"),
    ("idade", "Sua idade? (anos)\n1) <18\n2) 18–25\n3) 26–35\n4) 36–45\n5) 46–55\n6) >55"),
    ("altura", "Sua altura?\n1) <1,60\n2) 1,60–1,70\n3) 1,71–1,80\n4) 1,81–1,90\n5) >1,90"),
    ("peso", "Seu peso atual?\n1) <60\n2) 61–75\n3) 76–90\n4) 91–105\n5) >105"),
    ("atividade", "Nível de atividade?\n1) Sedentário\n2) Leve\n3) Moderado\n4) Alto\n5) Atleta"),
    ("objetivo", "Objetivo principal?\n1) Emagrecimento\n2) Definição\n3) Manutenção\n4) Ganho de Massa"),
]

@app.post("/bot")
def bot():
    db = load_db()
    from_phone = request.values.get("From", "").replace("whatsapp:", "")
    body = (request.values.get("Body", "").strip() or "").lower()
    user = db["users"].get(from_phone) or {"state": 0, "answers": {}, "profile": {}}
    resp = MessagingResponse()

    if body in ("menu", "help", "ajuda"):
        resp.message("Digite 'iniciar' para começar a anamnese ou 'status' para ver seu plano.")
        return str(resp)

    if body in ("reset", "reiniciar"):
        user = {"state": 0, "answers": {}, "profile": {}}
        db["users"][from_phone] = user
        save_db(db)
        resp.message("Dados apagados. Digite 'iniciar' para recomeçar.")
        return str(resp)

    if body in ("status",):
        prof = user.get("profile")
        if not prof:
            resp.message("Sem dados ainda. Digite 'iniciar'.")
            return str(resp)
        msg = (
            f"🎯 Objetivo: {prof['goal_name']}\n"
            f"🔥 Calorias meta: {prof['calories']} kcal\n"
            f"🧮 Macros (g): P{prof['protein']} C{prof['carbs']} G{prof['fat']}\n"
            f"💧 Água: {prof['water_ml']} ml/dia"
        )
        resp.message(msg)
        return str(resp)

    if body in ("start", "iniciar", "oi", "olá", "ola"):
        user["state"] = 0

    if user["state"] < len(QUESTIONS):
        key, text = QUESTIONS[user["state"]]
        if body and user["state"] > 0:
            prev_key, _ = QUESTIONS[user["state"] - 1]
            user["answers"][prev_key] = request.values.get("Body", "").strip()
        resp.message(text)
        user["state"] += 1
        db["users"][from_phone] = user
        save_db(db)
        return str(resp)

    if user["state"] == len(QUESTIONS):
        prev_key, _ = QUESTIONS[-1]
        user["answers"][prev_key] = request.values.get("Body", "")
        user["state"] += 1

    ans = user["answers"]
    sexo = SEX.get(str(ans.get("sexo", "1")), "M")
    idade = 30
    altura_cm = 175
    peso_kg = 80
    act_name, act_factor = ACTIVITY.get(str(ans.get("atividade", "2")), ("Leve", 1.375))
    goal_name, goal_factor = GOAL.get(str(ans.get("objetivo", "2")), ("Definição", -0.10))
    tmb = mifflin_st_jeor(sexo, peso_kg, altura_cm, idade)
    tdee = tmb * act_factor
    calories = int(round(tdee * (1 + goal_factor), 0))
    protein, carbs, fat = split_macros(calories)
    water_ml = int(round(peso_kg * 37.5)) * 10

    user["profile"] = {
        "sex": sexo,
        "age": idade,
        "height_cm": altura_cm,
        "weight_kg": peso_kg,
        "activity": act_name,
        "goal_name": goal_name,
        "tmb": int(round(tmb)),
        "tdee": int(round(tdee)),
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "water_ml": water_ml,
    }

    db["users"][from_phone] = user
    save_db(db)
    result = (
        "✅ Pronto! Este é seu plano inicial:\n"
        f"• TMB: {int(round(tmb))} kcal\n"
        f"• TDEE (atividade {act_name}): {int(round(tdee))} kcal\n"
        f"• 🎯 Calorias meta: {calories} kcal\n"
        f"• 🧮 Macros (g): P{protein} C{carbs} G{fat}\n"
        f"• 💧 Água/dia: {water_ml} ml\n\n"
        "Digite 'status' para ver de novo ou 'reiniciar' para refazer."
    )
    resp.message(result)
    return str(resp)

@app.get("/admin/ping")
def ping():
    return {"ok": True, "project": PROJECT_NAME}

if __name__ == "__main__":
    # usa 8080 se PORT estiver vazia ou não existir
    port = int(os.getenv("PORT") or "8080")
    app.run(host="0.0.0.0", port=port)
@app.get("/")
def root():
    return {"ok": True, "project": PROJECT_NAME}
