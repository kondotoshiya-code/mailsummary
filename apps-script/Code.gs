/**
 * 毎日 朝8時・昼12時・夕方17時（日本時間）に Gmail を読み、
 * 「返信すべき / 対応すべき / キャッチアップ」に分類して
 * Google Chat に要約を送る Google Apps Script。
 *
 * 使い方は docs/apps-script手順.md を参照。
 */

/* ===================================================================== */
/*  ▼▼▼ ここに2つの値を貼り付けてください（クォート「'」の間だけ） ▼▼▼   */
/* ===================================================================== */

// ① Gemini の APIキー（AIza... で始まる文字列）
var GEMINI_API_KEY = 'ここにGeminiのAPIキーを貼る';

// ② Google Chat の Webhook URL（https://chat.googleapis.com/... ）
var CHAT_WEBHOOK_URL = 'ここにGoogle ChatのWebhook URLを貼る';

/* ===================================================================== */
/*  ▲▲▲ 貼り付けるのはこの2つだけ。これより下は触らなくてOK ▲▲▲        */
/* ===================================================================== */


// 使用する Gemini モデル（無料枠で利用可）。必要なら変更可。
var GEMINI_MODEL = 'gemini-2.0-flash';

// 1回の要約で扱う最大メール数（多すぎる場合の安全弁）
var MAX_EMAILS = 40;

// 本文として AI に渡す最大文字数
var MAX_BODY_CHARS = 2500;

// Google Chat の1メッセージあたりの安全な文字数上限
var MAX_MESSAGE_CHARS = 3800;

var TZ = 'Asia/Tokyo';


/**
 * 【最初に1回だけ実行】3つのトリガー（朝8/昼12/夕17時）を登録する。
 * メニューの関数選択で installTriggers を選び「実行」する。
 */
function installTriggers() {
  // 既存の同名トリガーを削除してから入れ直す
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'mailSummary') {
      ScriptApp.deleteTrigger(t);
    }
  });
  [8, 12, 17].forEach(function (h) {
    ScriptApp.newTrigger('mailSummary')
      .timeBased()
      .atHour(h)
      .everyDays(1)
      .inTimezone(TZ)
      .create();
  });
  Logger.log('トリガーを登録しました（毎日 8時・12時・17時 JST）。');
}


/**
 * 【動作確認用】直近24時間のメールで今すぐ1回実行する。
 */
function runTestNow() {
  var afterEpoch = Math.floor((Date.now() - 24 * 3600 * 1000) / 1000);
  mailSummary_(afterEpoch, '（テスト）');
}


/**
 * 【切り分け用】Gmail も Gemini も使わず、Google Chat に固定メッセージだけ送る。
 * これが届けば Webhook はOK。届かなければ Webhook URL の問題。
 */
function testWebhookOnly() {
  var webhook = cfgValue_(CHAT_WEBHOOK_URL, 'CHAT_WEBHOOK_URL');
  if (!webhook) {
    throw new Error('コード上部の CHAT_WEBHOOK_URL に Webhook URL を貼り付けてください。');
  }
  var res = UrlFetchApp.fetch(webhook, {
    method: 'post',
    contentType: 'application/json; charset=UTF-8',
    payload: JSON.stringify({ text: '✅ Webhookテスト：これが届けば送信先の設定はOKです。' }),
    muteHttpExceptions: true
  });
  Logger.log('応答コード: ' + res.getResponseCode());
  Logger.log('応答本文: ' + res.getContentText());
  if (res.getResponseCode() >= 300) {
    throw new Error('Webhook送信に失敗 (' + res.getResponseCode() + '): ' + res.getContentText());
  }
}


/**
 * トリガーから呼ばれる本番関数。
 */
function mailSummary() {
  var now = new Date();
  mailSummary_(computeAfterEpoch_(now), slotLabel_(now));
}


function mailSummary_(afterEpoch, slotLabelText) {
  var cfg = getConfig_();
  var emails = fetchEmails_(afterEpoch);
  Logger.log('取得メール: ' + emails.length + ' 件');

  var dateStr = Utilities.formatDate(new Date(), TZ, 'yyyy/MM/dd');

  if (emails.length === 0) {
    postToChat_(cfg.webhook, [
      '*📬 メールサマリー（' + slotLabelText + '）* — ' + dateStr +
      '\n\n新着で対応が必要なメールはありませんでした。✨'
    ]);
    return;
  }

  var items = classifyWithGemini_(emails, cfg.key);
  var messages = buildMessages_(items, slotLabelText, dateStr);
  postToChat_(cfg.webhook, messages);
  Logger.log('Google Chat に ' + messages.length + ' メッセージ送信しました。');
}


/* ===================== 設定の読み込み ===================== */

// コード上部の値を優先。空（プレースホルダのまま）ならスクリプト プロパティを見る。
function cfgValue_(codeValue, propName) {
  if (codeValue && codeValue.indexOf('ここに') === -1) {
    return codeValue.trim();
  }
  var p = PropertiesService.getScriptProperties().getProperty(propName);
  return p ? p.trim() : '';
}

function getConfig_() {
  var key = cfgValue_(GEMINI_API_KEY, 'GEMINI_API_KEY');
  var webhook = cfgValue_(CHAT_WEBHOOK_URL, 'CHAT_WEBHOOK_URL');
  if (!key || !webhook) {
    throw new Error(
      'コード上部の GEMINI_API_KEY と CHAT_WEBHOOK_URL に値を貼り付けてください' +
      '（クォート「\'」の間に貼る）。'
    );
  }
  return { key: key, webhook: webhook };
}


/* ===================== 時刻まわり ===================== */

function slotLabel_(now) {
  var hour = parseInt(Utilities.formatDate(now, TZ, 'H'), 10);
  if (hour < 10) return '朝';
  if (hour < 14) return '昼';
  return '夕方';
}

/**
 * このスロットで集計対象にする「これ以降」の時刻（UNIX秒）を返す。
 * 朝の実行は前日17時以降（夜間＋前日夕方分）をカバーする。
 */
function computeAfterEpoch_(now) {
  var hour = parseInt(Utilities.formatDate(now, TZ, 'H'), 10);
  var todayYmd = Utilities.formatDate(now, TZ, 'yyyy-MM-dd');
  var target;
  if (hour < 10) {
    var yesterday = new Date(now.getTime() - 24 * 3600 * 1000);
    var yYmd = Utilities.formatDate(yesterday, TZ, 'yyyy-MM-dd');
    target = new Date(yYmd + 'T17:00:00+09:00');
  } else if (hour < 14) {
    target = new Date(todayYmd + 'T08:00:00+09:00');
  } else {
    target = new Date(todayYmd + 'T12:00:00+09:00');
  }
  return Math.floor(target.getTime() / 1000);
}


/* ===================== Gmail 取得 ===================== */

function fetchEmails_(afterEpoch) {
  var query = 'in:inbox after:' + afterEpoch +
    ' -category:promotions -category:social';
  var threads = GmailApp.search(query, 0, MAX_EMAILS);
  var emails = [];
  threads.forEach(function (thread) {
    var msgs = thread.getMessages();
    var m = msgs[msgs.length - 1]; // スレッドの最新メッセージ
    var body = (m.getPlainBody() || '').replace(/\s+\n/g, '\n').trim();
    if (body.length > MAX_BODY_CHARS) {
      body = body.substring(0, MAX_BODY_CHARS) + ' …(以下省略)';
    }
    emails.push({
      from: m.getFrom(),
      subject: m.getSubject() || '(件名なし)',
      date: Utilities.formatDate(m.getDate(), TZ, 'MM/dd HH:mm'),
      body: body
    });
  });
  return emails;
}


/* ===================== Gemini で分類・要約 ===================== */

function classifyWithGemini_(emails, apiKey) {
  var list = emails.map(function (e, i) {
    return '[' + i + ']\n差出人: ' + e.from + '\n件名: ' + e.subject +
      '\n日時: ' + e.date + '\n本文抜粋:\n' + e.body + '\n';
  }).join('\n');

  var prompt =
    'あなたは多忙なビジネスパーソンの優秀な秘書です。\n' +
    '以下の受信メール一覧を読み、各メールを次の4カテゴリに分類し、日本語で簡潔に要約してください。\n\n' +
    'カテゴリ:\n' +
    '- "reply"  : 本人が「返信」すべきメール（質問・依頼・確認待ち・日程調整など返事待ち）\n' +
    '- "action" : 返信ではないが「対応・作業」が必要（承認・支払い・手続き・期限のあるタスク等）\n' +
    '- "catchup": 返信も対応も不要だが「把握」しておくと良い情報（連絡・議事録・進捗共有等）\n' +
    '- "ignore" : 広告・宣伝・自動通知・メルマガなど見る必要のないもの\n\n' +
    '各メールについて次のフィールドを持つJSONを返してください:\n' +
    '- index    : 入力と同じ番号（整数）\n' +
    '- category : reply / action / catchup / ignore のいずれか\n' +
    '- summary  : 日本語1〜2文の要約（何を求められているか）\n' +
    '- priority : high / medium / low\n' +
    '- deadline : 期限が読み取れれば日付、なければ空文字\n\n' +
    '出力は次の形式のJSONのみ:\n' +
    '{"items":[{"index":0,"category":"reply","summary":"...","priority":"high","deadline":""}]}\n\n' +
    '--- メール一覧 ---\n' + list;

  var url = 'https://generativelanguage.googleapis.com/v1beta/models/' +
    GEMINI_MODEL + ':generateContent?key=' + encodeURIComponent(apiKey);

  var payload = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: 0.2,
      responseMimeType: 'application/json'
    }
  };

  var res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  if (res.getResponseCode() !== 200) {
    throw new Error('Gemini API エラー (' + res.getResponseCode() + '): ' +
      res.getContentText().substring(0, 500));
  }

  var data = JSON.parse(res.getContentText());
  var text = data.candidates[0].content.parts[0].text;
  var parsed = JSON.parse(text);
  var byIndex = {};
  (parsed.items || []).forEach(function (it) { byIndex[it.index] = it; });

  return emails.map(function (e, i) {
    var it = byIndex[i] || {};
    var cat = it.category;
    if (['reply', 'action', 'catchup', 'ignore'].indexOf(cat) === -1) cat = 'catchup';
    return {
      email: e,
      category: cat,
      summary: it.summary || e.subject,
      priority: it.priority || 'medium',
      deadline: it.deadline || ''
    };
  });
}


/* ===================== Google Chat メッセージ整形 ===================== */

function buildMessages_(items, slotLabelText, dateStr) {
  var groups = { reply: [], action: [], catchup: [] };
  items.forEach(function (c) {
    if (groups[c.category]) groups[c.category].push(c);
  });

  var order = { high: 0, medium: 1, low: 2 };
  Object.keys(groups).forEach(function (k) {
    groups[k].sort(function (a, b) {
      return (order[a.priority] || 1) - (order[b.priority] || 1);
    });
  });

  var mark = { high: '🔴', medium: '🟡', low: '⚪' };
  var sections = [
    ['reply', '✉️ *返信すべきメール*'],
    ['action', '✅ *対応すべきメール*'],
    ['catchup', '📰 *キャッチアップ（把握しておくと良い内容）*']
  ];

  var header = '*📬 メールサマリー（' + slotLabelText + '）* — ' + dateStr + '\n' +
    '返信 ' + groups.reply.length + '件 / 対応 ' + groups.action.length +
    '件 / キャッチアップ ' + groups.catchup.length + '件';

  if (groups.reply.length + groups.action.length + groups.catchup.length === 0) {
    return [header + '\n\n新着で対応が必要なメールはありませんでした。✨'];
  }

  var lines = [header];
  sections.forEach(function (s) {
    var arr = groups[s[0]];
    if (arr.length === 0) return;
    lines.push('');
    lines.push(s[1] + '（' + arr.length + '件）');
    arr.forEach(function (c) {
      var sender = shortSender_(c.email.from);
      var deadline = c.deadline ? ' 〆' + c.deadline : '';
      lines.push((mark[c.priority] || '🟡') + ' *' + c.email.subject + '*（' + sender + '）' + deadline);
      lines.push('　' + c.summary);
    });
  });

  return splitMessages_(lines);
}

function shortSender_(from) {
  var m = /^\s*"?([^"<]+?)"?\s*</.exec(from);
  return m ? m[1].trim() : from.trim();
}

function splitMessages_(lines) {
  var messages = [];
  var current = [];
  var length = 0;
  lines.forEach(function (line) {
    var add = line.length + 1;
    if (length + add > MAX_MESSAGE_CHARS && current.length > 0) {
      messages.push(current.join('\n'));
      current = [];
      length = 0;
    }
    current.push(line);
    length += add;
  });
  if (current.length > 0) messages.push(current.join('\n'));
  return messages;
}


/* ===================== Google Chat 送信 ===================== */

function postToChat_(webhookUrl, messages) {
  messages.forEach(function (text) {
    var res = UrlFetchApp.fetch(webhookUrl, {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      payload: JSON.stringify({ text: text }),
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 300) {
      throw new Error('Google Chat 送信エラー (' + res.getResponseCode() + '): ' +
        res.getContentText().substring(0, 300));
    }
  });
}
