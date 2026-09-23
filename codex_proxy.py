"""
Codex Internal API Proxy
======================
Convert OpenAI Responses API requests (used by Codex CLI / Desktop) into
OpenAI Chat Completions API requests (used by most internal LLM gateways).

Run:
    pip install -r requirements.txt
    # edit .env
    python codex_proxy.py
"""
import os, json, uuid, logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

# ========================== Config ==========================
UPSTREAM_BASE_URL    = os.getenv("UPSTREAM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
UPSTREAM_API_KEY     = os.getenv("UPSTREAM_API_KEY", "")
UPSTREAM_MODEL       = os.getenv("UPSTREAM_MODEL", "gpt-4o")
UPSTREAM_CHAT_PATH   = os.getenv("UPSTREAM_CHAT_PATH", "/chat/completions")
UPSTREAM_MODELS_PATH = os.getenv("UPSTREAM_MODELS_PATH", "/models")
LISTEN_HOST          = os.getenv("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT          = int(os.getenv("LISTEN_PORT", "8000"))
LOG_LEVEL            = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE             = os.getenv("LOG_FILE", "")
REQUEST_LOG          = os.getenv("REQUEST_LOG", "")
DEBUG_DUMP           = os.getenv("DEBUG_DUMP", "false").lower() == "true"
AUTH_HEADER          = os.getenv("AUTH_HEADER") or (f"Bearer {UPSTREAM_API_KEY}" if UPSTREAM_API_KEY else "")
EXTRA_HEADERS = {}
for kv in os.getenv("EXTRA_HEADERS", "").split(";"):
    kv = kv.strip()
    if "=" in kv:
        k, v = kv.split("=", 1)
        EXTRA_HEADERS[k.strip()] = v.strip()

# ========================== Logging ==========================
handlers = [logging.StreamHandler()]
if LOG_FILE:
    handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s", handlers=handlers)
log = logging.getLogger("codex-proxy")
stats = {"requests": 0, "errors": 0, "tool_calls": 0}

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 60)
    log.info("Codex Internal API Proxy starting")
    log.info(f"  Upstream:  {UPSTREAM_BASE_URL}")
    log.info(f"  Model:     {UPSTREAM_MODEL}")
    log.info(f"  Listen:    {LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"  Log level: {LOG_LEVEL}")
    if not UPSTREAM_API_KEY:
        log.warning("UPSTREAM_API_KEY is empty -- upstream calls will fail")
    yield
    log.info("Proxy shutting down. Stats: %s", stats)

app = FastAPI(lifespan=lifespan, title="Codex Internal API Proxy")

# ========================== Responses -> Chat (request) ==========================
def responses_to_chat(body: dict) -> dict:
    chat = {"model": body.get("model") or UPSTREAM_MODEL, "messages": [], "stream": bool(body.get("stream", True))}
    if body.get("instructions"):
        chat["messages"].append({"role": "system", "content": body["instructions"]})
    for item in body.get("input", []):
        role = item.get("role")
        if role == "user":
            content = item.get("content", [])
            if isinstance(content, str):
                chat["messages"].append({"role": "user", "content": content}); continue
            text_parts, image_parts = [], []
            for p in content:
                ptype = p.get("type")
                if ptype in ("input_text", "text") and p.get("text"):
                    text_parts.append(p["text"])
                elif ptype == "input_image":
                    img = p.get("image_url")
                    if isinstance(img, dict): img = img.get("url", "")
                    if img: image_parts.append({"type": "image_url", "image_url": {"url": img}})
            if image_parts:
                parts = ([{"type": "text", "text": "\n".join(text_parts)}] if text_parts else []) + image_parts
                chat["messages"].append({"role": "user", "content": parts})
            else:
                chat["messages"].append({"role": "user", "content": "\n".join(text_parts)})
        elif role == "assistant":
            content = item.get("content", [])
            text_parts, tool_calls = [], []
            if isinstance(content, str):
                text_parts.append(content)
            else:
                for p in content:
                    ptype = p.get("type")
                    if ptype in ("text", "output_text") and p.get("text"):
                        text_parts.append(p["text"])
                    elif ptype in ("reasoning", "thinking"):
                        pass
                    elif ptype in ("tool_call", "function_call"):
                        tool_calls.append({
                            "id": p.get("call_id") or p.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {"name": p.get("name", ""), "arguments": p.get("arguments", "") or ""},
                        })
            msg = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
            if tool_calls: msg["tool_calls"] = tool_calls
            chat["messages"].append(msg)
        elif role == "tool":
            content = item.get("content", [])
            if isinstance(content, list):
                for p in content:
                    chat["messages"].append({"role": "tool", "tool_call_id": p.get("call_id") or p.get("tool_call_id", ""), "content": p.get("output", "") or p.get("content", "")})
            else:
                chat["messages"].append({"role": "tool", "tool_call_id": item.get("call_id") or item.get("tool_call_id", ""), "content": str(content)})
    if body.get("tools"):
        chat_tools = []
        for t in body["tools"]:
            if t.get("type") == "function":
                fn = t.get("function") if isinstance(t.get("function"), dict) else None
                chat_tools.append({"type": "function", "function": {"name": (fn or {}).get("name") or t.get("name"), "description": (fn or {}).get("description") or t.get("description", ""), "parameters": (fn or {}).get("parameters") or t.get("parameters", {})}})
            else:
                chat_tools.append(t)
        chat["tools"] = chat_tools
        chat["parallel_tool_calls"] = body.get("parallel_tool_calls", True)
    tc = body.get("tool_choice")
    if tc in ("auto", "none", "required"):
        chat["tool_choice"] = tc
    elif isinstance(tc, dict):
        if tc.get("type") == "function":
            chat["tool_choice"] = {"type": "function", "function": {"name": tc.get("name") or (tc.get("function") or {}).get("name")}}
    for k in ("temperature", "top_p", "frequency_penalty", "presence_penalty", "stop", "n", "response_format", "seed", "user", "max_tokens", "max_completion_tokens"):
        if k in body: chat[k] = body[k]
    chat.setdefault("temperature", 1.0)
    return chat

# ========================== Chat SSE -> Responses SSE ==========================
async def stream_chat_to_responses(upstream: httpx.Response, model: str, response_id: str) -> AsyncIterator[bytes]:
    def sse(event: str, data: dict) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    fc_ids, fc_idx, args_buf = {}, {}, {}
    next_idx, text_started, usage_info = 0, False, None
    yield sse("response.created", {"type": "response.created", "response": {"id": response_id, "object": "response", "status": "in_progress", "model": model}})
    async for line in upstream.aiter_lines():
        if not line.startswith("data: "): continue
        payload = line[6:]
        if payload.strip() == "[DONE]": break
        try: chunk = json.loads(payload)
        except json.JSONDecodeError: continue
        if chunk.get("usage") and not chunk.get("choices"):
            usage_info = chunk["usage"]; continue
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                if not text_started:
                    yield sse("response.output_item.added", {"type": "response.output_item.added", "output_index": next_idx, "item": {"type": "message", "id": msg_id, "role": "assistant", "status": "in_progress", "content": []}})
                    next_idx += 1; text_started = True
                yield sse("response.output_text.delta", {"type": "response.output_text.delta", "item_id": msg_id, "output_index": 0, "delta": text})
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                if idx not in fc_ids:
                    fc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:24]}"
                    fc_ids[idx] = fc_id; fc_idx[idx] = next_idx; next_idx += 1
                    fn_name = (tc.get("function") or {}).get("name") or ""
                    yield sse("response.output_item.added", {"type": "response.output_item.added", "output_index": fc_idx[idx], "item": {"type": "function_call", "id": f"fc_{uuid.uuid4().hex[:24]}", "call_id": fc_id, "name": fn_name, "arguments": "", "status": "in_progress"}})
                arg_delta = (tc.get("function") or {}).get("arguments", "")
                if arg_delta:
                    args_buf[idx] = args_buf.get(idx, "") + arg_delta
                    yield sse("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": f"fc_{fc_ids[idx]}", "output_index": fc_idx[idx], "delta": arg_delta})
        if chunk.get("usage"): usage_info = chunk["usage"]
    if text_started:
        yield sse("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": {"type": "message", "id": msg_id, "role": "assistant", "status": "completed", "content": []}})
    for idx, args in args_buf.items():
        yield sse("response.output_item.done", {"type": "response.output_item.done", "output_index": fc_idx.get(idx, idx), "item": {"type": "function_call", "id": f"fc_{fc_ids[idx]}", "call_id": fc_ids[idx], "arguments": args, "status": "completed"}})
        stats["tool_calls"] += 1
    completed = {"id": response_id, "object": "response", "status": "completed", "model": model}
    if usage_info:
        completed["usage"] = {"input_tokens": usage_info.get("prompt_tokens", 0), "output_tokens": usage_info.get("completion_tokens", 0), "total_tokens": usage_info.get("total_tokens", 0)}
    yield sse("response.completed", {"type": "response.completed", "response": completed})
    yield b"data: [DONE]\n\n"

# ========================== Non-streaming Chat -> Responses ==========================
def chat_response_to_responses(chat_resp: dict, model: str, response_id: str) -> dict:
    output = []
    for choice in chat_resp.get("choices", []):
        msg = choice.get("message") or {}
        text = msg.get("content") or ""; refusal = msg.get("refusal")
        if refusal:
            output.append({"type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}", "role": "assistant", "status": "completed", "content": [{"type": "refusal", "refusal": refusal}]})
        elif text:
            output.append({"type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]})
        for tc in msg.get("tool_calls") or []:
            output.append({"type": "function_call", "id": f"fc_{uuid.uuid4().hex[:24]}", "call_id": tc.get("id") or f"call_{uuid.uuid4().hex[:24]}", "name": (tc.get("function") or {}).get("name", ""), "arguments": (tc.get("function") or {}).get("arguments", ""), "status": "completed"})
            stats["tool_calls"] += 1
    usage = chat_resp.get("usage") or {}
    return {"id": response_id, "object": "response", "created_at": int(datetime.now().timestamp()), "status": "completed", "model": model, "output": output, "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}}

def upstream_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if AUTH_HEADER: h["Authorization"] = AUTH_HEADER
    h.update(EXTRA_HEADERS)
    return h

# ========================== Endpoints ==========================
@app.get("/health")
async def health():
    return {"status": "ok", "upstream": UPSTREAM_BASE_URL, "model": UPSTREAM_MODEL, "stats": stats}

@app.get("/")
async def root():
    return {"name": "Codex Internal API Proxy", "upstream": UPSTREAM_BASE_URL, "model": UPSTREAM_MODEL, "endpoints": ["GET /health", "POST /v1/responses", "GET /v1/models"]}

@app.post("/v1/responses")
@app.post("/responses")
async def proxy_responses(request: Request):
    stats["requests"] += 1
    rid = f"resp_{uuid.uuid4().hex[:24]}"
    try: body = await request.json()
    except Exception as e:
        stats["errors"] += 1; raise HTTPException(400, f"Invalid JSON: {e}")
    if DEBUG_DUMP and REQUEST_LOG:
        try:
            with open(REQUEST_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n\n=== {rid} ===\n{json.dumps(body, indent=2, ensure_ascii=False)[:8000]}\n")
        except Exception as e: log.warning(f"dump failed: {e}")
    chat_body = responses_to_chat(body)
    stream = chat_body.get("stream", True)
    log.info(f"[{rid}] -> {UPSTREAM_BASE_URL}{UPSTREAM_CHAT_PATH} stream={stream} msgs={len(chat_body['messages'])} tools={len(chat_body.get('tools', []))}")
    if stream:
        async def gen():
            try:
                timeout = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", f"{UPSTREAM_BASE_URL}{UPSTREAM_CHAT_PATH}", json=chat_body, headers=upstream_headers()) as upstream:
                        if upstream.status_code != 200:
                            err = await upstream.aread(); stats["errors"] += 1; log.error(f"[{rid}] upstream {upstream.status_code}: {err[:300]!r}")
                            yield ("event: error\ndata: " + json.dumps({"type": "error", "code": upstream.status_code, "message": f"Upstream {upstream.status_code}: {err.decode(errors='ignore')[:300]}"}, ensure_ascii=False) + "\n\n").encode("utf-8"); return
                        async for chunk in stream_chat_to_responses(upstream, chat_body["model"], rid): yield chunk
            except httpx.RequestError as e:
                stats["errors"] += 1; log.error(f"[{rid}] conn error: {e}")
                yield ("event: error\ndata: " + json.dumps({"type": "error", "message": f"Connection error: {e}"}, ensure_ascii=False) + "\n\n").encode("utf-8")
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    else:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0)) as client:
                resp = await client.post(f"{UPSTREAM_BASE_URL}{UPSTREAM_CHAT_PATH}", json=chat_body, headers=upstream_headers())
                if resp.status_code != 200:
                    stats["errors"] += 1; log.error(f"[{rid}] upstream {resp.status_code}: {resp.text[:300]}"); raise HTTPException(resp.status_code, resp.text)
                return JSONResponse(chat_response_to_responses(resp.json(), chat_body["model"], rid))
        except httpx.HTTPError as e:
            stats["errors"] += 1; log.error(f"[{rid}] upstream err: {e}"); raise HTTPException(502, f"Upstream error: {e}")

@app.get("/v1/models")
@app.get("/models")
async def list_models():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{UPSTREAM_BASE_URL}{UPSTREAM_MODELS_PATH}", headers=upstream_headers())
            if r.status_code == 200: return JSONResponse(r.json())
    except Exception as e: log.debug(f"upstream /models failed: {e}")
    now = int(datetime.now().timestamp())
    return JSONResponse({"object": "list", "data": [{"id": UPSTREAM_MODEL, "object": "model", "created": now, "owned_by": "internal-proxy"}]})

@app.api_route("/{path:path}", methods=["GET", "POST"])
async def passthrough(request: Request, path: str):
    upstream_path = "/" + path
    if path.startswith("v1/"): upstream_path = "/" + path[3:]
    body = await request.body() if request.method == "POST" else None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0)) as client:
            r = await client.request(request.method, f"{UPSTREAM_BASE_URL}{upstream_path}", content=body, headers=upstream_headers())
            ct = r.headers.get("content-type", "")
            if "application/json" in ct: return JSONResponse(r.json(), status_code=r.status_code)
            return JSONResponse({"raw": r.text}, status_code=r.status_code)
    except Exception as e: raise HTTPException(502, f"Upstream error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level=LOG_LEVEL.lower(), access_log=False)