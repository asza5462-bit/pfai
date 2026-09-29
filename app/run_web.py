import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("AURUM_HOST", os.getenv("PFAI_HOST", "0.0.0.0"))
    port = int(os.getenv("PORT", os.getenv("AURUM_PORT", "8000")))
    uvicorn.run("goldbot.api:app", host=host, port=port, reload=False)
