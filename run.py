import uvicorn
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        app_dir="backend",
        host="127.0.0.1",
        port=8000,
        reload=True
    )