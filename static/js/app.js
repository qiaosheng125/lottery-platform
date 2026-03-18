// 生成或获取设备唯一ID
function getOrCreateDeviceId() {
  let id = localStorage.getItem('lottery_device_id');
  if (!id) {
    id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
    localStorage.setItem('lottery_device_id', id);
  }
  return id;
}

// 获取设备名称（本地缓存）
function getDeviceName() {
  return localStorage.getItem('lottery_device_name') || '';
}

// 保存设备名称
function saveDeviceName(name) {
  localStorage.setItem('lottery_device_name', name);
}

// 注册设备并检查是否需要命名
async function registerDeviceAndCheckName() {
  const deviceId = getOrCreateDeviceId();
  const deviceName = getDeviceName();
  try {
    const res = await fetch('/api/device/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ device_id: deviceId, device_name: deviceName || undefined }),
    });
    const data = await res.json();

    // 检查设备名重复
    if (!data.success && data.duplicate) {
      showToast(data.error, 'warning');
      showDeviceNamePrompt(deviceId, data.error);
      return;
    }
  } catch(e) {}

  if (!deviceName) {
    showDeviceNamePrompt(deviceId);
  }
}

// 显示设备命名弹窗
function showDeviceNamePrompt(deviceId, errorMsg = '') {
  // Remove any existing prompt
  const existing = document.getElementById('device-name-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'device-name-modal';
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:#fff;border-radius:8px;padding:24px;width:320px;max-width:90vw;">
      <h5 class="mb-3"><i class="bi bi-device-hdd"></i> 设置设备名称</h5>
      ${errorMsg ? `<div class="alert alert-warning py-2 small mb-2">${errorMsg}</div>` : ''}
      <p class="text-muted small mb-3">请为此设备起一个便于识别的名称（如"台式机"、"手机1"）</p>
      <input type="text" id="device-name-input" class="form-control mb-3"
             placeholder="输入设备名称" maxlength="20" autofocus>
      <div class="d-flex gap-2">
        <button class="btn btn-primary flex-grow-1" onclick="submitDeviceName('${deviceId}')">确认</button>
        <button class="btn btn-outline-secondary" onclick="submitDeviceName('${deviceId}', true)">跳过</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  // Allow Enter key to submit
  document.getElementById('device-name-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitDeviceName(deviceId);
  });
}

async function submitDeviceName(deviceId, skip = false) {
  const input = document.getElementById('device-name-input');
  const name = skip ? ('设备_' + deviceId.substring(0, 4)) : (input ? input.value.trim() : '');
  if (!skip && !name) {
    input && input.classList.add('is-invalid');
    return;
  }

  const finalName = name || ('设备_' + deviceId.substring(0, 4));
  saveDeviceName(finalName);

  try {
    const res = await fetch(`/api/device/${deviceId}/name`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ name: finalName }),
    });
    const data = await res.json();

    // 检查设备名重复
    if (!data.success) {
      showToast(data.error, 'danger');
      if (input) {
        input.classList.add('is-invalid');
        input.focus();
      }
      return;
    }
  } catch(e) {
    showToast('网络错误，请重试', 'danger');
    return;
  }

  const modal = document.getElementById('device-name-modal');
  if (modal) modal.remove();
}

// Toast notification
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container') || (() => {
    const el = document.createElement('div');
    el.id = 'toast-container';
    el.className = 'position-fixed bottom-0 end-0 p-3';
    el.style.zIndex = 9999;
    document.body.appendChild(el);
    return el;
  })();

  const toast = document.createElement('div');
  toast.className = `toast align-items-center text-bg-${type} border-0 show`;
  toast.role = 'alert';
  toast.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 3500);
}

// Add btn-xs style
const style = document.createElement('style');
style.textContent = `.btn-xs { padding: 0.1rem 0.4rem; font-size: 0.75rem; }`;
document.head.appendChild(style);

