import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template
from openai import OpenAI

app = Flask(__name__)

URLS_FILE   = "urls.json"
CONFIG_FILE = "config.json"

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

def salvar_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ─── URLs ────────────────────────────────────────────────────────

def carregar_urls():
    if not os.path.exists(URLS_FILE):
        return []
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_urls(urls):
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)


# ─── osTicket ────────────────────────────────────────────────────

def buscar_base_conhecimento(pergunta):
    """Busca artigos na base de conhecimento do osTicket."""
    try:
        headers = {
            "X-API-Key": OSTICKET_KEY,
            "Content-Type": "application/json",
        }
        # Busca FAQs públicas
        url = f"{OSTICKET_URL}/api/kb/faqs.json"
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return ""

        faqs = resp.json()
        pergunta_lower = pergunta.lower()
        resultados = []

        for faq in faqs if isinstance(faqs, list) else faqs.get("faqs", []):
            titulo   = faq.get("question", faq.get("title", ""))
            conteudo = faq.get("answer",   faq.get("content", ""))
            # Verifica relevância simples por palavras-chave
            palavras = pergunta_lower.split()
            if any(p in (titulo + conteudo).lower() for p in palavras if len(p) > 3):
                resultados.append(f"Pergunta: {titulo}\nResposta: {conteudo}")

        return "\n\n".join(resultados[:3]) if resultados else ""
    except Exception:
        return ""


def verificar_chamados(email):
    """Verifica chamados abertos de um cliente pelo e-mail."""
    try:
        headers = {
            "X-API-Key": OSTICKET_KEY,
            "Content-Type": "application/json",
        }
        url  = f"{OSTICKET_URL}/api/tickets.json?email={email}"
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None

        dados    = resp.json()
        tickets  = dados if isinstance(dados, list) else dados.get("tickets", [])
        abertos  = [t for t in tickets if t.get("status", "").lower() in ["open", "aberto"]]

        if not abertos:
            return "Não encontrei chamados abertos para esse e-mail."

        linhas = [f"Encontrei {len(abertos)} chamado(s) aberto(s):"]
        for t in abertos[:3]:
            linhas.append(
                f"• #{t.get('number', t.get('id', '?'))} — {t.get('subject', 'Sem assunto')} "
                f"[{t.get('status', '')}]"
            )
        return "\n".join(linhas)
    except Exception:
        return None


def abrir_chamado(nome, email, assunto, mensagem, topico_id=None):
    """Abre um novo chamado no osTicket."""
    try:
        headers = {
            "X-API-Key": OSTICKET_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "name":     nome,
            "email":    email,
            "subject":  assunto,
            "message":  f"data:text/html,{mensagem}",
            "ip":       "0.0.0.0",
        }
        if topico_id:
            payload["topicId"] = topico_id

        url  = f"{OSTICKET_URL}/api/tickets.json"
        resp = requests.post(url, headers=headers, json=payload, timeout=10)

        if resp.status_code in [200, 201]:
            numero = resp.text.strip().strip('"')
            return f"Chamado #{numero} aberto com sucesso! Você receberá atualizações no e-mail {email}."
        return None
    except Exception:
        return None


# ─── Contexto de URLs ─────────────────────────────────────────────

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

def montar_contexto():
    urls = carregar_urls()
    if not urls:
        return ""
    ctx = "Informações da loja:\n\n"
    for item in urls:
        c = ler_url(item["url"])
        if c:
            ctx += f"--- {item['nome']} ---\n{c}\n\n"
    return ctx


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
    config = carregar_config()
    config["modelo"] = modelo
    salvar_config(config)
    return jsonify({"ok": True, "modelo": modelo})


@app.route("/urls", methods=["GET"])
def listar_urls():
    return jsonify(carregar_urls())

@app.route("/urls", methods=["POST"])
def adicionar_url():
    dados = request.json
    if not dados or not dados.get("url") or not dados.get("nome"):
        return jsonify({"erro": "Informe 'url' e 'nome'."}), 400
    urls = carregar_urls()
    urls.append({"nome": dados["nome"], "url": dados["url"]})
    salvar_urls(urls)
    return jsonify({"ok": True})

@app.route("/urls/<int:index>", methods=["DELETE"])
def remover_url(index):
    urls = carregar_urls()
    if index < 0 or index >= len(urls):
        return jsonify({"erro": "URL não encontrada."}), 404
    urls.pop(index)
    salvar_urls(urls)
    return jsonify({"ok": True})


@app.route("/ticket", methods=["POST"])
def criar_ticket():
    """Abre um chamado diretamente via API."""
    dados    = request.json
    nome     = dados.get("nome", "").strip()
    email    = dados.get("email", "").strip()
    assunto  = dados.get("assunto", "Solicitação de atendimento").strip()
    mensagem = dados.get("mensagem", "").strip()

    if not nome or not email or not mensagem:
        return jsonify({"erro": "Informe nome, email e mensagem."}), 400

    resultado = abrir_chamado(nome, email, assunto, mensagem)
    if resultado:
        return jsonify({"ok": True, "mensagem": resultado})
    return jsonify({"erro": "Não foi possível abrir o chamado."}), 500


@app.route("/chamados", methods=["GET"])
def listar_chamados():
    """Verifica chamados de um cliente pelo e-mail."""
    email = request.args.get("email", "").strip()
    if not email:
        return jsonify({"erro": "Informe o e-mail."}), 400
    resultado = verificar_chamados(email)
    return jsonify({"resultado": resultado})


@app.route("/chat", methods=["POST"])
def chat():
    dados    = request.json
    pergunta = dados.get("pergunta", "").strip()
    email    = dados.get("email", "").strip()

    if not pergunta:
        return jsonify({"erro": "Informe a pergunta."}), 400

    config  = carregar_config()
    modelo  = config.get("modelo", "sabia-4")

    # Detectar intenções especiais
    pergunta_lower = pergunta.lower()

    # Intenção: verificar chamado
    if email and any(p in pergunta_lower for p in ["meu chamado", "meu ticket", "minha solicitação", "status", "andamento"]):
        resultado_chamado = verificar_chamados(email)
        if resultado_chamado:
            return jsonify({"resposta": resultado_chamado, "modelo_usado": "osticket", "intencao": "chamado"})

    # Intenção: abrir chamado de troca/devolução
    intencao_troca = any(p in pergunta_lower for p in [
        "quero trocar", "trocar produto", "devolver", "devolução",
        "arrependimento", "produto com defeito", "abrir chamado", "abrir ticket"
    ])

    # Busca na base de conhecimento do osTicket
    kb_contexto = buscar_base_conhecimento(pergunta)

    # Contexto das URLs cadastradas
    url_contexto = montar_contexto()

    # Monta o system prompt
    system_parts = [
        "Você é um assistente de atendimento ao cliente de uma loja virtual. "
        "Responda de forma clara, simpática e objetiva, sempre em português."
    ]

    if kb_contexto:
        system_parts.append(f"\nBase de conhecimento da loja:\n{kb_contexto}")

    if url_contexto:
        system_parts.append(f"\nInformações adicionais:\n{url_contexto}")

    if intencao_troca:
        system_parts.append(
            "\nO cliente deseja abrir um chamado de troca ou devolução. "
            "Oriente-o a informar: nome completo, e-mail e número do pedido. "
            "Informe que assim que ele fornecer esses dados, o chamado será aberto automaticamente."
        )

    if not kb_contexto and not url_contexto:
        system_parts.append(
            "\nSe não souber a resposta, diga que não sabe e sugira que o cliente "
            "entre em contato pelo WhatsApp ou abra um chamado."
        )

    system_prompt = " ".join(system_parts)

    response = client.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": pergunta},
        ],
        max_tokens=600,
    )

    resposta   = response.choices[0].message.content
    return jsonify({
        "resposta":     resposta,
        "modelo_usado": modelo,
        "intencao":     "troca" if intencao_troca else "geral",
        "kb_encontrou": bool(kb_contexto),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
