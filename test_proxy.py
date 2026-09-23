"""Smoke test for the Codex proxy. Run: python test_proxy.py"""
import asyncio, sys, json, httpx

BASE = "http://127.0.0.1:8000"

async def test_health():
    print("=== /health ===")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        print(f"  status={r.status_code}")
        if r.status_code == 200:
            print(f"  {r.json()}"); return True
        return False

async def test_models():
    print("\n=== /v1/models ===")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/v1/models")
        print(f"  status={r.status_code}")
        try:
            data = r.json()
            print(f"  models={[m.get('id') for m in data.get('data', [])]}")
        except Exception:
            print(f"  {r.text[:200]}")

async def test_streaming():
    print("\n=== streaming chat ===")
    body = {"model": "test", "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply with exactly the word: pong"}]}], "stream": True}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            async with c.stream("POST", f"{BASE}/v1/responses", json=body) as r:
                print(f"  status={r.status_code}")
                if r.status_code != 200:
                    print(f"  body: {await r.aread()!r}"); return
                events = []
                async for line in r.aiter_lines():
                    if line.startswith("event: "): events.append(line[7:])
                print(f"  events: {events}")
                print("  " + ("OK streaming chat" if "response.completed" in events else "FAIL missing response.completed"))
        except Exception as e:
            print(f"  ERROR: {e}")

async def test_tools():
    print("\n=== tool calling (THE CRITICAL ONE) ===")
    body = {
        "model": "test",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "What's the weather in Tokyo? Use the get_weather tool."}]}],
        "tools": [{"type": "function", "name": "get_weather", "description": "Get current weather for a city",
                   "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            async with c.stream("POST", f"{BASE}/v1/responses", json=body) as r:
                print(f"  status={r.status_code}")
                if r.status_code != 200:
                    print(f"  body: {await r.aread()!r}"); return
                events, tool_calls, text_chunks = [], [], []
                async for line in r.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line[7:])
                    elif line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "response.output_item.added":
                                item = data.get("item", {})
                                if item.get("type") == "function_call":
                                    tool_calls.append({"name": item.get("name"), "args": ""})
                            elif data.get("type") == "response.function_call_arguments.delta":
                                if tool_calls: tool_calls[-1]["args"] += data.get("delta", "")
                            elif data.get("type") == "response.output_text.delta":
                                text_chunks.append(data.get("delta", ""))
                        except Exception: pass
                print(f"  events: {events}")
                print(f"  text: {''.join(text_chunks)[:100]!r}")
                print(f"  tool calls: {tool_calls}")
                fc_added = "response.output_item.added" in events
                fc_args  = "response.function_call_arguments.delta" in events
                if fc_added and fc_args and any(tc.get("name") == "get_weather" for tc in tool_calls):
                    print("  OK tool calling works")
                else:
                    print("  FAIL tool calling did NOT work -- this is the 'only chat works' symptom")
        except Exception as e:
            print(f"  ERROR: {e}")

async def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"Testing proxy at {BASE}")
    print("=" * 60)
    if not await test_health():
        print("\nHealth failed -- is the proxy running? start.bat")
        sys.exit(1)
    if only != "--stream-only": await test_models()
    if only != "--tools-only":  await test_streaming()
    if only != "--stream-only": await test_tools()
    print("\n" + "=" * 60)
    print("Done. Check proxy.log for details.")

if __name__ == "__main__":
    asyncio.run(main())