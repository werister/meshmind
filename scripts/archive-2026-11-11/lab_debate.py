"""Tiny 2-model debate demo on the mini lab (1 round each side, short)."""
import json
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TOPIC = "Should tiny CPU-only models be allowed to vote in an AI safety gate?"


def chat(model, system, user, num_predict=70, timeout=300):
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps({
            "model": model, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"temperature": 0.7, "num_predict": num_predict},
        }).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body.get("message", {}).get("content", ""), body.get("eval_count", 0)


def main():
    total = 0
    print(f"TOPIC: {TOPIC}\n", flush=True)
    pro, t = chat("gemma3:1b-it-q4_K_M",
                  "You argue FOR the motion in at most 3 short sentences.",
                  f"Motion: {TOPIC} Give your opening argument.")
    total += t
    print(f"--- FOR (gemma3:1b) ---\n{pro}\n", flush=True)
    con, t = chat("qwen2.5:0.5b",
                  "You argue AGAINST the motion in at most 3 short sentences.",
                  f"Motion: {TOPIC} Give your opening argument.")
    total += t
    print(f"--- AGAINST (qwen2.5:0.5b) ---\n{con}\n", flush=True)
    rebut, t = chat("granite3.1-moe:3b",
                    "You are the judge. Read both arguments and give a verdict in at most 3 short sentences.",
                    f"Motion: {TOPIC}\nFOR: {pro}\nAGAINST: {con}\nWho won and why?")
    total += t
    print(f"--- JUDGE (granite3.1-moe:3b) ---\n{rebut}\n", flush=True)
    print(f"DEBATE_EVAL_TOKENS: {total}")


if __name__ == "__main__":
    main()
