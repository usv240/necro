import uvicorn
uvicorn.run("backend.main:app", host="127.0.0.1", port=8080, log_level="warning", access_log=False)
