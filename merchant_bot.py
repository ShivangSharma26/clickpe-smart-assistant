import streamlit as st
import os
from dotenv import load_dotenv

# --- Imports ---
from langchain_google_genai import ChatGoogleGenerativeAI
# CHANGE IS HERE: Hum Google ki jagah Local Embeddings use kar rahe hain
from langchain_huggingface import HuggingFaceEmbeddings 
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_core.messages import HumanMessage, SystemMessage

# LangGraph Imports
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict, Annotated, List

# Load API Key
load_dotenv()

# --- 1. RAG SETUP (Hybrid: Local Embeddings + Google Chat) ---
@st.cache_resource
def setup_rag():
    # Policy file load
    # Ensure file exists at this path
    if not os.path.exists("./knowledge_base/policy.txt"):
        st.error("Error: policy.txt not found in knowledge_base folder!")
        return None

    loader = TextLoader("./knowledge_base/policy.txt")
    documents = loader.load()
    
    # Split Text
    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)
    
    # --- MAJOR CHANGE: Using Free Local Embeddings ---
    # Ye model first time run hone mein 10-20 seconds lega (download hoga 50MB)
    # Uske baad ye instant chalega. No Rate Limits!
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Vector Store
    vectorstore = Chroma.from_documents(documents=docs, embedding=embeddings)
    return vectorstore.as_retriever()

# --- 2. LANGGRAPH STATE ---
class AgentState(TypedDict):
    messages: List[Annotated[HumanMessage, SystemMessage]]
    context: str

# --- 3. NODE LOGIC ---
def retrieve_node(state: AgentState):
    retriever = setup_rag()
    last_message = state["messages"][-1].content
    
    if retriever:
        docs = retriever.invoke(last_message)
        context_text = "\n".join([d.page_content for d in docs])
    else:
        context_text = "No policy context available."
        
    return {"context": context_text}

def generate_node(state: AgentState):
    # Chat ke liye abhi bhi Google Gemini use kar rahe hain (Ye free hai aur fast hai)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)

    
    context = state["context"]
    messages = state["messages"]
    
    system_prompt = f"""You are 'ClickPe Sahayak', a friendly advisor for shop owners.
    Use this ClickPe policy to answer: {context}
    
    If the answer is not in context, say you don't know but try to be helpful.
    Answer in simple Hinglish (Hindi + English).
    """
    
    all_messages = [SystemMessage(content=system_prompt)] + messages
    try:
        response = llm.invoke(all_messages)
        return {"messages": [response]}
    except Exception as e:
        return {"messages": [HumanMessage(content=f"⚠️ TECHNICAL ERROR: {str(e)}")]}
# --- 4. BUILD GRAPH ---
def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)
    
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

# --- 5. UI FUNCTION ---
def render_merchant_ui():
    st.header("🏪 ClickPe Merchant Sahayak")
    st.caption("Powered by Gemini 1.5 Flash + Local Embeddings")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    for msg in st.session_state.messages:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        with st.chat_message(role):
            st.write(msg.content)

    if user_input := st.chat_input("Puchiye apne loan ya policy ke baare mein..."):
        st.session_state.messages.append(HumanMessage(content=user_input))
        with st.chat_message("user"):
            st.write(user_input)

        app = build_graph()
        config = {"configurable": {"thread_id": "merchant_test_local"}}
        
        with st.spinner("Analyzing policy..."):
            inputs = {"messages": st.session_state.messages, "context": ""}
            result = app.invoke(inputs, config=config)
            bot_response = result["messages"][-1]
            
            st.session_state.messages.append(bot_response)
            with st.chat_message("assistant"):
                st.write(bot_response.content)