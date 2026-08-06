import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

// 採用したネタから、ショート動画の台本のたたき台を作る。
// 収集の巡回とは違い「採用したときだけ」呼ぶので、Gemini の消費は1日数回で収まる。
export async function POST(request) {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      {
        error:
          'GEMINI_API_KEY が Vercel 側に設定されていません。Vercel のプロジェクト設定で環境変数を追加すると台本生成が使えるようになります。',
      },
      { status: 503 }
    );
  }

  try {
    const { title, outline, reason, seconds } = await request.json();
    if (!title) {
      return NextResponse.json({ error: 'title is required' }, { status: 400 });
    }

    const length = seconds === 60 ? 60 : 30;
    const prompt = [
      'あなたはゲーム『鳴潮』専門のショート動画作家です。',
      `以下のネタから、${length}秒のYouTubeショート台本のたたき台を作ってください。`,
      '',
      '条件:',
      `1. 全体で${length}秒で読み切れる分量に収めること（${length === 30 ? '目安250〜300字' : '目安500〜600字'}）。`,
      '2. 冒頭2秒で必ず視聴者の手を止める一言から始めること。ただし「〜をご存じですか？」のような手垢のついた定型は禁止。',
      '3. 視聴者が最後まで見る理由を、序盤で明示すること。',
      '4. 断定を避けた曖昧な表現は使わず、結論をはっきり言い切ること。',
      '5. 出力は純粋なJSONオブジェクトのみ。Markdownコードブロックは不可。',
      '',
      '形式:',
      '{',
      '  "hook": "冒頭2秒のセリフ",',
      '  "body": ["本編のセリフを1文ずつ配列で", "..."],',
      '  "closing": "締めのセリフ",',
      '  "titles": ["動画タイトル案1", "案2", "案3"],',
      '  "thumbnail_texts": ["サムネ文言案1", "案2"],',
      '  "assets": ["撮影・収録が必要な素材1", "素材2"]',
      '}',
      '',
      `ネタの見出し: ${title}`,
      `ネタの詳細: ${String(outline || '').slice(0, 2000)}`,
      `注目されている理由: ${String(reason || '').slice(0, 500)}`,
    ].join('\n');

    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
        cache: 'no-store',
      }
    );

    if (!res.ok) {
      const errText = await res.text();
      // 無料枠を使い切っているケースが最も多いので、原因を切り分けられる文言にする
      if (res.status === 429) {
        return NextResponse.json(
          { error: 'Gemini の利用枠を使い切っています。時間をおいて再度お試しください。' },
          { status: 429 }
        );
      }
      throw new Error(`Gemini API Error: ${res.status} ${errText}`);
    }

    const data = await res.json();
    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text || '';
    const cleaned = text.replace(/^```(json)?/gm, '').replace(/```$/gm, '').trim();

    let script;
    try {
      script = JSON.parse(cleaned);
    } catch {
      // JSON として解釈できなかった場合でも、生成本文は捨てずに返す
      return NextResponse.json({ success: true, raw: cleaned });
    }

    return NextResponse.json({ success: true, script });
  } catch (error) {
    console.error('Script generation failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
