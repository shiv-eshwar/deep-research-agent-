import streamlit as st
import requests
import json
import time
import os

# --- Configuration ---
API_URL = os.getenv("API_URL", "http://localhost:8000") 

st.set_page_config(
    page_title="Deep Research Agent",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("🧠 Deep Research AI Agent")
st.markdown("Enter a complex question or topic to generate a comprehensive, synthesized research report.")

# --- Session State ---
if "research_active" not in st.session_state:
    st.session_state.research_active = False

if "report" not in st.session_state:
    st.session_state.report = ""

# --- UI Layout ---
query = st.text_input("Research Topic", placeholder="e.g. What are the biggest risks of autonomous AI agents in 2025?")

if st.button("Start Research", type="primary", disabled=st.session_state.research_active):
    if not query:
        st.warning("Please enter a research topic first.")
    else:
        st.session_state.research_active = True
        st.session_state.report = ""
        
        # We will poll the async endpoint instead of SSE for better compatibility with Streamlit's execution model
        status_placeholder = st.empty()
        log_container = st.container()
        
        try:
            with status_placeholder.status("Starting deep research...", expanded=True) as status_box:
                
                # 1. Start the async job
                st.write("Initializing agent and planning research strategy...")
                response = requests.post(f"{API_URL}/research/async", json={"query": query})
                response.raise_for_status()
                
                job_data = response.json()
                job_id = job_data["job_id"]
                st.write(f"Job started. ID: `{job_id}`")
                
                # 2. Poll for completion
                max_polls = 120 # 10 minutes max at 5s intervals
                polls = 0
                
                while polls < max_polls:
                    time.sleep(5)
                    polls += 1
                    
                    poll_response = requests.get(f"{API_URL}/research/jobs/{job_id}")
                    if poll_response.status_code == 200:
                        status_data = poll_response.json()
                        current_status = status_data["status"]
                        
                        if current_status == "completed":
                            status_box.update(label="Research Complete!", state="complete", expanded=False)
                            st.session_state.report = status_data["report"]
                            
                            # Display metrics if available
                            if "metadata" in status_data:
                                meta = status_data["metadata"]
                                iters = meta.get("research_iterations", 0)
                                revs = meta.get("revision_count", 0)
                                sources = meta.get("sources_found", 0)
                                st.success(f"Finalized after {iters} search iterations and {revs} draft revisions using {sources} sources.")
                            break
                        
                        elif current_status == "failed":
                            error_msg = status_data.get("error", "Unknown error")
                            status_box.update(label="Research Failed", state="error", expanded=True)
                            st.error(f"Job failed: {error_msg}")
                            break
                        
                        else:
                            # It's still running
                            st.write("Agent is actively searching, synthesizing, and reflecting... Please wait.")
                    else:
                        st.warning(f"Failed to poll job status. HTTP {poll_response.status_code}")
                
                if polls >= max_polls:
                     status_box.update(label="Research Timed Out", state="error")
                     st.error("The research job took too long to complete. Please try a simpler query.")
                     
        except Exception as e:
            status_placeholder.error(f"Failed to connect to the backend API: {e}. Is the API running at {API_URL}?")
        
        finally:
            st.session_state.research_active = False

# --- Display Report ---
if st.session_state.report:
    st.markdown("---")
    st.markdown("## Final Research Report")
    st.markdown(st.session_state.report)
    
    st.download_button(
        label="Download Markdown Report",
        data=st.session_state.report,
        file_name="research_report.md",
        mime="text/markdown"
    )
