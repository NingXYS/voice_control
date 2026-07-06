#!/usr/bin/env python3
"""
Qwen2.5-7B-GGUF → OpenAI 兼容 API 服务
供 Dify 作为模型提供商对接，使 Dify 能调用本地 Qwen 模型。
使用 llama-cpp-python 加载 GGUF 格式模型，支持 CPU/GPU 推理。
"""
import os
import sys
import json
import time
import warnings
import argparse
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore")

# ==================== 模型加载 ====================
MODEL_PATH = os.environ.get("QWEN_MODEL_PATH", "/home/ning/model/qwen2-7b-instruct-q5_k_m.gguf")
N_GPU_LAYERS = int(os.environ.get("N_GPU_LAYERS", "-1"))  # -1 表示全部层使用 GPU
N_CTX = int(os.environ.get("N_CTX", "2048"))
N_THREADS = int(os.environ.get("N_THREADS", "8"))

app = FastAPI(title="Qwen Local API")

llm = None


def load_model():
    global llm
    print(f"⏳ 加载 Qwen2.5-GGUF 模型: {MODEL_PATH}")
    from llama_cpp import Llama

    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        n_gpu_layers=N_GPU_LAYERS,
        verbose=False,
    )
    print(f"✅ Qwen 模型已加载 (GPU layers: {N_GPU_LAYERS}, Context: {N_CTX})，等待请求...")


# ==================== OpenAI 兼容数据结构 ====================
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "qwen2.5"
    messages: List[ChatMessage]
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 512
    stream: bool = False


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]


# ==================== API 端点 ====================
@app.get("/health")
@app.get("/v1/health")
async def health():
    return {"status": "ok", "model_loaded": llm is not None}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "qwen2.5", "object": "model", "created": int(time.time())}]
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        # 构造 messages
        messages = []
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        # 使用 llama-cpp-python 进行推理
        response = llm.create_chat_completion(
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
        )

        # 提取响应内容
        response_text = response["choices"][0]["message"]["content"]

        # 构造 OpenAI 格式响应
        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[{
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }],
            usage={
                "prompt_tokens": response["usage"]["prompt_tokens"],
                "completion_tokens": response["usage"]["completion_tokens"],
                "total_tokens": response["usage"]["total_tokens"],
            },
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 启动 ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen OpenAI-compatible API Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--model-path", default=MODEL_PATH, help="模型路径")
    args = parser.parse_args()

    MODEL_PATH = args.model_path
    load_model()

    print(f"\n🚀 Qwen API 服务启动: http://{args.host}:{args.port}")
    print(f"   OpenAI 兼容端点: http://{args.host}:{args.port}/v1/chat/completions")
    print("   在 Dify 中配置为「OpenAI API Compatible」提供商即可对接\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
