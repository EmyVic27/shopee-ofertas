import hashlib  
import time  
import random  
import json  
import re  
import os  
import requests  
from datetime import datetime  
import urllib.parse  
import streamlit as st  
from google import genai  

# Configuração da página no Streamlit  
st.set_page_config(  
    page_title="Buscador de Ofertas Shopee + Gemini AI",  
    page_icon="🛍️",  
    layout="wide"  
)  

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"  
HISTORICO_FILE = "historico_ofertas.json"  
SESSAO_FILE = "sessao_app.json"

# ============== PERSISTÊNCIA DE SESSÃO EM DISCO ==============
# Isso resolve o problema de perder as ofertas e os filtros toda vez que o
# navegador recarrega a aba (comum no celular quando você troca de app pra
# mandar a oferta no WhatsApp e volta). Diferente do st.session_state (que
# só existe enquanto a aba fica conectada), isso fica salvo em arquivo.

DEFAULTS_SESSAO = {
    "k_modo_busca": "🏷️ Usar Categorias da Shopee",
    "k_categorias": ["🎈 Festas, Lembrancinhas & Personalizados", "🏠 Casa, Cozinha & Utensílios"],
    "k_keywords": "qualquer tema, sacolinhas pvc, pegue monte, lembrancinha",
    "k_excluir_palavras": "",
    "k_ordem": "Relevância (Igual à pesquisa do site da Shopee)",
    "k_qtd_termo": 30,
    "k_tipos_loja": ["Todas as Lojas (Recomendado - Maior volume)"],
    "k_min_vendas": 0,
    "k_min_price": 0.0,
    "k_max_price": 0.0,
    "k_usar_historico": True,
    "k_filtrar_desconto": False,
    "k_min_desconto": 20,
    "k_filtrar_comissao": False,
    "k_min_comissao": 8.0,
    "k_estilo_prompt": "Amiga / Achadinho (padrão, caloroso e natural)",
    "k_campanha_ativa": False,
    "k_dia_duplo": "",
    "k_mencionar_cupom": False,
    "k_tamanho_lote": 10,
    "resultados": [],
}


def carregar_sessao_disco() -> dict:
    if os.path.exists(SESSAO_FILE):
        try:
            with open(SESSAO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def salvar_sessao_disco():
    dados = {chave: st.session_state.get(chave) for chave in DEFAULTS_SESSAO}
    try:
        with open(SESSAO_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # se der erro ao salvar, não trava o app


# Roda só uma vez por sessão nova: carrega o que tinha salvo antes (se tinha)
if "sessao_ja_carregada" not in st.session_state:
    dados_salvos = carregar_sessao_disco()
    valores_iniciais = {**DEFAULTS_SESSAO, **dados_salvos}
    for chave, valor in valores_iniciais.items():
        st.session_state[chave] = valor
    st.session_state.sessao_ja_carregada = True


# ============== DICIONÁRIO DE CATEGORIAS DA SHOPEE ==============  

CATEGORIAS_MAP = {  
    "🎈 Festas, Lembrancinhas & Personalizados": [  
        "lembrancinha", "festa infantil", "kit personalizado", "qualquer tema",   
        "sacolinhas pvc", "pegue monte", "caixas personalizadas", "lembrancinha premium", "15 anos",
        "topo de bolo", "docinho", "balão", "painel de festa", "convite personalizado"
    ],  
    "🏠 Casa, Cozinha & Utensílios": [  
        "cozinha", "casa", "utilidades", "organizador", "eletrodomesticos", "decoração",
        "utensílios de cozinha", "potes herméticos", "cesto organizador", "tapete", "cortina"
    ],  
    "👗 Moda Feminina & Acessórios": [  
        "moda feminina", "bolsas", "acessórios", "vestido", "bijuterias", "óculos de sol",
        "relógio feminino", "sandália feminina", "conjunto feminino"
    ],  
    "👕 Moda Masculina": [
        "moda masculina", "camisa masculina", "bermuda", "tênis masculino", "relógio masculino",
        "bone", "cinto masculino"
    ],
    "💄 Beleza & Cuidados": [  
        "maquiagem", "skincare", "cabelos", "perfume", "unhas", "escova de cabelo",
        "protetor solar", "hidratante", "batom"
    ],  
    "🧸 Brinquedos & Infantil": [  
        "brinquedos", "jogos educativos", "maternidade", "infantil", "boneca", "carrinho de brinquedo",
        "quebra cabeça", "brinquedo bebê"
    ],  
    "👶 Bebês": [
        "fralda", "mamadeira", "carrinho de bebê", "roupinha bebê", "chupeta", "banheira bebê"
    ],
    "📱 Eletrônicos & Celulares": [
        "capinha de celular", "fone de ouvido", "carregador", "power bank", "smartwatch",
        "película de vidro", "suporte de celular"
    ],
    "💻 Informática": [
        "mouse", "teclado", "webcam", "pendrive", "cabo usb", "hub usb"
    ],
    "🛠️ Ferramentas & Construção": [
        "ferramentas", "furadeira", "chave de fenda", "trena", "parafusadeira"
    ],
    "🚗 Automotivo": [
        "acessórios carro", "capa de banco", "som automotivo", "aromatizante carro", "suporte veicular"
    ],
    "⚽ Esporte & Lazer": [
        "roupa fitness", "garrafa térmica", "corda de pular", "faixa elástica", "bicicleta acessórios"
    ],
    "🐶 Pet Shop": [
        "ração", "brinquedo pet", "coleira", "casinha de cachorro", "areia de gato"
    ],
    "📚 Papelaria & Escritório": [
        "caderno", "caneta", "mochila escolar", "estojo", "organizador de mesa"
    ],
    "🎮 Games": [
        "controle de video game", "acessórios ps4", "acessórios ps5", "headset gamer"
    ],
    "💊 Saúde & Suplementos": [
        "whey protein", "vitamina", "termômetro", "máscara facial", "suplemento"
    ],
    "🌐 Busca Livre Geral (Todas as Categorias da Shopee)": [  
        "promoção", "desconto", "oferta", "achadinhos", "utilidades"  
    ]  
}  

# ============== POOL DIVERSICADO DE SEGURANÇA (SEM NOME DE PRODUTO) ==============  

POOL_FALLBACK_FRASES = [  
    "Amiga, corre que isso não vai durar muito! 🏃‍♀️💨",  
    "Gente, socorro, achei um achadinho bom demais pra deixar passar! 😱",  
    "Óoo lindeza, e olha o valor disso! 😍",  
    "Para tudo, isso aqui é achado e vai esgotar rápido! ⚡",  
    "Amiga, isso tá quase de graça, olha só! 🤑",  
    "Separei isso especialmente pra você! 💛",  
    "Corre, corre, que isso não vai durar nem 5 minutos! 🏃‍♀️💨",  
    "Achei e já vim correndo te contar antes que suba o preço! 😍",  
    "Amiga, larga tudo e aproveita esse achadinho de hoje! 👀",  
    "Gente, preço bom desse jeito não dura nada! ⏳",  
    "Amiga, essa dica é de ouro pra quem ama economizar! ✨",  
    "Aqui é chance rara, garante já! 🍀",  
    "Amiga, você não tem noção do tanto que vale a pena! 🎁",  
    "Gente, esse preço ficou um absurdo de barato! 💣",  
    "Amiga, essa dica vale cada segundo, aproveita antes que esgote! 💕",  
    "Isso aqui tá voando da prateleira, pega o seu rápido! 🛒",  
    "Amiga, hoje é dia de sorte com esse preço! 🌟",  
    "Gente, eu juro que fiquei de boca aberta com esse valor! 😮",  
    "Amiga, corre que fica ainda mais em conta! 🎟️",  
    "Isso aqui é hit garantido, separado com todo carinho! 🌸"  
]  

# ============== FUNÇÕES DE API E AUXILIARES ==============  

def gerar_assinatura(app_id: str, app_secret: str, payload: str, timestamp: int) -> str:  
    base = f"{app_id}{timestamp}{payload}{app_secret}"  
    return hashlib.sha256(base.encode("utf-8")).hexdigest()  

def buscar_ofertas(app_id: str, app_secret: str, keyword, limit: int = 10, page: int = 1, sort_type: int = 1):  
    """Consulta a API da Shopee. sort_type: 1 = Relevância (Site), 2 = Comissão, 3 = Populares/Vendas"""  
    query = """  
    query buscarOfertas($keyword: String, $limit: Int, $page: Int, $sortType: Int) {  
        productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: $sortType) {  
            nodes {  
                itemId  
                productName  
                price  
                priceMin  
                priceMax  
                commissionRate  
                offerLink  
                imageUrl  
                priceDiscountRate  
                shopId  
                shopType  
                sales  
            }
            # ATENÇÃO: "sales" não é um campo confirmado no schema oficial da
            # Shopee (não achamos documentação garantindo isso). Se a busca
            # começar a retornar erro "Cannot query field 'sales'", remova essa
            # linha e o filtro de vendas mínimas vai parar de funcionar até lá.  
            pageInfo {  
                page  
                limit  
                hasNextPage  
            }  
        }  
    }  
    """  
    payload = json.dumps({  
        "query": query,  
        "variables": {  
            "keyword": keyword if keyword else None,   
            "limit": limit,   
            "page": page,  
            "sortType": sort_type  
        }  
    })  
    
    timestamp = int(time.time())  
    assinatura = gerar_assinatura(app_id, app_secret, payload, timestamp)  
    
    headers = {  
        "Content-Type": "application/json",  
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={assinatura}",  
    }  
    
    try:  
        resp = requests.post(API_URL, data=payload, headers=headers, timeout=15)  
        resp.raise_for_status()  
        data = resp.json()  
        if "errors" in data:  
            return [], False, str(data["errors"])  
        
        bloco = data.get("data", {}).get("productOfferV2", {})  
        nodes = bloco.get("nodes", [])  
        has_next = bloco.get("pageInfo", {}).get("hasNextPage", False)  
        return nodes, has_next, None  
    except Exception as e:  
        return [], False, str(e)  

def buscar_todas_ofertas(app_id: str, app_secret: str, keyword, total_desejado: int, sort_type: int = 1):  
    todas = []  
    page = 1  
    ultimo_erro = None  
    while len(todas) < total_desejado:  
        restante = total_desejado - len(todas)  
        limite_pagina = min(50, restante)  
        nodes, has_next, erro = buscar_ofertas(app_id, app_secret, keyword, limite_pagina, page, sort_type)  
        if erro:  
            ultimo_erro = erro  
            break  
        if not nodes:  
            break  
        todas.extend(nodes)  
        if not has_next:  
            break  
        page += 1  
    return todas, ultimo_erro  

def obter_tipos_loja(oferta) -> list:  
    shop_type = oferta.get("shopType")  
    if isinstance(shop_type, list):  
        return shop_type  
    if shop_type is not None:  
        return [shop_type]  
    return []  

PALAVRAS_IGNORAR = {  
    "kit", "un un", "unid", "unidade", "unidades", "pct", "pacote", "pacotes",  
    "com", "sem", "de", "da", "do", "para", "pra", "e", "ou", "un", "peça", "pecas",  
}  

def _singularizar(palavra: str) -> str:
    """Normalização simples de plural em português (heurística, não é gramática perfeita,
    mas resolve a maioria dos casos tipo 'copos'->'copo', 'sacolas'->'sacola')."""
    if len(palavra) > 4 and palavra.endswith("ns"):
        return palavra[:-2] + "m"
    if len(palavra) > 4 and palavra.endswith("res"):
        return palavra[:-2]
    if len(palavra) > 4 and palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


def normalizar_produto(nome: str) -> frozenset:
    """Gera um CONJUNTO de palavras-chave do produto (não mais uma string fixa),
    ignorando números/quantidades e normalizando plural, pra permitir comparar
    por SIMILARIDADE (não precisa ser 100% idêntico pra contar como duplicata)."""
    if not nome:
        return frozenset()
    texto = nome.lower()
    texto = re.sub(r"\d+[/\d]*", " ", texto)  # remove qualquer número/sequência (05/25/50, 100, etc.)
    texto = re.sub(r"[^\w\sáàâãéêíóôõúüç]", " ", texto)
    palavras = {_singularizar(p) for p in texto.split() if p not in PALAVRAS_IGNORAR and len(p) > 2}
    return frozenset(palavras)


def produtos_sao_parecidos(a: frozenset, b: frozenset, limiar: float = 0.55) -> bool:
    """Compara dois produtos por similaridade de Jaccard (interseção/união das
    palavras). limiar=0.55 significa que precisa ter mais da metade das
    palavras em comum pra contar como 'mesmo produto'."""
    if not a or not b:
        return False
    intersecao = len(a & b)
    if intersecao == 0:
        return False
    uniao = len(a | b)
    return (intersecao / uniao) >= limiar


def produto_ja_visto(produto_key: frozenset, lista_vistos: list, limiar: float = 0.55) -> bool:
    return any(produtos_sao_parecidos(produto_key, visto, limiar) for visto in lista_vistos)

def carregar_historico() -> dict:  
    if os.path.exists(HISTORICO_FILE):  
        try:  
            with open(HISTORICO_FILE, "r", encoding="utf-8") as f:  
                return json.load(f)  
        except Exception:  
            pass  
    return {"links": [], "produtos": [], "frases": []}  

def salvar_historico(historico: dict):  
    with open(HISTORICO_FILE, "w", encoding="utf-8") as f:  
        json.dump(historico, f, ensure_ascii=False, indent=2)  

def limpar_historico_arquivo():  
    salvar_historico({"links": [], "produtos": [], "frases": []})  

def filtrar_ofertas(ofertas, historico: dict, usar_historico: bool,  
                    tipos_loja_selecionados: list, min_vendas: int,  
                    filtrar_comissao: bool, min_comissao: float,  
                    filtrar_desconto: bool, min_desconto: float,  
                    min_preco: float, max_preco: float,
                    palavras_excluidas: list = None):  
    links_usados = set(historico["links"]) if usar_historico else set()  
    # compatibilidade: histórico antigo guardava string, o novo guarda lista de palavras
    produtos_usados = []
    if usar_historico:
        for p in historico["produtos"]:
            if isinstance(p, str):
                produtos_usados.append(frozenset(p.split()))
            else:
                produtos_usados.append(frozenset(p))
    produtos_nesta_rodada = []  
    
    filtradas = []  
    descartes_historico = 0  
    descartes_preco = 0  
    descartes_loja = 0  
    descartes_vendas = 0  
    descartes_excluidos = 0
    palavras_excluidas = palavras_excluidas or []
    
    for oferta in ofertas:  
        comissao = float(oferta.get("commissionRate") or 0) * 100  
        desconto = float(oferta.get("priceDiscountRate") or 0)  
        link = oferta.get("offerLink", "")  
        produto_key = normalizar_produto(oferta.get("productName", ""))  
        nome_lower = (oferta.get("productName") or "").lower()
        preco = float(oferta.get("price") or oferta.get("priceMin") or 0)  
        vendas = int(oferta.get("sales") or 0)  
        loja_tipos = obter_tipos_loja(oferta)  

        if palavras_excluidas and any(p in nome_lower for p in palavras_excluidas):
            descartes_excluidos += 1
            continue
        
        # Correção no filtro de tipo de loja para aceitar variações do rótulo  
        passou_loja = False  
        if not tipos_loja_selecionados or any("Todas" in str(t) for t in tipos_loja_selecionados):  
            passou_loja = True  
        else:  
            if any("Oficiais" in str(t) for t in tipos_loja_selecionados) and 1 in loja_tipos:  
                passou_loja = True  
            if any("Indicadas" in str(t) for t in tipos_loja_selecionados) and 2 in loja_tipos:  
                passou_loja = True  
        
        if not passou_loja:  
            descartes_loja += 1  
            continue  
            
        if vendas < min_vendas:  
            descartes_vendas += 1  
            continue  
            
        if (min_preco > 0 and preco < min_preco) or (max_preco > 0 and preco > max_preco):  
            descartes_preco += 1  
            continue  
            
        if filtrar_comissao and comissao < min_comissao:  
            continue  
        if filtrar_desconto and desconto < min_desconto:  
            continue  
            
        if usar_historico:  
            if link in links_usados or produto_ja_visto(produto_key, produtos_usados) or produto_ja_visto(produto_key, produtos_nesta_rodada):  
                descartes_historico += 1  
                continue  
        
        produtos_nesta_rodada.append(produto_key)  
        filtradas.append(oferta)  
        
    filtradas.sort(key=lambda o: float(o.get("priceDiscountRate") or 0), reverse=True)  
    stats = {  
        "total_bruto": len(ofertas),  
        "passaram": len(filtradas),  
        "descartes_historico": descartes_historico,  
        "descartes_preco": descartes_preco,  
        "descartes_loja": descartes_loja,  
        "descartes_vendas": descartes_vendas,
        "descartes_excluidos": descartes_excluidos
    }  
    return filtradas, stats  

# ============== FOCO E ÂNGULO POR TOM ==============
# Cada tom tem seu próprio foco — assim "Amiga / Achadinho" não fica
# contaminado com linguagem de urgência/promoção que pertence a outros tons.

TONS_CONFIG = {
    "Amiga / Achadinho (padrão, caloroso e natural)": {
        "foco": "carinho genuíno, proximidade e recomendação sincera — NADA de linguagem de propaganda, promoção ou urgência",
        "angulos": [
            "Tom de amiga próxima recomendando com carinho, sem pressa nenhuma",
            "Empolgação calorosa e genuína, como quem compartilha algo bom com uma amiga",
            "Recomendação natural, tranquila, como numa conversa de WhatsApp entre amigas",
            "Carinho e cuidado, tipo 'lembrei de você quando vi isso'",
        ],
    },
    "Conselho de Amiga (recomendação pessoal)": {
        "foco": "conselho sincero de quem já testou ou confia, tom de quem quer o bem da outra pessoa, sem parecer venda",
        "angulos": [
            "Conselho direto de amiga: 'olha, eu compraria isso sem pensar duas vezes'",
            "Recomendação de quem se preocupa e quer ajudar a economizar/acertar na escolha",
            "Tom de quem já passou pela mesma necessidade e quer indicar a solução",
        ],
    },
    "Urgência / Imediatismo (aja agora)": {
        "foco": "urgência real, poucas unidades, sensação de que precisa decidir AGORA",
        "angulos": [
            "Urgência e velocidade, achadinho que pode esgotar a qualquer momento",
            "Correria genuína, tipo 'corre que já era quando eu vi'",
            "Pressão de tempo real, sem soar artificial ou exagerada",
        ],
    },
    "Persuasiva / Gatilhos Mentais": {
        "foco": "persuasão com gatilhos mentais reais (escassez, prova social, curiosidade) — soar convincente e estratégico, não robótico",
        "angulos": [
            "Gatilho de prova social, tipo 'todo mundo tá comprando isso agora'",
            "Gatilho de curiosidade, que deixa a pessoa querendo saber mais antes de clicar",
            "Gatilho de escassez combinado com benefício claro e direto",
        ],
    },
    "Festa Infantil & Maternidade (dica de amiga)": {
        "foco": "praticidade pra quem organiza festa infantil ou é mãe, tom de dica útil entre amigas",
        "angulos": [
            "Dica prática de mãe pra mãe, sem pressa, focada em utilidade",
            "Empolgação com achado que facilita a vida de quem organiza festa",
        ],
    },
    "Oportunidade imperdível (foco em economia)": {
        "foco": "economia real, quanto vale a pena, sem apelar pra urgência artificial",
        "angulos": [
            "Recomendação direta focada em quanto compensa financeiramente",
            "Surpresa genuína com o quanto o preço vale a pena",
        ],
    },
    "Emocionada / Reação de surpresa com o preço": {
        "foco": "reação espontânea e emocionada com o preço, tipo 'não acreditei quando vi'",
        "angulos": [
            "Surpresa genuína e emocionada com o preço baixo",
            "Reação de choque bom, tipo 'juro que não acreditei'",
        ],
    },
    "Direta e objetiva (sem enrolação)": {
        "foco": "direto ao ponto, sem enrolação, sem apelo emocional forçado, frase quase informativa mas simpática",
        "angulos": [
            "Frase direta e curta, sem rodeios",
            "Informativa e prática, vai direto no benefício",
        ],
    },
}


def _config_do_tom(estilo_prompt: str) -> dict:
    return TONS_CONFIG.get(estilo_prompt, TONS_CONFIG["Amiga / Achadinho (padrão, caloroso e natural)"])


def _chamar_gemini_com_retry(gemini_client, mod: str, prompt: str, tentativas: int = 2, json_mode: bool = True):
    """Tenta chamar o mesmo modelo mais de uma vez antes de desistir —
    evita cair no fallback genérico só porque bateu um limite momentâneo
    de requisições (comum na cota gratuita do Gemini)."""
    ultimo_erro = None
    config = {"temperature": 1.25}
    if json_mode:
        config["response_mime_type"] = "application/json"
    for tentativa in range(tentativas):
        try:
            return gemini_client.models.generate_content(
                model=mod,
                contents=prompt,
                config=config,
            ), None
        except Exception as e:
            ultimo_erro = str(e)
            if "429" in ultimo_erro or "quota" in ultimo_erro.lower() or "rate" in ultimo_erro.lower():
                time.sleep(1.5 * (tentativa + 1))  # espera crescente antes de tentar de novo
                continue
            break  # erro que não é de limite de requisição, não adianta tentar de novo no mesmo modelo
    return None, ultimo_erro


def gerar_frases_lote_gemini(gemini_client, ofertas_lote: list, estilo_prompt: str, frases_recentes: list, campanha_texto: str, mencionar_cupom: bool) -> tuple:
    """Gera UMA frase pra cada oferta do lote, mas numa ÚNICA chamada ao Gemini
    (bem mais rápido e mais barato que uma chamada por oferta). Pede o
    resultado em JSON e valida antes de aceitar.

    Retorna (lista_de_frases, usou_fallback: bool) — o segundo valor serve
    pra você saber se a IA realmente gerou as frases ou se caiu no pool
    estático genérico (normalmente sinal de cota do Gemini estourada).

    campanha_texto: contexto de campanha específico (ex: "campanha do dia 9.9")
    — deixe vazio para mensagens genéricas, sem menção a data nenhuma.
    mencionar_cupom: se True, instrui a IA a mencionar cupom quando fizer sentido."""
    config_tom = _config_do_tom(estilo_prompt)
    angulo_escolhido = random.choice(config_tom["angulos"])

    # Agora passamos o NOME real do produto pro Gemini conseguir analisar o
    # contexto (pra quê serve, tipo de item) e escrever algo específico —
    # só que ele é proibido de escrever esse nome de volta na frase.
    itens_prompt = "\n".join(
        f"{i+1}. Produto (só pra você entender o contexto, NÃO repita esse nome): "
        f"\"{(o.get('productName') or 'item')[:100]}\" | Preço R$ {o.get('price') or o.get('priceMin') or '?'} | Desconto {o.get('priceDiscountRate', 0)}%"
        for i, o in enumerate(ofertas_lote)
    )

    bloco_recentes = ""
    if frases_recentes:
        ultimas = frases_recentes[-20:]
        bloco_recentes = "Frases já usadas em rodadas anteriores — NÃO repita nada parecido com estas:\n"
        bloco_recentes += "\n".join(f"- {f}" for f in ultimas)

    linha_contexto = f"Contexto da campanha: {campanha_texto}." if campanha_texto.strip() else "Sem campanha ou data específica — mensagem genérica, atemporal, sem mencionar nenhuma data."
    linha_cupom = "Pode mencionar cupom quando fizer sentido." if mencionar_cupom else "NÃO mencione cupom em nenhuma frase."

    prompt = f"""
    Você é a Carla Barce (influencer de festas, casa e achadinhos no WhatsApp),
    conhecida por escrever mensagens que parecem 100% humanas, específicas e
    nunca genéricas — cada seguidora sente que aquela mensagem foi pensada
    especialmente pra aquele produto.

    Preciso de {len(ofertas_lote)} frases DIFERENTES ENTRE SI, uma para cada
    item da lista abaixo (na mesma ordem). ANALISE o que cada produto é/serve
    pra escrever algo ESPECÍFICO sobre a utilidade, ocasião de uso ou benefício
    dele — sem nunca escrever o nome do produto.

    {linha_contexto}
    {linha_cupom}

    Itens:
    {itens_prompt}

    {bloco_recentes}

    REGRAS ESTRITAS E OBRIGATÓRIAS:
    1. JAMAIS escreva o nome literal do produto — mas USE o que ele é pra tornar a frase específica (ex: se for algo de cozinha, fale de praticidade na cozinha; se for de festa, fale do momento da festa; etc.), sem citar o item por nome.
    2. As {len(ofertas_lote)} frases desta lista devem ser TODAS diferentes entre si — em estrutura, abertura e vocabulário. Proibido repetir a mesma frase ou frases quase idênticas dentro do lote.
    3. Nenhuma frase pode soar genérica ou "copiada e colada" — cada uma tem que parecer escrita pensando naquele produto específico.
    4. Tom obrigatório: {config_tom['foco']}. Ângulo de inspiração: {angulo_escolhido}.
    5. 1 a 2 emojis por frase, coerentes com o tom pedido.
    6. No máximo 10 a 16 palavras por frase.
    7. Responda APENAS com um JSON no formato: {{"frases": ["frase 1", "frase 2", ...]}}
       Sem markdown, sem explicação, sem texto fora do JSON.
    """

    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    for mod in modelos:
        response, erro = _chamar_gemini_com_retry(gemini_client, mod, prompt)
        if response is None or not response.text:
            continue
        try:
            texto = response.text.strip()
            texto = re.sub(r"^```json|```$", "", texto).strip()
            dados = json.loads(texto)
            frases = dados.get("frases", [])
            if len(frases) >= len(ofertas_lote):
                return [f.strip() for f in frases[:len(ofertas_lote)]], False
        except Exception:
            continue

    # Se o lote falhar (JSON quebrado, todos os modelos indisponíveis etc.),
    # cai pro método individual item a item, que é mais lento mas mais robusto.
    resultado = []
    for oferta in ofertas_lote:
        frase = gerar_frase_gemini(gemini_client, oferta, estilo_prompt, frases_recentes + resultado, campanha_texto, mencionar_cupom)
        resultado.append(frase)
    return resultado, True


def gerar_frase_gemini(gemini_client, oferta, estilo_prompt: str, frases_recentes: list, campanha_texto: str = "", mencionar_cupom: bool = False) -> str:  
    preco = oferta.get("price") or oferta.get("priceMin") or ""  
    desconto = oferta.get("priceDiscountRate", "")  

    config_tom = _config_do_tom(estilo_prompt)
    angulo_escolhido = random.choice(config_tom["angulos"])

    # Mostra pro Gemini as últimas frases geradas nesta mesma rodada, pra ele
    # ativamente evitar repetir a mesma estrutura/abertura.
    bloco_recentes = ""  
    if frases_recentes:  
        ultimas = frases_recentes[-8:]  
        bloco_recentes = "NÃO repita a estrutura, abertura ou ideia destas frases já usadas agora:\n"  
        bloco_recentes += "\n".join(f"- {f}" for f in ultimas)  

    linha_contexto = f"Contexto da campanha: {campanha_texto}." if campanha_texto.strip() else "Sem campanha ou data específica — mensagem genérica, atemporal, sem mencionar nenhuma data."
    linha_cupom = "Pode mencionar cupom quando fizer sentido." if mencionar_cupom else "NÃO mencione cupom."

    nome_produto = (oferta.get("productName") or "item")[:100]

    prompt = f"""  
    Você é a Carla Barce (influencer de festas, casa e achadinhos de ofertas no WhatsApp),
    conhecida por escrever mensagens específicas, nunca genéricas.

    Produto (só pra você entender o contexto — NÃO repita esse nome na frase): "{nome_produto}"
    - Preço: R$ {preco}  
    - Desconto: {desconto}%  
    - Tom obrigatório: {config_tom['foco']}. Ângulo de inspiração: {angulo_escolhido}.
    - {linha_contexto}
    - {linha_cupom}

    {bloco_recentes}  

    Crie UMA ÚNICA FRASE CURTA, IMPERDÍVEL E ESPECÍFICA (use o que o produto É/serve pra deixar a frase específica, sem citar o nome dele).

    REGRAS ESTRITAS E OBRIGATÓRIAS:  
    1. JAMAIS mencione o nome do produto. NUNCA coloque o nome do item no texto.  
    2. JAMAIS comece com "Gente, olha essa oferta" ou "Gente, olha só". Alterne completamente o início da frase.  
    3. Respeite rigorosamente o tom obrigatório acima — nada de linguagem de outro tom.
    4. Não pode soar genérica — precisa parecer escrita pensando neste produto específico.
    5. Use de 1 a 2 emojis alegres e coerentes com o tom pedido.  
    6. Mantenha o texto CURTO (no máximo 10 a 16 palavras) para leitura instantânea.  
    7. Responda APENAS com a frase final, sem aspas, sem explicações e sem introduções.  
    """  

    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]  
    
    for mod in modelos:  
        response, erro = _chamar_gemini_com_retry(gemini_client, mod, prompt, json_mode=False)
        if response is None or not response.text:
            continue
        res = response.text.strip().replace("\n", " ").replace('"', '')  
        if len(res) > 5 and not res.lower().startswith("gente, olha") and res not in frases_recentes:  
            return res  

    # Fallback: garante que não repete nem no pool estático, e evita
    # linguagem de correria/urgência se o tom escolhido não pedir isso
    tom_calmo = "amiga" in estilo_prompt.lower() or "maternidade" in estilo_prompt.lower() or "economia" in estilo_prompt.lower()
    palavras_urgencia = ("corre", "voando", "esgot", "última", "acabando")
    pool_filtrado = POOL_FALLBACK_FRASES
    if tom_calmo:
        pool_filtrado = [f for f in POOL_FALLBACK_FRASES if not any(p in f.lower() for p in palavras_urgencia)]
    opcoes_livres = [f for f in (pool_filtrado or POOL_FALLBACK_FRASES) if f not in frases_recentes]  
    return random.choice(opcoes_livres or pool_filtrado or POOL_FALLBACK_FRASES)  

# ============== INTERFACE STREAMLIT ==============  

st.title("🛍️ Painel de Ofertas Shopee + Gemini AI")  
st.caption("Pesquise por categoria, palavras-chave ou busca livre para o WhatsApp")  

# Sidebar - Configurações
# IMPORTANTE (segurança): as chaves NÃO ficam mais escritas no código.
# Elas vêm de variáveis de ambiente ou do arquivo .streamlit/secrets.toml
# (que você cria localmente e NUNCA sobe pro GitHub / Streamlit Cloud).
# Veja as instruções no final do arquivo sobre como criar esse secrets.toml.
st.sidebar.header("🔑 Autenticação e APIs")

def _valor_padrao(nome_secret: str) -> str:
    """Busca a chave em st.secrets (se configurado) ou variável de ambiente.
    Se não achar em lugar nenhum, deixa em branco pro usuário preencher na hora."""
    try:
        if nome_secret in st.secrets:
            return st.secrets[nome_secret]
    except Exception:
        pass
    return os.environ.get(nome_secret, "")

app_id = st.sidebar.text_input("Shopee APP_ID", value=_valor_padrao("SHOPEE_APP_ID"))
app_secret = st.sidebar.text_input("Shopee APP_SECRET", value=_valor_padrao("SHOPEE_APP_SECRET"), type="password")
gemini_key = st.sidebar.text_input("Gemini API Key", value=_valor_padrao("GEMINI_API_KEY"), type="password")

st.sidebar.markdown("---")  
st.sidebar.header("⚙️ Modo de Pesquisa e Categorias")  

modo_busca = st.sidebar.radio(  
    "Escolha como deseja pesquisar:",  
    [  
        "🏷️ Usar Categorias da Shopee",  
        "✍️ Digitar Palavras-Chave Específicas",  
        "🔀 Combinar Categorias + Palavras-Chave",  
        "🌐 Busca Livre Geral (Sem restrição)"  
    ],
    key="k_modo_busca"
)  

categorias_selecionadas = []  
keywords_digitadas = ""  

if modo_busca in ["🏷️ Usar Categorias da Shopee", "🔀 Combinar Categorias + Palavras-Chave"]:  
    categorias_selecionadas = st.sidebar.multiselect(  
        "Selecione as Categorias da Shopee:",  
        list(CATEGORIAS_MAP.keys()),  
        key="k_categorias"
    )  

if modo_busca in ["✍️ Digitar Palavras-Chave Específicas", "🔀 Combinar Categorias + Palavras-Chave"]:  
    keywords_digitadas = st.sidebar.text_input(  
        "Digite as Palavras-chave (separadas por vírgula):",  
        help="Digite exatamente como você costuma pesquisar no aplicativo da Shopee.",
        key="k_keywords"
    )  

excluir_palavras_texto = st.sidebar.text_input(
    "🚫 Excluir produtos que contenham (separadas por vírgula):",
    help="Ex: digitar 'sacola' remove qualquer produto cujo nome contenha essa palavra, mesmo que o termo buscado seja diferente.",
    key="k_excluir_palavras"
)
palavras_excluidas = [p.strip().lower() for p in excluir_palavras_texto.split(",") if p.strip()]

st.sidebar.markdown("---")  
st.sidebar.header("🔍 Ordenação da Busca na Shopee")  

opcao_ordem = st.sidebar.selectbox(  
    "Ordenar Busca Por:",  
    [  
        "Relevância (Igual à pesquisa do site da Shopee)",  
        "Mais Vendidos / Populares",  
        "Maior Taxa de Comissão"  
    ],
    key="k_ordem"
)  

sort_type_map = {  
    "Relevância (Igual à pesquisa do site da Shopee)": 1,  
    "Mais Vendidos / Populares": 3,  
    "Maior Taxa de Comissão": 2  
}  
sort_type_escolhido = sort_type_map[opcao_ordem]  

qtd_por_keyword = st.sidebar.number_input(  
    "Quantidade de Ofertas por Termo:",  
    min_value=5,  
    max_value=200,  
    step=5,
    key="k_qtd_termo"
)  

st.sidebar.markdown("---")  
st.sidebar.header("🏬 Filtros de Loja e Vendas")  

tipos_loja = st.sidebar.multiselect(  
    "Tipos de Loja na Shopee:",  
    [  
        "Todas as Lojas (Recomendado - Maior volume)",  
        "Lojas Oficiais (Shopee Oficial)",  
        "Lojas Indicadas (Shopee Indicado)"  
    ],  
    key="k_tipos_loja"
)  

min_vendas = st.sidebar.number_input("Vendas Mínimas do Produto", step=5, key="k_min_vendas")  

col_p1, col_p2 = st.sidebar.columns(2)  
with col_p1:  
    min_price = st.number_input("Preço Mínimo (R$)", step=5.0, key="k_min_price")  
with col_p2:  
    max_price = st.number_input("Preço Máximo (R$ 0 = sem limite)", step=10.0, key="k_max_price")  

st.sidebar.markdown("---")  
st.sidebar.header("🎯 Histórico e Filtros")  

usar_historico = st.sidebar.checkbox("Ignorar Ofertas Já Buscadas Antes (Histórico)", key="k_usar_historico")  

if st.sidebar.button("🧹 Limpar Histórico do Servidor"):  
    limpar_historico_arquivo()  
    st.sidebar.success("Histórico zerado com sucesso!")  

filtrar_desconto = st.sidebar.checkbox("Filtrar por Desconto Mínimo", key="k_filtrar_desconto")  
min_desconto = st.sidebar.slider("Desconto Mínimo (%)", 5, 90, key="k_min_desconto") if filtrar_desconto else 0  

filtrar_comissao = st.sidebar.checkbox("Filtrar por Comissão Mínima", key="k_filtrar_comissao")  
min_comissao = st.sidebar.slider("Comissão Mínima (%)", 1.0, 30.0, key="k_min_comissao") if filtrar_comissao else 0  

st.sidebar.markdown("---")  
st.sidebar.header("✍️ Tom e Estilo da Mensagem")  
estilo_prompt = st.sidebar.selectbox(  
    "Escolha o tom da mensagem:",  
    [  
        "Amiga / Achadinho (padrão, caloroso e natural)",  
        "Urgência / Poucas unidades restantes",  
        "Festa Infantil & Maternidade (dica de amiga)",  
        "Oportunidade imperdível (foco em economia)",  
        "Emocionada / Reação de surpresa com o preço",  
        "Direta e objetiva (sem enrolação)",  
    ],
    key="k_estilo_prompt"
)  

st.sidebar.markdown("---")
st.sidebar.header("🗓️ Campanha específica (opcional)")
campanha_ativa = st.sidebar.checkbox("Mencionar uma data/campanha específica nas frases?", key="k_campanha_ativa")
campanha_texto = ""
if campanha_ativa:
    dia_duplo = st.sidebar.text_input(
        "Qual data/campanha? (ex: 9.9, 10.10, 11.11, Black Friday)",
        placeholder="ex: 9.9",
        key="k_dia_duplo"
    )
    if dia_duplo.strip():
        campanha_texto = f"campanha do dia {dia_duplo.strip()}"

mencionar_cupom = st.sidebar.checkbox("Mencionar cupom nas frases?", key="k_mencionar_cupom")

tamanho_lote_gemini = st.sidebar.slider(
    "Ofertas por chamada ao Gemini (lote)",
    min_value=5, max_value=25,
    help="Números maiores = menos chamadas à API = mais rápido e mais barato. Se notar frases de baixa qualidade, diminua.",
    key="k_tamanho_lote"
)

# Conteúdo Principal  

if st.button("🚀 Buscar Novas Ofertas", type="primary", use_container_width=True):  
    if not app_id or not app_secret or not gemini_key:  
        st.error("Preencha todas as chaves de API na barra lateral antes de continuar.")  
    else:  
        gemini_client = genai.Client(api_key=gemini_key)  
        historico = carregar_historico()  
        
        buscas = []  
        
        if modo_busca in ["🏷️ Usar Categorias da Shopee", "🔀 Combinar Categorias + Palavras-Chave"]:  
            for cat in categorias_selecionadas:  
                buscas.extend(CATEGORIAS_MAP.get(cat, []))  
                
        if modo_busca in ["✍️ Digitar Palavras-Chave Específicas", "🔀 Combinar Categorias + Palavras-Chave"]:  
            if keywords_digitadas.strip():  
                kw_lista = [k.strip() for k in re.split(r"[,\n]", keywords_digitadas) if k.strip()]  
                buscas.extend(kw_lista)  
                
        if modo_busca == "🌐 Busca Livre Geral (Sem restrição)" or not buscas:  
            buscas = ["promoção", "desconto", "oferta", "achadinhos", "utilidades", "presente"]  
            
        buscas = list(dict.fromkeys(buscas))  
        
        progresso = st.progress(0)  
        status_text = st.empty()  
        
        todas_ofertas_filtradas = []  
        total_buscas = len(buscas)  
        total_bruto_acumulado = 0  
        total_descarte_hist = 0  
        total_descarte_loja = 0  
        diagnostico_por_termo = []
        
        for index, kw in enumerate(buscas):  
            status_text.text(f"Buscando {qtd_por_keyword} ofertas para termo: '{kw}' (Modo: {opcao_ordem})...")  
            
            ofertas, erro_busca = buscar_todas_ofertas(app_id, app_secret, kw, qtd_por_keyword, sort_type=sort_type_escolhido)  
            if erro_busca:  
                st.warning(f"⚠️ Erro ao buscar '{kw}': {erro_busca}")  
            boas, stats = filtrar_ofertas(  
                ofertas, historico, usar_historico,  
                tipos_loja, min_vendas,  
                filtrar_comissao, min_comissao,  
                filtrar_desconto, min_desconto,  
                min_price, max_price,
                palavras_excluidas
            )  
            todas_ofertas_filtradas.extend(boas)  
            total_bruto_acumulado += stats["total_bruto"]  
            total_descarte_hist += stats["descartes_historico"]  
            total_descarte_loja += stats["descartes_loja"]  
            diagnostico_por_termo.append({
                "Termo buscado": kw,
                "Encontradas na Shopee": stats["total_bruto"],
                "Passaram nos filtros": stats["passaram"],
                "Descartadas (já usadas antes)": stats["descartes_historico"],
                "Descartadas (loja)": stats["descartes_loja"],
                "Descartadas (preço)": stats["descartes_preco"],
                "Descartadas (vendas)": stats["descartes_vendas"],
                "Descartadas (palavra excluída)": stats["descartes_excluidos"],
                "Erro": erro_busca or "",
            })
            progresso.progress((index + 1) / total_buscas)  
        
        status_text.text("Gerando frases personalizadas com o Gemini AI...")  
        
        resultados_gerados = []  
        novos_links = []  
        novos_produtos = []  
        novas_frases = []  
        
        progresso_gemini = st.progress(0)  
        total_boas = len(todas_ofertas_filtradas)  
        
        idx_global = 0
        lotes_com_fallback = 0
        total_lotes = 0
        for inicio in range(0, total_boas, tamanho_lote_gemini):
            lote = todas_ofertas_filtradas[inicio:inicio + tamanho_lote_gemini]
            frases_do_lote, usou_fallback = gerar_frases_lote_gemini(gemini_client, lote, estilo_prompt, novas_frases, campanha_texto, mencionar_cupom)
            total_lotes += 1
            if usou_fallback:
                lotes_com_fallback += 1

            for oferta, frase in zip(lote, frases_do_lote):
                link = oferta.get("offerLink", "")
                texto_final = f"cta[{frase.upper()}]\n\n{link}"

                texto_encoded = urllib.parse.quote(texto_final)
                whatsapp_url = f"https://api.whatsapp.com/send?text={texto_encoded}"

                resultados_gerados.append({
                    "id": idx_global,
                    "oferta": oferta,
                    "frase": frase,
                    "texto_final": texto_final,
                    "whatsapp_url": whatsapp_url,
                    "link": link,
                    "selecionado": True,
                    "enviada": False
                })

                novos_links.append(link)
                p_key = normalizar_produto(oferta.get("productName", ""))
                if p_key:
                    novos_produtos.append(p_key)
                novas_frases.append(frase)
                idx_global += 1

            if total_boas > 0:
                progresso_gemini.progress(min(idx_global / total_boas, 1.0))  
        
        if usar_historico and resultados_gerados:  
            historico["links"] = list(set(historico["links"]) | set(novos_links))  
            # produtos agora são frozensets (conjuntos de palavras) — convertemos
            # pra listas de listas, que é o que o JSON consegue guardar.
            produtos_existentes = []
            for p in historico["produtos"]:
                if isinstance(p, str):
                    produtos_existentes.append(frozenset(p.split()))
                else:
                    produtos_existentes.append(frozenset(p))
            produtos_combinados = produtos_existentes + [p for p in novos_produtos if p]
            # remove duplicatas exatas (mesma frozenset) mantendo a ordem
            vistos_exatos = set()
            produtos_unicos = []
            for p in produtos_combinados:
                if p not in vistos_exatos:
                    vistos_exatos.add(p)
                    produtos_unicos.append(list(p))
            historico["produtos"] = produtos_unicos
            historico["frases"] = list(set(historico["frases"]) | set(novas_frases))  
            salvar_historico(historico)  
        
        st.session_state.resultados = resultados_gerados  
        st.session_state.diagnostico = diagnostico_por_termo
        status_text.success(f"Concluído! {len(resultados_gerados)} ofertas geradas de um total de {total_bruto_acumulado} produtos analisados na Shopee.")  
        if total_lotes > 0 and lotes_com_fallback > 0:
            st.warning(
                f"⚠️ {lotes_com_fallback} de {total_lotes} lotes de frases usaram o texto de reserva (fallback) "
                f"em vez do Gemini — isso normalmente acontece quando a cota gratuita da API do Gemini é excedida. "
                f"Se as frases vierem repetitivas, essa é a causa mais provável: espere um pouco e tente de novo, "
                f"ou reduza a quantidade de ofertas por busca."
            )

if st.session_state.get("diagnostico"):
    with st.expander("🔍 Ver detalhamento por termo de busca (diagnóstico)"):
        st.caption("Use isso pra ver exatamente o que cada termo/categoria retornou e por que algo pode ter sido descartado.")
        st.dataframe(st.session_state.diagnostico, use_container_width=True)  

# Exibição dos Resultados  

if st.session_state.resultados:  
    st.subheader(f"📋 Ofertas Encontradas ({len(st.session_state.resultados)})")  
    
    selecionados = [item for item in st.session_state.resultados if item["selecionado"]]  
    
    if selecionados:  
        texto_bloco_total = "\n\n---\n\n".join([r["texto_final"] for r in selecionados])  
        texto_bloco_encoded = urllib.parse.quote(texto_bloco_total)  
        whatsapp_lote_url = f"https://api.whatsapp.com/send?text={texto_bloco_encoded}"  
        
        st.markdown("### 📲 Opção 1: Enviar TODAS as Selecionadas em Bloco (Mensagem Única)")  
        st.link_button(  
            f"🚀 Encaminhar {len(selecionados)} Ofertas Selecionadas no WhatsApp em Mensagem Única",  
            whatsapp_lote_url,  
            use_container_width=True,  
            type="primary"  
        )  
        st.markdown("---")  
    
    tab_cards, tab_fila, tab_exportar = st.tabs([  
        "🖼️ Pesquisar & Selecionar Ofertas",  
        "📲 Fila de Envio Individual",  
        "📥 Exportar Selecionadas (.txt)"  
    ])  
    
    with tab_cards:  
        st.write("Marque as caixas das ofertas que você mais gostou:")  
        
        col_m1, col_m2 = st.columns(2)  
        with col_m1:  
            if st.button("Marcar Todas"):  
                for r in st.session_state.resultados:  
                    r["selecionado"] = True  
                st.rerun()  
        with col_m2:  
            if st.button("Desmarcar Todas"):  
                for r in st.session_state.resultados:  
                    r["selecionado"] = False  
                st.rerun()  
                
        st.markdown("---")  
        
        for idx, item in enumerate(st.session_state.resultados):  
            oferta = item["oferta"]  
            nome = oferta.get("productName", "Produto Shopee")  
            preco = oferta.get("price") or oferta.get("priceMin") or "0.00"  
            desconto = oferta.get("priceDiscountRate", 0)  
            vendas = oferta.get("sales", 0)  
            imagem = oferta.get("imageUrl", "")  
            
            with st.container():  
                c_sel, c_img, c_info, c_action = st.columns([0.5, 1, 2.5, 1.5])  
                
                with c_sel:  
                    item["selecionado"] = st.checkbox(  
                        "", value=item["selecionado"], key=f"cb_{idx}"  
                    )  
                
                with c_img:  
                    if imagem:  
                        st.image(imagem, width=110)  
                    else:  
                        st.write("📷 Sem imagem")  
                
                with c_info:  
                    st.markdown(f"**{idx + 1}. {nome}**")  
                    st.markdown(f"💰 **Preço:** R$ {preco} | 🔥 **Desconto:** {desconto}% | 🛒 **Vendas:** {vendas}")  
                    st.code(item["texto_final"], language=None)  
                
                with c_action:  
                    st.write("")  
                    st.write("")  
                    st.link_button("📲 Enviar Esta Oferta", item["whatsapp_url"], use_container_width=True)  
                    
            st.markdown("---")  

    with tab_fila:  
        st.info("💡 Envie uma oferta por vez, na ordem — depois de mandar no WhatsApp, marque como enviada pra ir pra próxima automaticamente. Isso fica salvo mesmo se você sair do app e voltar.")

        if not selecionados:  
            st.warning("Nenhuma oferta selecionada.")  
        else:  
            # Garante que cada item tenha o campo "enviada" (compatibilidade com resultados antigos)
            for item in selecionados:
                item.setdefault("enviada", False)

            enviadas = [item for item in selecionados if item["enviada"]]
            pendentes = [item for item in selecionados if not item["enviada"]]

            st.progress(len(enviadas) / len(selecionados) if selecionados else 0)
            st.markdown(f"**{len(enviadas)} de {len(selecionados)} enviadas**")

            if pendentes:
                atual = pendentes[0]
                nome = atual["oferta"].get("productName", "Produto")
                st.markdown("### 📲 Próxima da fila:")
                st.write(f"**{nome[:80]}**")
                st.code(atual["texto_final"], language=None)

                col_env1, col_env2 = st.columns(2)
                with col_env1:
                    st.link_button("🚀 Abrir no WhatsApp", atual["whatsapp_url"], use_container_width=True, type="primary")
                with col_env2:
                    if st.button("✅ Marcar como enviada e ir pra próxima", use_container_width=True):
                        atual["enviada"] = True
                        salvar_sessao_disco()
                        st.rerun()
            else:
                st.success("🎉 Todas as ofertas selecionadas já foram marcadas como enviadas!")

            with st.expander("Ver fila completa"):
                for s_idx, item in enumerate(selecionados):
                    nome = item["oferta"].get("productName", "Produto")
                    status = "✅" if item["enviada"] else "⏳"
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"{status} **#{s_idx + 1}:** {nome[:60]}...")
                    with col2:
                        st.link_button("Disparar", item["whatsapp_url"], use_container_width=True, key=f"disparo_{item['id']}")
                    st.divider()

            if st.button("🔄 Reiniciar fila (desmarcar todas como enviadas)"):
                for item in selecionados:
                    item["enviada"] = False
                salvar_sessao_disco()
                st.rerun()

    with tab_exportar:  
        if selecionados:  
            texto_bloco_total = "\n\n---\n\n".join([r["texto_final"] for r in selecionados])  
            st.download_button(  
                label="📥 Baixar Ofertas Selecionadas (.txt)",  
                data=texto_bloco_total,  
                file_name=f"ofertas_shopee_selecionadas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",  
                mime="text/plain",  
                use_container_width=True  
            )  
        else:  
            st.warning("Nenhuma oferta selecionada para exportar.")  

else:  
    st.info("Ajuste os filtros na barra lateral e clique no botão '🚀 Buscar Novas Ofertas' para iniciar.")  

# Salva a sessão inteira em disco toda vez que o script roda — é isso que
# garante que, mesmo se a aba recarregar (ex: trocar de app no celular),
# ao voltar tudo reaparece do jeito que você deixou.
salvar_sessao_disco()

