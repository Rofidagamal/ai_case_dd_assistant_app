#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
# Skip Streamlit's one-time "enter your email" question
mkdir -p ~/.streamlit
[ -f ~/.streamlit/credentials.toml ] || printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
streamlit run app.py --server.headless false
