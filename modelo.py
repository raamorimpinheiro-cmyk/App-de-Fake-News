"""
Integração com a API da OpenAI (ChatGPT).

Requisitos:
    pip install openai python-dotenv

Arquivo .env (na MESMA pasta deste arquivo):
    OPENAI_API_KEY=sua_chave_aqui

    # Opcional: chaves diferentes conforme o tamanho da pergunta.
    # Se alguma faltar, usa OPENAI_API_KEY.
    # OPENAI_API_KEY_1=chave_para_textos_de_ate_50_caracteres
    # OPENAI_API_KEY_2=chave_para_textos_de_51_a_100_caracteres
    # OPENAI_API_KEY_3=chave_para_textos_de_101_caracteres_ou_mais

    # Opcional: modelo (geral ou por API)
    # OPENAI_MODEL=gpt-5-mini
    # OPENAI_MODEL_3=gpt-5
"""

import os
import re
import json
import base64
import threading

from dotenv import load_dotenv

# Carrega o .env da pasta do projeto, independente de onde o app foi iniciado
PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PASTA_PROJETO, ".env"))

try:
    import openai
    from openai import OpenAI
    OPENAI_OK = True
except ImportError:
    OPENAI_OK = False

# Ordem de tentativa. Se um modelo não existir na sua conta (404),
# tenta o próximo. Todos aceitam texto e imagem.
MODELOS_PADRAO = [
    "gpt-5-mini",
    "gpt-5",
    "gpt-4.1-mini",
    "gpt-4o-mini",
]

# Troca de API pelo tamanho da pergunta (em caracteres):
#   até 50      -> API 1
#   51 a 100    -> API 2
#   101 ou mais -> API 3
LIMITE_API_1 = 50
LIMITE_API_2 = 100

# Imagens não têm "tamanho de texto"; como são as requisições mais
# pesadas, usam a API 3.
API_IMAGEM = 3

MIME_IMAGEM = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

VEREDITOS_NOTICIA = (
    "PROVAVELMENTE FALSA",
    "PROVAVELMENTE VERDADEIRA",
    "INCONCLUSIVA",
)

VEREDITOS_IMAGEM = (
    "PROVAVELMENTE IA",
    "POSSIVELMENTE MANIPULADA",
    "PROVAVELMENTE REAL",
)


class ErroIA(Exception):
    """Erro com mensagem amigável para mostrar na interface."""


_clientes = {}
_lock = threading.Lock()


# ============================================================
# CONFIGURAÇÃO
# ============================================================
def escolher_api(tamanho):
    """Retorna o número da API (1, 2 ou 3) conforme o tamanho da pergunta."""
    if tamanho <= LIMITE_API_1:
        return 1
    if tamanho <= LIMITE_API_2:
        return 2
    return 3


def _limpar(valor):
    return (valor or "").strip().strip('"').strip("'")


def _obter_chave(numero_api):
    """Retorna (chave, nome_da_variavel) para a API escolhida."""
    for nome in (f"OPENAI_API_KEY_{numero_api}", "OPENAI_API_KEY"):
        chave = _limpar(os.getenv(nome))
        if chave:
            return chave, nome
    raise ErroIA(
        "Chave da API da OpenAI (ChatGPT) não encontrada.\n\n"
        "Crie um arquivo .env na pasta do projeto com:\n"
        "OPENAI_API_KEY=sua_chave_aqui\n\n"
        f"Pasta esperada: {PASTA_PROJETO}"
    )


def _obter_cliente(numero_api):
    """Retorna (cliente, nome_da_variavel). Um cliente por chave."""
    if not OPENAI_OK:
        raise ErroIA(
            "Biblioteca da OpenAI não instalada.\n\n"
            "Execute: pip install openai"
        )
    chave, nome = _obter_chave(numero_api)
    with _lock:
        if chave not in _clientes:
            _clientes[chave] = OpenAI(api_key=chave, timeout=60, max_retries=2)
        return _clientes[chave], nome


def _lista_modelos(numero_api):
    modelos = []
    for nome in (f"OPENAI_MODEL_{numero_api}", "OPENAI_MODEL"):
        preferido = _limpar(os.getenv(nome))
        if preferido and preferido not in modelos:
            modelos.append(preferido)
    for m in MODELOS_PADRAO:
        if m not in modelos:
            modelos.append(m)
    return modelos


def status_configuracao():
    """Retorna None se tudo estiver ok, ou uma mensagem de erro."""
    try:
        if not OPENAI_OK:
            raise ErroIA(
                "Biblioteca da OpenAI não instalada.\n"
                "Execute: pip install openai"
            )
        _obter_chave(1)
        _obter_chave(2)
        _obter_chave(3)
        return None
    except ErroIA as e:
        return str(e)


# ============================================================
# CHAMADA À OPENAI
# ============================================================
def _traduzir_erro(e, nome_chave):
    if isinstance(e, openai.AuthenticationError):
        return (
            "Chave da API inválida.\n\n"
            f"Confira o valor de {nome_chave} no arquivo .env "
            "(gere uma nova em https://platform.openai.com/api-keys)."
        )
    if isinstance(e, openai.PermissionDeniedError):
        return (
            "Acesso negado pela API da OpenAI.\n\n"
            f"A chave {nome_chave} não tem permissão para este modelo "
            "ou sua região não é suportada."
        )
    if isinstance(e, openai.RateLimitError):
        if getattr(e, "code", None) == "insufficient_quota" or "quota" in str(e).lower():
            return (
                f"A conta da chave {nome_chave} está sem créditos.\n\n"
                "A assinatura do ChatGPT Plus NÃO inclui a API: adicione "
                "créditos em https://platform.openai.com/settings/organization/billing"
            )
        return (
            f"Limite de uso da chave {nome_chave} atingido.\n\n"
            "Aguarde alguns instantes e tente novamente."
        )
    if isinstance(e, openai.APIConnectionError):
        return (
            "Não foi possível conectar à OpenAI.\n\n"
            "Verifique sua conexão com a internet."
        )
    codigo = getattr(e, "status_code", None)
    msg = getattr(e, "message", None) or str(e)
    return f"Erro da API da OpenAI ({codigo}):\n{msg}"


def _ler_json(texto):
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        achado = re.search(r"\{.*\}", texto, re.DOTALL)
        if achado:
            return json.loads(achado.group(0))
        raise ErroIA("O ChatGPT retornou uma resposta em formato inesperado.")


def _modelo_indisponivel(e):
    if isinstance(e, openai.NotFoundError):
        return True
    return (
        isinstance(e, openai.BadRequestError)
        and "model" in str(e).lower()
        and ("does not exist" in str(e).lower() or "not supported" in str(e).lower())
    )


def _gerar_json(conteudo, numero_api):
    """`conteudo` é o campo content da mensagem do usuário (texto ou lista)."""
    cliente, nome_chave = _obter_cliente(numero_api)
    print(f"[OPENAI] Usando API {numero_api} ({nome_chave})")

    mensagens = [
        {
            "role": "system",
            "content": "Você responde sempre em português e somente com um objeto JSON válido.",
        },
        {"role": "user", "content": conteudo},
    ]

    ultimo_erro = None
    for modelo in _lista_modelos(numero_api):
        try:
            resposta = cliente.chat.completions.create(
                model=modelo,
                messages=mensagens,
                response_format={"type": "json_object"},
            )
            return _ler_json(resposta.choices[0].message.content)
        except openai.APIError as e:
            # Modelo inexistente/sem acesso ou servidor instável: tenta o próximo
            if _modelo_indisponivel(e) or isinstance(e, openai.InternalServerError):
                ultimo_erro = e
                print(f"[OPENAI] Modelo '{modelo}' falhou, tentando o próximo...")
                continue
            raise ErroIA(_traduzir_erro(e, nome_chave)) from e
        except ErroIA:
            raise
        except Exception as e:
            raise ErroIA(f"Erro inesperado ao consultar o ChatGPT:\n{e}") from e

    raise ErroIA(
        "Nenhum modelo da OpenAI respondeu.\n\n"
        f"Modelos tentados: {', '.join(_lista_modelos(numero_api))}\n"
        f"Último erro: {ultimo_erro}\n\n"
        "Defina um modelo disponível na sua conta com OPENAI_MODEL no .env."
    )


def _confianca(valor):
    try:
        valor = float(str(valor).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return 50.0
    if 0 < valor <= 1:
        valor *= 100
    return max(0.0, min(100.0, valor))


def _normalizar(valor, opcoes, padrao):
    valor = str(valor or "").upper().strip()
    for opcao in opcoes:
        if opcao in valor or (valor and valor in opcao):
            return opcao
    return padrao

# FUNÇÕES USADAS PELO APP
def verificar_noticia(texto):
    """Retorna (veredito, confianca_0_a_100, explicacao, numero_api)."""
    texto = (texto or "").strip()
    if not texto:
        raise ErroIA("Texto vazio.")

    prompt = (
        "Você é um verificador de fatos. Analise a notícia abaixo e avalie se "
        "ela parece ser desinformação (fake news). Considere: sensacionalismo, "
        "ausência de fontes, inconsistências, apelos emocionais, afirmações "
        "inverossímeis e coerência com fatos conhecidos.\n\n"
        "Responda SOMENTE com um JSON neste formato:\n"
        '{"veredito": "PROVAVELMENTE FALSA" | "PROVAVELMENTE VERDADEIRA" | "INCONCLUSIVA", '
        '"confianca": número de 0 a 100, '
        '"explicacao": "explicação curta em português (máx. 3 frases)"}\n\n'
        f"NOTÍCIA:\n{texto[:12000]}"
    )

    numero_api = escolher_api(len(texto))
    dados = _gerar_json(prompt, numero_api)
    veredito = _normalizar(dados.get("veredito"), VEREDITOS_NOTICIA, "INCONCLUSIVA")
    confianca = _confianca(dados.get("confianca"))
    explicacao = str(dados.get("explicacao", "")).strip()
    return veredito, confianca, explicacao, numero_api


def verificar_imagem(caminho):
    """Retorna (resultado, confianca_0_a_100, motivo)."""
    if not os.path.isfile(caminho):
        raise ErroIA(f"Arquivo não encontrado: {caminho}")

    extensao = os.path.splitext(caminho)[1].lower()
    mime = MIME_IMAGEM.get(extensao)
    if not mime:
        raise ErroIA("Formato não suportado. Use PNG, JPG, JPEG ou WEBP.")

    with open(caminho, "rb") as f:
        dados_imagem = f.read()

    if len(dados_imagem) > 20 * 1024 * 1024:
        raise ErroIA("Imagem muito grande (máximo 20 MB).")

    prompt = (
        "Analise esta imagem e avalie se ela foi gerada por inteligência "
        "artificial, se foi manipulada/editada, ou se parece uma foto real. "
        "Observe: mãos e dedos, textos distorcidos, iluminação e sombras "
        "inconsistentes, texturas artificiais, bordas de recortes, reflexos.\n\n"
        "Responda SOMENTE com um JSON neste formato:\n"
        '{"resultado": "PROVAVELMENTE IA" | "POSSIVELMENTE MANIPULADA" | "PROVAVELMENTE REAL", '
        '"confianca": número de 0 a 100, '
        '"motivo": "explicação curta em português (máx. 2 frases)"}'
    )

    url_imagem = f"data:{mime};base64,{base64.b64encode(dados_imagem).decode('ascii')}"
    conteudo = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": url_imagem}},
    ]

    dados = _gerar_json(conteudo, API_IMAGEM)
    resultado = _normalizar(dados.get("resultado"), VEREDITOS_IMAGEM, "PROVAVELMENTE REAL")
    confianca = _confianca(dados.get("confianca"))
    motivo = str(dados.get("motivo", "")).strip()
    return resultado, confianca, motivo
