// Cloudflare Workers - ランプ監視システム用通知ハンドラー
addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

// 共通鍵（config.yamlのsecretと一致させる）
const ALLOWED_SECRET = "pA!M.k_)!$G.vABQ9aeQmPNM";

// Discord Webhook URL（環境変数から取得することを推奨）
const DISCORD_WEBHOOK_URL =
  "https://discord.com/api/webhooks/1410427865874305057/FfrSwdzlxyjlemcXPfzek-oKjYgomypzr75-kp9VeocIK5Uak0aQNBoToPUEhQ43rkAg";

async function handleRequest(request) {
  // CORS対応
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Signature",
      },
    });
  }

  if (request.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: {
        "Access-Control-Allow-Origin": "*",
      },
    });
  }

  let requestData = {};
  let signature = "";

  try {
    // リクエストボディを取得
    const body = await request.text();
    requestData = JSON.parse(body);

    // HMAC署名検証（オプション）
    signature = request.headers.get("X-Signature") || "";

    if (ALLOWED_SECRET && signature) {
      const isValidSignature = await verifySignature(
        body,
        signature,
        ALLOWED_SECRET
      );
      if (!isValidSignature) {
        console.log("署名検証失敗:", signature);
        return new Response("Unauthorized - Invalid Signature", {
          status: 401,
          headers: { "Access-Control-Allow-Origin": "*" },
        });
      }
    } else if (ALLOWED_SECRET && !signature) {
      console.log("署名が必要ですが提供されていません");
      return new Response("Unauthorized - Signature Required", {
        status: 401,
        headers: { "Access-Control-Allow-Origin": "*" },
      });
    }

    console.log("受信データ:", requestData);
  } catch (e) {
    console.log("JSON parse error:", e);
    return new Response("Bad Request", {
      status: 400,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  }

  // 通知メッセージを作成
  const message = createNotificationMessage(requestData);

  // Discord Embedを作成
  const embed = createDiscordEmbed(requestData);

  const payload = {
    content: message,
    embeds: [embed],
  };

  // Discord Webhookに送信
  try {
    const discordResponse = await fetch(DISCORD_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!discordResponse.ok) {
      const errorText = await discordResponse.text();
      console.log("Discord送信エラー:", errorText);
      return new Response("Discord通知送信に失敗しました。", {
        status: 500,
        headers: { "Access-Control-Allow-Origin": "*" },
      });
    }

    console.log("Discord通知送信成功");
    return new Response("Discord通知を送信しました。", {
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  } catch (error) {
    console.log("Discord送信例外:", error);
    return new Response("Discord通知送信中にエラーが発生しました。", {
      status: 500,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  }
}

function createNotificationMessage(data) {
  const lampId = data.lamp_id || "不明";
  const state = data.state || "不明";
  const confidence = data.confidence || 0;
  const timestamp = data.timestamp || Math.floor(Date.now() / 1000);

  // 日本時間に変換
  const date = new Date(timestamp * 1000);
  const jstDate = new Date(date.getTime() + 9 * 60 * 60 * 1000); // UTC+9
  const timeString = jstDate.toLocaleString("ja-JP");

  let emoji = "";
  let statusText = "";

  switch (state) {
    case "RED":
      emoji = "🔴";
      statusText = "異常";
      break;
    case "GREEN":
      emoji = "🟢";
      statusText = "正常";
      break;
    default:
      emoji = "⚪";
      statusText = "不明";
      break;
  }

  return (
    `${emoji} **制御盤ランプ監視アラート**\n` +
    `ランプ ${lampId} が **${statusText}** 状態になりました！\n` +
    `時刻: ${timeString}`
  );
}

function createDiscordEmbed(data) {
  const lampId = data.lamp_id || "不明";
  const state = data.state || "不明";
  const confidence = (data.confidence || 0) * 100;
  const timestamp = data.timestamp || Math.floor(Date.now() / 1000);
  const message = data.message || "";

  let color = 0x808080; // グレー（不明）
  let title = "";

  switch (state) {
    case "RED":
      color = 0xff0000; // 赤
      title = "🚨 異常検出";
      break;
    case "GREEN":
      color = 0x00ff00; // 緑
      title = "✅ 正常復旧";
      break;
    default:
      title = "❓ 状態不明";
      break;
  }

  return {
    title: title,
    description: message,
    color: color,
    fields: [
      {
        name: "ランプ番号",
        value: `L${lampId}`,
        inline: true,
      },
      {
        name: "状態",
        value: state,
        inline: true,
      },
      {
        name: "信頼度",
        value: `${confidence.toFixed(1)}%`,
        inline: true,
      },
    ],
    timestamp: new Date(timestamp * 1000).toISOString(),
    footer: {
      text: "制御盤ランプ監視システム",
    },
  };
}

async function verifySignature(body, signature, secret) {
  try {
    // 署名形式: "sha256=ハッシュ値"
    if (!signature.startsWith("sha256=")) {
      return false;
    }

    const receivedHash = signature.substring(7);

    // HMAC-SHA256で署名を計算
    const encoder = new TextEncoder();
    const keyData = encoder.encode(secret);
    const messageData = encoder.encode(body);

    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      keyData,
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );

    const signatureBuffer = await crypto.subtle.sign(
      "HMAC",
      cryptoKey,
      messageData
    );
    const computedHash = Array.from(new Uint8Array(signatureBuffer))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

    // 定数時間比較
    return computedHash === receivedHash;
  } catch (error) {
    console.log("署名検証エラー:", error);
    return false;
  }
}
