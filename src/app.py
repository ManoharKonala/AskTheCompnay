import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import requests
import json
import pandas as pd
from typing import Dict, Any, List

# Set page config
st.set_page_config(
    page_title="AskTheCompany — Enterprise Multimodal RAG",
    page_icon="🔓",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_URL = "http://localhost:8000"

# Custom CSS for premium styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main {
        background-color: #0f172a;
        color: #f1f5f9;
    }
    
    .stButton>button {
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
        font-weight: 500;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.3), 0 4px 6px -2px rgba(59, 130, 246, 0.05);
    }
    
    .card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    
    .source-badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 8px;
        text-transform: uppercase;
    }
    
    .badge-confluence { background-color: #0369a1; color: #e0f2fe; }
    .badge-slack { background-color: #6b21a8; color: #f3e8ff; }
    .badge-excel { background-color: #15803d; color: #dcfce7; }
    .badge-pdf { background-color: #b91c1c; color: #fee2e2; }
    
    .acl-badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        background-color: #374151;
        color: #f3f4f6;
        border: 1px solid #4b5563;
    }
    
    .score-badge {
        float: right;
        font-size: 0.85rem;
        font-weight: 600;
        color: #10b981;
    }
    
    .header-gradient {
        background: linear-gradient(to right, #3b82f6, #8b5cf6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.5rem;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# Session state initialization
if "token" not in st.session_state:
    st.session_state["token"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None
if "user_groups" not in st.session_state:
    st.session_state["user_groups"] = []

# Pre-populate demo users on the backend on startup
def setup_demo_users():
    # Demo credentials loaded from environment variables (never hardcode secrets)
    demo_users = [
        {"username": os.getenv("DEMO_GUEST_USER", "guest"), "password": os.getenv("DEMO_GUEST_PASS", ""), "groups": ["Public"]},
        {"username": os.getenv("DEMO_HR_USER", "hr_staff"), "password": os.getenv("DEMO_HR_PASS", ""), "groups": ["HR"]},
        {"username": os.getenv("DEMO_MANAGER_USER", "manager"), "password": os.getenv("DEMO_MANAGER_PASS", ""), "groups": ["Management"]},
        {"username": os.getenv("DEMO_ADMIN_USER", "admin"), "password": os.getenv("DEMO_ADMIN_PASS", ""), "groups": ["HR", "Management", "Engineering"]}
    ]
    for user in demo_users:
        try:
            requests.post(f"{API_URL}/auth/register", json=user)
        except Exception:
            pass

setup_demo_users()

# Sidebar for Authentication / Role Selection
with st.sidebar:
    st.markdown("### 🔐 Identity & Access Control")
    st.write("Simulate different users to verify the ACL (Access Control List) filters.")
    
    # Simple Quick Login
    role = st.selectbox(
        "Quick Login as:",
        ["Select...", "Guest (Public)", "HR Staff (HR)", "Manager (Management)", "Admin (All Groups)"]
    )
    
    if role != "Select...":
        # Demo credentials loaded from environment variables (never hardcode secrets)
        credentials = {
            "Guest (Public)": (os.getenv("DEMO_GUEST_USER", "guest"), os.getenv("DEMO_GUEST_PASS", "")),
            "HR Staff (HR)": (os.getenv("DEMO_HR_USER", "hr_staff"), os.getenv("DEMO_HR_PASS", "")),
            "Manager (Management)": (os.getenv("DEMO_MANAGER_USER", "manager"), os.getenv("DEMO_MANAGER_PASS", "")),
            "Admin (All Groups)": (os.getenv("DEMO_ADMIN_USER", "admin"), os.getenv("DEMO_ADMIN_PASS", ""))
        }
        username, password = credentials[role]
        
        # Authenticate
        try:
            response = requests.post(
                f"{API_URL}/auth/token",
                data={"username": username, "password": password}
            )
            if response.status_code == 200:
                data = response.json()
                st.session_state["token"] = data["access_token"]
                st.session_state["username"] = username
                # Decode groups locally for display
                # In a real app we'd decode the JWT payload
                groups_map = {
                    "guest": ["Public"],
                    "hr_staff": ["HR"],
                    "manager": ["Management"],
                    "admin": ["HR", "Management", "Engineering"]
                }
                st.session_state["user_groups"] = groups_map[username]
                st.sidebar.success(f"Logged in as: **{username}**")
            else:
                st.sidebar.error("Failed to authenticate demo user.")
        except Exception as e:
            st.sidebar.error(f"Cannot reach API server: {e}")
            
    st.markdown("---")
    if st.session_state["username"]:
        st.write(f"**Current User:** `{st.session_state['username']}`")
        st.write(f"**Assigned Groups:**")
        for g in st.session_state["user_groups"]:
            st.markdown(f"- `<span class='acl-badge'>{g}</span>`", unsafe_allow_html=True)
    else:
        st.warning("Please log in using the dropdown above.")

# Main Page Layout
st.markdown("<h1 class='header-gradient'>AskTheCompany</h1>", unsafe_allow_html=True)
st.markdown("##### Production-Grade Multimodal RAG with Document-Level Access Control Lists (ACLs)")

tabs = st.tabs(["🔍 Secure Query", "📊 System Admin & Audit Logs"])

# ==========================================
# TAB 1: Secure Query
# ==========================================
with tabs[0]:
    if not st.session_state["token"]:
        st.info("👈 Please select a role in the sidebar to log in and start querying.")
    else:
        query = st.text_input("Ask a question about company policies, finances, or Slack threads:", placeholder="e.g., What is the annual leave policy?")
        
        if query:
            with st.spinner("Retrieving relevant context and generating answer..."):
                headers = {"Authorization": f"Bearer {st.session_state['token']}"}
                try:
                    res = requests.post(
                        f"{API_URL}/query",
                        json={"query": query},
                        headers=headers
                    )
                    
                    if res.status_code == 200:
                        data = res.json()
                        answer = data["answer"]
                        citations = data["citations"]
                        chunks = data["retrieved_chunks"]
                        cached = data["cached"]
                        
                        # Cache indicator
                        if cached:
                            st.info("⚡ Response retrieved from Semantic Cache (Redis)")
                            
                        # Answer Card
                        st.markdown("### 🤖 Answer")
                        st.markdown(f"<div class='card' style='font-size: 1.1rem; line-height: 1.6;'>{answer}</div>", unsafe_allow_html=True)
                        
                        # Citations
                        if citations:
                            st.markdown("**Cited Documents:**")
                            cols = st.columns(len(citations))
                            for idx, cit in enumerate(citations):
                                cols[idx].markdown(f"📄 `{cit}`")
                                
                        # Retrieved Chunks Details (ACL Validation)
                        st.markdown("---")
                        st.markdown("### 📂 Source Lineage & ACL Verification")
                        st.write("Below are the exact document chunks retrieved from the vector database. Notice how they match your user permissions:")
                        
                        for idx, chunk in enumerate(chunks):
                            src_type = chunk["source_type"]
                            filename = chunk["filename"]
                            score = chunk.get("rerank_score", 0.0)
                            allowed = chunk["allowed_groups"]
                            text_content = chunk["text"]
                            
                            badge_class = f"badge-{src_type}"
                            
                            st.markdown(f"""
                            <div class='card'>
                                <span class='score-badge'>Re-rank Score: {score:.4f}</span>
                                <span class='source-badge {badge_class}'>{src_type}</span>
                                <strong>{filename}</strong>
                                <div style='margin-top: 10px; margin-bottom: 10px; font-size: 0.9rem; color: #cbd5e1; background-color: #0f172a; padding: 12px; border-radius: 6px; white-space: pre-wrap;'>{text_content}</div>
                                <span style='font-size: 0.8rem; color: #94a3b8;'>Allowed Groups:</span>
                                {' '.join([f"<span class='acl-badge'>{a}</span>" for a in allowed])}
                            </div>
                            """, unsafe_allow_html=True)
                            
                    else:
                        st.error(f"Error: {res.json().get('detail', 'Query failed')}")
                except Exception as e:
                    st.error(f"Failed to connect to API server: {e}")

# ==========================================
# TAB 2: System Admin
# ==========================================
with tabs[1]:
    st.markdown("### ⚙️ System Administration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Ingestion Control")
        st.write("Trigger the ingestion pipeline to parse all files in `data/seed` and upsert them to Qdrant and PostgreSQL.")
        
        if st.button("🚀 Trigger Ingestion"):
            with st.spinner("Running ingestion pipeline (parsing, OCR, embedding)..."):
                try:
                    res = requests.post(f"{API_URL}/ingest")
                    if res.status_code == 200:
                        st.success("Ingestion completed successfully!")
                        st.json(res.json())
                    else:
                        st.error("Ingestion failed.")
                except Exception as e:
                    st.error(f"Connection error: {e}")
                    
    with col2:
        st.markdown("#### Database Inspection")
        st.write("Ensure your PostgreSQL and Qdrant instances are connected.")
        try:
            health_res = requests.get(f"{API_URL}/health", timeout=3)
            if health_res.status_code == 200:
                health_data = health_res.json()
                st.success("🟢 PostgreSQL Connected" if health_data.get("postgres") else "🔴 PostgreSQL Disconnected")
                st.success("🟢 Qdrant Vector DB Connected" if health_data.get("qdrant") else "🔴 Qdrant Vector DB Disconnected")
                st.success("🟢 Redis Cache Connected" if health_data.get("redis") else "🔴 Redis Cache Disconnected")
            else:
                st.error("🔴 Failed to fetch health status from API.")
        except Exception:
            st.error("🔴 Backend API is unreachable.")

    # Audit Logs Section
    st.markdown("---")
    st.markdown("### 📜 Query Audit Logs")
    st.write("This log displays all queries processed by the RAG system, including the user, query, response, and retrieved sources. This is persisted in PostgreSQL.")
    
    # We can fetch audit logs if the user is logged in
    if st.session_state["token"]:
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        try:
            res = requests.get(f"{API_URL}/admin/logs", headers=headers, params={"limit": 50})
            if res.status_code == 200:
                data = res.json()
                logs = data.get("logs", data) if isinstance(data, dict) else data
                total = data.get("total", len(logs)) if isinstance(data, dict) else len(logs)
                if logs:
                    st.caption(f"Showing {len(logs)} of {total} total log entries.")
                    log_data = []
                    for log in logs:
                        log_data.append({
                            "Timestamp": log["timestamp"],
                            "User ID": log["user_id"],
                            "Query": log["query"],
                            "Response": log["response"][:100] + "..." if len(log["response"]) > 100 else log["response"],
                            "Retrieved Chunks": str(log["retrieved_chunks"])
                        })
                    df_logs = pd.DataFrame(log_data)
                    st.dataframe(df_logs, use_container_width=True)
                else:
                    st.info("No audit logs found. Run some queries first!")
            elif res.status_code == 403:
                st.error("Admin privileges required to view logs.")
            elif res.status_code == 429:
                st.warning("Rate limit exceeded. Please wait and try again.")
            else:
                st.error(f"Failed to fetch logs: {res.status_code}")
        except Exception as e:
            st.error(f"Failed to fetch audit logs from API: {e}")
    else:
        st.info("Please log in to view audit logs.")
