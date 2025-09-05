def build_reply(body: str, sender: str) -> str:
    """
    Menu real (topo) e respostas objetivas.
    - 'menu' ou '0' -> mostra opções
    - '1' -> Mete o Shape (status rápido)
    - '2' -> Cardápio/Pedidos (explica fluxo híbrido)
    - '3' -> Assistente Educacional (status rápido)
    - 'ping' -> health
    """
    text = (body or "").strip().lower()

    if text in {"ping", "status", "up"}:
        return "✅ Online.\nUse 'menu' para ver opções."

    if text in {"menu", "0"}:
        return (
            "📋 MENU PRINCIPAL\n"
            "1) 🏋️ Mete o Shape — treino/dieta via WhatsApp\n"
            "2) 🍔 Cardápio/Pedidos — escolher no site e fechar pelo WhatsApp\n"
            "3) 📚 Assistente Educacional — MAT/PT/Leitura\n"
            "\nResponda com 1, 2 ou 3."
        )

    if text == "1":
        return (
            "🏋️ METE O SHAPE\n"
            "• Status: esqueleto pronto e webhook ativo.\n"
            "• Próximo: anamnese ➜ macro ➜ cardápio/treino diário.\n"
            "Digite 'menu' para voltar."
        )

    if text == "2":
        return (
            "🍔 CARDÁPIO/PEDIDOS\n"
            "Fluxo híbrido: você abre o cardápio (HTML), monta o carrinho e finaliza; "
            "o pedido chega aqui no WhatsApp e o status é atualizado por mensagem.\n"
            "Digite 'menu' para voltar."
        )

    if text == "3":
        return (
            "📚 ASSISTENTE EDUCACIONAL\n"
            "Fluxo: Matemática → Português → Leitura (90 dias). "
            "Está pronto para ativar Leitura.\n"
            "Digite 'menu' para voltar."
        )

    # Fallback SEM eco (mais limpo)
    return "Não entendi. Digite 'menu' para ver as opções."
