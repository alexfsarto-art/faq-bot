import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

CONFIG_FILE = "config.json"
URLS_FILE   = "urls.json"
INFO_FILE   = "info_extra.txt"

client = OpenAI(
    api_key=os.environ.get("MARITACA_API_KEY"),
    base_url="https://chat.maritaca.ai/api",
)

MODELOS_DISPONIVEIS = {
    "sabia-4":      "Sabiá 4 — mais inteligente, respostas mais completas",
    "sabiazinho-4": "Sabiázinho 4 — mais rápido e econômico",
}

OSTICKET_URL = os.environ.get("OSTICKET_URL", "https://www.alexsartoshop.com.br/suporte")
OSTICKET_KEY = os.environ.get("OSTICKET_API_KEY", "468BDF9419886AF9B7968FB2B373D8E7")


# ─── Config ──────────────────────────────────────────────────────

def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        return {"modelo": "sabia-4"}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─── Info extra ──────────────────────────────────────────────────

def carregar_info():
    if not os.path.exists(INFO_FILE):
        return ""
    with open(INFO_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def salvar_info(texto):
    with open(INFO_FILE, "w", encoding="utf-8") as f:
        f.write(texto.strip())


# ─── URLs ────────────────────────────────────────────────────────

def carregar_urls():
    if not os.path.exists(URLS_FILE):
        return []
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_urls(urls):
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)

def ler_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp    = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        texto = resp.text
        texto = re.sub(r"<style[^>]*>.*?</style>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<script[^>]*>.*?</script>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto[:4000]
    except Exception:
        return ""

def montar_contexto_urls():
    urls = carregar_urls()
    if not urls:
        return ""
    ctx = ""
    for item in urls:
        c = ler_url(item["url"])
        if c:
            ctx += f"--- {item['nome']} ---\n{c}\n\n"
    return ctx


# ─── osTicket ────────────────────────────────────────────────────

def abrir_chamado(nome, email, assunto, mensagem):
    try:
        headers = {
            "X-API-Key": OSTICKET_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "name":    nome,
            "email":   email,
            "subject": assunto,
            "message": f"data:text/html,{mensagem}",
            "ip":      "0.0.0.0",
        }
        resp = requests.post(
            f"{OSTICKET_URL}/api/tickets.json",
            headers=headers, json=payload, timeout=10
        )
        if resp.status_code in [200, 201]:
            numero = resp.text.strip().strip('"')
            return numero
        return None
    except Exception:
        return None


# ─── Rotas ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("admin.html")


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({**carregar_config(), "modelos": MODELOS_DISPONIVEIS})

@app.route("/config", methods=["POST"])
def set_config():
    dados  = request.json
    modelo = dados.get("modelo", "").strip()
    if modelo not in MODELOS_DISPONIVEIS:
        return jsonify({"erro": "Modelo inválido."}), 400
    cfg = carregar_config()
    cfg["modelo"] = modelo
    salvar_config(cfg)
    return jsonify({"ok": True})


@app.route("/info", methods=["GET"])
def get_info():
    return jsonify({"texto": carregar_info()})

@app.route("/info", methods=["POST"])
def set_info():
    dados = request.json
    texto = dados.get("texto", "").strip()
    salvar_info(texto)
    return jsonify({"ok": True})


@app.route("/urls", methods=["GET"])
def listar_urls():
    return jsonify(carregar_urls())

@app.route("/urls", methods=["POST"])
def adicionar_url():
    dados = request.json
    if not dados or not dados.get("url") or not dados.get("nome"):
        return jsonify({"erro": "Informe url e nome."}), 400
    urls = carregar_urls()
    urls.append({"nome": dados["nome"], "url": dados["url"]})
    salvar_urls(urls)
    return jsonify({"ok": True})

@app.route("/urls/<int:index>", methods=["DELETE"])
def remover_url(index):
    urls = carregar_urls()
    if index < 0 or index >= len(urls):
        return jsonify({"erro": "Não encontrada."}), 404
    urls.pop(index)
    salvar_urls(urls)
    return jsonify({"ok": True})


@app.route("/ticket", methods=["POST"])
def criar_ticket():
    dados    = request.json
    nome     = dados.get("nome", "").strip()
    email    = dados.get("email", "").strip()
    assunto  = dados.get("assunto", "Solicitação").strip()
    mensagem = dados.get("mensagem", "").strip()
    if not nome or not email or not mensagem:
        return jsonify({"erro": "Informe nome, email e mensagem."}), 400
    numero = abrir_chamado(nome, email, assunto, mensagem)
    if numero:
        return jsonify({"ok": True, "numero": numero})
    return jsonify({"erro": "Não foi possível abrir o chamado."}), 500


@app.route("/chat", methods=["POST"])
def chat():
    dados    = request.json
    pergunta = dados.get("pergunta", "").strip()
    historico = dados.get("historico", [])

    if not pergunta:
        return jsonify({"erro": "Informe a pergunta."}), 400

    config = carregar_config()
    modelo = config.get("modelo", "sabia-4")
    pergunta_lower = pergunta.lower()

    # Detectar se cliente enviou dados para abrir chamado
    # Padrão: contém e-mail + número de pedido na mensagem
    tem_email  = bool(re.search(r"[\w.+-]+@[\w-]+\.\w+", pergunta))
    tem_pedido = bool(re.search(r"\b\d{2,}\b", pergunta))
    quer_troca = any(p in pergunta_lower for p in [
        "trocar", "troca", "devolver", "devolução", "defeito",
        "abrir chamado", "abrir ticket", "solicitação"
    ])

    # Se historico indica que estava em fluxo de troca e agora tem email+pedido
    em_fluxo_troca = any(
        "nome completo" in m.get("conteudo", "").lower() or
        "número do pedido" in m.get("conteudo", "").lower()
        for m in historico if m.get("papel") == "bot"
    )

    if em_fluxo_troca and tem_email and tem_pedido:
        # Extrai dados da mensagem
        email_match = re.search(r"[\w.+-]+@[\w-]+\.\w+", pergunta)
        email_cliente = email_match.group(0) if email_match else "não informado"

        # Tenta extrair nome (primeira palavra antes do ; ou ,)
        partes = re.split(r"[;,]", pergunta)
        nome_cliente  = partes[0].strip() if partes else "Cliente"
        pedido_match  = re.search(r"\b(\d{2,})\b", pergunta)
        num_pedido    = pedido_match.group(1) if pedido_match else "não informado"

        mensagem_ticket = (
            f"Solicitação de troca/devolução\n"
            f"Cliente: {nome_cliente}\n"
            f"E-mail: {email_cliente}\n"
            f"Pedido: #{num_pedido}\n"
            f"Mensagem original: {pergunta}"
        )

        numero = abrir_chamado(
            nome_cliente, email_cliente,
            f"Troca/Devolução — Pedido #{num_pedido}",
            mensagem_ticket
        )

        if numero:
            return jsonify({
                "resposta": (
                    f"✅ Chamado **#{numero}** aberto com sucesso!\n\n"
                    f"Você receberá as próximas atualizações no e-mail **{email_cliente}**. "
                    f"Nossa equipe entrará em contato em breve para orientar o processo de troca. 😊"
                ),
                "modelo_usado": "osticket",
                "intencao": "troca_aberta",
            })

    # Monta contexto
    info_extra   = carregar_info()
    url_contexto = montar_contexto_urls()

    system_parts = [
        "Você é um assistente de atendimento ao cliente de uma loja virtual chamada Alex Sarto Shop. "
        "Responda de forma clara, simpática e objetiva, sempre em português brasileiro."
    ]

    if info_extra:
        system_parts.append(f"\nInformações da loja:\n{info_extra}")

    if url_contexto:
        system_parts.append(f"\nConteúdo adicional:\n{url_contexto}")

    if quer_troca:
        system_parts.append(
            "\nO cliente quer trocar ou devolver um produto. "
            "Peça: nome completo, e-mail cadastrado na compra e número do pedido. "
            "Diga que assim que ele enviar esses dados, o chamado será aberto automaticamente."
        )
    elif not info_extra and not url_contexto:
        system_parts.append(
            "\nSe não souber a resposta, diga que não sabe e sugira contato pelo WhatsApp ou abertura de chamado."
        )

    system_prompt = "\n".join(system_parts)

    # Monta mensagens com histórico
    messages = [{"role": "system", "content": system_prompt}]
    for m in historico[-6:]:  # últimas 6 mensagens para contexto
        role = "user" if m.get("papel") == "usuario" else "assistant"
        messages.append({"role": role, "content": m.get("conteudo", "")})
    messages.append({"role": "user", "content": pergunta})

    response = client.chat.completions.create(
        model=modelo,
        messages=messages,
        max_tokens=600,
    )

    return jsonify({
        "resposta":     response.choices[0].message.content,
        "modelo_usado": modelo,
        "intencao":     "troca" if quer_troca else "geral",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
