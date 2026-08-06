#!/usr/bin/env bash
#
# Vercel の Ignored Build Step から呼ばれる。
#   終了コード 0 → ビルドをスキップ
#   終了コード 1 → ビルドを実行
#
# 15分おき/毎時の自動収集が書き込むデータファイルは、どれも画面表示のたびに
# GitHub や Notion から直接読み込まれる。つまりこれらだけが変わったコミットで
# 再ビルドしても、サイトの表示内容は一切変わらない。
# 無料枠(1日100デプロイ)を使い切らないよう、その場合はビルドを飛ばす。
#
# ※ ignoreCommand は256文字までしか書けないため、処理をこのファイルに逃がしている。

set -u

# 自動生成されるデータファイル。これ以外に変更があれば必ずビルドする。
GENERATED=(
  ':(exclude)scraper/logs.json'
  ':(exclude)scraper/config_intelligence.json'
  ':(exclude)scraper/intelligence_logs.json'
  ':(exclude)src/data/intelligence_cache.json'
  ':(exclude)src/data/upcoming_schedule.json'
)

# マージコミットの場合、HEAD^ は自分側の親を指すため、差分には相手側から
# 入ってきた変更しか現れない。コード変更を取りこぼしてスキップしてしまうので
# マージコミットは無条件でビルドする。
if git rev-parse -q --verify HEAD^2 >/dev/null 2>&1; then
  echo "[vercel-ignore] マージコミットのためビルドします"
  exit 1
fi

# 親が取得できない(浅いクローンの先端など)場合も、安全側に倒してビルドする。
if ! git rev-parse -q --verify HEAD^ >/dev/null 2>&1; then
  echo "[vercel-ignore] 直前のコミットを参照できないためビルドします"
  exit 1
fi

if git diff --quiet HEAD^ HEAD -- . "${GENERATED[@]}"; then
  echo "[vercel-ignore] 自動収集のデータ更新のみのためスキップします"
  exit 0
fi

echo "[vercel-ignore] コード等の変更を検出したためビルドします"
exit 1
