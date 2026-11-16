import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import checkin
from logging_config import redact


COOKIE = "gld:sess=test-session; gld:sess.sig=test-signature"


class CheckinResponseTests(unittest.TestCase):
    def parse(self, payload):
        return checkin.parse_checkin(payload, "glados.one", Mock())

    def test_new_response_does_not_depend_on_old_message(self):
        result = self.parse({"code": 0, "repeated": False, "points": 6, "message": "OK"})
        self.assertEqual(result.code, checkin.CheckinStatus.SUCCESS)
        self.assertEqual(result.points, 6)

    def test_already_checked_in_is_a_normal_result(self):
        result = self.parse({"code": 0, "repeated": True, "points": 6})
        self.assertEqual(result.code, checkin.CheckinStatus.REPEAT)
        self.assertEqual(result.points, 0)

    def test_expired_session_cannot_be_misread_as_already_checked_in(self):
        result = self.parse({"code": -2, "repeated": True, "checkedIn": True})
        self.assertEqual(result.code, checkin.CheckinStatus.FAILURE)

    def test_boolean_is_not_a_valid_response_code(self):
        self.assertEqual(self.parse({"code": False}).code, checkin.CheckinStatus.FAILURE)

    def test_wrong_domain_with_zero_code_is_rejected(self):
        result = self.parse({"code": 0, "message": "please checkin via https://glados.one"})
        self.assertEqual(result.code, checkin.CheckinStatus.FAILURE)

    def test_legacy_cookie_remains_compatible_and_deduplicated(self):
        accounts = checkin.Accounts.parse(f"{COOKIE}&{COOKIE}")
        self.assertEqual(len(accounts), 1)

    def test_unrelated_domain_cannot_receive_session_cookie(self):
        self.assertEqual(checkin.normalize_origin("https://example.com"), "")
        self.assertEqual(checkin.normalize_origin("https://glados.one/console/checkin"), "glados.one")


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.account = checkin.CookieEntry.build(1, COOKIE)
        self.config = Mock(exchange_plan="plan500", exchange_plans=checkin.EXCHANGE_PLANS)
        self.api = Mock()
        self.api.checkin.return_value = checkin.CheckinResult(code=checkin.CheckinStatus.REPEAT)

    def run_account(self):
        return self.account._sign_in(self.api, "glados.one", 796, self.config)

    def test_insufficient_points_are_preserved_without_exchange_request(self):
        self.api.get_points.return_value = 253
        result = self.run_account()
        self.api.exchange.assert_not_called()
        self.assertFalse(result.exchange_failed)
        self.assertEqual(result.points_total, 253)

    def test_unknown_balance_cannot_trigger_exchange(self):
        self.api.get_points.return_value = None
        result = self.run_account()
        self.api.exchange.assert_not_called()
        self.assertTrue(result.exchange_failed)

    def test_successful_exchange_refreshes_actual_balance_and_days(self):
        self.api.get_points.side_effect = [506, 6]
        self.api.exchange.return_value = "兑换成功: plan500"
        self.api.fetch_status.return_value = {"code": 0, "data": {"leftDays": "896.9"}}
        result = self.run_account()
        self.api.exchange.assert_called_once_with("plan500")
        self.assertEqual(result.points_total, 6)
        self.assertEqual(result.days, 896)
        self.assertFalse(result.exchange_failed)

    def test_ambiguous_exchange_is_not_replayed(self):
        self.api.get_points.return_value = 506
        self.api.exchange.return_value = "兑换未完成，请到站点确认"
        result = self.run_account()
        self.api.exchange.assert_called_once_with("plan500")
        self.assertTrue(result.exchange_failed)

    def test_failed_post_exchange_read_is_reported_for_verification(self):
        self.api.get_points.side_effect = [506, None]
        self.api.exchange.return_value = "兑换成功: plan500"
        self.api.fetch_status.return_value = None
        result = self.run_account()
        self.api.exchange.assert_called_once_with("plan500")
        self.assertTrue(result.exchange_failed)
        self.assertIsNone(result.days)

    def test_failed_checkin_cannot_spend_points(self):
        self.api.checkin.return_value = checkin.CheckinResult.failure("glados.one")
        self.api.get_points.return_value = 506
        self.run_account()
        self.api.exchange.assert_not_called()

    def test_exchange_network_timeout_uses_no_retry_session(self):
        with checkin.API("glados.one", COOKIE) as api:
            with patch.object(api._no_retry_session, "post", side_effect=requests.Timeout):
                with patch.object(api.session, "post") as retry_post:
                    message = api.exchange("plan500")
                    retry_post.assert_not_called()
        self.assertIn("确认", message)


class FailureReportingTests(unittest.TestCase):
    def report(self, result):
        account = checkin.CookieEntry.build(1, COOKIE)
        account.result = result
        return checkin.Report(checkin.Accounts([account]))

    def test_repeat_and_insufficient_points_do_not_fail_workflow(self):
        result = checkin.CheckinResult(code=checkin.CheckinStatus.REPEAT)
        self.assertFalse(self.report(result).has_failures)

    def test_failed_exchange_fails_workflow_even_after_good_checkin(self):
        result = checkin.CheckinResult(code=checkin.CheckinStatus.SUCCESS, exchange_failed=True)
        self.assertTrue(self.report(result).has_failures)

    def test_business_failure_sets_nonzero_exit_and_writes_summary(self):
        report = self.report(checkin.CheckinResult.failure("glados.one"))
        config = Mock(accounts=checkin.Accounts(report.entries), load_error="")
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with patch("checkin.Config", return_value=config):
                with patch("checkin.CheckinRunner") as runner:
                    runner.return_value.run.return_value = report
                    with patch("checkin.PushService"), patch.dict(
                        checkin.os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}, clear=True
                    ):
                        with self.assertRaises(SystemExit) as error:
                            checkin.main()
            self.assertEqual(error.exception.code, 1)
            self.assertIn("签到失败", summary_path.read_text(encoding="utf-8"))

    def test_session_fields_are_redacted(self):
        text = redact(COOKIE)
        self.assertNotIn("test-session", text)
        self.assertNotIn("test-signature", text)


if __name__ == "__main__":
    unittest.main()
