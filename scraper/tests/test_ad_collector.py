"""広告収集の判定部分のテスト。

    実行: npm run test:py

ネットワークには一切繋がない。Googleの内部RPCが返す形をそのまま貼って、
解釈だけを対象にしている。ここが壊れると「広告が静かにゼロ件になる」ため、
形が変わったことに気づけるようにしておく。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ad_collector import (  # noqa: E402
    extract_youtube_id,
    format_period,
    parse_creative,
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


if __name__ == "__main__":
    unittest.main()
