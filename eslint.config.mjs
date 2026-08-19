import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = defineConfig([
  ...nextVitals,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // 動作確認用に置かれたまま残っている断片。UTF-16で保存されており
    // lint が解析に失敗してリポジトリ全体の検査が止まるため対象外にする。
    "test.js",
  ]),
]);

export default eslintConfig;
