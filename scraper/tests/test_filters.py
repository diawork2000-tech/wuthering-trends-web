"""収集の判定部分のテスト。

    実行: npm run test:py   （または python -m unittest discover -s scraper/tests -t .）

Notion にも Gemini にも接続しない。純粋な判定だけを対象にしている。
ここで守りたいのは「拾うべきものを捨てない」「捨てるべきものを拾わない」の2点で、
過去に実際に起きた取りこぼし・誤爆をそのままテストにしてある。
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trend_collector import should_exclude  # noqa: E402
from intelligence_collector import is_relevant, is_real_date, merge_version_entry  # noqa: E402
from purge_excluded import is_protected  # noqa: E402


EXCLUDE_WORDS = ["MMD", "cosplay", "Vtuber", "fanart", "コスプレ", "切り抜き"]


class TestShouldExclude(unittest.TestCase):
    def test_日本語と地続きでも除外できる(self):
        # 以前は \b を使っており、Python の \w が日本語を含むため境界が生まれず
        # 「鳴潮MMD」「鳴潮cosplay」が素通りしていた
        for title in ["鳴潮MMD 踊ってみた", "鳴潮cosplay まとめ", "Vtuber鳴潮実況", "鳴潮fanart集"]:
            with self.subTest(title=title):
                self.assertTrue(should_exclude(title, EXCLUDE_WORDS))

    def test_区切られている場合も従来どおり除外できる(self):
        for title in ["【MMD】鳴潮", "cosplay 鳴潮", "鳴潮 MMD", "鳴潮 切り抜き"]:
            with self.subTest(title=title):
                self.assertTrue(should_exclude(title, EXCLUDE_WORDS))

    def test_英単語の一部には反応しない(self):
        # cosplay を含む cosplayer で止めない、といった精度が要る
        self.assertFalse(should_exclude("鳴潮のcosplayer以外の話", EXCLUDE_WORDS))

    def test_無関係なタイトルは通す(self):
        for title in ["鳴潮 3.6 攻略", "鳴潮 コマンド解説", "音痕の色が特殊なキャラ"]:
            with self.subTest(title=title):
                self.assertFalse(should_exclude(title, EXCLUDE_WORDS))

    def test_除外ワードが空なら何も落とさない(self):
        self.assertFalse(should_exclude("鳴潮MMD", []))


class TestIsRelevant(unittest.TestCase):
    def test_鳴潮の話は通す(self):
        self.assertTrue(is_relevant("【鳴潮】音痕の違いが最高な件"))
        self.assertTrue(is_relevant("Wuthering Waves new character"))

    def test_他ゲームは落とす(self):
        self.assertFalse(is_relevant("原神の新キャラ実装"))
        self.assertFalse(is_relevant("鳴潮と崩壊スターレイルの比較"))

    def test_一般語の崩壊では落とさない(self):
        # 「崩壊」単体を除外語にしていたため、バランス崩壊の話まで落ちていた
        self.assertTrue(is_relevant("【鳴潮】バランス崩壊してるキャラ3選"))

    def test_二次創作や実写は落とす(self):
        self.assertFalse(is_relevant("【鳴潮】ダーニャのコスプレ写真"))
        self.assertFalse(is_relevant("海外絵師が描いた鳴潮のファンアート"))

    def test_プレイヤーを含むネタは落とさない(self):
        # 除外語「レイヤー」が「プレイヤー」に一致し、実測9件を捨てていた
        self.assertTrue(is_relevant("【鳴潮】プレイヤースキル次第で最強火力が出るキャラ3選"))

    def test_ゲーム内スクショ集は落とさない(self):
        # 「写真集」を除外語にしていたため、ゲーム内スクショ集まで落ちていた
        self.assertTrue(is_relevant('【鳴潮】"自分の好み"を詰め込んだエイメス写真集'))

    def test_鳴潮連は別物として落とす(self):
        # 徳島の阿波踊りに『鳴潮連』という連がある
        self.assertFalse(is_relevant("鳴門の阿波踊り『鳴潮連』豪華ステージ 椅子席は抽選"))

    def test_空文字は通さない(self):
        self.assertFalse(is_relevant(""))
        self.assertFalse(is_relevant(None))


class TestIsRealDate(unittest.TestCase):
    def test_実在する日付だけ通す(self):
        near = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        self.assertTrue(is_real_date(near))

    def test_形は合っていても存在しない日付は弾く(self):
        self.assertFalse(is_real_date("2026-99-99"))
        self.assertFalse(is_real_date("2026-02-30"))

    def test_書式が違うものは弾く(self):
        for bad in ["2026/08/12", "20260812", "", None, "近日公開"]:
            with self.subTest(bad=bad):
                self.assertFalse(is_real_date(bad))

    def test_現実的な範囲から外れたものは弾く(self):
        self.assertFalse(is_real_date("1999-01-01"))
        self.assertFalse(is_real_date("2099-01-01"))


class TestMergeVersionEntry(unittest.TestCase):
    def test_前回読めた情報を今回読めなくても消さない(self):
        prev = {"version": "1.3", "title": "拾遺散記", "date": "2026-06-05",
                "confirmed": True, "new_character_first": True}
        new = {"version": "1.3", "title": "", "date": "2026-06-05", "confirmed": True,
               "new_character_first": None}
        out = merge_version_entry(prev, new)
        self.assertEqual(out["title"], "拾遺散記")
        self.assertIs(out["new_character_first"], True)

    def test_新しい確定情報は取り込む(self):
        prev = {"version": "4.6", "title": "", "date": "2026-09-30", "confirmed": False}
        new = {"version": "4.6", "title": "", "date": "2026-10-07", "confirmed": True}
        out = merge_version_entry(prev, new)
        self.assertEqual(out["date"], "2026-10-07")
        self.assertTrue(out["confirmed"])

    def test_未確定の情報で確定日を上書きしない(self):
        prev = {"version": "7.0", "title": "", "date": "2026-08-12", "confirmed": True}
        new = {"version": "7.0", "title": "", "date": "2026-08-20", "confirmed": False}
        out = merge_version_entry(prev, new)
        self.assertEqual(out["date"], "2026-08-12")

    def test_新キャラ有無をFalseで上書きできる(self):
        prev = {"version": "7.0", "date": "2026-08-12", "confirmed": True,
                "new_character_second": True}
        new = {"version": "7.0", "date": "2026-08-12", "confirmed": True,
               "new_character_second": False}
        self.assertIs(merge_version_entry(prev, new)["new_character_second"], False)


class TestIsProtected(unittest.TestCase):
    """除外ワードの掃除が、人の判断を消さないことを確かめる。"""

    @staticmethod
    def page(adopted=False, status=None):
        props = {"採用": {"checkbox": adopted}}
        if status:
            props["制作状況"] = {"select": {"name": status}}
        return {"properties": props}

    def test_採用済みは保護する(self):
        self.assertTrue(is_protected(self.page(adopted=True))[0])

    def test_制作中と投稿済みと見送りは保護する(self):
        for status in ["制作中", "投稿済み", "見送り"]:
            with self.subTest(status=status):
                self.assertTrue(is_protected(self.page(status=status))[0])

    def test_未着手は保護しない(self):
        self.assertFalse(is_protected(self.page(status="未着手"))[0])

    def test_制作状況が未設定でも保護しない(self):
        self.assertFalse(is_protected(self.page())[0])


if __name__ == "__main__":
    unittest.main()
