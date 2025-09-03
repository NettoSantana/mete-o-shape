import os
from flask import Flask

app = Flask(__name__)
PROJECT_NAME = os.getenv("PROJECT_NAME", "mete_o_shape")

@app.get("/")
def root():
    return {"ok": True, "project": PROJECT_NAME, "route": "/"}

@app.get("/admin/ping")
def ping():
    return {"ok": True, "project": PROJECT_NAME, "route": "/admin/ping"}

if __name__ == "__main__":
    port = int(os.getenv("PORT") or "8080")
    app.run(host="0.0.0.0", port=port)
