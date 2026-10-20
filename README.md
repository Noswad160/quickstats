# spambot — waste scammers' time, not yours

Spam calls to your iPhone get forwarded to a Twilio number. An AI character answers, figures out
whether the caller is spam, and then either:

- **spam:** keeps them talking for as long as possible as Earl (82, hard of hearing, endless stories),
  Linda (constantly distracted) or Gerald (must verify everything). It presses "1" to get past
  robocall menus to a real person, and never gives out real information.
- **a real caller:** says it's your automated assistant, takes a message, and texts it to you.

Your phone is never tied up: a forwarded call leaves your line, so you can keep using it normally.

```
caller ──> your iPhone (silenced / declined) ──carrier forwarding──> Twilio number
                                                                        │ speech <-> text (ConversationRelay)
                                                                        ▼
                                                              this server ──> Claude
```

## Try it in your terminal first

```bash
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m spambot chat                    # you play the caller; it screens you first
python -m spambot chat --mode spam --persona gerald
```

## Run it for real

1. **Twilio:** create an account, buy a voice-capable number (about $1.15/month), and note the
   Account SID and Auth Token. ConversationRelay may need Twilio's AI features addendum accepted in
   the Console (Voice settings) before it works.
2. **Deploy this server** somewhere with a public HTTPS URL (Fly.io, Render, Railway, or any VPS),
   using the `Dockerfile`. Set the variables from `.env.example`. Mount a volume at `/data` so the call
   log survives restarts. For a quick local test, `ngrok http 8080` works too.
3. **Point the number at it:** in the Twilio Console, number → Voice → "A call comes in" → Webhook,
   `POST https://YOUR-URL/voice`.
4. **Call your Twilio number** from your phone. You should hear "Hello?" Say you're calling about a
   car warranty and meet Earl.

## Send spam calls from your iPhone

1. **Turn on conditional call forwarding to your Twilio number.** This replaces voicemail for
   unanswered, declined and busy calls. Dial it from the Phone app and press call:
   - AT&T or T-Mobile: `**004*1XXXXXXXXXX#` (your Twilio number). Undo with `##004#`.
   - Verizon: `*71` followed by the Twilio number. Undo with `*73`.
   - Other carriers: search "<carrier> conditional call forwarding".
2. **Silence unknown callers:** Settings → Apps → Phone → Screen Unknown Callers → **Silence**
   (on older iOS: Settings → Phone → Silence Unknown Callers). Calls from numbers not in your contacts
   go straight to forwarding without ringing.
3. **Decline anything else that looks like spam** (press the side button twice); it gets forwarded too.

Because forwarding replaces voicemail, everyone you miss reaches the bot. Real callers get the polite
message-taker and you get a text; add people you never want screened to `ALLOWLIST`. Your carrier
voicemail stops receiving messages while forwarding is on.

## Costs and limits

Each forwarded minute costs Twilio voice time plus ConversationRelay plus Claude: very roughly
$0.10/min with `claude-opus-5-5`, less with `claude-haiku-5-5`. A 20-minute scammer is a dollar or two.
`MAX_CALL_MINUTES` (default 30) ends any one call; `DAILY_MINUTES_CAP` (default 180) declines new
calls for the rest of the day.

## Recording and transcripts

No audio is recorded. With `SAVE_TRANSCRIPTS=true` the server keeps a text transcript of each call
(`GET /calls` with `Authorization: Bearer $ADMIN_TOKEN`). Arkansas allows one-party consent, but
callers in all-party-consent states (California, Florida, Washington and others) may be covered by
stricter rules; set `SAVE_TRANSCRIPTS=false` if that matters to you.

## Layout

- `spambot/call.py`: one call: screening, modes, interruptions, keypad presses
- `spambot/personas.py`: the characters and their ground rules
- `spambot/llm.py`: Claude calls (streamed replies, screening, message summaries)
- `spambot/relay.py`: Twilio ConversationRelay websocket
- `spambot/app.py`: web server (webhook, websocket, call log)
