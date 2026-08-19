// ピックアップAPIの判定部分のテスト。
// Node同梱のテストランナーで動くので、追加のライブラリは要らない。
//   実行: npm test
//
// ここで守りたいのは「人の判断を壊さないこと」の1点。
// 過去に実際に起きた事故を、そのままテストにしてある。

import test from 'node:test';
import assert from 'node:assert/strict';
import { extractVideoId, parsePatchBody } from '../src/lib/pickup-helpers.js';

const ID_A = '3b882a7701b081b58424f99fee8091f2';
const ID_B = '3b882a77-01b0-810a-a9d8-c98bd785d887';

test('YouTubeのURLから動画IDを取り出す', () => {
  assert.equal(extractVideoId('https://www.youtube.com/watch?v=45ohbCDiAzQ'), '45ohbCDiAzQ');
  assert.equal(extractVideoId('https://youtu.be/45ohbCDiAzQ'), '45ohbCDiAzQ');
  assert.equal(extractVideoId('https://www.youtube.com/shorts/45ohbCDiAzQ'), '45ohbCDiAzQ');
  assert.equal(extractVideoId('https://m.youtube.com/watch?v=45ohbCDiAzQ'), '45ohbCDiAzQ');
});

test('YouTube以外のURLは動画IDとして扱わない', () => {
  // ここが緩いと、たまたま ?v= を持つ別サイトの記事が同じ動画として
  // 名寄せされ、解除時にまとめて巻き込まれる
  assert.equal(extractVideoId('https://example.com/watch?v=45ohbCDiAzQ'), '');
  assert.equal(extractVideoId('https://note.com/article?v=45ohbCDiAzQ'), '');
});

test('11文字でないIDは受け付けない', () => {
  assert.equal(extractVideoId('https://www.youtube.com/watch?v=short'), '');
  assert.equal(extractVideoId('https://www.youtube.com/watch?v=waytoolongvalue123'), '');
});

test('壊れたURLでも例外を投げない', () => {
  assert.equal(extractVideoId('not a url'), '');
  assert.equal(extractVideoId(''), '');
  assert.equal(extractVideoId(null), '');
});

test('制作状況だけを送ったとき、採用は書き換えない', () => {
  // 修正前は採用が無条件に代入され、status だけ送ると採用が外れていた。
  // 「制作状況を変えたつもりがピックアップから消える」事故の再発防止。
  const r = parsePatchBody({ ids: [ID_A], status: '制作中' });
  assert.equal(r.error, undefined);
  assert.deepEqual(Object.keys(r.properties), ['制作状況']);
});

test('採用だけを送ったとき、制作状況は書き換えない', () => {
  const r = parsePatchBody({ ids: [ID_A], adopted: false });
  assert.deepEqual(Object.keys(r.properties), ['採用']);
  assert.equal(r.properties['採用'].checkbox, false);
});

test('重複したIDはまとめられる', () => {
  // 名寄せで束ねた行を平坦化して送るため、同じIDが複数回入りうる
  const r = parsePatchBody({ ids: [ID_A, ID_A, ID_A], adopted: false });
  assert.deepEqual(r.ids, [ID_A]);
});

test('更新する項目が無い要求は拒否する', () => {
  const r = parsePatchBody({ ids: [ID_A] });
  assert.match(r.error, /adopted か status/);
});

test('IDの形式を検証する', () => {
  assert.match(parsePatchBody({ ids: 'abc' }).error, /配列/);
  assert.match(parsePatchBody({ ids: ['not-an-id'], adopted: false }).error, /不正/);
  assert.match(parsePatchBody({ ids: [], adopted: false }).error, /ids is required/);
  assert.equal(parsePatchBody({ ids: [ID_B], adopted: false }).error, undefined);
});

test('存在しない制作状況は拒否する', () => {
  assert.match(parsePatchBody({ ids: [ID_A], status: '完了' }).error, /いずれか/);
});

test('件数の上限を超える要求は拒否する', () => {
  const many = Array.from({ length: 201 }, (_, i) =>
    i.toString(16).padStart(32, '0')
  );
  assert.match(parsePatchBody({ ids: many, adopted: false }).error, /200 件まで/);
});
