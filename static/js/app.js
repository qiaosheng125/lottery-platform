function getOrCreateDeviceId() {
  return localStorage.getItem('lottery_device_id') || '';
}

function saveDeviceId(id) {
  localStorage.setItem('lottery_device_id', id);
}

function isValidDeviceId(id) {
  return !!id && id.length <= 20 && /^[A-Za-z0-9_-]+$/.test(id);
}

function clearStoredDevice() {
  localStorage.removeItem('lottery_device_id');
}

async function registerDeviceAndCheckName() {
  const deviceId = getOrCreateDeviceId();
  if (!deviceId || !isValidDeviceId(deviceId)) {
    clearStoredDevice();
    showDeviceIdPrompt(deviceId ? '\u8bbe\u5907\u6807\u8bc6\u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u8fde\u5b57\u7b26\u548c\u4e0b\u5212\u7ebf\uff0c\u4e14\u957f\u5ea6\u4e0d\u80fd\u8d85\u8fc7 20\u3002' : '');
    return;
  }

  try {
    const res = await fetch('/api/device/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: deviceId,
        client_info: { client_type: 'web' },
      }),
    });
    const data = await res.json();
    if (data && data.success && data.device) {
      return;
    }
    if (data && data.error) {
      showToast(data.error, 'warning');
    }
  } catch (e) {
  }
}

function showDeviceIdPrompt(message = '') {
  const existing = document.getElementById('device-id-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'device-id-modal';
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:#fff;border-radius:8px;padding:24px;width:320px;max-width:90vw;">
      <h5 class="mb-3"><i class="bi bi-cpu"></i> \u9996\u6b21\u4f7f\u7528\uff1a\u8bbe\u7f6e\u63a5\u5355\u8bbe\u5907\u6807\u8bc6</h5>
      <p class="text-muted small mb-3">\u8bf7\u8f93\u5165\u8bbe\u5907\u6807\u8bc6\uff08\u5982 D01\uff09\u3002\u7f51\u9875\u7aef\u540e\u7eed\u5c06\u53ea\u4f7f\u7528\u8fd9\u4e00\u4e2a\u503c\uff0c\u4e0d\u518d\u5355\u72ec\u8981\u6c42\u8bbe\u7f6e\u8bbe\u5907\u540d\u3002</p>
      ${message ? `<div class="alert alert-warning py-2 small">${message}</div>` : ''}
      <input type="text" id="device-id-input" class="form-control mb-3"
             placeholder="\u8bf7\u8f93\u5165\u8bbe\u5907\u6807\u8bc6" maxlength="20" autofocus>
      <div class="d-flex gap-2">
        <button class="btn btn-secondary" onclick="closeDeviceIdModal()">\u7a0d\u540e\u8bbe\u7f6e</button>
        <button class="btn btn-primary flex-grow-1" onclick="submitDeviceId()">\u786e\u8ba4\u4fdd\u5b58</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  document.getElementById('device-id-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitDeviceId();
  });
}

function closeDeviceIdModal() {
  const modal = document.getElementById('device-id-modal');
  if (modal) modal.remove();
}

async function submitDeviceId() {
  const input = document.getElementById('device-id-input');
  const id = input ? input.value.trim() : '';
  if (!id) {
    input && input.classList.add('is-invalid');
    return;
  }
  if (!isValidDeviceId(id)) {
    input && input.classList.add('is-invalid');
    showToast('\u8bbe\u5907\u6807\u8bc6\u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u8fde\u5b57\u7b26\u548c\u4e0b\u5212\u7ebf\uff0c\u4e14\u957f\u5ea6\u4e0d\u80fd\u8d85\u8fc7 20\u3002', 'warning');
    return;
  }

  saveDeviceId(id);

  const modal = document.getElementById('device-id-modal');
  if (modal) modal.remove();

  window.location.reload();
}

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

const style = document.createElement('style');
style.textContent = `.btn-xs { padding: 0.1rem 0.4rem; font-size: 0.75rem; }`;
document.head.appendChild(style);
