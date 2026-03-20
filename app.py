import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from langchain_groq import ChatGroq
from langchain_community.tools import DuckDuckGoSearchRun
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
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
    
    # Carga memoria previa
    if "messages" not in st.session_state:
        st.session_state.messages = []
        records = sheet_history.get_all_records()
        user_records = [r for r in records if r.get("User") == user_id][-30:]
        for r in user_records:
            st.session_state.messages.append({"role": "user" if r["Role"] == "user" else "assistant", "content": r["Message"]})

    # Muestra historial
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Herramienta de búsqueda web
    search_tool = DuckDuckGoSearchRun()

    # LLM + Agente
    llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=st.secrets["GROQ_API_KEY"], temperature=0.7)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""Eres un asistente doméstico familiar en Mendoza, Argentina. 
        Usa la herramienta de búsqueda web cuando te pregunten precios, lugares o promociones.
        Responde siempre en español, claro y útil. Considera supermercados locales (Carrefour, Coto, Jumbo, Changomás, Día)."""),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, [search_tool], prompt)
    agent_executor = AgentExecutor(agent=agent, tools=[search_tool], verbose=False, handle_parsing_errors=True)

    if prompt_user := st.chat_input("Ej: Me falta arroz, busca dónde está más barato en Mendoza"):
        st.session_state.messages.append({"role": "user", "content": prompt_user})
        with st.chat_message("user"):
            st.markdown(prompt_user)

        with st.chat_message("assistant"):
            with st.spinner("Buscando y pensando..."):
                response = agent_executor.invoke({"input": prompt_user, "chat_history": st.session_state.messages})
                output = response["output"]
                st.markdown(output)

        # Guarda en Sheets
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

                MIS REGLAS (ajústalas como quieras en el código):
                - COMPRA fuerte si RSI < 30 y precio > SMA50 y MACD cruzó arriba
                - VENTA si RSI > 70 o precio < SMA200
                - NEUTRO en otros casos
                - Riesgo máximo 2% del capital
                - Considera Argentina (impuestos, comisiones)

                Responde en español con:
                1. Señal clara (COMPRA / VENTA / NEUTRO)
                2. Explicación paso a paso
                3. Stop-loss y Take-profit
                4. Tamaño de posición sugerido
                """

                respuesta = llm.invoke(prompt_trading).content

                # Guarda señal
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheet_senales.append_row([now, activo, respuesta])

                st.success(f"Señal generada y guardada para {activo}")
                st.markdown(respuesta)

                # Gráfico
                df_plot = pd.DataFrame(sheet_crudos.get_all_records())
                if not df_plot.empty and "Close" in df_plot.columns:
                    fig = px.line(df_plot[df_plot.get("Ticker") == activo], x="Date" if "Date" in df_plot.columns else df_plot.index, 
                                  y=["Close", "SMA50", "SMA200"] if all(x in df_plot.columns for x in ["SMA50","SMA200"]) else ["Close"])
                    st.plotly_chart(fig, use_container_width=True)

# ==================== SIDEBAR INFO ====================
st.sidebar.info("App desplegada desde GitHub + Google Sheets\nMemoria persistente + búsqueda web activa")
st.sidebar.caption("Versión marzo 2026 - Raúl Mendoza")