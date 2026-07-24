# Five-minute demo script

1. Show `accounts/`, copy `template.md` to a fourth account, and run
   `python run.py --list-accounts` to prove no Python change is required.
2. Run `python run.py --account responsible-ai-lab --topic "..."`; point out
   run ID, score, rewrite count, terminal state, and SQLite path in the CLI.
3. Open Streamlit and inspect the same run under Run history and Scores & usage.
4. Load a saved fail-after-two snapshot, edit the queued post, approve with an
   operator and mandatory note, then show the immutable audit and mock receipt.
5. Show a rejected state being blocked, the scheduled workflow, and the
   evaluation JSON's same-topic output comparison and per-account usage.

Use one commit and one SQLite snapshot throughout. Do not display `.env`,
Actions Secrets, request headers, or provider tokens.
