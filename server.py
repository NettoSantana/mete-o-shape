def build_reply(body: str, sender: str) -> str:
    """
    Menu real (topo) e respostas objetivas.
    - 'menu' ou '0' -> mostra opções
    - '1' -> Mete o Shape
    - '2' -> Cardápio/Pedidos
    - '3' -> Assistente Educacional
    - 'ping' -> healthcheck
    """
    text = (body or "").strip().lower()

    if text in {"ping", "status", "up"}:
        return "✅ Online.\nUse 'menu' para ver opções."

    if text in {"menu", "0"}:
        return (
            "📋 MENU PRINCIPAL\n"
            "1️⃣ 🏋️ Mete o Shape — treino/dieta via WhatsApp\n"
            "2️⃣ 🍔 Cardápio/Pedidos — escolher no site e fechar pelo WhatsApp\n"
            "3️⃣ 📚 Assistente Educacional — MAT/PT/Leitura\n"
            "\nResponda com 1, 2 ou 3."
        )

    if text == "1":
        return (
            "🏋️ METE O SHAPE\n"
            "Esqueleto ativo ✅\n"
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

    # Fallback sem eco
    return "❓ Não entendi.\nDigite 'menu' para ver as opções."
