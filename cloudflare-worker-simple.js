// Cloudflare Workers - ランプ監視システム用通知ハンドラー（シンプル版）
addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

const ALLOWED_SECRET = "pA!M.k_)!$G.vABQ9aeQmPNM";

async function handleRequest(request) {
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  let lampId = "";
  let state = "";
  let secret = "";
  let message = "";

  try {
    const body = await request.json();
    lampId = body.lamp_id || "";
    state = body.state || "";
    secret = body.secret || "";
    message = body.message || "";

    if (secret !== ALLOWED_SECRET) {
      console.log("シークレット不一致:", secret);
      return new Response("Unauthorized", { status: 401 });
    }

    console.log("Received lamp_id:", lampId, "state:", state);
  } catch (e) {
    console.log("JSON parse error:", e);
    return new Response("Bad Request", { status: 400 });
  }

  // 通知メッセージを作成
  const notificationMessage = message
    ? message
    : `ランプ ${lampId} が ${state} 状態になりました！`;

  const payload = { content: notificationMessage };

  const discordWebhookUrl =
    "https://discord.com/api/webhooks/1347020516829040791/2zIW9_ADomhqlt8EUUem9GydtQ2uMQ6ju3BswoiJyLUsTUdyouY-bFupd-6P7I-PNoFG";

  const discordResponse = await fetch(discordWebhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!discordResponse.ok) {
    console.log("Discord送信エラー:", await discordResponse.text());
    return new Response("Discord通知送信に失敗しました。", { status: 500 });
  }

  return new Response("Discord通知を送信しました。", { status: 200 });
}
