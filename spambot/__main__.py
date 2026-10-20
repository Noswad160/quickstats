"""spambot command line.

  python -m spambot serve [--port 8080]      run the Twilio web server
  python -m spambot chat [--persona earl]    talk to the bot in your terminal (you play the caller)
"""
import argparse
import asyncio
import logging

from . import config, personas


async def chat(persona_key: str, mode: str | None) -> None:
    from .call import Call, Digits, Hangup, Speak
    from .llm import ClaudeLLM

    s = config.load()
    call = Call(llm=ClaudeLLM(s.model, s.effort), owner_name=s.owner_name,
                persona=personas.PERSONAS[persona_key])
    if mode:
        call.mode = mode
    call.greeting_spoken("Hello?")
    print("Bot: Hello?   (you're the caller; Ctrl-D to hang up)")
    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            break
        if not line:
            continue
        before = call.mode
        print("Bot: ", end="", flush=True)
        async for ev in call.respond(line):
            if isinstance(ev, Speak):
                print(ev.text, end="", flush=True)
            elif isinstance(ev, Digits):
                print(f" [presses {ev.digits}] ", end="", flush=True)
            elif isinstance(ev, Hangup):
                print(" [hangs up]", end="")
        print()
        if call.mode != before:
            print(f"   (screened as {call.mode}: {call.verdict_reason})")
    print(f"\nCall lasted {call.seconds / 60:.1f} minutes, mode {call.mode}.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="spambot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8080)
    ch = sub.add_parser("chat")
    ch.add_argument("--persona", default=config.load().persona, choices=sorted(personas.PERSONAS))
    ch.add_argument("--mode", choices=["spam", "legit"], help="skip screening and start in this mode")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(), host=args.host, port=args.port)
    else:
        asyncio.run(chat(args.persona, args.mode))


if __name__ == "__main__":
    main()
