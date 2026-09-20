# Project: Letters To The Dead
A RAG system: it answers questions using only retrieved passages from
Marcus Aurelius's Meditations (public-domain translation), and cites them.
Pipeline: ingest -> index -> retrieve -> answer. Python.

# How to help me
- I want to understand every line. Explain the why before showing code.
- Work in small steps. Propose one step, wait for my go-ahead, then do it.
- Never edit files without asking first.
- Before running anything, ask me to predict what it will do.
- After each step, ask me one question to check I understood.
- Keep code simple and readable over clever.

# Saving tokens
- Read only the files I name. Ask before opening others.
- Cap output of unknown commands: COMMAND 2>&1 | head -c 4000
- Keep replies short. No long summaries after each step.