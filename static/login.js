var rawConfig = {
  sendCodeUrl: "/api/auth/send-code",
  verifyCodeUrl: "/api/auth/verify-code",
  verify2FAUrl: "/api/auth/verify-2fa",
  dashboardUrl: "/dashboard",
  authStatusUrl: "/api/auth/status"
};

var FLASK_PORT = window.FLASK_PORT || '5000';
function isUnresolved(v) { return typeof v === 'string' && v.indexOf('\u007b\u007b') !== -1; }
var apiBase = isUnresolved(rawConfig.sendCodeUrl) ? 'http://127.0.0.1:' + FLASK_PORT : '';
var config = {};
Object.keys(rawConfig).forEach(function(k) {
  config[k] = isUnresolved(rawConfig[k]) ? apiBase + rawConfig[k] : rawConfig[k];
});

var currentStateKey = null;
var currentPhone = null;
var sendInFlight = false;
var verifyInFlight = false;

function toStr(v) {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (typeof v === 'object') {
    if (v.message && typeof v.message === 'string') return v.message;
    if (v.error && typeof v.error === 'string') return v.error;
    if (v.detail && typeof v.detail === 'string') return v.detail;
    try { return JSON.stringify(v); } catch (e) { return ''; }
  }
  return '';
}

function showStatus(msg, type) {
  var el = document.getElementById('globalStatus');
  el.textContent = toStr(msg) || 'Something went wrong. Please try again.';
  el.className = 'status-message ' + type;
}

function goToStep(step) {
  document.querySelectorAll('.step').forEach(function(el) { el.classList.remove('active'); });
  if (step === 'phone') {
    document.getElementById('stepPhone').classList.add('active');
  } else if (step === 'code') {
    document.getElementById('stepCode').classList.add('active');
  } else if (step === '2fa') {
    document.getElementById('step2FA').classList.add('active');
  }
}

function extractError(err) {
  if (err instanceof Error) return err.message || 'Something went wrong.';
  return toStr(err) || 'Something went wrong.';
}

async function postJson(url, payload) {
  var response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload || {})
    });
  } catch (e) {
    throw { message: 'Network error. Check that the server is running.', status: 0 };
  }
  var data = {};
  try { data = await response.json(); } catch (e) { data = { error: 'Invalid server response' }; }
  if (!response.ok) {
    throw { message: toStr(data.error || data.message) || 'Request failed', status: response.status, data: data };
  }
  return data;
}

async function handleSendCode(e) {
  e.preventDefault();
  if (sendInFlight) return false;
  var phone = document.getElementById('phone').value.trim();
  if (!phone) { showStatus('Enter your phone number', 'error'); return false; }

  var btn = document.getElementById('sendCodeBtn');
  sendInFlight = true;
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';

  try {
    var data = await postJson(config.sendCodeUrl, { phone: phone });
    currentStateKey = data.state_key;
    currentPhone = phone;
    var hint = (data.delivery && typeof data.delivery === 'object') ? data.delivery : {};
    var hintMsg = toStr(hint.message) || 'Code sent';
    var hintText = toStr(hint.hint) || 'Check your Telegram app or SMS inbox.';
    var maskedPhone = phone.substring(0, 4) + '****' + phone.substring(phone.length - 2);
    document.getElementById('deliveryHint').innerHTML =
      '<strong>' + hintMsg.replace(/</g, '&lt;') + '</strong> to ' + maskedPhone + '<br>' +
      hintText.replace(/</g, '&lt;');
    goToStep('code');
    document.getElementById('code').focus();
  } catch (err) {
    var msg = extractError(err);
    if (err.status === 429) {
      msg = 'Too many requests. ' + msg;
    }
    if (err.data && err.data.retry_after) {
      msg += ' Try again in ' + err.data.retry_after + 's.';
    }
    showStatus(msg, 'error');
  } finally {
    sendInFlight = false;
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-paper-plane"></i> Send Code';
  }
  return false;
}

async function handleVerifyCode(e) {
  e.preventDefault();
  if (verifyInFlight) return false;
  var code = document.getElementById('code').value.trim();
  if (!code) { showStatus('Enter the verification code', 'error'); return false; }

  if (!currentStateKey) {
    showStatus('Your session expired. Please enter your phone number again.', 'error');
    goToStep('phone');
    return false;
  }

  var btn = document.getElementById('verifyCodeBtn');
  verifyInFlight = true;
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

  try {
    var data = await postJson(config.verifyCodeUrl, { state_key: currentStateKey, code: code });
    if (data.requires_2fa) {
      goToStep('2fa');
      document.getElementById('password').focus();
    } else if (data.success) {
      showStatus('Login successful! Redirecting...', 'success');
      setTimeout(function() { window.location.href = config.dashboardUrl; }, 1000);
    } else {
      showStatus(toStr(data.error) || 'Verification failed', 'error');
    }
  } catch (err) {
    var msg = extractError(err);
    if (err.status === 400 && msg.indexOf('expired') !== -1) {
      currentStateKey = null;
      currentPhone = null;
      showStatus('Your verification session expired. Please enter your phone number again.', 'error');
      goToStep('phone');
    } else {
      if (err.data && err.data.retry_after) {
        msg += ' Try again in ' + err.data.retry_after + 's.';
      }
      showStatus(msg, 'error');
    }
  } finally {
    verifyInFlight = false;
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-check"></i> Verify Code';
  }
  return false;
}

async function handleVerify2FA(e) {
  e.preventDefault();
  var password = document.getElementById('password').value;
  if (!password) { showStatus('Enter your 2FA password', 'error'); return false; }

  if (!currentStateKey) {
    showStatus('Your session expired. Please enter your phone number again.', 'error');
    goToStep('phone');
    return false;
  }

  var btn = document.getElementById('verify2FABtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

  try {
    var data = await postJson(config.verify2FAUrl, { state_key: currentStateKey, password: password });
    if (data.success) {
      showStatus('Login successful! Redirecting...', 'success');
      setTimeout(function() { window.location.href = config.dashboardUrl; }, 1000);
    } else {
      showStatus(toStr(data.error) || '2FA verification failed', 'error');
    }
  } catch (err) {
    var msg = extractError(err);
    if (err.status === 400 && msg.indexOf('expired') !== -1) {
      currentStateKey = null;
      currentPhone = null;
      showStatus('Your verification session expired. Please enter your phone number again.', 'error');
      goToStep('phone');
    } else {
      showStatus(msg || '2FA verification failed', 'error');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-shield-alt"></i> Verify Password';
  }
  return false;
}

document.addEventListener('DOMContentLoaded', function() {
  var phoneForm = document.getElementById('phoneForm');
  var codeForm = document.getElementById('codeForm');
  var twoFAForm = document.getElementById('twoFAForm');
  var backToPhone = document.getElementById('backToPhone');
  var backToCode = document.getElementById('backToCode');

  if (phoneForm) phoneForm.addEventListener('submit', handleSendCode);
  if (codeForm) codeForm.addEventListener('submit', handleVerifyCode);
  if (twoFAForm) twoFAForm.addEventListener('submit', handleVerify2FA);
  if (backToPhone) backToPhone.addEventListener('click', function() {
    currentStateKey = null;
    currentPhone = null;
    goToStep('phone');
  });
  if (backToCode) backToCode.addEventListener('click', function() {
    goToStep('code');
  });

  fetch(config.authStatusUrl).then(function(r) { return r.json(); }).then(function(data) {
    if (!data.telegram_configured) {
      showStatus('Telegram API is not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env.', 'info');
    }
  }).catch(function() {});
});
