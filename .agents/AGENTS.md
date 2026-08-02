# LinkedIn Agent Project Memory

## Deployed Architecture
* **FastAPI Server**: Deployed on Render at `https://linkedin-agent-6gu6.onrender.com`.
* **LinkedIn Token Persistence**: Saved permanently as `LINKEDIN_TOKEN_JSON` in the Render environment variables dashboard.
* **Auto-update configuration**: `RENDER_API_KEY` and `RENDER_SERVICE_ID` are configured in Render environment variables so the app can automatically update the token when re-authenticating.

## Pending Approvals & Post Generation
* **Local Post Generation**: Writing approvals locally requires using `git add -f pending_approvals.json` and pushing to GitHub so the Render server can access the tokens.
* **Best Practice**: Trigger post generation directly from the Render dashboard (e.g., "Write Your Own Post" or scheduler) so that tokens are generated directly on the server, avoiding any Git commit/sync issues.
