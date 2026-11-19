/* keepalive.js — 页面保活 (v3)
   目的: 让 Android 上的浏览器页面在后台/小窗状态不被系统挂起,
        这样 Web Bluetooth 的 GATT 连接和保活帧都能持续。

   三个手段一起上:
   1) 静音 WAV 循环播放 —— Android 判定为"正在播放媒体", 不冻结页面
   2) Screen Wake Lock —— 尽量阻止熄屏
   3) Bluefy 专有的 setScreenDimEnabled(false)

   页面被切到后台再回来时, 重新拿一次 wake lock (系统会自动释放)。

   用法: 在 relay.html 的 </body> 前加一行
        <script src="keepalive.js"></script>
*/
(function () {
  var audio = null;
  var wakeLock = null;
  var started = false;

  function silentWavURL() {
    var sr = 8000, n = sr;               // 1 秒 8kHz 单声道 16bit 静音
    var buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    function ws(o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    ws(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    ws(36, 'data'); v.setUint32(40, n * 2, true);
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }

  function log(msg) {
    var b = document.getElementById('log-box');
    if (b) b.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg + '\n' + b.textContent;
  }

  async function acquireWakeLock() {
    try {
      if (navigator.wakeLock && !wakeLock) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', function () { wakeLock = null; });
      }
    } catch (e) { /* 不支持就算了, 静音音频那条兜着 */ }
  }

  async function start() {
    if (started) return;
    started = true;

    // 1) Bluefy 专属: 关掉自动熄屏
    try {
      if (navigator.bluetooth && typeof navigator.bluetooth.setScreenDimEnabled === 'function') {
        await navigator.bluetooth.setScreenDimEnabled(false);
      }
    } catch (e) { }

    // 2) 标准 Screen Wake Lock
    await acquireWakeLock();

    // 3) 静音音频循环 —— 主力手段
    try {
      if (!audio) {
        audio = new Audio(silentWavURL());
        audio.loop = true;
        audio.volume = 0.01;
      }
      await audio.play();
      log('🔇 静音保活已开 (页面不会被系统冻结)');
    } catch (e) {
      log('⚠️ 静音保活失败: ' + (e && e.message ? e.message : e));
    }
  }

  function stop() {
    try { if (audio) { audio.pause(); } } catch (e) { }
    try { if (wakeLock) { wakeLock.release(); wakeLock = null; } } catch (e) { }
    try {
      if (navigator.bluetooth && typeof navigator.bluetooth.setScreenDimEnabled === 'function') {
        navigator.bluetooth.setScreenDimEnabled(true);
      }
    } catch (e) { }
    started = false;
  }

  // 页面被冻结后恢复时, 重新拿保活
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      start();
    }
  });
  window.addEventListener('focus', start);
  window.addEventListener('pageshow', start);

  // 页面加载就开
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(start, 500);
  } else {
    window.addEventListener('DOMContentLoaded', function () { setTimeout(start, 500); });
  }

  // 暴露给控制台: keepalive.start() / keepalive.stop()
  window.keepalive = { start: start, stop: stop };
})();
