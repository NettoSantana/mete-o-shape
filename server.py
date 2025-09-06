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
