import os
import json
import requests
from flask import Flask, request, jsonify, render_template
from openai import OpenAI

app = Flask(__name__)

URLS_FILE    = "urls.json"
CONFIG_FILE  = "config.json"

# Cliente da Maritaca AI
client = OpenAI(
    api_key=os.environ.get("MARITACA_API_KEY"),
    base_url="https://chat.maritaca.ai/api",
)

MODELOS_DISPONIVEIS = {
    "sabia-4":      "Sabiá 4 — mais inteligente, respostas mais completas",
    "sabiazinho-4": "Sabiázinho 4 — mais rápido e econômico",
}


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


# ─── Conteúdo das páginas ────────────────────────────────────────

def ler_conteudo_url(url):
    try:
        import re
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        texto = resp.text
        texto = re.sub(r"<style[^>]*>.*?</style>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<script[^>]*>.*?</script>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto[:4000]
    except Exception as e:
        return f"(Não foi possível ler a página: {e})"

def montar_contexto():
    urls = carregar_urls()
    if not urls:
        return ""
    contexto = "Abaixo estão as políticas e informações da loja:\n\n"
    for item in urls:
        conteudo = ler_conteudo_url(item["url"])
        contexto += f"--- {item['nome']} ---\n{conteudo}\n\n"
    return contexto


# ─── Rotas ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("admin.html")


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({**carregar_config(), "modelos": MODELOS_DISPONIVEIS})

@app.route("/config", methods=["POST"])
def set_config():
    dados = request.json
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


@app.route("/chat", methods=["POST"])
def chat():
    dados   = request.json
    pergunta = dados.get("pergunta", "").strip()
    if not pergunta:
        return jsonify({"erro": "Informe a pergunta."}), 400

    config  = carregar_config()
    modelo  = config.get("modelo", "sabia-4")
    contexto = montar_contexto()

    if contexto:
        system_prompt = (
            "Você é um assistente de atendimento ao cliente de uma loja virtual. "
            "Responda de forma clara, simpática e objetiva, sempre em português. "
            "Use APENAS as informações abaixo para responder. "
            "Se a resposta não estiver nas informações, diga que não sabe e sugira "
            "que o cliente entre em contato diretamente com a loja.\n\n"
            + contexto
        )
    else:
        system_prompt = (
            "Você é um assistente de atendimento ao cliente de uma loja virtual. "
            "Responda de forma clara, simpática e objetiva, sempre em português. "
            "Se não souber a resposta, diga que não sabe e sugira que o cliente "
            "entre em contato diretamente com a loja."
        )

    response = client.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": pergunta},
        ],
        max_tokens=600,
    )

    resposta = response.choices[0].message.content
    return jsonify({"resposta": resposta, "modelo_usado": modelo})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
