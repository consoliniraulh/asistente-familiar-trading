import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from langchain_groq import ChatGroq
from langchain_community.tools import DuckDuckGoSearchRun
from langgraph.prebuilt import create_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
import plotly.express as px

st.set_page_config(page_title="Mi Asistente Familiar + Trading", layout="wide")
st.title("🤖 Asistente Familiar y Trading - Mendoza")

# ==================== CONEXIÓN A GOOGLE SHEETS ====================
creds_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
client = gspread.authorize(creds)
sh = client.open("AsistenteFamiliarTrading")

sheet_history = sh.worksheet("ChatHistory")
sheet_crudos = sh.worksheet("DatosCrudos")
sheet_indicadores = sh.worksheet("Indicadores")
sheet_senales = sh.worksheet("Señales")

# ==================== USUARIO FAMILIAR ====================
if "user_id" not in st.session_state:
    st.session_state.user_id = "Raúl"

usuarios = ["Raúl", "Pareja", "Hijo1", "Hijo2"]
user_id = st.sidebar.selectbox("Usuario actual", usuarios, index=usuarios.index(st.session_state.user_id))
st.session_state.user_id = user_id

# ==================== TABS ====================
tab1, tab2 = st.tabs(["💬 Chat Doméstico (con búsqueda web)", "📈 Análisis Trading Automático"])

# ===================== TAB 1: CHAT DOMÉSTICO =====================
with tab1:
    st.subheader("Chat Familiar - Preguntame cualquier cosa (compras, listas, recordatorios...)")
    
    # Carga memoria previa (últimos 30 mensajes del usuario)
    if "messages" not in st.session_state:
        st.session_state.messages = []
        records = sheet_history.get_all_records()
        user_records = [r for r in records if r.get("User") == user_id][-30:]
        for r in user_records:
            role = "user" if r["Role"] == "user" else "assistant"
            st.session_state.messages.append({"role": role, "content": r["Message"]})

    # Muestra historial
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Herramienta de búsqueda web
    search_tool = DuckDuckGoSearchRun()

    # LLM
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=st.secrets["GROQ_API_KEY"],
        temperature=0.7
    )
    
    # Prompt del sistema
    system_prompt = f"""Eres un asistente doméstico familiar en Mendoza, Argentina. 
Usa la herramienta de búsqueda web cuando te pregunten precios, lugares, promociones o información actual.
Responde siempre en español, claro, útil y amigable.
Considera supermercados locales: Carrefour, Coto, Jumbo, Changomás, Día, Disco, etc.
Si es posible, incluye precios aproximados o la mejor opción encontrada."""

    # Creamos el agente con LangGraph (estilo ReAct moderno)
    agent_executor = create_react_agent(
        model=llm,
        tools=[search_tool],
        prompt=ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("placeholder", "{messages}"),
        ])
    )

    if prompt_user := st.chat_input("Ej: Me falta arroz, busca dónde está más barato en Mendoza"):
        st.session_state.messages.append({"role": "user", "content": prompt_user})
        with st.chat_message("user"):
            st.markdown(prompt_user)

        with st.chat_message("assistant"):
            with st.spinner("Buscando y pensando..."):
                # Invocación moderna con LangGraph
                response = agent_executor.invoke({
                    "messages": [HumanMessage(content=prompt_user)]
                })
                output = response["messages"][-1].content
                st.markdown(output)

        # Guarda en Google Sheets
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet_history.append_row([now, user_id, "user", prompt_user])
        sheet_history.append_row([now, user_id, "assistant", output])
        st.session_state.messages.append({"role": "assistant", "content": output})

# ===================== TAB 2: TRADING =====================
with tab2:
    st.subheader("Análisis Trading Automático")
    df_ind = pd.DataFrame(sheet_indicadores.get_all_records())
    
    if df_ind.empty:
        st.warning("La pestaña 'Indicadores' está vacía. Carga datos primero.")
    else:
        activos = df_ind["Ticker"].unique() if "Ticker" in df_ind.columns else ["Elegir manual"]
        activo = st.selectbox("Activo a analizar", activos)
        
        if st.button("🔍 Generar señal ahora", type="primary"):
            with st.spinner("Leyendo datos y aplicando tus reglas..."):
                # Última fila del activo
                data = df_ind[df_ind["Ticker"] == activo].iloc[-1]
                
                # === PERSONALIZA AQUÍ TUS REGLAS EXACTAS ===
                prompt_trading = f"""
Eres un trader experimentado. Analiza estos datos del activo {activo}:

Precio: {data.get('Close', 'N/A')}
RSI: {data.get('RSI', 'N/A')} | MACD: {data.get('MACD', 'N/A')}
SMA50: {data.get('SMA50', 'N/A')} | SMA200: {data.get('SMA200', 'N/A')}
Volumen: {data.get('Volume', 'N/A')}

TUS REGLAS (modifícalas según tu estrategia):
- COMPRA fuerte si RSI < 30 y precio > SMA50 y MACD cruzó arriba
- VENTA si RSI > 70 o precio < SMA200
- NEUTRO en otros casos
- Riesgo máximo 2% del capital por operación
- Considera contexto Argentina (impuestos, comisiones, acceso al dólar)

Responde en español con:
1. Señal clara (COMPRA / VENTA / NEUTRO)
2. Explicación paso a paso
3. Stop-loss y Take-profit sugeridos
4. Tamaño de posición recomendado (ej: % del capital)
"""

                respuesta = llm.invoke(prompt_trading).content

                # Guarda señal
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheet_senales.append_row([now, activo, respuesta])

                st.success(f"Señal generada y guardada para {activo}")
                st.markdown(respuesta)

                # Gráfico simple
                df_plot = pd.DataFrame(sheet_crudos.get_all_records())
                if not df_plot.empty and "Close" in df_plot.columns:
                    columnas_grafico = ["Close"]
                    if "SMA50" in df_plot.columns:
                        columnas_grafico.append("SMA50")
                    if "SMA200" in df_plot.columns:
                        columnas_grafico.append("SMA200")
                    
                    fig = px.line(
                        df_plot[df_plot.get("Ticker") == activo],
                        x="Date" if "Date" in df_plot.columns else df_plot.index,
                        y=columnas_grafico,
                        title=f"{activo} - Precio y Medias"
                    )
                    st.plotly_chart(fig, use_container_width=True)

# ==================== SIDEBAR INFO ====================
st.sidebar.info("App desplegada desde GitHub + Google Sheets\nMemoria persistente + búsqueda web activa")
st.sidebar.caption("Versión marzo 2026 - Raúl Mendoza")
