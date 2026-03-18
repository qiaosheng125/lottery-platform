/**
 * 票面渲染工具
 * 样式参考 aaa-main/templates/dashboard.html getPlayTypeColors()
 */

// 按玩法类型返回配色方案
function getPlayTypeColors(lotteryType) {
  if (!lotteryType) lotteryType = '';
  if (lotteryType.indexOf('胜平负') !== -1) {
    return {
      header: 'background:#3d6fd4;color:#fff',
      badge:  'background:#17a2b8;color:#fff',
      border: '#3d6fd4',
    };
  } else if (lotteryType.indexOf('半全场') !== -1) {
    return {
      header: 'background:#28a745;color:#fff',
      badge:  'background:#28a745;color:#fff',
      border: '#28a745',
    };
  } else if (lotteryType.indexOf('比分') !== -1) {
    return {
      header: 'background:#c0392b;color:#fff',
      badge:  'background:#c0392b;color:#fff',
      border: '#c0392b',
    };
  } else if (lotteryType.indexOf('上下盘') !== -1) {
    return {
      header: 'background:#c9960c;color:#1a1a1a',
      badge:  'background:#c9960c;color:#1a1a1a',
      border: '#c9960c',
    };
  } else if (lotteryType.indexOf('胜负') !== -1) {
    return {
      header: 'background:#17a2b8;color:#1a1a1a',
      badge:  'background:#17a2b8;color:#1a1a1a',
      border: '#17a2b8',
    };
  } else if (lotteryType.indexOf('总进球') !== -1) {
    return {
      header: 'background:#2c2c2c;color:#fff',
      badge:  'background:#2c2c2c;color:#fff',
      border: '#2c2c2c',
    };
  }
  return {
    header: 'background:#6f42c1;color:#fff',
    badge:  'background:#6f42c1;color:#fff',
    border: '#6f42c1',
  };
}

/**
 * 解析票面原始内容
 * 格式: {玩法}|{场次选项}|{场次数*1}|{最终倍数}
 */
function parseTicketContent(raw) {
  const parts = raw.trim().split('|');
  if (parts.length < 4) return null;

  const betCode = parts[0].trim().toUpperCase();
  const fieldsStr = parts[1].trim();
  const finalMult = parseInt(parts[3].trim(), 10) || 1;

  const fields = {};
  fieldsStr.split(',').forEach(part => {
    const eqIdx = part.indexOf('=');
    if (eqIdx < 0) return;
    const fieldNo = part.substring(0, eqIdx).trim();
    const opts = part.substring(eqIdx + 1).split('/').map(o => o.trim()).filter(Boolean);
    if (opts.length > 0) fields[fieldNo] = opts;
  });

  // 金额 = 2 × 各场次选项积 × 最终倍率
  let product = 1;
  Object.values(fields).forEach(opts => { product *= opts.length; });
  const amount = 2 * product * finalMult;

  return { betCode, fields, finalMult, amount };
}

const BET_TYPE_NAMES = {
  SPF: '胜平负', BQC: '半全场', CBF: '比分',
  SF: '胜负', JQS: '总进球', SXP: '上下盘',
};

/**
 * 生成票面HTML，样式与 aaa-main dashboard 一致
 * lotteryType: 从文件名解析的类型（如"胜平负"），用于配色
 */
function renderTicketHTML(raw, lotteryType) {
  const parsed = parseTicketContent(raw);
  if (!parsed) {
    return `<div class="font-monospace small p-2" style="word-break:break-all">${raw}</div>`;
  }

  const { betCode, fields, finalMult, amount } = parsed;
  // 优先用传入的 lotteryType，fallback 到 betCode 映射
  const typeName = lotteryType || BET_TYPE_NAMES[betCode] || betCode;
  const colors = getPlayTypeColors(typeName);

  // 按场次号排序
  const fieldNos = Object.keys(fields).sort((a, b) => parseInt(a) - parseInt(b));

  let matchRows = fieldNos.map(no => {
    const opts = fields[no];
    // 每行最多4个badge
    let badgeRows = '';
    for (let i = 0; i < opts.length; i += 4) {
      const rowOpts = opts.slice(i, i + 4);
      const badges = rowOpts.map(o =>
        `<span class="badge m-1 ticket-badge" style="${colors.badge}">${o}</span>`
      ).join('');
      badgeRows += `<div class="d-flex flex-wrap justify-content-center mb-1">${badges}</div>`;
    }
    return `
      <div class="mb-1 match-card" style="border:1px solid ${colors.border};border-radius:4px;overflow:hidden">
        <div class="py-1 px-2 text-center match-header" style="${colors.header}">
          <strong class="match-number">场次 [${no}]</strong>
        </div>
        <div class="py-1 px-1 text-center" style="background:#fff">
          ${badgeRows}
        </div>
      </div>`;
  }).join('');

  return `
    <div class="ticket-render" style="background:#1a1a2e;border-radius:6px;overflow:hidden;padding-bottom:4px">
      <div class="text-center py-2 px-3 ticket-header" style="background:#6f42c1;color:#fff">
        <div class="ticket-type">${typeName}${finalMult}倍投</div>
        <div class="ticket-amount">金额 ${amount} 元</div>
      </div>
      <div class="px-2 pt-2">${matchRows}</div>
      <div class="text-center py-2 ticket-footer" style="color:#2ecc71">
        总金额: ${amount} 元
      </div>
    </div>`;
}
