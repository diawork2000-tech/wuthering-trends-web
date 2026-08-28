"""公式SNS収集の組み立てと判定のテスト。

    実行: npm run test:py

ネットワークには繋がない。URLの組み立てと、取得結果の解釈だけを対象にする。
ここが壊れると「静かにゼロ件」になり、取り逃しに気づけなくなる。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sns_collector  # noqa: E402
from sns_collector import (  # noqa: E402
    account_label,
    translate_posts,
    collect_account,
    collect_sns_posts,
    describe_targets,
    feed_url,
    load_accounts,
    source_label,
)

RSSHUB = "https://rsshub.example.com"


class FakeFeed:
    def __init__(self, entries):
        self.entries = entries

    def get(self, key, default=None):
        return getattr(self, key, default)


def account(platform, ident, lang="ja", name=""):
    return {"platform": platform, "id": ident, "lang": lang, "name": name, "url": ""}


class TestFeedUrl(unittest.TestCase):
    def test_x_uses_twitter_route(self):
        url = feed_url(account("x", "WW_JP_Official"), RSSHUB)
        self.assertEqual(url, f"{RSSHUB}/twitter/user/WW_JP_Official")

    def test_bilibili_uses_dynamic_not_video(self):
        # 動画だけでなく告知文も拾いたいので dynamic を使う。
        # video に変えると文字だけの発表が丸ごと落ちる。
        url = feed_url(account("bilibili", "1955897084", "zh-CN"), RSSHUB)
        self.assertIn("/bilibili/user/dynamic/1955897084", url)

    def test_weibo_route(self):
        url = feed_url(account("weibo", "7730797357", "zh-CN"), RSSHUB)
        self.assertEqual(url, f"{RSSHUB}/weibo/user/7730797357")

    def test_reddit_does_not_use_rsshub(self):
        # Reddit は公式RSSが読めるので中継を挟まない。
        # RSSHub が落ちている日でも Reddit だけは動き続ける。
        url = feed_url(account("reddit", "WutheringWaves", "en"), "")
        self.assertTrue(url.startswith("https://www.reddit.com/"))
        self.assertNotIn("rsshub", url)

    def test_reddit_uses_hot_not_new(self):
        # new は掲示板の全書き込みが流れてきて、公式の投稿が埋もれる。
        url = feed_url(account("reddit", "WutheringWaves", "en"), "")
        self.assertIn("/hot/.rss", url)
        self.assertNotIn("/new/", url)

    def test_access_key_is_appended(self):
        url = feed_url(account("x", "WW_JP_Official"), RSSHUB, "SECRET")
        self.assertTrue(url.endswith("?key=SECRET"))

    def test_no_rsshub_means_no_url(self):
        self.assertEqual(feed_url(account("x", "WW_JP_Official"), ""), "")

    def test_unknown_platform_is_skipped(self):
        self.assertEqual(feed_url(account("tiktok", "wutheringwavesjp"), RSSHUB), "")


class TestSourceLabel(unittest.TestCase):
    def test_x_gets_at_mark(self):
        self.assertEqual(
            source_label(account("x", "WW_JP_Official", "ja")),
            "X ・ 日本語 ・ @WW_JP_Official",
        )

    def test_reddit_gets_r_prefix(self):
        self.assertEqual(
            source_label(account("reddit", "WutheringWaves", "en")),
            "Reddit ・ 英語 ・ r/WutheringWaves",
        )

    def test_numeric_id_is_shown_as_a_readable_name(self):
        # 数字のIDだけ出されても人間には読めないので、名前のほうを使う。
        # 生のIDは画面の「収集中のアカウント」一覧で確認できる。
        label = source_label(account("bilibili", "1955897084", "zh-CN", "鸣潮"))
        self.assertEqual(label, "BiliBili ・ 中国語 ・ 鸣潮")

    def test_parenthetical_note_is_trimmed_from_name(self):
        # 一覧側の名前には「（認証済・535万）」のような注記が付く。
        # 絞り込みボタンの文字になるので、そこは落とす。
        self.assertEqual(
            account_label(account("bilibili", "1955897084", "zh-CN", "鸣潮（認証済・535万）")),
            "鸣潮",
        )


class TestCollectAccount(unittest.TestCase):
    def test_empty_feed_is_reported_not_silently_dropped(self):
        # 取得できたのに0件、が一番危ない。TikTok が常にこの形で返してくる。
        # ここを "ok" で返すと「正常終了・0件」が延々と続いてしまう。
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed([]), "")):
            posts, state = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts, [])
        self.assertEqual(state, "empty")

    def test_http_error_is_reported(self):
        with mock.patch("sns_collector._fetch", return_value=(None, "HTTP 503")):
            posts, state = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(state, "HTTP 503")

    def test_error_reason_is_carried_back(self):
        # 状態番号だけでは何が起きたのか分からず、毎回サーバーのログを
        # 人が見に行くことになる。理由まで持ち帰る。
        page = ("<html><head><style>details::-webkit-scrollbar { width: 0.25rem; }</style></head>"
                "<body>Welcome to RSSHub! Looks like something went wrong "
                "Error Message: RejectError: Authentication failed. "
                "Route: /bilibili/user/dynamic/1</body></html>")
        res = mock.Mock(status_code=503, text=page)
        with mock.patch("sns_collector.requests.get", return_value=res):
            feed, error = sns_collector._fetch("https://example.com/x", "label")
        self.assertIsNone(feed)
        self.assertIn("HTTP 503", error)
        self.assertIn("Authentication failed", error)
        # 見た目を整えるCSSが理由を押しのけないこと（実際に一度そうなった）
        self.assertNotIn("scrollbar", error)

    def test_entries_without_link_are_skipped(self):
        entries = [{"title": "本文", "link": ""}, {"title": "本文2", "link": "https://x.com/a/status/1"}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, state = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(state, "ok")
        self.assertEqual(len(posts), 1)

    def test_max_items_is_respected(self):
        entries = [{"title": f"t{i}", "link": f"https://x.com/a/status/{i}"} for i in range(50)]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 5)
        self.assertEqual(len(posts), 5)

    def test_posted_at_is_sortable(self):
        # 「8月28日」のような表示用の形にしてしまうと並べ替えができない。
        entries = [{"title": "t", "link": "https://x.com/a/status/1",
                    "published_parsed": (2026, 8, 28, 3, 4, 5, 0, 0, 0)}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["posted_at"], "2026-08-28T03:04:05+00:00")

    def test_video_post_carries_its_mp4_and_poster(self):
        # RSSHub は本文に <video src poster> を入れてくる。ここを読めないと
        # 動画付きの投稿がただの静止画になる。
        html = ("<video width='1280' height='720' src='https://video.twimg.com/a.mp4' "
                "controls='controls' poster='https://pbs.twimg.com/b.jpg'></video>")
        entries = [{"title": "PV公開", "link": "https://x.com/a/status/1", "summary": html}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["video_url"], "https://video.twimg.com/a.mp4")
        # 表紙は本文中の1枚目より投稿の中身に近い
        self.assertEqual(posts[0]["thumbnail"], "https://pbs.twimg.com/b.jpg")

    def test_image_only_post_has_no_video(self):
        html = "<img src='https://pbs.twimg.com/c.jpg'>"
        entries = [{"title": "お知らせ", "link": "https://x.com/a/status/1", "summary": html}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["video_url"], "")
        self.assertEqual(posts[0]["thumbnail"], "https://pbs.twimg.com/c.jpg")

    def test_non_https_video_is_ignored(self):
        html = "<video src='//video.twimg.com/a.mp4'></video>"
        entries = [{"title": "t", "link": "https://x.com/a/status/1", "summary": html}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["video_url"], "")

    def test_post_carries_its_source(self):
        entries = [{"title": "告知です", "link": "https://x.com/a/status/1"}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "WW_JP_Official", "ja"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["platform"], "X")
        self.assertEqual(posts[0]["lang"], "日本語")
        self.assertIn("@WW_JP_Official", posts[0]["channel"])

    def test_html_is_stripped_from_title(self):
        # X の投稿には見出しが無く、RSSHub は本文をそのまま入れてくる。
        entries = [{"title": "<p>お知らせ<br>второй</p>", "link": "https://x.com/a/status/1"}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertNotIn("<", posts[0]["title"])


class TestCollectAll(unittest.TestCase):
    def test_reddit_still_runs_without_rsshub(self):
        # RSSHub をまだ立てていない間も、Reddit だけは動く。全部を止めない。
        accounts = [account("x", "a"), account("reddit", "WutheringWaves", "en")]
        entries = [{"title": "post", "link": "https://www.reddit.com/r/x/comments/1/"}]
        with mock.patch.dict(os.environ, {"RSSHUB_BASE_URL": ""}, clear=False), \
             mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, stats = collect_sns_posts({"interval_seconds": 0}, accounts)
        self.assertEqual(stats["skipped_no_rsshub"], 1)
        self.assertEqual(len(posts), 1)

    def test_collected_count_excludes_skipped_accounts(self):
        # 対象数と、実際に取れた数を混ぜない。混ぜると見送りが起きていても
        # 全部から取れたように読めてしまう。
        accounts = [account("x", "a"), account("reddit", "WutheringWaves", "en")]
        entries = [{"title": "post", "link": "https://www.reddit.com/r/x/comments/1/"}]
        with mock.patch.dict(os.environ, {"RSSHUB_BASE_URL": ""}, clear=False), \
             mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            _, stats = collect_sns_posts({"interval_seconds": 0}, accounts)
        self.assertEqual(stats["accounts"], 2)
        self.assertEqual(stats["collected_accounts"], 1)


class TestTranslation(unittest.TestCase):
    def post(self, title, lang="韓国語"):
        return {"title": title, "lang": lang, "original_title": ""}

    def test_translated_title_replaces_the_original(self):
        posts = [self.post("시그리카")]
        n, failed = translate_posts(posts, lambda t: "シグリカ", interval=0)
        self.assertEqual((n, failed), (1, 0))
        self.assertEqual(posts[0]["title"], "シグリカ")
        self.assertEqual(posts[0]["original_title"], "시그리카")

    def test_other_languages_are_left_alone(self):
        # 英語は読めるので訳さない。訳す件数を絞らないと翻訳側に弾かれる。
        posts = [self.post("Resonator Preview", lang="英語"), self.post("お知らせ", lang="日本語")]
        n, failed = translate_posts(posts, lambda t: "訳", interval=0)
        self.assertEqual((n, failed), (0, 0))
        self.assertEqual(posts[0]["title"], "Resonator Preview")

    def test_unchanged_result_counts_as_a_failure(self):
        # 元の実装は失敗すると黙って原文を返していたため、一度も訳せていない
        # ことに誰も気づけなかった。同じ文が返ったら失敗として数える。
        posts = [self.post("시그리카")]
        n, failed = translate_posts(posts, lambda t: t, interval=0)
        self.assertEqual((n, failed), (0, 1))
        self.assertEqual(posts[0]["original_title"], "")

    def test_exception_counts_as_a_failure(self):
        def boom(_):
            raise RuntimeError("翻訳サービスが落ちた")

        posts = [self.post("시그리카")]
        n, failed = translate_posts(posts, boom, interval=0)
        self.assertEqual((n, failed), (0, 1))
        self.assertEqual(posts[0]["title"], "시그리카")


class TestAccountList(unittest.TestCase):
    def test_shipped_list_is_loadable_and_scoped(self):
        accounts = load_accounts()
        self.assertTrue(accounts, "収集対象が空になっている")
        # 取得できないと確認済みの媒体が紛れ込んでいないこと。
        # TikTok は 200 を返しながら常に0件で、静かな失敗になる。
        platforms = {a["platform"] for a in accounts}
        self.assertNotIn("tiktok", platforms)
        self.assertNotIn("facebook", platforms)
        for a in accounts:
            self.assertTrue(feed_url(a, RSSHUB), f"URLを組み立てられない: {a['platform']}/{a['id']}")

    def test_targets_can_be_listed_for_the_log(self):
        # どのアカウントを見に行っているかは、設定ファイルを開かずに分かる必要がある。
        targets = describe_targets()
        self.assertEqual(len(targets), len(load_accounts()))
        self.assertTrue(any("@WW_JP_Official" in t for t in targets))


if __name__ == "__main__":
    unittest.main()
