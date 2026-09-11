"""Add GitHub Copilot seat holders to a configured organization team."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable, Iterable

import requests
from dotenv import load_dotenv

API_URL = "https://api.github.com"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 30


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing."""


class GitHubApiError(RuntimeError):
    """Raised when GitHub returns an unsuccessful API response."""


@dataclass(frozen=True)
class Settings:
    token: str
    organization: str
    team_name: str


def load_settings() -> Settings:
    """Load required configuration from the local .env file and environment."""
    load_dotenv()
    values = {
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "").strip(),
        "GITHUB_ORG": os.getenv("GITHUB_ORG", "").strip(),
        "GITHUB_TEAM_NAME": os.getenv("GITHUB_TEAM_NAME", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(f"Missing required .env value(s): {', '.join(missing)}")

    return Settings(
        token=values["GITHUB_TOKEN"],
        organization=values["GITHUB_ORG"],
        team_name=values["GITHUB_TEAM_NAME"],
    )


class GitHubClient:
    """Minimal GitHub REST client for Copilot seat and team operations."""

    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def get_copilot_seat_logins(self, organization: str) -> list[str]:
        """Return ordered, unique logins for all assigned Copilot seats."""
        seats = self._get_all_pages(f"/orgs/{organization}/copilot/billing/seats", "seats")
        seen_logins: set[str] = set()
        logins: list[str] = []
        for seat in seats:
            assignee = seat.get("assignee") or {}
            login = assignee.get("login")
            if login and login not in seen_logins:
                seen_logins.add(login)
                logins.append(login)
        return logins

    def get_team_slug(self, organization: str, team_name: str) -> str:
        """Resolve one exact team display name to its GitHub API slug."""
        teams = self._get_all_pages(f"/orgs/{organization}/teams")
        matches = [team for team in teams if team.get("name") == team_name]
        if not matches:
            raise GitHubApiError(
                f"No team named {team_name!r} was found in organization {organization!r}."
            )
        if len(matches) > 1:
            raise GitHubApiError(
                f"More than one team named {team_name!r} was found in organization {organization!r}. "
                "Use a unique display name."
            )

        slug = matches[0].get("slug")
        if not slug:
            raise GitHubApiError(f"Team {team_name!r} did not include a usable slug.")
        return slug

    def add_user_to_team(self, organization: str, team_slug: str, username: str) -> None:
        """Request member access for one user in an organization team."""
        response = self.session.put(
            f"{API_URL}/orgs/{organization}/teams/{team_slug}/memberships/{username}",
            json={"role": "member"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_error(response)

    def _get_all_pages(self, path: str, item_key: str | None = None) -> list[dict]:
        page = 1
        items: list[dict] = []
        while True:
            response = self.session.get(
                f"{API_URL}{path}",
                params={"per_page": PER_PAGE, "page": page},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            self._raise_for_error(response)
            payload = response.json()
            page_items = payload.get(item_key, []) if item_key else payload
            if not isinstance(page_items, list):
                raise GitHubApiError("GitHub returned an unexpected response format.")
            items.extend(page_items)
            if len(page_items) < PER_PAGE:
                return items
            page += 1

    @staticmethod
    def _raise_for_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            message = response.json().get("message", "No further detail provided.")
        except ValueError:
            message = response.text or "No further detail provided."

        status_messages = {
            401: "Authentication failed. Check GITHUB_TOKEN.",
            403: "Access was denied. Check token permissions, organization policy, and SSO authorization.",
            404: "The organization, team, or endpoint was not found.",
            422: "GitHub could not process this request. Check the target user and team configuration.",
            429: "GitHub rate limit reached. Wait before running the script again.",
        }
        detail = status_messages.get(response.status_code, "GitHub API request failed.")
        raise GitHubApiError(f"{detail} HTTP {response.status_code}: {message}")


def is_affirmative(response: str, default: bool) -> bool:
    """Interpret y/yes and n/no responses, retaining the specified default otherwise."""
    normalized = response.strip().lower()
    if normalized in {"y", "yes"}:
        return True
    if normalized in {"n", "no"}:
        return False
    return default


def add_users(
    client: GitHubClient,
    organization: str,
    team_slug: str,
    usernames: Iterable[str],
    output: Callable[[str], None] = print,
) -> tuple[int, int]:
    """Attempt to add every username and return successful and failed counts."""
    succeeded = 0
    failed = 0
    for username in usernames:
        try:
            client.add_user_to_team(organization, team_slug, username)
        except (GitHubApiError, requests.RequestException) as error:
            failed += 1
            output(f"Failed to add {username}: {error}")
        else:
            succeeded += 1
            output(f"Added {username}.")
    return succeeded, failed


def main(
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    client_factory: Callable[[str], GitHubClient] = GitHubClient,
) -> int:
    try:
        settings = load_settings()
        client = client_factory(settings.token)
        usernames = client.get_copilot_seat_logins(settings.organization)

        if is_affirmative(
            input_fn(f"{len(usernames)} users with Copilot seat found. Print list? [N/y] "),
            default=False,
        ):
            for username in usernames:
                output(username)

        if not is_affirmative(
            input_fn(f"Add {len(usernames)} users to team {settings.team_name}? [Y/n] "),
            default=True,
        ):
            output("Aborted. No users were added.")
            return 0

        team_slug = client.get_team_slug(settings.organization, settings.team_name)
        succeeded, failed = add_users(client, settings.organization, team_slug, usernames, output)
        output(f"Completed: {len(usernames)} attempted, {succeeded} succeeded, {failed} failed.")
        return 1 if failed else 0
    except (ConfigurationError, GitHubApiError, requests.RequestException) as error:
        output(f"Error: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())