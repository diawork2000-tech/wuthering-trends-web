// GitHub リポジトリを設定ファイル置き場 兼 ジョブ起動口として使うための共通ヘルパー。
// 以前は API ルート 7 本それぞれに owner/name/branch が直書きされていたため、
// リポジトリ名を変えると 7 箇所を直す必要があった。ここに集約する。

export const REPO_OWNER = process.env.GITHUB_REPO_OWNER || 'diawork2000-tech';
export const REPO_NAME = process.env.GITHUB_REPO_NAME || 'wuthering-trends-web';
export const BRANCH = process.env.GITHUB_BRANCH || 'main';

const CONTENTS_URL = (filePath) =>
  `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${filePath}`;

/** GITHUB_PAT を取り出す。未設定なら呼び出し側で 500 を返せるよう例外にする。 */
function requirePat() {
  const pat = process.env.GITHUB_PAT;
  if (!pat) {
    throw new Error('GITHUB_PAT is missing');
  }
  return pat;
}

function authHeaders(pat) {
  return {
    Authorization: `token ${pat}`,
    Accept: 'application/vnd.github.v3+json',
  };
}

/**
 * リポジトリ上の JSON ファイルを読む。
 * ファイルが存在しない場合は例外ではなく null を返す（ログ系は「まだ無い」が正常なため）。
 */
export async function readRepoJson(filePath) {
  const pat = requirePat();
  const res = await fetch(`${CONTENTS_URL(filePath)}?ref=${BRANCH}`, {
    headers: authHeaders(pat),
    cache: 'no-store',
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GitHub API Error: ${res.status}`);
  }

  const data = await res.json();
  const content = Buffer.from(data.content, 'base64').toString('utf-8');
  return { json: JSON.parse(content), sha: data.sha };
}

/**
 * リポジトリ上の JSON ファイルを書き換える。
 *
 * GitHub Actions 側も同じファイルを commit するため、Web UI を開いたまま放置すると
 * 手元の sha が古くなり 409 で保存が弾かれる。その都度ユーザーが画面を開き直して
 * 入力し直すのは手間なので、競合したら最新 sha を取り直して一度だけ自動リトライする。
 *
 * @param onConflict (remoteJson, localJson) => merged
 *        競合時にリモート側の変更をどう取り込むか。省略時はローカル側で上書き。
 */
export async function writeRepoJson(filePath, json, sha, message, { onConflict } = {}) {
  const pat = requirePat();

  const put = async (body, currentSha) => {
    const content = Buffer.from(JSON.stringify(body, null, 2), 'utf-8').toString('base64');
    return fetch(CONTENTS_URL(filePath), {
      method: 'PUT',
      headers: { ...authHeaders(pat), 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, content, sha: currentSha, branch: BRANCH }),
    });
  };

  let res = await put(json, sha);

  // 409 (sha 競合) / 422 (sha 不一致) は Actions が先にコミットしたケース。
  if (res.status === 409 || res.status === 422) {
    const latest = await readRepoJson(filePath);
    if (latest) {
      const merged = onConflict ? onConflict(latest.json, json) : json;
      res = await put(merged, latest.sha);
    }
  }

  if (!res.ok) {
    throw new Error(`GitHub API Error: ${res.status} ${await res.text()}`);
  }
  return true;
}

/** GitHub Actions の repository_dispatch を叩いてワークフローを起動する。 */
export async function dispatchWorkflow(eventType, clientPayload = {}) {
  const pat = requirePat();
  const res = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/dispatches`,
    {
      method: 'POST',
      headers: { ...authHeaders(pat), 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, client_payload: clientPayload }),
      cache: 'no-store',
    }
  );

  if (!res.ok) {
    throw new Error(`GitHub dispatch failed: ${res.status} ${await res.text()}`);
  }
  return true;
}
