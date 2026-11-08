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

    def test_html_entities_in_urls_are_restored(self):
        # 本文はHTMLなので & が &amp; と書かれている。戻さないと画像が404になる。
        # 実際にこれで186件の画像が表示できていなかった。
        html = "<img src='https://pbs.twimg.com/media/AAA?format=jpg&amp;name=orig'>"
        entries = [{"title": "t", "link": "https://x.com/a/status/1", "summary": html}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "a"), RSSHUB, "", 20)
        self.assertEqual(posts[0]["thumbnail"], "https://pbs.twimg.com/media/AAA?format=jpg&name=orig")
        self.assertNotIn("&amp;", posts[0]["thumbnail"])

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

    def test_error_page_is_not_stored_as_a_translation(self):
        # 翻訳先が落ちるとエラー画面の文面が返ってくる。実際に
        # 「Error 500 (Server Error)」が7件、訳文として登録されていた。
        posts = [self.post("시그리카")]
        n, failed = translate_posts(
            posts, lambda t: "Error 500 (Server Error)!!1500.That’s an error", interval=0
        )
        self.assertEqual((n, failed), (0, 1))
        self.assertEqual(posts[0]["title"], "시그리카")
        self.assertEqual(posts[0]["original_title"], "")

    def test_retry_recovers_a_temporary_failure(self):
        calls = []

        def flaky(text):
            calls.append(text)
            return "" if len(calls) == 1 else "シグリカ"

        posts = [self.post("시그리카")]
        n, failed = translate_posts(posts, flaky, interval=0)
        self.assertEqual((n, failed), (1, 0))
        self.assertEqual(posts[0]["title"], "シグリカ")


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
        # 公式と公式以外（x_watch.json）の両方が並ぶこと
        self.assertEqual(len(targets), len(load_accounts()) + len(sns_collector.load_watch()[0]))
        self.assertTrue(any("@WW_JP_Official" in t for t in targets))




class TestWatchAccounts(unittest.TestCase):
    """公式以外の X（x_watch.json）。オーナーの X のリストから 2026-11-08 に足した。"""

    def test_shipped_watch_list(self):
        accounts, exclude, interval = sns_collector.load_watch()
        self.assertEqual(len(accounts), 11)
        # 除外は最初は空（オーナー判断。リーク系でも小ネタが多いので今は落とさない）
        self.assertEqual(exclude, [])
        self.assertGreaterEqual(interval, 2)
        for a in accounts:
            self.assertEqual(a["platform"], "x")
            self.assertEqual(a["lang"], "auto")
            self.assertTrue(a["exclude_retweets"])
        # 公式と重ねない（WW_2NDFES は公式側で収集している）
        official = {a["id"].lower() for a in load_accounts() if a["platform"] == "x"}
        self.assertFalse({a["id"].lower() for a in accounts} & official)

    def test_watch_feed_drops_retweets(self):
        # リポストは投稿者がリポストした人になり、元の投稿者を照合で落とせない
        url = feed_url({"platform": "x", "id": "wuwaguy", "lang": "auto", "exclude_retweets": True}, RSSHUB)
        self.assertEqual(url, f"{RSSHUB}/twitter/user/wuwaguy/includeRts=false")

    def test_official_feed_keeps_its_route(self):
        self.assertEqual(feed_url(account("x", "WW_JP_Official"), RSSHUB), f"{RSSHUB}/twitter/user/WW_JP_Official")

    def test_watch_runs_every_few_hours_in_japan_time(self):
        import datetime as dt
        jst = dt.timezone(dt.timedelta(hours=9))
        self.assertTrue(sns_collector.watch_due(3, dt.datetime(2026, 11, 8, 21, 1, tzinfo=jst)))
        self.assertFalse(sns_collector.watch_due(3, dt.datetime(2026, 11, 8, 22, 1, tzinfo=jst)))
        self.assertTrue(sns_collector.watch_due(3, dt.datetime(2026, 11, 9, 0, 1, tzinfo=jst)))

    def test_official_is_read_before_watch(self):
        # 公式以外で token が止められても、公式の分は先に取り終えているように
        order = []

        def fake_collect(acc, *args, **kwargs):
            order.append(acc["id"])
            return [], "ok"

        watch = [{"platform": "x", "id": "wuwaguy", "lang": "auto", "source_type": "creator",
                  "exclude_retweets": True, "watch": True}]
        with mock.patch.dict(os.environ, {"RSSHUB_BASE_URL": RSSHUB}),              mock.patch.object(sns_collector, "load_accounts", return_value=[account("x", "WW_JP_Official")]),              mock.patch.object(sns_collector, "load_watch", return_value=(watch, [], 3)),              mock.patch.object(sns_collector, "watch_due", return_value=True),              mock.patch.object(sns_collector, "collect_account", side_effect=fake_collect):
            collect_sns_posts({"interval_seconds": 0})
        self.assertEqual(order, ["WW_JP_Official", "wuwaguy"])

    def test_watch_is_skipped_when_not_due(self):
        watch = [{"platform": "x", "id": "wuwaguy", "lang": "auto", "exclude_retweets": True}]
        with mock.patch.dict(os.environ, {"RSSHUB_BASE_URL": RSSHUB}),              mock.patch.object(sns_collector, "load_accounts", return_value=[account("x", "WW_JP_Official")]),              mock.patch.object(sns_collector, "load_watch", return_value=(watch, [], 3)),              mock.patch.object(sns_collector, "watch_due", return_value=False),              mock.patch.object(sns_collector, "collect_account", return_value=([], "ok")):
            _, stats = collect_sns_posts({"interval_seconds": 0})
        self.assertEqual(stats["accounts"], 1)
        self.assertEqual(stats["watch_skipped"], 1)


class TestExclusionAndLanguage(unittest.TestCase):
    def test_handles_from_link_and_quoted_post(self):
        html = "<div>本文 <a href='https://x.com/leaker_x/status/9'>引用</a> https://x.com/i/status/1</div>"
        found = sns_collector.mentioned_handles("https://x.com/wuwaguy/status/1", html)
        self.assertEqual(found, {"wuwaguy", "leaker_x"})

    def test_excluded_author_or_quote_is_dropped(self):
        entries = [
            {"title": "自分の投稿", "link": "https://x.com/leaker_x/status/1", "summary": ""},
            {"title": "引用した投稿", "link": "https://x.com/wuwaguy/status/2",
             "summary": "<a href='https://x.com/Leaker_X/status/9'>引用</a>"},
            {"title": "普通の投稿", "link": "https://x.com/wuwaguy/status/3", "summary": ""},
        ]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "wuwaguy"), RSSHUB, "", 20, exclude=["@leaker_x"])
        self.assertEqual([p["title"] for p in posts], ["普通の投稿"])

    def test_empty_exclude_keeps_everything(self):
        entries = [{"title": "t", "link": "https://x.com/leaker_x/status/1", "summary": ""}]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(account("x", "leaker_x"), RSSHUB, "", 20, exclude=[])
        self.assertEqual(len(posts), 1)

    def test_language_is_detected_per_post_for_watch_accounts(self):
        acc = {"platform": "x", "id": "wuwaguy", "lang": "auto", "source_type": "creator", "url": ""}
        entries = [
            {"title": "新キャラの小ネタです", "link": "https://x.com/wuwaguy/status/1"},
            {"title": "New character tips", "link": "https://x.com/wuwaguy/status/2"},
            {"title": "신규 캐릭터", "link": "https://x.com/wuwaguy/status/3"},
        ]
        with mock.patch("sns_collector._fetch", return_value=(FakeFeed(entries), "")):
            posts, _ = collect_account(acc, RSSHUB, "", 20)
        self.assertEqual([p["lang"] for p in posts], ["日本語", "英語", "韓国語"])
        self.assertEqual(posts[0]["channel"], "X ・ 日本語 ・ @wuwaguy")
        self.assertEqual(posts[0]["source_type"], "クリエイター")

    def test_source_type_of_official_accounts(self):
        self.assertEqual(sns_collector.source_type_of({"category": "dev"}), "公式")
        self.assertEqual(sns_collector.source_type_of({"category": "community"}), "コミュニティ")
        self.assertEqual(sns_collector.source_type_of({"source_type": "media"}), "メディア")

    def test_chinese_is_not_mistaken_for_japanese(self):
        # 中国語にも漢字は入るが、かなは入らない
        self.assertEqual(sns_collector.detect_lang("鸣潮 新版本上线"), "zh-CN")
        self.assertEqual(sns_collector.detect_lang("鳴潮の新バージョン"), "ja")


if __name__ == "__main__":
    unittest.main()
