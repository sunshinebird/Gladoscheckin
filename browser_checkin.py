"""Run the official check-in page in a visible Chromium browser."""

import datetime as dt
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from checkin import (
    APIEndpoint,
    CheckinResult,
    CheckinStatus,
    Config,
    LogEmoji,
    PushService,
    Report,
    RunBudget,
    left_days,
    parse_checkin,
    to_int,
)
from logging_config import init_logger, redact


TIMEZONE = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def browser_cookies(raw, domain):
    cookies = []
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies.append({
                "name": name,
                "value": value,
                "url": f"https://{domain}/",
                "secure": True,
            })
    return cookies


def daily_points(data, today=None):
    today = today or dt.datetime.now(TIMEZONE).date()
    for record in data.get("history", []):
        if not isinstance(record, dict) or "checkin" not in str(record.get("business", "")):
            continue
        timestamp = to_int(record.get("time"))
        if timestamp is None:
            continue
        try:
            date = dt.datetime.fromtimestamp(
                timestamp / 1000 if timestamp > 1e12 else timestamp, TIMEZONE
            ).date()
        except (OSError, ValueError, OverflowError):
            continue
        if date == today:
            return to_int(record.get("change"))
    earned = data.get("earned")
    if isinstance(earned, dict):
        for key, value in earned.items():
            try:
                date = dt.datetime.strptime(key, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if date == today:
                return to_int(value)
    return None


class BrowserAccountAPI:
    def __init__(self, context, domain):
        self.context = context
        self.domain = domain

    def _request(self, method, path, data=None):
        url = f"https://{self.domain}{path}"
        if method == "GET":
            response = self.context.request.get(url, max_redirects=0, timeout=30000)
        else:
            response = self.context.request.post(
                url, data=data, max_redirects=0, timeout=30000
            )
        if not response.ok:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: invalid response")
        return payload

    def fetch_status(self):
        return self._request("GET", APIEndpoint.STATUS)

    def get_point_data(self):
        return self._request("GET", APIEndpoint.POINTS)

    def get_points(self):
        return to_int(self.get_point_data().get("points"))

    def exchange(self, plan):
        try:
            payload = self._request("POST", APIEndpoint.EXCHANGE, {"planType": plan})
        except Exception:
            return "兑换未完成，请到站点确认"
        if payload.get("code") == 0:
            return f"兑换成功: {plan}"
        return f"兑换失败: {payload.get('message', '未知错误')}"


def run_account(browser, entry, config, budget):
    domain, days = entry._resolve_domain(config, budget)
    if domain is None or budget.expired():
        return CheckinResult.failure(entry.origin or "未探测")

    options = {"timezone_id": "Asia/Shanghai", "viewport": {"width": 1365, "height": 900}}
    if entry.user_agent:
        options["user_agent"] = entry.user_agent
    context = browser.new_context(**options)
    try:
        context.add_cookies(browser_cookies(entry.cookie, domain))
        page = context.new_page()
        page.goto(f"https://{domain}/console/checkin", wait_until="domcontentloaded", timeout=60000)
        page.bring_to_front()
        api = BrowserAccountAPI(context, domain)
        status = api.fetch_status()
        if status.get("code") != 0:
            raise RuntimeError("Browser session was rejected")
        points_before = api.get_point_data()

        if daily_points(points_before) is not None:
            result = CheckinResult(domain=domain, code=CheckinStatus.REPEAT)
        else:
            button = page.locator("button.ckb")
            if not button.count():
                button = page.get_by_role("button", name=re.compile(r"^(签到|簽到|check[\s-]*in)", re.I))
            # Let the website obtain and submit its own verification token.
            with page.expect_response(
                lambda response: (
                    urlsplit(response.url).path == APIEndpoint.CHECKIN
                    and response.request.method == "POST"
                ),
                timeout=120000,
            ) as pending:
                button.click(timeout=30000)
            result = parse_checkin(
                pending.value.json(), domain,
                lambda emoji, message, force=False: entry.log(domain, emoji, message, force=True),
            )

        result.domain = domain
        result.days = left_days(status) if left_days(status) is not None else days
        points_after = api.get_point_data()
        result.points_total = to_int(points_after.get("points"))
        if result.code is CheckinStatus.SUCCESS and daily_points(points_after) is None:
            page.wait_for_timeout(1000)
            points_after = api.get_point_data()
            result.points_total = to_int(points_after.get("points"))
            if daily_points(points_after) is None:
                result.code = CheckinStatus.FAILURE
                result.note = "签到响应后未发现今日积分入账记录，请确认"
        if result.code in (CheckinStatus.SUCCESS, CheckinStatus.REPEAT):
            result.exchange = entry._apply_exchange(api, config, domain, result)
        entry.result = result
        entry._log_result()
        return result
    finally:
        context.close()


def main():
    from playwright.sync_api import sync_playwright

    init_logger()
    config = Config()
    if not config.accounts:
        report = Report.failed(config.load_error or "未找到有效 Cookie")
    else:
        budget = RunBudget()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                for entry in config.accounts:
                    try:
                        entry.result = run_account(browser, entry, config, budget)
                    except Exception as error:
                        entry.result = CheckinResult.failure(entry.origin or "未探测")
                        entry.result.note = f"浏览器流程失败 ({type(error).__name__})，请检查官网验证状态"
                        entry.log(entry.result.domain, LogEmoji.ERROR, entry.result.note, force=True)
            finally:
                browser.close()
        report = Report(config.accounts)

    logger.info("%s\n%s", report.title, report.render())
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(redact(f"## {report.title}\n\n{report.render('  ' + chr(10))}\n"))
    PushService(config).send(report)
    return 1 if report.has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
