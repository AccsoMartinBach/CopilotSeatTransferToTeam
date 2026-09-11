import os
import unittest
from unittest.mock import Mock, patch

import requests

from sync_copilot_seats import (
    ConfigurationError,
    GitHubApiError,
    GitHubClient,
    Settings,
    main,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self._payload


class GitHubClientTests(unittest.TestCase):
    def test_get_copilot_seat_logins_collects_all_pages_and_unique_assignees(self):
        session = Mock()
        first_page = [
            {"assignee": {"login": "ada"}},
            {"assignee": None},
            {"assignee": {"login": "ada"}},
        ] + [{"assignee": {"login": f"user-{index}"}} for index in range(97)]
        second_page = [{"assignee": {"login": "grace"}}]
        session.get.side_effect = [
            FakeResponse(payload={"seats": first_page}),
            FakeResponse(payload={"seats": second_page}),
        ]

        client = GitHubClient("token", session=session)

        logins = client.get_copilot_seat_logins("octo-org")

        self.assertEqual(logins[0], "ada")
        self.assertEqual(logins[-1], "grace")
        self.assertEqual(len(logins), 100)
        self.assertEqual(session.get.call_count, 2)

    def test_get_team_slug_requires_one_exact_display_name_match(self):
        session = Mock()
        session.get.return_value = FakeResponse(
            payload=[
                {"name": "Platform", "slug": "platform"},
                {"name": "Other", "slug": "other"},
            ]
        )
        client = GitHubClient("token", session=session)

        self.assertEqual(client.get_team_slug("octo-org", "Platform"), "platform")
        with self.assertRaisesRegex(GitHubApiError, "No team named"):
            client.get_team_slug("octo-org", "Missing")

    def test_add_user_to_team_uses_resolved_slug_and_member_role(self):
        session = Mock()
        session.put.return_value = FakeResponse(status_code=200)
        client = GitHubClient("token", session=session)

        client.add_user_to_team("octo-org", "platform", "ada")

        session.put.assert_called_once_with(
            "https://api.github.com/orgs/octo-org/teams/platform/memberships/ada",
            json={"role": "member"},
            timeout=30,
        )


class MainTests(unittest.TestCase):
    def test_main_does_not_write_when_addition_is_declined(self):
        client = Mock()
        client.get_copilot_seat_logins.return_value = ["ada", "grace"]
        outputs = []

        with patch("sync_copilot_seats.load_settings", return_value=Settings("token", "octo-org", "Platform")):
            exit_code = main(
                input_fn=Mock(side_effect=["", "n"]),
                output=outputs.append,
                client_factory=Mock(return_value=client),
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Aborted. No users were added.", outputs)
        client.get_team_slug.assert_not_called()
        client.add_user_to_team.assert_not_called()

    def test_main_prints_list_and_adds_every_seat_user_by_default(self):
        client = Mock()
        client.get_copilot_seat_logins.return_value = ["ada", "grace"]
        client.get_team_slug.return_value = "platform"
        outputs = []

        with patch("sync_copilot_seats.load_settings", return_value=Settings("token", "octo-org", "Platform")):
            exit_code = main(
                input_fn=Mock(side_effect=["y", ""]),
                output=outputs.append,
                client_factory=Mock(return_value=client),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(outputs[:2], ["ada", "grace"])
        client.add_user_to_team.assert_any_call("octo-org", "platform", "ada")
        client.add_user_to_team.assert_any_call("octo-org", "platform", "grace")
        self.assertIn("Completed: 2 attempted, 2 succeeded, 0 failed.", outputs)

    def test_main_reports_partial_membership_failures_and_continues(self):
        client = Mock()
        client.get_copilot_seat_logins.return_value = ["ada", "grace"]
        client.get_team_slug.return_value = "platform"
        client.add_user_to_team.side_effect = [GitHubApiError("denied"), None]
        outputs = []

        with patch("sync_copilot_seats.load_settings", return_value=Settings("token", "octo-org", "Platform")):
            exit_code = main(
                input_fn=Mock(side_effect=["n", "y"]),
                output=outputs.append,
                client_factory=Mock(return_value=client),
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Failed to add ada: denied", outputs)
        self.assertIn("Added grace.", outputs)
        self.assertIn("Completed: 2 attempted, 1 succeeded, 1 failed.", outputs)

    def test_main_returns_configuration_error_without_api_calls(self):
        client_factory = Mock()
        outputs = []

        with patch("sync_copilot_seats.load_settings", side_effect=ConfigurationError("Missing required .env value(s): GITHUB_TOKEN")):
            exit_code = main(output=outputs.append, client_factory=client_factory)

        self.assertEqual(exit_code, 1)
        self.assertEqual(outputs, ["Error: Missing required .env value(s): GITHUB_TOKEN"])
        client_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()