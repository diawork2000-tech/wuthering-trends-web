import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retranslate_titles import needs_translation
from sns_collector import detect_lang

LANGS = {"韓国語", "中国語"}


def row(title, category="切り抜き", lang="", original=""):
    return {"properties": {
        "タイトル": {"title": [{"plain_text": title}]},
        "カテゴリ": {"select": {"name": category}},
        "言語": {"select": {"name": lang} if lang else None},
        "原文": {"rich_text": [{"plain_text": original}] if original else []},
    }}


class TestNeedsTranslation(unittest.TestCase):
    def test_targets(self):
        self.assertTrue(needs_translation(row("Best team guide"), LANGS))
        self.assertTrue(needs_translation(row("릴리의 숙면 가이드", "SNS", "韓国語"), LANGS))
        # 断られた回の行は、原文が見出しと同じまま入っていることがある
        self.assertTrue(needs_translation(row("Best team", original="Best team"), LANGS))

    def test_skips(self):
        for r in (row("やさしい解説"), row("abc.mp4", "広告"), row("Good morning", "SNS", "英語"),
                  row("┌|∵|┘ 😭"), row("#WuWa https://t.co/abc"),
                  row("最強編成", original="最强配队")):
            self.assertFalse(needs_translation(r, LANGS))


class TestDetectLangIgnoresTags(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(detect_lang("Good morning #WuWa #鳴潮"), "en")
        self.assertEqual(detect_lang("今日的新角色 #鳴潮"), "zh-CN")
        self.assertEqual(detect_lang("#鸣潮"), "zh-CN")
        self.assertEqual(detect_lang("Lily #めいちょう"), "ja")


if __name__ == "__main__":
    unittest.main()
