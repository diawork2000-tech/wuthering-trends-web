"""登録済みURLの取得と、Notionの1万件上限を越える読み取りのテスト。

    実行: npm run test:py

ここが「途中までの一覧」を返すと、登録済みの行を未登録と見なして
まるごと再登録する。実際に起きた原因は2つあり、どちらも再現している。
  - 通信が途中で失敗しても、黙ってそこまでの一覧を返していた
  - Notion は1回の問い合わせで1万件までしか返さず、その先が見えなかった
結果、広告が1回あたり約370件ずつ重複登録され、同じ動画が最大6回入った。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notion_utils  # noqa: E402
import trend_collector  # noqa: E402


class FakeNotion:
    """本物の Notion と同じく、1回の問い合わせを cap 件で黙って打ち切る偽物。"""

    def __init__(self, rows, cap, fail_on_call=None):
        self.rows = rows
        self.cap = cap
        self.fail_on_call = fail_on_call
        self.calls = 0
        self._served = {}

    def __call__(self, method, url, headers, json=None, timeout=None):
        self.calls += 1
        if self.fail_on_call == self.calls:
            return mock.Mock(status_code=500, text="error")
        since = None
        flt = json.get("filter") or {}
        for cond in flt.get("and", [flt]):
            if cond.get("timestamp") == "created_time":
                since = cond["created_time"]["on_or_after"]
        matched = sorted(
            (r for r in self.rows if since is None or r["created_time"] >= since),
            key=lambda r: r["created_time"],
        )[: self.cap]
        start = int(json.get("start_cursor") or 0)
        page = matched[start:start + json["page_size"]]
        end = start + len(page)
        more = end < len(matched)
        res = mock.Mock(status_code=200)
        res.json.return_value = {"results": page, "has_more": more, "next_cursor": str(end) if more else None}
        return res


def make_rows(n, per_minute=4):
    rows = []
    for i in range(n):
        minute = i // per_minute
        rows.append({
            "id": f"id{i}",
            "created_time": f"2026-09-01T{minute // 60:02d}:{minute % 60:02d}:00.000Z",
            "properties": {"URL": {"url": f"https://www.youtube.com/watch?v={i}"}},
        })
    return rows


class TestQueryDatabaseAll(unittest.TestCase):
    def test_reads_past_the_cap(self):
        # 本物の上限は1万件。ここでは7件に縮めて、25件を全部読めるかを見る。
        rows = make_rows(25)
        fake = FakeNotion(rows, cap=7)
        with mock.patch.object(notion_utils, "notion_request", fake), \
             mock.patch.object(notion_utils, "NOTION_QUERY_CAP", 7):
            got, complete = notion_utils.query_database_all({}, "db", page_size=3)
        self.assertTrue(complete)
        self.assertEqual({r["id"] for r in got}, {r["id"] for r in rows})
        # 境目の行は2回返るが、同じ行が2回入らないこと
        self.assertEqual(len(got), len(rows))

    def test_failure_is_reported_as_incomplete(self):
        fake = FakeNotion(make_rows(25), cap=7, fail_on_call=4)
        with mock.patch.object(notion_utils, "notion_request", fake), \
             mock.patch.object(notion_utils, "NOTION_QUERY_CAP", 7):
            _, complete = notion_utils.query_database_all({}, "db", page_size=3)
        self.assertFalse(complete)

    def test_stops_instead_of_looping_forever(self):
        # 同じ分に上限以上の行がある場合、先へ進めない。無限に回らず諦めること。
        rows = make_rows(20, per_minute=20)
        fake = FakeNotion(rows, cap=7)
        with mock.patch.object(notion_utils, "notion_request", fake), \
             mock.patch.object(notion_utils, "NOTION_QUERY_CAP", 7):
            _, complete = notion_utils.query_database_all({}, "db", page_size=3)
        self.assertFalse(complete)
        self.assertLess(fake.calls, 50)


class TestExistingUrls(unittest.TestCase):
    def test_incomplete_scan_returns_none(self):
        with mock.patch.object(trend_collector, "query_database_all", return_value=([], False)):
            self.assertIsNone(trend_collector.get_existing_notion_urls({}, "db"))

    def test_urls_are_collected(self):
        rows = make_rows(3)
        with mock.patch.object(trend_collector, "query_database_all", return_value=(rows, True)):
            urls = trend_collector.get_existing_notion_urls({}, "db")
        self.assertEqual(len(urls), 3)

    def test_empty_database_is_an_empty_set_not_none(self):
        # 空のDBは正常。None（取り切れなかった）と区別できないと、
        # 初回の登録がいつまでも始まらない。
        with mock.patch.object(trend_collector, "query_database_all", return_value=([], True)):
            self.assertEqual(trend_collector.get_existing_notion_urls({}, "db"), set())


if __name__ == "__main__":
    unittest.main()
