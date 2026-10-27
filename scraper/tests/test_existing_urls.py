"""登録済みURLの取得のテスト。

    実行: npm run test:py

ここが「途中までの一覧」を返すと、登録済みの行を未登録と見なして
まるごと再登録する。実際に広告が1回あたり約370件ずつ重複登録され、
同じ動画が最大6回入っていた。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import trend_collector  # noqa: E402


def page(url):
    return {"properties": {"URL": {"url": url}}}


def response(status, results=(), has_more=False, cursor=None):
    res = mock.Mock(status_code=status, text="error")
    res.json.return_value = {"results": list(results), "has_more": has_more, "next_cursor": cursor}
    return res


class TestExistingUrls(unittest.TestCase):
    def test_all_pages_are_collected(self):
        pages = [
            response(200, [page("https://a")], has_more=True, cursor="c1"),
            response(200, [page("https://b")]),
        ]
        with mock.patch.object(trend_collector, "notion_request", side_effect=pages):
            urls = trend_collector.get_existing_notion_urls({}, "db")
        self.assertEqual(urls, {"https://a", "https://b"})

    def test_failure_midway_returns_none_not_a_partial_list(self):
        # 1ページ目だけ取れて2ページ目で落ちた場合。途中までの一覧を返すと、
        # 2ページ目以降に載っていた行がすべて再登録される。
        pages = [
            response(200, [page("https://a")], has_more=True, cursor="c1"),
            response(500),
        ]
        with mock.patch.object(trend_collector, "notion_request", side_effect=pages):
            self.assertIsNone(trend_collector.get_existing_notion_urls({}, "db"))

    def test_network_error_returns_none(self):
        with mock.patch.object(trend_collector, "notion_request", side_effect=ConnectionError("切断")):
            self.assertIsNone(trend_collector.get_existing_notion_urls({}, "db"))

    def test_empty_database_is_an_empty_set_not_none(self):
        # 空のDBは正常。None（取り切れなかった）と区別できないと、
        # 初回の登録がいつまでも始まらない。
        with mock.patch.object(trend_collector, "notion_request", return_value=response(200)):
            self.assertEqual(trend_collector.get_existing_notion_urls({}, "db"), set())


if __name__ == "__main__":
    unittest.main()
