import datetime as dt
import unittest
from unittest.mock import MagicMock, Mock, patch

from browser_checkin import BrowserAccountAPI, TIMEZONE, browser_cookies, daily_points, run_account
from checkin import CookieEntry, CheckinStatus, EXCHANGE_PLANS


class BrowserFlowTests(unittest.TestCase):
    def test_cookies_are_scoped_to_the_account_host(self):
        cookies = browser_cookies("gld:sess=abc==; gld:sess.sig=signature", "glados.one")
        self.assertEqual(cookies[0]["value"], "abc==")
        self.assertTrue(all(cookie["url"] == "https://glados.one/" for cookie in cookies))
        self.assertTrue(all(cookie["secure"] for cookie in cookies))

    def test_midnight_record_uses_beijing_date(self):
        timestamp = dt.datetime(2026, 11, 16, 0, 5, tzinfo=TIMEZONE).timestamp() * 1000
        payload = {"history": [{"business": "checkin", "time": timestamp, "change": 11}]}
        self.assertEqual(daily_points(payload, dt.date(2026, 11, 16)), 11)
        self.assertIsNone(daily_points(payload, dt.date(2026, 11, 15)))

    def test_other_credit_cannot_be_misread_as_checkin(self):
        timestamp = dt.datetime(2026, 11, 16, 10, tzinfo=TIMEZONE).timestamp() * 1000
        payload = {"history": [{"business": "reward", "time": timestamp, "change": 11}]}
        self.assertIsNone(daily_points(payload, dt.date(2026, 11, 16)))

    def test_earned_dictionary_supports_unpadded_dates_and_zero(self):
        self.assertEqual(daily_points({"earned": {"2026-11-6": 0}}, dt.date(2026, 11, 6)), 0)

    def test_exchange_timeout_is_not_retried(self):
        context = Mock()
        context.request.post.side_effect = TimeoutError
        message = BrowserAccountAPI(context, "glados.one").exchange("plan500")
        self.assertIn("确认", message)
        context.request.post.assert_called_once()

    def test_exchange_uses_browser_session_and_does_not_follow_redirects(self):
        context = Mock()
        response = context.request.post.return_value
        response.ok = True
        response.json.return_value = {"code": 0}
        message = BrowserAccountAPI(context, "glados.one").exchange("plan500")
        self.assertEqual(message, "兑换成功: plan500")
        context.request.post.assert_called_once_with(
            "https://glados.one/api/user/exchange", data={"planType": "plan500"},
            max_redirects=0, timeout=30000,
        )

    def run_first_checkin(self, response, credited):
        browser = MagicMock()
        page = browser.new_context.return_value.new_page.return_value
        page.expect_response.return_value.__enter__.return_value.value.json.return_value = response
        entry = CookieEntry.build(1, "gld:sess=test", origin="glados.one")
        entry._resolve_domain = Mock(return_value=("glados.one", 795))
        config = Mock(exchange_plan="plan500", exchange_plans=EXCHANGE_PLANS)
        api = Mock()
        api.fetch_status.return_value = {"code": 0, "data": {"leftDays": 795}}
        today = dt.datetime.now(TIMEZONE).date().isoformat()
        after = {"points": 264, "earned": {today: 11}} if credited else {"points": 253}
        api.get_point_data.side_effect = [{"points": 253}, after, after]
        with patch("browser_checkin.BrowserAccountAPI", return_value=api):
            result = run_account(browser, entry, config, Mock(expired=Mock(return_value=False)))
        return result, api

    def test_first_checkin_requires_real_credit_before_success(self):
        result, api = self.run_first_checkin({"code": 0, "points": 11, "repeated": False}, True)
        self.assertEqual(result.code, CheckinStatus.SUCCESS)
        self.assertEqual(result.points_total, 264)
        api.exchange.assert_not_called()

    def test_success_response_without_daily_credit_is_a_failure(self):
        result, api = self.run_first_checkin({"code": 0, "points": 11, "repeated": False}, False)
        self.assertEqual(result.code, CheckinStatus.FAILURE)
        api.exchange.assert_not_called()

    def test_cloudflare_rejection_is_never_reported_as_success(self):
        result, api = self.run_first_checkin(
            {"code": 5, "message": "Cloudflare verification failed"}, False
        )
        self.assertEqual(result.code, CheckinStatus.FAILURE)
        api.exchange.assert_not_called()


if __name__ == "__main__":
    unittest.main()
