"""見出しの翻訳のテスト。

    実行: npm run test:py

以前の翻訳は、Google 翻訳のスマホ向けページを読み取る方式で、2026-09-11 以降は
自動アクセスが確認画面へ転送され、2か月1件も訳せていなかった。失敗しても原文を
返すだけで止まらないため誰も気づけなかった。ここでは通信しない。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import trend_collector as tc  # noqa: E402


def gtx_response(*segments, status=200):
    res = mock.Mock(status_code=status)
    res.json.return_value = [[[s, "orig"] for s in segments], None, "en"]
    return res


class TestTranslateIfNeeded(unittest.TestCase):
    def setUp(self):
        tc.TRANSLATION_STATS.update(ok=0, failed=0)

    def test_foreign_text_is_translated(self):
        with mock.patch.object(tc.requests, "get", return_value=gtx_response("こんにちは")) as get:
            self.assertEqual(tc.translate_if_needed("Hello"), "こんにちは")
        self.assertIn("translate.googleapis.com", get.call_args[0][0])
        self.assertEqual(tc.TRANSLATION_STATS, {"ok": 1, "failed": 0})

    def test_japanese_is_not_sent(self):
        with mock.patch.object(tc.requests, "get") as get:
            self.assertEqual(tc.translate_if_needed("本日メンテナンス"), "本日メンテナンス")
        get.assert_not_called()

    def test_long_text_segments_are_joined(self):
        with mock.patch.object(tc.requests, "get", return_value=gtx_response("前半。", "後半。")):
            self.assertEqual(tc.translate_if_needed("First. Second."), "前半。後半。")

    def test_blocked_endpoint_returns_original_and_is_counted(self):
        # 窓口に止められても収集は止めない。ただし失敗は必ず数える。
        with mock.patch.object(tc.requests, "get", return_value=gtx_response(status=429)):
            self.assertEqual(tc.translate_if_needed("Hello"), "Hello")
        self.assertEqual(tc.TRANSLATION_STATS, {"ok": 0, "failed": 1})

    def test_unchanged_result_retries_as_chinese(self):
        responses = [gtx_response("鳴潮 新版本"), gtx_response("鳴潮 新バージョン")]
        with mock.patch.object(tc.requests, "get", side_effect=responses) as get:
            self.assertEqual(tc.translate_if_needed("鳴潮 新版本"), "鳴潮 新バージョン")
        self.assertEqual(get.call_args_list[1][1]["params"]["sl"], "zh-TW")

    def test_still_unchanged_counts_as_failure(self):
        with mock.patch.object(tc.requests, "get", return_value=gtx_response("Hello")):
            self.assertEqual(tc.translate_if_needed("Hello"), "Hello")
        self.assertEqual(tc.TRANSLATION_STATS["failed"], 1)


class TestGameName(unittest.TestCase):
    """ゲーム名は訳させない。「嵐の波」「Mingchao」になると何の動画か分からない。"""

    def setUp(self):
        tc.TRANSLATION_STATS.update(ok=0, failed=0)

    def sent_text(self, text, reply="訳"):
        with mock.patch.object(tc.requests, "get", return_value=gtx_response(reply)) as get:
            tc.translate_if_needed(text)
        return get.call_args[1]["params"]["q"]

    def test_english_name_is_replaced_before_translating(self):
        self.assertEqual(self.sent_text("Tips - Wuthering Waves"), "Tips - 鳴潮")
        self.assertEqual(self.sent_text("WuWa 3.6 news"), "鳴潮 3.6 news")

    def test_korean_and_chinese_names(self):
        self.assertEqual(self.sent_text("『명조:워더링 웨이브』 소식"), "『鳴潮』 소식")
        self.assertEqual(self.sent_text("鸣潮 新版本"), "鳴潮 新版本")

    def test_words_containing_wuwa_are_left_alone(self):
        self.assertEqual(self.sent_text("WuWawesome edit"), "WuWawesome edit")

    def test_romanized_name_in_the_result_is_restored(self):
        for reply in ("Mingchao バージョン", "ミンチャオ先行", "Ming Chao の新キャラ"):
            with mock.patch.object(tc.requests, "get", return_value=gtx_response(reply)):
                self.assertIn("鳴潮", tc.translate_if_needed("鸣潮 test"))


class TestTranslateOnlyNewYouTubeRows(unittest.TestCase):
    """見出しを訳すのは登録する直前だけ。登録済みの動画まで毎時訳すと窓口に止められる。"""

    def run_send(self, videos, category, existing):
        calls = []

        def fake_translate(text):
            calls.append(text)
            return "訳:" + text

        ok = mock.Mock(status_code=200)
        with mock.patch.dict(os.environ, {"NOTION_API_KEY": "k", "NOTION_DATABASE_ID": "db"}), \
             mock.patch.object(tc, "translate_if_needed", side_effect=fake_translate), \
             mock.patch.object(tc, "notion_request", return_value=ok), \
             mock.patch.object(tc.time, "sleep"):
            tc.send_to_notion(videos, category, set(existing))
        return calls

    def video(self, n):
        return {"title": f"title{n}", "original_title": f"title{n}", "url": f"https://www.youtube.com/watch?v={n}",
                "channel": "c", "thumbnail": ""}

    def test_only_new_videos_are_translated(self):
        calls = self.run_send([self.video(1), self.video(2)], "最新 (Shorts)", ["https://www.youtube.com/watch?v=1"])
        self.assertEqual(calls, ["title2"])

    def test_sns_and_ads_are_not_translated_here(self):
        self.assertEqual(self.run_send([self.video(3)], "SNS", []), [])
        self.assertEqual(self.run_send([self.video(4)], "広告", []), [])


if __name__ == "__main__":
    unittest.main()
