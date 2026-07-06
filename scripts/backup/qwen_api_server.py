#!/usr/bin/env python3
"""
Qwen → OpenAI 兼容 API 服务 (Ollama 转发版)
供 Dify 作为模型提供商对接，请求转发到本地 Ollama 服务。
"""
import os
import time
import json
import warnings
import argparse
import requests
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore")

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")

app = FastAPI(title="Qwen Local API (Ollama Proxy)")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "qwen2"
    messages: List[ChatMessage]
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 512
    stream: bool = False


def _to_openai_response(ollama_resp: dict, model: str, prompt_tokens: int = 0, completion_tokens: int = 0):
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": ollama_resp["message"]["content"]
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/health")
@app.get("/v1/health")
async def health():
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        return {"status": "ok", "ollama_connected": r.status_code == 200}
    except Exception:
        return {"status": "error", "ollama_connected": False}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": OLLAMA_MODEL, "object": "model", "created": int(time.time())}]
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "max_tokens": request.max_tokens,
            },
        }

        r = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        ollama_resp = r.json()

        return _to_openai_response(
            ollama_resp,
            model=request.model,
            prompt_tokens=0,
            completion_tokens=0,
        )

    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Ollama service not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen OpenAI-compatible API Server (Ollama Proxy)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--ollama-url", default=OLLAMA_BASE, help="Ollama 服务地址")
    args = parser.parse_args()

    OLLAMA_BASE = args.ollama_url

    print(f"⏳ 连接 Ollama 服务: {OLLAMA_BASE}")
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if resp.status_code == 200:
            print(f"✅ Ollama 服务已连接，模型: {OLLAMA_MODEL}")
        else:
            print(f"❌ Ollama 服务异常: {resp.status_code}")
    except Exception as e:
        print(f"❌ Ollama 服务连接失败: {e}")

    print(f"\n🚀 Qwen API 服务启动: http://{args.host}:{args.port}")
    print(f"   OpenAI 兼容端点: http://{args.host}:{args.port}/v1/chat/completions")
    print(f"   转发到: {OLLAMA_BASE}/api/chat\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
