import sys
import uvicorn

def main():
    if len(sys.argv) < 2:
        print("usage: agentd {serve,migrate}", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "serve":
        uvicorn.run("agentd.app:app", host="0.0.0.0", port=8080)
    elif cmd == "migrate":
        # 迁移逻辑以后再加，先占位
        print("migrate: nothing to do yet")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
