# Copilot Seat Team Sync

This command-line script retrieves every assigned GitHub Copilot seat in one organization and, after confirmation, submits a request to add every listed user to a configured GitHub team.

# Quickstart

1. Obtain classic personal access token: <img width="946" height="669" alt="image" src="https://github.com/user-attachments/assets/5f236481-b5f0-4073-9ee9-888e800d6a19" />
2. Rename `.env.sample` to `.env` and set token with `GITHUB_TOKEN`
3. Run `python sync_copilot_seats.py`
4. Interact with prompts, asking for confirmation



## Detailed Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and supply the values:

   ```dotenv
   GITHUB_TOKEN=github_pat_your_token
   GITHUB_ORG=your-organization
   GITHUB_TEAM_NAME=Your Team Display Name
   ```

`GITHUB_TEAM_NAME` is the team display name, not its API slug. It must exactly match one team in the configured organization. The script rejects missing and ambiguous names before changing memberships.

## GitHub Access

Create a fine-grained personal access token for the target organization. Grant the token the organization permissions required by GitHub to read Copilot billing seats and write team memberships. Access can also require organization-owner or team-maintainer privileges, SSO authorization, or OAuth/PAT approval under your organization's policy.

GitHub permission naming and availability can vary by organization and account type. Confirm the token can use these endpoints before a production run:

- `GET /orgs/{org}/copilot/billing/seats`
- `GET /orgs/{org}/teams`
- `PUT /orgs/{org}/teams/{team_slug}/memberships/{username}`

## Run

```powershell
python sync_copilot_seats.py
```

The script asks:

```text
<number> users with Copilot seat found. Print list? [N/y]
Add <number> users to team <team name>? [Y/n]
```

The first prompt defaults to `No`; the second defaults to `Yes`. A declined add prompt exits without resolving the team or sending any membership request.

After approval, it submits one membership request for every occupied Copilot seat. It deliberately does not first remove people already on the team or pre-filter existing members. GitHub may treat existing memberships as successful no-op updates. Per-user failures are printed, the remaining users continue processing, and the final summary reports attempted, successful, and failed requests.

## Test

```powershell
python -m unittest discover -s tests -v
```
