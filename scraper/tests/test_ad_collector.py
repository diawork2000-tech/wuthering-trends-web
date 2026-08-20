"""広告収集の判定部分のテスト。

    実行: npm run test:py

ネットワークには一切繋がない。Googleの内部RPCが返す形をそのまま貼って、
解釈だけを対象にしている。ここが壊れると「広告が静かにゼロ件になる」ため、
形が変わったことに気づけるようにしておく。
"""

import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ad_collector import (  # noqa: E402
    MAX_RESOLVE_MISSES,
    _needs_resolving,
    extract_youtube_id,
    format_period,
    is_other_game,
    load_cache,
    parse_creative,
    select_advertisers,
)


class TestExtractYoutubeId(unittest.TestCase):
    def test_プレビューからYouTube動画IDを取り出す(self):
        # 広告プレビュー本体は難読化されているが、サムネイルURLだけは素で埋まっている
        text = 'a=1;var t="https://i.ytimg.com/vi/W2C_Gm_ZLoI/hqdefault.jpg";'
        self.assertEqual(extract_youtube_id(text), "W2C_Gm_ZLoI")

    def test_ハイフンやアンダースコアを含むIDも取れる(self):
        text = 'https://i.ytimg.com/vi/4__0pJ6UpBw/maxresdefault.jpg'
        self.assertEqual(extract_youtube_id(text), "4__0pJ6UpBw")

    def test_動画を含まない広告では空を返す(self):
        self.assertEqual(extract_youtube_id('<img src="https://tpc.googlesyndication.com/x.png">'), "")
        self.assertEqual(extract_youtube_id(""), "")
        self.assertEqual(extract_youtube_id(None), "")


class TestParseCreative(unittest.TestCase):
    VIDEO_AD = {
        "1": "AR00700200168850456577",
        "2": "CR05946875567025422337",
        "3": {"1": {"4": "https://displayads-formats.googleusercontent.com/ads/preview/content.js?x=1"}},
        "4": 3,
        "6": {"1": "1783647175", "2": 219526000},
        "7": {"1": "1787223390", "2": 16033000},
        "12": "広州庫洛科技有限公司",
    }

    IMAGE_AD = {
        "1": "AR00700200168850456577",
        "2": "CR18313846567116734465",
        "3": {"3": {"2": '<img src="https://tpc.googlesyndication.com/archive/simgad/1032" height="173">'}},
        "4": 1,
        "6": {"1": "1753427430"},
        "7": {"1": "1787223197"},
        "12": "広州庫洛科技有限公司",
    }

    def test_動画広告からプレビューURLと期間を取り出す(self):
        info = parse_creative(self.VIDEO_AD)
        self.assertEqual(info["creative_id"], "CR05946875567025422337")
        self.assertTrue(info["preview_url"].startswith("https://displayads-formats."))
        self.assertEqual(info["first_shown"], "2026-07-10")
        self.assertEqual(info["last_shown"], "2026-08-20")

    def test_画像広告にはプレビューURLが無い(self):
        # 動画IDが取れないものはここで弾かれ、動画DBには入らない
        self.assertEqual(parse_creative(self.IMAGE_AD)["preview_url"], "")

    def test_形が変わっても例外を投げない(self):
        # 相手の仕様変更で落ちると収集全体が止まるため、欠損として返す
        for broken in [{}, {"3": None}, {"3": {"1": None}}, {"6": {"1": "abc"}}]:
            with self.subTest(broken=broken):
                info = parse_creative(broken)
                self.assertEqual(info["preview_url"], "")
                self.assertEqual(info["first_shown"], "")


class TestFormatPeriod(unittest.TestCase):
    def test_両端があれば範囲で表示する(self):
        self.assertEqual(format_period("2026-01-05", "2026-08-18"), "2026-01-05 〜 2026-08-18")

    def test_片方しか無くても読める形にする(self):
        self.assertEqual(format_period("2026-01-05", ""), "2026-01-05")
        self.assertEqual(format_period("", "2026-08-18"), "2026-08-18")

    def test_どちらも無ければ空(self):
        self.assertEqual(format_period("", ""), "")


class TestIsOtherGame(unittest.TestCase):
    """同じ広告主がパニシングの広告も出しているので、混ざらないようにする。"""

    def test_パニシングの素材は除く(self):
        self.assertTrue(is_other_game("PGR-JP-V-CQ-QZY-4.5-空花2.0多角色旋转合影-1080x1920.mp4", ""))
        self.assertTrue(is_other_game("何かの広告", "パニシング:グレイレイヴン"))
        self.assertTrue(is_other_game("何かの広告", "PGR"))

    def test_鳴潮の素材は残す(self):
        self.assertFalse(is_other_game("WW-JP-V-SSW-DJS-3.6-清宵直面BOSS拼主城行走-1920x1080.mp4", "Wuthering Waves"))
        self.assertFalse(is_other_game("『鳴潮』キャラクターPV丨清宵丨修真", "鳴潮 (Wuthering Waves)公式"))

    def test_語の一部には反応しない(self):
        # 「PGR」で始まる素材だけを対象にする。含むだけでは落とさない
        self.assertFalse(is_other_game("鳴潮とPGRを比較してみた", "個人チャンネル"))


class TestSelectAdvertisers(unittest.TestCase):
    """本家の広告だけを集める。代理店は個人配信者の動画を回しているだけ。"""

    FOUND = {
        "AR00700200168850456577": "广州库洛科技有限公司",
        "AR02411244470184968193": "COMETS INTERNATIONAL LIMITED",
        "AR02965941824335642625": "RPL Digital, SIA",
        "AR12990585511142752257": "JOÃO CÉSAR SIMPLÍCIO DE ALMEIDA",
    }
    PATTERNS = ["库洛", "庫洛", "Kuro"]

    def test_本家だけ残す(self):
        kept, skipped = select_advertisers(self.FOUND, self.PATTERNS)
        self.assertEqual(list(kept), ["AR00700200168850456577"])
        self.assertEqual(len(skipped), 3)

    def test_別法人でも名前が合えば拾う(self):
        # 本家がアカウントを増やしたときに黙って取りこぼさないよう、
        # IDの直書きではなく名前で見ている
        found = {**self.FOUND, "AR99": "Kuro Games Global Pte. Ltd."}
        kept, _ = select_advertisers(found, self.PATTERNS)
        self.assertIn("AR99", kept)

    def test_大文字小文字を区別しない(self):
        kept, _ = select_advertisers({"AR1": "KURO GAMES"}, ["kuro"])
        self.assertEqual(list(kept), ["AR1"])

    def test_条件が空なら全部通す(self):
        kept, skipped = select_advertisers(self.FOUND, [])
        self.assertEqual(len(kept), 4)
        self.assertEqual(skipped, {})

    def test_名前が取れていない広告主は外す(self):
        # 名前が空だと本家か判断できない。取りこぼしより誤混入を避ける
        kept, skipped = select_advertisers({"AR1": ""}, self.PATTERNS)
        self.assertEqual(kept, {})
        self.assertEqual(list(skipped), ["AR1"])


class TestNeedsResolving(unittest.TestCase):
    """一度の通信の綾で、動画広告が永久に埋もれないようにする。"""

    WITH_PREVIEW = {"creative_id": "CR1", "preview_url": "https://example.invalid/p.js"}
    NO_PREVIEW = {"creative_id": "CR2", "preview_url": ""}

    def test_未取得なら調べる(self):
        self.assertTrue(_needs_resolving(self.WITH_PREVIEW, {}))

    def test_動画IDが取れているなら調べ直さない(self):
        cache = {"CR1": {"video_id": "W2C_Gm_ZLoI"}}
        self.assertFalse(_needs_resolving(self.WITH_PREVIEW, cache))

    def test_取りこぼしは回数を区切って引き直す(self):
        # プレビューは毎回組み立て直され、動画IDが入らない回がある。
        # 1回の空振りで「動画ではない広告」と確定させると二度と拾えない。
        self.assertTrue(_needs_resolving(self.WITH_PREVIEW, {"CR1": {"video_id": "", "misses": 1}}))
        self.assertFalse(
            _needs_resolving(self.WITH_PREVIEW, {"CR1": {"video_id": "", "misses": MAX_RESOLVE_MISSES}})
        )

    def test_旧形式の控えも引き直しの対象になる(self):
        # misses を持たない古い控えを「確定」と読むと、取りこぼしが固定される
        self.assertTrue(_needs_resolving(self.WITH_PREVIEW, {"CR1": {"video_id": ""}}))

    def test_通信に失敗した回は空振りに数えない(self):
        # レート制限に当たった日に全件が空振り扱いになり、数回で
        # 「動画ではない広告」として確定してしまうのを防ぐ
        import ad_collector

        calls = []

        def boom(url, timeout=25, label="プレビュー"):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

        original = ad_collector._fetch
        ad_collector._fetch = boom
        try:
            video_id, fetched = ad_collector.resolve_video_id("https://example.invalid/p.js")
        finally:
            ad_collector._fetch = original

        self.assertEqual(video_id, "")
        self.assertFalse(fetched)

    def test_中身を見て無ければ空振りに数える(self):
        import ad_collector

        original = ad_collector._fetch
        ad_collector._fetch = lambda url, timeout=25, label="プレビュー": "<div>画像だけの広告</div>"
        try:
            video_id, fetched = ad_collector.resolve_video_id("https://example.invalid/p.js")
        finally:
            ad_collector._fetch = original

        self.assertEqual(video_id, "")
        self.assertTrue(fetched)

    def test_プレビューが無い広告は調べない(self):
        # 画像・テキスト広告。動画は存在しないので確定させてよい
        self.assertFalse(_needs_resolving(self.NO_PREVIEW, {}))


class TestLoadCache(unittest.TestCase):
    def test_旧形式の控えを読み替える(self):
        import json
        import tempfile

        legacy = {"CR1": {"video_id": "W2C_Gm_ZLoI", "title": "t", "channel": "c"}}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(legacy, f)
            cache = load_cache(path)
        self.assertEqual(cache["creatives"]["CR1"]["video_id"], "W2C_Gm_ZLoI")
        self.assertEqual(cache["advertisers"], {})

    def test_控えが無くても壊れない(self):
        cache = load_cache(os.path.join("存在しない", "cache.json"))
        self.assertEqual(cache, {"creatives": {}, "advertisers": {}})


if __name__ == "__main__":
    unittest.main()
