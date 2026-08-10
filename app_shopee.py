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

# ============== DICIONÁRIO DE CATEGORIAS DA SHOPEE ==============  

CATEGORIAS_MAP = {  
    "🎈 Festas, Lembrancinhas & Personalizados": [  
        "lembrancinha", "festa infantil", "kit personalizado", "qualquer tema",   
        "sacolinhas pvc", "pegue monte", "caixas personalizadas", "lembrancinha premium", "15 anos"  
    ],  
    "🏠 Casa, Cozinha & Utensílios": [  
        "cozinha", "casa", "utilidades", "organizador", "eletrodomesticos", "decoração"  
    ],  
    "👗 Moda Feminina & Acessórios": [  
        "moda feminina", "bolsas", "acessórios", "vestido", "bijuterias"  
    ],  
    "💄 Beleza & Cuidados": [  
        "maquiagem", "skincare", "cabelos", "perfume", "unhas"  
    ],  
    "🧸 Brinquedos & Infantil": [  
        "brinquedos", "jogos educativos", "maternidade", "infantil"  
    ],  
    "🌐 Busca Livre Geral (Todas as Categorias da Shopee)": [  
        "promoção", "desconto", "oferta", "achadinhos", "utilidades"  
    ]  
}  

# ============== POOL DIVERSICADO DE SEGURANÇA (SEM NOME DE PRODUTO) ==============  

POOL_FALLBACK_FRASES = [  
    "Amiga, corre que o cupom do 8.8 tá voando da tela! 🏃‍♀️💨",  
    "Gente, socorro, achei um achadinho bom demais pra deixar passar! 😱",  
    "Óoo lindeza, e olha o valor disso com desconto! 😍",  
    "Para tudo, essa promoção relâmpago vai esgotar rápido! ⚡",  
    "Amiga, isso tá quase de graça hoje, olha só! 🤑",  
    "Separei isso especialmente pra você aproveitar o cupom! 💛",  
    "Corre, corre, que isso não vai durar nem 5 minutos! 🏃‍♀️💨",  
    "Achei e já vim correndo te contar antes que subam o preço! 😍",  
    "Amiga, larga tudo e aproveita esse achadinho de hoje! 👀",  
    "Gente, preço bom desse jeito no 8.8 não dura nada! ⏳",  
    "Amiga, essa dica é de ouro pra quem ama economizar! ✨",  
    "Aqui é chance rara, pega seu cupom e garante já! 🍀",  
    "Amiga, você não tem noção do tanto que vale a pena! 🎁",  
    "Gente, esse preço com cupom ficou um absurdo de barato! 💣",  
    "Amiga, essa dica vale cada segundo, aproveita antes que esgoste! 💕",  
    "Isso aqui tá voando da prateleira, pega o seu rápido! 🛒",  
    "Amiga, hoje é dia de sorte com esse descontaço! 🌟",  
    "Gente, eu juro que fiquei de boca aberta com esse valor! 😮",  
    "Amiga, pega o cupom que fica ainda mais barato, corre! 🎟️",  
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

def normalizar_produto(nome: str) -> str:  
    if not nome:  
        return ""  
    texto = nome.lower()  
    texto = re.sub(r"\d+[/\d]*", " ", texto)  # remove qualquer número/sequência (05/25/50, 100, etc.)
    texto = re.sub(r"[^\w\sáàâãéêíóôõúüç]", " ", texto)  
    palavras = [p for p in texto.split() if p not in PALAVRAS_IGNORAR and len(p) > 2]  
    return " ".join(sorted(set(palavras[:8])))  

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
                    min_preco: float, max_preco: float):  
    links_usados = set(historico["links"]) if usar_historico else set()  
    produtos_usados = set(historico["produtos"]) if usar_historico else set()  
    produtos_nesta_rodada = set()  
    
    filtradas = []  
    descartes_historico = 0  
    descartes_preco = 0  
    descartes_loja = 0  
    descartes_vendas = 0  
    
    for oferta in ofertas:  
        comissao = float(oferta.get("commissionRate") or 0) * 100  
        desconto = float(oferta.get("priceDiscountRate") or 0)  
        link = oferta.get("offerLink", "")  
        produto_key = normalizar_produto(oferta.get("productName", ""))  
        preco = float(oferta.get("price") or oferta.get("priceMin") or 0)  
        vendas = int(oferta.get("sales") or 0)  
        loja_tipos = obter_tipos_loja(oferta)  
        
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
            if link in links_usados or (produto_key and (produto_key in produtos_usados or produto_key in produtos_nesta_rodada)):  
                descartes_historico += 1  
                continue  
        
        produtos_nesta_rodada.add(produto_key)  
        filtradas.append(oferta)  
        
    filtradas.sort(key=lambda o: float(o.get("priceDiscountRate") or 0), reverse=True)  
    stats = {  
        "total_bruto": len(ofertas),  
        "passaram": len(filtradas),  
        "descartes_historico": descartes_historico,  
        "descartes_preco": descartes_preco,  
        "descartes_loja": descartes_loja,  
        "descartes_vendas": descartes_vendas  
    }  
    return filtradas, stats  

def gerar_frases_lote_gemini(gemini_client, ofertas_lote: list, estilo_prompt: str, frases_recentes: list) -> list:
    """Gera UMA frase pra cada oferta do lote, mas numa ÚNICA chamada ao Gemini
    (bem mais rápido e mais barato que uma chamada por oferta). Pede o
    resultado em JSON e valida antes de aceitar."""
    itens_prompt = "\n".join(
        f"{i+1}. Preço R$ {o.get('price') or o.get('priceMin') or '?'}, desconto {o.get('priceDiscountRate', 0)}%"
        for i, o in enumerate(ofertas_lote)
    )

    bloco_recentes = ""
    if frases_recentes:
        ultimas = frases_recentes[-15:]
        bloco_recentes = "Frases já usadas — NÃO repita nenhuma estrutura parecida com estas:\n"
        bloco_recentes += "\n".join(f"- {f}" for f in ultimas)

    prompt = f"""
    Você é a Carla Barce (influencer de festas, casa e achadinhos no WhatsApp).
    Preciso de {len(ofertas_lote)} frases CURTAS e IMPERDÍVEIS, uma para cada
    item da lista abaixo (na mesma ordem), pra campanha de cupons 8.8 da Shopee.

    Itens:
    {itens_prompt}

    {bloco_recentes}

    REGRAS ESTRITAS E OBRIGATÓRIAS:
    1. JAMAIS mencione nome de produto.
    2. Cada frase começa de um jeito DIFERENTE das outras — sem repetir "Gente, olha" em mais de uma.
    3. Tom: {estilo_prompt}. Foque em urgência, cupom 8.8, achadinho que vale a pena, economia real.
    4. 1 a 2 emojis por frase.
    5. No máximo 10 a 14 palavras por frase.
    6. Responda APENAS com um JSON no formato: {{"frases": ["frase 1", "frase 2", ...]}}
       Sem markdown, sem explicação, sem texto fora do JSON.
    """

    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    for mod in modelos:
        try:
            response = gemini_client.models.generate_content(
                model=mod,
                contents=prompt,
                config={"temperature": 1.15, "response_mime_type": "application/json"},
            )
            if not response or not response.text:
                continue
            texto = response.text.strip()
            texto = re.sub(r"^```json|```$", "", texto).strip()
            dados = json.loads(texto)
            frases = dados.get("frases", [])
            if len(frases) >= len(ofertas_lote):
                return [f.strip() for f in frases[:len(ofertas_lote)]]
        except Exception:
            continue

    # Se o lote falhar (JSON quebrado, todos os modelos indisponíveis etc.),
    # cai pro método individual item a item, que é mais lento mas mais robusto.
    resultado = []
    for oferta in ofertas_lote:
        resultado.append(gerar_frase_gemini(gemini_client, oferta, estilo_prompt, frases_recentes + resultado))
    return resultado


def gerar_frase_gemini(gemini_client, oferta, estilo_prompt: str, frases_recentes: list) -> str:  
    preco = oferta.get("price") or oferta.get("priceMin") or ""  
    desconto = oferta.get("priceDiscountRate", "")  

    angulos = [  
        "Tom de amiga íntima compartilhando um achadinho no evento 8.8",  
        "Urgência e velocidade com cupons relâmpago esgotando",  
        "Empolgação com utilidade prática para lembrancinha/festa ou casa",  
        "Surpresa com o preço extremamente baixo e oportunidade única",  
        "Recomendação direta e carinhosa de quem ama economizar"  
    ]  
    angulo_escolhido = random.choice(angulos)  

    # Mostra pro Gemini as últimas frases geradas nesta mesma rodada, pra ele
    # ativamente evitar repetir a mesma estrutura/abertura.
    bloco_recentes = ""  
    if frases_recentes:  
        ultimas = frases_recentes[-8:]  
        bloco_recentes = "NÃO repita a estrutura, abertura ou ideia destas frases já usadas agora:\n"  
        bloco_recentes += "\n".join(f"- {f}" for f in ultimas)  

    prompt = f"""  
    Você é a Carla Barce (influencer de festas, casa e achadinhos de ofertas no WhatsApp).  
    Crie UMA ÚNICA FRASE CURTA, IMPERDÍVEL E MUITO NATURAL para mandar no seu grupo durante a campanha de cupons 8.8 da Shopee.  

    Dados da promoção:  
    - Preço: R$ {preco}  
    - Desconto: {desconto}%  
    - Tom principal: {estilo_prompt} ({angulo_escolhido})  

    {bloco_recentes}  

    REGRAS ESTRITAS E OBRIGATÓRIAS:  
    1. JAMAIS mencione o nome do produto. NUNCA coloque o nome do item no texto.  
    2. JAMAIS comece com "Gente, olha essa oferta" ou "Gente, olha só". Alterne completamente o início da frase.  
    3. Foque em: urgência, cupons 8.8, achadinho que vale a pena, economia real ou carinho com as seguidoras.  
    4. Use de 1 a 2 emojis alegres e adequados.  
    5. Mantenha o texto CURTO (no máximo 10 a 14 palavras) para leitura instantânea.  
    6. Responda APENAS com a frase final, sem aspas, sem explicações e sem introduções.  
    """  

    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]  
    
    for mod in modelos:  
        try:  
            response = gemini_client.models.generate_content(  
                model=mod,  
                contents=prompt,  
                config={"temperature": 1.15},  # eleva a variação das respostas  
            )  
            if response and response.text:  
                res = response.text.strip().replace("\n", " ").replace('"', '')  
                if len(res) > 5 and not res.lower().startswith("gente, olha") and res not in frases_recentes:  
                    return res  
        except Exception:  
            continue  

    # Fallback: garante que não repete nem no pool estático  
    opcoes_livres = [f for f in POOL_FALLBACK_FRASES if f not in frases_recentes]  
    return random.choice(opcoes_livres or POOL_FALLBACK_FRASES)  

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
    ]  
)  

categorias_selecionadas = []  
keywords_digitadas = ""  

if modo_busca in ["🏷️ Usar Categorias da Shopee", "🔀 Combinar Categorias + Palavras-Chave"]:  
    categorias_selecionadas = st.sidebar.multiselect(  
        "Selecione as Categorias da Shopee:",  
        list(CATEGORIAS_MAP.keys()),  
        default=["🎈 Festas, Lembrancinhas & Personalizados", "🏠 Casa, Cozinha & Utensílios"]  
    )  

if modo_busca in ["✍️ Digitar Palavras-Chave Específicas", "🔀 Combinar Categorias + Palavras-Chave"]:  
    keywords_digitadas = st.sidebar.text_input(  
        "Digite as Palavras-chave (separadas por vírgula):",  
        value="qualquer tema, sacolinhas pvc, pegue monte, lembrancinha",  
        help="Digite exatamente como você costuma pesquisar no aplicativo da Shopee."  
    )  

st.sidebar.markdown("---")  
st.sidebar.header("🔍 Ordenação da Busca na Shopee")  

opcao_ordem = st.sidebar.selectbox(  
    "Ordenar Busca Por:",  
    [  
        "Relevância (Igual à pesquisa do site da Shopee)",  
        "Mais Vendidos / Populares",  
        "Maior Taxa de Comissão"  
    ]  
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
    value=30,  
    step=5  
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
    default=["Todas as Lojas (Recomendado - Maior volume)"]  
)  

min_vendas = st.sidebar.number_input("Vendas Mínimas do Produto", value=0, step=5)  

col_p1, col_p2 = st.sidebar.columns(2)  
with col_p1:  
    min_price = st.number_input("Preço Mínimo (R$)", value=0.0, step=5.0)  
with col_p2:  
    max_price = st.number_input("Preço Máximo (R$ 0 = sem limite)", value=0.0, step=10.0)  

st.sidebar.markdown("---")  
st.sidebar.header("🎯 Histórico e Filtros")  

usar_historico = st.sidebar.checkbox("Ignorar Ofertas Já Buscadas Antes (Histórico)", value=True)  

if st.sidebar.button("🧹 Limpar Histórico do Servidor"):  
    limpar_historico_arquivo()  
    st.sidebar.success("Histórico zerado com sucesso!")  

filtrar_desconto = st.sidebar.checkbox("Filtrar por Desconto Mínimo", value=False)  
min_desconto = st.sidebar.slider("Desconto Mínimo (%)", 5, 90, 20) if filtrar_desconto else 0  

filtrar_comissao = st.sidebar.checkbox("Filtrar por Comissão Mínima", value=False)  
min_comissao = st.sidebar.slider("Comissão Mínima (%)", 1.0, 30.0, 8.0) if filtrar_comissao else 0  

st.sidebar.markdown("---")  
st.sidebar.header("✍️ Tom e Estilo do Gemini")  
estilo_prompt = st.sidebar.selectbox(  
    "Estilo da Frase:",  
    [  
        "Amiga / Achadinhos (Especial Cupons 8.8)",  
        "Urgência / Promoção Relâmpago (Poucas unidades)",  
        "Festa Infantil & Maternidade (Dica de amiga)",  
        "Oportunidade Imperdível (Foco em economizar)"  
    ]  
)  
tamanho_lote_gemini = st.sidebar.slider(
    "Ofertas por chamada ao Gemini (lote)",
    min_value=5, max_value=25, value=10,
    help="Números maiores = menos chamadas à API = mais rápido e mais barato. Se notar frases de baixa qualidade, diminua."
)

# Conteúdo Principal  

if "resultados" not in st.session_state:  
    st.session_state.resultados = []  

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
                min_price, max_price  
            )  
            todas_ofertas_filtradas.extend(boas)  
            total_bruto_acumulado += stats["total_bruto"]  
            total_descarte_hist += stats["descartes_historico"]  
            total_descarte_loja += stats["descartes_loja"]  
            progresso.progress((index + 1) / total_buscas)  
        
        status_text.text("Gerando frases personalizadas com o Gemini AI...")  
        
        resultados_gerados = []  
        novos_links = []  
        novos_produtos = []  
        novas_frases = []  
        
        progresso_gemini = st.progress(0)  
        total_boas = len(todas_ofertas_filtradas)  
        
        idx_global = 0
        for inicio in range(0, total_boas, tamanho_lote_gemini):
            lote = todas_ofertas_filtradas[inicio:inicio + tamanho_lote_gemini]
            frases_do_lote = gerar_frases_lote_gemini(gemini_client, lote, estilo_prompt, novas_frases)

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
                    "selecionado": True
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
            historico["produtos"] = list(set(historico["produtos"]) | set(novos_produtos))  
            historico["frases"] = list(set(historico["frases"]) | set(novas_frases))  
            salvar_historico(historico)  
        
        st.session_state.resultados = resultados_gerados  
        status_text.success(f"Concluído! {len(resultados_gerados)} ofertas geradas de um total de {total_bruto_acumulado} produtos analisados na Shopee.")  

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
        st.info(f"💡 **Ofertas Selecionadas: {len(selecionados)}**. Clique no botão de disparo de cada oferta sequencialmente se preferir enviá-las em mensagens isoladas no WhatsApp.")  
        if not selecionados:  
            st.warning("Nenhuma oferta selecionada.")  
        else:  
            for s_idx, item in enumerate(selecionados):  
                nome = item["oferta"].get("productName", "Produto")  
                col1, col2 = st.columns([3, 1])  
                with col1:  
                    st.write(f"**Oferta {s_idx + 1}:** {nome[:60]}...")  
                with col2:  
                    st.link_button(f"🚀 Disparar Oferta #{s_idx + 1}", item["whatsapp_url"], use_container_width=True)  
                st.divider()  

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
