import hashlib  
import time  
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

# ============== FUNÇÕES DE API E AUXILIARES ==============  

def gerar_assinatura(app_id: str, app_secret: str, payload: str, timestamp: int) -> str:  
    base = f"{app_id}{timestamp}{payload}{app_secret}"  
    return hashlib.sha256(base.encode("utf-8")).hexdigest()  

def buscar_ofertas(app_id: str, app_secret: str, keyword, limit: int = 10, page: int = 1):  
    query = """  
    query buscarOfertas($keyword: String, $limit: Int, $page: Int) {  
        productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: 2) {  
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
        "variables": {"keyword": keyword if keyword else None, "limit": limit, "page": page}  
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

def buscar_todas_ofertas(app_id: str, app_secret: str, keyword, total_desejado: int):  
    todas = []  
    page = 1  
    while len(todas) < total_desejado:  
        restante = total_desejado - len(todas)  
        limite_pagina = min(50, restante)  
        nodes, has_next, erro = buscar_ofertas(app_id, app_secret, keyword, limite_pagina, page)  
        if erro or not nodes:  
            break  
        todas.extend(nodes)  
        if not has_next:  
            break  
        page += 1  
    return todas  

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
    texto = re.sub(r"\d+[/]\d*", " ", texto)  
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

def filtrar_ofertas(ofertas, historico: dict, usar_historico: bool,  
                    tipos_loja_selecionados: list, min_vendas: int,  
                    filtrar_comissao: bool, min_comissao: float,  
                    filtrar_desconto: bool, min_desconto: float,  
                    min_preco: float, max_preco: float):  
    links_usados = set(historico["links"]) if usar_historico else set()  
    produtos_usados = set(historico["produtos"]) if usar_historico else set()  
    produtos_nesta_rodada = set()  
    
    filtradas = []  
    for oferta in ofertas:  
        comissao = float(oferta.get("commissionRate") or 0) * 100  
        desconto = float(oferta.get("priceDiscountRate") or 0)  
        link = oferta.get("offerLink", "")  
        produto_key = normalizar_produto(oferta.get("productName", ""))  
        preco = float(oferta.get("price") or oferta.get("priceMin") or 0)  
        vendas = int(oferta.get("sales") or 0)  
        loja_tipos = obter_tipos_loja(oferta)  
        
        passou_loja = False  
        if "Todas as Lojas" in tipos_loja_selecionados:  
            passou_loja = True  
        else:  
            if "Lojas Oficiais (Shopee Oficial)" in tipos_loja_selecionados and 1 in loja_tipos:  
                passou_loja = True  
            if "Lojas Indicadas (Shopee Indicado)" in tipos_loja_selecionados and 2 in loja_tipos:  
                passou_loja = True  
        
        if not passou_loja:  
            continue  
            
        if vendas < min_vendas:  
            continue  
            
        if min_preco > 0 and preco < min_preco:  
            continue  
        if max_preco > 0 and preco > max_preco:  
            continue  
            
        if filtrar_comissao and comissao < min_comissao:  
            continue  
        if filtrar_desconto and desconto < min_desconto:  
            continue  
            
        if link in links_usados:  
            continue  
        if produto_key and (produto_key in produtos_usados or produto_key in produtos_nesta_rodada):  
            continue  
        
        produtos_nesta_rodada.add(produto_key)  
        filtradas.append(oferta)  
        
    filtradas.sort(key=lambda o: float(o.get("priceDiscountRate") or 0), reverse=True)  
    return filtradas  

def gerar_frase_gemini(gemini_client, oferta, estilo_prompt: str) -> str:  
    nome_produto = oferta.get("productName", "")  
    preco = oferta.get("price") or oferta.get("priceMin") or ""  
    desconto = oferta.get("priceDiscountRate", "")  

    prompt = f"""  
    Você cria mensagens promocionais para grupos de ofertas no WhatsApp.  
    Estilo desejado: {estilo_prompt}  
    
    Produto: {nome_produto}  
    Preço: R$ {preco}  
    Desconto: {desconto}%  

    Diretrizes estritas:  
    1. Crie UMA ÚNICA frase curta, chamativa e natural recomendando o produto.  
    2. Relacione a frase especificamente à utilidade ou benefício do produto.  
    3. Use 1 a 2 emojis adequados.  
    4. Responda APENAS com a frase final, sem aspas, explicações ou saudações.  
    """  
    try:  
        response = gemini_client.models.generate_content(  
            model="gemini-2.5-flash",  
            contents=prompt  
        )  
        return response.text.strip().replace("\n", " ")  
    except Exception as e:  
        return "Caramba, amiga, olha esse achado incrível! 😱"  

# ============== INTERFACE STREAMLIT ==============  

st.title("🛍️ Painel de Ofertas Shopee + Gemini AI")  
st.caption("Pesquise, selecione os melhores achados e envie individualmente ou em lote para o WhatsApp")  

# Sidebar - Configurações  
st.sidebar.header("🔑 Autenticação e APIs")  
app_id = st.sidebar.text_input("Shopee APP_ID", value="18325850447")  
app_secret = st.sidebar.text_input("Shopee APP_SECRET", value="BLFN3YKFSMCSHSKY65YQMFUMRDLCHPYY", type="password")  
gemini_key = st.sidebar.text_input("Gemini API Key", value="AQ.Ab8RN6JpRbEOoJTrl2mHywFNLg4-Hp8fJSrfBOJXFNoxj0C-sw", type="password")  

st.sidebar.markdown("---")  
st.sidebar.header("⚙️ Configurações da Busca")  

keywords_input = st.sidebar.text_area(  
    "Palavras-chave (uma por linha ou separadas por vírgula):",  
    value="lembrancinha, festa infantil, cozinha, casa, moda feminina, eletrodomesticos",  
    height=100  
)  

# NOVO PARAMETRO: Quantidade de ofertas por palavra-chave  
qtd_por_keyword = st.sidebar.number_input(  
    "Quantidade de Ofertas por Palavra-chave:",  
    min_value=5,  
    max_value=200,  
    value=30,  
    step=5  
)  

tipos_loja = st.sidebar.multiselect(  
    "Tipos de Loja na Shopee:",  
    [  
        "Lojas Oficiais (Shopee Oficial)",  
        "Lojas Indicadas (Shopee Indicado)",  
        "Todas as Lojas"  
    ],  
    default=["Lojas Oficiais (Shopee Oficial)", "Lojas Indicadas (Shopee Indicado)"]  
)  

min_vendas = st.sidebar.number_input("Vendas Mínimas do Produto", value=0, step=5)  

col_p1, col_p2 = st.sidebar.columns(2)  
with col_p1:  
    min_price = st.number_input("Preço Mínimo (R$)", value=0.0, step=5.0)  
with col_p2:  
    max_price = st.number_input("Preço Máximo (R$ 0 = sem limite)", value=250.0, step=10.0)  

st.sidebar.markdown("---")  
st.sidebar.header("🎯 Filtros de Desconto e Comissão")  
filtrar_desconto = st.sidebar.checkbox("Filtrar por Desconto Mínimo", value=False)  
min_desconto = st.sidebar.slider("Desconto Mínimo (%)", 5, 90, 20) if filtrar_desconto else 0  

filtrar_comissao = st.sidebar.checkbox("Filtrar por Comissão Mínima", value=False)  
min_comissao = st.sidebar.slider("Comissão Mínima (%)", 1.0, 30.0, 8.0) if filtrar_comissao else 0  

buscar_gerais = st.sidebar.checkbox("Incluir Ofertas Gerais (Sem termo específico)", value=True)  
usar_historico = st.sidebar.checkbox("Ignorar Produtos/Links Já Divulgados (Histórico)", value=True)  

st.sidebar.markdown("---")  
st.sidebar.header("✍️ Tom e Estilo do Gemini")  
estilo_prompt = st.sidebar.selectbox(  
    "Estilo da Frase:",  
    [  
        "Amiga / Achadinhos (Descontraído e íntimo)",  
        "Urgência / Promoção Relâmpago (Oportunidade única)",  
        "Festa Infantil & Maternidade (Carinhoso e prático)",  
        "Direto e Objetivo (Foco no preço e economia)"  
    ]  
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
        
        keywords_list = [k.strip() for k in re.split(r"[,\n]", keywords_input) if k.strip()]  
        buscas = list(keywords_list)  
        if buscar_gerais:  
            buscas.append(None)  
        
        progresso = st.progress(0)  
        status_text = st.empty()  
        
        todas_ofertas_filtradas = []  
        total_buscas = len(buscas)  
        
        for index, kw in enumerate(buscas):  
            rotulo = "Ofertas Gerais" if kw is None else kw  
            status_text.text(f"Buscando {qtd_por_keyword} ofertas para: {rotulo}...")  
            
            ofertas = buscar_todas_ofertas(app_id, app_secret, kw, qtd_por_keyword)  
            boas = filtrar_ofertas(  
                ofertas, historico, usar_historico,  
                tipos_loja, min_vendas,  
                filtrar_comissao, min_comissao,  
                filtrar_desconto, min_desconto,  
                min_price, max_price  
            )  
            todas_ofertas_filtradas.extend(boas)  
            progresso.progress((index + 1) / total_buscas)  
        
        status_text.text("Gerando frases personalizadas com o Gemini AI...")  
        
        resultados_gerados = []  
        novos_links = []  
        novos_produtos = []  
        novas_frases = []  
        
        progresso_gemini = st.progress(0)  
        total_boas = len(todas_ofertas_filtradas)  
        
        for idx, oferta in enumerate(todas_ofertas_filtradas):  
            frase = gerar_frase_gemini(gemini_client, oferta, estilo_prompt)  
            link = oferta.get("offerLink", "")  
            texto_final = f"cta[{frase.upper()}]\n\n{link}"  
            
            texto_encoded = urllib.parse.quote(texto_final)  
            whatsapp_url = f"https://api.whatsapp.com/send?text={texto_encoded}"  
            
            resultados_gerados.append({  
                "id": idx,  
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
            
            if total_boas > 0:  
                progresso_gemini.progress((idx + 1) / total_boas)  
            time.sleep(0.5)  
        
        if usar_historico and resultados_gerados:  
            historico["links"] = list(set(historico["links"]) | set(novos_links))  
            historico["produtos"] = list(set(historico["produtos"]) | set(novos_produtos))  
            historico["frases"] = list(set(historico["frases"]) | set(novas_frases))  
            salvar_historico(historico)  
        
        st.session_state.resultados = resultados_gerados  
        status_text.success(f"Concluído! {len(resultados_gerados)} ofertas geradas.")  

# Exibição dos Resultados  

if st.session_state.resultados:  
    st.subheader(f"📋 Ofertas Encontradas ({len(st.session_state.resultados)})")  
    
    # Seleção rápida  
    selecionados = [item for item in st.session_state.resultados if item["selecionado"]]  
    
    # Bloco para envio do LOTE COMPLETO de selecionadas  
    if selecionados:  
        texto_bloco_total = "\n\n---\n\n".join([r["texto_final"] for r in selecionados])  
        texto_bloco_encoded = urllib.parse.quote(texto_bloco_total)  
        whatsapp_lote_url = f"https://api.whatsapp.com/send?text={texto_bloco_encoded}"  
        
        st.markdown("### 📲 Opção 1: Enviar TODAS as Selecionadas de uma vez só")  
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
