# Five-minute demo script

1. Show `accounts/` and copy `template.md` to an account-4 Markdown file. Run
   `python run.py --list-accounts` to prove no Python change is required.
2. Run one account with `--pipeline full`; point out the shared run ID, Critic
   score, rewrite count, and final workflow state.
3. Run the offline fail-after-two test or open its saved SQLite snapshot. Show
   the item in Streamlit Human review with violations and score history.
4. Edit the content, then approve with an operator and mandatory note. Show the
   immutable actions and revisions, followed by the mock Publisher receipt.
5. Show a rejected/failed state being blocked, token/cost views, the scheduled
   workflow, and the resumable evaluation report.

Use the same release commit and SQLite snapshot for every step. Do not expose
`.env`, Streamlit secrets, request headers, or provider tokens on screen.
