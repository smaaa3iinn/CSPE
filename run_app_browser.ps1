# Open CSPE in your default web browser (original behavior).
$env:PYTHONPATH = (Get-Location).Path
$env:STREAMLIT_SERVER_ENABLE_STATIC_SERVING = "true"
streamlit run app/app.py
