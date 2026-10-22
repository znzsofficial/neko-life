"""CI discovery guard: real SDK and every safety/ecosystem test must execute."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))

    def ids(group):
        for item in group:
            if isinstance(item, unittest.TestSuite):
                yield from ids(item)
            else:
                yield item.id()

    discovered = set(ids(suite))
    required = {
        "tests.test_authorization.AuthorizationTests.test_real_sdk_unwraps_host_envelope_and_declared_readonly_capabilities",
        "tests.test_authorization.AuthorizationTests.test_no_cross_request_cache_and_revoke_during_lookup",
        "tests.test_authorization.AuthorizationTests.test_same_number_group_private_and_platform_are_not_interchangeable",
        "tests.test_authorization.AuthorizationTests.test_permission_reload_keeps_schedule_tasks_and_budget_zero",
        "tests.test_ecosystem.EcosystemTests.test_life_scene_reaches_signed_draw_execution_once",
        "tests.test_ecosystem.EcosystemTests.test_draw_and_tts_hooks_preserve_life_context_without_spending",
        "tests.test_ecosystem.EcosystemTests.test_authenticated_exploration_and_share_receipt_without_network_or_qq",
        "tests.test_focus.FocusTests.test_only_route_members_and_existing_context_authorization_receive_labeled_reference",
        "tests.test_focus.FocusTests.test_revocation_before_return_discards_all_group_references",
    }
    if not required <= discovered:
        raise SystemExit("Critical test discovery missing: " + ", ".join(sorted(required - discovered)))
    if suite.countTestCases() < 87:
        raise SystemExit("Test discovery shrank below the reviewed safety baseline (87).")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print("CI requires all SDK, authorization and pinned ecosystem tests; skips are failures.")
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)


if __name__ == "__main__":
    main()
