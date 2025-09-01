/**
 * Cloudflare Workers - ランプ監視システム用通知ハンドラー（HMAC署名検証版）
 * * 機能:
 * 1. POSTリクエストのみ受け付ける
 * 2. HTTPヘッダーから 'x-signature-256' を読み取る
 * 3. リクエストボディと環境変数 'SECRET_KEY' を使って署名を検証する
 * 4. 署名が有効な場合のみ、環境変数 'DISCORD_WEBHOOK_URL' に通知を転送する
 */
export default {
  async fetch(request, env) {
    // POST以外のリクエストは拒否
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // 1. ヘッダーから署名を取得 (小文字で取得するのが一般的)
    const signature = request.headers.get("x-signature-256");
    if (!signature) {
      console.log("署名ヘッダー (x-signature-256) が見つかりませんでした。");
      return new Response("Unauthorized - Signature Required", { status: 401 });
    }

    // 2. リクエストボディの生テキストを取得
    const bodyText = await request.clone().text();

    // 3. 署名が有効か検証
    const isValid = await verifySignature(bodyText, signature, env.SECRET_KEY);

    if (!isValid) {
      console.log("無効な署名です。");
      return new Response("Unauthorized - Invalid Signature", { status: 401 });
    }

    // 4. 署名が正しければ、Discordへ通知
    try {
      const body = JSON.parse(bodyText);
      const message =
        body.message ||
        `ランプ ${body.lamp_id} が ${body.state} 状態になりました！`;
      const payload = { content: message };

      const discordResponse = await fetch(env.DISCORD_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!discordResponse.ok) {
        console.log(
          "Discordへの送信に失敗しました:",
          await discordResponse.text()
        );
        return new Response("Failed to send Discord notification.", {
          status: 500,
        });
      }

      return new Response("Notification sent successfully.", { status: 200 });
    } catch (e) {
      console.log("JSONのパースまたは通知処理中にエラー:", e.message);
      return new Response("Bad Request", { status: 400 });
    }
  },
};

// --- 署名検証のためのヘルパー関数 ---

async function verifySignature(body, signature, secret) {
  // 環境変数が設定されているか確認
  if (typeof secret !== "string" || secret.length === 0) {
    console.log("エラー: 環境変数 'SECRET_KEY' が設定されていません。");
    return false;
  }

  // 署名が 'sha256=...' の形式か確認
  const [algo, sigHex] = signature.split("=");
  if (algo !== "sha256" || !sigHex) {
    return false;
  }

  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const sigBuffer = hexToBuffer(sigHex);
    const data = encoder.encode(body);
    return await crypto.subtle.verify("HMAC", key, sigBuffer, data);
  } catch (e) {
    console.log("署名検証中に内部エラー:", e.message);
    return false;
  }
}

// 16進数文字列をArrayBufferに変換する関数
function hexToBuffer(hex) {
  const buffer = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    buffer[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return buffer;
}
