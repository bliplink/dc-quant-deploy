/* OpenTradingCore shared, non-sensitive language preference.
 * SameSite cookie works across opentradingcore.com subdomains; legacy storage
 * keys remain mirrored for older deployed clients. No session data is stored.
 */
(function (global) {
  'use strict';
  var name = 'otc_language';
  var legacy = ['otc.lang', 'dc-trade-language', 'otc.tenant.lang'];
  var readCookie = function () {
    var cookie = document.cookie.split('; ');
    for (var i = 0; i < cookie.length; i++) {
      var item = cookie[i].split('=');
      if (item[0] === name) return decodeURIComponent(item.slice(1).join('='));
    }
    return null;
  };
  var normalize = function (value) {
    if (value === 'zh' || value === 'zh-CN' || value === 'zh_CN') return 'zh-CN';
    return value === 'en' || value === 'en-US' ? 'en' : null;
  };
  var stored = function () {
    try {
      for (var i = 0; i < legacy.length; i++) {
        var val = normalize(global.localStorage.getItem(legacy[i]));
        if (val) return val;
      }
    } catch (_) { /* Local storage may be disabled by the browser. */ }
    return null;
  };
  var last = null;
  var mirroring = false;
  function mirror(value) {
    mirroring = true;
    try {
      global.localStorage.setItem('otc.lang', value);
      global.localStorage.setItem('dc-trade-language', value === 'zh-CN' ? 'zh' : 'en');
      global.localStorage.setItem('otc.tenant.lang', value === 'zh-CN' ? 'zh' : 'en');
    } catch (_) { /* Cookie is independently sufficient. */ }
    finally { mirroring = false; }
  }
  function writeCookie(value) {
    var host = global.location.hostname.toLowerCase();
    var scope = host === 'opentradingcore.com' || /\.opentradingcore\.com$/.test(host)
      ? '; Domain=.opentradingcore.com' : '';
    var secure = global.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = name + '=' + encodeURIComponent(value)
      + '; Path=/; Max-Age=31536000; SameSite=Lax' + scope + secure;
  }
  function notify(value, source) {
    global.dispatchEvent(new CustomEvent('otc-language-change', {
      detail: { language: value, source: source }
    }));
  }
  function set(value) {
    var normalized = normalize(value);
    if (!normalized) return last || 'en';
    var changed = last !== normalized;
    last = normalized;
    writeCookie(normalized);
    mirror(normalized);
    if (changed) notify(normalized, 'local');
    return normalized;
  }
  function get() {
    return normalize(readCookie()) || stored() || 'en';
  }
  function sync() {
    var value = get();
    if (value !== last) {
      last = value;
      mirror(value);
      notify(value, 'external');
    }
    return value;
  }
  // Compatibility for older bundles that only write their own localStorage
  // key when a user chooses a language. Do not interfere with other keys.
  try {
    var originalSetItem = global.Storage.prototype.setItem;
    global.Storage.prototype.setItem = function (key, value) {
      var result = originalSetItem.call(this, key, value);
      if (!mirroring && this === global.localStorage && legacy.indexOf(String(key)) >= 0) {
        var next = normalize(String(value));
        if (next && next !== last) set(next);
      }
      return result;
    };
  } catch (_) { /* Some isolated browser contexts disallow prototype hooks. */ }

  global.OTCSharedLanguage = {
    get: get,
    set: set,
    normalize: normalize,
    app: function () { return get() === 'zh-CN' ? 'zh' : 'en'; },
    sync: sync
  };
  if (normalize(readCookie())) sync();
  else set(stored() || 'en');
  global.addEventListener('focus', sync);
  global.addEventListener('pageshow', sync);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) sync(); });
  // Older Tenant Web releases cannot react to new cross-origin cookies in an
  // already-open tab. Reopen that view only when the change came from another
  // page; switching language locally must never reload an unsent form.
  if (/^tenant\.opentradingcore\.com$/.test(global.location.hostname) ||
      global.location.port === '18092') {
    global.addEventListener('otc-language-change', function (event) {
      if (event.detail.source === 'external' && document.readyState === 'complete')
        global.location.reload();
    });
  }
})(window);
