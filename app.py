import os
import json
import requests
from flask import Flask, request, jsonify, render_template
from openai import OpenAI

app = Flask(__name__)

# Arquivo onde as URLs ficam salvas
URLS_FILE = "urls.json"

# Cliente da Maritaca AI
client = OpenAI(
    api_key=os.environ.get("MARITACA_API_KEY"),
    base_url="https://chat.maritaca.ai/api",
)


def carregar_urls():
    """Lê as URLs salvas no arquivo."""
    if not os.path.exists(URLS_FILE):
        return []
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_urls(urls):
    """Salva as URLs no arquivo."""
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)


def ler_conteudo_url(url):
    """Lê o texto de uma página da web."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        # Remove tags HTML de forma simples
        texto = resp.text
        import re
        texto = re.sub(r"<style[^>]*>.*?</style>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<script[^>]*>.*?</script>", "", texto, flags=re.DOTALL)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()

        # Limita o tamanho para não estourar o contexto da IA
        return texto[:4000]
    except Exception as e:
        return f"(Não foi possível ler a página: {e})"


def montar_contexto():
    """Lê todas as URLs cadastradas e monta um contexto para a IA."""
    urls = carregar_urls()
    if not urls:
        return ""

    contexto = "Abaixo estão as políticas e informações da loja:\n\n"
    for item in urls:
        conteudo = ler_conteudo_url(item["url"])
        contexto += f"--- {item['nome']} ---\n{conteudo}\n\n"

    return contexto


# ─── Rotas da API ────────────────────────────────────────────────

@app.route("/")
def index():
    """Painel de administração."""
    return render_template("admin.html")


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
    """Endpoint principal — recebe a pergunta e retorna a resposta da IA."""
    dados = request.json
    pergunta = dados.get("pergunta", "").strip()

    if not pergunta:
        return jsonify({"erro": "Informe a pergunta."}), 400

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
        model="sabia-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": pergunta},
        ],
        max_tokens=600,
    )

    resposta = response.choices[0].message.content
    return jsonify({"resposta": resposta})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
