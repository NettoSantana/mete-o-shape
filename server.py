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

    # Healthcheck
    if text in {"ping", "status", "up"}:
        return "✅ Online.\nDigite 'menu' para ver as opções."

    # Menu principal
    if text in {"menu", "0"}:
        return (
            "📋 MENU PRINCIPAL\n"
            "1️⃣ 🏋️ Mete o Shape — treino/dieta via WhatsApp\n"
            "2️⃣ 🍔 Cardápio/Pedidos — escolher no site e fechar pelo WhatsApp\n"
            "3️⃣ 📚 Assistente Educacional — MAT/PT/Leitura\n"
            "\nResponda com 1, 2 ou 3."
        )

    # Opções
    if text == "1":
        return (
            "🏋️ METE O SHAPE\n"
            "Status: esqueleto ativo ✅\n"
            "➡️ Fluxo: Anamnese → Macros → Cardápio/Treino diário.\n"
            "Digite 'menu' para voltar."
        )

    if text == "2":
        return (
            "🍔 CARDÁPIO/PEDIDOS\n"
            "Fluxo híbrido: abra o cardápio (HTML), monte seu carrinho e finalize.\n"
            "➡️ O pedido é registrado no WhatsApp e atualizado por status.\n"
            "Digite 'menu' para voltar."
        )

    if text == "3":
        return (
            "📚 ASSISTENTE EDUCACIONAL\n"
            "Fluxo: Matemática → Português → Leitura (90 dias).\n"
            "➡️ Pronto para ativar Leitura.\n"
            "Digite 'menu' para voltar."
        )

    # Fallback
    return "❓ Não entendi.\nDigite 'menu' para ver as opções."
